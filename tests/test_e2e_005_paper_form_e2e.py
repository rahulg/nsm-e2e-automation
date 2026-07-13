"""
E2E-005: Paper Form End-to-End
Staff Portal only — offline mail → staff enters paper forms.

Workflow: Offline mail → SP: Add from Paper (LT-260, with owner) → Record Payment →
          LT-260 Processed → Issue LT-160B / LT-260A →
          LT-262 Add from Paper → Check DCI → Issue LT-264 & Garage → Track LT-264 → LT-264B →
          Review Court Hearings → Possessory Lien → Save →
          LT-263 Add from Paper → fill sale details → Submit →
          Sold listing → View Correspondence → LT-265

Phases:
  1. [Staff Portal] Add paper LT-260 via "Add from Paper", fill details, submit
  2. [Staff Portal] LT-260 Processed → search VIN → open record → verify status = Processed
  3. [Staff Portal] Record mailed payment — Payments listing → enter VIN → Check → submit
  4. [Staff Portal] LT-262 Add from Paper → Submit → Check DCI → Issue LT-264 & Garage →
                    Track LT-264 (hearing → LT-264B) → Review Court Hearings → Possessory Lien → Save
  5. [Staff Portal] LT-263 Add from Paper → modal VIN → fill sale details → Submit → Issue → OK
  6. [Staff Portal] Sold listing → search VIN → click → View Correspondence → LT-265 entry
"""

import re
from datetime import datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from src.config.test_data import (
    STANDARD_SALE_DATA,
    MAILED_PAYMENT,
)
from src.helpers.data_helper import (
    generate_vin,
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
ADDRESS = generate_address()
PERSON = generate_person()


# ─── Local dialog helpers (poll the modal in, so no fixed sleeps needed) ───
def _confirm_yes(page):
    """Confirm a dialog by clicking Yes."""
    yes = page.locator('mat-dialog-container button:has-text("Yes")').first
    yes.wait_for(state="visible", timeout=10_000)
    yes.click()


def _save_and_confirm(page):
    """Click Save, then confirm the dialog with Yes."""
    save = page.locator('button:has-text("Save")').first
    save.wait_for(state="visible", timeout=15_000)
    save.scroll_into_view_if_needed()
    save.click()
    _confirm_yes(page)


@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.high
@pytest.mark.paper_form
@pytest.mark.fixed
@pytest.mark.smoke
class TestE2E005PaperFormE2E:
    """E2E-005: Paper Form — All forms entered by staff from mailed paperwork"""

    # ========================================================================
    # PHASE 1: Staff Portal — Add paper LT-260
    # ========================================================================
    def test_phase_1_staff_portal_add_paper_lt260(self, staff_page: Page):
        """Phase 1: [Staff Portal] Add paper LT-260 via 'Add from Paper'
        Flow: LT-260 listing → Add from Paper → modal (VIN + Next) →
              fill Make, Year, DATE VEHICLE LEFT, SEARCH LOCATION,
              + Add Owner (owner details), Stolen=No →
              Submit → Yes → green banner → redirect to details page
        """
        page = staff_page

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

        # + Add Owner → owner details
        paper_form.add_owner(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

        # Stolen → No
        paper_form.select_stolen_no()

        # Submit → confirm modal (Yes) → green banner → details page
        paper_form.submit_with_confirmation()

    # ========================================================================
    # PHASE 2: Staff Portal — LT-260 Processed → verify record status
    # ========================================================================
    def test_phase_2_staff_portal_verify_lt260_processed(self, staff_page: Page):
        """Phase 2: [Staff Portal] LT-260 listing → Processed tab → search VIN → open record →
        assert detail page visible → status = Processed.

        Owner path: because Phase 1 attaches an owner, the submitted paper LT-260
        auto-issues LT-160B / LT-260A and lands in the Processed listing on submit,
        so this phase verifies it reached Processed rather than issuing manually.
        """
        page = staff_page

        staff_dashboard = StaffDashboardPage(page)
        lt260_listing = Lt260ListingPage(page)
        form_processing = FormProcessingPage(page)

        staff_dashboard.navigate_to_lt260_listing()
        lt260_listing.click_processed_tab()
        lt260_listing.search_by_vin(TEST_VIN)
        lt260_listing.select_application(0)

        form_processing.expect_detail_page_visible()

        # Verify status = Processed
        form_processing.expect_status_processed()

    # ========================================================================
    # PHASE 3: Staff Portal — Record mailed payment
    # ========================================================================
    def test_phase_3_staff_portal_record_payment(self, staff_page: Page):
        """Phase 3: [Staff Portal] Record mailed payment via Payments listing.
        Flow: Payments listing → Record Mailed Payment → new page → enter VIN → + icon →
              Payment Type=Check → Business/Payer Name → Date Check Was Received →
              Check Number → Submit → green banner → back to listing.
        """
        page = staff_page

        staff_dashboard = StaffDashboardPage(page)
        payments = StaffPaymentsPage(page)

        staff_dashboard.navigate_to_payments()
        payments.record_mailed_payment(
            vin=TEST_VIN,
            payer_name=MAILED_PAYMENT["payer_name"],
            check_number=MAILED_PAYMENT["check_number"],
        )

    # ========================================================================
    # PHASE 4: Staff Portal — LT-262 Add from Paper → Submit → Check DCI →
    #          Issue LT-264 & LT-264 Garage → Track LT-264 (hearing → LT-264B) →
    #          Review Court Hearings → Possessory Lien → Save
    # ========================================================================
    def test_phase_4_staff_portal_lt264_hearing(self, staff_page: Page):
        """Phase 4: [Staff Portal] LT-262 listing → Add from Paper → modal (VIN + Next) →
        Submit → confirm (Yes) → Check DCI tab → Issue LT-264 and LT-264 Garage →
        Track LT-264: log receipt + request judicial hearing → Save → confirm (Yes) →
        assert LT-264B issued-to-requestor toast → Review Court Hearings →
        check Possessory Lien → Save → confirm (Yes) → green banner.

        The LT-264 / Track-LT-264 / LT-264B sequence mirrors E2E-031's proven flow
        (issue_lt264, click_track_lt264_tab, positional log-receipt + hearing checkboxes).
        """
        page = staff_page

        staff_dashboard = StaffDashboardPage(page)
        lt262_listing = Lt262ListingPage(page)
        paper_form = PaperFormPage(page)

        staff_dashboard.navigate_to_lt262_listing()
        lt262_listing.click_add_from_paper()

        # Modal: enter VIN + click Next
        paper_form.fill_modal_vin_and_next(TEST_VIN)

        # Submit → confirmation modal → Yes
        submit_btn = page.locator('button:has-text("Submit")').first
        expect(submit_btn).to_be_visible(timeout=15_000)
        submit_btn.click()
        _confirm_yes(page)
        page.wait_for_timeout(2000)  # settle before Check DCI issuance

        # Check DCI AND NMVTIS tab → Issue LT-264 and LT-264 Garage → confirm (Issue)
        lt262_listing.issue_lt264()

        # Issued banner + TRACK LT-264 tab now available
        expect(
            page.get_by_text("The form has been issued successfully.").first
        ).to_be_visible(timeout=15_000)

        # ── TRACK LT-264: log receipt + request judicial hearing → Save → LT-264B ──
        lt262_listing.click_track_lt264_tab()
        page.wait_for_timeout(2000)  # let the TRACK LT-264 tab render (per E2E-031)

        # Checkbox 1 — "Log Receipt of Signed LT-264 Letters" (enables hearing section)
        log_receipt_cb = page.locator('mat-checkbox').first
        log_receipt_cb.wait_for(state="visible", timeout=10_000)
        if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
            log_receipt_cb.locator("label").click()
            page.wait_for_timeout(1000)  # Angular reveals the hearing section

        # Checkbox 2 — "Select recipients requesting judicial hearing"
        hearing_cb = page.locator('mat-checkbox').nth(1)
        hearing_cb.wait_for(state="visible", timeout=10_000)
        if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
            hearing_cb.locator("label").click()
            page.wait_for_timeout(500)

        # Save → confirm ("…generate LT-264B form and send it to the requestor")
        _save_and_confirm(page)

        # Assert LT-264B issued-to-requestor toast
        expect(
            page.get_by_text(
                re.compile(r"LT-264B form has been successfully issued to the requestor", re.I)
            ).first
        ).to_be_visible(timeout=15_000)

        # ── REVIEW COURT HEARINGS: Possessory Lien → Save ──
        lt262_listing.click_review_hearings_tab()

        possessory_cb = page.locator('mat-checkbox').first
        possessory_cb.wait_for(state="visible", timeout=15_000)
        if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
            possessory_cb.locator("label").click()
            page.wait_for_timeout(1000)  # Angular settle before Save

        _save_and_confirm(page)

        # Verify green banner
        success = page.get_by_text(re.compile(r"success", re.I)).first
        expect(success).to_be_visible(timeout=15_000)

    # ========================================================================
    # PHASE 5: Staff Portal — LT-263 Add from Paper → fill sale details → Submit
    # ========================================================================
    def test_phase_5_staff_portal_add_paper_lt263(self, staff_page: Page):
        """Phase 5: [Staff Portal] LT-263 listing → Add from Paper → modal (VIN + Next) →
        Vehicle Sale Information: TYPE OF SALE=Public, SALE DATE, Lien Amount, Lien For=LABOR →
        Submit → confirm (Yes) → Issue modal → Issue → OK modal → OK.
        """
        page = staff_page

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

    # ========================================================================
    # PHASE 6: Staff Portal — Sold listing → search VIN → View Correspondence → LT-265
    # ========================================================================
    def test_phase_6_staff_portal_verify_sold_lt265(self, staff_page: Page):
        """Phase 6: [Staff Portal] Sold listing → search VIN → click → status=Processed →
        View Correspondence/Documents → Correspondence History modal → LT-265 entry visible.
        """
        page = staff_page

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
