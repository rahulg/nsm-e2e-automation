"""
E2E-009: Vehicle Reclaim Mid-Process (Cross-Portal)
PP: LT-260 → SP: Process → PP: LT-262 → SP: Process LT-264 →
PP: Vehicle Reclaim → SP: Close File

Phases:
  1. [Public Portal]  Submit LT-260
  2. [Staff Portal]   Process LT-260
  3. [Public Portal]  Submit LT-262 with payment
  4. [Staff Portal]   Process LT-262, issue LT-264
  5. [Public Portal]  Initiate Vehicle Reclaim — pay pending amount
  6. [Staff Portal]   Close file with closing remarks
  7. [Public Portal]  Verify application in Closed tab, no further forms submittable
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
    CLOSE_FILE_REMARKS,
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
from src.pages.public_portal.vehicle_reclaim_page import VehicleReclaimPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
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
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.alternate
@pytest.mark.critical
class TestE2E009VehicleReclaim:
    """E2E-009: Vehicle Reclaim — owner reclaims mid-process, file closed"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260"""
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
        """Phase 2: [Staff Portal] Process LT-260"""
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
            lt260_listing.verify_auto_issuance()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Submit LT-262 with payment"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)
            dashboard.expect_application_processed()
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
    # PHASE 4: Staff Portal — Process LT-262, issue LT-264
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Process LT-262, issue LT-264 via Nordis"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)
            lt262_listing.verify_lien_details_visible()
            lt262_listing.issue_lt264()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Initiate Vehicle Reclaim
    # ========================================================================
    def test_phase_5_public_portal_vehicle_reclaim(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Initiate Vehicle Reclaim — pay pending amount"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)

            reclaim = VehicleReclaimPage(page)
            reclaim.click_vehicle_reclaim()
            reclaim.expect_pending_amount_displayed()
            reclaim.confirm_and_pay()
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Close file
    # ========================================================================
    def test_phase_6_staff_portal_close_file(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Close file with closing remarks"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_all_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Close file using page object method
            form_processing.close_file(remarks=CLOSE_FILE_REMARKS)

            # Verify in Closed tab
            lt262_listing.click_closed_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.expect_applications_visible()
        finally:
            page.close()

    # ========================================================================
    # PHASE 7: Public Portal — Verify closed, no further forms
    # ========================================================================
    def test_phase_7_public_portal_verify_closed(self, public_context: BrowserContext):
        """Phase 7: [Public Portal] Application in Closed tab, no further forms submittable"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)

            # No further forms should be submittable
            dashboard.expect_file_locked()
        finally:
            page.close()
