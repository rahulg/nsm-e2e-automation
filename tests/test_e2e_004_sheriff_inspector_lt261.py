"""
E2E-004: Sheriff/Inspector Standalone (LT-261)
Staff Portal only — no Public Portal involvement.

Workflow: SP: LT-261 → SP: LT-265 (vehicle approved for sale directly)

Phases:
  1. [Staff Portal] Add from E-Stop → modal (VIN only) → fill form → submit
  2. [Staff Portal] LT-261 listing → search VIN → status Processed → View Correspondence → LT-265 entry
  3. [Staff Portal] Sold listing → search VIN → status Processed → View Correspondence → LT-265 entry
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    generate_person,
    future_date,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page
from src.pages.staff_portal.sold_listing_page import SoldListingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
OFFICER = generate_person()

SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
class TestE2E004SheriffInspectorLt261:
    """E2E-004: Sheriff/Inspector LT-261 — Staff-only workflow to LT-265"""

    # ========================================================================
    # PHASE 1: Staff Portal — Add LT-261 from E-Stop
    # ========================================================================
    def test_phase_1_staff_portal_submit_lt261(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Add from E-Stop → modal (VIN only) → fill form → submit"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Navigate to LT-261 listing
            staff_dashboard.navigate_to_lt261_listing()

            # Click "Add from E-Stop" — opens modal
            lt261.click_add_from_estop()

            # Modal: enter VIN, click Next
            lt261.fill_modal_vin_next(TEST_VIN)

            # Form: Year
            lt261.fill_year("2018")

            # Form: Make (autocomplete chip input)
            lt261.fill_make("TOY")

            # Under "Location of Vehicle-Sale Date":
            # Search location (type "pen", select first suggestion)
            lt261.fill_search_location("pen")

            # Right panel: check "USE SAME ADDRESS AS PLACE STORED"
            lt261.check_use_same_address_storage()

            # Sale Date
            lt261.fill_sale_date(future_date(21))

            # Under "Notice of Sale for Other Reasons": select first option
            lt261.select_notice_of_sale_reason()

            # Under "Name and Address of Agency or Department Selling Vehicle":
            # Check "USE SAME ADDRESS AS PLACE STORED"
            lt261.check_agency_use_same_address()

            # Fill NAME field
            lt261.fill_agency_name(OFFICER["name"])

            # Stolen → No
            lt261.select_stolen_no()

            # Submit → confirm modal → green banner → redirect to listing
            lt261.submit_with_confirmation()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Verify LT-261 Processed + LT-265 in correspondence
    # ========================================================================
    def test_phase_2_staff_portal_verify_lt261_processed(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] LT-261 listing → search VIN → status Processed →
        View Correspondence/Documents → Correspondence History modal has LT-265 entry"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Navigate to LT-261 listing → Processed tab
            staff_dashboard.navigate_to_lt261_listing()
            lt261.click_processed_tab()

            # Search for the VIN using filters
            lt261.search_by_vin(TEST_VIN)
            lt261.select_application(0)

            # Verify status is Processed
            lt261.expect_status_processed()

            # Click "View Correspondence/Documents" → verify modal + LT-265 entry
            lt261.click_view_correspondence()
            lt261.expect_lt265_in_correspondence()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Verify vehicle in Sold listing + LT-265 in correspondence
    # ========================================================================
    def test_phase_3_staff_portal_verify_sold(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Sold listing → search VIN → status Processed →
        View Correspondence/Documents → Correspondence History modal has LT-265 entry"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            sold_listing = SoldListingPage(page)
            lt261 = Lt261Page(page)

            # Navigate to Sold listing
            staff_dashboard.navigate_to_sold()

            # Search for the VIN using filters
            sold_listing.search_by_vin(TEST_VIN)
            sold_listing.select_application(0)

            # Verify status is Processed
            lt261.expect_status_processed()

            # Click "View Correspondence/Documents" → verify modal + LT-265 entry
            lt261.click_view_correspondence()
            lt261.expect_lt265_in_correspondence()
        finally:
            page.close()
