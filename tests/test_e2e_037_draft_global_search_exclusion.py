"""
E2E-037: Draft LT-262 Global Search Exclusion
Verifies that a saved LT-262 Draft is EXCLUDED from Staff Portal Global Search (LT-262 tab empty),
and after completing and paying the LT-262 it shows "LT-262 Submitted" in global search.

Phases:
  1. [Public Portal]  Submit LT-260
  2. [Staff Portal]   Process LT-260 (add owner, stolen=No, issue 160B/260A)
  3. [Public Portal]  Start LT-262, fill through Tab C, Save as Draft → confirm → dashboard
  4. [Staff Portal]   Header Global Search → LT-260 tab = "LT-260 Processed";
                      LT-262 tab = "LT-262 Draft"
  5. [Public Portal]  Search VIN → status "LT-262 Draft" → Submit LT-262 → Next x3 →
                      complete remaining tabs → pay
  6. [Staff Portal]   Header Global Search → LT-260 tab = "LT-260 Processed";
                      LT-262 tab = "LT-262 Submitted"
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


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E037DraftGlobalSearchExclusion:
    """E2E-037: LT-262 Draft → global search shows Draft; after payment shows Submitted"""

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_create_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Login, create LT-260, VIN lookup, fill form, submit"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Select business (if multi-business user)
            dashboard.select_business(BUSINESS_NAME)

            # Click "Start here" to create LT-260
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

            # Navigate to LT-260 listing → To Process tab
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()

            # Search for our specific VIN
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)

            # Verify detail page loaded
            form_processing.expect_detail_page_visible()

            # Click Edit
            form_processing.click_edit()

            # Add owner under "Owner(s) Check"
            form_processing.add_owner(
                PERSON["name"], ADDRESS["street"], ADDRESS["zip"]
            )

            # Select STOLEN = No
            form_processing.select_stolen_no()

            # Save
            form_processing.click_save()

            # Issue 160B and 260A
            form_processing.issue_160b_and_260a()

            # Verify success toast and Processed status
            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Start LT-262, fill through Tab C, Save as Draft
    # ========================================================================
    def test_phase_3_public_portal_save_lt262_draft(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, start LT-262, fill through Tab C,
        Save as Draft → confirm modal → green banner → dashboard"""
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

            # Click "Submit LT-262"
            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()

            # Skip pre-filled tabs A (Vehicle) and B (Location) via Next
            lt262.skip_vehicle_and_location_tabs()

            # Fill Tab C — lien charges (advances to D via Next)
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})

            # Click Save as Draft
            save_draft_btn = page.locator('//button[contains(text()," Save as Draft ")]').first
            save_draft_btn.wait_for(state="visible", timeout=10_000)
            save_draft_btn.click()
            page.wait_for_timeout(1000)

            # Confirm modal → Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(2000)

            # Verify green success banner
            success_banner = page.get_by_text(re.compile(r"draft|saved|success", re.I)).first
            expect(success_banner).to_be_visible(timeout=15_000)

            # Verify redirect back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Global Search: LT-260 Processed, LT-262 Draft
    # ========================================================================
    def test_phase_4_staff_portal_global_search_draft(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Header Global Search → LT-260 tab = 'LT-260 Processed';
        LT-262 tab = empty (Draft is EXCLUDED from staff global search)"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Navigate to LT-260 listing first so the header search field is fully rendered
            staff_dashboard = StaffDashboardPage(page)
            staff_dashboard.navigate_to_lt260_listing()
            page.wait_for_timeout(1000)

            # Enter VIN in header search field
            header_search = page.locator(
                "mat-toolbar input, app-toolbar input, "
                "input[placeholder*='Search' i], input[aria-label*='Search' i]"
            ).first
            header_search.wait_for(state="visible", timeout=15_000)
            header_search.fill(TEST_VIN)
            page.locator("//span[contains(text(),'Search ')]").first.click()
            page.wait_for_timeout(2000)

            # Verify LT-260 tab shows "LT-260 Processed"
            page.locator('[role="tab"]:has-text("LT-260")').first.click()
            page.wait_for_timeout(1000)
            expect(
                page.get_by_text(re.compile(r"LT-260 Processed", re.I)).first
            ).to_be_visible(timeout=10_000)

            # Switch to LT-262 tab — draft is excluded, only column headers visible (no data rows)
            page.locator('[role="tab"]:has-text("LT-262")').first.click()
            page.wait_for_timeout(2000)
            expect(page.locator("mat-row")).to_have_count(0, timeout=5_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Resume draft LT-262, complete and pay
    # ========================================================================
    def test_phase_5_public_portal_complete_lt262(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Search VIN → status 'LT-262 Draft' → Submit LT-262 →
        Next x3 (skip Tabs A/B/C) → complete remaining tabs → pay"""
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

            # Verify status is "LT-262 Draft"
            expect(
                page.get_by_text(re.compile(r"LT-262 Draft", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Click "Submit LT-262" to resume the draft
            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()

            # Click Next 3 times to skip pre-filled tabs A, B, C
            for _ in range(3):
                next_btn = page.locator('button:has-text("Next")').first
                next_btn.wait_for(state="visible", timeout=10_000)
                next_btn.scroll_into_view_if_needed()
                next_btn.click()
                page.wait_for_timeout(1000)

            # Fill Tab D — date of storage (advances to E via Next)
            lt262.fill_date_of_storage(past_date(30))

            # Fill Tab E — person authorizing storage
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Fill Additional Details
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Upload supporting documents
            lt262.upload_documents([SAMPLE_DOC_PATH])

            # Accept terms and sign
            lt262.accept_terms_and_sign(PERSON["name"])

            # Finish and pay
            lt262.finish_and_pay()

            # Click "Pay Using ACH/Drawdown"
            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=15_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            # Confirm drawdown modal → Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=15_000)

            # Verify redirect to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Global Search: LT-260 Processed, LT-262 Submitted
    # ========================================================================
    def test_phase_6_staff_portal_global_search_submitted(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Header Global Search → LT-260 tab = 'LT-260 Processed';
        LT-262 tab = 'LT-262 Submitted'"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Navigate to LT-260 listing first so the header search field is fully rendered
            staff_dashboard = StaffDashboardPage(page)
            staff_dashboard.navigate_to_lt260_listing()
            page.wait_for_timeout(1000)

            # Enter VIN in header search field
            header_search = page.locator(
                "mat-toolbar input, app-toolbar input, "
                "input[placeholder*='Search' i], input[aria-label*='Search' i]"
            ).first
            header_search.wait_for(state="visible", timeout=15_000)
            header_search.fill(TEST_VIN)
            page.locator("//span[contains(text(),'Search ')]").first.click()
            page.wait_for_timeout(2000)

            # Verify LT-260 tab shows "LT-260 Processed"
            page.locator('[role="tab"]:has-text("LT-260")').first.click()
            page.wait_for_timeout(1000)
            expect(
                page.get_by_text(re.compile(r"LT-260 Processed", re.I)).first
            ).to_be_visible(timeout=10_000)

            # Switch to LT-262 tab and verify Submitted status
            page.locator('[role="tab"]:has-text("LT-262")').first.click()
            page.wait_for_timeout(1000)
            expect(
                page.get_by_text(re.compile(r"LT-262 Submitted", re.I)).first
            ).to_be_visible(timeout=10_000)
        finally:
            page.close()
