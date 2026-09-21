"""
NCNSS-27067375: LT-261 form not appearing in any listing when Stolen = Yes.

BUG fix verification (Staff Portal, LT-261 E-Stop paper form):
  When "Stolen = Yes" is selected on the LT-261 paper form, the application must
  NOT auto-process and the record must remain SAVED and visible in an LT-261
  listing (the defect was the record vanishing from every listing). No LT-265/265A
  issuance popup must appear for a stolen record.

Scenarios (from ExpertlyTestBuddy plan.json for ticket 27067375):
  SC-1  [High]      Baseline — Stolen=No E-Stop LT-261 auto-processes → Sold (regression guard)
  SC-2  [Critical]  THE FIX — Stolen=Yes suppresses auto-process; record SAVED + in listing
  SC-3  [High]      Stolen=Yes details — no LT-265/265A popup; Stolen toggle re-evaluates
  TC-13 [Medium]    RBAC — Fiscal User cannot reach LT-261 (Cancel/process flow unreachable)

Reuses the proven E-Stop fill sequence from test_e2e_004_sheriff_inspector_lt261.py
and the Lt261Page Stolen helpers added for this ticket.
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import generate_vin, generate_person, future_date
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page
from src.pages.staff_portal.sold_listing_page import SoldListingPage


SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def fill_estop_form(lt261: Lt261Page, officer_name: str):
    """Fill the LT-261 E-Stop paper form body (everything EXCEPT the Stolen field).

    Mirrors test_e2e_004's proven sequence. The sale-date / notice-of-sale /
    agency section is filled tolerantly because a Stolen=Yes selection may hide
    or relax parts of it — the critical action under test is Stolen + Submit.
    """
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")
    try:
        lt261.check_use_same_address_storage()
        lt261.fill_sale_date(future_date(21))
        lt261.select_notice_of_sale_reason()
        lt261.check_agency_use_same_address()
        lt261.fill_agency_name(officer_name)
    except Exception as exc:
        # Stolen=Yes may relax/hide the sale section — keep going to Submit.
        print(f"NOTE: optional sale/agency section step skipped ({type(exc).__name__})")


# ============================================================================
# SC-2 [Critical] + SC-3 [High]: Stolen=Yes — THE FIX
# Covers: TC-02, TC-03, TC-04, TC-05
# ============================================================================
@pytest.mark.ncnss27067375
@pytest.mark.regression
@pytest.mark.critical
class TestE2E_NCNSS27067375_SC2_StolenYesListing:
    """SC-2/SC-3: Stolen=Yes LT-261 is saved, stays in a listing, not auto-processed, no LT-265 popup."""

    SC2_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc2_submit_stolen_yes_no_lt265_popup(self, staff_context: BrowserContext):
        """SC-2/SC-3: Submit E-Stop with Stolen=Yes → NO LT-265/265A issuance popup (TC-05, BR-122)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.SC2_VIN)
            fill_estop_form(lt261, self.OFFICER["name"])

            # The behaviour under test: Stolen = Yes
            lt261.select_stolen_yes()
            lt261.submit_stolen_form()

            # The fix: no LT-265/265A issuance popup for a stolen record
            lt261.expect_no_lt265_issue_popup()
            print(
                f"EXPECTED: Stolen=Yes LT-261 submits with NO LT-265/265A popup (auto-process "
                f"suppressed, BR-122) | ACTUAL: no LT-265 popup — MATCH | VIN={self.SC2_VIN}"
            )
        finally:
            page.close()

    def test_sc2_record_present_in_lt261_listing(self, staff_context: BrowserContext):
        """SC-2: The Stolen=Yes record IS present in the LT-261 listing — NOT lost (TC-02, TC-04)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            # The defect was disappearance from EVERY tab — check the All tab (broadest).
            try:
                lt261.all_tab.click(timeout=8_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            except Exception:
                pass

            lt261.expect_vin_in_listing(self.SC2_VIN)
            print(
                f"EXPECTED: VIN {self.SC2_VIN} present in an LT-261 listing (record saved, not lost) | "
                f"ACTUAL: record found — MATCH"
            )
        finally:
            page.close()

    def test_sc2_record_not_auto_processed_to_sold(self, staff_context: BrowserContext):
        """SC-2: The Stolen=Yes record did NOT auto-process — absent from the Sold listing (TC-02)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            sold = SoldListingPage(page)

            dashboard.navigate_to_sold()
            try:
                sold.search_by_vin(self.SC2_VIN)
            except Exception:
                pass
            rows = sold.application_rows.count()
            assert rows == 0, (
                f"EXPECTED: VIN {self.SC2_VIN} absent from Sold (Stolen=Yes must NOT auto-process) | "
                f"ACTUAL: {rows} row(s) in Sold — record was incorrectly auto-processed"
            )
            print(
                f"EXPECTED: VIN {self.SC2_VIN} NOT in Sold (no auto-process) | "
                f"ACTUAL: absent from Sold — MATCH"
            )
        finally:
            page.close()


# ============================================================================
# SC-1 [High]: Baseline — Stolen=No auto-processes (over-suppression regression guard)
# Covers: TC-01
# ============================================================================
@pytest.mark.ncnss27067375
@pytest.mark.regression
@pytest.mark.high
class TestE2E_NCNSS27067375_SC1_NonStolenBaseline:
    """SC-1: Stolen=No E-Stop LT-261 still auto-processes through to Sold (fix must not over-suppress)."""

    SC1_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc1_stolen_no_autoprocesses_to_sold(self, staff_context: BrowserContext):
        """SC-1: Stolen=No E-Stop LT-261 auto-processes → appears in Sold (TC-01)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.SC1_VIN)
            fill_estop_form(lt261, self.OFFICER["name"])
            lt261.select_stolen_no()
            lt261.submit_with_confirmation()

            # Auto-processed → should appear in the Sold listing
            dashboard.navigate_to_sold()
            sold = SoldListingPage(page)
            sold.search_by_vin(self.SC1_VIN)
            sold.expect_applications_visible()
            print(
                f"EXPECTED: Stolen=No LT-261 auto-processes → VIN {self.SC1_VIN} in Sold | "
                f"ACTUAL: found in Sold — MATCH"
            )
        finally:
            page.close()


# ============================================================================
# TC-13 [Medium]: RBAC — Fiscal User cannot access LT-261
# ============================================================================
@pytest.mark.ncnss27067375
@pytest.mark.regression
@pytest.mark.rbac
@pytest.mark.medium
class TestE2E_NCNSS27067375_TC13_FiscalRBAC:
    """TC-13: Fiscal User cannot log/process LT-261 (BR-9)."""

    def test_tc13_fiscal_user_no_lt261_access(self, fiscal_context: BrowserContext):
        """Fiscal User cannot reach the LT-261 listing / Add Paper E-Stop entry point."""
        page = fiscal_context.new_page()
        try:
            page.goto(SP_DASHBOARD_URL, timeout=60_000)
            page.wait_for_load_state("networkidle")

            lt261_link = page.locator('a[href*="LT-261/list"]').first
            if lt261_link.is_visible():
                lt261_link.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)
                add_btn = page.locator(
                    'button:has-text("Add from E-Stop"), button:has-text("Add Paper E-Stop"), '
                    'button:has-text("Add from Paper"), //span[contains(text(),"Add Paper E-Stop")]'
                )
                count = add_btn.count()
                assert count == 0, (
                    f"EXPECTED: 0 'Add Paper E-Stop' entry points for Fiscal User (BR-9) | "
                    f"ACTUAL: {count} visible — RBAC FAIL"
                )
                print(
                    "EXPECTED: Fiscal User cannot add/process LT-261 (no entry points, BR-9) | "
                    "ACTUAL: 0 entry points — MATCH"
                )
            else:
                print(
                    "EXPECTED: LT-261 not accessible to Fiscal User (BR-9) | "
                    "ACTUAL: LT-261 nav link hidden — MATCH"
                )
        finally:
            page.close()
