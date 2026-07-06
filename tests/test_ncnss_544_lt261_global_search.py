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

import random
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


# ============================================================================
# NCNSS-27276758: "Stolen VIN is not displayed for LT-261 application in Global
# Search". THE FIX gates NSM.Helpers._elasticSearch.upsert in forms.LT261.submit
# on (isStolen==true AND saveAction=='SUBMIT') so a stolen E-Stop LT-261 — which
# is held MANUAL and skips LT261.autoProcess (where non-stolen ones get indexed)
# — is now ALSO indexed into lt261_nss_qa27c and its VIN surfaces in Global Search
# under the LT-261 tab. Previously it never appeared.
#
# Synthesis target SC-1 (Critical): a freshly SUBMITTED stolen (isStolen=Yes)
# LT-261 is found in Global Search by VIN under the LT-261 tab, the stolen VIN is
# rendered, and row-click routes to /LT-261/<id>/details. Reuses the E-Stop fill +
# GS-by-VIN search of NCNSS-544 above and the Stolen=Yes helpers added for
# NCNSS-27067375 (lt261_page.select_stolen_yes / submit_stolen_form).
# ============================================================================


def fill_estop_form_tolerant(lt261: Lt261Page, officer_name: str):
    """Fill the LT-261 E-Stop body EXCEPT Stolen — tolerant of the sale/agency
    section being relaxed/hidden once Stolen=Yes is selected (mirrors the
    NCNSS-27067375 stolen test's fill)."""
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")
    try:
        lt261.check_use_same_address_storage()
        lt261.fill_sale_date(future_date(21))
        lt261.select_notice_of_sale_reason()
        lt261.check_agency_use_same_address()
        lt261.fill_agency_name(officer_name)
    except Exception as exc:  # noqa: BLE001
        print(f"NOTE: optional sale/agency section step skipped ({type(exc).__name__})")


def gs_find_vin_under_lt261_tab(page, vin: str, attempts: int = 6):
    """Retry Global Search by VIN, click the LT-261 tab, return the visible VIN
    cell locator if found (else None). ES indexing can lag, so retry."""
    for _ in range(attempts):
        header_global_search(page, vin)
        lt261_tab = page.locator('[role="tab"]:has-text("LT-261")').first
        if lt261_tab.count() > 0 and lt261_tab.is_visible():
            lt261_tab.click()
            page.wait_for_timeout(1500)
            vin_cell = page.locator(
                f"//span[contains(text(),'{vin}')] | //td[contains(text(),'{vin}')]"
            ).first
            if vin_cell.count() > 0 and vin_cell.is_visible():
                return vin_cell
        page.wait_for_timeout(5000)
        go_to_staff_dashboard(page)
    return None


@pytest.mark.ncnss27276758
@pytest.mark.regression
@pytest.mark.critical
class TestE2E_NCNSS27276758_SC1_StolenGlobalSearch:
    """SC-1 (CORE): a SUBMITTED stolen (isStolen=Yes) LT-261 is found in Global
    Search by VIN under the LT-261 tab, its VIN renders, and the row routes to details."""

    SC1_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc1_create_and_submit_stolen_lt261(self, staff_context: BrowserContext):
        """Create + SUBMIT a Stolen=Yes E-Stop LT-261 and capture POSITIVE PROOF it
        persisted: no LT-265 auto-issue popup (stolen held manual) AND the VIN is
        present in the LT-261 listing (the record under test for Global Search)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.SC1_VIN)
            fill_estop_form_tolerant(lt261, self.OFFICER["name"])

            # The behaviour under test: Stolen = Yes, then SUBMIT.
            lt261.select_stolen_yes()
            lt261.submit_stolen_form()
            lt261.expect_no_lt265_issue_popup()

            # POSITIVE PROOF of submission: the stolen record persisted and is
            # visible in the LT-261 listing (held manual, not auto-processed away).
            dashboard.navigate_to_lt261_listing()
            try:
                lt261.all_tab.click(timeout=8_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            except Exception:
                pass
            lt261.expect_vin_in_listing(self.SC1_VIN)
            print(
                f"EXPECTED: Stolen=Yes LT-261 SUBMITTED + persisted (no LT-265 auto-issue, "
                f"VIN in listing) | ACTUAL: submitted, VIN {self.SC1_VIN} present in LT-261 "
                f"listing — MATCH (proof of submission)"
            )
        finally:
            page.close()

    def test_sc1_stolen_vin_found_in_global_search(self, staff_context: BrowserContext):
        """SC-1 CORE: the stolen LT-261's VIN is returned in Global Search under the
        LT-261 tab (the NCNSS-27276758 fix — gated upsert on stolen SUBMIT), the VIN
        renders, and the row routes to /LT-261/<id>/details."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            vin_cell = gs_find_vin_under_lt261_tab(page, self.SC1_VIN)
            assert vin_cell is not None, (
                f"EXPECTED: stolen LT-261 VIN {self.SC1_VIN} found under the Global Search "
                f"'LT-261' tab (NCNSS-27276758 fix — gated _elasticSearch.upsert on stolen "
                f"SUBMIT indexes it into lt261_nss_qa27c) | ACTUAL: not found after retries — "
                f"the stolen VIN never surfaced (defect reproduced / fix not live on this env)"
            )
            # The stolen VIN is actually RENDERED in the result row.
            assert vin_cell.is_visible(), (
                f"EXPECTED: stolen VIN {self.SC1_VIN} rendered in the LT-261 result row | "
                f"ACTUAL: cell present but not visible"
            )
            print(
                f"EXPECTED: stolen VIN {self.SC1_VIN} rendered in Global Search 'LT-261' tab | "
                f"ACTUAL: found + rendered — MATCH (NCNSS-27276758 fix verified)"
            )

            # SC-1 / TC-15: row-click routes to the LT-261 details page.
            vin_cell.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
            assert re.search(r"/LT-261/.+/details", page.url, re.I), (
                f"EXPECTED: row-click routes to /LT-261/<id>/details | ACTUAL: {page.url}"
            )
            print(f"EXPECTED: stolen row-click → LT-261 details | ACTUAL: {page.url} — MATCH")
        finally:
            page.close()


@pytest.mark.ncnss27276758
@pytest.mark.regression
@pytest.mark.high
class TestE2E_NCNSS27276758_SC2_SubmitGate:
    """SC-2 (submit-gate guard): the _elasticSearch.upsert fires ONLY on the stolen
    SUBMIT transition. A stolen E-Stop LT-261 that is filled but NOT submitted (no
    SUBMIT, i.e. abandoned/draft) is NOT indexed and does NOT surface in Global
    Search — proving the saveAction=='SUBMIT' half of the gate.

    NOTE: the LT-261 E-Stop paper form is SUBMIT-only (no 'Save as Draft' control),
    so a persisted stolen DRAFT cannot be produced through this UI. This test instead
    proves the gate behaviourally: merely opening + filling a Stolen=Yes form (without
    SUBMIT) leaves the VIN un-indexed. Combined with SC-1 (SUBMIT → indexed) this
    establishes 'upsert fires only on SUBMIT, never before'."""

    SC2_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc2_unsubmitted_stolen_not_in_global_search(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Open + fill a Stolen=Yes E-Stop form but DO NOT submit.
            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.SC2_VIN)
            fill_estop_form_tolerant(lt261, self.OFFICER["name"])
            lt261.select_stolen_yes()
            # Deliberately NO submit — abandon by navigating back to the dashboard.
            go_to_staff_dashboard(page)

            # A short pass — we EXPECT absence (no ES write happened without SUBMIT).
            vin_cell = gs_find_vin_under_lt261_tab(page, self.SC2_VIN, attempts=2)
            assert vin_cell is None, (
                f"EXPECTED: un-submitted stolen VIN {self.SC2_VIN} NOT in Global Search "
                f"(upsert gated on saveAction=='SUBMIT') | ACTUAL: it was indexed without a "
                f"SUBMIT — the submit-gate leaked"
            )
            print(
                f"EXPECTED: un-submitted stolen VIN {self.SC2_VIN} absent from Global Search "
                f"(submit-gate) | ACTUAL: absent — MATCH"
            )
        finally:
            page.close()


# ============================================================================
# NCNSS-27258416 / womi:ncdmv-493: "Submitter Name and License Plate Number are
# not displayed when searching LT-261 applications using Global Search".
#
# REAL defect = SUBMITTER NAME only: the LT-261 Global Search projection/DTO
# (method 4c413ee...) never resolved the requestor/agency name (BR-14), so the
# result row / details rendered it blank though the LT-261 was returned. THE FIX
# resolves + carries submitterName in the projection/index (lt261_nss_qa27c) so it
# renders in the Global Search row AND on the details page.
#
# License Plate was NOT a bug: it is legitimately blank when the LT-261 carries no
# plate value; it renders when data exists. A blank-plate case must PASS as blank.
#
# Synthesis targets (ExpertlyTestBuddy plan.json for ticket 27258416):
#   SC-1 [Critical] a SUBMITTED LT-261 renders its Submitter Name (requestor/agency,
#                   non-blank) in the GS result row under the LT-261 tab AND on the
#                   details page; findable by a 3+ char Submitter-Name partial;
#                   row-click routes to /LT-261/<id>/details.  (folds SC-2 + SC-6)
#   SC-3 [High]     License Plate renders when data present; blank-without-data
#                   PASSES as blank (not-a-bug); a missing plate must not blank/break
#                   the Submitter Name or the row.
# Reuses NCNSS-544's E-Stop fill + GS-by-VIN search above (fill_estop_form fills the
# agency/requestor NAME, which IS the Submitter Name, BR-14).
# ============================================================================


def gs_get_lt261_row(page, vin: str, attempts: int = 6):
    """Retry GS by VIN under the LT-261 tab; return the RESULT ROW locator (the
    <tr> ancestor of the VIN cell) if found, else None."""
    vin_cell = gs_find_vin_under_lt261_tab(page, vin, attempts=attempts)
    if vin_cell is None:
        return None
    row = vin_cell.locator("xpath=ancestor::tr[1]")
    if row.count() == 0:
        return None
    return row.first


@pytest.mark.ncnss27258416
@pytest.mark.regression
@pytest.mark.critical
class TestE2E_NCNSS27258416_SC1_SubmitterNameGlobalSearch:
    """SC-1 (CORE, Critical): a SUBMITTED LT-261 renders its Submitter Name
    (requestor/agency, BR-14 — the literal NCNSS-27258416 fix) NON-BLANK in the
    Global Search result row under the LT-261 tab AND on the details page; the
    Submitter Name is findable by a 3+ char partial; row-click routes to
    /LT-261/<id>/details. Folds SC-2 (projection resolves submitterName ⇒ it
    rendered) and SC-6 (fresh headless context = cache-cleared)."""

    SC1_VIN = generate_vin()
    OFFICER = generate_person()
    # A unique, name-like Submitter token so the row match + Submitter-Name partial
    # search are unambiguous (never a false positive from another record's name).
    SUB_TOKEN = "Zq" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))
    SUBMITTER = f"{OFFICER['name']} {SUB_TOKEN}"

    def test_sc1_create_and_submit_lt261(self, staff_context: BrowserContext):
        """PRE-2 / positive proof: create + SUBMIT a fresh E-Stop LT-261 with the
        requestor/agency (Submitter) NAME populated, and prove it persisted (VIN
        present in the LT-261 listing) — a clicked SUBMIT alone is not proof."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.SC1_VIN)
            # fill_estop_form sets the agency/requestor NAME = Submitter Name (BR-14).
            fill_estop_form(lt261, self.SUBMITTER)
            lt261.select_stolen_no()
            lt261.submit_with_confirmation()

            # POSITIVE PROOF of submission: the record persisted + is in the listing.
            dashboard.navigate_to_lt261_listing()
            try:
                lt261.all_tab.click(timeout=8_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            except Exception:
                pass
            lt261.expect_vin_in_listing(self.SC1_VIN)
            print(
                f"EXPECTED: LT-261 SUBMITTED + persisted with Submitter '{self.SUBMITTER}' "
                f"(VIN {self.SC1_VIN} in listing) | ACTUAL: submitted, VIN present — MATCH "
                f"(proof of submission)"
            )
        finally:
            page.close()

    def test_sc1_submitter_name_renders_in_global_search_and_details(self, staff_context: BrowserContext):
        """SC-1 CORE (+SC-2/SC-6, TC-01/02/03/05/11/16/17): the Submitter Name is
        rendered NON-BLANK in the GS LT-261 result row and on the details page,
        is findable by a 3+ char Submitter-Name partial, and the row routes to
        /LT-261/<id>/details. Also folds the SC-3 defensive check (a missing plate
        must not blank/break the Submitter Name or the row)."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ── SC-1 / SC-2 / TC-01/03/11: Submitter Name renders NON-BLANK in the row ──
            row = gs_get_lt261_row(page, self.SC1_VIN)
            assert row is not None, (
                f"EXPECTED: submitted LT-261 VIN {self.SC1_VIN} found under the GS 'LT-261' "
                f"tab | ACTUAL: not found after retries — the record never surfaced (fix "
                f"not live / index not populated on this env)"
            )
            row_text = (row.text_content() or "").strip()
            print(f"DIAG: LT-261 GS result row text = {row_text!r}")
            assert self.SUBMITTER.split()[-1] in row_text and self.OFFICER["name"] in row_text, (
                f"EXPECTED: Submitter Name '{self.SUBMITTER}' (requestor/agency, BR-14) "
                f"rendered NON-BLANK in the GS LT-261 result row (the NCNSS-27258416 fix — "
                f"projection method 4c413ee now resolves submitterName) | ACTUAL: not present "
                f"in the row — row text was {row_text!r} (defect reproduced: submitterName blank)"
            )
            print(
                f"EXPECTED: Submitter Name '{self.SUBMITTER}' non-blank in GS LT-261 row | "
                f"ACTUAL: rendered — MATCH (NCNSS-27258416 fix verified; SC-2 projection resolved)"
            )

            # ── SC-3 defensive (TC-07): the E-Stop LT-261 carries NO plate, yet the
            # Submitter Name + VIN still render intact — a missing plate does not
            # blank/break the row (the not-a-bug half is asserted fully in SC-3 class). ──
            assert self.SC1_VIN in row_text, (
                f"EXPECTED: VIN {self.SC1_VIN} still rendered in the row alongside the "
                f"Submitter Name despite a blank plate (defensive) | ACTUAL: VIN missing "
                f"from row {row_text!r}"
            )
            print(
                "EXPECTED: blank License Plate does not break the row (Submitter Name + VIN "
                "intact) | ACTUAL: both present — MATCH (SC-3 defensive)"
            )

            # ── TC-16 / TC-05: findable by a 3+ char Submitter-Name partial ──
            partial = self.SUB_TOKEN[:5]  # >3 chars, unique to this record
            partial_row = gs_get_lt261_row(page, partial, attempts=3)
            # partial search returns by Submitter Name; confirm OUR VIN is in the hit.
            partial_ok = partial_row is not None and self.SC1_VIN in (partial_row.text_content() or "")
            assert partial_ok, (
                f"EXPECTED: LT-261 findable by a 3+ char Submitter-Name partial "
                f"'{partial}' (searchable Submitter column, TC-05/TC-16) | ACTUAL: our VIN "
                f"{self.SC1_VIN} not returned for the partial — Submitter Name not searchable"
            )
            print(
                f"EXPECTED: LT-261 found by 3+ char Submitter partial '{partial}' | "
                f"ACTUAL: VIN {self.SC1_VIN} returned — MATCH"
            )

            # ── SC-6 / TC-17: row-click routes to details AND details shows Submitter Name ──
            details_row = gs_get_lt261_row(page, self.SC1_VIN, attempts=3)
            assert details_row is not None, "row disappeared before detail navigation"
            details_row.locator(
                f"xpath=.//span[contains(text(),'{self.SC1_VIN}')] | "
                f".//td[contains(text(),'{self.SC1_VIN}')]"
            ).first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            assert re.search(r"/LT-261/.+/details", page.url, re.I), (
                f"EXPECTED: row-click routes to /LT-261/<id>/details (TC-17) | ACTUAL: {page.url}"
            )
            details_text = page.locator("body").inner_text()
            assert self.SUB_TOKEN in details_text, (
                f"EXPECTED: the LT-261 details page also shows the Submitter Name "
                f"'{self.SUBMITTER}' (TC-02) | ACTUAL: token '{self.SUB_TOKEN}' not found on "
                f"the details page {page.url}"
            )
            print(
                f"EXPECTED: row-click → LT-261 details showing Submitter Name | "
                f"ACTUAL: {page.url} shows '{self.SUB_TOKEN}' — MATCH (SC-6 fresh context)"
            )
        finally:
            page.close()


@pytest.mark.ncnss27258416
@pytest.mark.regression
@pytest.mark.high
class TestE2E_NCNSS27258416_SC3_LicensePlateBehavior:
    """SC-3 (High, TC-06/07): License Plate behaviour. An E-Stop LT-261 carries no
    plate value, so the plate column is legitimately BLANK — this must PASS as blank
    (NOT-A-BUG), and the blank plate must never blank/break the Submitter Name or the
    rest of the row (defensive).

    NOTE: the plate-PRESENT regression (TC-04) needs a plate-bearing LT-261 (a
    public LT-260/262-origin record). The staff E-Stop paper form has no license-
    plate input, so a plate-present record cannot be produced from this UI harness;
    TC-04 is flagged as covered-elsewhere (LT-260 origin) rather than automated here."""

    SC3_VIN = generate_vin()
    OFFICER = generate_person()
    SUB_TOKEN = "Zp" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))
    SUBMITTER = f"{OFFICER['name']} {SUB_TOKEN}"

    def test_sc3_create_lt261_without_plate(self, staff_context: BrowserContext):
        """Create + SUBMIT a fresh E-Stop LT-261 (no plate) with a Submitter Name."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.SC3_VIN)
            fill_estop_form(lt261, self.SUBMITTER)
            lt261.select_stolen_no()
            lt261.submit_with_confirmation()

            dashboard.navigate_to_lt261_listing()
            try:
                lt261.all_tab.click(timeout=8_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1000)
            except Exception:
                pass
            lt261.expect_vin_in_listing(self.SC3_VIN)
            print(
                f"EXPECTED: plate-less LT-261 SUBMITTED + persisted (VIN {self.SC3_VIN}) | "
                f"ACTUAL: present in listing — MATCH"
            )
        finally:
            page.close()

    def test_sc3_blank_plate_passes_and_row_intact(self, staff_context: BrowserContext):
        """TC-06/07: the plate-less LT-261 renders in GS with a legitimately BLANK
        plate (NOT scored a failure) while the Submitter Name + VIN stay intact."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            row = gs_get_lt261_row(page, self.SC3_VIN)
            assert row is not None, (
                f"EXPECTED: plate-less LT-261 VIN {self.SC3_VIN} found under the GS 'LT-261' "
                f"tab | ACTUAL: not found after retries"
            )
            row_text = (row.text_content() or "").strip()
            print(f"DIAG: SC-3 plate-less GS row text = {row_text!r}")

            # NOT-A-BUG: no generated plate (format LLL-DDDD) should appear for this record.
            assert not re.search(r"\b[A-Z]{3}-\d{4}\b", row_text), (
                f"EXPECTED: no license-plate value for a plate-less LT-261 (legitimately "
                f"blank, not-a-bug) | ACTUAL: a plate-like token appeared in {row_text!r}"
            )
            # Defensive: the blank plate did NOT blank/break the Submitter Name or VIN.
            assert self.SUB_TOKEN in row_text and self.SC3_VIN in row_text, (
                f"EXPECTED: blank plate leaves Submitter '{self.SUBMITTER}' + VIN "
                f"{self.SC3_VIN} intact (defensive) | ACTUAL: row {row_text!r} missing one"
            )
            print(
                f"EXPECTED: plate legitimately BLANK + Submitter/VIN intact (not-a-bug) | "
                f"ACTUAL: no plate token, Submitter '{self.SUB_TOKEN}' + VIN present — MATCH "
                f"(SC-3 blank-plate PASSES as blank)"
            )
        finally:
            page.close()


@pytest.mark.ncnss27276758
@pytest.mark.regression
@pytest.mark.medium
class TestE2E_NCNSS27276758_TC16_NegativeSearch:
    """TC-16 (data validation): a VIN with no stolen LT-261 returns NO LT-261 hit
    in Global Search — the gated upsert must not create false positives."""

    ABSENT_VIN = generate_vin()  # freshly generated, never submitted → must not exist

    def test_tc16_absent_vin_no_false_lt261_hit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            # Navigate to the LT-261 listing first so the header Global Search field is
            # fully rendered (mirrors e2e_037's robust pattern) before searching.
            try:
                StaffDashboardPage(page).navigate_to_lt261_listing()
                page.wait_for_timeout(1000)
            except Exception:
                pass

            # We EXPECT absence. Retry to absorb transient header-search render flakiness;
            # require at least one search to actually execute so the negative is meaningful.
            found_cell = None
            searched_ok = False
            for _ in range(3):
                try:
                    header_global_search(page, self.ABSENT_VIN)
                    searched_ok = True
                except Exception as exc:  # noqa: BLE001
                    print(f"NOTE: header search not ready, retrying ({type(exc).__name__})")
                    go_to_staff_dashboard(page)
                    page.wait_for_timeout(1500)
                    continue
                lt261_tab = page.locator('[role="tab"]:has-text("LT-261")').first
                if lt261_tab.count() > 0 and lt261_tab.is_visible():
                    lt261_tab.click()
                    page.wait_for_timeout(1500)
                    cell = page.locator(
                        f"//span[contains(text(),'{self.ABSENT_VIN}')] | "
                        f"//td[contains(text(),'{self.ABSENT_VIN}')]"
                    ).first
                    if cell.count() > 0 and cell.is_visible():
                        found_cell = cell
                        break
                page.wait_for_timeout(1000)
                go_to_staff_dashboard(page)

            assert searched_ok, (
                f"EXPECTED: Global Search executed for absent VIN {self.ABSENT_VIN} | "
                f"ACTUAL: header search field never became usable (test infra, not a product result)"
            )
            assert found_cell is None, (
                f"EXPECTED: no LT-261 result for never-submitted VIN {self.ABSENT_VIN} "
                f"(no false positive) | ACTUAL: a matching row was returned"
            )
            print(
                f"EXPECTED: absent VIN {self.ABSENT_VIN} returns no LT-261 hit | "
                f"ACTUAL: no result — MATCH (no false positive)"
            )
        finally:
            page.close()
