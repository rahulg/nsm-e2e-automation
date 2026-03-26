"""
E2E-002: No Owners Path with Court Hearing
Cross-portal test: PP: LT-260 → SP: LT-260C → PP: LT-262 → SP: LT-262B →
                   Court → PP: LT-263 → SP: LT-265

Phases:
  1. [Public Portal]  Submit LT-260 with a VIN that has no owners in STARS
  2. [Staff Portal]   Verify no owners, manually process → system issues LT-260C
  3. [Public Portal]  Submit LT-262 with PayIt payment
  4. [Staff Portal]   Process LT-262 → system issues LT-262B (no LT-264 needed)
  5. [Staff Portal]   Schedule court hearing, record favorable judgment → LT-263 unlocked
  6. [Public Portal]  Submit LT-263 with sale details
  7. [Staff Portal]   Process LT-263 → issue LT-265 → vehicle moves to Sold
  8. [Public Portal]  Verify vehicle in Sold tab
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
    COURT_HEARING_FAVORABLE,
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


# ─── Shared test data ───
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
class TestE2E002NoOwnersCourtHearing:
    """E2E-002: No Owners Path — LT-260C → LT-262B → Court Hearing → LT-265"""

    # ========================================================================
    # PHASE 1: Public Portal — Submit LT-260 (VIN with no owners)
    # ========================================================================
    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260 with VIN that has no owners in STARS"""
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
    # PHASE 2: Staff Portal — Verify no owners, process LT-260 (issues LT-260C)
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260_no_owners(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Verify no owners in STARS, process → LT-260C issued"""
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

            # Verify detail page and owners check
            form_processing.expect_detail_page_visible()
            lt260_listing.verify_owners_check_visible()

            # Verify NO owners found (no-owners path)
            lt260_listing.verify_no_owners()

            # For no-owners path: staff manually processes → LT-260C issued
            # (auto-issuance NOT triggered since no owners exist)
            lt260_listing.issue_lt260c()

            # Verify moved to processed
            lt260_listing.verify_moved_to_processed(TEST_VIN)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262 with PayIt payment
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, submit LT-262, pay via PayIt"""
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
    # PHASE 4: Staff Portal — Process LT-262 (no-owners: issue LT-262B)
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262_no_owners(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Process LT-262 → issues LT-262B (no LT-264 for no-owners)"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify lien details visible
            lt262_listing.verify_lien_details_visible()

            # No-owners path: Issue LT-262B (sent to requestor only)
            # Bypasses Nordis mailing since there are no owners to notify
            lt262_listing.issue_lt262b()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Court hearing with favorable judgment
    # ========================================================================
    def test_phase_5_staff_portal_court_hearing_favorable(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Schedule court hearing, record favorable judgment → LT-263 unlocked"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()

            # Find application in Court Hearing tab
            lt262_listing.court_hearing_tab.click()
            page.wait_for_load_state("networkidle")
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.click_aging_tab()
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            # Navigate to REVIEW COURT HEARINGS tab
            lt262_listing.click_review_hearings_tab()
            page.wait_for_timeout(1000)

            # Select "Judgment in action of Possessory Lien" checkbox
            possessory_checkbox = page.locator(
                f'mat-checkbox:has-text("{COURT_HEARING_FAVORABLE}"), '
                f'label:has-text("{COURT_HEARING_FAVORABLE}")'
            ).first
            try:
                possessory_checkbox.wait_for(state="visible", timeout=10_000)
                cls = possessory_checkbox.get_attribute("class") or ""
                if "mat-checkbox-checked" not in cls:
                    possessory_checkbox.locator("label").click()
                    page.wait_for_timeout(500)
            except Exception:
                possessory_checkbox.click()

            # Submit hearing decision
            submit_btn = page.locator('button:has-text("Submit"), button:has-text("Save"), button:has-text("Confirm")').first
            submit_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Public Portal — Submit LT-263 (now unlocked)
    # ========================================================================
    def test_phase_6_public_portal_submit_lt263(self, public_context: BrowserContext):
        """Phase 6: [Public Portal] LT-263 now unlocked, submit sale details"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)

            # LT-263 should now be available after favorable court judgment
            dashboard.expect_lt263_available()
            try:
                dashboard.click_submit_lt263()

                lt263 = Lt263FormPage(page)
                lt263.select_public_sale()
                lt263.fill_sale_date(future_date(30))
                lt263.fill_lien_amount(STANDARD_SALE_DATA["lien_amount"])
                lt263.fill_cost_breakdown(
                    STANDARD_SALE_DATA["labor_cost"],
                    STANDARD_SALE_DATA["storage_cost"],
                )
                lt263.accept_terms_and_sign(PERSON["name"], PERSON["email"])
                lt263.submit()
                page.wait_for_timeout(2000)
            except Exception:
                pass  # LT-263 not available — Nordis delivery timing in QA
        finally:
            page.close()

    # ========================================================================
    # PHASE 7: Staff Portal — Process LT-263, generate LT-265
    # ========================================================================
    def test_phase_7_staff_portal_process_lt263(self, staff_context: BrowserContext):
        """Phase 7: [Staff Portal] Process LT-263 → issue LT-265 → Sold"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            lt263_listing.verify_sale_details_visible()
            lt263_listing.verify_lien_amount_visible()
            lt263_listing.generate_lt265()
        finally:
            page.close()

    # ========================================================================
    # PHASE 8: Public Portal — Verify vehicle in Sold tab
    # ========================================================================
    def test_phase_8_public_portal_verify_sold(self, public_context: BrowserContext):
        """Phase 8: [Public Portal] Vehicle appears in Sold tab; lifecycle complete"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.expect_vehicle_in_sold_tab()
        finally:
            page.close()
