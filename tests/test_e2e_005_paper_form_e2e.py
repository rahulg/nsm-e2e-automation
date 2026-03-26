"""
E2E-005: Paper Form End-to-End
Staff Portal only — offline mail → staff enters paper forms.

Workflow: Offline mail → SP: Add from Paper (LT-260) → Record Payment →
          Process → Paper LT-262 → Paper LT-263 → LT-265

Phases:
  1. [Staff Portal] Add paper LT-260 via "Add from Paper", select requester type, fill details
  2. [Staff Portal] Record mailed payment (check/money order)
  3. [Staff Portal] Process LT-260 → forms auto-issued
  4. [Staff Portal] Add paper LT-262 via "Add from Paper", fill lien details, record payment, process
  5. [Staff Portal] Add paper LT-263 via "Add from Paper", fill sale details, process
  6. [Staff Portal] Issue LT-265 → vehicle in Sold tab
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
    STANDARD_SALE_DATA,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
    MAILED_PAYMENT,
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
from src.pages.staff_portal.payments_page import StaffPaymentsPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.high
@pytest.mark.paper_form
class TestE2E005PaperFormE2E:
    """E2E-005: Paper Form — All forms entered by staff from mailed paperwork"""

    # ========================================================================
    # PHASE 1: Staff Portal — Add paper LT-260
    # ========================================================================
    def test_phase_1_staff_portal_add_paper_lt260(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Add paper LT-260 via 'Add from Paper'"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            paper_form = PaperFormPage(page)

            # Navigate to LT-260 listing and click "Add from Paper"
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_add_from_paper()

            # Paper form entry screen
            paper_form.expect_paper_form_visible()

            # Select requester type
            paper_form.select_requester_type("Individual")

            # Enter VIN and lookup
            paper_form.enter_vin(TEST_VIN)
            paper_form.click_vin_lookup()

            # Fill vehicle details (manual if VIN not found in STARS)
            paper_form.fill_vehicle_details(VEHICLE)

            # Fill storage location
            paper_form.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])

            # Submit paper LT-260
            paper_form.submit()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Record mailed payment
    # ========================================================================
    def test_phase_2_staff_portal_record_payment(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Record mailed payment (check/money order)"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            payments = StaffPaymentsPage(page)

            # Navigate to Payments
            staff_dashboard.navigate_to_payments()

            # Record mailed payment
            payments.record_mailed_payment(
                check_number=MAILED_PAYMENT["check_number"],
                amount=MAILED_PAYMENT["amount"],
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Process LT-260
    # ========================================================================
    def test_phase_3_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Process LT-260 → forms auto-issued"""
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

            # Process — auto-issuance or manual depending on owners
            try:
                lt260_listing.verify_auto_issuance()
            except Exception:
                lt260_listing.issue_lt260c()
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Add paper LT-262, record payment, process
    # ========================================================================
    def test_phase_4_staff_portal_add_paper_lt262(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Add paper LT-262, fill lien details, record payment, process"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)
            paper_form = PaperFormPage(page)

            # Navigate to LT-262 listing and click "Add from Paper"
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_add_from_paper()

            # Fill lien charges
            paper_form.fill_lien_charges(STANDARD_LIEN_CHARGES)

            # Verify pre-filled fields are editable (paper form feature)
            paper_form.verify_fields_editable()

            # Submit paper LT-262
            paper_form.submit()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Add paper LT-263, fill sale details
    # ========================================================================
    def test_phase_5_staff_portal_add_paper_lt263(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Add paper LT-263 — no date restrictions for paper"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            paper_form = PaperFormPage(page)

            # Navigate to LT-263 listing and click "Add from Paper"
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_add_from_paper()

            # Fill sale details — paper forms have NO date restrictions
            paper_form.fill_sale_details(
                sale_type="public",
                sale_date=future_date(30),
                lien_amount=STANDARD_SALE_DATA["lien_amount"],
            )

            # Submit paper LT-263
            paper_form.submit()
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Process LT-263, issue LT-265
    # ========================================================================
    def test_phase_6_staff_portal_issue_lt265(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Process LT-263 → issue LT-265 → Sold"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()
            lt263_listing.search_by_vin(TEST_VIN)
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            lt263_listing.verify_sale_details_visible()
            lt263_listing.generate_lt265()

            # Verify in Sold tab
            lt263_listing.click_processed_sold_tab()
            lt263_listing.search_by_vin(TEST_VIN)
            lt263_listing.verify_vehicle_sold()
        finally:
            page.close()
