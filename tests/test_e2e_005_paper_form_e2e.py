"""
E2E-005: Paper Form End-to-End
Staff Portal only — offline mail → staff enters paper forms.

Workflow: Offline mail → SP: Add from Paper (LT-260) → Record Payment →
          LT-260 To Process → Issue LT-260C →
          LT-262 To Process → Submit → Check DCI → Issue LT-262B →
          Review Court Hearings → Possessory Lien → Save →
          LT-263 Add from Paper → fill sale details → Submit →
          Sold listing → View Correspondence → LT-265

Phases:
  1. [Staff Portal] Add paper LT-260 via "Add from Paper", fill details, submit
  2. [Staff Portal] Record mailed payment — Payments listing → enter VIN → Check → submit
  3. [Staff Portal] LT-260 To Process → search VIN → Issue LT-260C → confirm → status=Processed
  4. [Staff Portal] LT-262 To Process → search VIN → Submit → Check DCI → Generate LT-262B →
                    Review Court Hearings → Possessory Lien → Save → confirm
  5. [Staff Portal] LT-263 Add from Paper → modal VIN → fill sale details → Submit → Issue → OK
  6. [Staff Portal] Sold listing → search VIN → click → View Correspondence → LT-265 entry
"""

import re
from datetime import datetime, timedelta

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
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage
from src.pages.staff_portal.payments_page import StaffPaymentsPage
from src.pages.staff_portal.sold_listing_page import SoldListingPage


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

            # Navigate to LT-260 listing and click "Add from Paper"
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_add_from_paper()

            # Modal: enter VIN and click Next
            paper_form.fill_modal_vin_and_next(TEST_VIN)

            # Form: Make (autocomplete) — Year first, then Make
            paper_form.fill_year("2018")
            paper_form.fill_make("TOY")

            # Date Vehicle Left
            paper_form.fill_date_vehicle_left(past_date(30))

            # Under "Vehicle Storage Details": SEARCH LOCATION
            paper_form.fill_search_location("Garage")

            # Stolen → No
            paper_form.select_stolen_no()

            # Submit → confirm modal (Yes) → green banner → details page
            paper_form.submit_with_confirmation()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Record mailed payment
    # ========================================================================
    def test_phase_2_staff_portal_record_payment(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Record mailed payment via Payments listing.
        Flow: Payments listing → Record Mailed Payment → new page → enter VIN → + icon →
              Payment Type=Check → Business/Payer Name → Date Check Was Received →
              Check Number → Submit → green banner → back to listing.
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
    # PHASE 3: Staff Portal — LT-260 To Process → Issue LT-260C
    # ========================================================================
    def test_phase_3_staff_portal_issue_lt260c(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] LT-260 listing → search VIN → click → Issue LT-260C →
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
            lt260_listing.select_application(0)

            form_processing.expect_detail_page_visible()

            # Click Issue LT-260C
            lt260_listing.issue_lt260c()

            # Confirmation modal → Issue
            issue_btn = page.locator('mat-dialog-container button:has-text("Issue")').first
            issue_btn.wait_for(state="visible", timeout=10_000)
            issue_btn.click()
            page.wait_for_timeout(2000)

            # Verify green banner
            form_processing.expect_issued_success_toast()

            # Verify status = Processed
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — LT-262 To Process → Submit → Check DCI →
    #          Generate LT-262B → Review Court Hearings → Possessory Lien → Save
    # ========================================================================
    def test_phase_4_staff_portal_lt262b_court_hearing(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] LT-262 listing → Add from Paper → modal (VIN + Next) →
        Submit → confirm (Yes) → Check DCI tab → Generate LT-262B → confirm (Issue) →
        Review Court Hearings → check Possessory Lien → Save → confirm (Yes) → green banner.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)
            paper_form = PaperFormPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_add_from_paper()

            # Modal: enter VIN + click Next
            paper_form.fill_modal_vin_and_next(TEST_VIN)

            # Submit button → confirmation modal → Yes
            submit_btn = page.locator('button:has-text("Submit")').first
            expect(submit_btn).to_be_visible(timeout=15_000)
            submit_btn.click()
            page.wait_for_timeout(1000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(2000)

            # Check DCI AND NMVTIS tab → Generate LT-262B → confirm (Issue)
            lt262_listing.issue_lt262b()
            page.wait_for_timeout(1000)

            # REVIEW COURT HEARINGS tab — check "Judgment in action of Possessory Lien"
            possessory_cb = page.locator('mat-checkbox').first
            possessory_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
                possessory_cb.locator("label").click()
                page.wait_for_timeout(1000)

            # Save
            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=15_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(1000)

            # Confirmation modal → Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(2000)

            # Verify green banner
            success = page.get_by_text(re.compile(r"success", re.I)).first
            expect(success).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — LT-263 Add from Paper → fill sale details → Submit
    # ========================================================================
    def test_phase_5_staff_portal_add_paper_lt263(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] LT-263 listing → Add from Paper → modal (VIN + Next) →
        Vehicle Sale Information: TYPE OF SALE=Public, SALE DATE, Lien Amount, Lien For=LABOR →
        Submit → confirm (Yes) → Issue modal → Issue → OK modal → OK.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            paper_form = PaperFormPage(page)

            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_add_from_paper()

            # Modal: enter VIN + click Next
            paper_form.fill_modal_vin_and_next(TEST_VIN)

            # Fill sale details — skip Sunday (not accepted as a sale date)
            sale_dt = datetime.now() - timedelta(days=5)
            if sale_dt.weekday() == 6:  # 6 = Sunday
                sale_dt += timedelta(days=1)
            paper_form.fill_lt263_sale_details(
                sale_type="public",
                sale_date=sale_dt.strftime("%Y-%m-%d"),
                lien_amount=STANDARD_SALE_DATA["lien_amount"],
            )

            # Submit → Yes → Issue → OK
            paper_form.submit_paper_lt263()
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Sold listing → search VIN → View Correspondence → LT-265
    # ========================================================================
    def test_phase_6_staff_portal_verify_sold_lt265(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Sold listing → search VIN → click → status=Processed →
        View Correspondence/Documents → Correspondence History modal → LT-265 entry visible.
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            sold_listing = SoldListingPage(page)

            staff_dashboard.navigate_to_sold()
            sold_listing.search_by_vin(TEST_VIN)
            sold_listing.expect_applications_visible()
            sold_listing.select_application(0)

            # Verify status = Processed
            expect(
                page.get_by_text(re.compile(r"Processed", re.I)).first
            ).to_be_visible(timeout=15_000)

            # View Correspondence/Documents → modal with LT-265 entry
            sold_listing.verify_lt265_in_correspondence()
        finally:
            page.close()
