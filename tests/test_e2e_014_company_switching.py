"""
E2E-014: Business Admin Company Switching & Data Isolation
Submit LT-260 under "G-Car Garages New" → Switch to "A-Car Garages" →
Verify VIN not visible under second business

Phases:
  1. [Public Portal] Select "G-Car Garages New", fill & submit LT-260
  2. [Public Portal] Switch to "A-Car Garages", search VIN → entry NOT visible
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
BUSINESS_A = "G-Car Garages New"
BUSINESS_B = "A-Car Garages"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.multiuser
@pytest.mark.high
class TestE2E014CompanySwitching:
    """E2E-014: Company Switching — data isolation between two businesses"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260 under G-Car Garages New
    # ========================================================================
    def test_phase_1_submit_lt260_under_business_a(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Select G-Car Garages New, fill & submit LT-260"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_A)
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
            page.wait_for_timeout(3000)

            # Verify redirect back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=45_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Public Portal — Switch to A-Car Garages, verify VIN not visible
    # ========================================================================
    def test_phase_2_switch_to_business_b_verify_isolation(self, public_context: BrowserContext):
        """Phase 2: [Public Portal] Switch to A-Car Garages → search VIN → not found"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_B)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)

            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            # VIN submitted under G-Car Garages New must NOT appear under A-Car Garages
            expect(dashboard.application_list.first).not_to_be_visible(timeout=10_000)
        finally:
            page.close()
