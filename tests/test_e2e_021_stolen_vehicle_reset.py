"""
E2E-021: Stolen Vehicle Reset — Resubmit Same VIN After Stolen, Process New Case
PP: Submit LT-260 → SP: Mark stolen → PP: Resubmit same VIN (auto-filled) →
SP: Process new submission → SP: Verify both records (Processed + Stolen)

Phases:
  1. [Public Portal]  Submit LT-260 for a VIN
  2. [Staff Portal]   Open LT-260, set Stolen=Yes, save, download CMS
  3. [Staff Portal]   Stolen tab → verify status=Stolen + LT-260D in correspondence
  4. [Public Portal]  Verify file is locked — no LT-262 or further action possible
  5. [Public Portal]  Resubmit LT-260 for the same VIN — vehicle details auto-filled, skip fill_vehicle_details
  6. [Staff Portal]   Open new LT-260, add owner, set stolen=No, save, issue 160B/260A
  7. [Staff Portal]   To Process tab → search VIN → status=Processed;
                      Stolen tab → search VIN → status=Stolen
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
)
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
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

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
class TestE2E021StolenVehicleReset:
    """E2E-021: Mark stolen → resubmit same VIN → process new case → verify both records"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260 for a VIN"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Edit LT-260, set Stolen=Yes, save, download CMS
    # ========================================================================
    def test_phase_2_staff_portal_mark_stolen(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] LT-260 listing → search VIN → open → Edit →
        select Stolen=Yes → Save → verify status=Stolen → Download for CMS → green banner"""
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
            form_processing.select_stolen_yes()
            form_processing.click_save()

            form_processing.expect_status_stolen()

            lt260_listing.download_for_cms()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Stolen tab → verify status + Correspondence History LT-260D
    # ========================================================================
    def test_phase_3_staff_portal_verify_stolen_tab(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] LT-260 listing → Stolen tab → search VIN → open →
        verify status=Stolen → View Correspondence/Documents → LT-260D entry"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_stolen_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.expect_applications_visible()
            lt260_listing.select_application(0)

            form_processing.expect_status_stolen()

            lt260_listing.verify_correspondence_lt260d()
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Public Portal — Search VIN, verify status=Stolen, no action buttons
    # ========================================================================
    def test_phase_4_public_portal_verify_locked(self, public_context: BrowserContext):
        """Phase 4: [Public Portal] Search same VIN → status=Stolen →
        no action buttons (no Submit LT-262 / LT-263)"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business()

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            expect(page.get_by_text(re.compile(r"\bStolen\b", re.I)).first).to_be_visible(timeout=15_000)

            expect(page.locator('button:has-text("Submit LT-262"), a:has-text("Submit LT-262")')).to_have_count(0, timeout=5_000)
            expect(page.locator('button:has-text("Submit LT-263"), a:has-text("Submit LT-263")')).to_have_count(0, timeout=5_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Resubmit LT-260 for same VIN (vehicle details auto-filled)
    # ========================================================================
    def test_phase_5_public_portal_resubmit_lt260(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Resubmit LT-260 for same VIN — after VIN lookup,
        vehicle details are auto-filled from previous submission so fill_vehicle_details is skipped"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()
            # Vehicle details auto-filled from prior submission — skip fill_vehicle_details
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Process new LT-260, add owner, set stolen=No, issue 160B/260A
    # ========================================================================
    def test_phase_6_staff_portal_process_new_lt260(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Open new LT-260 in To Process → add owner →
        set stolen=No → save → issue 160B/260A → verify status=Processed"""
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

            # Issue 160B and 260A — use longer modal timeout (stolen history slows dialog render)
            issue_btn = page.locator(
                'button:has-text("Issue 160B and 260A"), '
                'button:has-text("Issue 160B"), '
                'button:has-text("160B")'
            ).first
            issue_btn.scroll_into_view_if_needed(timeout=5_000)
            issue_btn.click()
            page.wait_for_timeout(3000)

            modal_issue_btn = page.locator(
                'mat-dialog-container button:has-text("Issue")'
            ).first
            modal_issue_btn.wait_for(state="visible", timeout=20_000)
            modal_issue_btn.click()
            page.wait_for_timeout(3000)

            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 7: Staff Portal — Verify Processed (new) and Stolen (original) records
    # ========================================================================
    def test_phase_7_staff_portal_verify_both_records(self, staff_context: BrowserContext):
        """Phase 7: [Staff Portal] To Process tab → search VIN → click → status=Processed;
        Stolen tab → search VIN → click → status=Stolen"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            # ── New submission should be Processed ──
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_processed_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.expect_applications_visible()
            lt260_listing.select_application(0)

            form_processing.expect_status_processed()

            # ── Original submission should still be Stolen ──
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_stolen_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.expect_applications_visible()
            lt260_listing.select_application(0)

            form_processing.expect_status_stolen()
        finally:
            page.close()
