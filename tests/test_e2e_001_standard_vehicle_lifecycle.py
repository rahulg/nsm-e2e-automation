"""
E2E-001: Standard Vehicle Lifecycle — Happy Path
Cross-portal test spanning Public Portal and Staff Portal.

Phases:
  1. [Public Portal]  Login, create LT-260, VIN lookup, fill form, submit
  2. [Staff Portal]   Open LT-260, verify owners + stolen indicator, verify correspondence
  3. [Public Portal]  Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay
  4. [Staff Portal]   Open LT-262, verify details, CHECK DCI → Issue LT-264
  5. [Staff Portal]   Track LT-264 delivery, verify court hearings status
  6. [Staff Portal]   Open LT-263 (To Process), verify sale details, Generate LT-265
  7. [Staff Portal]   Open LT-262, REVIEW LT-263 tab → verify LT-263 details
  8. [Staff Portal]   Verify LT-263 in Processed (Sold) tab with completed sale info
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    past_date,
    generate_person,
    today_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.shopping_cart_page import ShoppingCartPage
from src.pages.public_portal.payment_page import PaymentPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")

# Public Portal: use signin URL — with stored auth state it auto-redirects to dashboard
PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL

# Staff Portal dashboard URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
class TestE2E001StandardVehicleLifecycle:
    """E2E-001: Complete lifecycle — LT-260 → LT-262 → LT-264 → LT-263 → LT-265 (Sold)"""

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_create_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Login, create LT-260, VIN lookup, fill form, submit"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Select business (if multi-business user)
            dashboard.select_business()

            # Click "Start here" to create LT-260
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)

            # Enter VIN and perform VIN Lookup
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()

            # Fill vehicle details
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])

            # Fill authorized person (Tab 2)
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Accept terms and sign (Tab 3)
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            # Submit LT-260
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Verify LT-260 processing
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Open LT-260, verify owners check + stolen indicator, verify correspondence"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            # Navigate to LT-260 listing → To Process tab
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()

            # Search for our specific VIN
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)

            # Verify detail page, owners check, and stolen indicator
            form_processing.expect_detail_page_visible()
            lt260_listing.verify_owners_check_visible()
            lt260_listing.verify_stolen_indicator_no()

            # Verify correspondence documents issued
            lt260_listing.verify_auto_issuance()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Verify LT-260 shows as "Processed"
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)
            dashboard.expect_application_processed()

            # Click "Submit LT-262"
            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()

            # Fill Tab C — lien charges (checkboxes + amounts)
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})

            # Fill Tab D — date of storage
            lt262.fill_date_of_storage(past_date(30))

            # Fill Tab E — person authorizing storage
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Fill Additional Details (outer tab)
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Upload supporting documents
            lt262.upload_documents([SAMPLE_DOC_PATH])

            # Accept terms and sign
            lt262.accept_terms_and_sign(PERSON["name"])

            # Finish and pay
            lt262.finish_and_pay()

            # Wait for cart page to load
            cart = ShoppingCartPage(page)
            cart.expect_cart_not_empty()

            # Pay from drawdown account
            cart.checkout()
            payment = PaymentPage(page)
            payment.confirm_drawdown_payment()
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Process LT-262 → Issue LT-264
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Open LT-262, verify details, CHECK DCI → Issue LT-264"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → To Process tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()

            # Search for our specific VIN
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify lien details on REVIEW LT-262 tab
            lt262_listing.verify_lien_details_visible()

            # Navigate to CHECK DCI AND NMVTIS → verify owner details
            lt262_listing.verify_owner_details_visible()

            # Issue LT-264
            lt262_listing.issue_lt264()
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Track LT-264, verify court hearings
    # ========================================================================
    def test_phase_5_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Verify LT-264 tracking and court hearings status"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → find application (may be in Aging or Court Hearing tab)
            staff_dashboard.navigate_to_lt262_listing()

            # Try Aging tab first, then Court Hearing tab
            lt262_listing.click_aging_tab()
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.court_hearing_tab.click()
                page.wait_for_load_state("networkidle")
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            # Verify TRACK LT-264 tab
            lt262_listing.verify_lt264_tracking_visible()

            # Verify court hearings status
            lt262_listing.verify_no_hearings_requested()
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

            # Wait for applications to load and select the first one
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)

            # Verify sale details are visible on detail page
            lt263_listing.verify_sale_details_visible()
            lt263_listing.verify_lien_amount_visible()

            # Generate LT-265
            lt263_listing.generate_lt265()
        finally:
            page.close()

    # ========================================================================
    # PHASE 7: Staff Portal — Generate LT-265
    # ========================================================================
    def test_phase_7_staff_portal_generate_lt265(self, staff_context: BrowserContext):
        """Phase 7: [Staff Portal] Open LT-262 detail → REVIEW LT-263 tab → Generate LT-265"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → find application
            staff_dashboard.navigate_to_lt262_listing()

            # Search in All tab to find the application regardless of current status
            lt262_listing.all_tab.click()
            page.wait_for_load_state("networkidle")
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify LT-263 details on REVIEW LT-263 tab
            lt262_listing.verify_lt263_details_visible()

            # Generate LT-265
            lt262_listing.generate_lt265()
        finally:
            page.close()

    # ========================================================================
    # PHASE 8: Staff Portal — Verify Sold status on LT-263 Processed (Sold)
    # ========================================================================
    def test_phase_8_staff_portal_verify_sold(self, staff_context: BrowserContext):
        """Phase 8: [Staff Portal] Verify LT-263 in Processed (Sold) tab with completed sale info"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            # Navigate to LT-263 listing → Processed (Sold) tab
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_processed_sold_tab()

            # Wait for applications to load and select the first one
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)

            # Verify sold vehicle details
            lt263_listing.verify_vehicle_description_visible()
            lt263_listing.verify_sale_details_visible()
            lt263_listing.verify_vehicle_sold()
        finally:
            page.close()
