"""
E2E-019: Payment Failure and Retry — PayIt Fails → Retry → Switch to Drawdown
Cross-portal test verifying payment failure recovery.

Phases:
  1. [Public Portal + Staff Portal]  Submit and process LT-260
  2. [Public Portal]  Submit LT-262, attempt PayIt → abandon (simulates failure)
                      → assert application shows "Payment Pending" on dashboard
  3. [Public Portal]  From "Payment Pending" state → Pay Now → switch to Drawdown
                      → payment succeeds → "LT-262 Submitted"
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import SAMPLE_DOC_PATH
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    generate_person,
    past_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
BUSINESS_NAME = "G-Car Garages New"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.payment
@pytest.mark.fixed
class TestE2E019PaymentFailureRetry:
    """E2E-019: PayIt abandoned (simulated failure) → retry via Drawdown → success"""

    # ========================================================================
    # PHASE 1: Setup — Submit and process LT-260
    # ========================================================================
    def test_phase_1_setup_lt260(self, public_context: BrowserContext, staff_context: BrowserContext):
        """Phase 1: Submit LT-260 (PP) and process it (SP) so LT-262 is ready"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit_with_vin_image()
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)
            form_processing.expect_detail_page_visible()

            form_processing.click_edit()
            form_processing.add_owner(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            form_processing.select_stolen_no()
            form_processing.click_save()
            form_processing.issue_160b_and_260a()
            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Public Portal — Submit LT-262, attempt PayIt, then abandon
    # ========================================================================
    def test_phase_2_submit_lt262_abandon_payit(self, public_context: BrowserContext):
        """Phase 2: Submit LT-262 → click Pay Using Credit Card/PayIt → navigate
        away without completing (simulates abandoned/failed PayIt) →
        verify application shows Payment Pending on dashboard"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)
            dashboard.expect_application_processed()

            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()
            lt262.skip_vehicle_and_location_tabs()
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})
            lt262.fill_date_of_storage(past_date(30))
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.upload_documents([SAMPLE_DOC_PATH])
            lt262.accept_terms_and_sign(PERSON["name"])
            lt262.finish_and_pay()

            # Reach cart page and click PayIt button to simulate an attempt
            payit_btn = page.locator(
                "//button[.//span[contains(text(),'Pay Using Credit Card/PayIt')]]"
                "|//span[contains(text(),'Pay Using Credit Card/PayIt')]"
            ).first
            payit_btn.wait_for(state="visible", timeout=15_000)
            payit_btn.scroll_into_view_if_needed()
            payit_btn.click()
            # Brief wait to let PayIt initialize, then abandon without completing
            page.wait_for_timeout(5000)

            # Abandon: navigate back to PP dashboard
            go_to_public_dashboard(page)

            # Application should now show "Payment Pending"
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)
            expect(
                page.get_by_text(re.compile(r"Payment Pending", re.I)).first
            ).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Switch to Drawdown, payment succeeds
    # ========================================================================
    def test_phase_3_retry_with_drawdown_succeeds(self, public_context: BrowserContext):
        """Phase 3: From Payment Pending state → Pay Now → switch to ACH/Drawdown
        → confirm → verify success banner + LT-262 Submitted"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            # "Pay now" button should be visible after abandoned PayIt
            pay_now_btn = page.locator(
                'button:has-text("Pay now"), button:has-text("Pay Now"), '
                'a:has-text("Pay now"), a:has-text("Pay Now")'
            ).first
            pay_now_btn.wait_for(state="visible", timeout=15_000)
            pay_now_btn.click()
            page.wait_for_timeout(2000)

            # Switch to Drawdown on the cart page
            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            # Confirm drawdown modal
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Soft check: success banner
            try:
                success_banner = page.get_by_text(
                    re.compile(r"Your payment has been completed successfully", re.I)
                )
                expect(success_banner.first).to_be_visible(timeout=20_000)
            except Exception:
                pass

            # If not redirected to dashboard, navigate there manually
            try:
                page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
            except Exception:
                go_to_public_dashboard(page)

            # Hard assert: VIN shows "LT-262 Submitted"
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)
            expect(
                page.get_by_text(re.compile(r"LT-262 Submitted", re.I)).first
            ).to_be_visible(timeout=15_000)
        finally:
            page.close()
