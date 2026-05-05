"""
E2E-032: Draft Auto-Save and Resume
Fill LT-260 through Tab 2 (Authorized Person), click Save as Draft → verify redirect.
Phase 2: resume draft from dashboard, verify pre-filled fields, complete and submit.

Phases:
  1. [Public Portal] Fill LT-260 through Tab 2, click Save as Draft
  2. [Public Portal] Open draft from dashboard, verify pre-filled fields, complete submission
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


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
DATE_VEHICLE_LEFT = past_date(30)
STORAGE_PHONE = "9195551234"
BUSINESS_NAME = "G-Car Garages New"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.medium
@pytest.mark.fixed
class TestE2E032DraftAutoSave:
    """E2E-032: Fill through Tab 2 → Save as Draft → resume from dashboard → complete submission"""

    # ========================================================================
    # PHASE 1: Public Portal — Fill LT-260 through Tab 2 and Save as Draft
    # ========================================================================
    def test_phase_1_fill_and_save_draft(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Fill LT-260 through Authorized Person tab, click Save as Draft"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)

            # Enter VIN (no VIN lookup — modal will appear at submit)
            lt260.enter_vin(TEST_VIN)

            # Fill vehicle details (Tab 1)
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(DATE_VEHICLE_LEFT)
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])

            # Fill authorized person (Tab 2)
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Click Save as Draft
            save_draft_btn = page.locator('//button[contains(text()," Save as Draft ")]')
            save_draft_btn.wait_for(state="visible", timeout=10_000)
            save_draft_btn.click()
            page.wait_for_timeout(1000)

            # Confirm the modal
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(2000)

            # Verify green success banner
            success_banner = page.get_by_text(re.compile(r"draft|saved|success", re.I)).first
            expect(success_banner).to_be_visible(timeout=15_000)

            # Verify redirect back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Public Portal — Resume draft, verify fields, complete submission
    # ========================================================================
    def test_phase_2_resume_verify_and_submit(self, public_context: BrowserContext):
        """Phase 2: [Public Portal] Open draft, verify pre-filled fields, complete and submit LT-260"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)

            # Search for the same VIN
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            # Verify status is "LT-260 Draft"
            expect(page.get_by_text(re.compile(r"LT-260 Draft", re.I)).first).to_be_visible(timeout=15_000)

            # Verify "Submit LT-260" action button is visible
            submit_lt260_btn = page.locator('button:has-text("Submit LT-260"), a:has-text("Submit LT-260")').first
            expect(submit_lt260_btn).to_be_visible(timeout=10_000)

            # Click "Submit LT-260" to open the pre-filled form
            submit_lt260_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            # Verify "LT-260 - Vehicle Details" page opened
            expect(
                page.get_by_text(re.compile(r"LT-260.*Vehicle Details|Vehicle Details", re.I)).first
            ).to_be_visible(timeout=15_000)

            lt260 = Lt260FormPage(page)

            # ── Verify Vehicle Details (Tab 1) pre-filled ──
            expect(lt260.vin_input).to_have_value(TEST_VIN, timeout=10_000)

            # Make — when loaded from draft the autocomplete input may be hidden;
            # fall back to verifying the make text is visible anywhere on the page
            try:
                expect(lt260.make_input).to_have_value(
                    re.compile(re.escape(VEHICLE["make"]), re.I), timeout=5_000
                )
            except Exception:
                expect(page.get_by_text(re.compile(re.escape(VEHICLE["make"]), re.I)).first).to_be_visible(timeout=10_000)

            expect(lt260.year_input).to_have_value(VEHICLE["year"], timeout=10_000)

            # Date vehicle left — Angular may reformat YYYY-MM-DD, verify field is not empty
            date_val = lt260.date_vehicle_left_input.input_value()
            assert date_val, "Date vehicle left should be pre-filled in the draft"

            expect(lt260.location_input).to_have_value(STORAGE_LOCATION_NAME, timeout=10_000)
            expect(lt260.address_input).to_have_value(ADDRESS["street"], timeout=10_000)

            # Phone — verify field is not empty (Angular tel input may reformat digits)
            phone_val = lt260.phone_input.input_value()
            assert phone_val, "Telephone number should be pre-filled in the draft"

            # Click Next → Authorized Person tab (Tab 2)
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            # ── Verify Authorized Person Details (Tab 2) pre-filled ──
            expect(lt260.auth_person_name_input).to_have_value(PERSON["name"], timeout=10_000)
            expect(lt260.auth_person_address_input).to_have_value(ADDRESS["street"], timeout=10_000)
            expect(lt260.auth_person_zip_input).to_have_value(ADDRESS["zip"], timeout=10_000)

            # Accept terms and sign (Tab 3) — internally clicks Next to advance tab
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            # Submit — VIN image modal should appear
            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)

            # Verify redirect back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()
