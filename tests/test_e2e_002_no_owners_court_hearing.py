"""
E2E-002: No Owners Path with Court Hearing
Cross-portal test: PP: LT-260 → SP: LT-260C → PP: LT-262 → SP: LT-262B →
                   Court → PP: LT-263 → SP: LT-265

Phases:
  1. [Public Portal]  Submit LT-260 with a VIN that has no owners in STARS
  2. [Staff Portal]   Verify no owners, manually process → system issues LT-260C
  3. [Public Portal]  Submit LT-262 with PayIt payment
  4. [Staff Portal]   Process LT-262 → Issue LT-262B → Court Hearing → Possessory Lien judgment
  5. [Public Portal]  Submit LT-263 with sale details
  6. [Staff Portal]   Review LT-263, Generate LT-265
  7. [Staff Portal]   Verify LT-263 details on REVIEW LT-263 tab
  8. [Staff Portal]   Verify LT-263 Processed (Sold) and Sold listing
  9. [Public Portal]  Verify vehicle in Sold Vehicles tab
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    VIN_NO_OWNERS,
    STANDARD_LIEN_CHARGES,
    STANDARD_SALE_DATA,
    SAMPLE_DOC_PATH,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
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
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage
from src.pages.staff_portal.sold_listing_page import SoldListingPage


# ─── Shared test data ───
BUSINESS_NAME = "G-Car Garages New"
# Use VIN_NO_OWNERS if a real STARS VIN is configured; otherwise generate random
TEST_VIN = VIN_NO_OWNERS if VIN_NO_OWNERS != "PLACEHOLDER_NO_OWNERS" else generate_vin()
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
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E002NoOwnersCourtHearing:
    """E2E-002: No Owners Path — LT-260C → LT-262B → Court Hearing → LT-265"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260 (VIN with no owners)
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Login, create LT-260, VIN lookup, fill form, submit"""
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
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)

            # Verify redirect back to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Set stolen=No, save, issue LT-260C
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260_no_owners(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Open LT-260, set stolen=No, save, Issue LT-260C → Processed"""
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

            # Verify detail page loaded
            form_processing.expect_detail_page_visible()

            # Click Edit
            form_processing.click_edit()

            # Select STOLEN = No (no owner details needed for no-owners path)
            form_processing.select_stolen_no()

            # Save
            form_processing.click_save()

            # Issue LT-260C button now visible — click it, confirm modal
            lt260_listing.issue_lt260c()

            # Confirm modal → click Issue
            issue_btn = page.locator('mat-dialog-container button:has-text("Issue")').first
            issue_btn.wait_for(state="visible", timeout=10_000)
            issue_btn.click()
            page.wait_for_timeout(2000)

            # Verify green success banner
            form_processing.expect_issued_success_toast()

            # Verify status changed to Processed
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262 with Drawdown payment
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Select business (same as Phase 1)
            dashboard.select_business(BUSINESS_NAME)

            # Search for the same VIN from Phase 1
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)
            dashboard.expect_application_processed()

            # Click "Submit LT-262"
            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()

            # Skip pre-filled tabs A (Vehicle) and B (Location) via Next
            lt262.skip_vehicle_and_location_tabs()

            # Fill Tab C — lien charges (advances to D via Next)
            lt262.fill_lien_charges(STANDARD_LIEN_CHARGES)

            # Fill Tab D — date of storage (advances to E via Next)
            lt262.fill_date_of_storage(past_date(30))

            # Fill Tab E — person authorizing storage
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Fill Additional Details
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Upload supporting documents
            lt262.upload_documents([SAMPLE_DOC_PATH])

            # Accept terms and sign
            lt262.accept_terms_and_sign(PERSON["name"])

            # Finish and pay — redirects to cart page
            lt262.finish_and_pay()

            # Click "Pay Using ACH/Drawdown" on the cart page
            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            # Confirm drawdown modal
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=30_000)

            # Verify redirect to dashboard
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Verify lien details, Issue LT-262B via CHECK DCI tab
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262_no_owners(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Verify lien details → CHECK DCI → Issue LT-262B →
        REVIEW COURT HEARINGS → Possessory Lien judgment → waiting for LT-263"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify lien details on REVIEW LT-262 tab
            lt262_listing.verify_lien_details_visible()

            # Navigate to CHECK DCI AND NMVTIS → Issue LT-262B → confirm modal
            # → verify green banner → auto-redirect to REVIEW COURT HEARINGS tab
            lt262_listing.issue_lt262b()
            page.wait_for_timeout(1000)

            # ── REVIEW COURT HEARINGS ─────────────────────────────────────────
            # Check "Judgment in action of Possessory Lien" checkbox
            possessory_cb = page.locator('mat-checkbox').first
            possessory_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
                possessory_cb.locator("label").click()
                page.wait_for_timeout(1000)

            # Click Save
            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=30_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(2000)

            # Confirm modal — click Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text(re.compile(r"success", re.I)).first
            expect(success_banner).to_be_visible(timeout=30_000)

            # Click Next button
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=30_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            # Verify "Waiting for the requester to submit LT-263." modal
            waiting_msg = page.get_by_text("Waiting for the requester to submit LT-263.")
            expect(waiting_msg).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Public Portal — Submit LT-263
    # ========================================================================
    def test_phase_5_public_portal_submit_lt263(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Submit LT-263 — sale type, sale date, lien amount"""
        from datetime import datetime, timedelta

        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Select business
            dashboard.select_business(BUSINESS_NAME)

            # Search for the same VIN
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            # Verify status is "LT-262 Processed" and Submit LT-263 button is available
            expect(page.get_by_text(re.compile(r"LT-262 Processed", re.I)).first).to_be_visible(timeout=30_000)
            dashboard.expect_lt263_available()

            # Click "Submit LT-263"
            dashboard.click_submit_lt263()
            page.wait_for_timeout(2000)

            # Verify LT-263 form page
            expect(page.get_by_text(re.compile(r"LT-263.*Form Details", re.I)).first).to_be_visible(timeout=30_000)

            # Select "Type of Sale" → Public
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

            # Enter Sale Date (21 days from today)
            sale_date = (datetime.now() + timedelta(days=21)).strftime("%m/%d/%Y")
            sale_date_input = page.locator(
                'input[aria-label*="Sale Date" i], input[placeholder*="MM/DD/YYYY"]'
            ).first
            sale_date_input.wait_for(state="visible", timeout=10_000)
            sale_date_input.fill(sale_date)
            page.wait_for_timeout(500)

            # Enter Lien Amount
            lien_amount_input = page.locator(
                'input[aria-label*="Lien Amount" i], input[name*="lien" i][name*="amount" i]'
            ).first
            lien_amount_input.wait_for(state="visible", timeout=10_000)
            lien_amount_input.fill("800")
            page.wait_for_timeout(500)

            # Click Next
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=30_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            # Terms and Conditions page — check all checkboxes
            expect(page.get_by_text(re.compile(r"Terms and Conditions", re.I)).first).to_be_visible(timeout=30_000)

            mat_checkboxes = page.locator('mat-checkbox')
            cb_count = mat_checkboxes.count()
            for i in range(cb_count):
                cb = mat_checkboxes.nth(i)
                if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
                    cb.locator("label").click()
                    page.wait_for_timeout(200)

            # Fill Name field
            name_input = page.locator(
                'input[aria-label*="Name" i], input[aria-label*="NAME" i]'
            ).first
            name_input.wait_for(state="visible", timeout=10_000)
            name_input.fill(PERSON["name"])

            # Fill Date field
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

            # Click Submit
            submit_btn = page.locator('button:has-text("Submit")').first
            submit_btn.wait_for(state="visible", timeout=30_000)
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text(re.compile(r"Form is submitted successfully", re.I)).first
            expect(success_banner).to_be_visible(timeout=30_000)

            # Verify VIN status is "LT-263 Submitted" on dashboard
            expect(page.get_by_text(re.compile(r"LT-263 Submitted", re.I)).first).to_be_visible(timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Review LT-263, Generate LT-265
    # ========================================================================
    def test_phase_6_staff_portal_process_lt263(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] Open LT-263 from To Process, verify sale details, Generate LT-265"""
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

    # ========================================================================
    # PHASE 7: Staff Portal — Verify LT-263 details on REVIEW LT-263 tab
    # ========================================================================
    def test_phase_7_staff_portal_verify_lt263_on_lt262(self, staff_context: BrowserContext):
        """Phase 7: [Staff Portal] Open LT-262 detail → REVIEW LT-263 tab → verify LT-263 details"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → All tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.all_tab.click()
            page.wait_for_load_state("networkidle")
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify LT-263 sale details are visible on REVIEW LT-263 tab
            lt262_listing.verify_lt263_details_visible()
        finally:
            page.close()

    # ========================================================================
    # PHASE 8: Staff Portal — Verify Sold status on LT-263 Processed (Sold)
    # ========================================================================
    def test_phase_8_staff_portal_verify_sold(self, staff_context: BrowserContext):
        """Phase 8: [Staff Portal] Verify LT-263 Processed (Sold), then Sold listing status"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            # Navigate to LT-263 listing → Processed (Sold) tab
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_processed_sold_tab()

            # Search for our VIN and select the application
            lt263_listing.search_by_vin(TEST_VIN)
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)

            # Verify sold vehicle details
            lt263_listing.verify_vehicle_description_visible()
            lt263_listing.verify_sale_details_visible()
            lt263_listing.verify_vehicle_sold()

            # Navigate to Sold listing from left sidebar
            staff_dashboard.navigate_to_sold()
            sold_listing = SoldListingPage(page)
            sold_listing.search_by_vin(TEST_VIN)
            sold_listing.expect_applications_visible()
            sold_listing.select_application(0)

            # Verify status is Processed
            expect(page.get_by_text(re.compile(r"Processed", re.I)).first).to_be_visible(timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 9: Public Portal — Verify Vehicle Sold status
    # ========================================================================
    def test_phase_9_public_portal_verify_vehicle_sold(self, public_context: BrowserContext):
        """Phase 9: [Public Portal] Verify vehicle appears in Sold Vehicles/Completed tab"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Select business
            dashboard.select_business(BUSINESS_NAME)

            # Click "Sold Vehicles/Completed" tab
            dashboard.click_sold_completed_tab()
            page.wait_for_timeout(2000)

            # Search for the VIN
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            # Verify status is "Vehicle Sold"
            expect(page.get_by_text(re.compile(r"Vehicle Sold", re.I)).first).to_be_visible(timeout=30_000)
        finally:
            page.close()
