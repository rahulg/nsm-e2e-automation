"""
E2E-018: Duplicate VIN Detection
Same user submits LT-260 twice for the same VIN — second submission must be blocked.

Phases:
  1. [Public Portal] Submit LT-260 (same as E2E-001 Phase 1)
  2. [Public Portal] Attempt a second LT-260 for the same VIN → red error banner
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


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

BUSINESS_NAME = "G-Car Garages New"
PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
class TestE2E018DuplicateVinDetection:
    """E2E-018: Duplicate VIN — second LT-260 for same VIN must be blocked with error banner"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260 (same as E2E-001 Phase 1)
    # ========================================================================
    def test_phase_1_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260 successfully for TEST_VIN"""
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

            # Verify successful submission — redirected back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Public Portal — Attempt duplicate LT-260 for same VIN
    # ========================================================================
    def test_phase_2_duplicate_submission_blocked(self, public_context: BrowserContext):
        """Phase 2: [Public Portal] Re-submit LT-260 with same VIN — expect red error banner"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(15))
            lt260.fill_license_plate(generate_license_plate())
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            # Click Submit — duplicate VIN banner appears on the same page
            lt260.submit_button.click()
            page.wait_for_timeout(3000)

            # Assert red error banner — duplicate VIN must be blocked
            error_banner = page.locator(
                ':has-text("is associated with an ongoing application")'
            ).last

            expect(error_banner).to_be_visible(timeout=10_000)
            expect(error_banner).to_contain_text(TEST_VIN)
            expect(error_banner).to_contain_text(
                "is associated with an ongoing application and cannot be entered again"
            )
        finally:
            page.close()
