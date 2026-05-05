"""
E2E-025: Paper Form Submitted Date
SP: Add from Paper LT-260 → Record Mailed Payment →
SP: LT-260 To Process → verify "Date Submitted" = today → Issue LT-260C → Processed

Phases:
  1. [Staff Portal] Add paper LT-260 via "Add from Paper"
  2. [Staff Portal] Record mailed payment
  3. [Staff Portal] LT-260 To Process → search VIN → verify Date Submitted = today →
                    Issue LT-260C → confirm → status=Processed
"""

import re
from datetime import datetime

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_SALE_DATA,
    MAILED_PAYMENT,
)
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    generate_person,
    past_date,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
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
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.paper_form
@pytest.mark.fixed
class TestE2E025PaperFormSubmittedDate:
    """E2E-025: Paper form — verify Date Submitted column = today after Add from Paper"""

    # ========================================================================
    # PHASE 1: Staff Portal — Add paper LT-260
    # ========================================================================
    def test_phase_1_staff_portal_add_paper_lt260(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Add paper LT-260 via 'Add from Paper'
        Flow: LT-260 listing → Add from Paper → modal (VIN + Next) →
              fill Make, Year, DATE VEHICLE LEFT, SEARCH LOCATION, Stolen=No →
              Submit → Yes → green banner → redirect to details page
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            paper_form = PaperFormPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_add_from_paper()

            paper_form.fill_modal_vin_and_next(TEST_VIN)

            paper_form.fill_year("2018")
            paper_form.fill_make("TOY")
            paper_form.fill_date_vehicle_left(past_date(30))
            paper_form.fill_search_location("Garage")
            paper_form.select_stolen_no()
            paper_form.submit_with_confirmation()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Record mailed payment
    # ========================================================================
    def test_phase_2_staff_portal_record_payment(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Record mailed payment via Payments listing.
        Flow: Payments listing → Record Mailed Payment → enter VIN → Check → submit
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            payments = StaffPaymentsPage(page)

            staff_dashboard.navigate_to_payments()
            payments.record_mailed_payment(
                vin=TEST_VIN,
                payer_name=MAILED_PAYMENT["payer_name"],
                check_number=MAILED_PAYMENT["check_number"],
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — LT-260 To Process → verify Date Submitted → Issue LT-260C
    # ========================================================================
    def test_phase_3_staff_portal_issue_lt260c(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] LT-260 listing → search VIN →
        verify Date Submitted column = today → click → Issue LT-260C →
        confirm modal (Issue) → green banner → status = Processed.
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

            # Verify "Date Submitted" column shows today's date (MM-DD-YYYY format)
            today = datetime.now().strftime("%m-%d-%Y")
            date_submitted = page.locator(
                f"//td[contains(@class,'datesubmitted') or contains(@class,'submittedDate') or "
                f"contains(@class,'date')]//span[contains(text(),'{today}')] | "
                f"//td//span[contains(text(),'{today}')]"
            ).first
            expect(date_submitted).to_be_visible(timeout=10_000)

            lt260_listing.select_application(0)
            form_processing.expect_detail_page_visible()

            # Click Issue LT-260C
            lt260_listing.issue_lt260c()

            # Confirmation modal → Issue
            issue_btn = page.locator('mat-dialog-container button:has-text("Issue")').first
            issue_btn.wait_for(state="visible", timeout=10_000)
            issue_btn.click()
            page.wait_for_timeout(2000)

            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()
