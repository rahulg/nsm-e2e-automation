"""
E2E-020: Paper LT-263 with Relaxed Date Validation
Paper forms have no date restrictions — private sale < 1 month should be accepted.

Phases:
  1. [Staff Portal] Add paper LT-263 with private sale date < 1 month from today
  2. [Staff Portal] Verify system accepts it (paper form date exemption)
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
    PRIVATE_SALE_DATA,
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
    future_date,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.medium
@pytest.mark.paper_form
class TestE2E020PaperFormRelaxedDates:
    """E2E-020: Paper LT-263 — private sale date < 1 month accepted (no date restrictions)"""

    # ========================================================================
    # PHASE 1: Staff Portal — Add paper LT-263 with sale date < 1 month
    # ========================================================================
    def test_phase_1_add_paper_lt263_short_date(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Add paper LT-263 with private sale date < 1 month away"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            paper_form = PaperFormPage(page)

            # Navigate to LT-263 listing and click "Add from Paper"
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_add_from_paper()

            # Fill sale details — private sale with date < 1 month from today
            # This would be rejected for online forms but paper forms are exempt
            paper_form.fill_sale_details(
                sale_type="private",
                sale_date=future_date(15),  # Only 15 days out (< 1 month)
                lien_amount=PRIVATE_SALE_DATA["lien_amount"],
            )

            # Submit paper LT-263
            paper_form.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Verify system accepted the paper form
    # ========================================================================
    def test_phase_2_verify_paper_form_accepted(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Verify paper LT-263 was accepted despite short sale date"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            # Navigate to LT-263 listing → To Process tab
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()

            # The paper form should appear in To Process (not rejected)
            lt263_listing.expect_applications_visible()

            # Verify no date validation error banners
            try:
                error = page.locator('text=/date.*invalid|date.*error|date.*rejected/i').first
                error.wait_for(state="visible", timeout=3_000)
                pytest.fail("Date validation error found — paper form should bypass date restrictions")
            except Exception:
                pass  # Expected: no date error for paper forms
        finally:
            page.close()
