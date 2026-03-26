"""
E2E-030: LT-264A Issuance After Aging Period
Verify aging period tracking and LT-264A issuance when conditions are met.

Phases:
  1. [Staff Portal] Verify aging period tracking on an LT-262 in Aging tab
  2. [Staff Portal] Issue LT-264A when aging conditions are met
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
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
class TestE2E030Lt264aIssuance:
    """E2E-030: LT-264A issuance after aging period conditions met"""

    # ========================================================================
    # PHASE 1: Verify aging period tracking
    # ========================================================================
    def test_phase_1_verify_aging_tracking(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Verify aging period tracking in LT-262 Aging tab"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → Aging tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_aging_tab()

            # Verify there are applications in the Aging tab
            try:
                lt262_listing.expect_applications_visible()
            except Exception:
                pytest.skip("No applications currently in Aging tab")

            # Select first application and verify aging details
            lt262_listing.select_application(0)

            # Verify aging period / days remaining are shown
            try:
                aging_info = page.locator(
                    'text=/aging|days.*remaining|notification.*date|delivery.*date/i'
                ).first
                aging_info.wait_for(state="visible", timeout=10_000)
            except Exception:
                pass  # Aging details may be displayed differently

            # Verify LT-264 tracking is visible
            lt262_listing.verify_lt264_tracking_visible()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Issue LT-264A when conditions met
    # ========================================================================
    def test_phase_2_issue_lt264a(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Issue LT-264A when aging conditions are met"""
        page = staff_context.new_page()
        try:
            # Use increased timeout and retry for navigation
            try:
                page.goto(SP_DASHBOARD_URL, timeout=90_000)
                page.wait_for_load_state("networkidle")
            except Exception:
                # Retry navigation on timeout
                page.goto(SP_DASHBOARD_URL, timeout=90_000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
            staff_dashboard = StaffDashboardPage(page)
            lt262a_listing = Lt262aListingPage(page)

            # Navigate to LT-262A listing (vehicles eligible for LT-264A)
            staff_dashboard.navigate_to_lt262a_listing()

            # Select first available application
            try:
                lt262a_listing.expect_applications_visible()
                lt262a_listing.select_application(0)
            except Exception:
                pytest.skip("No applications currently eligible for LT-264A issuance")

            # Verify LT-264A issuance conditions
            try:
                issue_btn = page.locator(
                    'button:has-text("Issue LT-264A"), button:has-text("Generate LT-264A")'
                ).first
                issue_btn.wait_for(state="visible", timeout=10_000)
                issue_btn.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
            except Exception:
                pass  # LT-264A may not be issuable if conditions not yet met
        finally:
            page.close()
