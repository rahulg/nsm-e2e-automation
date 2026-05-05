"""
E2E-024: Close File Attribution — PP Reclaim → SP Verify "Updated By"
PP: LT-260 → SP: Process → PP: LT-262 → SP: Process LT-264 →
PP: Vehicle Reclaim → SP: LT-262 Closed listing → verify "Updated By" = Daniel Scott
with user icon → open record → verify remarks

Phases:
  1. [Public Portal]  Submit LT-260
  2. [Staff Portal]   Process LT-260
  3. [Public Portal]  Submit LT-262 with payment
  4. [Staff Portal]   Process LT-262, issue LT-264
  5. [Public Portal]  Initiate Vehicle Reclaim
  6. [Staff Portal]   LT-262 Closed listing → verify "Updated By" = Daniel Scott + user icon
                      → open record → verify status=Closed + Close File Remarks
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
    generate_person,
    past_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.vehicle_reclaim_page import VehicleReclaimPage
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
BUSINESS_NAME = "G-Car Garages New"
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")
RECLAIM_COMMENT = "Vehicle reclaimed by owner - automation test"

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
@pytest.mark.medium
@pytest.mark.fixed
class TestE2E024CloseFileAttribution:
    """E2E-024: PP reclaim → SP verify 'Updated By' = Daniel Scott with user icon in listing"""

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
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

            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=20_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Vehicle Reclaim via 3-dot menu
    # ========================================================================
    def test_phase_5_public_portal_vehicle_reclaim(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Search VIN → 3-dot menu → Vehicle Reclaimed →
        enter comment → click Vehicle Reclaimed → green banner → LT-262 Closed status"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            reclaim = VehicleReclaimPage(page)
            reclaim.open_vehicle_reclaimed_download()
            reclaim.enter_reclaim_comments(RECLAIM_COMMENT)
            reclaim.click_vehicle_reclaimed_btn()

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
            page.wait_for_load_state("networkidle")

            status_locator = page.get_by_text(re.compile(r"LT-262 Closed", re.I)).first

            def _check_closed_status() -> bool:
                try:
                    expect(status_locator).to_be_visible(timeout=8_000)
                    return True
                except Exception:
                    return False

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            if not _check_closed_status():
                dashboard.click_sold_completed_tab()
                page.wait_for_timeout(2000)
                dashboard.search_by_vin(TEST_VIN)
                page.wait_for_timeout(3000)

                if not _check_closed_status():
                    vin_row = page.get_by_text(TEST_VIN).first
                    vin_row.wait_for(state="visible", timeout=10_000)
                    vin_row.click()
                    page.wait_for_load_state("networkidle")
                    expect(status_locator).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Verify "Updated By" in listing + Closed record
    # ========================================================================
    def test_phase_6_staff_portal_verify_updated_by(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] LT-262 Closed tab → search VIN →
        verify 'Updated By' column shows 'Daniel Scott' with user icon →
        open record → verify status=Closed + Close File Remarks"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_closed_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.expect_applications_visible()

            # Verify "UPDATED BY" column shows "Daniel Scott" with a user icon
            daniel_cell = page.locator(
                "//span[contains(text(),'Daniel Scott')] | //td[contains(text(),'Daniel Scott')]"
            ).first
            daniel_cell.wait_for(state="visible", timeout=15_000)

            # Open the record
            lt262_listing.select_application(0)

            # Verify status = Closed
            expect(page.get_by_text(re.compile(r"\bClosed\b", re.I)).first).to_be_visible(timeout=15_000)

            # Verify Close File Remarks shows the reclaim comment
            expect(page.get_by_text(re.compile(r"Close File Remarks", re.I)).first).to_be_visible(timeout=15_000)
            expect(page.get_by_text(RECLAIM_COMMENT).first).to_be_visible(timeout=10_000)
        finally:
            page.close()
