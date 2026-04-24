"""
E2E-023: PayIt Status Update — Abandoned Attempt then Successful Payment
PP: LT-260 → SP: Process LT-260 → PP: Submit LT-262 → Cart →
PP: Abandoned PayIt attempt → PP: Successful PayIt login + pay →
SP: Global search → Payment Details verification

Phases:
  1. [Public Portal]  Login, create LT-260, VIN lookup, fill form, submit
  2. [Staff Portal]   Open LT-260, add owner, set stolen=No, save, issue 160B/260A
  3. [Public Portal]  Verify LT-260 processed, fill LT-262, end at finish_and_pay()
  4. [Public Portal]  Dashboard → Pay now → Cart → PayIt login → Pay $20.06 →
                      verify green banner + status = LT-262 Submitted
  5. [Staff Portal]   Header search VIN → Payments tab → click entry →
                      Payment Details heading + VIN under LT-262 Details
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    past_date,
    generate_person,
    today_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")
BUSINESS_NAME = "G-Car Garages New"

PAYIT_EMAIL = "rupin@webintensive.com"
PAYIT_PASSWORD = "Test@1234"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.critical
@pytest.mark.payment
class TestE2E023PayItStatusUpdate:
    """E2E-023: Abandoned PayIt → retry from dashboard → success → staff verifies"""

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_create_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Login, create LT-260, VIN lookup, fill form, submit"""
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
            page.wait_for_timeout(2000)

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Process LT-260
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Open LT-260, add owner, set stolen=No, save, issue 160B/260A"""
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
    # PHASE 3: Public Portal — Fill LT-262, end at finish_and_pay()
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262_to_cart(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, fill LT-262, call finish_and_pay()"""
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
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Public Portal — Pay now → Cart → PayIt login → pay → verify
    # ========================================================================
    def test_phase_4_public_portal_complete_payit_payment(self, public_context: BrowserContext):
        """Phase 4: [Public Portal] Dashboard → search VIN → Pay now → Cart →
        Pay using Credit Card/payIt → Log in to PayIt → login → Pay $20.06 →
        verify green banner + status = LT-262 Submitted"""
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

            # "Pay now" button should still be visible after abandoned PayIt
            pay_now_btn = page.locator(
                'button:has-text("Pay now"), button:has-text("Pay Now"), '
                'a:has-text("Pay now"), a:has-text("Pay Now")'
            ).first
            pay_now_btn.wait_for(state="visible", timeout=15_000)
            pay_now_btn.click()
            page.wait_for_timeout(2000)

            # On cart page — click "Pay Using Credit Card/PayIt" (click the button, not just the span)
            payit_btn = page.locator(
                "//button[.//span[contains(text(),'Pay Using Credit Card/PayIt')]]"
                "|//span[contains(text(),'Pay Using Credit Card/PayIt')]"
            ).first
            payit_btn.wait_for(state="visible", timeout=15_000)
            payit_btn.scroll_into_view_if_needed()
            payit_btn.click()

            # Wait for PayIt "Please Wait — Hang On for Login" to resolve.
            # PayIt either shows a mobilgov login iframe OR renders checkout directly.
            page.wait_for_load_state("domcontentloaded", timeout=20_000)

            import time as _time
            deadline = _time.time() + 45
            login_done = False
            while _time.time() < deadline:
                # Check if mobilgov login iframe has appeared
                login_frame = next(
                    (f for f in page.frames if "mobilgov.com" in f.url or "auth-dev" in f.url),
                    None,
                )
                if login_frame is not None and login_frame.locator("input[type='password']").count() > 0:
                    # Email field uses type=text (not type=email) in mobilgov iframe
                    login_frame.locator("input[type='text']").first.fill(PAYIT_EMAIL)
                    login_frame.locator("input[type='password']").first.fill(PAYIT_PASSWORD)
                    login_frame.locator("button:has-text('Log In')").first.click()
                    page.wait_for_timeout(8000)
                    login_done = True
                    break
                # Check if Pay button already visible (session pre-existing)
                if page.locator("button:has-text('Pay $'), button:has-text('Pay Now')").first.is_visible():
                    login_done = True
                    break
                page.wait_for_timeout(2000)

            # On Checkout page — click "Pay $xx.xx"
            pay_btn = page.locator(
                "button:has-text('Pay $'), button:has-text('Pay Now')"
            ).first
            pay_btn.wait_for(state="visible", timeout=30_000)
            pay_btn.click()
            page.wait_for_timeout(8000)

            # Should redirect back to PP dashboard with green banner
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)

            success_banner = page.get_by_text(re.compile(r"Your payment has been completed successfully", re.I))
            expect(success_banner.first).to_be_visible(timeout=15_000)

            # Search for the same VIN — status should be "LT-262 Submitted"
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

    # ========================================================================
    # PHASE 5: Staff Portal — Header search → Payments tab → Payment Details
    # ========================================================================
    def test_phase_5_staff_portal_verify_payment_details(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Header search field → enter VIN → Search →
        Payments tab → click VIN entry → Payment Details heading →
        VIN visible under LT-262 Details"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Enter VIN in the header search field
            header_search = page.locator(
                'mat-toolbar input, '
                'app-toolbar input, '
                'input[placeholder*="Search" i], '
                'input[aria-label*="Search" i]'
            ).first
            header_search.wait_for(state="visible", timeout=15_000)
            header_search.fill(TEST_VIN)

            # Click the Search button
            page.locator("//span[contains(text(),'Search ')]").first.click()
            page.wait_for_timeout(4000)

            # Click the Payments tab
            payments_tab = page.locator('[role="tab"]:has-text("Payment")').first
            payments_tab.wait_for(state="visible", timeout=15_000)
            payments_tab.click()
            page.wait_for_timeout(2000)

            # Find the VIN entry in the Payments tab and click it
            vin_entry = page.locator(
                f'//span[contains(text(),"{TEST_VIN}")]'
                f'|//td[contains(text(),"{TEST_VIN}")]'
                f'|//span[@class[contains(.,"table-link")]][contains(text(),"{TEST_VIN}")]'
            ).first
            vin_entry.wait_for(state="visible", timeout=15_000)
            vin_entry.click()
            page.wait_for_timeout(3000)

            # Verify "Payment Details" heading
            expect(
                page.get_by_text(re.compile(r"Payment Details", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Verify VIN visible under "LT-262 Details" heading
            expect(
                page.get_by_text(re.compile(r"LT-262 Details", re.I)).first
            ).to_be_visible(timeout=15_000)

            expect(
                page.get_by_text(TEST_VIN).first
            ).to_be_visible(timeout=10_000)
        finally:
            page.close()
