"""
E2E-020: Paper Form — Relaxed Date Validation (Private Sale)
Full lifecycle via public portal (LT-260 → LT-262) then staff enters paper LT-263
with a private sale date within the next 15 days (paper forms have no date restrictions).

Phases:
  1. [Public Portal]  Login, create LT-260, VIN lookup, fill form, submit
  2. [Staff Portal]   Open LT-260, add owner, set stolen=No, issue 160B/260A
  3. [Public Portal]  Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay
  4. [Staff Portal]   Open LT-262, verify details, CHECK DCI → Issue LT-264
  5. [Staff Portal]   Track LT-264 delivery, verify court hearings status
  6. [Staff Portal]   LT-263 Add from Paper → private sale, date within next 15 days → Submit → Issue
  7. [Staff Portal]   Sold listing → search VIN → View Correspondence → LT-265 entry
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import STANDARD_SALE_DATA
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    past_date,
    future_date,
    generate_person,
    today_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.public_portal.shopping_cart_page import ShoppingCartPage
from src.pages.public_portal.payment_page import PaymentPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage
from src.pages.staff_portal.sold_listing_page import SoldListingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")
BUSINESS_NAME = "G-Car Garages New"

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
@pytest.mark.medium
@pytest.mark.paper_form
class TestE2E020PaperFormRelaxedDates:
    """E2E-020: Full lifecycle — paper LT-263 with private sale date < 1 month (no date restrictions)"""

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
    # PHASE 2: Staff Portal — Verify LT-260 processing
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

            form_processing.add_owner(
                PERSON["name"], ADDRESS["street"], ADDRESS["zip"]
            )

            form_processing.select_stolen_no()

            form_processing.click_save()

            form_processing.issue_160b_and_260a()

            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay"""
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

            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=15_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=15_000)

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Process LT-262 → Issue LT-264
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Open LT-262, verify details, CHECK DCI → Issue LT-264"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()

            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            lt262_listing.verify_lien_details_visible()

            lt262_listing.verify_owner_details_visible()

            lt262_listing.issue_lt264()

            success_banner = page.get_by_text("The form has been issued successfully.")
            expect(success_banner).to_be_visible(timeout=15_000)

            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Track LT-264, verify court hearings
    # ========================================================================
    def test_phase_5_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Track LT-264 — log receipt, hearing decision"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_aging_tab()
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.court_hearing_tab.click()
                page.wait_for_load_state("networkidle")
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            lt262_listing.click_track_lt264_tab()
            page.wait_for_timeout(2000)

            log_receipt_cb = page.locator('mat-checkbox').first
            if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
                log_receipt_cb.locator("label").click()
                page.wait_for_timeout(1000)

            hearing_cb = page.locator('mat-checkbox').nth(1)
            hearing_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
                hearing_cb.locator("label").click()
                page.wait_for_timeout(500)

            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=15_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            possessory_text = page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
            possessory_text.wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(2000)

            possessory_cb = page.locator('mat-checkbox').first
            possessory_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
                possessory_cb.locator("label").click()
                page.wait_for_timeout(1000)

            save_btn2 = page.locator('button:has-text("Save")').first
            save_btn2.wait_for(state="visible", timeout=15_000)
            save_btn2.scroll_into_view_if_needed()
            save_btn2.click()
            page.wait_for_timeout(2000)

            yes_btn2 = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn2.wait_for(state="visible", timeout=10_000)
            yes_btn2.click()
            page.wait_for_timeout(3000)

            success_banner = page.get_by_text(re.compile(r"success", re.I)).first
            expect(success_banner).to_be_visible(timeout=15_000)

            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=15_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            waiting_msg = page.get_by_text("Waiting for the requester to submit LT-263.")
            expect(waiting_msg).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — LT-263 Add from Paper → private sale, next 15 days
    # ========================================================================
    def test_phase_6_staff_portal_add_paper_lt263(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] LT-263 listing → Add from Paper → modal (VIN + Next) →
        Vehicle Sale Information: TYPE OF SALE=Private, SALE DATE (weekday within 15 days),
        Lien Amount, Lien For=LABOR → Submit → confirm (Yes) → Issue modal → Issue → OK.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            paper_form = PaperFormPage(page)

            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_add_from_paper()

            paper_form.fill_modal_vin_and_next(TEST_VIN)

            # Pick the first weekday within the next 15 days
            sale_dt = datetime.now() + timedelta(days=7)
            if sale_dt.weekday() == 5:  # Saturday → Monday
                sale_dt += timedelta(days=2)
            elif sale_dt.weekday() == 6:  # Sunday → Monday
                sale_dt += timedelta(days=1)

            paper_form.fill_lt263_sale_details(
                sale_type="private",
                sale_date=sale_dt.strftime("%Y-%m-%d"),
                lien_amount=STANDARD_SALE_DATA["lien_amount"],
            )

            paper_form.submit_paper_lt263()
        finally:
            page.close()

    # ========================================================================
    # PHASE 7: Staff Portal — Sold listing → search VIN → View Correspondence → LT-265
    # ========================================================================
    def test_phase_7_staff_portal_verify_sold_lt265(self, staff_context: BrowserContext):
        """Phase 7: [Staff Portal] Sold listing → search VIN → click → status=Processed →
        View Correspondence/Documents → Correspondence History modal → LT-265 entry visible.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            sold_listing = SoldListingPage(page)

            staff_dashboard.navigate_to_sold()
            sold_listing.search_by_vin(TEST_VIN)
            sold_listing.expect_applications_visible()
            sold_listing.select_application(0)

            expect(
                page.get_by_text(re.compile(r"Processed", re.I)).first
            ).to_be_visible(timeout=15_000)

            sold_listing.verify_lt265_in_correspondence()
        finally:
            page.close()
