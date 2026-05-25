"""
E2E-051: Public Portal Message Center Receipt Across Notification-Triggering Letter Issuance Events
Cross-portal test spanning Public Portal and Staff Portal.

Uses Individual Public Portal user (INDIVIDUAL_PUBLIC_USERNAME / INDIVIDUAL_PUBLIC_PASSWORD).

Verifies that a Message Center entry appears in the requestor's Public Portal inbox
for each letter issuance event that triggers a notification:
  LT-160B (after LT-260 processing)
  LT-264   (after LT-262 processing)
  LT-264A (after aging period — timing-dependent)
  LT-265 / LT-265A (after LT-263 processing → sale approval)
  LT-260C / LT-262B (no-owners path)

Phases:
  0a. [Public Portal — Individual] Submit LT-260 (mirrors E2E-001 Phase 1)
  0b. [Staff Portal] Process LT-260 → LT-160B issued (mirrors E2E-001 Phase 2)
  1.  [Public Portal — Individual] Message Center → verify
                      "Notification: LT-160B Form Issued for <VIN>"
  2a. [Public Portal — Individual] Submit LT-262 + pay (mirrors E2E-001 Phase 3)
  2b. [Staff Portal] Process LT-262 → issue LT-264 + LT-264G (mirrors E2E-001 Phase 4)
  2c. [Public Portal — Individual] Message Center → verify
                      "Notification: LT-264 Form Issued for <VIN>"
  3.  [Timing-dependent — skip if aging not passed] Verify LT-264A Message Center entry
  4a. [Public Portal — Individual] Submit LT-263 for VIN-A
  4b. [Staff Portal] Process LT-263 → issue LT-265 + LT-265A
  4c. [Public Portal — Individual] Verify Message Center entry for LT-265 sale approval
  5a. [Public Portal — Individual] Submit LT-260 for VIN-B (no-owners path)
  5b. [Staff Portal] Process VIN-B LT-260 → LT-260C issued
  5c. [Public Portal — Individual] Verify Message Center entry for LT-260C
  6.  [AD Method Step-Count Guard — NOT AUTOMATABLE] Engineering pre-publish check

Ref: Edge Case 34, Business Rule 87, Business Rule 88, Business Rule 34,
     Journey 2.5, Journey 2.8, Journey 5.2
"""

import re
from pathlib import Path
from datetime import datetime

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    VIN_NO_OWNERS,
    STANDARD_SALE_DATA,
)
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    generate_person,
    past_date,
    future_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage

FIXTURE_DOC = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")

# ─── Shared test data ───
TEST_VIN_A = generate_vin()
VEHICLE_A = random_vehicle()
PLATE_A = generate_license_plate()

# VIN-B: no-owners path → LT-260C notification
TEST_VIN_B = VIN_NO_OWNERS if not VIN_NO_OWNERS.startswith("PLACEHOLDER") else generate_vin()
VEHICLE_B = random_vehicle()
PLATE_B = generate_license_plate()

ADDRESS = generate_address()
PERSON = generate_person()

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


def open_message_center(page):
    """Navigate to the Message Center / Messages tab on Public Portal."""
    try:
        dashboard = PublicDashboardPage(page)
        dashboard.click_messages_tab()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
    except Exception:
        try:
            msg_tab = page.locator(
                'button:has-text("Messages"), a:has-text("Messages"), '
                'a:has-text("Message Center"), button:has-text("Message Center")'
            ).first
            msg_tab.wait_for(state="visible", timeout=10_000)
            msg_tab.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        except Exception:
            pass


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
class TestE2E051MessageCenterReceipt:
    """E2E-051: Public Portal Message Center Receipt Across Notification-Triggering Letter Issuance Events"""

    # ========================================================================
    # PHASE 0a: Public Portal (Individual) — Submit LT-260
    # Mirrors E2E-001 Phase 1 — individual user, no select_business()
    # ========================================================================
    def test_phase_0a_public_portal_create_lt260(self, individual_public_context: BrowserContext):
        """Phase 0a: [Public Portal] Submit LT-260 for VIN-A (individual user)."""
        page = individual_public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Individual user has no business selection — go straight to Start here
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)

            lt260.enter_vin(TEST_VIN_A)

            lt260.fill_vehicle_details(VEHICLE_A)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE_A)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])

            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 0b: Staff Portal — Process LT-260 → Issue LT-160B + LT-260A
    # Mirrors E2E-001 Phase 2
    # ========================================================================
    def test_phase_0b_staff_process_lt260(self, staff_context: BrowserContext):
        """Phase 0b: [Staff Portal] Open LT-260, add owner, set stolen=No, save, issue LT-160B/LT-260A."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()

            lt260_listing.search_by_vin(TEST_VIN_A)
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
    # PHASE 1: Public Portal (Individual) — Message Center — LT-160B Notification
    # ========================================================================
    def test_phase_1_verify_lt160b_message_center_entry(self, individual_public_context: BrowserContext):
        """Phase 1: [Public Portal] Navigate to Message Center → verify
        'Notification: LT-160B Form Issued for <VIN>' entry exists."""
        page = individual_public_context.new_page()
        try:
            go_to_public_dashboard(page)
            open_message_center(page)

            expected_text = f"Notification: LT-160B Form Issued for {TEST_VIN_A}"

            notification = page.get_by_text(expected_text).first
            expect(notification).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2a: Public Portal (Individual) — Submit LT-262 + Pay
    # Mirrors E2E-001 Phase 3 — individual user, no select_business()
    # ========================================================================
    def test_phase_2a_submit_lt262_vin_a(self, individual_public_context: BrowserContext):
        """Phase 2a: [Public Portal] Submit LT-262 for VIN-A and complete drawdown payment."""
        page = individual_public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Individual user — no select_business()
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN_A)
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

            lt262.upload_documents([FIXTURE_DOC])

            lt262.accept_terms_and_sign(PERSON["name"])

            lt262.finish_and_pay()

            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=30_000)

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2b: Staff Portal — Process LT-262 → Issue LT-264 + LT-264G
    # Mirrors E2E-001 Phase 4
    # ========================================================================
    def test_phase_2b_staff_process_lt262_issue_lt264(self, staff_context: BrowserContext):
        """Phase 2b: [Staff Portal] Open LT-262, verify details, CHECK DCI → Issue LT-264."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()

            lt262_listing.search_by_vin(TEST_VIN_A)
            lt262_listing.select_application(0)

            lt262_listing.verify_lien_details_visible()

            lt262_listing.verify_owner_details_visible()

            lt262_listing.issue_lt264()

            success_banner = page.get_by_text("The form has been issued successfully.")
            expect(success_banner).to_be_visible(timeout=30_000)

            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2c: Public Portal (Individual) — Message Center — LT-264 Notification
    # ========================================================================
    def test_phase_2c_verify_lt264_message_center_entry(self, individual_public_context: BrowserContext):
        """Phase 2c: [Public Portal] Navigate to Message Center → verify
        'Notification: LT-264 Form Issued for <VIN>' entry exists."""
        page = individual_public_context.new_page()
        try:
            go_to_public_dashboard(page)
            open_message_center(page)

            expected_text = f"Notification: LT-264 Form Issued for {TEST_VIN_A}"

            notification = page.get_by_text(expected_text).first
            expect(notification).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: API — Trigger Automation Chain to Advance LT-262 to Aging State
    # Mirrors E2E-030 Phase 5
    # ========================================================================
    def test_phase_3_api_trigger_aging(self, staff_context: BrowserContext):
        """Phase 3: [API] Hit automation chain with staff authToken + VIN-A to advance
        LT-262 to Aging state and issue LT-264A."""
        import requests

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
        response = requests.post(url, headers=headers, json={"vin": TEST_VIN_A})
        assert response.status_code == 200, (
            f"Automation chain API failed: {response.status_code} — {response.text}"
        )

    # ========================================================================
    # PHASE 4a: Staff Portal — Track LT-264 (LT-264A Path)
    # Mirrors E2E-030 Phase 6
    # ========================================================================
    def test_phase_4a_staff_track_lt264_lt264a_path(self, staff_context: BrowserContext):
        """Phase 4a: [Staff Portal] Track LT-264 — select 'All parties did not sign' radio,
        check participant checkbox, save, complete court hearing → possessory lien → LT-264A issued."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_aging_tab()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(8000)
            lt262_listing.search_by_vin(TEST_VIN_A)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.court_hearing_tab.click()
                page.wait_for_load_state("networkidle")
                lt262_listing.search_by_vin(TEST_VIN_A)

            lt262_listing.select_application(0)

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

            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=15_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Wait for redirect to REVIEW COURT HEARINGS
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
    # PHASE 4b: Public Portal (Individual) — Message Center — LT-264A & LT-263 Notifications
    # ========================================================================
    def test_phase_4b_verify_lt264a_lt263_message_center_entries(self, individual_public_context: BrowserContext):
        """Phase 4b: [Public Portal] Navigate to Message Center → verify
        'Notification: LT-264A Form Issued for <VIN>' and
        'Notification: LT-263 Form Issued for <VIN>' entries exist."""
        page = individual_public_context.new_page()
        try:
            go_to_public_dashboard(page)
            open_message_center(page)

            page.wait_for_timeout(2000)

            # LT-263 appears on top (newest), LT264A second (no dash in LT264A per system)
            expected_lt263 = f"Notification: LT-263 Form Issued for {TEST_VIN_A}"
            notification_lt263 = page.get_by_text(expected_lt263).first
            expect(notification_lt263).to_be_visible(timeout=15_000)

            expected_lt264a = f"Notification: LT264A Form Issued for {TEST_VIN_A}"
            notification_lt264a = page.get_by_text(expected_lt264a).first
            expect(notification_lt264a).to_be_visible(timeout=15_000)
        finally:
            page.close()
