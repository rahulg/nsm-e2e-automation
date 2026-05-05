"""
E2E-027: Case Status — Global Search Verification
Verifies status transitions are reflected in the Staff Portal header Global Search
at key points through the LT-260 → LT-262 → LT-264 → Court Hearing lifecycle.

Phases:
  1. [Public Portal]  Submit LT-260
  2. [Staff Portal]   Global Search → LT-260 Submitted →
                      Process LT-260 →
                      Global Search → LT-260 Processed
  3. [Public Portal]  Submit LT-262 with payment
  4. [Staff Portal]   Global Search → LT-262 Submitted →
                      Process LT-262 / Issue LT-264 →
                      Global Search → Aging
  5. [Staff Portal]   Track LT-264 → Save → Confirm →
                      Global Search → Court Hearing → open detail → REVIEW COURT HEARINGS tab →
                      Possessory Lien → Save → Confirm →
                      Global Search → LT-262 Processed
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
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def global_search_verify_status(page, vin: str, tab_name: str, expected_status: str):
    """Header search → enter VIN → Search → click tab → verify status in row."""
    header_search = page.locator(
        "mat-toolbar input, app-toolbar input, "
        "input[placeholder*='Search' i], input[aria-label*='Search' i]"
    ).first
    header_search.wait_for(state="visible", timeout=15_000)
    header_search.fill(vin)
    page.locator("//span[contains(text(),'Search ')]").first.click()
    page.wait_for_timeout(2000)

    page.locator(f'[role="tab"]:has-text("{tab_name}")').first.click()
    page.wait_for_timeout(1000)

    expect(
        page.get_by_text(re.compile(re.escape(expected_status), re.I)).first
    ).to_be_visible(timeout=10_000)


def global_search_open_detail_and_tab(page, vin: str, tab_name: str, expected_status: str, detail_tab: str):
    """Header search → verify status → click VIN entry → open detail → click detail_tab."""
    global_search_verify_status(page, vin, tab_name, expected_status)

    vin_entry = page.locator(
        f"//span[contains(text(),'{vin}')] | //td[contains(text(),'{vin}')]"
    ).first
    vin_entry.wait_for(state="visible", timeout=10_000)
    vin_entry.click()
    page.wait_for_timeout(2000)

    detail = page.locator(f'[role="tab"]:has-text("{detail_tab}")').first
    detail.wait_for(state="visible", timeout=15_000)
    detail.click()
    page.wait_for_timeout(2000)


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
class TestE2E027CaseStatusGlobalSearch:
    """E2E-027: Global Search reflects correct status at each lifecycle transition"""

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
    # PHASE 2: Staff Portal — Global Search (Submitted) → Process → Global Search (Processed)
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal]
        Global Search → LT-260 tab → status=LT-260 Submitted →
        Process LT-260 (add owner, stolen=No, issue 160B/260A) →
        Global Search → LT-260 tab → status=LT-260 Processed
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ── Global Search: verify LT-260 Submitted ──
            global_search_verify_status(page, TEST_VIN, "LT-260", "LT-260 Submitted")

            # ── Navigate back to staff dashboard and process LT-260 ──
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

            # ── Global Search: verify LT-260 Processed ──
            global_search_verify_status(page, TEST_VIN, "LT-260", "LT-260 Processed")
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
    # PHASE 4: Staff Portal — Global Search (Submitted) → Issue LT-264 → Global Search (Aging)
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal]
        Global Search → LT-262 tab → status=LT-262 Submitted →
        Process LT-262, issue LT-264 →
        Global Search → LT-262 tab → status=Aging
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ── Global Search: verify LT-262 Submitted ──
            global_search_verify_status(page, TEST_VIN, "LT-262", "LT-262 Submitted")

            # ── Navigate back and process LT-262 ──
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

            # ── Global Search: verify Aging ──
            global_search_verify_status(page, TEST_VIN, "LT-262", "Aging")
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Track LT-264 → Court Hearing → Possessory Lien
    # ========================================================================
    def test_phase_5_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Track LT-264 → Save → Confirm →
        Global Search → LT-262 tab → Court Hearing → open detail → REVIEW COURT HEARINGS tab →
        Possessory Lien checkbox → Save → Confirm →
        Global Search → LT-262 tab → LT-262 Processed
        """
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

            # Wait for redirect to REVIEW COURT HEARINGS — wait for its unique content
            possessory_text = page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
            possessory_text.wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(2000)

            # ── Global Search: verify Court Hearing → open detail → REVIEW COURT HEARINGS tab ──
            global_search_open_detail_and_tab(
                page, TEST_VIN, "LT-262", "Court Hearing", "REVIEW COURT HEARINGS"
            )

            # Check "Judgment in action of Possessory Lien" checkbox
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

            ok_btn = page.locator("//span[contains(text(),'OK')]").first
            ok_btn.wait_for(state="visible", timeout=10_000)
            ok_btn.click()
            page.wait_for_timeout(2000)

            # ── Global Search: verify LT-262 Processed ──
            global_search_verify_status(page, TEST_VIN, "LT-262", "LT-262 Processed")
        finally:
            page.close()
