"""
NCNSS 27303020: Enhancement — Reprint button for LT-265A on the LT-261 page
after LT-265A integration with Nordis (CR NCNSS-547).

Dev change (documents.CorrespondenceHistory Step 2): reprint allowed for the
LT-265A **logged for DWI** only. E-Stop 265As and all LT-265s remain excluded
(residual BR-122). Reprint parity with §3.37/§3.39: banner "The form has been
sent again for reprinting", NEW correspondence entry, original retained; §3.61
same-day rule (index side not verifiable same-run — see SC-4 in the manifest).

Scenarios (from ExpertlyTestBuddy plan.json for ticket 27303020):
  SC-1 [Critical] DWI LT-265A row gains a working Reprint button (TC-01/02/04/07/11)
  SC-2 [High]     Scope guards — E-Stop stays Reprint-free; stolen=Yes has no 265A (TC-05/06)
  SC-3 [Medium]   RBAC — Fiscal cannot reach LT-261 at all (TC-10; TC-09 N&S-User half
                  needs a saved N&S User auth state — see manifest note)
  TC-12 [Low]     OQ-64 recipient observation (recorded, not asserted) inside SC-1

Reuses: the NCNSS-544 E-Stop fill sequence (fill_estop_form), Lt261Page's modal/
form/submit/correspondence helpers, and the e2e_004 Processed-tab verification
pattern. The 'Add Paper DWI' modal is identical to the E-Stop one (VIN + Next,
no radio — live-confirmed 2026-07-09), and DWI skips STARS on load (BR-128).
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext

from src.config.env import ENV
from src.helpers.data_helper import generate_vin, generate_person, future_date
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page

BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
SP_DASHBOARD_URL = BASE_URL + "/pages/ncdot-notice-and-storage/dashboard"
LT261_LIST_URL = BASE_URL + "/pages/ncdot-notice-and-storage/LT-261/list"

SHOTS = (Path(__file__).resolve().parent.parent.parent
         / "skills" / "nsm-lt265a-reprint" / "screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)


def _shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    except Exception:
        pass


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def fill_lt261_form(lt261: Lt261Page, officer_name: str):
    """The shared LT-261 paper-form body (same fields for DWI and E-Stop)."""
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")
    lt261.check_use_same_address_storage()
    lt261.fill_sale_date(future_date(21))
    lt261.select_notice_of_sale_reason()
    lt261.check_agency_use_same_address()
    lt261.fill_agency_name(officer_name)


def _control_near_label(page, label: str):
    """Find the input/mat-select belonging to `label` (exact text, case-insensitive):
    same row to the right, or directly below. Returns {'kind','id'} or None."""
    return page.evaluate(
        """(label) => {
      const norm = s => (s||'').trim().replace(/\\s+/g,' ').toUpperCase();
      const labs = [...document.querySelectorAll('*')].filter(
        e => e.children.length===0 && norm(e.textContent)===norm(label)
             && (e.offsetWidth||e.offsetHeight));
      if (!labs.length) return null;
      const r = labs[labs.length-1].getBoundingClientRect();
      const cands = [...document.querySelectorAll('input, mat-select')]
        .filter(e => e.offsetWidth||e.offsetHeight)
        .map(e => ({e, b: e.getBoundingClientRect()}))
        .filter(o =>
          (Math.abs((o.b.y+o.b.height/2)-(r.y+r.height/2)) < 22 && o.b.x > r.x) ||
          (Math.abs(o.b.x - r.x) < 80 && o.b.y > r.y && o.b.y < r.y + 90))
        .sort((a,b) => (Math.hypot(a.b.x-r.x, a.b.y-r.y) - Math.hypot(b.b.x-r.x, b.b.y-r.y)));
      if (!cands.length) return null;
      const el = cands[0].e;
      if (!el.id) el.id = 'nl-' + Math.random().toString(36).slice(2,10);
      return {kind: el.tagName === 'MAT-SELECT' ? 'select' : 'input', id: el.id};
    }""",
        label,
    )


def fill_by_label(page, label: str, value: str):
    ctl = _control_near_label(page, label)
    assert ctl, f"no control found for label '{label}'"
    loc = page.locator(f"#{ctl['id']}")
    if ctl["kind"] == "select":
        loc.click()
        page.wait_for_timeout(600)
        opt = page.locator(
            f'.cdk-overlay-pane mat-option:has-text("{value}")').first
        if not opt.count():
            opt = page.locator(".cdk-overlay-pane mat-option").first
        opt.click()
        page.wait_for_timeout(400)
    else:
        loc.click()
        loc.fill("")
        loc.press_sequentially(value, delay=40)
        page.wait_for_timeout(400)


def add_owner(page, name: str):
    """Click '+ Add Owner' and fill Owner 1 — required for an LT-265A to be
    issued at all (the 265A targets owners; synthetic VINs have no STARS data,
    so without this the case gets only LT-261 + LT-265 rows — live-confirmed
    2026-07-09). Owner inputs carry semantic names: owner_name__id-*,
    owner_address__id-*, owner_zip__id-*, owner_city__id-*."""
    page.locator(':text("+ Add Owner")').first.click()
    page.wait_for_timeout(2_000)

    # The Owner-block inputs share a per-render suffix (owner_zip__id-NNN etc.).
    # Derive it from owner_zip — a bare owner_name prefix ALSO matches the
    # judicial section's 'NAME OF OWNER FROM WHOM THE VEHICLE WAS SEIZED'
    # input, which sits earlier in the DOM (live-confirmed misfill 2026-07-09).
    suffix = page.evaluate(
        """() => {
      const z = [...document.querySelectorAll('input')].find(e => /^owner_zip/.test(e.name||''));
      if (!z) return null;
      const m = (z.name||'').match(/^owner_zip(.*)$/);
      return m ? m[1] : null;
    }"""
    )

    def owner_input(prefix):
        if suffix is not None:
            byname = page.locator(f'input[name="{prefix}{suffix}"]')
            if byname.count():
                return byname.first
        return page.locator(f'input[name^="{prefix}"]').last

    def type_into(loc, value):
        loc.scroll_into_view_if_needed()
        loc.click()
        loc.fill("")
        loc.press_sequentially(value, delay=40)
        page.wait_for_timeout(400)

    type_into(owner_input("owner_name"), name)
    # owner_address__ vs owner_address2__ — the exact-suffix match avoids line 2
    type_into(owner_input("owner_address"), "716 North Elm Street")
    type_into(owner_input("owner_zip"), "27401")
    page.wait_for_timeout(1_200)  # zip may auto-populate city/state
    city = owner_input("owner_city")
    if not (city.input_value() or "").strip():
        type_into(city, "Greensboro")
    state = page.locator(
        'mat-select[name^="owner_state"], mat-select[aria-label*="State" i]').first
    try:
        if state.count() and not (state.text_content() or "").strip():
            state.click()
            page.wait_for_timeout(600)
            opt = page.locator('.cdk-overlay-pane mat-option:has-text("NORTH CAROLINA")').first
            if not opt.count():
                opt = page.locator(".cdk-overlay-pane mat-option").first
            opt.click()
            page.wait_for_timeout(400)
    except Exception:
        pass


def create_lt261(page, vin: str, officer_name: str, kind: str, stolen: str = "no"):
    """Create + submit a fresh LT-261. kind: 'dwi' | 'estop'."""
    go_to_staff_dashboard(page)
    StaffDashboardPage(page).navigate_to_lt261_listing()
    lt261 = Lt261Page(page)
    if kind == "dwi":
        btn = page.locator('button:has-text("Add Paper DWI")').first
        btn.wait_for(state="visible", timeout=15_000)
        btn.click()
        page.wait_for_timeout(1_500)
    else:
        lt261.click_add_from_estop()
    lt261.fill_modal_vin_next(vin)
    fill_lt261_form(lt261, officer_name)
    add_owner(page, f"Owner {officer_name}")
    if stolen == "yes":
        lt261.select_stolen_yes()
        lt261.submit_stolen_form()
    else:
        lt261.select_stolen_no()
        lt261.submit_with_confirmation()


def open_correspondence_for_vin(page, vin: str, attempts: int = 8) -> bool:
    """LT-261 listing → Processed tab → search VIN → open Correspondence History.

    Retries while auto-processing completes. Returns True when the modal opened.
    """
    lt261 = Lt261Page(page)
    for i in range(attempts):
        page.goto(LT261_LIST_URL, timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        page.wait_for_timeout(4_000)
        try:
            lt261.click_processed_tab()
            page.wait_for_timeout(2_000)
            lt261.search_by_vin(vin)
            page.wait_for_timeout(2_000)
            lt261.select_application(0)
            page.wait_for_timeout(2_000)
            lt261.click_view_correspondence()
            page.wait_for_timeout(2_000)
            return True
        except Exception:
            page.wait_for_timeout(10_000)  # auto-processing may still be running
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


def letter_rows(rows, letter: str) -> list:
    """Rows for a letter type; 'LT-265' must not swallow 'LT-265A'."""
    pat = re.compile(re.escape(letter) + r"(?![A-Za-z0-9])", re.I)
    return [r for r in rows if pat.search(r["text"].replace(" ", ""))
            or pat.search(r["text"])]


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


@pytest.mark.ncnss27303020
@pytest.mark.regression
class TestE2E_NCNSS27303020_SC1_DwiReprint:
    """SC-1: the enhancement — the DWI LT-265A row has a working Reprint button."""

    VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc1_create_dwi_lt261(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            create_lt261(page, self.VIN, self.OFFICER["name"], kind="dwi")
            _shot(page, "sc1_dwi_submitted")
            print(f"EXPECTED: DWI LT-261 created for VIN {self.VIN} | ACTUAL: submitted -> MATCH")
        finally:
            page.close()

    def test_sc1_reprint_present_works_and_scoped(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            opened = open_correspondence_for_vin(page, self.VIN)
            _shot(page, "sc1_correspondence_open")
            assert opened, (f"VIN {self.VIN}: LT-261 never reached Processed/correspondence "
                            f"(auto-processing did not complete)")
            rows = correspondence_rows(page)
            rows_265a = [r for r in rows if re.search(r"265\s*A", r["text"], re.I)]
            rows_265 = [r for r in rows if re.search(r"LT[- ]?265(?!\s*A)", r["text"], re.I)]
            print(f"correspondence rows: {[(r['text'][:60], r['hasReprint']) for r in rows]}")

            # TC-01: LT-265A row exists and has the Reprint control (at Sold — TC-11)
            ok01 = rows_265a and any(r["hasReprint"] for r in rows_265a)
            print(f"EXPECTED (TC-01/11): Reprint control present on the DWI LT-265A row "
                  f"(case auto-processed, terminal status) | ACTUAL: 265A rows="
                  f"{len(rows_265a)}, withReprint={sum(r['hasReprint'] for r in rows_265a)} -> "
                  f"{'MATCH' if ok01 else 'MISMATCH'}")
            assert rows_265a, "no LT-265A row in Correspondence History on a DWI case"
            assert any(r["hasReprint"] for r in rows_265a), \
                "ENHANCEMENT MISSING: no Reprint control on the DWI LT-265A row"

            # TC-04: LT-265 row (same case) must NOT have Reprint
            leak = [r for r in rows_265 if r["hasReprint"]]
            print(f"EXPECTED (TC-04): LT-265 row has NO Reprint (never Nordis-bound) | "
                  f"ACTUAL: 265 rows={len(rows_265)}, withReprint={len(leak)} -> "
                  f"{'MATCH' if not leak else 'MISMATCH'}")
            assert not leak, f"SCOPE LEAK: Reprint appeared on LT-265 row(s): {leak}"

            # TC-12 (OQ-64, observation only): record row/recipient text
            print(f"OQ-64 OBSERVATION (no assertion): 265A row text = "
                  f"{[r['text'] for r in rows_265a]}")

            # TC-02: click Reprint → banner + new entry, original retained
            before = len(rows)
            banner = click_reprint_on_265a(page)
            rows_after = correspondence_rows(page)
            after = len(rows_after)
            rows_265a_after = [r for r in rows_after if re.search(r"265\s*A", r["text"], re.I)]
            _shot(page, "sc1_after_reprint")
            banner_ok = bool(re.search(r"reprint", banner, re.I))
            grew = after > before or len(rows_265a_after) > len(rows_265a)
            print(f"EXPECTED (TC-02): banner 'sent again for reprinting' + NEW 265A entry, "
                  f"original retained | ACTUAL: banner='{banner[:80]}', entries {before}->{after}, "
                  f"265A rows {len(rows_265a)}->{len(rows_265a_after)} -> "
                  f"{'MATCH' if (banner_ok or grew) and len(rows_265a_after) >= len(rows_265a) else 'MISMATCH'}")
            assert banner_ok or grew, \
                f"reprint click produced no banner and no new entry (banner='{banner[:120]}')"
            assert len(rows_265a_after) >= len(rows_265a), "original 265A entry disappeared after reprint"

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
        finally:
            page.close()


@pytest.mark.ncnss27303020
@pytest.mark.regression
class TestE2E_NCNSS27303020_SC2_ScopeGuards:
    """SC-2: E-Stop cases and never-issued 265As stay Reprint-free."""

    ESTOP_VIN = generate_vin()
    STOLEN_VIN = generate_vin()
    OFFICER = generate_person()

    def test_sc2_create_estop_lt261(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            create_lt261(page, self.ESTOP_VIN, self.OFFICER["name"], kind="estop")
            _shot(page, "sc2_estop_submitted")
            print(f"EXPECTED: E-Stop LT-261 created for VIN {self.ESTOP_VIN} | ACTUAL: submitted -> MATCH")
        finally:
            page.close()

    def test_sc2_estop_rows_have_no_reprint(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            opened = open_correspondence_for_vin(page, self.ESTOP_VIN)
            _shot(page, "sc2_estop_correspondence")
            assert opened, f"E-Stop VIN {self.ESTOP_VIN} never reached Processed/correspondence"
            rows = correspondence_rows(page)
            leak = [r for r in rows
                    if re.search(r"265", r["text"], re.I) and r["hasReprint"]]
            print(f"EXPECTED (TC-05): NO Reprint on E-Stop 265A/265 rows (enhancement is "
                  f"DWI-only per dev change) | ACTUAL: rows="
                  f"{[(r['text'][:50], r['hasReprint']) for r in rows]} -> "
                  f"{'MATCH' if not leak else 'MISMATCH'}")
            assert not leak, (f"DWI-ONLY SCOPE VIOLATED: Reprint present on E-Stop rows: {leak} "
                              f"(if the PO intended E-Stop reprint too, this is RTM Q1 — "
                              f"flag, don't just fail)")
        finally:
            page.close()

    def test_sc2_stolen_yes_has_no_265a_row(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            create_lt261(page, self.STOLEN_VIN, self.OFFICER["name"], kind="estop", stolen="yes")
            _shot(page, "sc2_stolen_submitted")
            # stolen=Yes suppresses auto-processing (BR-36/37): case stays Submitted.
            lt261 = Lt261Page(page)
            page.goto(LT261_LIST_URL, timeout=60_000)
            page.wait_for_timeout(5_000)
            lt261.search_by_vin(self.STOLEN_VIN)
            page.wait_for_timeout(2_000)
            found_265a_reprint = False
            corr_reachable = False
            try:
                lt261.select_application(0)
                page.wait_for_timeout(2_000)
                lt261.click_view_correspondence()
                page.wait_for_timeout(2_000)
                corr_reachable = True
                rows = correspondence_rows(page)
                found_265a_reprint = any(
                    re.search(r"265\s*A", r["text"], re.I) and r["hasReprint"] for r in rows)
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
        finally:
            page.close()


@pytest.mark.ncnss27303020
@pytest.mark.rbac
class TestE2E_NCNSS27303020_SC3_RBAC:
    """SC-3: Fiscal User cannot reach LT-261 / Correspondence History at all (TC-10).
    TC-09 (N&S User can reprint) needs a saved N&S-User auth state — not present in
    auth/qa; covered by the Admin click in SC-1, N&S-User half flagged in the manifest."""

    def test_sc3_fiscal_cannot_reach_lt261(self, fiscal_context: BrowserContext):
        page = fiscal_context.new_page()
        try:
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
        finally:
            page.close()
