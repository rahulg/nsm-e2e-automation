"""
E2E-007: Rejection and Resubmission
PP: LT-260 → SP: Reject → PP: Notification + Correct + Resubmit → SP: Process

Phases:
  1. [Public Portal]  Submit LT-260 with incomplete information
  2. [Staff Portal]   Reject LT-260 with rejection reasons
  3. [Staff Portal]   Verify application in Rejected tab
  4. [Public Portal]  Verify rejection notification/reasons visible
  5. [Public Portal]  Resubmit corrected LT-260
  6. [Staff Portal]   Process resubmitted LT-260 — auto-issuance
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    SAMPLE_DOC_PATH,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
    REJECTION_REASONS,
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
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
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
@pytest.mark.fixed
class TestE2E007RejectionResubmission:
    """E2E-007: Rejection and Resubmission — LT-260 reject → correct → resubmit"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260 (with incomplete info)
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260 with intentionally incomplete data"""
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
    # PHASE 2: Staff Portal — Reject LT-260
    # ========================================================================
    def test_phase_2_staff_portal_reject_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Open LT-260, reject with reasons"""
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

            # Reject with reasons
            lt260_listing.reject_application(REJECTION_REASONS)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Verify in Rejected tab
    # ========================================================================
    def test_phase_3_staff_portal_verify_rejected(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Verify application moved to Rejected tab"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_rejected_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.expect_applications_visible()
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Public Portal — Verify rejection notification
    # ========================================================================
    def test_phase_4_public_portal_verify_rejection(self, public_context: BrowserContext):
        """Phase 4: [Public Portal] Verify rejection notification and reasons visible"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)

            # Verify rejection status and reasons are visible
            dashboard.expect_application_rejected()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Resubmit corrected LT-260
    # ========================================================================
    def test_phase_5_public_portal_resubmit_lt260(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Correct and resubmit LT-260"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            # Resubmit — VIN lookup pre-fills vehicle details, so skip fill_vehicle_details
            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()
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
    # PHASE 6: Staff Portal — Process resubmitted LT-260
    # ========================================================================
    def test_phase_6_staff_portal_process_resubmission(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Process resubmitted LT-260 — same as E2E-001 Phase 2.
        Edit → add owner → stolen=No → save → Issue 160B and 260A → verify Processed.
        """
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

            # Edit → add owner → stolen=No → save
            form_processing.click_edit()
            form_processing.add_owner(
                PERSON["name"], ADDRESS["street"], ADDRESS["zip"]
            )
            form_processing.select_stolen_no()
            form_processing.click_save()

            # Issue 160B and 260A
            form_processing.issue_160b_and_260a()

            # Verify success and Processed status
            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()
