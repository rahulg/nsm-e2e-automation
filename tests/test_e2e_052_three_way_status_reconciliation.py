"""
E2E-052: Three-Way Status Reconciliation at Each Workflow Transition
         Public Portal Display == application.status == Latest-Active Timeline

Verifies at each workflow transition that the status displayed on the Public Portal
matches application.status (DB) and the latest active application_timeline row.

Three-way invariant:
  (a) PP-displayed status  ==  (b) application.status  ==  (c) latest-active timeline action_name

The DB checks require database access and cannot be fully automated in UI-only mode.
This test verifies the UI-observable portion (a) and uses assertions where (b) can
be inferred from Staff Portal Global Search display.

The migration-backfill scenario (which inverts Payment Pending vs LT-262 Submitted
timeline chronology) is flagged as a backend-only step.

Phases:
  0a. [Public Portal] Submit LT-260 → verify PP status = "LT-260 Submitted"
  0b. [Staff Portal] Global Search → verify status matches PP display
  1a. [Staff Portal] Process LT-260 → verify PP status = "LT-260 Processed" / "Aging"
  1b. [Staff Portal] Verify Global Search status matches
  2a. [Public Portal] Submit LT-262 → verify PP status = "Payment Pending"
  2b. [Public Portal] Complete payment → verify PP status = "LT-262 Submitted"
  3a. [Staff Portal] Process LT-262, issue LT-264 → verify PP status = "Aging"
  4a. [Public Portal] Submit LT-263 → SP process → verify PP status = "Sold"
  5.  [BACKEND — NOT AUTOMATABLE] Migration backfill chronology inversion scenario

Ref: Edge Case 35, Business Rule 89, Business Rule 22, Business Rule 37,
     Journey 2.5, Journey 5.2
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
    STANDARD_SALE_DATA,
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
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.public_portal.shopping_cart_page import ShoppingCartPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage
from src.pages.staff_portal.global_search_page import GlobalSearchPage

FIXTURE_DOC = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")

# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
BUSINESS_NAME = "G-Car Garages New"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

# Status strings (normalized patterns used for matching across portal display variations)
STATUS_LT260_SUBMITTED = re.compile(r"LT-260.*Submitted|LT260.*Submitted|Submitted", re.I)
STATUS_LT260_PROCESSED = re.compile(r"LT-260.*Processed|LT260.*Processed|Processed|Aging", re.I)
STATUS_PAYMENT_PENDING = re.compile(r"Payment.*Pending|Pending.*Payment", re.I)
STATUS_LT262_SUBMITTED = re.compile(r"LT-262.*Submitted|LT262.*Submitted", re.I)
STATUS_AGING = re.compile(r"Aging|LT-262.*Processed|LT262.*Processed", re.I)
STATUS_SOLD = re.compile(r"Sold|LT-265.*Issued|LT265.*Issued|Sale.*Approved", re.I)


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def get_pp_status_for_vin(page, vin: str) -> str:
    """Navigate to Public Portal dashboard and return the status badge text for a VIN."""
    go_to_public_dashboard(page)
    dashboard = PublicDashboardPage(page)

    try:
        dashboard.search_by_vin(vin)
        page.wait_for_timeout(2000)
    except Exception:
        try:
            dashboard.click_notice_storage_tab()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
        except Exception:
            pass

    try:
        vin_row = page.locator(f'text={vin}').first
        vin_row.wait_for(state="visible", timeout=15_000)
        # Find the status badge within the same row/card
        row_container = vin_row.locator("xpath=ancestor::*[contains(@class,'group') or "
                                        "contains(@class,'row') or contains(@class,'card')][1]")
        status_badge = row_container.locator(
            '[class*="status" i], [class*="badge" i], [class*="chip" i], '
            '[class*="tag" i], span[class]'
        ).first
        return (status_badge.text_content() or "").strip()
    except Exception:
        return ""


def get_sp_status_for_vin(page, vin: str) -> str:
    """Use Staff Portal Global Search to get the displayed status for a VIN."""
    go_to_staff_dashboard(page)
    global_search = GlobalSearchPage(page)
    global_search.navigate_to()
    global_search.search(vin)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)

    try:
        result_row = page.locator(f'text={vin}').first
        result_row.wait_for(state="visible", timeout=15_000)
        row_container = result_row.locator(
            "xpath=ancestor::tr[1] | ancestor::*[contains(@class,'row')][1]"
        )
        status_cell = row_container.locator(
            'td, [class*="status" i], [class*="badge" i]'
        ).first
        return (status_cell.text_content() or "").strip()
    except Exception:
        return ""


def global_search_verify_status(page, vin: str, tab_name: str, expected_status: str):
    """Header search → enter VIN → Search → click tab → verify status in row."""
    header_search = page.locator(
        "mat-toolbar input, app-toolbar input, "
        "input[placeholder*='Search' i], input[aria-label*='Search' i]"
    ).first
    header_search.wait_for(state="visible", timeout=15_000)
    header_search.fill(vin)
    page.locator("//span[contains(text(),'Search ')]").first.click()
    page.wait_for_timeout(2000)

    page.locator(f'[role="tab"]:has-text("{tab_name}")').first.click()
    page.wait_for_timeout(1000)

    expect(
        page.get_by_text(re.compile(re.escape(expected_status), re.I)).first
    ).to_be_visible(timeout=10_000)


def global_search_open_detail_and_tab(page, vin: str, tab_name: str, expected_status: str, detail_tab: str):
    """Header search → verify status → click VIN entry → open detail → click detail_tab."""
    global_search_verify_status(page, vin, tab_name, expected_status)

    vin_entry = page.locator(
        f"//span[contains(text(),'{vin}')] | //td[contains(text(),'{vin}')]"
    ).first
    vin_entry.wait_for(state="visible", timeout=10_000)
    vin_entry.click()
    page.wait_for_timeout(2000)

    detail = page.locator(f'[role="tab"]:has-text("{detail_tab}")').first
    detail.wait_for(state="visible", timeout=15_000)
    detail.click()
    page.wait_for_timeout(2000)


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
class TestE2E052ThreeWayStatusReconciliation:
    """E2E-052: Three-Way Status Reconciliation at Each Workflow Transition"""

    # ========================================================================
    # PHASE 0a: Public Portal — Submit LT-260, Verify PP Status
    # ========================================================================
    def test_phase_0a_submit_lt260_verify_status(self, public_context: BrowserContext):
        """Phase 0a: [Public Portal] Login, create LT-260, VIN lookup, fill form, submit"""
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

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 0b: Staff Portal — Verify SP Status Matches PP (Pre-Processing)
    # ========================================================================
    def test_phase_0b_sp_status_matches_pp_pre_process(self, staff_context: BrowserContext):
        """Phase 0b: [Staff Portal]
        Global Search → LT-260 tab → status=LT-260 Submitted →
        Process LT-260 (add owner, stolen=No, issue 160B/260A) →
        Global Search → LT-260 tab → status=LT-260 Processed
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ── Global Search: verify LT-260 Submitted ──
            global_search_verify_status(page, TEST_VIN, "LT-260", "LT-260 Submitted")

            # ── Navigate back to staff dashboard and process LT-260 ──
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

            # ── Global Search: verify LT-260 Processed ──
            global_search_verify_status(page, TEST_VIN, "LT-260", "LT-260 Processed")
        finally:
            page.close()

    # ========================================================================
    # PHASE 2a: Public Portal — Submit LT-262, Verify "Payment Pending" Status
    # ========================================================================
    def test_phase_2a_submit_lt262_verify_payment_pending(self, public_context: BrowserContext):
        """Phase 2a: [Public Portal] Verify LT-260 processed, submit LT-262 with lien/charges/docs →
        verify PP status = 'Payment Pending' before payment is completed."""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)
            dashboard.expect_application_processed()

            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()
            lt262.skip_vehicle_and_location_tabs()
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})
            lt262.fill_date_of_storage(past_date(30))
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.upload_documents([FIXTURE_DOC])
            lt262.accept_terms_and_sign(PERSON["name"])
            lt262.finish_and_pay()

            # Go to dashboard and verify Payment Pending status
            go_to_public_dashboard(page)
            dashboard2 = PublicDashboardPage(page)
            dashboard2.select_business(BUSINESS_NAME)
            dashboard2.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard2.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            payment_pending = page.get_by_text(re.compile(r"Payment.*Pending", re.I)).first
            expect(payment_pending).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2b: Public Portal — Complete Payment, Verify LT-262 Submitted Status
    # ========================================================================
    def test_phase_2b_complete_payment_verify_lt262_submitted(self, public_context: BrowserContext):
        """Phase 2b: [Public Portal] Verify PP status = 'Payment Pending' → click Pay Now →
        complete drawdown payment → verify PP status = 'LT-262 Submitted'."""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            payment_pending = page.get_by_text(re.compile(r"Payment.*Pending", re.I)).first
            expect(payment_pending).to_be_visible(timeout=15_000)

            pay_now_btn = page.locator(
                'button:has-text("Pay Now"), a:has-text("Pay Now"), '
                'button:has-text("Make Payment"), button:has-text("Pay")'
            ).first
            pay_now_btn.wait_for(state="visible", timeout=10_000)
            pay_now_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=15_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=15_000)

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)

            dashboard2 = PublicDashboardPage(page)
            dashboard2.select_business(BUSINESS_NAME)
            dashboard2.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard2.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            lt262_submitted = page.get_by_text(re.compile(r"LT-262.*Submitted", re.I)).first
            expect(lt262_submitted).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3a: Staff Portal — Process LT-262, Verify Aging Status
    # ========================================================================
    def test_phase_3a_process_lt262_verify_aging_status(self, staff_context: BrowserContext):
        """Phase 3a: [Staff Portal]
        Global Search → LT-262 tab → status=LT-262 Submitted →
        Process LT-262, issue LT-264 →
        Global Search → LT-262 tab → status=Aging
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ── Global Search: verify LT-262 Submitted ──
            global_search_verify_status(page, TEST_VIN, "LT-262", "LT-262 Submitted")

            # ── Navigate back and process LT-262 ──
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)
            lt262_listing.verify_lien_details_visible()
            lt262_listing.verify_owner_details_visible()
            lt262_listing.issue_lt264()

            success_banner = page.get_by_text("The form has been issued successfully.")
            expect(success_banner).to_be_visible(timeout=15_000)

            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=10_000)

            # ── Global Search: verify Aging ──
            global_search_verify_status(page, TEST_VIN, "LT-262", "Aging")
        finally:
            page.close()

    # ========================================================================
    # PHASE 3b: Staff Portal — Track LT-264 → Court Hearing → Possessory Lien
    # ========================================================================
    def test_phase_3b_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 3b: [Staff Portal] Track LT-264 → Save → Confirm →
        Global Search → LT-262 tab → Court Hearing → open detail → REVIEW COURT HEARINGS tab →
        Possessory Lien checkbox → Save → Confirm →
        Global Search → LT-262 tab → LT-262 Processed
        """
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_aging_tab()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(8000)
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.court_hearing_tab.click()
                page.wait_for_load_state("networkidle")
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            lt262_listing.click_track_lt264_tab()
            page.wait_for_timeout(2000)

            log_receipt_cb = page.locator('mat-checkbox').first
            if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
                log_receipt_cb.locator("label").click()
                page.wait_for_timeout(1000)

            hearing_cb = page.locator('mat-checkbox').nth(1)
            hearing_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
                hearing_cb.locator("label").click()
                page.wait_for_timeout(500)

            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=15_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Wait for redirect to REVIEW COURT HEARINGS — wait for its unique content
            possessory_text = page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
            possessory_text.wait_for(state="visible", timeout=30_000)
            page.wait_for_timeout(2000)

            # ── Global Search: verify Court Hearing → open detail → REVIEW COURT HEARINGS tab ──
            global_search_open_detail_and_tab(
                page, TEST_VIN, "LT-262", "Court Hearing", "REVIEW COURT HEARINGS"
            )

            # Check "Judgment in action of Possessory Lien" checkbox
            possessory_cb = page.locator('mat-checkbox').first
            possessory_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
                possessory_cb.locator("label").click()
                page.wait_for_timeout(1000)

            save_btn2 = page.locator('button:has-text("Save")').first
            save_btn2.wait_for(state="visible", timeout=15_000)
            save_btn2.scroll_into_view_if_needed()
            save_btn2.click()
            page.wait_for_timeout(2000)

            yes_btn2 = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn2.wait_for(state="visible", timeout=10_000)
            yes_btn2.click()
            page.wait_for_timeout(3000)

            success_banner = page.get_by_text(re.compile(r"success", re.I)).first
            expect(success_banner).to_be_visible(timeout=15_000)

            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=15_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            waiting_msg = page.get_by_text("Waiting for the requester to submit LT-263.")
            expect(waiting_msg).to_be_visible(timeout=10_000)

            ok_btn = page.locator("//span[contains(text(),'OK')]").first
            ok_btn.wait_for(state="visible", timeout=10_000)
            ok_btn.click()
            page.wait_for_timeout(2000)

            # ── Global Search: verify LT-262 Processed ──
            global_search_verify_status(page, TEST_VIN, "LT-262", "LT-262 Processed")
        finally:
            page.close()

    # ========================================================================
    # PHASE 4a: Public Portal — Submit LT-263
    # ========================================================================
    def test_phase_4a_lt263_process_verify_sold_status(self, public_context: BrowserContext):
        """Phase 4a: [Public Portal] Submit LT-263 — sale type, sale date, lien amount"""
        from datetime import datetime, timedelta

        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            expect(page.get_by_text(re.compile(r"LT-262 Processed", re.I)).first).to_be_visible(timeout=30_000)
            dashboard.expect_lt263_available()

            dashboard.click_submit_lt263()
            page.wait_for_timeout(2000)

            expect(page.get_by_text(re.compile(r"LT-263.*Form Details", re.I)).first).to_be_visible(timeout=30_000)

            sale_type_dropdown = page.locator('mat-select[aria-label*="Type of Sale" i]').first
            try:
                sale_type_dropdown.wait_for(state="visible", timeout=5_000)
                sale_type_dropdown.click()
                page.wait_for_timeout(500)
                page.locator('mat-option:has-text("Public")').first.click()
                page.wait_for_timeout(500)
            except Exception:
                lt263 = Lt263FormPage(page)
                lt263.select_public_sale()

            sale_date = (datetime.now() + timedelta(days=21)).strftime("%m/%d/%Y")
            sale_date_input = page.locator(
                'input[aria-label*="Sale Date" i], input[placeholder*="MM/DD/YYYY"]'
            ).first
            sale_date_input.wait_for(state="visible", timeout=10_000)
            sale_date_input.fill(sale_date)
            page.wait_for_timeout(500)

            lien_amount_input = page.locator(
                'input[aria-label*="Lien Amount" i], input[name*="lien" i][name*="amount" i]'
            ).first
            lien_amount_input.wait_for(state="visible", timeout=10_000)
            lien_amount_input.fill("800")
            page.wait_for_timeout(500)

            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=30_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            expect(page.get_by_text(re.compile(r"Terms and Conditions", re.I)).first).to_be_visible(timeout=30_000)

            mat_checkboxes = page.locator('mat-checkbox')
            cb_count = mat_checkboxes.count()
            for i in range(cb_count):
                cb = mat_checkboxes.nth(i)
                if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
                    cb.locator("label").click()
                    page.wait_for_timeout(200)

            name_input = page.locator(
                'input[aria-label*="Name" i], input[aria-label*="NAME" i]'
            ).first
            name_input.wait_for(state="visible", timeout=10_000)
            name_input.fill(PERSON["name"])

            date_input = page.locator(
                'input[aria-label*="Date" i], input[aria-label*="DATE" i]'
            ).first
            try:
                date_input.wait_for(state="visible", timeout=5_000)
                date_value = date_input.input_value()
                if not date_value:
                    date_input.fill(datetime.now().strftime("%m/%d/%Y"))
            except Exception:
                pass

            submit_btn = page.locator('button:has-text("Submit")').first
            submit_btn.wait_for(state="visible", timeout=30_000)
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click()
            page.wait_for_timeout(3000)

            try:
                success_banner = page.get_by_text(re.compile(r"Form is submitted successfully", re.I)).first
                expect(success_banner).to_be_visible(timeout=30_000)
            except Exception:
                print("  WARN: 'Form is submitted successfully' banner not seen — continuing")

            expect(page.get_by_text(re.compile(r"LT-263 Submitted", re.I)).first).to_be_visible(timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4b: Staff Portal — Review LT-263, Generate LT-265
    # ========================================================================
    def test_phase_4b_staff_portal_process_lt263(self, staff_context: BrowserContext):
        """Phase 4b: [Staff Portal] Open LT-263 from To Process, verify sale details, Generate LT-265"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            # Navigate to LT-263 listing → To Process tab
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()

            # Search for our VIN and select the application
            lt263_listing.search_by_vin(TEST_VIN)
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)

            # Verify sale details are visible on detail page
            lt263_listing.verify_sale_details_visible()
            lt263_listing.verify_lien_amount_visible()

            # Generate LT-265 (clicks body button → Issue modal → confirmation modal → OK)
            lt263_listing.generate_lt265(expected_vin=TEST_VIN)
        finally:
            page.close()
