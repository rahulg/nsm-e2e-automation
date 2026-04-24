"""
E2E-031: LT-264B Hearing Notification to Requestor
Owner requests hearing → Staff issues LT-264B → Requestor notified.

Phases:
  1. [Public Portal]  Login, create LT-260, VIN lookup, fill form, submit
  2. [Staff Portal]   Process LT-260 — add owner, stolen=No, issue 160B/260A
  3. [Public Portal]  Submit LT-262 with lien/charges/docs, pay via drawdown
  4. [Staff Portal]   Open LT-262, verify details, CHECK DCI → Issue LT-264
  5. [Staff Portal]   Track LT-264 delivery → redirect to REVIEW COURT HEARINGS
  6. [Staff Portal]   LT-262 Court Hearing tab → search VIN → View Correspondence → verify LT-264B
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
@pytest.mark.high
class TestE2E031Lt264bHearingNotification:
    """E2E-031: LT-264B — owner hearing request → staff issues → requestor notified"""

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

            # Enter VIN (no VIN lookup — modal will appear at submit)
            lt260.enter_vin(TEST_VIN)

            # Fill vehicle details
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])

            # Fill authorized person (Tab 2)
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Accept terms and sign (Tab 3)
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            # Submit — VIN image modal should appear now that webdriver flag is hidden
            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)

            # Verify redirect back to dashboard
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
    # PHASE 5: Staff Portal — Track LT-264 → redirect to REVIEW COURT HEARINGS
    # ========================================================================
    def test_phase_5_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Track LT-264 — log receipt + hearing checkbox → Save → redirect to REVIEW COURT HEARINGS"""
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

            # Go to TRACK LT-264 tab
            lt262_listing.click_track_lt264_tab()
            page.wait_for_timeout(2000)

            # Check checkbox under "Log Receipt of Signed LT-264 Letters"
            log_receipt_cb = page.locator('mat-checkbox').first
            if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
                log_receipt_cb.locator("label").click()
                page.wait_for_timeout(1000)

            # Second checkbox — "Select recipients requesting judicial hearing"
            hearing_cb = page.locator('mat-checkbox').nth(1)
            hearing_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
                hearing_cb.locator("label").click()
                page.wait_for_timeout(500)

            # Click Save
            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=15_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(2000)

            # Confirm modal — click Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Wait for redirect to REVIEW COURT HEARINGS — wait for its unique content
            possessory_text = page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
            possessory_text.wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Court Hearing tab → open record → verify LT-264B
    # ========================================================================
    def test_phase_6_staff_portal_verify_lt264b_correspondence(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] LT-262 → Court Hearing tab → search VIN → open record
        → View Correspondence/Documents → Correspondence History modal → LT-264B entry"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → Court Hearing tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.court_hearing_tab.click()
            page.wait_for_load_state("networkidle")

            # Search for VIN using filters
            lt262_listing.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            lt262_listing.select_application(0)
            page.wait_for_timeout(2000)

            # Wait for LT-264B to be generated before opening correspondence
            page.wait_for_timeout(5000)

            # Click "View Correspondence/Documents" link
            view_corr = page.locator('//span[contains(text(),"View Correspondence/Documents")]').first
            view_corr.wait_for(state="visible", timeout=15_000)
            view_corr.click()
            page.wait_for_timeout(1500)

            # Verify "Correspondence History" modal is displayed
            modal = page.locator('mat-dialog-container').first
            expect(modal).to_be_visible(timeout=10_000)
            expect(page.get_by_text(re.compile(r"Correspondence History", re.I)).first).to_be_visible(timeout=10_000)

            # Scroll to bottom of modal — LT-264B entry appears at the end of the list
            modal_content = page.locator('mat-dialog-container mat-dialog-content, mat-dialog-container .mat-dialog-content').first
            try:
                modal_content.evaluate("el => el.scrollTo(0, el.scrollHeight)")
            except Exception:
                modal.evaluate("el => el.scrollTo(0, el.scrollHeight)")
            page.wait_for_timeout(1000)

            # Verify LT-264B entry is present in the modal
            lt264b_entry = page.get_by_text(re.compile(r"LT-264B", re.I)).first
            expect(lt264b_entry).to_be_visible(timeout=10_000)
        finally:
            page.close()
