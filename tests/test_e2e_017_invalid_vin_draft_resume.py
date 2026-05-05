"""
E2E-017: Invalid VIN → VIN Image Modal → Draft → Resume → Submit
PP: Invalid VIN → Modal → Upload → Save Draft → Logout → Resume → Submit

Phases:
  1. [Public Portal] Enter unknown VIN, VIN lookup fails, fill manually
  2. [Public Portal] Save as Draft
  3. [Public Portal] Resume draft, complete remaining fields
  4. [Public Portal] Submit → VIN Image Modal appears → upload photo → submit
"""

import re

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

TEST_VIN = generate_vin()  # Random VIN — guaranteed not in STARS
VEHICLE = random_vehicle()
ADDRESS = generate_address()
PERSON = generate_person()

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
class TestE2E017InvalidVinDraftResume:
    """E2E-017: Invalid VIN → manual entry → draft → resume → VIN image modal → submit"""

    def test_phase_1_enter_invalid_vin_save_draft(self, public_context: BrowserContext):
        """Phase 1: Enter unknown VIN, fill manually, save as draft"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()

            # VIN not found — fields NOT auto-populated, fill manually
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(generate_license_plate())
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])

            # Save as draft
            draft_btn = page.locator('button:has-text("Save as Draft"), button:has-text("Save Draft")').first
            draft_btn.wait_for(state="visible", timeout=10_000)
            draft_btn.click()
            page.wait_for_timeout(1000)

            # Confirm modal → click Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        finally:
            page.close()

    def test_phase_2_resume_draft_and_submit(self, fresh_public_context: BrowserContext):
        """Phase 2: Resume draft → verify LT-260 Draft status → Submit LT-260 → Next on pre-filled Tab 1
        → fill Authorized Person → Terms → submit_with_vin_image"""
        page = fresh_public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_notice_storage_tab()

            # Search for the draft by VIN
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            # Verify status is "LT-260 Draft"
            expect(page.get_by_text(re.compile(r"LT-260 Draft", re.I)).first).to_be_visible(timeout=15_000)

            # Click "Submit LT-260" button
            submit_lt260_btn = page.locator('button:has-text("Submit LT-260"), a:has-text("Submit LT-260")').first
            submit_lt260_btn.wait_for(state="visible", timeout=10_000)
            submit_lt260_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            lt260 = Lt260FormPage(page)

            # Tab 1 (Vehicle Details) is pre-filled — fill_authorized_person clicks Next internally
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Terms & signature
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            # Submit — handles VIN image modal for unknown VINs
            lt260.submit_with_vin_image()

            # Verify redirect back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()
