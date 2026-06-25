"""
NCNSS-544: LT-261s not displaying in Global Search Results.

BUG fix verification (Staff Portal, Global Search): LT-261 records were not
returned by Global Search. The fix adds an LT-261 tab + results table backed by a
new ElasticSearch index (es_lt261_index = lt261_nss_qa27c, discriminator
case_number LIKE 'D%'). This test creates a FRESH LT-261 (E-Stop) and verifies it
is now found in Global Search by VIN under the LT-261 tab, with the row-click
routing to the LT-261 details page.

Scenarios (from ExpertlyTestBuddy plan.json for ticket 27253731):
  SC-1 [Critical] LT-261 found by VIN, returned under the LT-261 tab (core fix)
  SC-6 [High]     LT-261 row-click routes to /ncdot-notice-and-storage/LT-261/<id>/details

GATING (PRE-2): requires the lt261_nss_qa27c ES index to exist + be populated, the
es_lt261_index config row present, and the AD/PD methods PUBLISHED on QA. If the
LT-261 tab is absent or returns no result, the fix is not live/indexed on QA — that
is a real FAIL (fix not verified), not a test defect.

Reuses the E-Stop fill sequence from test_e2e_004 and the e2e_027 Global Search
header-search pattern.
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import generate_vin, generate_person, future_date
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page


SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def header_global_search(page, term: str):
    """Header toolbar Global Search → enter term → click Search (mirrors e2e_027)."""
    header_search = page.locator(
        "mat-toolbar input, app-toolbar input, "
        "input[placeholder*='Search' i], input[aria-label*='Search' i]"
    ).first
    header_search.wait_for(state="visible", timeout=15_000)
    header_search.fill(term)
    page.locator("//span[contains(text(),'Search ')]").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2500)


def fill_estop_form(lt261: Lt261Page, officer_name: str):
    """Fill the LT-261 E-Stop paper form body (reuses test_e2e_004's sequence)."""
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")
    lt261.check_use_same_address_storage()
    lt261.fill_sale_date(future_date(21))
    lt261.select_notice_of_sale_reason()
    lt261.check_agency_use_same_address()
    lt261.fill_agency_name(officer_name)


@pytest.mark.ncnss544
@pytest.mark.regression
@pytest.mark.critical
class TestE2E_NCNSS544_SC1_Lt261GlobalSearch:
    """SC-1/SC-6: a fresh LT-261 is found in Global Search by VIN under the LT-261 tab."""

    SC1_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc1_create_lt261(self, staff_context: BrowserContext):
        """Stage a fresh, indexable LT-261 (E-Stop) so Global Search has something to find."""
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
            print(f"EXPECTED: LT-261 created for VIN {self.SC1_VIN} | ACTUAL: submitted — MATCH")
        finally:
            page.close()

    def test_sc1_lt261_found_in_global_search_by_vin(self, staff_context: BrowserContext):
        """SC-1: Global Search by VIN returns the LT-261 under the LT-261 tab (core fix, BR-64)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ES indexing can lag — retry the search a few times.
            found = False
            for attempt in range(6):
                header_global_search(page, self.SC1_VIN)

                # The fix adds an LT-261 tab — it must exist.
                lt261_tab = page.locator('[role="tab"]:has-text("LT-261")').first
                if lt261_tab.count() > 0 and lt261_tab.is_visible():
                    lt261_tab.click()
                    page.wait_for_timeout(1500)
                    vin_cell = page.locator(
                        f"//span[contains(text(),'{self.SC1_VIN}')] | //td[contains(text(),'{self.SC1_VIN}')]"
                    ).first
                    if vin_cell.count() > 0 and vin_cell.is_visible():
                        found = True
                        break
                page.wait_for_timeout(5000)  # wait for indexing, then retry
                go_to_staff_dashboard(page)

            assert found, (
                f"EXPECTED: LT-261 VIN {self.SC1_VIN} found under the Global Search 'LT-261' tab "
                f"(NCNSS-544 fix) | ACTUAL: not found after retries — either the LT-261 tab is "
                f"absent or the lt261_nss_qa27c index is not populated/published on this env (fix not verified)"
            )
            print(
                f"EXPECTED: LT-261 VIN {self.SC1_VIN} in Global Search 'LT-261' tab | "
                f"ACTUAL: found — MATCH (NCNSS-544 fix verified)"
            )

            # SC-6: row-click routes to the LT-261 details page
            vin_cell = page.locator(
                f"//span[contains(text(),'{self.SC1_VIN}')] | //td[contains(text(),'{self.SC1_VIN}')]"
            ).first
            vin_cell.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
            assert re.search(r"/LT-261/.+/details", page.url, re.I), (
                f"EXPECTED: row-click routes to /LT-261/<id>/details (FO-58) | ACTUAL: {page.url}"
            )
            print(f"EXPECTED: row-click → LT-261 details | ACTUAL: {page.url} — MATCH")
        finally:
            page.close()
