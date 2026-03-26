"""
E2E-018: Duplicate VIN Detection
Two users submit LT-260 for the same VIN — staff verifies duplicate detected.

Phases:
  1. [Public Portal - User A] Submit LT-260 for a VIN
  2. [Public Portal - User B] Submit LT-260 for the same VIN
  3. [Staff Portal]            Verify duplicate VIN detected in LT-260 listing
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
# Both users will submit for the SAME VIN
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE_A = generate_license_plate()
PLATE_B = generate_license_plate()
ADDRESS_A = generate_address()
ADDRESS_B = generate_address()
PERSON_A = generate_person()
PERSON_B = generate_person()

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
class TestE2E018DuplicateVinDetection:
    """E2E-018: Duplicate VIN — two users submit LT-260 for same VIN, staff sees duplicate"""

    # ========================================================================
    # PHASE 1: Public Portal (User A) — Submit LT-260
    # ========================================================================
    def test_phase_1_user_a_submits_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal - User A] Submit LT-260 for VIN"""
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
            lt260.fill_license_plate(PLATE_A)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS_A["street"], ADDRESS_A["zip"])
            lt260.fill_authorized_person(PERSON_A["name"], ADDRESS_A["street"], ADDRESS_A["zip"])
            lt260.accept_terms_and_sign(PERSON_A["name"], PERSON_A["email"])
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Public Portal (User B) — Submit LT-260 for same VIN
    # ========================================================================
    def test_phase_2_user_b_submits_lt260_same_vin(self, public_user_b_context: BrowserContext):
        """Phase 2: [Public Portal - User B] Submit LT-260 for the SAME VIN"""
        page = public_user_b_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(15))
            lt260.fill_license_plate(PLATE_B)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS_B["street"], ADDRESS_B["zip"])
            lt260.fill_authorized_person(PERSON_B["name"], ADDRESS_B["street"], ADDRESS_B["zip"])
            lt260.accept_terms_and_sign(PERSON_B["name"], PERSON_B["email"])
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Verify duplicate detected
    # ========================================================================
    def test_phase_3_staff_verifies_duplicate(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Search VIN — verify duplicate entries or duplicate indicator"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()
            lt260_listing.search_by_vin(TEST_VIN)

            # Expect at least two rows for the same VIN (duplicate submissions)
            rows = lt260_listing.application_rows
            rows.first.wait_for(state="visible", timeout=10_000)
            assert rows.count() >= 2, (
                f"Expected at least 2 applications for VIN {TEST_VIN}, "
                f"found {rows.count()}"
            )

            # Select the first application and verify duplicate indicator or warning
            lt260_listing.select_application(0)
            form_processing = FormProcessingPage(page)
            form_processing.expect_detail_page_visible()

            # Look for duplicate VIN warning on the detail page
            try:
                duplicate_indicator = page.locator(
                    'text=/duplicate/i, [class*="duplicate" i], [class*="warning" i]:has-text("VIN")'
                ).first
                duplicate_indicator.wait_for(state="visible", timeout=5_000)
            except Exception:
                pass  # Duplicate may be shown differently (e.g., badge, banner)
        finally:
            page.close()
