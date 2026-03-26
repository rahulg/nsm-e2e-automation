"""
E2E-008: Stolen Vehicle Discovery & Lockout
PP: LT-260 → SP: Stolen → Download CMS → PP: Locked (no LT-262 possible)

Phases:
  1. [Public Portal]  Submit LT-260 for a VIN with stolen indicator
  2. [Staff Portal]   Open LT-260, verify stolen indicator, save as stolen
  3. [Staff Portal]   Download for CMS, verify in Stolen tab
  4. [Public Portal]  Verify file is locked — no LT-262 or further action possible
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    VIN_STOLEN,
    SAMPLE_DOC_PATH,
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
# Use STARS VIN with stolen indicator if configured; otherwise generate random
TEST_VIN = VIN_STOLEN if VIN_STOLEN != "PLACEHOLDER_STOLEN" else generate_vin()
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
@pytest.mark.alternate
@pytest.mark.critical
class TestE2E008StolenVehicleLockout:
    """E2E-008: Stolen Vehicle — save as stolen → CMS download → PP locked"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260 for a VIN with stolen indicator"""
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
    # PHASE 2: Staff Portal — Verify stolen, save as stolen, download CMS
    # ========================================================================
    def test_phase_2_staff_portal_mark_stolen(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Verify stolen indicator = Yes, save as stolen"""
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

            # Verify stolen indicator shows "Yes"
            lt260_listing.verify_stolen_indicator_yes()

            # Save as stolen
            lt260_listing.save_as_stolen()

            # Download for CMS
            lt260_listing.download_for_cms()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Verify in Stolen tab
    # ========================================================================
    def test_phase_3_staff_portal_verify_stolen_tab(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Verify application in Stolen tab"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_stolen_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.expect_applications_visible()
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Public Portal — Verify file locked
    # ========================================================================
    def test_phase_4_public_portal_verify_locked(self, public_context: BrowserContext):
        """Phase 4: [Public Portal] File locked — no LT-262 or further action available"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)

            # File should be locked — no submit buttons for LT-262/LT-263
            dashboard.expect_file_locked()
        finally:
            page.close()
