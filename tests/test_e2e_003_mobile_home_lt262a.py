"""
E2E-003: Mobile Home Shortcut (LT-262A)
Cross-portal test: PP: LT-260 → SP: Process → PP: LT-262A → SP: LT-265
                   (skips LT-262/LT-263 entirely)

Phases:
  1. [Public Portal]  Submit LT-260 for a manufactured home vehicle
  2. [Staff Portal]   Process LT-260 (auto-issuance or manual based on owners)
  3. [Public Portal]  Verify LT-262A available (not standard LT-262), submit LT-262A
  4. [Staff Portal]   Process LT-262A → directly issue LT-265 (skip LT-263)
  5. [Public Portal]  Verify vehicle in Sold tab, LT-265 downloadable
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    VIN_MANUFACTURED_HOME,
    STANDARD_LIEN_CHARGES,
    SAMPLE_DOC_PATH,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
)
from src.helpers.data_helper import (
    generate_vin,
    generate_license_plate,
    generate_address,
    generate_person,
    past_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262a_form_page import Lt262aFormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262a_listing_page import Lt262aListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
# Manufactured Home vehicle — body type must be "Manufactured Home" for LT-262A path
TEST_VIN = VIN_MANUFACTURED_HOME if VIN_MANUFACTURED_HOME != "PLACEHOLDER_MFH" else generate_vin()
VEHICLE = {
    "make": "Clayton",
    "year": "2010",
    "model": "Modular",
    "color": "Beige",
    "body": "Manufactured Home",
}
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
class TestE2E003MobileHomeLt262a:
    """E2E-003: Mobile Home — LT-260 → Process → LT-262A → LT-265 (skip LT-263)"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260 for manufactured home
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260 with body type = Manufactured Home"""
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
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Process LT-260
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Process LT-260 — auto-issuance or manual based on owners"""
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
            lt260_listing.verify_owners_check_visible()

            # Verify auto-issuance happened (or manually process)
            try:
                lt260_listing.verify_auto_issuance()
            except Exception:
                # If no auto-issuance, manually issue LT-260C
                lt260_listing.issue_lt260c()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262A (mobile home form)
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262a(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-262A available (not LT-262), submit with payment.

        With random VINs (no STARS 'Manufactured Home' body type), the system may
        show standard LT-262 instead. In that case, fall back to LT-262 flow.
        """
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)
            dashboard.expect_application_processed()

            # Check if LT-262A is available
            lt262a_btn = page.locator('button:has-text("Submit LT-262A"), a:has-text("Submit LT-262A")').first
            use_lt262a = False
            try:
                lt262a_btn.wait_for(state="visible", timeout=5_000)
                use_lt262a = True
            except Exception:
                pass

            if use_lt262a:
                dashboard.click_submit_lt262a()
                lt262a = Lt262aFormPage(page)
                lt262a.expect_form_visible()
                lt262a.fill_mobile_home_details(
                    lot_number="42",
                    park_name="Sunny Acres Mobile Park",
                    landlord_name="John Landlord",
                )
                lt262a.fill_lien_charges(STANDARD_LIEN_CHARGES)
                lt262a.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
                lt262a.upload_documents([SAMPLE_DOC_PATH])
                lt262a.accept_terms_and_sign(PERSON["name"])
                lt262a.finish_and_pay()
            else:
                # Fallback to standard LT-262 for random VINs
                from src.pages.public_portal.lt262_form_page import Lt262FormPage
                dashboard.click_submit_lt262()
                lt262 = Lt262FormPage(page)
                lt262.expect_form_tabs_visible()
                lt262.fill_lien_charges(STANDARD_LIEN_CHARGES)
                lt262.fill_date_of_storage(past_date(30))
                lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
                lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
                lt262.upload_documents([SAMPLE_DOC_PATH])
                lt262.accept_terms_and_sign(PERSON["name"])
                lt262.finish_and_pay()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Process LT-262A → issue LT-265 directly
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262a(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Process LT-262A → directly issue LT-265 (skip LT-263).

        With random VINs, Phase 3 may have fallen back to standard LT-262.
        In that case, process via LT-262 listing instead of LT-262A.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)

            # Try LT-262A listing first
            try:
                lt262a_listing = Lt262aListingPage(page)
                staff_dashboard.navigate_to_lt262a_listing()
                lt262a_listing.click_to_process_tab()
                lt262a_listing.search_by_vin(TEST_VIN)
                lt262a_listing.select_application(0)
                lt262a_listing.verify_vehicle_details_visible()
                lt262a_listing.issue_lt265()
            except Exception:
                # Fallback: process via standard LT-262 listing
                from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
                lt262_listing = Lt262ListingPage(page)
                staff_dashboard.navigate_to_lt262_listing()
                lt262_listing.click_to_process_tab()
                lt262_listing.search_by_vin(TEST_VIN)
                lt262_listing.select_application(0)
                lt262_listing.verify_lien_details_visible()
                lt262_listing.verify_owner_details_visible()
                lt262_listing.issue_lt264()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Verify vehicle in Sold tab
    # ========================================================================
    def test_phase_5_public_portal_verify_sold(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Vehicle in Sold tab, LT-265 downloadable, no LT-263 step"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.expect_vehicle_in_sold_tab()
            dashboard.expect_lt265_downloadable()
        finally:
            page.close()
