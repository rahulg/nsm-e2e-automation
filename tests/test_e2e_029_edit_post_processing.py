"""
E2E-029: Edit Form Data Post-Processing — Correspondence Recipient Name Check
PP: Submit LT-260 → SP: Process LT-260 →
SP: Verify LT-260A RECIPIENT NAME in Correspondence History →
SP: Edit owner name → Verify correspondence RECIPIENT NAME shows updated name.

Phases:
  1. [PP + SP] Submit LT-260 (E2E-001 Phase 1) + Process LT-260 (E2E-001 Phase 2)
  2. [SP]      LT-260 Processed tab → open Correspondence History → verify LT-260A
               RECIPIENT NAME = owner name added in Phase 1
  3. [SP]      Edit owner name on processed form → open Correspondence History →
               verify LT-260A RECIPIENT NAME = updated owner name
"""

import re

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
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
EDITED_PERSON = generate_person()
BUSINESS_NAME = "G-Car Garages New"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def _verify_lt260a_recipient(page, expected_name: str) -> None:
    """Open Correspondence History modal, scroll, assert LT-260A row contains expected_name."""
    view_corr = page.locator('//span[contains(text(),"View Correspondence/Documents")]').first
    view_corr.wait_for(state="visible", timeout=15_000)
    view_corr.click()

    modal_title = page.get_by_text(re.compile(r"Correspondence History", re.I)).first
    expect(modal_title).to_be_visible(timeout=10_000)
    page.wait_for_timeout(5_000)

    modal = page.locator("mat-dialog-container").first
    modal.evaluate("el => el.scrollTop = el.scrollHeight")
    page.wait_for_timeout(1_000)

    # Assert LT-260A entry is present
    lt260a_entry = page.locator("mat-dialog-container").get_by_text(
        re.compile(r"\bLT-260A\b", re.I)
    ).first
    expect(lt260a_entry).to_be_visible(timeout=10_000)

    # Find RECIPIENT NAME column index from table headers
    recipient_col_idx = -1
    headers = page.locator("mat-dialog-container th")
    for i in range(headers.count()):
        if "recipient" in headers.nth(i).inner_text().strip().lower():
            recipient_col_idx = i
            break

    # Get the LT-260A row
    lt260a_row = page.locator("mat-dialog-container tbody tr").filter(has_text="LT-260A").first
    lt260a_row.wait_for(state="visible", timeout=10_000)

    if recipient_col_idx >= 0:
        recipient_text = lt260a_row.locator("td").nth(recipient_col_idx).inner_text().strip()
        assert expected_name.lower() in recipient_text.lower(), (
            f"LT-260A RECIPIENT NAME: expected '{expected_name}', got '{recipient_text}'"
        )
    else:
        # Fallback: assert name appears anywhere in the row
        row_text = lt260a_row.inner_text()
        assert expected_name.lower() in row_text.lower(), (
            f"Expected '{expected_name}' in LT-260A row text, got: '{row_text}'"
        )

    # Close modal
    try:
        close_btn = page.locator(
            'mat-dialog-container button:has-text("Close"), [mat-dialog-close]'
        ).first
        close_btn.click(timeout=3_000)
        page.wait_for_timeout(500)
    except Exception:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.medium
@pytest.mark.fixed
class TestE2E029EditPostProcessing:
    """E2E-029: Edit owner name post-processing — correspondence RECIPIENT NAME check"""

    # ========================================================================
    # PHASE 1: Submit LT-260 (PP) + Process LT-260 (SP)
    # ========================================================================
    def test_phase_1_submit_and_process_lt260(
        self, public_context: BrowserContext, staff_context: BrowserContext
    ):
        """Phase 1: [PP] Submit LT-260 (E2E-001 Phase 1) + [SP] Process LT-260 (E2E-001 Phase 2)"""
        # ── Public Portal: submit LT-260 ─────────────────────────────────────
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
            # Soft check — redirect back to dashboard may not always happen; don't fail the test
            try:
                page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
            except Exception:
                print("  WARN: did not redirect back to dashboard after LT-260 submit — continuing")
        finally:
            page.close()

        # ── Staff Portal: process LT-260 ─────────────────────────────────────
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
            form_processing.click_edit()
            form_processing.add_owner(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            form_processing.select_stolen_no()
            form_processing.click_save()
            form_processing.issue_160b_and_260a()
            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Verify LT-260A RECIPIENT NAME = original owner name
    # ========================================================================
    def test_phase_2_verify_lt260a_recipient_original(self, staff_context: BrowserContext):
        """Phase 2: [SP] Processed tab → search VIN → verify status=Processed →
        open Correspondence History → assert LT-260A RECIPIENT NAME = Phase 1 owner name"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_processed_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)
            form_processing.expect_status_processed()

            _verify_lt260a_recipient(page, PERSON["name"])
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Edit owner name → verify correspondence shows updated name
    # ========================================================================
    def test_phase_3_edit_owner_and_verify_correspondence(self, staff_context: BrowserContext):
        """Phase 3: [SP] Processed tab → search VIN → verify status=Processed →
        Edit → update owner name → open Correspondence History →
        assert LT-260A RECIPIENT NAME = updated owner name"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_processed_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)
            form_processing.expect_status_processed()

            # Open edit mode
            form_processing.click_edit()

            # Update existing owner name field (first owner row)
            owner_name_input = page.locator('input[name*="owner_name"]').first
            owner_name_input.wait_for(state="visible", timeout=10_000)
            owner_name_input.scroll_into_view_if_needed()
            owner_name_input.fill(EDITED_PERSON["name"])
            page.wait_for_timeout(500)

            # Save — wait for loader to disappear, then hold 10s for any
            # background re-generation to complete before opening the modal
            form_processing.click_save()
            try:
                loader = page.locator(".exp-loader-overlay-backdrop")
                loader.wait_for(state="hidden", timeout=15_000)
            except Exception:
                pass
            page.wait_for_timeout(10_000)

            _verify_lt260a_recipient(page, EDITED_PERSON["name"])
        finally:
            page.close()
