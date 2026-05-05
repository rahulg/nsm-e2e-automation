"""
E2E-030: LT-264A Issuance After Aging Period
Full lifecycle to reach Aging state, then verify LT-264A issuance.

Phases:
  1. [Public Portal]  Login, create LT-260, VIN lookup, fill form, submit
  2. [Staff Portal]   Open LT-260, add owner, set stolen=No, save, issue 160B/260A
  3. [Public Portal]  Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay
  4. [Staff Portal]   Open LT-262, verify details, CHECK DCI → Issue LT-264
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
from src.pages.staff_portal.lt262a_listing_page import Lt262aListingPage
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
@pytest.mark.fixed
class TestE2E030Lt264aIssuance:
    """E2E-030: LT-264A issuance — full lifecycle to LT-264 issued, then LT-264A flow"""

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
    # PHASE 3: Public Portal — Submit LT-262
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Select business (same as Phase 1)
            dashboard.select_business(BUSINESS_NAME)

            # Search for the same VIN from Phase 1
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

            # Fill Tab D — date of storage (advances to E via Next)
            lt262.fill_date_of_storage(past_date(30))

            # Fill Tab E — person authorizing storage
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Fill Additional Details (advances via Next from Form Details)
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Upload supporting documents
            lt262.upload_documents([SAMPLE_DOC_PATH])

            # Accept terms and sign
            lt262.accept_terms_and_sign(PERSON["name"])

            # Finish and pay — redirects to cart page
            lt262.finish_and_pay()

            # Click "Pay Using ACH/Drawdown" on the cart page
            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=15_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            # Confirm drawdown modal: "Are you sure you want to use your Drawdown balance?"
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=15_000)

            # Verify redirect to dashboard with VIN showing "LT-262 Submitted"
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

            # Navigate to LT-262 listing → To Process tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()

            # Search for our specific VIN
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify lien details on REVIEW LT-262 tab
            lt262_listing.verify_lien_details_visible()

            # Navigate to CHECK DCI AND NMVTIS → verify owner details
            lt262_listing.verify_owner_details_visible()

            # Issue LT-264 (clicks button → modal → Issue → success)
            lt262_listing.issue_lt264()

            # Verify green success banner
            success_banner = page.get_by_text("The form has been issued successfully.")
            expect(success_banner).to_be_visible(timeout=15_000)

            # Verify redirected to TRACK LT-264 tab
            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: API — Trigger automation chain to advance LT-262 to Aging state
    # ========================================================================
    def test_phase_5_api_trigger_aging(self, staff_context: BrowserContext):
        """Phase 5: [API] Hit automation chain with staff authToken + VIN to advance to Aging"""
        import requests

        # Get authToken from staff portal localStorage
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            auth_token = page.evaluate("() => localStorage.getItem('authToken')")
            assert auth_token, "authToken not found in staff portal localStorage"
        finally:
            page.close()

        url = (
            "https://nsm-qa.nc.verifi.dev/rest/api/automation/chain/execute"
            "/485a239fd539a7654cfb94cdf8b8f59e?encrypted=true"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:141.0) Gecko/20100101 Firefox/141.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/json",
            "Authorization": auth_token,
            "Origin": "https://nsm-qa.nc.verifi.dev",
        }
        response = requests.post(url, headers=headers, json={"vin": TEST_VIN})
        assert response.status_code == 200, (
            f"Automation chain API failed: {response.status_code} — {response.text}"
        )

    # ========================================================================
    # PHASE 6: Staff Portal — Track LT-264 (LT-264A path)
    # ========================================================================
    def test_phase_6_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Track LT-264 — select 'All parties did not sign' radio,
        check participant checkbox, save, complete court hearing → possessory lien"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → find application in Aging tab
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

            # Select radio: "All parties did not sign for the LT-264 letter by the 30th day of the delivery"
            radio_span = page.locator(
                "//span[contains(text(),'All parties did not sign for the LT-264 letter by the 30th day of the delivery')]"
            ).nth(1)
            radio_span.wait_for(state="visible", timeout=10_000)
            radio_span.click()
            page.wait_for_timeout(1000)

            # Checkbox under "Select participants that did not sign for the LT-264 letter"
            page.wait_for_timeout(2000)
            participant_cb = page.locator(
                "//span[@class='mat-checkbox-inner-container mat-checkbox-inner-container-no-side-margin']"
            ).first
            participant_cb.wait_for(state="visible", timeout=10_000)
            participant_cb.click()
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

            # Wait for redirect to REVIEW COURT HEARINGS
            possessory_text = page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
            possessory_text.wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(2000)

            # Check "Judgment in action of Possessory Lien" checkbox
            possessory_cb = page.locator('mat-checkbox').first
            possessory_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
                possessory_cb.locator("label").click()
                page.wait_for_timeout(1000)

            # Click Save
            save_btn2 = page.locator('button:has-text("Save")').first
            save_btn2.wait_for(state="visible", timeout=15_000)
            save_btn2.scroll_into_view_if_needed()
            save_btn2.click()
            page.wait_for_timeout(2000)

            # Confirm modal — click Yes
            yes_btn2 = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn2.wait_for(state="visible", timeout=10_000)
            yes_btn2.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text(re.compile(r"success", re.I)).first
            expect(success_banner).to_be_visible(timeout=15_000)

            # Click Next button
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=15_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            # Verify waiting message
            waiting_msg = page.get_by_text("Waiting for the requester to submit LT-263.")
            expect(waiting_msg).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 7: Staff Portal — Verify LT-264A in Correspondence History
    # ========================================================================
    def test_phase_7_staff_portal_verify_lt264a(self, staff_context: BrowserContext):
        """Phase 7: [Staff Portal] LT-262 Processed tab → search VIN → verify Processed →
        View Correspondence/Documents → Correspondence History modal → verify LT-264A entry"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → Processed tab
            staff_dashboard.navigate_to_lt262_listing()
            page.locator('[role="tab"]:has-text("Processed")').first.click()
            page.wait_for_load_state("networkidle")

            # Search for VIN using filters
            lt262_listing.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            lt262_listing.select_application(0)

            # Verify status = Processed
            expect(
                page.get_by_text(re.compile(r"Processed", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Click "View Correspondence/Documents"
            view_corr = page.locator("//span[contains(text(),'View Correspondence/Documents')]").first
            view_corr.wait_for(state="visible", timeout=15_000)
            view_corr.click()
            page.wait_for_timeout(3000)

            # Verify "Correspondence History" modal is displayed
            modal = page.locator("mat-dialog-container").first
            modal.wait_for(state="visible", timeout=10_000)
            expect(
                page.get_by_text(re.compile(r"Correspondence History", re.I)).first
            ).to_be_visible(timeout=10_000)

            # Scroll to bottom of modal to reveal LT-264A entry
            modal_content = page.locator("mat-dialog-container mat-dialog-content").first
            modal_content.evaluate("el => el.scrollTo(0, el.scrollHeight)")
            page.wait_for_timeout(2000)

            # Verify LT-264A entry is present
            expect(
                page.get_by_text(re.compile(r"LT-264A", re.I)).first
            ).to_be_visible(timeout=10_000)
        finally:
            page.close()
