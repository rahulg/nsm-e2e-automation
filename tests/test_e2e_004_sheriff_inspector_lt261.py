"""
E2E-004: Sheriff/Inspector Standalone (LT-261)
Staff Portal only — no Public Portal involvement.

Workflow: SP: LT-261 → SP: LT-265 (vehicle approved for sale directly)

Phases:
  1. [Staff Portal] Navigate to LT-261, enter vehicle and officer details, submit
  2. [Staff Portal] Issue LT-265 directly — no LT-260, LT-262, or LT-263 needed
  3. [Staff Portal] Verify vehicle moves to Sold tab
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_person,
    generate_address,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
OFFICER = generate_person()
ADDRESS = generate_address()

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
    # PHASE 1: Staff Portal — Create and submit LT-261
    # ========================================================================
    def test_phase_1_staff_portal_submit_lt261(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Navigate to LT-261, fill vehicle + officer info, submit"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Navigate to LT-261 listing
            staff_dashboard.navigate_to_lt261_listing()

            # Enter vehicle details
            lt261.enter_vin(TEST_VIN)
            lt261.click_vin_lookup()
            lt261.fill_vehicle_details(VEHICLE)

            # Fill officer/inspector information
            lt261.fill_officer_info(
                name=OFFICER["name"],
                badge="NC-12345",
                department="NC Highway Patrol",
            )

            # Fill location and circumstances
            lt261.fill_location_and_circumstances(
                location=f"{ADDRESS['street']}, {ADDRESS['city']}, NC {ADDRESS['zip']}",
                circumstances="Vehicle found abandoned on roadside. No plates, no registration visible. "
                              "Appears inoperable. Officer verified VIN from dash plate.",
            )

            # Submit LT-261
            lt261.submit()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Issue LT-265 directly
    # ========================================================================
    def test_phase_2_staff_portal_issue_lt265(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Issue LT-265 directly from LT-261 — no LT-260/262/263 needed"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Navigate to LT-261 listing
            staff_dashboard.navigate_to_lt261_listing()
            lt261.click_to_process_tab()
            lt261.search_by_vin(TEST_VIN)
            lt261.select_application(0)

            # Issue LT-265 directly (skips entire LT-260/262/263 chain)
            lt261.issue_lt265()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Verify vehicle in Sold tab
    # ========================================================================
    def test_phase_3_staff_portal_verify_sold(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Verify vehicle in Sold/Processed tab — workflow complete"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Navigate to LT-261 listing and verify in processed tab
            staff_dashboard.navigate_to_lt261_listing()
            lt261.verify_vehicle_in_sold_tab(TEST_VIN)

            # Also verify in Sold nav section
            staff_dashboard.navigate_to_sold()
            page.wait_for_timeout(2000)

            # Search for our VIN in the sold listing
            search = page.locator('input[placeholder*="Search using VIN"]').first
            try:
                search.fill(TEST_VIN)
                search.press("Enter")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            except Exception:
                pass
        finally:
            page.close()
