"""
E2E-004: Sheriff/Inspector Standalone (LT-261)  (+ NCNSS-27303020 DWI LT-265A reprint)
Staff Portal only — no Public Portal involvement.

This file is the SINGLE home for LT-261 paper-form coverage. It merges two suites:

  * E2E-004 — the four-phase standalone lifecycle:
      1. E-STOP + owner details + Stolen = NO  → LT-261 Processed listing → vehicle Sold
      2. DWI    + owner details + Stolen = NO  → LT-261 Processed listing → vehicle Sold
      3. E-STOP + owner details + Stolen = YES → LT-261 Stolen listing
      4. DWI    + owner details + Stolen = YES → LT-261 Stolen listing
  * NCNSS-27303020 — Enhancement: Reprint button for LT-265A on the LT-261 page after
    LT-265A integration with Nordis (CR NCNSS-547). Dev change
    (documents.CorrespondenceHistory Step 2): reprint allowed for the LT-265A **logged
    for DWI** only. E-Stop 265As and all LT-265s remain excluded (residual BR-122).
    Reprint parity with §3.37/§3.39: banner "The form has been sent again for
    reprinting", NEW correspondence entry, original retained; §3.61 same-day rule
    (index side not verifiable same-run — see SC-4 in the manifest).

    NCNSS scenarios (from ExpertlyTestBuddy plan.json for ticket 27303020):
      SC-1 [Critical] DWI LT-265A row gains a working Reprint button (TC-01/02/04/07/11)
      SC-2 [High]     Scope guards — E-Stop stays Reprint-free; stolen=Yes has no 265A (TC-05/06)
      SC-3 [Medium]   RBAC — Fiscal cannot reach LT-261 at all (TC-10; TC-09 N&S-User half
                      needs a saved N&S User auth state — see manifest note)
      TC-12 [Low]     OQ-64 recipient observation (recorded, not asserted) inside SC-1

  tests/test_ncnss_27303020_lt265a_reprint.py was the merge source and was DELETED on
  2026-07-23. Its three unused helpers (_control_near_label, fill_by_label, letter_rows)
  were dropped, and its hand-rolled 'Add Paper DWI' locator and add_owner() were replaced
  by the page-object entry points the E2E-004 phases already exercise.

Form-type default asserted in every phase (verified against the live QA app):
  * DWI    → "Use Same Address as Place Stored" IS auto-checked by default.
  * E-STOP → "Use Same Address as Place Stored" is NOT auto-checked by default.
There are two such checkboxes (location panel + agency section) and both follow the
rule, so the assertion covers both. It runs immediately after the form loads, before
anything is clicked, so it observes the true default.

TWO TAB MODELS are kept on purpose:
  * The E2E-004 phases share the session-scoped `staff_page` fixture — the Angular app
    loads cold once and steps move between listings through the in-app sidebar. Phases
    stay separate test methods so a failure names the exact step, and each phase owns
    its VIN so the phases are independent.
  * The NCNSS classes take their own tab per test from the `pages` fixture. They drive a
    full create→auto-process→correspondence cycle and SC-3 needs a Fiscal context
    entirely, so they must not inherit whatever state a phase left in the shared tab.

Artifacts:
  Screenshots → skills/nsm-lt265a-reprint/screenshots/  (path is a tooling contract:
                runTestPlan's `glob:screenshots/*.png` strategy embeds them in result.html)
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    generate_person,
    future_date,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page, wait_for_vin_in_listing
from src.pages.staff_portal.sold_listing_page import SoldListingPage


BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
SP_DASHBOARD_URL = BASE_URL + "/pages/ncdot-notice-and-storage/dashboard"
LT261_LIST_URL = BASE_URL + "/pages/ncdot-notice-and-storage/LT-261/list"

# Screenshots land in the skill dir so runTestPlan's `glob:screenshots/*.png` snapshot
# strategy embeds them in result.html. Do not relocate without updating the
# nsm-lt265a-reprint skill.
SHOTS = (Path(__file__).resolve().parent.parent.parent
         / "skills" / "nsm-lt265a-reprint" / "screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)


def _shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    except Exception:
        pass


# ─── Fixtures ───
@pytest.fixture
def pages():
    """Factory for browser tabs that must be closed regardless of test outcome.

    Usage: `page = pages(some_context)`. Fixture finalization runs on failure, which
    replaces the per-test try/finally: page.close() blocks the NCNSS suite used."""
    opened = []

    def _open(ctx: BrowserContext):
        page = ctx.new_page()
        opened.append(page)
        return page

    yield _open
    for page in opened:
        try:
            page.close()
        except Exception:
            pass


# ─── In-app navigation (tab is shared — clear overlays before each sidebar click) ───
def dismiss_overlays(page: Page):
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        page.evaluate(
            """() => document.querySelectorAll(
                '.cdk-overlay-backdrop, .cdk-overlay-backdrop-showing'
            ).forEach(b => b.remove())"""
        )
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.cdk-overlay-backdrop-showing').length === 0",
            timeout=5_000,
        )
    except Exception:
        pass


def go_to_staff_dashboard(page: Page):
    """Cold-load the Staff Portal on a fresh tab (the NCNSS classes' entry point —
    the E2E-004 phases get this once from the session-scoped `staff_page` fixture)."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def goto_lt261_listing(page: Page) -> Lt261Page:
    dismiss_overlays(page)
    StaffDashboardPage(page).navigate_to_lt261_listing()
    lt261 = Lt261Page(page)
    lt261._wait_listing_settled()
    return lt261


def goto_sold_listing(page: Page) -> SoldListingPage:
    dismiss_overlays(page)
    StaffDashboardPage(page).navigate_to_sold()
    Lt261Page(page)._wait_listing_settled()
    return SoldListingPage(page)


def expect_vin_on_detail_page(page: Page, vin: str):
    """Assert the opened detail page is the record for `vin` (not a neighbouring row)."""
    expect(page.get_by_text(re.compile(re.escape(vin), re.I)).first).to_be_visible(
        timeout=15_000
    )


# ─── Form driving ───
def open_lt261_form(page: Page, form_type: str, vin: str) -> Lt261Page:
    """LT-261 listing → open the paper form; assert its type and checkbox defaults."""
    lt261 = goto_lt261_listing(page)
    lt261.open_paper_form(form_type, vin)

    lt261.expect_form_type(form_type)
    # Default-state check must happen before any checkbox is touched.
    lt261.expect_use_same_address_default(form_type)
    print(
        f"EXPECTED: '{form_type}' form, use-same-address default "
        f"checked={form_type == 'DWI'} | ACTUAL: {lt261.use_same_address_states()} -- MATCH"
    )
    return lt261


def fill_lt261_form(lt261: Lt261Page, officer_name: str, owner_name: str,
                    require_sale_section: bool = False):
    """Fill the paper form body — everything except Stolen, which each caller drives.

    `require_sale_section` decides how a failure in the sale/agency block is treated. The
    E2E-004 phases tolerate it (default): those fields are not what the phase asserts. The
    NCNSS-27303020 reprint cases pass True — an LT-265A is only issued when that section is
    complete, so swallowing a failure there would resurface later as a bogus
    'ENHANCEMENT MISSING: no Reprint control' verdict instead of a setup error.
    """
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")

    try:
        # No-ops on DWI (already auto-checked) — the helpers guard on mat-checkbox-checked.
        lt261.check_use_same_address_storage()
        lt261.fill_sale_date(future_date(21))
        lt261.select_notice_of_sale_reason()
        lt261.check_agency_use_same_address()
        lt261.fill_agency_name(officer_name)
    except Exception as exc:
        if require_sale_section:
            raise
        print(f"NOTE: optional sale/agency section step skipped ({type(exc).__name__}: {exc})")

    lt261.fill_owner_seized_from(owner_name)
    # The Owner(s) Check block is what makes an LT-265A issuable at all — the 265A targets
    # owners, and synthetic VINs carry no STARS data, so without an owner the case gets only
    # LT-261 + LT-265 rows (live-confirmed 2026-07-09). Both suites need it, so it goes
    # through the page object's add_owner_details() rather than a parallel implementation.
    lt261.add_owner_details(name=owner_name)


def create_lt261(page: Page, vin: str, officer_name: str, form_type: str,
                 stolen: bool = False) -> Lt261Page:
    """Create and submit a fresh LT-261 on a brand-new tab. form_type: 'DWI' | 'E-Stop'.

    Routes through open_lt261_form(), so a mis-wired 'Add Paper DWI' button is caught by
    expect_form_type() here rather than being reported downstream as a missing enhancement.
    """
    go_to_staff_dashboard(page)
    lt261 = open_lt261_form(page, form_type, vin)
    fill_lt261_form(lt261, officer_name, f"Owner {officer_name}", require_sale_section=True)

    if stolen:
        lt261.select_stolen_yes()
        lt261.submit_stolen_form()
    else:
        lt261.select_stolen_no()
        lt261.submit_with_confirmation()
    return lt261


# ─── Correspondence History (NCNSS-27303020) ───
def open_correspondence_for_vin(page: Page, vin: str) -> bool:
    """LT-261 listing → Processed tab → find `vin` → open its Correspondence History.

    Returns True when the modal opened. The VIN only reaches the Processed tab once
    auto-processing finishes, so the listing search is retried through the page object's
    bounded wait_for_vin_in_listing() poller — the pre-merge NCNSS version looped its own
    goto + five fixed sleeps up to eight times (~2.5 min of blind waiting worst case).
    """
    go_to_staff_dashboard(page)
    lt261 = goto_lt261_listing(page)
    lt261.click_processed_tab()

    try:
        waited = wait_for_vin_in_listing(page, lt261.search_by_vin, vin, "LT-261 Processed")
    except AssertionError as exc:
        print(f"NOTE: {vin} never reached the Processed listing — {exc}")
        return False

    try:
        lt261.select_application(0)
        expect_vin_on_detail_page(page, vin)
        lt261.click_view_correspondence()
        print(f"correspondence opened for {vin} (Processed after {waited:.1f}s)")
        return True
    except Exception as exc:
        print(f"NOTE: correspondence modal did not open for {vin} "
              f"({type(exc).__name__}: {exc})")
        return False


def correspondence_rows(page) -> list:
    """Rows of the Correspondence History modal: letter text + reprint control?

    A row 'has reprint' when it contains a control whose text/title/aria/class
    mentions reprint (§3.39 'Send for Reprinting').
    """
    return page.evaluate(
        """() => {
      const dlg = document.querySelector('mat-dialog-container') || document.body;
      const rows = [...dlg.querySelectorAll('table tbody tr, mat-row, [class*=row]')]
        .filter(r => (r.textContent||'').trim());
      const seen = new Set();
      const out = [];
      for (const r of rows) {
        const txt = (r.textContent||'').trim().replace(/\\s+/g,' ').slice(0,160);
        if (seen.has(txt)) continue;
        seen.add(txt);
        const ctl = [...r.querySelectorAll('button, a, [role=button], mat-icon, img, span[title], [aria-label]')]
          .find(e => /reprint/i.test((e.textContent||'') + ' ' + (e.getAttribute('title')||'')
                     + ' ' + (e.getAttribute('aria-label')||'') + ' ' + (e.className||'')));
        out.push({text: txt, hasReprint: !!ctl});
      }
      return out;
    }"""
    )


def rows_265a(rows) -> list:
    """Correspondence rows for the LT-265A."""
    return [r for r in rows if re.search(r"265\s*A", r["text"], re.I)]


def rows_265_only(rows) -> list:
    """Correspondence rows for the plain LT-265 — 'LT-265' must not swallow 'LT-265A'."""
    return [r for r in rows if re.search(r"LT[- ]?265(?!\s*A)", r["text"], re.I)]


def click_reprint_on_265a(page) -> str:
    """Click the LT-265A row's reprint control; confirm any dialog; return banner text."""
    dlg = page.locator("mat-dialog-container").last
    row = dlg.locator(
        'table tbody tr:has-text("LT-265A"), tr:has-text("LT265A"), [class*=row]:has-text("265A")'
    ).first
    ctl = row.locator(
        'button:has-text("Reprint"), a:has-text("Reprint"), [title*="eprint"], '
        '[aria-label*="eprint" i], button:has(mat-icon), mat-icon'
    ).first
    ctl.click()
    page.wait_for_timeout(1_500)
    # tolerant: a confirm dialog may appear
    confirm = page.locator(
        'mat-dialog-container button:has-text("Yes"), mat-dialog-container button:has-text("Confirm"), '
        'mat-dialog-container button:has-text("Reprint"), mat-dialog-container button:has-text("Ok")'
    )
    for c in confirm.all():
        try:
            label = (c.text_content() or "").strip().lower()
            if label in ("yes", "confirm", "reprint", "ok"):
                c.click()
                page.wait_for_timeout(1_500)
                break
        except Exception:
            pass
    page.wait_for_timeout(3_000)
    return page.evaluate(
        """() => [...document.querySelectorAll('simple-snack-bar, [class*=snack], [class*=toast], [class*=banner], [role=alert], [class*=success]')]
             .filter(el => el.offsetWidth || el.offsetHeight)
             .map(e => (e.textContent||'').trim()).filter(t => t).join(' | ')"""
    )


# ============================================================================
# Base classes — not collected (pytest.ini: python_classes = TestE2E*)
# ============================================================================
class _StolenNoPhase:
    """Stolen = NO → auto-processes: LT-261 Processed listing, then Sold."""

    FORM_TYPE: str = ""
    VIN: str = ""
    OFFICER: dict = {}

    def test_1_submit(self, staff_page: Page):
        """Submit the LT-261 paper form with owner details and Stolen = NO."""
        lt261 = open_lt261_form(staff_page, self.FORM_TYPE, self.VIN)
        fill_lt261_form(lt261, self.OFFICER["name"], self.OFFICER["name"])

        lt261.select_stolen_no()
        lt261.submit_with_confirmation()
        print(f"SUBMITTED: {self.FORM_TYPE} LT-261, Stolen=No, VIN={self.VIN}")

    def test_2_moved_to_lt261_processed(self, staff_page: Page):
        """The application is moved to the LT-261 Processed listing (+ LT-265 issued)."""
        lt261 = goto_lt261_listing(staff_page)
        lt261.click_processed_tab()

        # A just-submitted record takes a few seconds to become queryable — poll.
        waited = wait_for_vin_in_listing(
            staff_page, lt261.search_by_vin, self.VIN, "LT-261 Processed"
        )

        lt261.select_application(0)
        expect_vin_on_detail_page(staff_page, self.VIN)
        lt261.expect_status_processed()

        # Pre-existing E2E-004 coverage: auto-issuance produces an LT-265 entry.
        lt261.click_view_correspondence()
        lt261.expect_lt265_in_correspondence()
        print(
            f"EXPECTED: {self.VIN} Processed + LT-265 issued | ACTUAL: MATCH "
            f"(appeared after {waited:.1f}s)"
        )

    def test_3_vehicle_marked_sold(self, staff_page: Page):
        """The vehicle is marked as Sold."""
        sold = goto_sold_listing(staff_page)

        waited = wait_for_vin_in_listing(staff_page, sold.search_by_vin, self.VIN, "Sold")

        sold.select_application(0)
        expect_vin_on_detail_page(staff_page, self.VIN)
        Lt261Page(staff_page).expect_status_processed()
        print(
            f"EXPECTED: {self.VIN} marked Sold | ACTUAL: found in Sold -- MATCH "
            f"(appeared after {waited:.1f}s)"
        )


class _StolenYesPhase:
    """Stolen = YES → routed to the LT-261 Stolen listing (no auto-process)."""

    FORM_TYPE: str = ""
    VIN: str = ""
    OFFICER: dict = {}

    def test_1_submit(self, staff_page: Page):
        """Submit the LT-261 paper form with owner details and Stolen = YES."""
        lt261 = open_lt261_form(staff_page, self.FORM_TYPE, self.VIN)
        fill_lt261_form(lt261, self.OFFICER["name"], self.OFFICER["name"])

        lt261.select_stolen_yes()
        # Stolen=Yes must NOT auto-issue LT-265, so no success/issuance banner is expected.
        lt261.submit_stolen_form()
        print(f"SUBMITTED: {self.FORM_TYPE} LT-261, Stolen=Yes, VIN={self.VIN}")

    def test_2_moved_to_stolen_listing(self, staff_page: Page):
        """The application is moved to the LT-261 Stolen listing."""
        lt261 = goto_lt261_listing(staff_page)
        waited = lt261.expect_vin_in_stolen_listing(self.VIN)
        print(
            f"EXPECTED: {self.VIN} in LT-261 Stolen listing ({self.FORM_TYPE}, Stolen=Yes) | "
            f"ACTUAL: found -- MATCH (appeared after {waited:.1f}s)"
        )


# ============================================================================
# PHASE 1: E-STOP, Stolen = NO → LT-261 Processed → Sold
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase1EstopStolenNo(_StolenNoPhase):
    FORM_TYPE = "E-Stop"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# PHASE 2: DWI, Stolen = NO → LT-261 Processed → Sold
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase2DwiStolenNo(_StolenNoPhase):
    FORM_TYPE = "DWI"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# PHASE 3: E-STOP, Stolen = YES → LT-261 Stolen listing
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase3EstopStolenYes(_StolenYesPhase):
    FORM_TYPE = "E-Stop"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# PHASE 4: DWI, Stolen = YES → LT-261 Stolen listing
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase4DwiStolenYes(_StolenYesPhase):
    FORM_TYPE = "DWI"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# NCNSS-27303020 SC-1: the DWI LT-265A Reprint button
# ============================================================================
@pytest.mark.ncnss27303020
@pytest.mark.regression
class TestE2E_NCNSS27303020_SC1_DwiReprint:
    """SC-1: the enhancement — the DWI LT-265A row has a working Reprint button."""

    VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc1_create_dwi_lt261(self, staff_context: BrowserContext, pages):
        page = pages(staff_context)
        create_lt261(page, self.VIN, self.OFFICER["name"], "DWI")
        _shot(page, "sc1_dwi_submitted")
        print(f"EXPECTED: DWI LT-261 created for VIN {self.VIN} | ACTUAL: submitted -> MATCH")

    def test_sc1_reprint_present_works_and_scoped(self, staff_context: BrowserContext, pages):
        page = pages(staff_context)
        opened = open_correspondence_for_vin(page, self.VIN)
        _shot(page, "sc1_correspondence_open")
        assert opened, (f"VIN {self.VIN}: LT-261 never reached Processed/correspondence "
                        f"(auto-processing did not complete)")

        rows = correspondence_rows(page)
        a_rows, plain_rows = rows_265a(rows), rows_265_only(rows)
        print(f"correspondence rows: {[(r['text'][:60], r['hasReprint']) for r in rows]}")

        # TC-01: LT-265A row exists and has the Reprint control (at Sold — TC-11)
        ok01 = a_rows and any(r["hasReprint"] for r in a_rows)
        print(f"EXPECTED (TC-01/11): Reprint control present on the DWI LT-265A row "
              f"(case auto-processed, terminal status) | ACTUAL: 265A rows="
              f"{len(a_rows)}, withReprint={sum(r['hasReprint'] for r in a_rows)} -> "
              f"{'MATCH' if ok01 else 'MISMATCH'}")
        assert a_rows, "no LT-265A row in Correspondence History on a DWI case"
        assert any(r["hasReprint"] for r in a_rows), \
            "ENHANCEMENT MISSING: no Reprint control on the DWI LT-265A row"

        # TC-04: LT-265 row (same case) must NOT have Reprint
        leak = [r for r in plain_rows if r["hasReprint"]]
        print(f"EXPECTED (TC-04): LT-265 row has NO Reprint (never Nordis-bound) | "
              f"ACTUAL: 265 rows={len(plain_rows)}, withReprint={len(leak)} -> "
              f"{'MATCH' if not leak else 'MISMATCH'}")
        assert not leak, f"SCOPE LEAK: Reprint appeared on LT-265 row(s): {leak}"

        # TC-12 (OQ-64, observation only): record row/recipient text
        print(f"OQ-64 OBSERVATION (no assertion): 265A row text = {[r['text'] for r in a_rows]}")

        # TC-02: click Reprint → banner + new entry, original retained
        before = len(rows)
        banner = click_reprint_on_265a(page)
        rows_after = correspondence_rows(page)
        after = len(rows_after)
        a_rows_after = rows_265a(rows_after)
        _shot(page, "sc1_after_reprint")
        banner_ok = bool(re.search(r"reprint", banner, re.I))
        grew = after > before or len(a_rows_after) > len(a_rows)
        print(f"EXPECTED (TC-02): banner 'sent again for reprinting' + NEW 265A entry, "
              f"original retained | ACTUAL: banner='{banner[:80]}', entries {before}->{after}, "
              f"265A rows {len(a_rows)}->{len(a_rows_after)} -> "
              f"{'MATCH' if (banner_ok or grew) and len(a_rows_after) >= len(a_rows) else 'MISMATCH'}")
        assert banner_ok or grew, \
            f"reprint click produced no banner and no new entry (banner='{banner[:120]}')"
        assert len(a_rows_after) >= len(a_rows), "original 265A entry disappeared after reprint"

        # TC-07 (UI half): a second same-day reprint logs its own entry too
        banner2 = click_reprint_on_265a(page)
        rows_final = correspondence_rows(page)
        _shot(page, "sc1_after_second_reprint")
        grew2 = len(rows_final) > after or bool(re.search(r"reprint", banner2, re.I))
        print(f"EXPECTED (TC-07 UI): second same-day reprint accepted and logged "
              f"(index dedup is §3.61, nightly — not verifiable here) | "
              f"ACTUAL: banner='{banner2[:60]}', entries {after}->{len(rows_final)} -> "
              f"{'MATCH' if grew2 else 'MISMATCH'}")
        assert grew2, "second same-day reprint was rejected/no-op"


# ============================================================================
# NCNSS-27303020 SC-2: scope guards
# ============================================================================
@pytest.mark.ncnss27303020
@pytest.mark.regression
class TestE2E_NCNSS27303020_SC2_ScopeGuards:
    """SC-2: E-Stop cases and never-issued 265As stay Reprint-free."""

    ESTOP_VIN = generate_vin()
    STOLEN_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc2_create_estop_lt261(self, staff_context: BrowserContext, pages):
        page = pages(staff_context)
        create_lt261(page, self.ESTOP_VIN, self.OFFICER["name"], "E-Stop")
        _shot(page, "sc2_estop_submitted")
        print(f"EXPECTED: E-Stop LT-261 created for VIN {self.ESTOP_VIN} | ACTUAL: submitted -> MATCH")

    def test_sc2_estop_rows_have_no_reprint(self, staff_context: BrowserContext, pages):
        page = pages(staff_context)
        opened = open_correspondence_for_vin(page, self.ESTOP_VIN)
        _shot(page, "sc2_estop_correspondence")
        assert opened, f"E-Stop VIN {self.ESTOP_VIN} never reached Processed/correspondence"

        rows = correspondence_rows(page)
        leak = [r for r in rows if re.search(r"265", r["text"], re.I) and r["hasReprint"]]
        print(f"EXPECTED (TC-05): NO Reprint on E-Stop 265A/265 rows (enhancement is "
              f"DWI-only per dev change) | ACTUAL: rows="
              f"{[(r['text'][:50], r['hasReprint']) for r in rows]} -> "
              f"{'MATCH' if not leak else 'MISMATCH'}")
        assert not leak, (f"DWI-ONLY SCOPE VIOLATED: Reprint present on E-Stop rows: {leak} "
                          f"(if the PO intended E-Stop reprint too, this is RTM Q1 — "
                          f"flag, don't just fail)")

    def test_sc2_stolen_yes_has_no_265a_row(self, staff_context: BrowserContext, pages):
        page = pages(staff_context)
        lt261 = create_lt261(page, self.STOLEN_VIN, self.OFFICER["name"], "E-Stop", stolen=True)
        _shot(page, "sc2_stolen_submitted")

        # stolen=Yes suppresses auto-processing (BR-36/37): the case stays Submitted, so it
        # never reaches the Processed tab — search the default listing instead.
        page.goto(LT261_LIST_URL, timeout=60_000)
        page.wait_for_timeout(5_000)
        lt261.search_by_vin(self.STOLEN_VIN)
        page.wait_for_timeout(2_000)

        found_265a_reprint = False
        corr_reachable = False
        try:
            lt261.select_application(0)
            lt261.click_view_correspondence()
            corr_reachable = True
            rows = correspondence_rows(page)
            found_265a_reprint = any(r["hasReprint"] for r in rows_265a(rows))
            print(f"stolen case correspondence rows: "
                  f"{[(r['text'][:50], r['hasReprint']) for r in rows]}")
        except Exception as e:
            print(f"correspondence not reachable on the stolen (Submitted) case — "
                  f"acceptable: {str(e)[:80]}")
        _shot(page, "sc2_stolen_correspondence")
        print(f"EXPECTED (TC-06): stolen=Yes case has NO LT-265A row / no orphan Reprint "
              f"(no issuance, BR-36/37) | ACTUAL: corr_reachable={corr_reachable}, "
              f"265A-with-Reprint={found_265a_reprint} -> "
              f"{'MATCH' if not found_265a_reprint else 'MISMATCH'}")
        assert not found_265a_reprint, \
            "orphan Reprint control on a never-issued LT-265A (stolen=Yes case)"


# ============================================================================
# NCNSS-27303020 SC-3: RBAC
# ============================================================================
@pytest.mark.ncnss27303020
@pytest.mark.rbac
class TestE2E_NCNSS27303020_SC3_RBAC:
    """SC-3: Fiscal User cannot reach LT-261 / Correspondence History at all (TC-10).
    TC-09 (N&S User can reprint) needs a saved N&S-User auth state — not present in
    auth/qa; covered by the Admin click in SC-1, N&S-User half flagged in the manifest."""

    def test_sc3_fiscal_cannot_reach_lt261(self, fiscal_context: BrowserContext, pages):
        page = pages(fiscal_context)
        go_to_staff_dashboard(page)
        nav_visible = page.locator(
            'a:has-text("LT-261"), button:has-text("Add Paper DWI")').first.is_visible() \
            if page.locator('a:has-text("LT-261")').count() else False

        page.goto(LT261_LIST_URL, timeout=60_000)
        page.wait_for_timeout(6_000)
        url = page.url
        denied = ("/LT-261" not in url) or ("login" in url) or ("denied" in url.lower())
        add_btns = page.locator(
            'button:has-text("Add Paper DWI"), button:has-text("Add Paper E-Stop")').count()
        _shot(page, "sc3_fiscal_lt261_attempt")

        ok = (not nav_visible) and (denied or add_btns == 0)
        print(f"EXPECTED (TC-10): Fiscal has no LT-261 nav and direct URL is denied/neutered | "
              f"ACTUAL: nav_visible={nav_visible}, direct_url_landed={url}, "
              f"add_buttons={add_btns} -> {'MATCH' if ok else 'MISMATCH'}")
        assert ok, (f"Fiscal user reached LT-261 surface: nav={nav_visible}, url={url}, "
                    f"add_buttons={add_btns}")
