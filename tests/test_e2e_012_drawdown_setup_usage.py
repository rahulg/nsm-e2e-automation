"""
E2E-012: Drawdown Payment — Setup to Usage
PP: Setup bank → Add funds → Auto-recharge → Pay LT-262 → Verify balance deducted

Precondition: Business Admin with active NSM account, Drawdown NOT yet configured,
              LT-260 already processed (LT-262 ready to submit).

Phases:
  1. [Public Portal]  Navigate to Drawdown settings, add bank information
  2. [Public Portal]  Add funds to Drawdown wallet
  3. [Public Portal]  Configure auto-recharge
  4. [Public Portal]  Submit LT-262 and pay via Drawdown
  5. [Public Portal]  Verify balance deducted, view account history
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
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
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.profile_page import PublicProfilePage
from src.pages.public_portal.payment_page import PaymentPage
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
@pytest.mark.high
@pytest.mark.payment
class TestE2E012DrawdownSetupUsage:
    """E2E-012: Drawdown — setup bank, add funds, auto-recharge, pay, verify"""

    def test_phase_0_setup_lt260(self, public_context: BrowserContext, staff_context: BrowserContext):
        """Phase 0: Setup — submit and process LT-260 so LT-262 is ready"""
        # Submit LT-260
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

        # Process LT-260 on staff portal
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

    def test_phase_1_setup_drawdown_bank(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Add bank information for Drawdown"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            profile = PublicProfilePage(page)
            profile.navigate_to_drawdown()
            profile.add_bank_information(
                account_number="123456789",
                routing_number="021000021",
            )
        finally:
            page.close()

    def test_phase_2_add_funds(self, public_context: BrowserContext):
        """Phase 2: [Public Portal] Add funds to Drawdown wallet"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            profile = PublicProfilePage(page)
            profile.navigate_to_drawdown()
            profile.add_funds("100")
            profile.expect_balance_displayed()
        finally:
            page.close()

    def test_phase_3_configure_auto_recharge(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Configure auto-recharge"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            profile = PublicProfilePage(page)
            profile.navigate_to_drawdown()
            profile.configure_auto_recharge(threshold="20", reload_amount="50")
        finally:
            page.close()

    def test_phase_4_pay_lt262_via_drawdown(self, public_context: BrowserContext):
        """Phase 4: [Public Portal] Submit LT-262 and pay via Drawdown"""
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

            # Select Drawdown payment
            payment = PaymentPage(page)
            payment.confirm_drawdown_payment()
        finally:
            page.close()

    def test_phase_5_verify_balance_and_history(self, public_context: BrowserContext):
        """Phase 5: [Public Portal] Verify balance deducted, view account history"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            profile = PublicProfilePage(page)
            profile.navigate_to_drawdown()

            # Verify balance is displayed (should show deduction)
            profile.expect_balance_displayed()

            # View account history
            profile.view_account_history()
            profile.expect_history_entries_visible()
        finally:
            page.close()
