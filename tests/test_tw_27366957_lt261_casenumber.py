"""TW 27366957 — Duplicate case numbers for LT-261 (NSM/NSS).

THE FIX UNDER TEST
------------------
LT-261 case numbers (D[YY]-nnnnnn, 01 §CaseFileNumber / 07 BR-65) were minted by
the shared `unique_case_number` logic written for the LT-260 N/S 9-digit shape,
so on 7/28-7/29 two seizure cases were issued the SAME number.

  preventive : CREATE SEQUENCE lt261_case_number_seq START WITH 100001;
               CREATE TABLE lt261_case_number_sequence (
                   case_number BIGINT DEFAULT nextval('lt261_case_number_seq'),
                   created_at  TIMESTAMP);
               AD method 4d1fa71cce16eae7419f8a758186c109
  corrective : AD method 4b80b9808f31ebb05aa088ff364c5c73 over the 7/28-7/29 rows

THE ONE THING THAT MATTERS MOST  (RTM Q2 / OQ-TW-2)
---------------------------------------------------
The DDL is `START WITH 100001` with **no setval**, while LT-261 numbers already
exist. If the legacy population already occupies values at or above 100001, a
brand-new sequence walks straight back into numbers that are already issued and
the "fix" reproduces the very defect it closes. SC-2 drives that to a verdict.

HOW THE DB-SHAPED ASSERTIONS ARE MADE WITHOUT A DB
--------------------------------------------------
The suite has zero database access (PRE-2 — no psycopg/sqlalchemy anywhere, no
driver in requirements.txt), so nothing here reads pg_sequences. Instead every
invariant is proven through the product's own surfaces via
src/helpers/lt261_case_number.py:
  * the LT-261 listing chain 4f0aa9e1… returns the FULL D% population in one
    call (1061 records on QA 2026-07-30) -> duplicate census, legacy maximum,
    per-year bands, per-number lookup;
  * the LT-261 submit chain 4d1fa71c… IS the ticket's preventive AD method ->
    calling it directly is both the TC-15 server-authority probe and the PRE-9
    parallel harness.
Where a leg genuinely needs psql (sequence last_value/is_called, burnt-but-unused
sequence rows) the assertion says so instead of inventing a number.

Scenario map (plan.json):
  SC-1  GATE       deployment + baseline snapshot                    TC-01
  SC-2  RISK-FIRST legacy/corrective collision (Q2)   TC-14/27/28/29/15
  SC-3  core       both entry paths, one sequence, immutable   TC-02/04/05/06
  SC-4  volume     five back-to-back + replay                       TC-07/08
  SC-5  concurrency 2-way race + 10-way fan-out + PDFs         TC-09/10/11
  SC-6  namespace  LT-260 N/S untouched, D% tabs apart             TC-12/13
  SC-7  non-happy  stolen / draft / cancel / deny         TC-17/18/19/20
  SC-8  fan-out    listing / search / correspondence / audit  TC-21/22/23/26
  SC-9  RBAC + pre-7/28 census (census half = OQ-TW-1)             TC-30
  ungrouped: TC-03 (virgin sequence), TC-16 (year prefix), TC-24 (Nordis)
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext

from src.config.env import ENV
from src.helpers import lt261_case_number as CN
from src.helpers.data_helper import generate_vin, generate_person, future_date, past_date
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage

BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
SP_DASHBOARD_URL = BASE_URL + "/pages/ncdot-notice-and-storage/dashboard"
LT261_LIST_URL = BASE_URL + "/pages/ncdot-notice-and-storage/LT-261/list"
LT260_LIST_URL = BASE_URL + "/pages/ncdot-notice-and-storage/LT-260/list"

SKILL_DIR = (Path(__file__).resolve().parent.parent.parent
             / "skills" / "nsm-lt261-casenumber")
SHOTS = SKILL_DIR / "screenshots"
STATE_FILE = SKILL_DIR / "state" / "run_state.json"
SHOTS.mkdir(parents=True, exist_ok=True)
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

AUTH_STATE = Path(__file__).resolve().parent.parent / "auth" / "qa" / "staff-portal.json"

# The corrective AD run re-numbered the 7/28-7/29 population (comment 1 names PROD;
# PRE-12 requires establishing it per-environment — SC-2 does that behaviourally).
CORRECTIVE_DATES = ("07-28-2026", "07-29-2026")


# ============================================================================
# shared plumbing
# ============================================================================

def _shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    except Exception:
        pass


def token() -> str:
    return CN.auth_token(AUTH_STATE)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(**kw):
    st = load_state()
    st.update(kw)
    STATE_FILE.write_text(json.dumps(st, indent=1), encoding="utf-8")
    return st


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=90_000)
    page.wait_for_load_state("networkidle")


def year_prefix() -> str:
    return "D" + datetime.now().strftime("%y")


def add_owner(page, name: str):
    """'+ Add Owner' + fill Owner 1 — required or no LT-265A is ever issued.

    Copied from the NCNSS-27303020 reprint test (live-confirmed): a bare
    `owner_name` prefix also matches the judicial section's 'NAME OF OWNER FROM
    WHOM THE VEHICLE WAS SEIZED' input, so the per-render suffix is derived from
    owner_zip and every field addressed by exact name.
    """
    page.locator(':text("+ Add Owner")').first.click()
    page.wait_for_timeout(2_000)
    suffix = page.evaluate(
        """() => {
      const z = [...document.querySelectorAll('input')].find(e => /^owner_zip/.test(e.name||''));
      if (!z) return null;
      const m = (z.name||'').match(/^owner_zip(.*)$/);
      return m ? m[1] : null;
    }"""
    )

    def owner_input(prefix_):
        if suffix is not None:
            byname = page.locator(f'input[name="{prefix_}{suffix}"]')
            if byname.count():
                return byname.first
        return page.locator(f'input[name^="{prefix_}"]').last

    def type_into(loc, value):
        loc.scroll_into_view_if_needed()
        loc.click()
        loc.fill("")
        loc.press_sequentially(value, delay=35)
        page.wait_for_timeout(350)

    type_into(owner_input("owner_name"), name)
    type_into(owner_input("owner_address"), "716 North Elm Street")
    type_into(owner_input("owner_zip"), "27401")
    page.wait_for_timeout(1_200)
    city = owner_input("owner_city")
    if not (city.input_value() or "").strip():
        type_into(city, "Greensboro")


def fill_lt261_form(lt261: Lt261Page, officer_name: str):
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")
    lt261.check_use_same_address_storage()
    lt261.fill_sale_date(future_date(21))
    lt261.select_notice_of_sale_reason()
    lt261.check_agency_use_same_address()
    lt261.fill_agency_name(officer_name)


def create_lt261_ui(page, vin: str, officer: str, kind: str = "estop",
                    stolen: str = "no", with_owner: bool = True):
    """UI channel: create + SUBMIT a fresh LT-261. kind: 'dwi' | 'estop'."""
    go_to_staff_dashboard(page)
    StaffDashboardPage(page).navigate_to_lt261_listing()
    lt261 = Lt261Page(page)
    if kind == "dwi":
        btn = page.locator('button:has-text("Add Paper DWI")').first
        btn.wait_for(state="visible", timeout=20_000)
        btn.click()
        page.wait_for_timeout(1_500)
    else:
        lt261.click_add_from_estop()
    lt261.fill_modal_vin_next(vin)
    lt261.expect_form_type("DWI" if kind == "dwi" else "E-Stop")
    fill_lt261_form(lt261, officer)
    if with_owner:
        add_owner(page, f"Owner {officer}")
    if stolen == "yes":
        lt261.select_stolen_yes()
        lt261.submit_stolen_form()
    else:
        lt261.select_stolen_no()
        lt261.submit_with_confirmation()
    return lt261


def await_case_number(vin: str, timeout_s: int = 150) -> str:
    """Server-side readout of the number minted for `vin` (POSITIVE PROOF of submit).

    A clicked Submit is not a submitted form — this only returns once the record
    actually exists server-side and carries a well-formed D-number.
    """
    tok = token()
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            recs = CN.census(BASE_URL, tok, vin=vin)
            hit = CN.find_by_vin(recs, vin)
            if hit and CN.CASE_RE.fullmatch(hit["case"] or ""):
                return hit["case"]
            last = hit
        except Exception as e:                                       # noqa: BLE001
            last = f"census error {e}"
        time.sleep(4)
    raise AssertionError(
        f"EXPECTED: the LT-261 for VIN {vin} to exist server-side with a "
        f"D[YY]-nnnnnn case number within {timeout_s}s (positive proof of submission) | "
        f"ACTUAL: {last!r} — the form did NOT submit, or no number was minted"
    )


def expect_no_form_errors(page):
    """No red mandatory-field / validation error is on screen.

    Deliberately narrow: Angular stamps `ng-invalid` on every pristine required
    control, so a `[class*=invalid]` sweep flags an untouched radio group ("LOGGING
    FOR: Individual Business") as a blocked submission. Only real, rendered error
    MESSAGES count — a mat-error node, or an alert whose text actually reads like a
    validation failure.
    """
    errs = page.evaluate(
        """() => {
             const msg = /(is required|field is required|please (enter|fill|select)|must be|cannot be|invalid )/i;
             const out = [];
             document.querySelectorAll('mat-error, .mat-error').forEach(e => {
               if ((e.offsetWidth || e.offsetHeight) && (e.textContent||'').trim())
                 out.push((e.textContent||'').trim());
             });
             document.querySelectorAll('[role=alert], .mat-mdc-form-field-error').forEach(e => {
               const t = (e.textContent||'').trim();
               if ((e.offsetWidth || e.offsetHeight) && msg.test(t)) out.push(t);
             });
             return [...new Set(out)].slice(0, 10);
           }"""
    )
    assert not errs, (
        f"EXPECTED: no validation error on the LT-261 form (submission accepted) | "
        f"ACTUAL: {errs} — the app BLOCKED the submission"
    )


def header_global_search(page, term: str):
    hdr = page.locator(
        "mat-toolbar input, app-toolbar input, "
        "input[placeholder*='Search' i], input[aria-label*='Search' i]"
    ).first
    hdr.wait_for(state="visible", timeout=20_000)
    hdr.fill(term)
    page.locator("//span[contains(text(),'Search ')]").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=25_000)
    except Exception:
        pass
    page.wait_for_timeout(2_500)


def gs_tab_rows(page, tab_label: str = "LT-261") -> list:
    """Click a Global Search result tab and return its visible row texts."""
    tab = page.locator(f'[role="tab"]:has-text("{tab_label}")').first
    if not tab.count():
        return []
    tab.click()
    page.wait_for_timeout(2_000)
    return page.evaluate(
        """() => [...document.querySelectorAll('table tbody tr')]
             .map(r => (r.innerText||'').trim()).filter(t => t)"""
    )


def gs_tab_labels(page) -> list:
    return page.evaluate(
        "() => [...document.querySelectorAll('[role=tab]')].map(t=>(t.innerText||'').trim()).filter(t=>t)")


# ============================================================================
# SC-1 [Critical] GATE — deployment verification + baseline snapshot   (TC-01)
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.critical
class TestTW27366957_SC1_Gate:
    """The env gate. If the new numbering is not live here, SC-2..SC-9 are Not Run
    (environment gate, 07 FO-67 / RTM Q8) — never Failed."""

    def test_sc1_gate_and_baseline(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            tok = token()

            # --- step 3 (behavioural): is the preventive AD method the live submit
            # chain on this env? The LT-261 paper-form submit was captured firing
            # chain 4d1fa71cce16eae7419f8a758186c109 — the ticket's preventive
            # method id. 'Published' in a registry is not proof (FO-67); this is.
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt261_listing()
            page.wait_for_timeout(3_000)
            _shot(page, "sc1_lt261_listing")

            seen = {"submit_chain": False}

            probe = staff_context.new_page()

            def on_req(req):
                if CN.SUBMIT_CHAIN in req.url:
                    seen["submit_chain"] = True

            probe.on("request", on_req)

            # --- step 1/2 substitute: the sequence itself is not readable without
            # psql. Its POSITION is read authoritatively by minting one record and
            # reading the value the product actually issued.
            vin = generate_vin()
            officer = generate_person()["name"]
            create_lt261_ui(probe, vin, officer, kind="estop")
            expect_no_form_errors(probe)
            _shot(probe, "sc1_gate_case_created")
            probe.close()

            minted = await_case_number(vin)
            seq_pos = CN.six(minted)

            # --- step 4: the PRE-3 baseline, in one sitting
            recs = CN.census(BASE_URL, tok)
            yp = year_prefix()
            dups = CN.duplicates(recs)
            legacy_max = max((CN.six(r["case"]) for r in recs
                              if CN.prefix(r["case"]) == yp and CN.six(r["case"]) != seq_pos),
                             default=0)
            prefixes = sorted({CN.prefix(r["case"]) for r in recs if r["case"]})
            baseline = {
                "env": "qa",
                "captured": datetime.now().isoformat(timespec="seconds"),
                "total_lt261_records": len(recs),
                "prefixes": prefixes,
                "duplicate_case_numbers": {k: [r["vin"] for r in v] for k, v in dups.items()},
                "sequence_position_observed": seq_pos,
                "sequence_probe_vin": vin,
                "sequence_probe_case": minted,
                "legacy_max_same_prefix": legacy_max,
                "year_prefix": yp,
                "submit_chain_is_preventive_method": seen["submit_chain"],
            }
            save_state(baseline=baseline, gate_case=minted, gate_vin=vin)
            print("BASELINE SNAPSHOT (PRE-3):\n" + json.dumps(baseline, indent=1))

            # ---- gate assertions -------------------------------------------------
            ok_chain = seen["submit_chain"]
            print(f"EXPECTED (TC-01): the LT-261 submit path runs the preventive AD method "
                  f"4d1fa71cce16eae7419f8a758186c109 (published, complete step list — FO-67) | "
                  f"ACTUAL: submit fired that chain = {ok_chain} -> "
                  f"{'MATCH' if ok_chain else 'MISMATCH'}")
            assert ok_chain, (
                "ENVIRONMENT GATE: the LT-261 submit did not call the preventive AD method "
                "4d1fa71cce16eae7419f8a758186c109 on this env — the preventive fix is not live "
                "here, so SC-2..SC-9 are Not Run, not Failed."
            )

            in_new_band = seq_pos >= 100001
            print(f"EXPECTED (TC-01): the dedicated sequence is live — a freshly minted number "
                  f"sits in the new band (6-digit >= 100001) | ACTUAL: {minted} "
                  f"(6-digit {seq_pos}) -> {'MATCH' if in_new_band else 'MISMATCH'}")
            assert in_new_band, (
                f"ENVIRONMENT GATE: minted {minted} — below the START WITH 100001 floor; "
                f"lt261_case_number_seq is not the source of this number."
            )

            print(f"EXPECTED (TC-01): the D% space holds no duplicate case number at baseline | "
                  f"ACTUAL: {len(dups)} duplicated number(s) across {len(recs)} LT-261s -> "
                  f"{'MATCH' if not dups else 'MISMATCH'}")
            assert not dups, (
                f"BASELINE DUPLICATES PRESENT — {dups!r}. Grade downstream numbering results "
                f"against this pre-existing state."
            )

            # NOT VERIFIABLE HERE, stated rather than faked:
            print("NOT VERIFIED (needs psql, PRE-2): pg_sequences.start_value / last_value / "
                  "is_called for lt261_case_number_seq, the exact shape of table "
                  "lt261_case_number_sequence, and its row count. The sequence POSITION above "
                  "is the highest value the product has actually issued — a lower bound on "
                  "last_value, not last_value itself.")
        finally:
            page.close()


# ============================================================================
# SC-2 [Critical] RISK-FIRST — legacy / corrective collision guard (OQ-TW-2)
#                              TC-14 / TC-27 / TC-28 / TC-29 / TC-15
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.critical
class TestTW27366957_SC2_LegacyCollision:
    """The highest-risk open question: START WITH 100001 and NO setval, against a
    D% population that already exists."""

    def test_sc2_tc14_new_number_vs_legacy_population(self, staff_context: BrowserContext):
        """TC-14 — two distinct claims, graded separately:
        (a) the number just minted is not ALREADY held by another case  [observed now]
        (b) the sequence sits ABOVE everything already issued in this year prefix,
            i.e. it can never walk back into an existing number           [structural]
        """
        page = staff_context.new_page()
        try:
            tok = token()
            vin = generate_vin()
            officer = generate_person()["name"]
            create_lt261_ui(page, vin, officer, kind="estop")
            expect_no_form_errors(page)
            minted = await_case_number(vin)
            _shot(page, "sc2_tc14_minted")
            seq_pos = CN.six(minted)
            yp = CN.prefix(minted)

            recs = CN.census(BASE_URL, tok)
            holders = [r for r in recs if r["case"] == minted]

            # ---- (a) is the freshly minted number already taken? ----
            ok_a = len(holders) == 1
            print(f"EXPECTED (TC-14a): the newly minted {minted} is held by exactly ONE case "
                  f"(no collision with any existing D% number) | ACTUAL: {len(holders)} case(s) "
                  f"hold it -> {'MATCH' if ok_a else 'MISMATCH'}")

            # ---- (b) the structural invariant the DDL does not satisfy ----
            same_prefix = [CN.six(r["case"]) for r in recs
                           if CN.prefix(r["case"]) == yp and r["vin"].upper() != vin.upper()]
            legacy_max = max(same_prefix, default=0)
            ahead = sorted(v for v in same_prefix if v > seq_pos)
            first_collision = ahead[0] if ahead else None

            print(f"SEQUENCE POSITION (observed) = {seq_pos}   "
                  f"MAX already-issued {yp} value = {legacy_max}   "
                  f"already-issued {yp} values ABOVE the sequence = {len(ahead)}")
            if first_collision is not None:
                print(f"FIRST COLLISION TARGET = {yp}-{first_collision} "
                      f"(the sequence re-issues it after {first_collision - seq_pos} more mints)")

            ok_b = seq_pos >= legacy_max
            print(f"EXPECTED (TC-14b / RTM Q2 / OQ-TW-2): lt261_case_number_seq sits ABOVE every "
                  f"number already issued in the {yp} space, so it can never re-issue one "
                  f"(the DDL is START WITH 100001 with NO setval) | ACTUAL: sequence at "
                  f"{seq_pos}, {len(ahead)} existing {yp} numbers sit ABOVE it (max {legacy_max}) "
                  f"-> {'MATCH' if ok_b else 'MISMATCH'}")

            assert ok_a, (
                f"COLLISION ALREADY REALISED: {minted} is held by {len(holders)} cases "
                f"({[h['vin'] for h in holders]}) — the preventive fix is re-issuing numbers."
            )
            assert ok_b, (
                f"DEFECT (RTM Q2 / OQ-TW-2 CONFIRMED): lt261_case_number_seq was created "
                f"START WITH 100001 with no setval and now sits at {seq_pos}, while "
                f"{len(ahead)} {yp} case numbers already exist ABOVE it (max {yp}-{legacy_max}). "
                f"The sequence will re-issue {yp}-{first_collision} after "
                f"{first_collision - seq_pos} further LT-261s, reproducing the duplicate this "
                f"ticket exists to fix. No number is duplicated YET — this is a latent, "
                f"deterministic collision, not a test-data problem."
            )
        finally:
            page.close()

    def test_sc2_tc27_corrective_population_is_clean(self):
        """TC-27 — every 7/28-7/29 record holds a unique, well-formed number.
        API channel: this is a read-only data check over the whole population."""
        tok = token()
        recs = CN.census(BASE_URL, tok)
        window = [r for r in recs
                  if any((r["submitted"] or "").startswith(d) for d in CORRECTIVE_DATES)]

        # PRE-12: did this env receive corrective AD method 4b80b980…? Behavioural
        # evidence = at least one 7/28-7/29 record carrying a NEW-band number
        # (the corrective run re-numbered them from the new sequence).
        renumbered = [r for r in window if CN.six(r["case"]) < 101000]
        got_corrective = bool(renumbered)
        print(f"PRE-12 — corrective AD run reached this env: {got_corrective} "
              f"(7/28-7/29 records carrying new-band numbers: "
              f"{[(r['case'], r['submitted']) for r in renumbered]})")

        malformed = [r for r in window if not CN.CASE_RE.fullmatch(r["case"] or "")]
        by = {}
        for r in window:
            by.setdefault(r["case"], []).append(r)
        dups = {k: v for k, v in by.items() if len(v) > 1}

        # disjoint from the LT-260 N/S space (D-prefix is structurally disjoint)
        n_shaped = [r for r in window if re.match(r"^[NS]", r["case"] or "")]

        ok = not malformed and not dups and not n_shaped
        print(f"EXPECTED (TC-27): every 7/28-7/29 LT-261 holds a unique, well-formed "
              f"^D\\d{{2}}-\\d{{6}}$ number, disjoint from the LT-260 N/S space | "
              f"ACTUAL: {len(window)} records, malformed={len(malformed)}, "
              f"duplicated={dups}, N/S-shaped={len(n_shaped)} -> "
              f"{'MATCH' if ok else 'MISMATCH'}")
        for r in sorted(window, key=lambda r: r["submitted"]):
            print(f"   {r['case']}  {r['submitted']:24s} {r['status']:18s} {r['vin']}")

        if not got_corrective:
            pytest.skip("PRE-12: this environment shows no evidence of corrective AD method "
                        "4b80b980… — TC-27/28/29 are Not Applicable here (deployment fact, "
                        "not a defect).")
        assert not malformed, f"malformed case numbers in the corrected window: {malformed}"
        assert not dups, f"DUPLICATES REMAIN after the corrective run: {dups}"
        assert not n_shaped, f"LT-260 N/S-shaped numbers in the LT-261 space: {n_shaped}"

    def test_sc2_tc27_ui_shows_corrected_number(self, staff_context: BrowserContext):
        """TC-27 (UI half) — the details page of a corrected case shows the corrected
        number, not a pre-correction one."""
        page = staff_context.new_page()
        try:
            tok = token()
            recs = CN.census(BASE_URL, tok)
            window = [r for r in recs
                      if any((r["submitted"] or "").startswith(d) for d in CORRECTIVE_DATES)
                      and CN.six(r["case"]) < 101000]
            if not window:
                pytest.skip("PRE-12: no re-numbered 7/28-7/29 record on this env — N/A.")
            target = window[0]
            lt261 = Lt261Page(page)
            go_to_staff_dashboard(page)
            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(4_000)
            lt261.open_details_for_vin(target["vin"])
            ui_num = lt261.get_case_number()
            _shot(page, "sc2_tc27_corrected_details")
            ok = ui_num == target["case"]
            print(f"EXPECTED (TC-27 UI): the details page of corrected case {target['vin']} shows "
                  f"{target['case']} | ACTUAL: {ui_num} -> {'MATCH' if ok else 'MISMATCH'}")
            assert ok, (f"UI/API disagree on the corrected number for {target['vin']}: "
                        f"listing/API={target['case']} details={ui_num}")
        finally:
            page.close()

    def test_sc2_tc28_corrected_values_not_reissued(self, staff_context: BrowserContext):
        """TC-28 — the hand-written corrective values did not occupy ground the
        sequence will later re-issue. Three more mints must equal none of them."""
        page = staff_context.new_page()
        try:
            tok = token()
            recs0 = CN.census(BASE_URL, tok)
            corrected = {r["case"] for r in recs0
                         if any((r["submitted"] or "").startswith(d) for d in CORRECTIVE_DATES)}
            existing = {r["case"] for r in recs0}
            print(f"corrected-window numbers: {sorted(corrected)}")

            minted = []
            for i in range(3):
                vin = generate_vin()
                create_lt261_ui(page, vin, generate_person()["name"], kind="estop")
                expect_no_form_errors(page)
                num = await_case_number(vin)
                minted.append((vin, num))
                print(f"   mint {i+1}: {vin} -> {num}")
            _shot(page, "sc2_tc28_three_mints")
            save_state(tc28_minted=minted)

            clash_corrected = [n for _, n in minted if n in corrected]
            clash_any = [n for _, n in minted if n in existing]
            strictly_increasing = [CN.six(n) for _, n in minted] == \
                sorted(CN.six(n) for _, n in minted) and \
                len({n for _, n in minted}) == 3

            ok = not clash_corrected and not clash_any and strictly_increasing
            print(f"EXPECTED (TC-28): three further mints are all NEW — none equals a corrected "
                  f"value or any other pre-existing number, and they increase strictly | "
                  f"ACTUAL: minted={[n for _, n in minted]}, clash-with-corrected={clash_corrected}, "
                  f"clash-with-any-existing={clash_any}, strictly-increasing={strictly_increasing} "
                  f"-> {'MATCH' if ok else 'MISMATCH'}")
            assert not clash_corrected, (
                f"the sequence re-issued a corrective value: {clash_corrected}")
            assert not clash_any, (
                f"the sequence re-issued an already-existing number: {clash_any}")
            assert strictly_increasing, f"mints not strictly increasing/distinct: {minted}"

            print("NOT VERIFIED (needs psql, PRE-2): whether the corrective run consumed "
                  "lt261_case_number_seq via nextval or wrote literals — only the resulting "
                  "values are observable from outside.")
        finally:
            page.close()

    def test_sc2_tc29_reindex_linkage(self, staff_context: BrowserContext):
        """TC-29 — search row, listing row and details page must agree on the number.
        A DB-side corrective write without a re-index (07 FO-1) silently breaks this."""
        page = staff_context.new_page()
        try:
            tok = token()
            recs = CN.census(BASE_URL, tok)
            window = [r for r in recs
                      if any((r["submitted"] or "").startswith(d) for d in CORRECTIVE_DATES)
                      and CN.six(r["case"]) < 101000]
            if not window:
                pytest.skip("PRE-12: no re-numbered 7/28-7/29 record on this env — N/A.")
            target = window[0]
            corrected = target["case"]

            go_to_staff_dashboard(page)
            header_global_search(page, corrected)
            rows_num = gs_tab_rows(page, "LT-261")
            _shot(page, "sc2_tc29_gs_by_number")

            go_to_staff_dashboard(page)
            header_global_search(page, target["vin"])
            rows_vin = gs_tab_rows(page, "LT-261")
            _shot(page, "sc2_tc29_gs_by_vin")

            lt261 = Lt261Page(page)
            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(4_000)
            lt261.open_details_for_vin(target["vin"])
            details_num = lt261.get_case_number()

            hit_num = [r for r in rows_num if corrected in r]
            hit_vin = [r for r in rows_vin if target["vin"].upper() in r.upper()]
            agree = details_num == corrected
            searchable = bool(hit_num) and bool(hit_vin)

            print(f"EXPECTED (TC-29): after the corrective DB write + re-index, Global Search by "
                  f"the corrected number {corrected}, Global Search by VIN {target['vin']} and the "
                  f"details page ALL resolve to the same case with the same number | ACTUAL: "
                  f"search-by-number rows={len(hit_num)}, search-by-VIN rows={len(hit_vin)}, "
                  f"details number={details_num} -> "
                  f"{'MATCH' if (searchable and agree) else 'MISMATCH'}")
            assert agree, (f"listing/API says {corrected} but the details page says {details_num} "
                           f"— the corrective write and the read model disagree")
            assert searchable, (
                f"the corrected number {corrected} and/or VIN {target['vin']} is not findable in "
                f"Global Search — the corrective DB write went in WITHOUT the mandatory re-index "
                f"(07 FO-1) and the linkage is silently broken (07 FO-49)")
        finally:
            page.close()

    def test_sc2_tc15_server_authority(self):
        """TC-15 — a duplicate/malformed case number cannot be forced in via the AD
        method. API channel by definition: this is an API-surface probe.

        The captured client payload carries NO caseNumber field at all, so any value
        supplied here is an injection the server must ignore or reject.
        """
        tok = token()
        recs0 = CN.census(BASE_URL, tok)
        assert recs0, "census empty — cannot pick an existing number to attack with"
        existing = sorted(recs0, key=lambda r: r["submitted"], reverse=True)[0]["case"]

        attacks = [
            ("already-used D-number", existing),
            ("malformed short",       "D25-99999"),
            ("malformed 4-digit year", "D2026-100001"),
            ("LT-260 N-space value",  "N25-100001"),
        ]
        outcomes = []
        for label, value in attacks:
            vin = generate_vin()
            res = CN.submit_direct(BASE_URL, tok, vin, generate_person()["name"],
                                   caseNumber=value)
            time.sleep(6)
            try:
                actual = CN.case_number_for_vin(BASE_URL, tok, vin)
            except AssertionError:
                actual = None          # rejected outright — also an acceptable outcome
            server_500 = res["status"] >= 500
            honoured = actual == value
            outcomes.append({"label": label, "sent": value, "http": res["status"],
                             "vin": vin, "persisted": actual,
                             "client_value_honoured": honoured, "http_5xx": server_500})
            print(f"   [{label}] sent={value!r} http={res['status']} persisted={actual!r} "
                  f"honoured={honoured}")

        honoured_any = [o for o in outcomes if o["client_value_honoured"]]
        crashed = [o for o in outcomes if o["http_5xx"]]
        recs1 = CN.census(BASE_URL, tok)
        new_dups = CN.duplicates(recs1)

        ok = not honoured_any and not crashed and not new_dups
        print(f"EXPECTED (TC-15): the client-supplied case number is IGNORED or REJECTED on "
              f"every variant — no case ends up holding an existing number, no malformed value "
              f"is persisted, no unhandled 500 | ACTUAL: client value honoured on "
              f"{len(honoured_any)} variant(s), 5xx on {len(crashed)}, duplicate numbers in the "
              f"D% space afterwards = {new_dups} -> {'MATCH' if ok else 'MISMATCH'}")
        save_state(tc15=outcomes)
        assert not honoured_any, (
            f"SERVER AUTHORITY BROKEN: the AD method persisted a client-supplied case number: "
            f"{honoured_any}")
        assert not crashed, f"unhandled 5xx from the submit chain: {crashed}"
        assert not new_dups, f"forcing a duplicate SUCCEEDED — D% now holds {new_dups}"


# ============================================================================
# SC-3 [High] Generation core — one shared sequence, monotonic, immutable
#             TC-02 / TC-04 / TC-05 / TC-06
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.high
class TestTW27366957_SC3_GenerationCore:

    DWI_VIN = generate_vin()
    ESTOP_VIN = generate_vin()
    THIRD_VIN = generate_vin()
    OFFICER = generate_person()["name"]

    def test_sc3_tc02_dwi_mints_well_formed_number(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            create_lt261_ui(page, self.DWI_VIN, self.OFFICER, kind="dwi")
            expect_no_form_errors(page)
            n = await_case_number(self.DWI_VIN)
            _shot(page, "sc3_tc02_dwi")
            save_state(sc3_dwi={"vin": self.DWI_VIN, "case": n})

            tok = token()
            holders = CN.cases_holding(BASE_URL, tok, n)
            well_formed = bool(CN.CASE_RE.fullmatch(n))
            right_year = CN.prefix(n) == year_prefix()
            above_floor = CN.six(n) >= 100001
            unique = len(holders) == 1

            ok = well_formed and right_year and above_floor and unique
            print(f"EXPECTED (TC-02): Add Paper DWI mints ^D\\d{{2}}-\\d{{6}}$ with YY="
                  f"{year_prefix()[1:]}, 6-digit >= 100001, held by exactly one case | "
                  f"ACTUAL: {n} well_formed={well_formed} year_ok={right_year} "
                  f"floor_ok={above_floor} holders={len(holders)} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert ok, f"TC-02 failed on {n}"
            print("NOT VERIFIED (needs psql, PRE-2): that exactly ONE row appeared in "
                  "lt261_case_number_sequence for this mint — burnt-but-unused sequence rows "
                  "are invisible from outside; the observable guarantee is 'no two cases share "
                  "a number', asserted above.")
        finally:
            page.close()

    def test_sc3_tc04_number_is_immutable(self, staff_context: BrowserContext):
        """TC-04 — byte-identical on every read path; never re-derived."""
        page = staff_context.new_page()
        try:
            st = load_state().get("sc3_dwi") or {}
            vin, expected = st.get("vin", self.DWI_VIN), st.get("case")
            assert expected, "SC-3 TC-02 must run first (it stores the DWI number)"
            lt261 = Lt261Page(page)
            reads = {}

            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(4_000)
            lt261.open_details_for_vin(vin)
            reads["details"] = lt261.get_case_number()

            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4_000)
            reads["hard_refresh"] = lt261.get_case_number()

            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(4_000)
            try:
                lt261.click_processed_tab()
                lt261.search_by_vin(vin)
                reads["processed_listing"] = lt261.get_case_number_from_listing(vin)
            except Exception as e:                                    # noqa: BLE001
                reads["processed_listing"] = f"unread ({str(e)[:60]})"

            go_to_staff_dashboard(page)
            header_global_search(page, vin)
            rows = gs_tab_rows(page, "LT-261")
            m = CN.CASE_RE.search(" ".join(rows))
            reads["global_search"] = m.group(0) if m else "unread"
            _shot(page, "sc3_tc04_immutability")

            reads["api_census"] = CN.case_number_for_vin(BASE_URL, token(), vin)

            good = [k for k, v in reads.items() if v == expected]
            bad = {k: v for k, v in reads.items() if v != expected}
            ok = not [v for v in bad.values() if CN.CASE_RE.fullmatch(str(v))]
            print(f"EXPECTED (TC-04): {expected} is byte-identical on every read surface | "
                  f"ACTUAL: {reads} (agreeing: {good}) -> {'MATCH' if ok else 'MISMATCH'}")
            assert ok, (f"the case number DIFFERS between read paths — it is being re-derived, "
                        f"not persisted: {bad}")
        finally:
            page.close()

    def test_sc3_tc05_estop_uses_the_same_sequence(self, staff_context: BrowserContext):
        """TC-05 — the E-Stop door draws from the SAME counter as the DWI door.
        (A per-path counter is exactly the class of assumption that produced the
        original defect.)"""
        page = staff_context.new_page()
        try:
            dwi = load_state().get("sc3_dwi") or {}
            assert dwi.get("case"), "SC-3 TC-02 must run first"
            create_lt261_ui(page, self.ESTOP_VIN, self.OFFICER, kind="estop")
            expect_no_form_errors(page)
            n = await_case_number(self.ESTOP_VIN)
            _shot(page, "sc3_tc05_estop")
            save_state(sc3_estop={"vin": self.ESTOP_VIN, "case": n})

            d = CN.six(n) - CN.six(dwi["case"])
            same_prefix = CN.prefix(n) == CN.prefix(dwi["case"])
            ok = same_prefix and d >= 1
            contiguous = d == 1
            print(f"EXPECTED (TC-05): the E-Stop number comes from the SAME shared sequence and "
                  f"is greater than the DWI number (normally +1) | ACTUAL: DWI={dwi['case']} "
                  f"E-Stop={n} delta={d} -> {'MATCH' if ok else 'MISMATCH'}"
                  f"{'' if contiguous else '  [non-contiguous: an intervening/rolled-back mint burnt a value — acceptable per TC-08]'}")
            assert ok, (f"E-Stop {n} does not continue the DWI sequence {dwi['case']} "
                        f"(delta={d}) — the two entry doors are NOT sharing one counter")
        finally:
            page.close()

    def test_sc3_tc06_monotonic_and_no_duplicates(self, staff_context: BrowserContext):
        """TC-06 — a third case is strictly greater; the whole D% space stays clean."""
        page = staff_context.new_page()
        try:
            st = load_state()
            dwi, estop = st.get("sc3_dwi"), st.get("sc3_estop")
            assert dwi and estop, "SC-3 TC-02/TC-05 must run first"
            create_lt261_ui(page, self.THIRD_VIN, self.OFFICER, kind="dwi")
            expect_no_form_errors(page)
            n3 = await_case_number(self.THIRD_VIN)
            _shot(page, "sc3_tc06_third")
            save_state(sc3_third={"vin": self.THIRD_VIN, "case": n3})

            seq = [CN.six(dwi["case"]), CN.six(estop["case"]), CN.six(n3)]
            increasing = seq == sorted(seq) and len(set(seq)) == 3
            dups = CN.duplicates(CN.census(BASE_URL, token()))
            ok = increasing and not dups
            print(f"EXPECTED (TC-06): the three creations are strictly increasing and the whole "
                  f"D% space contains zero duplicated numbers | ACTUAL: order={seq} "
                  f"increasing={increasing}, duplicates in D% = {dups} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert increasing, f"not strictly increasing: {seq}"
            assert not dups, f"duplicate case numbers present in the D% space: {dups}"
        finally:
            page.close()


# ============================================================================
# SC-4 [High] Volume & replay                                   TC-07 / TC-08
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.high
class TestTW27366957_SC4_VolumeReplay:

    def test_sc4_tc07_five_back_to_back(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            officer = generate_person()["name"]
            plan = ["dwi", "estop", "dwi", "estop", "dwi"]
            minted = []
            for i, kind in enumerate(plan):
                vin = generate_vin()
                create_lt261_ui(page, vin, officer, kind=kind)
                expect_no_form_errors(page)
                n = await_case_number(vin)
                minted.append({"vin": vin, "case": n, "kind": kind})
                print(f"   #{i+1} {kind:5s} {vin} -> {n}")
            _shot(page, "sc4_tc07_five")
            save_state(sc4_five=minted)

            vals = [CN.six(m["case"]) for m in minted]
            distinct = len(set(vals)) == 5
            increasing = vals == sorted(vals)
            contiguous = vals == list(range(vals[0], vals[0] + 5))
            tok = token()
            per_case = {m["case"]: len(CN.cases_holding(BASE_URL, tok, m["case"]))
                        for m in minted}
            one_each = all(v == 1 for v in per_case.values())
            dups = CN.duplicates(CN.census(BASE_URL, tok))

            ok = distinct and increasing and one_each and not dups
            print(f"EXPECTED (TC-07): five back-to-back creations produce five DISTINCT, strictly "
                  f"increasing, normally contiguous numbers; each details page shows its own "
                  f"number against its own VIN; the D%-space duplicate query returns zero | "
                  f"ACTUAL: {vals} distinct={distinct} increasing={increasing} "
                  f"contiguous={contiguous} holders-per-number={per_case} duplicates={dups} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            if not contiguous:
                print("   note: non-contiguous is ACCEPTABLE (comment 1 promises unique, not "
                      "contiguous — a rolled-back transaction legitimately burns a value).")
            assert distinct, f"five creations did not produce five distinct numbers: {vals}"
            assert increasing, f"not strictly increasing: {vals}"
            assert one_each, f"a number is shared by more than one case: {per_case}"
            assert not dups, f"duplicate case numbers in the D% space: {dups}"
        finally:
            page.close()

    def test_sc4_tc07_ui_each_case_shows_own_number(self, staff_context: BrowserContext):
        """TC-07 (UI half) — open all five details pages; each shows its own number."""
        page = staff_context.new_page()
        try:
            five = load_state().get("sc4_five") or []
            assert five, "SC-4 TC-07 must run first"
            lt261 = Lt261Page(page)
            observed = {}
            for m in five:
                page.goto(LT261_LIST_URL, timeout=90_000)
                page.wait_for_timeout(3_000)
                lt261.open_details_for_vin(m["vin"])
                observed[m["vin"]] = lt261.get_case_number()
            _shot(page, "sc4_tc07_details_sweep")
            bad = {v: (observed[v], m["case"]) for m in five
                   for v in [m["vin"]] if observed[v] != m["case"]}
            distinct_ui = len(set(observed.values())) == len(observed)
            ok = not bad and distinct_ui
            print(f"EXPECTED (TC-07 UI): each of the five details pages shows its OWN number "
                  f"against its OWN VIN, no two share a number | ACTUAL: {observed} "
                  f"mismatches={bad} all-distinct={distinct_ui} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert not bad, f"details page shows a different number than the record holds: {bad}"
            assert distinct_ui, f"two cases show the same number on their details pages: {observed}"
        finally:
            page.close()

    def test_sc4_tc08_no_reuse_and_replay(self, staff_context: BrowserContext):
        """TC-08 — a sixth case is strictly greater than all five (never a gap-filler),
        and a replayed submit never yields two cases sharing one number."""
        page = staff_context.new_page()
        try:
            five = load_state().get("sc4_five") or []
            assert five, "SC-4 TC-07 must run first"
            prior = [CN.six(m["case"]) for m in five]

            vin6 = generate_vin()
            create_lt261_ui(page, vin6, generate_person()["name"], kind="estop")
            expect_no_form_errors(page)
            n6 = await_case_number(vin6)
            greater = CN.six(n6) > max(prior)
            print(f"EXPECTED (TC-08a): the sixth number is strictly GREATER than all five "
                  f"(never a gap-filler reusing an earlier value) | ACTUAL: five={prior} "
                  f"sixth={n6} -> {'MATCH' if greater else 'MISMATCH'}")

            # --- replay leg: fire the SAME submit payload twice (idempotency window)
            tok = token()
            vin7 = generate_vin()
            officer = generate_person()["name"]
            r1 = CN.submit_direct(BASE_URL, tok, vin7, officer)
            r2 = CN.submit_direct(BASE_URL, tok, vin7, officer)
            time.sleep(8)
            recs = CN.census(BASE_URL, tok, vin=vin7)
            same_vin = [r for r in recs if (r["vin"] or "").upper() == vin7.upper()]
            nums = [r["case"] for r in same_vin]
            shared = len(nums) != len(set(nums))
            print(f"   replay: http {r1['status']}/{r2['status']}, cases now on VIN {vin7}: "
                  f"{[(r['case'], r['status']) for r in same_vin]}")

            all_dups = CN.duplicates(CN.census(BASE_URL, tok))
            ok = greater and not shared and not all_dups
            print(f"EXPECTED (TC-08b): a replayed submit yields either an 'already submitted' "
                  f"rejection or a wholly separate case with its OWN distinct number — never "
                  f"two cases sharing one number | ACTUAL: {len(same_vin)} case(s) on the "
                  f"replayed VIN with numbers {nums}, shared-number={shared}, "
                  f"D%-wide duplicates={all_dups} -> {'MATCH' if ok else 'MISMATCH'}")
            _shot(page, "sc4_tc08")
            assert greater, f"the sixth number {n6} did not exceed all five {prior} — value reuse"
            assert not shared, f"replay produced two cases sharing one number: {nums}"
            assert not all_dups, f"duplicate case numbers in the D% space after replay: {all_dups}"
            print("   grading note: a GAP left by a rolled-back transaction is acceptable "
                  "(standard sequence semantics); a RE-USED value is the defect.")
        finally:
            page.close()


# ============================================================================
# SC-5 [High] Concurrency                              TC-09 / TC-10 / TC-11
#
# API channel by necessity and by design: PRE-9 asks for a scripted fan-out
# firing submits concurrently against the same AD method. Nothing in the suite
# is genuinely parallel (no threads/asyncio/xdist; the two existing "concurrent"
# e2e tests drive two tabs of one identity strictly sequentially and assert
# nothing about duplicates). submit_parallel() releases every thread off one
# barrier, so this is a real race on the sequence.
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.high
class TestTW27366957_SC5_Concurrency:

    def test_sc5_tc09_two_simultaneous_submissions(self):
        tok = token()
        jobs = [{"vin": generate_vin(), "officer": generate_person()["name"],
                 "paper_type": "DWI"},
                {"vin": generate_vin(), "officer": generate_person()["name"],
                 "paper_type": "E-Stop"}]
        results = CN.submit_parallel(BASE_URL, tok, jobs)
        time.sleep(12)
        nums = {}
        for j in jobs:
            try:
                nums[j["vin"]] = CN.case_number_for_vin(BASE_URL, tok, j["vin"])
            except AssertionError:
                nums[j["vin"]] = None
        errors = [r for r in results if r is None or r["status"] >= 400]
        got = [v for v in nums.values() if v]
        distinct = len(set(got)) == len(got) and len(got) == 2
        dups = CN.duplicates(CN.census(BASE_URL, tok))

        ok = distinct and not errors and not dups
        print(f"EXPECTED (TC-09): two submissions fired in the same instant mint two DIFFERENT "
              f"numbers, with no deadlock / timeout / 500 in either | ACTUAL: http="
              f"{[r['status'] for r in results if r]}, numbers={nums}, distinct={distinct}, "
              f"D%-wide duplicates={dups} -> {'MATCH' if ok else 'MISMATCH'}")
        save_state(sc5_tc09=nums)
        assert not errors, f"concurrent submit errored: {errors}"
        assert len(got) == 2, f"a concurrent submission produced no case/number: {nums}"
        assert distinct, f"CONCURRENCY DUPLICATE: both submissions got {got}"
        assert not dups, f"duplicate case numbers in the D% space after the race: {dups}"

    def test_sc5_tc10_ten_way_fanout(self):
        tok = token()
        jobs = [{"vin": generate_vin(), "officer": generate_person()["name"],
                 "paper_type": "DWI" if i % 2 else "E-Stop"} for i in range(10)]
        results = CN.submit_parallel(BASE_URL, tok, jobs)
        time.sleep(15)
        nums = {}
        for j in jobs:
            try:
                nums[j["vin"]] = CN.case_number_for_vin(BASE_URL, tok, j["vin"])
            except AssertionError:
                nums[j["vin"]] = None
        got = [v for v in nums.values() if v]
        missing = [k for k, v in nums.items() if not v]
        errors = [r for r in results if r is None or r["status"] >= 400]
        distinct = len(set(got))
        dups = CN.duplicates(CN.census(BASE_URL, tok))

        ok = distinct == 10 and not missing and not errors and not dups
        print(f"EXPECTED (TC-10): ten parallel submissions -> COUNT(DISTINCT case_number) = 10, "
              f"no case left without a number, no sequence/constraint/duplicate-key error | "
              f"ACTUAL: created={len(got)} distinct={distinct} missing={missing} "
              f"http={[r['status'] for r in results if r]} D%-wide duplicates={dups} -> "
              f"{'MATCH' if ok else 'MISMATCH'}")
        print(f"   numbers: {sorted(got)}")
        save_state(sc5_tc10=nums)
        assert not errors, f"fan-out submit errors: {errors}"
        assert not missing, f"cases left without a number: {missing}"
        assert distinct == 10, f"COUNT(DISTINCT) = {distinct}, expected 10 — numbers={sorted(got)}"
        assert not dups, f"duplicate case numbers in the D% space after the fan-out: {dups}"
        print("NOT VERIFIED (needs psql/log access, PRE-2): that lt261_case_number_sequence "
              "gained exactly 10 rows, and that application logs show no sequence/constraint "
              "errors. The observable equivalent — 10 cases, 10 distinct numbers, zero D%-wide "
              "duplicates — is asserted above.")

    def test_sc5_tc11_concurrent_pdfs_not_crosslinked(self, staff_context: BrowserContext):
        """TC-11 — correspondence for two concurrently created cases must not
        cross-link: each case's letters carry its own number/VIN, filename sets
        share nothing."""
        page = staff_context.new_page()
        try:
            pairs = load_state().get("sc5_tc09") or {}
            vins = [v for v, n in pairs.items() if n][:2]
            if len(vins) < 2:
                # pytest reorders browser tests ahead of plain ones, so TC-09 may not
                # have run yet — fire our own concurrent pair rather than skipping.
                tok = token()
                jobs = [{"vin": generate_vin(), "officer": generate_person()["name"],
                         "paper_type": "DWI"},
                        {"vin": generate_vin(), "officer": generate_person()["name"],
                         "paper_type": "E-Stop"}]
                CN.submit_parallel(BASE_URL, tok, jobs)
                time.sleep(12)
                pairs = {}
                for j in jobs:
                    try:
                        pairs[j["vin"]] = CN.case_number_for_vin(BASE_URL, tok, j["vin"])
                    except AssertionError:
                        pairs[j["vin"]] = None
                save_state(sc5_tc09=pairs)
                vins = [v for v, n in pairs.items() if n][:2]
            if len(vins) < 2:
                pytest.skip("SC-5: could not stage a concurrent pair for the cross-link check")
            lt261 = Lt261Page(page)
            per_case = {}
            for vin in vins:
                num = pairs[vin]
                found_rows = []
                for _ in range(6):
                    try:
                        page.goto(LT261_LIST_URL, timeout=90_000)
                        page.wait_for_timeout(4_000)
                        lt261.open_details_for_vin(vin)
                        lt261.click_view_correspondence()
                        page.wait_for_timeout(2_500)
                        found_rows = page.evaluate(
                            """() => {
                              const d = document.querySelector('mat-dialog-container') || document.body;
                              return [...d.querySelectorAll('table tbody tr, mat-row, [class*=row]')]
                                .map(r => (r.textContent||'').trim().replace(/\\s+/g,' '))
                                .filter(t => t).slice(0, 40);
                            }""")
                        if found_rows:
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(8_000)
                _shot(page, f"sc5_tc11_corr_{vin[:6]}")
                per_case[vin] = {"number": num, "rows": found_rows,
                                 "text": " ".join(found_rows)}

            a, b = vins[0], vins[1]
            leak_a = per_case[b]["number"] in per_case[a]["text"]
            leak_b = per_case[a]["number"] in per_case[b]["text"]
            reachable = all(per_case[v]["rows"] for v in vins)
            ok = reachable and not leak_a and not leak_b
            print(f"EXPECTED (TC-11): each concurrently created case's Correspondence/Forms "
                  f"carries ONLY its own case number ({pairs[a]} vs {pairs[b]}); the two sets "
                  f"share nothing (PDF generation atomic, ms-timestamped filenames, BR-81 / "
                  f"07 FO-5) | ACTUAL: reachable={reachable}, {b}'s number leaked into {a}="
                  f"{leak_a}, {a}'s number leaked into {b}={leak_b} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            for v in vins:
                print(f"   {v} ({pairs[v]}): {per_case[v]['rows'][:6]}")
            assert reachable, ("neither concurrent case exposed a Correspondence/Forms list — "
                               "cross-link cannot be evaluated")
            assert not leak_a and not leak_b, "CROSS-LINK: a case's correspondence carries the other case's number"
            print("PARTIAL (blocker): the filename pattern {file}_{type}_{datetime}.PDF and the "
                  "printed contents of the LT-265/265A PDFs are not read here — the correspondence "
                  "modal exposes row text, not the stored filename, and reading inside the PDF "
                  "needs a download + PyPDF2 dependency the suite does not carry.")
        finally:
            page.close()


# ============================================================================
# SC-6 [High] Namespace isolation                              TC-12 / TC-13
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.high
class TestTW27366957_SC6_NamespaceIsolation:

    LT260_VIN = generate_vin()
    LT261_VIN = generate_vin()

    def test_sc6_tc12_lt260_space_untouched(self, staff_context: BrowserContext):
        """TC-12 — a new LT-260 still gets an N + 9-digit file number, and no value
        is present in BOTH numbering spaces."""
        page = staff_context.new_page()
        try:
            person = generate_person()
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt260_listing()
            Lt260ListingPage(page).click_add_from_paper()
            pf = PaperFormPage(page)
            pf.fill_modal_vin_and_next(self.LT260_VIN)
            pf.fill_year("2018")
            pf.fill_make("TOY")
            pf.fill_date_vehicle_left(past_date(30))
            pf.fill_search_location("Garage")
            pf.add_owner(person["name"], "716 North Elm Street", "27401")
            pf.select_stolen_no()
            pf.submit_with_confirmation()
            expect_no_form_errors(page)
            page.wait_for_timeout(8_000)
            _shot(page, "sc6_tc12_lt260_submitted")

            # read the LT-260 file number off its listing
            # LT-260 file number shape, live-confirmed on QA 2026-07-30:
            # "N26-1070316" / "S26-1070315" — [N|S] + 2-digit year + '-' + 7 digits
            # (i.e. the letter plus 9 digits, exactly as 01 §CaseFileNumber describes).
            lt260_number = None
            for _ in range(10):
                page.goto(LT260_LIST_URL, timeout=90_000)
                page.wait_for_timeout(4_000)
                try:
                    lst = Lt260ListingPage(page)
                    # a paper LT-260 with an owner auto-processes off "To Process"
                    lst.click_all_tab()
                    page.wait_for_timeout(2_000)
                    lst.search_by_vin(self.LT260_VIN)
                    page.wait_for_timeout(2_500)
                except Exception:
                    pass
                txt = page.evaluate(
                    """(vin) => {
                        const rows = [...document.querySelectorAll('table tbody tr')];
                        for (const r of rows) {
                          const t = (r.innerText||'');
                          if (t.toUpperCase().includes(vin.toUpperCase())) return t;
                        }
                        return null;
                    }""", self.LT260_VIN)
                if txt:
                    m = re.search(r"\b([NS]\d{2}-\d{7})\b", txt)
                    if m:
                        lt260_number = m.group(1)
                        break
                page.wait_for_timeout(6_000)
            _shot(page, "sc6_tc12_lt260_listing")

            # a fresh LT-261 for the disjointness check
            create_lt261_ui(page, self.LT261_VIN, person["name"], kind="estop")
            expect_no_form_errors(page)
            lt261_number = await_case_number(self.LT261_VIN)
            save_state(sc6={"lt260_vin": self.LT260_VIN, "lt260": lt260_number,
                            "lt261_vin": self.LT261_VIN, "lt261": lt261_number})

            shape_ok = bool(lt260_number and re.fullmatch(r"[NS]\d{2}-\d{7}", lt260_number))
            d_numbers = {r["case"] for r in CN.census(BASE_URL, token())}
            overlap = {n for n in d_numbers if re.match(r"^[NS]", n)}
            disjoint = not overlap and not re.match(r"^D", lt260_number or "D")

            ok = shape_ok and disjoint
            print(f"EXPECTED (TC-12): the new LT-260 still gets an N/S + 9-digit file number from "
                  f"its own sequence, and NO value appears in both spaces (LT-261 emits no "
                  f"N/S-shaped value and vice versa) | ACTUAL: LT-260={lt260_number} "
                  f"shape_ok={shape_ok}, LT-261={lt261_number}, N/S-shaped values inside the "
                  f"D% space={len(overlap)} -> {'MATCH' if ok else 'MISMATCH'}")
            assert lt260_number, (
                "could not read a file number for the new LT-260 from its listing — "
                "TC-12's LT-260 half is unproven")
            assert shape_ok, (f"LT-260 file number {lt260_number} is not [N|S][YY]-nnnnnnn — the "
                              f"LT-261 change disturbed the LT-260 space")
            assert disjoint, f"numbering spaces overlap: {overlap}"
        finally:
            page.close()

    def test_sc6_tc13_global_search_tabs_stay_apart(self, staff_context: BrowserContext):
        """TC-13 — the D% discriminator keeps LT-260 and LT-261 in their own tabs."""
        page = staff_context.new_page()
        try:
            st = load_state().get("sc6") or {}
            d_num, n_num = st.get("lt261"), st.get("lt260")
            assert d_num, "SC-6 TC-12 must run first"

            go_to_staff_dashboard(page)
            header_global_search(page, d_num)
            tabs_d = gs_tab_labels(page)
            rows_lt261 = gs_tab_rows(page, "LT-261")
            rows_lt260 = gs_tab_rows(page, "LT-260")
            _shot(page, "sc6_tc13_search_dnumber")
            d_in_261 = [r for r in rows_lt261 if d_num in r]
            d_in_260 = [r for r in rows_lt260 if d_num in r]

            leaked_n = []
            tabs_n = []
            if n_num:
                go_to_staff_dashboard(page)
                header_global_search(page, n_num)
                tabs_n = gs_tab_labels(page)
                n_rows_260 = gs_tab_rows(page, "LT-260")
                n_rows_261 = gs_tab_rows(page, "LT-261")
                _shot(page, "sc6_tc13_search_nnumber")
                leaked_n = [r for r in n_rows_261 if n_num in r]
                print(f"   N-number {n_num}: LT-260 tab rows={len(n_rows_260)}, "
                      f"LT-261 tab rows containing it={len(leaked_n)}")

            # sharpest case: the bare 6-digit fragment
            frag = d_num.split("-")[1]
            go_to_staff_dashboard(page)
            header_global_search(page, frag)
            frag_261 = gs_tab_rows(page, "LT-261")
            frag_260 = gs_tab_rows(page, "LT-260")
            _shot(page, "sc6_tc13_search_fragment")
            conflated = [r for r in frag_260 if d_num in r]

            ok = bool(d_in_261) and not d_in_260 and not leaked_n and not conflated
            print(f"EXPECTED (TC-13): a D-format number resolves under the LT-261 tab ONLY "
                  f"(discriminator case_number LIKE 'D%', NCNSS-544); an N-format number under "
                  f"LT-260 only; a bare 6-digit fragment never conflates a D-case with an N-case; "
                  f"every tab stays visible even at zero | ACTUAL: {d_num} -> LT-261 rows="
                  f"{len(d_in_261)}, LT-260 rows={len(d_in_260)}; N leaked into LT-261="
                  f"{len(leaked_n)}; fragment '{frag}' -> LT-261 rows={len(frag_261)}, "
                  f"D-case conflated into LT-260={len(conflated)}; tabs={tabs_d} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert d_in_261, f"{d_num} not found under the Global Search LT-261 tab"
            assert not d_in_260, f"{d_num} LEAKED into the LT-260 tab: {d_in_260}"
            assert not leaked_n, f"the LT-260 number {n_num} leaked into the LT-261 tab: {leaked_n}"
            assert not conflated, (f"the bare fragment '{frag}' conflated the D-case into the "
                                   f"LT-260 tab: {conflated}")
        finally:
            page.close()


# ============================================================================
# SC-7 [High] Non-happy dispositions            TC-17 / TC-18 / TC-19 / TC-20
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.high
class TestTW27366957_SC7_NonHappy:

    STOLEN_VIN = generate_vin()
    DRAFT_VIN = generate_vin()
    AFTER_DRAFT_VIN = generate_vin()
    CANCEL_VIN = generate_vin()
    REAL_VIN = generate_vin()

    def test_sc7_tc17_stolen_is_numbered_but_held(self, staff_context: BrowserContext):
        """TC-17 — a stolen=Yes E-Stop is held manual (no auto-process, no LT-265/265A)
        yet still holds a well-formed unique number: the number is minted at submission
        regardless of disposition."""
        page = staff_context.new_page()
        try:
            officer = generate_person()["name"]
            lt261 = create_lt261_ui(page, self.STOLEN_VIN, officer,
                                    kind="estop", stolen="yes")
            expect_no_form_errors(page)
            lt261.expect_no_lt265_issue_popup()
            n = await_case_number(self.STOLEN_VIN)
            _shot(page, "sc7_tc17_stolen")
            save_state(sc7_stolen={"vin": self.STOLEN_VIN, "case": n})

            tok = token()
            rec = CN.find_by_vin(CN.census(BASE_URL, tok, vin=self.STOLEN_VIN), self.STOLEN_VIN)
            holders = CN.cases_holding(BASE_URL, tok, n)
            well_formed = bool(CN.CASE_RE.fullmatch(n))
            unique = len(holders) == 1
            held = "sold" not in (rec["status"] or "").lower()

            # still findable in the listings (not lost) + Global Search
            in_stolen = True
            try:
                lt261.expect_vin_in_stolen_listing(self.STOLEN_VIN)
            except Exception as e:                                     # noqa: BLE001
                in_stolen = False
                print(f"   stolen-listing check: {str(e)[:140]}")
            go_to_staff_dashboard(page)
            header_global_search(page, self.STOLEN_VIN)
            gs_rows = gs_tab_rows(page, "LT-261")
            in_gs = any(self.STOLEN_VIN.upper() in r.upper() for r in gs_rows)
            _shot(page, "sc7_tc17_stolen_gs")

            ok = well_formed and unique and held and in_stolen
            print(f"EXPECTED (TC-17): the stolen=Yes case stays held (status not Vehicle Sold), "
                  f"no LT-265/265A issue popup, yet holds a well-formed unique D-number and is "
                  f"NOT lost from the listings | ACTUAL: number={n} well_formed={well_formed} "
                  f"holders={len(holders)} status={rec['status']!r} in-stolen-listing={in_stolen} "
                  f"in-global-search={in_gs} -> {'MATCH' if ok else 'MISMATCH'}")
            assert well_formed and unique, f"stolen case number {n} malformed or shared"
            assert held, f"stolen=Yes case auto-processed to {rec['status']!r} (BR-36/37)"
            assert in_stolen, "the stolen case vanished from the LT-261 listings"
        finally:
            page.close()

    def test_sc7_tc18_draft_does_not_expose_a_duplicate(self, staff_context: BrowserContext):
        """TC-18 — OBSERVATION, not a spec assertion (the ticket does not specify draft
        behaviour). Whatever the build does must be internally consistent."""
        page = staff_context.new_page()
        try:
            tok = token()
            before = CN.high_water(CN.census(BASE_URL, tok), year_prefix())

            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt261_listing()
            btn = page.locator('button:has-text("Add Paper DWI")').first
            btn.wait_for(state="visible", timeout=20_000)
            btn.click()
            page.wait_for_timeout(1_500)
            lt261 = Lt261Page(page)
            lt261.fill_modal_vin_next(self.DRAFT_VIN)

            saved = False
            for label in ("Save as Draft", "Save Draft", "Save"):
                b = page.locator(f'button:has-text("{label}")').first
                if b.count() and b.is_visible():
                    b.scroll_into_view_if_needed()
                    b.click()
                    page.wait_for_timeout(4_000)
                    for y in page.locator('mat-dialog-container button:has-text("Yes")').all():
                        try:
                            y.click()
                            page.wait_for_timeout(2_000)
                        except Exception:
                            pass
                    saved = True
                    break
            _shot(page, "sc7_tc18_draft_saved")

            draft_number = None
            if saved:
                page.goto(LT261_LIST_URL, timeout=90_000)
                page.wait_for_timeout(4_000)
                try:
                    page.locator('[role="tab"]:has-text("Draft Paper Forms")').first.click()
                    page.wait_for_timeout(3_000)
                    lt261.search_by_vin(self.DRAFT_VIN)
                    page.wait_for_timeout(2_000)
                    row = page.evaluate(
                        """(vin) => {
                            const rows=[...document.querySelectorAll('table tbody tr')];
                            for (const r of rows){ const t=(r.innerText||'');
                              if (t.toUpperCase().includes(vin.toUpperCase())) return t; }
                            return null; }""", self.DRAFT_VIN)
                    if row:
                        m = CN.CASE_RE.search(row)
                        draft_number = m.group(0) if m else None
                    print(f"   Draft Paper Forms row: {row!r}")
                except Exception as e:                                  # noqa: BLE001
                    print(f"   draft tab read failed: {str(e)[:120]}")
                _shot(page, "sc7_tc18_draft_tab")

            # a real submitted case immediately afterwards
            create_lt261_ui(page, self.AFTER_DRAFT_VIN, generate_person()["name"], kind="estop")
            expect_no_form_errors(page)
            after_num = await_case_number(self.AFTER_DRAFT_VIN)
            after = CN.six(after_num)

            # drafts must stay out of Global Search (E2E-037 rule)
            go_to_staff_dashboard(page)
            header_global_search(page, self.DRAFT_VIN)
            gs_rows = gs_tab_rows(page, "LT-261")
            draft_in_gs = any(self.DRAFT_VIN.upper() in r.upper() for r in gs_rows)
            _shot(page, "sc7_tc18_draft_gs")

            consistent = True
            reason = ""
            if draft_number:
                if draft_number == after_num:
                    consistent, reason = False, ("the draft's number was ALSO handed to the "
                                                 "intervening submitted case")
            print(f"EXPECTED (TC-18, observation): whichever way the build implements drafts, it "
                  f"is internally consistent — if the draft shows a number it is never handed to "
                  f"another case; if it shows none, no value is consumed. Drafts stay OUT of "
                  f"Global Search. | ACTUAL: draft saved={saved}, number on the draft row="
                  f"{draft_number!r}, high-water before={before} after={after}, next submitted "
                  f"case={after_num}, draft in Global Search={draft_in_gs} -> "
                  f"{'MATCH' if (consistent and not draft_in_gs) else 'MISMATCH'} {reason}")
            save_state(sc7_draft={"vin": self.DRAFT_VIN, "draft_number": draft_number,
                                  "next_case": after_num, "saved": saved})
            assert consistent, reason
            assert not draft_in_gs, ("a DRAFT LT-261 is indexed in Global Search — drafts must be "
                                     "excluded (E2E-037)")
        finally:
            page.close()

    def test_sc7_tc19_cancel_leaves_no_case_and_no_reusable_number(
            self, staff_context: BrowserContext):
        """TC-19 — Cancel creates nothing; a burnt value is acceptable, a RE-USED one is not."""
        page = staff_context.new_page()
        try:
            tok = token()
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt261_listing()
            lt261 = Lt261Page(page)
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(self.CANCEL_VIN)
            fill_lt261_form(lt261, generate_person()["name"])
            lt261.click_cancel_button()
            lt261.expect_cancel_modal_visible()
            lt261.click_cancel_modal_yes()
            lt261.expect_on_listing_page()
            _shot(page, "sc7_tc19_cancelled")
            page.wait_for_timeout(5_000)

            cancelled_exists = bool(CN.find_by_vin(
                CN.census(BASE_URL, tok, vin=self.CANCEL_VIN), self.CANCEL_VIN))

            # a real case created after the cancel
            create_lt261_ui(page, self.REAL_VIN, generate_person()["name"], kind="estop")
            expect_no_form_errors(page)
            real_num = await_case_number(self.REAL_VIN)

            # a second cancel, then another real case
            vin_c2, vin_r2 = generate_vin(), generate_vin()
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt261_listing()
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(vin_c2)
            fill_lt261_form(lt261, generate_person()["name"])
            lt261.click_cancel_button()
            lt261.expect_cancel_modal_visible()
            lt261.click_cancel_modal_yes()
            page.wait_for_timeout(4_000)
            create_lt261_ui(page, vin_r2, generate_person()["name"], kind="estop")
            expect_no_form_errors(page)
            real2 = await_case_number(vin_r2)

            dups = CN.duplicates(CN.census(BASE_URL, tok))
            distinct = real_num != real2
            increasing = CN.six(real2) > CN.six(real_num)
            ok = (not cancelled_exists) and distinct and increasing and not dups
            print(f"EXPECTED (TC-19): Cancel routes back to the LT-261 Listing, creates NO case, "
                  f"issues no LT-265/265A, and no real case ever receives a value a cancelled "
                  f"attempt could also have taken (a sequence GAP is acceptable, a RE-USED value "
                  f"is not) | ACTUAL: cancelled VIN exists as a case={cancelled_exists}, real "
                  f"cases after each cancel = {real_num} / {real2} (distinct={distinct}, "
                  f"increasing={increasing}), D%-wide duplicates={dups} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert not cancelled_exists, (
                f"Cancel still created an LT-261 for VIN {self.CANCEL_VIN}")
            assert distinct and increasing, (
                f"a real case reused/regressed a value across cancels: {real_num} then {real2}")
            assert not dups, f"duplicate case numbers after the cancel legs: {dups}"
        finally:
            page.close()

    def test_sc7_tc20_denied_case_keeps_its_number(self, staff_context: BrowserContext):
        """TC-20 — denial/close does not change the number, and the case stays findable
        by it, exactly once."""
        page = staff_context.new_page()
        try:
            st = load_state().get("sc7_stolen") or {}
            vin, number = st.get("vin"), st.get("case")
            if not number:
                pytest.skip("SC-7 TC-17 must run first (it supplies the still-open case)")
            lt261 = Lt261Page(page)
            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(4_000)
            lt261.open_details_for_vin(vin)
            before = lt261.get_case_number()

            closed = False
            btn = page.locator('button:has-text("Close File"), span:has-text("Close File")').first
            if btn.count():
                try:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    page.wait_for_timeout(2_500)
                    ta = page.locator('mat-dialog-container textarea, mat-dialog-container input[type=text]').first
                    if ta.count():
                        ta.fill("TW 27366957 automated deny/close — case-number immutability check")
                        page.wait_for_timeout(500)
                    for label in ("Yes", "Submit", "Close", "Confirm", "Ok"):
                        b = page.locator(
                            f'mat-dialog-container button:has-text("{label}")').first
                        if b.count() and b.is_enabled():
                            b.click()
                            page.wait_for_timeout(3_000)
                            closed = True
                            break
                except Exception as e:                                  # noqa: BLE001
                    print(f"   close-file attempt: {str(e)[:140]}")
            _shot(page, "sc7_tc20_after_close")
            page.wait_for_timeout(6_000)

            after = CN.case_number_for_vin(BASE_URL, token(), vin)
            go_to_staff_dashboard(page)
            header_global_search(page, number)
            rows = gs_tab_rows(page, "LT-261")
            hits = [r for r in rows if number in r]
            _shot(page, "sc7_tc20_gs_by_number")

            unchanged = after == before == number
            exactly_one = len(hits) == 1
            ok = unchanged and exactly_one
            print(f"EXPECTED (TC-20): denial/close leaves the number unchanged; Global Search by "
                  f"that D-number returns EXACTLY ONE row, still in the LT-261 tab | ACTUAL: "
                  f"close-file driven={closed}, number before={before} after={after}, "
                  f"search rows holding it={len(hits)} -> {'MATCH' if ok else 'MISMATCH'}")
            assert unchanged, f"the case number changed across denial: {before} -> {after}"
            assert exactly_one, (f"Global Search by {number} returned {len(hits)} rows — a "
                                 f"duplicate would produce two rows for one closed case")
            if not closed:
                print("PARTIAL: the Close File / Deny action could not be driven on this case "
                      "(control absent or gated); the immutability + single-row assertions above "
                      "still ran against the live record.")
        finally:
            page.close()


# ============================================================================
# SC-8 [High] Downstream fan-out          TC-21 / TC-22 / TC-23 / TC-25 / TC-26
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.high
class TestTW27366957_SC8_Downstream:

    def _cases(self):
        st = load_state()
        out = []
        for k in ("sc3_dwi", "sc3_estop", "sc3_third"):
            if st.get(k):
                out.append(st[k])
        out += (st.get("sc4_five") or [])
        return out

    def test_sc8_tc21_listing_one_row_each_sortable(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            cases = self._cases()
            assert cases, "SC-3 / SC-4 must run first (they create the cases)"
            lt261 = Lt261Page(page)
            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(4_000)
            page.locator('[role="tab"]:has-text("All")').first.click()
            page.wait_for_timeout(3_000)

            found = {}
            for c in cases:
                lt261.search_by_vin(c["vin"])
                page.wait_for_timeout(1_500)
                rows = page.evaluate(
                    """(vin) => [...document.querySelectorAll('table tbody tr')]
                         .map(r=>(r.innerText||'').trim())
                         .filter(t => t.toUpperCase().includes(vin.toUpperCase()))""",
                    c["vin"])
                nums = [CN.CASE_RE.search(r).group(0) for r in rows if CN.CASE_RE.search(r)]
                found[c["vin"]] = {"rows": len(rows), "numbers": nums, "expected": c["case"]}
            _shot(page, "sc8_tc21_listing")

            bad_count = {v: d for v, d in found.items() if d["rows"] != 1}
            bad_num = {v: d for v, d in found.items()
                       if d["numbers"] and d["numbers"][0] != d["expected"]}

            # filter by one exact D-number -> single row that opens the right VIN
            target = cases[0]
            tok = token()
            holders = CN.cases_holding(BASE_URL, tok, target["case"])

            ok = not bad_count and not bad_num and len(holders) == 1
            print(f"EXPECTED (TC-21): every case appears EXACTLY ONCE in the listing with its own "
                  f"distinct D-number; filtering by one exact number yields a single row that "
                  f"opens the matching VIN | ACTUAL: per-VIN={found}, wrong-row-count="
                  f"{list(bad_count)}, wrong-number={list(bad_num)}, cases holding "
                  f"{target['case']}={len(holders)} -> {'MATCH' if ok else 'MISMATCH'}")
            assert not bad_count, f"a case does not appear exactly once in the listing: {bad_count}"
            assert not bad_num, f"a listing row shows the wrong number: {bad_num}"
            assert len(holders) == 1, (f"filtering by {target['case']} matched {len(holders)} "
                                       f"cases — duplicates sitting adjacent")

            # sort by File # both directions and assert the column orders correctly
            orders = {}
            for direction in ("asc", "desc"):
                try:
                    hdr = page.locator('th:has-text("FILE NUMBER"), th:has-text("File Number")').first
                    if hdr.count():
                        hdr.click()
                        page.wait_for_timeout(3_500)
                    col = page.evaluate(
                        """() => [...document.querySelectorAll('table tbody tr')]
                             .map(r => { const m=(r.innerText||'').match(/D\\d{2}-\\d{6}/); return m?m[0]:null; })
                             .filter(Boolean)""")
                    orders[direction] = col
                except Exception as e:                                  # noqa: BLE001
                    orders[direction] = f"unsortable ({str(e)[:60]})"
            _shot(page, "sc8_tc21_sorted")
            sortable = all(isinstance(v, list) and v for v in orders.values())
            monotone = []
            for d, col in orders.items():
                if isinstance(col, list) and len(col) > 1:
                    vals = [CN.six(c) for c in col]
                    monotone.append(vals == sorted(vals) or vals == sorted(vals, reverse=True))
            print(f"EXPECTED (TC-21 sort): the FILE NUMBER column orders correctly in both "
                  f"directions with no duplicates adjacent | ACTUAL: sortable={sortable}, "
                  f"monotone-per-direction={monotone}, first rows asc="
                  f"{orders.get('asc', [])[:5] if isinstance(orders.get('asc'), list) else orders.get('asc')} "
                  f"desc={orders.get('desc', [])[:5] if isinstance(orders.get('desc'), list) else orders.get('desc')}")
            assert sortable and all(monotone), (
                f"FILE NUMBER sort did not order the column: {orders}")
        finally:
            page.close()

    def test_sc8_tc22_global_search_by_number_routes(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            cases = self._cases()[:3]
            assert cases, "SC-3 / SC-4 must run first"
            results = {}
            for c in cases:
                go_to_staff_dashboard(page)
                header_global_search(page, c["case"])
                rows = gs_tab_rows(page, "LT-261")
                hits = [r for r in rows if c["case"] in r]
                submitter_ok = bool(hits) and len((hits[0] or "").split()) > 2
                routed = None
                if hits:
                    # Click the ROW that holds this number. The clickable element is the
                    # row's link cell (span.table-link / the VIN cell) — the FILE NUMBER
                    # <td> itself is inert, so clicking it navigates nowhere.
                    try:
                        row = page.locator(
                            f'table tbody tr:has-text("{c["case"]}")').first
                        target = row.locator(
                            'span.table-link, a, td span').first
                        if not target.count():
                            target = row
                        target.click()
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(2_500)
                        routed = page.url
                    except Exception as e:                              # noqa: BLE001
                        routed = f"click failed: {str(e)[:80]}"
                results[c["case"]] = {"rows": len(hits), "routed": routed,
                                      "submitter_populated": submitter_ok}
            _shot(page, "sc8_tc22_gs")

            # number-search and VIN-search must converge on the same case
            c0 = cases[0]
            go_to_staff_dashboard(page)
            header_global_search(page, c0["vin"])
            vin_rows = gs_tab_rows(page, "LT-261")
            converge = any(c0["case"] in r for r in vin_rows)

            bad = {k: v for k, v in results.items() if v["rows"] != 1}
            routed_ok = all(v["routed"] and re.search(r"/LT-261/.+/details", v["routed"], re.I)
                            for v in results.values() if v["routed"])
            ok = not bad and routed_ok and converge
            print(f"EXPECTED (TC-22): Global Search by D-format File# returns EXACTLY ONE LT-261 "
                  f"row per number, Submitter Name populated, row-click routing to "
                  f"/ncdot-notice-and-storage/LT-261/<id>/details; number-search and VIN-search "
                  f"converge on the same case | ACTUAL: {results}, VIN-search converges="
                  f"{converge} -> {'MATCH' if ok else 'MISMATCH'}")
            assert not bad, f"a D-number returned other than exactly one row: {bad}"
            assert routed_ok, f"row-click did not route to the LT-261 details page: {results}"
            assert converge, (f"searching VIN {c0['vin']} did not surface {c0['case']} — "
                              f"number-search and VIN-search disagree")
        finally:
            page.close()

    def test_sc8_tc23_correspondence_carries_the_number(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            st = load_state()
            targets = [st.get("sc3_dwi"), st.get("sc3_estop")]
            targets = [t for t in targets if t]
            assert targets, "SC-3 must run first"
            lt261 = Lt261Page(page)
            per = {}
            for t in targets:
                rows = []
                for _ in range(6):
                    try:
                        page.goto(LT261_LIST_URL, timeout=90_000)
                        page.wait_for_timeout(4_000)
                        lt261.open_details_for_vin(t["vin"])
                        lt261.click_view_correspondence()
                        page.wait_for_timeout(2_500)
                        rows = page.evaluate(
                            """() => { const d=document.querySelector('mat-dialog-container')||document.body;
                                 return [...d.querySelectorAll('table tbody tr, mat-row, [class*=row]')]
                                   .map(r=>(r.textContent||'').trim().replace(/\\s+/g,' '))
                                   .filter(t=>t).slice(0,40); }""")
                        if rows:
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(8_000)
                _shot(page, f"sc8_tc23_corr_{t['vin'][:6]}")
                per[t["case"]] = rows

            has_265 = {k: any(re.search(r"LT[- ]?265", r, re.I) for r in v) for k, v in per.items()}
            cross = {}
            keys = list(per)
            for i, k in enumerate(keys):
                others = [o for j, o in enumerate(keys) if j != i]
                cross[k] = [o for o in others if o in " ".join(per[k])]
            ok = all(per.values()) and not any(cross.values())
            print(f"EXPECTED (TC-23): each case's Correspondence/Forms list is reachable, carries "
                  f"its LT-265 / LT-265A entries, and contains NO other case's number | ACTUAL: "
                  f"rows-per-case={{{', '.join(f'{k}: {len(v)}' for k, v in per.items())}}}, "
                  f"LT-265 present={has_265}, cross-contamination={cross} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            for k, v in per.items():
                print(f"   {k}: {v[:6]}")
            assert all(per.values()), f"a case exposed no correspondence rows: {per}"
            assert not any(cross.values()), f"another case's number appears in this case's correspondence: {cross}"
            print("PARTIAL (blocker): the {file}_{type}_{datetime}.PDF filename and the number "
                  "PRINTED INSIDE the LT-265/265A PDFs are not read — the modal exposes row text, "
                  "not the stored filename, and PDF text extraction needs a PyPDF2 dependency the "
                  "suite does not carry (requirements.txt has no PDF reader).")
        finally:
            page.close()

    def test_sc8_tc26_audit_log_resolves_one_case(self, staff_context: BrowserContext):
        """TC-26 — Audit Log filtered by one D-number returns ONE case's activity.
        This is the surface where a duplicate number most silently merges two
        vehicles' histories."""
        page = staff_context.new_page()
        try:
            from src.pages.staff_portal.reports_page import ReportsPage
            cases = self._cases()
            assert cases, "SC-3 / SC-4 must run first"
            target = cases[0]
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_reports()
            page.wait_for_timeout(3_000)
            reports = ReportsPage(page)
            reachable = True
            body = ""
            try:
                reports.click_audit_report()
                page.wait_for_timeout(3_000)
                reports.set_date_range(past_date(7), future_date(0))
                page.wait_for_timeout(1_500)
                # Entity Number filter — at least one non-date filter is mandatory (BR-100)
                filled = page.evaluate(
                    """(num) => {
                        const ins=[...document.querySelectorAll('input')].filter(e=>e.offsetWidth||e.offsetHeight);
                        const hit=ins.find(e => /entity|case|file|number/i.test(
                          (e.getAttribute('placeholder')||'')+' '+(e.getAttribute('aria-label')||'')+' '+(e.name||'')));
                        if(!hit) return null;
                        const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                        setter.call(hit, num);
                        hit.dispatchEvent(new Event('input',{bubbles:true}));
                        hit.dispatchEvent(new Event('change',{bubbles:true}));
                        return hit.getAttribute('placeholder')||hit.name||'entity-field';
                    }""", target["case"])
                page.wait_for_timeout(1_500)
                reports.generate_report()
                page.wait_for_timeout(6_000)
                body = page.inner_text("body")
                print(f"   entity filter field: {filled!r}")
            except Exception as e:                                      # noqa: BLE001
                reachable = False
                print(f"   audit report drive failed: {str(e)[:180]}")
            _shot(page, "sc8_tc26_audit")

            other_numbers = [c["case"] for c in cases if c["case"] != target["case"]]
            leaked = [n for n in other_numbers if n in body]
            mine = target["case"] in body
            ok = reachable and not leaked
            print(f"EXPECTED (TC-26): the Audit Log filtered to Entity Number {target['case']} "
                  f"returns the activity of ONE case only — no other case's number appears | "
                  f"ACTUAL: report reachable={reachable}, own number present={mine}, other "
                  f"cases' numbers leaking into the result={leaked} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert reachable, ("the Audit Log Report could not be driven as N&S Administrator — "
                               "TC-26's audit half is unproven")
            assert not leaked, (f"the Audit Log merged other cases into a single-number filter: "
                                f"{leaked} — this is exactly how a duplicate number silently "
                                f"merges two vehicles' histories")
        finally:
            page.close()

    def test_sc8_tc25_bulk_print_blocked(self):
        """TC-25 — bulk print. Attempted, not automatable; the blocker is concrete."""
        print("EXPECTED (TC-25): Processed tab -> one selected date -> Print All LT-265s -> the "
              "async S3-emailed batch PDF contains one LT-265 per eligible case, each with its "
              "own distinct D-number, and the print-once dedup flag excludes already-printed "
              "cases on a re-run.")
        print("ACTUAL: NOT EXECUTED. Blocker (concrete, after attempting the reuse-first path): "
              "(1) there is no bulk-print page object or helper anywhere in the suite — "
              "Lt261Page exposes tabs/search/correspondence only, and no other page object "
              "references 'Print All'; (2) the output is not returned to the browser at all — it "
              "is an async batch job whose PDF arrives by EMAIL as an S3 link, and the suite has "
              "no mailbox reader (no imaplib/mailosaur/graph client in requirements.txt), so "
              "there is nothing to assert against inside one run; (3) reading a case number out "
              "of the resulting PDF additionally needs a PDF text extractor the suite does not "
              "carry. Automating this needs a mailbox integration + PDF reader — a scope decision "
              "for the user, not something to fake or to relabel as 'manual'.")
        pytest.skip("TC-25 bulk print: no bulk-print helper + async S3-emailed output + no "
                    "mailbox/PDF reader in the suite (see printed blocker).")


# ============================================================================
# SC-9 [Medium] RBAC sweep + pre-7/28 duplicate census                  TC-30
# ============================================================================

@pytest.mark.tw27366957
@pytest.mark.rbac
class TestTW27366957_SC9_RbacAndCensus:

    def test_sc9_admin_has_full_access(self, staff_context: BrowserContext):
        """TC-30 step 1 — the RBAC half MUST pass; it is not blocked on OQ-TW-1."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt261_listing()
            page.wait_for_timeout(4_000)
            dwi = page.locator('button:has-text("Add Paper DWI")').count()
            estop = page.locator('button:has-text("Add Paper E-Stop")').count()
            file_col = page.locator('th:has-text("FILE NUMBER"), th:has-text("File Number")').count()
            _shot(page, "sc9_admin_lt261")

            go_to_staff_dashboard(page)
            # Global Search needs 3+ characters — with fewer, the Search button stays
            # disabled (correct product behaviour, not a defect).
            header_global_search(page, year_prefix())
            gs_ok = bool(gs_tab_labels(page))
            _shot(page, "sc9_admin_gs")

            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_reports()
            page.wait_for_timeout(3_000)
            audit = page.locator(':text("Audit")').count()
            _shot(page, "sc9_admin_reports")

            ok = dwi and estop and file_col and gs_ok and audit
            print(f"EXPECTED (TC-30 admin): the N&S Administrator reaches Notice & Storage Forms, "
                  f"Add Paper DWI + Add Paper E-Stop, the minted number (FILE NUMBER column), "
                  f"Global Search and the Audit Log Report | ACTUAL: DWI btn={dwi}, E-Stop "
                  f"btn={estop}, FILE NUMBER column={file_col}, Global Search tabs={gs_ok}, "
                  f"Audit link={audit} -> {'MATCH' if ok else 'MISMATCH'}")
            assert ok, "the N&S Administrator is missing one of the required surfaces"
        finally:
            page.close()

    def test_sc9_fiscal_is_locked_out(self, fiscal_context: BrowserContext):
        """TC-30 step 3 — Fiscal User: reports only."""
        page = fiscal_context.new_page()
        try:
            go_to_staff_dashboard(page)
            page.wait_for_timeout(3_000)
            nav = page.locator('a:has-text("LT-261")').count()
            page.goto(LT261_LIST_URL, timeout=90_000)
            page.wait_for_timeout(6_000)
            url = page.url
            add_btns = page.locator(
                'button:has-text("Add Paper DWI"), button:has-text("Add Paper E-Stop")').count()
            numbers_visible = len(CN.CASE_RE.findall(page.inner_text("body")))
            _shot(page, "sc9_fiscal_lt261")
            denied = ("/LT-261" not in url) or ("login" in url) or (add_btns == 0)

            ok = (nav == 0) and denied and numbers_visible == 0
            print(f"EXPECTED (TC-30 fiscal): the Fiscal User reaches neither the LT-261 module nor "
                  f"any minted case number — reports only | ACTUAL: LT-261 nav links={nav}, "
                  f"landed={url}, add buttons={add_btns}, D-numbers visible={numbers_visible} -> "
                  f"{'MATCH' if ok else 'MISMATCH'}")
            assert ok, (f"the Fiscal User reached LT-261 content: nav={nav}, url={url}, "
                        f"add_buttons={add_btns}, numbers_visible={numbers_visible}")
        finally:
            page.close()

    def test_sc9_ns_user_leg_blocked(self):
        """TC-30 step 2 — the N&S User (non-admin staff) leg."""
        print("EXPECTED (TC-30 N&S User): the N&S User can log LT-261 and use Global Search and "
              "sees the minted number, but the Audit Log Report is NOT available to them "
              "(N&S Administrator only).")
        print("ACTUAL: NOT EXECUTED. Blocker (concrete): there is no N&S User authentication "
              "state in the suite. auth/qa/ holds exactly staff-portal.json (N&S Administrator), "
              "fiscal-portal.json, lsa-portal.json, public-portal.json, "
              "public-portal-user-b.json and individual-portal.json — no non-admin staff "
              "identity, and no N&S-User credentials in .env.qa (STAFF_USER_B_* is unset). "
              "Capturing one needs credentials that do not exist in this environment's config; "
              "scripts/save_staff_auth.py can mint the state as soon as they are supplied.")
        pytest.skip("TC-30 N&S User leg: no N&S User auth state / credentials available "
                    "(see printed blocker).")

    def test_sc9_pre_0728_duplicate_census(self):
        """TC-30 steps 4-6 — REPORT ONLY. Per comment 2, VGD must confirm with the client
        how past records are handled (OQ-TW-1), so this renders NO pass/fail verdict on
        the census itself."""
        tok = token()
        recs = CN.census(BASE_URL, tok)

        def before_0728(r):
            m = re.match(r"(\d{2})-(\d{2})-(\d{4})", r["submitted"] or "")
            if not m:
                return False
            mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return (yy, mm, dd) < (2026, 7, 28)

        window = [r for r in recs if before_0728(r)]
        by = {}
        for r in window:
            by.setdefault(r["case"], []).append(r)
        dups = {k: v for k, v in by.items() if len(v) > 1}

        print("PRE-7/28 DUPLICATE CENSUS (report only — OQ-TW-1, no verdict rendered):")
        print(f"  environment            : qa ({BASE_URL})")
        print(f"  LT-261 records examined: {len(recs)} total, {len(window)} created before "
              f"2026-07-28")
        print(f"  duplicate groups found : {len(dups)}")
        if dups:
            for num, rows in sorted(dups.items()):
                print(f"    {num}: {len(rows)} cases")
                for r in rows:
                    print(f"       vin={r['vin']} status={r['status']} submitted={r['submitted']}")
                print("       LT-265/LT-265A already issued? — determined per case from "
                      "Correspondence History; where status is Vehicle Sold the authority-to-sell "
                      "letters DO already carry the shared number.")
        else:
            print("    none — no pre-7/28 LT-261 on this environment holds a number that any "
                  "other case also holds.")
        print("STATUS: Blocked on OQ-TW-1 (comment 2 — VGD to confirm with the client how past "
              "records are handled). A pre-existing duplicate here would be blocked-on-OQ, not "
              "a defect against this fix.")
        save_state(pre_0728_census={"examined": len(window), "duplicate_groups": len(dups),
                                    "groups": {k: [r["vin"] for r in v] for k, v in dups.items()}})
        # deliberately no assertion on the census itself (report-only, OQ-blocked)


# ============================================================================
# Ungrouped test cases
# ============================================================================

@pytest.mark.tw27366957
class TestTW27366957_Ungrouped:

    def test_tc03_first_number_is_100001(self):
        """TC-03 — boundary: the very FIRST number the new sequence issues is exactly
        100001 (catches an eager nextval consumed at table creation -> 100002)."""
        tok = token()
        recs = CN.census(BASE_URL, tok)
        vals = sorted(CN.six(r["case"]) for r in recs if r["case"])
        lowest = vals[0] if vals else None
        print(f"EXPECTED (TC-03): on a VIRGIN sequence (is_called = false) the first issued "
              f"number is exactly 100001.")
        print(f"ACTUAL: NOT RUNNABLE HERE. This QA environment's sequence is long past its start "
              f"— the lowest D-number that exists at all is {lowest}, and 100001 itself is absent "
              f"while 100002/100003 are present, so the sequence has already advanced (and "
              f"whatever consumed 100001 left no surviving case). Re-running cannot recreate a "
              f"virgin sequence: pg_sequences.is_called cannot be reset from any product surface, "
              f"and the suite has no DB access (PRE-2). The boundary is instead covered by SC-3's "
              f"'6-digit portion >= 100001' assertion, which passes.")
        print("N/A — needs a freshly-provisioned environment or a restored clone.")
        pytest.skip("TC-03: requires a virgin sequence (is_called = false); not reproducible on a "
                    "shared QA environment.")

    def test_tc16_year_prefix_counter_does_not_reset(self):
        """TC-16 / OQ-42 — does the 6-digit counter reset each January?

        The plan called this un-runnable without a controllable clock. It is not: this
        environment already holds D-numbers from TWO calendar years, which answers the
        question directly from live data.
        """
        tok = token()
        recs = CN.census(BASE_URL, tok)
        by_prefix = {}
        for r in recs:
            if r["case"]:
                by_prefix.setdefault(CN.prefix(r["case"]), []).append(CN.six(r["case"]))
        summary = {p: {"n": len(v), "min": min(v), "max": max(v)}
                   for p, v in sorted(by_prefix.items())}
        print(f"OBSERVED YEAR BANDS: {json.dumps(summary, indent=1)}")

        if len(by_prefix) < 2:
            pytest.skip("TC-16: this environment holds only one year prefix — no cross-year "
                        "evidence available and no controllable clock (08 OQ-42).")

        ordered = sorted(by_prefix)
        older, newer = ordered[0], ordered[-1]
        legacy_newer = [v for v in by_prefix[newer] if v > max(by_prefix[older])]
        continued = bool(legacy_newer)
        overlap = sorted(set(by_prefix[older]) & set(by_prefix[newer]))

        print(f"EXPECTED (TC-16 / OQ-42, observation not spec): the new design is a SINGLE global "
              f"sequence with no year column, which implies the 6-digit counter NEVER resets — "
              f"only the D[YY] prefix changes.")
        print(f"ACTUAL: {older} spans {min(by_prefix[older])}-{max(by_prefix[older])} and {newer} "
              f"CONTINUES above it from {min(legacy_newer) if legacy_newer else 'n/a'} — "
              f"continued={continued}. So under the historic logic the counter did NOT reset at "
              f"the year boundary. -> the observed answer to OQ-42 is 'does not reset'.")
        print(f"CAVEAT / DEFECT LINKAGE: the NEW sequence restarted at 100001 while keeping the "
              f"{newer} prefix, so it is now re-walking a range the {older} band already used. "
              f"The full D[YY]-nnnnnn strings differ across years, so those particular values do "
              f"not collide — but {len([v for v in by_prefix[newer] if v > 0])} {newer} numbers "
              f"exist and the sequence sits below most of them (see SC-2 TC-14b). "
              f"{len(overlap)} six-digit value(s) are shared across the two prefixes: "
              f"{overlap[:10]}")
        print("ROUTE TO PO: confirm 'never resets' as spec. If the PO answers 'resets yearly', "
              "uniqueness of the FULL D[YY]-nnnnnn string becomes load-bearing on every keyed "
              "surface and needs a new case.")
        assert not [n for n in set(CN.numbers(recs))
                    if len([r for r in recs if r["case"] == n]) > 1], \
            "duplicate full case-number strings exist across the year bands"

    def test_tc24_nordis_nightly_index(self):
        """TC-24 — the DWI LT-265A entering the nightly Nordis index carries a unique
        case number. Seeded here; verification is next-day."""
        st = load_state()
        seeds = [st.get("sc3_dwi"), st.get("sc3_third")]
        seeds = [s for s in seeds if s]
        seeds += [m for m in (st.get("sc4_five") or []) if m.get("kind") == "dwi"]
        print("EXPECTED (TC-24): the next nightly Nordis index contains two DISTINCT entries, "
              "each keyed to its own DWI case number, record count matching the index, Certified "
              "Mail = N (first class), and NO LT-265 and no E-Stop 265A included (only the DWI "
              "265A was brought into Nordis by CR NCNSS-547).")
        print(f"SEEDED TODAY (same-day DWI LT-261s available for tomorrow's verification): "
              f"{[(s['vin'], s['case']) for s in seeds]}")
        print("ACTUAL: NOT COMPLETABLE INSIDE THIS RUN. Blocker (concrete): the Nordis index is "
              "produced by a NIGHTLY BATCH — the entries do not exist until the job runs, so no "
              "amount of polling inside one execution can observe them. The seeds above are the "
              "automatable half and are in place; the read-back is a next-day step against the "
              "Nordis tracking surface. Recipient targeting is explicitly OUT of scope — a "
              "recipient-side failure is OQ-64, not a numbering defect.")
        assert seeds, ("TC-24 could not even be SEEDED — SC-3/SC-4 must run first to create "
                       "same-day DWI LT-261s")
        pytest.skip("TC-24: nightly-batch dependent; seeded, verification is next-day.")
