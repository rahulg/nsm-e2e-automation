"""
E2E-046: Global Search Navigation to Offline Payment Details (Check/Money Order)
Staff Portal only — paper forms with offline payments.

Verifies that Global Search can navigate to Payment Details for offline payments
(Check and Money Order), and that the Payment Details page renders correctly
with the correct payment type.

Phases:
  0. [Staff Portal] Add paper LT-260 for Case A → record CHECK payment
  1. [Staff Portal] Add paper LT-260 for Case B → record MONEY ORDER payment
  2. [Staff Portal] Header search VIN-A → Payments tab → open entry →
                    verify Payment Details + payment type = Check
  3. [Staff Portal] Header search VIN-B → Payments tab → open entry →
                    verify Payment Details + payment type = Money Order
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import MAILED_PAYMENT
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    past_date,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage
from src.pages.staff_portal.payments_page import StaffPaymentsPage


# ─── Shared test data ───
# Case A: Check payment
TEST_VIN_A = generate_vin()
VEHICLE_A = random_vehicle()
CHECK_NUMBER = "CHK-98765"

# Case B: Money Order payment
TEST_VIN_B = generate_vin()
VEHICLE_B = random_vehicle()
MONEY_ORDER_NUMBER = "MO-54321"

SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.payment
@pytest.mark.fixed
class TestE2E046GlobalSearchOfflinePayment:
    """E2E-046: Global Search Navigation to Offline Payment Details (Check/Money Order)"""

    # ========================================================================
    # PHASE 0: Staff Portal — Add paper LT-260 for Case A + Check payment
    # ========================================================================
    def test_phase_0_setup_case_a_check_payment(self, staff_context: BrowserContext):
        """Phase 0: [Staff Portal] Add paper LT-260 for Case A → record Check payment."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            paper_form = PaperFormPage(page)
            payments = StaffPaymentsPage(page)

            # Add paper LT-260 for Case A
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_add_from_paper()
            paper_form.fill_modal_vin_and_next(TEST_VIN_A)
            paper_form.fill_year(VEHICLE_A["year"])
            paper_form.fill_make(VEHICLE_A["make"][:3])
            paper_form.fill_date_vehicle_left(past_date(30))
            paper_form.fill_search_location("Garage")
            paper_form.select_stolen_no()
            paper_form.submit_with_confirmation()

            # Record Check payment for Case A
            staff_dashboard.navigate_to_payments()
            payments.record_mailed_payment(
                vin=TEST_VIN_A,
                payer_name=MAILED_PAYMENT["payer_name"],
                check_number=CHECK_NUMBER,
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 1: Staff Portal — Add paper LT-260 for Case B + Money Order payment
    # ========================================================================
    def test_phase_1_setup_case_b_money_order_payment(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Add paper LT-260 for Case B → record Money Order payment."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            paper_form = PaperFormPage(page)
            payments = StaffPaymentsPage(page)

            # Add paper LT-260 for Case B
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_add_from_paper()
            paper_form.fill_modal_vin_and_next(TEST_VIN_B)
            paper_form.fill_year(VEHICLE_B["year"])
            paper_form.fill_make(VEHICLE_B["make"][:3])
            paper_form.fill_date_vehicle_left(past_date(30))
            paper_form.fill_search_location("Garage")
            paper_form.select_stolen_no()
            paper_form.submit_with_confirmation()

            # Record Money Order payment for Case B
            staff_dashboard.navigate_to_payments()
            payments.record_mailed_payment(
                vin=TEST_VIN_B,
                payer_name=MAILED_PAYMENT["payer_name"],
                check_number=MONEY_ORDER_NUMBER,
                payment_type="money_order",
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Header search VIN-A → Payments tab → verify Check
    # ========================================================================
    def test_phase_2_global_search_check_payment(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Header search VIN-A → Payments tab → open entry →
        verify Payment Details heading + payment type = Check."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)

            # Navigate to listing page first — header search not rendered on raw dashboard
            staff_dashboard.navigate_to_lt260_listing()
            page.wait_for_timeout(1000)

            # Enter VIN-A in header search field
            header_search = page.locator(
                "mat-toolbar input, app-toolbar input, "
                "input[placeholder*='Search' i], input[aria-label*='Search' i]"
            ).first
            header_search.wait_for(state="visible", timeout=15_000)
            header_search.fill(TEST_VIN_A)

            page.locator("//span[contains(text(),'Search ')]").first.click()
            page.wait_for_timeout(4000)

            # Click Payments tab
            payments_tab = page.locator('[role="tab"]:has-text("Payment")').first
            payments_tab.wait_for(state="visible", timeout=15_000)
            payments_tab.click()
            page.wait_for_timeout(2000)

            # Click the VIN entry in Payments tab
            vin_entry = page.locator(
                f'//span[contains(text(),"{TEST_VIN_A}")]'
                f'|//td[contains(text(),"{TEST_VIN_A}")]'
                f'|//span[@class[contains(.,"table-link")]][contains(text(),"{TEST_VIN_A}")]'
            ).first
            vin_entry.wait_for(state="visible", timeout=15_000)
            vin_entry.click()
            page.wait_for_timeout(3000)

            # Verify "Payment Details" heading
            expect(
                page.get_by_text(re.compile(r"Payment Details", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Verify payment type = "Check"
            expect(
                page.get_by_text(re.compile(r"\bCheck\b", re.I)).first
            ).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Header search VIN-B → Payments tab → verify Money Order
    # ========================================================================
    def test_phase_3_global_search_money_order_payment(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Header search VIN-B → Payments tab → open entry →
        verify Payment Details heading + payment type = Money Order."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)

            # Navigate to listing page first — header search not rendered on raw dashboard
            staff_dashboard.navigate_to_lt260_listing()
            page.wait_for_timeout(1000)

            # Enter VIN-B in header search field
            header_search = page.locator(
                "mat-toolbar input, app-toolbar input, "
                "input[placeholder*='Search' i], input[aria-label*='Search' i]"
            ).first
            header_search.wait_for(state="visible", timeout=15_000)
            header_search.fill(TEST_VIN_B)

            page.locator("//span[contains(text(),'Search ')]").first.click()
            page.wait_for_timeout(4000)

            # Click Payments tab
            payments_tab = page.locator('[role="tab"]:has-text("Payment")').first
            payments_tab.wait_for(state="visible", timeout=15_000)
            payments_tab.click()
            page.wait_for_timeout(2000)

            # Click the VIN entry in Payments tab
            vin_entry = page.locator(
                f'//span[contains(text(),"{TEST_VIN_B}")]'
                f'|//td[contains(text(),"{TEST_VIN_B}")]'
                f'|//span[@class[contains(.,"table-link")]][contains(text(),"{TEST_VIN_B}")]'
            ).first
            vin_entry.wait_for(state="visible", timeout=15_000)
            vin_entry.click()
            page.wait_for_timeout(3000)

            # Verify "Payment Details" heading
            expect(
                page.get_by_text(re.compile(r"Payment Details", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Verify payment type = "Money Order"
            expect(
                page.get_by_text(re.compile(r"Money\s+Order", re.I)).first
            ).to_be_visible(timeout=10_000)
        finally:
            page.close()
