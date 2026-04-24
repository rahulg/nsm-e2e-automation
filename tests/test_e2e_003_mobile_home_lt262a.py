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

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
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
TEST_VIN = generate_vin()
VEHICLE = {
    "make": "Ford",
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
        """Phase 1: [Public Portal] Submit LT-260 with body type = Manufactured Home.
        Same as E2E-001 Phase 1 — VIN modal handled at submit via submit_with_vin_image().
        """
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Process LT-260 (Rented Mobile Home)
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Process LT-260 — same as E2E-001 Phase 2 but select
        RENTED radio for Rented Mobile Home before saving.
        Edit → select RENTED → add owner → stolen=No → save → Issue 160B and 260A.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()

            # Retry search up to 3 times — new submission may not be indexed immediately
            for attempt in range(3):
                lt260_listing.search_by_vin(TEST_VIN)
                try:
                    lt260_listing.vin_links.first.wait_for(state="visible", timeout=8_000)
                    break
                except Exception:
                    if attempt < 2:
                        page.wait_for_timeout(5000)
                        page.reload()
                        page.wait_for_load_state("networkidle")
                        lt260_listing.click_to_process_tab()

            lt260_listing.select_application(0)

            form_processing.expect_detail_page_visible()
            form_processing.click_edit()

            # Select RENTED radio for Rented Mobile Home (mobile home specific field)
            form_processing.select_rented_mobile_home()

            # Add owner → stolen=No → save
            form_processing.add_owner(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            form_processing.select_stolen_no()
            form_processing.click_save()

            # Issue 160B and 260A
            form_processing.issue_160b_and_260a()

            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262A (mobile home form)
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262a(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Search VIN → Submit LT-262A → navigate sections via Next.

        Sections A–D : Next (no data entry)
        Section E    : Notice of Sale — date (+21 days), address, place of sale → Next
        Section F    : Phone → Next
        Section G    : Next
        Terms        : check all → name → date → Submit
        Verify green banner and status = 'LT-262A Submitted' on dashboard.
        """
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_notice_storage_tab()
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(1000)
            dashboard.select_application(0)

            # Click Submit LT-262A
            dashboard.click_submit_lt262a()

            lt262a = Lt262aFormPage(page)
            lt262a.expect_form_visible()

            # Sections A–D: click Next 4 times (no data entry)
            lt262a.click_next_sections(4)

            # Section E: Notice of Sale — date (+21 days), address, zip, place of sale
            lt262a.fill_section_e_notice_of_sale(
                address=ADDRESS["street"],
                place_of_sale="Test Storage Facility",
                zip_code=ADDRESS["zip"],
            )

            # Section F: Phone → Next
            lt262a.fill_phone(PERSON["phone"])

            # Section G: Next
            lt262a.click_next_sections(1)

            # Terms & Conditions: check all → name → date → Submit
            lt262a.accept_terms_and_submit(PERSON["name"])

            # Verify green banner
            lt262a.expect_success_banner()

            # Verify status on dashboard
            page.wait_for_timeout(2000)
            expect(page.get_by_text(re.compile(r"LT-262A Submitted|262A Submitted", re.I)).first).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Process LT-262A → issue LT-265 directly
    # ========================================================================
    # PHASE 4: Staff Portal — Issue LT-265 and LT-265A from LT-262A listing
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262a(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] LT-262A listing → filter by VIN → click application →
        Issue LT-265 and LT-265A → confirm modal → green banner → status = Processed.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262a_listing = Lt262aListingPage(page)

            staff_dashboard.navigate_to_lt262a_listing()
            lt262a_listing.search_by_vin(TEST_VIN)
            lt262a_listing.select_application(0)

            lt262a_listing.issue_lt265_and_lt265a()

            lt262a_listing.expect_success_banner()
            lt262a_listing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Verify in Sold listing + LT-265A in correspondence
    # ========================================================================
    def test_phase_5_staff_portal_verify_sold(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Sold listing → filter by VIN → click → status = Processed
        → View Correspondence/Documents → Correspondence History modal → LT-265A entry.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            from src.pages.staff_portal.sold_listing_page import SoldListingPage
            sold_listing = SoldListingPage(page)

            staff_dashboard.navigate_to_sold()
            sold_listing.search_by_vin(TEST_VIN)
            sold_listing.select_application(0)

            # Verify Processed status
            expect(
                page.get_by_text(re.compile(r"Processed", re.I)).first
            ).to_be_visible(timeout=15_000)

            # View Correspondence/Documents → verify LT-265A entry (mobile home path)
            sold_listing.verify_lt265_in_correspondence(entry="LT-265A")
        finally:
            page.close()
