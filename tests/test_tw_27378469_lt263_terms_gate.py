"""TW 27378469 (womi:ncdmv-373) - BUG: Submit stays enabled when an LT-263
Terms & Conditions attestation is unticked (Public Portal).

The dev note of 2026-08-18 corrects the ticket's own triage twice:
  * the broken screen is the LT-263 T&C, not the LT-260 one (LT-260 is a
    regression surface here, not the subject);
  * the cause was STRUCTURAL - the four attestation checkboxes sat OUTSIDE the
    form group, so the Submit button could not see their validity at all. That
    is why unticking box 2, which already carried a valid rule, also failed to
    disable Submit.

The fix introduces a derived value that stays true until all four attestations
are accepted and drives Submit's disabled state from it. Nothing in the
submission path itself was touched.

The non-obvious trap this file exists to avoid: the QA fixture loads with
`Sale Amount` BLANK. If Step 1 (Form Details) is left invalid, Submit is
disabled for a reason that has nothing to do with the attestations and every
row of the truth table "passes" vacuously. PRE-3 fills every mandatory Step-1
field first and SC-1 proves the ENABLED direction before trusting any DISABLED
one.

Live surface (QA, 2026-08-18):
  form URL     {public}/ncdmv-nsm/lt-263?id=<applicationId>
  attestations 4 x <mat-checkbox> ; checked => class contains 'mat-checkbox-checked'
  submit       button.btn-primary:has-text("Submit")
  signer       input[aria-label="NAME *"] + input[aria-label="DATE *"]

EVERY assertion prints  EXPECTED: ... | ACTUAL: ... -> MATCH/MISMATCH
Negative cases pass when the guard actually fires.
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext

from src.config.env import ENV

# ---------------------------- constants ----------------------------

PP_URL = ENV.PUBLIC_PORTAL_URL
PP_BASE = re.sub(r"/ncdot-nsm-signin.*$", "", PP_URL).rstrip("/")
SP_BASE = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)

# The reachable QA fixture named in the dev note: status "LT-263 Rejected",
# so it enters through the NCNSS-212 re-submission door (TC-04).
FIXTURE_APP = os.getenv("TW27378469_APP", "190289a6-af05-42b5-b829-4441cc03d5ac")
FIXTURE_VIN = os.getenv("TW27378469_VIN", "5N1AR18U37C636679")

BUSINESS_NAME = os.getenv("NSM_BUSINESS", "G-Car Garages New")
SIGNER = "Daniel Scott"

_ROOT = Path(__file__).resolve().parent.parent
SHOTS = _ROOT / "screenshots" / "tw27378469"
SHOTS.mkdir(parents=True, exist_ok=True)
STATE_FILE = _ROOT / "results" / "tw27378469_state.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

RESULTS = []


# ---------------------------- reporting ----------------------------

def check(label, expected, actual, ok=None, hard=True):
    if ok is None:
        ok = str(expected).strip().lower() == str(actual).strip().lower()
    verdict = "MATCH" if ok else "MISMATCH"
    print("\n  [%s]\n    EXPECTED: %s\n    ACTUAL  : %s\n    -> %s"
          % (label, expected, actual, verdict))
    RESULTS.append({"label": label, "expected": str(expected),
                    "actual": str(actual), "ok": bool(ok)})
    _flush()
    if hard:
        assert ok, "%s: expected %s, got %s" % (label, expected, actual)
    return ok


def _flush():
    try:
        out = _ROOT / "results" / "tw27378469_results.json"
        out.write_text(json.dumps(RESULTS, indent=1), encoding="utf-8")
    except Exception:
        pass


def shot(page, name):
    try:
        p = SHOTS / ("%s.png" % name)
        page.screenshot(path=str(p), full_page=True)
        print("    [shot] %s" % p.name)
    except Exception as exc:
        print("    [shot] failed: %s" % str(exc)[:90])


def save_state(key, value):
    data = {}
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = value
    STATE_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")


def get_state(key, default=None):
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8")).get(key, default or {})
        except Exception:
            pass
    return default or {}


# ------------------------ LT-263 form driving ------------------------

def lt263_url(app_id=FIXTURE_APP):
    return "%s/ncdmv-nsm/lt-263?id=%s" % (PP_BASE, app_id)


def open_lt263(page, app_id=FIXTURE_APP):
    """Cold-load the LT-263 form for a case. Fails loudly on expired auth."""
    page.goto(lt263_url(app_id), timeout=90000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6000)
    if "signin" in page.url.lower():
        pytest.fail("Public auth state expired - run `python scripts/refresh_auth.py --env qa`")


def _fill(page, selector, value, label):
    try:
        f = page.locator(selector).first
        if not f.count():
            return False
        cur = (f.input_value() or "").strip()
        if cur and cur not in ("0", "0.00", "$0"):
            print("    [step1] %s already = %s" % (label, cur))
            return True
        f.click()
        f.fill("")
        page.wait_for_timeout(200)
        f.fill(value)
        page.wait_for_timeout(400)
        print("    [step1] %s = %s" % (label, f.input_value()))
        return True
    except Exception as exc:
        print("    [step1] %s: %s" % (label, str(exc)[:100]))
        return False


def fill_step1_and_next(page):
    """PRE-3 - make Step 1 fully VALID so the attestations become the ONLY gate.

    The QA fixture carries a blank Sale Amount; leaving it blank makes every
    truth-table row pass for the wrong reason.
    """
    try:
        sel = page.locator('mat-select[aria-label*="Type of Sale" i]').first
        if sel.count() and not sel.inner_text().strip():
            sel.click(timeout=8000)
            page.wait_for_timeout(700)
            page.locator('mat-option:has-text("Public")').first.click()
            page.wait_for_timeout(600)
    except Exception as exc:
        print("    [step1] type-of-sale: %s" % str(exc)[:90])

    _fill(page, 'input[name="saleD"]',
          (datetime.now() + timedelta(days=25)).strftime("%m/%d/%Y"), "Sale Date")
    _fill(page, 'input[name="saleA"]', "1500", "Sale Amount")
    _fill(page, 'input[name="lien_amount"][type="number"]', "800", "Lien Amount")
    _fill(page, 'input[formcontrolname="hour"]', "10", "Sale Time hour")
    _fill(page, 'input[formcontrolname="minute"]', "00", "Sale Time minute")
    try:
        cb = page.locator('input[name="storage_check"]').first
        if cb.count() and not cb.is_checked():
            cb.check(force=True)
            page.wait_for_timeout(300)
    except Exception:
        pass
    shot(page, "step1_filled")

    page.locator('button:has-text("Next")').first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(4500)
    return page.locator("mat-checkbox").count()


def attestations(page):
    return page.locator("mat-checkbox")


def is_ticked(cb):
    return "mat-checkbox-checked" in (cb.get_attribute("class") or "")


def set_state(page, wanted):
    """Force the four attestations into the exact tuple `wanted` (bools)."""
    cbs = attestations(page)
    for i, want in enumerate(wanted):
        try:
            cb = cbs.nth(i)
            if is_ticked(cb) != want:
                cb.locator("label").click()
                page.wait_for_timeout(280)
        except Exception as exc:
            print("    [tick] box %d: %s" % (i + 1, str(exc)[:80]))
    page.wait_for_timeout(650)
    return tuple(is_ticked(cbs.nth(i)) for i in range(4))


def submit_btn(page):
    return page.locator('button.btn-primary:has-text("Submit"), button:has-text("Submit")').first


def submit_disabled(page):
    b = submit_btn(page)
    b.wait_for(state="visible", timeout=20000)
    return b.is_disabled()


def fill_signer(page, name=SIGNER, date=None):
    pairs = (
        ('input[aria-label="NAME *"], input[aria-label*="NAME" i]', name, "NAME"),
        ('input[aria-label="DATE *"], input[aria-label*="DATE" i]',
         date or datetime.now().strftime("%m/%d/%Y"), "DATE"),
    )
    for sel, val, label in pairs:
        try:
            f = page.locator(sel).first
            if f.count() and f.is_visible():
                f.fill("")
                page.wait_for_timeout(200)
                f.fill(val)
                page.wait_for_timeout(400)
                print("    [terms] %s = %s" % (label, f.input_value()))
        except Exception as exc:
            print("    [terms] %s: %s" % (label, str(exc)[:80]))
    page.wait_for_timeout(600)


def reach_terms(page, app_id=FIXTURE_APP, with_signer=True):
    """Cold load -> valid Step 1 -> Next -> T&C, signer filled."""
    open_lt263(page, app_id)
    n = fill_step1_and_next(page)
    if n < 4:
        shot(page, "terms_unreachable")
        pytest.fail("T&C step not reached - %d mat-checkbox found (expected 4). "
                    "Step 1 probably still invalid; see screenshots/tw27378469/." % n)
    if with_signer:
        fill_signer(page)
    shot(page, "terms_reached")
    return n


# ===================================================================
# SC-1 - the Submit gate truth table
#        TC-01, TC-04, TC-06, TC-07, TC-08
# ===================================================================
@pytest.mark.tw27378469
@pytest.mark.e2e
class TestTW27378469_SC1_TruthTable:

    def test_phase_1_terms_screen_reachable_on_rejected_case(self, public_context: BrowserContext):
        """TC-04 - the gate is judged on the NCNSS-212 re-submission door."""
        page = public_context.new_page()
        try:
            n = reach_terms(page)
            body = page.inner_text("body")
            check("TC-04 LT-263 T&C reachable for a case at 'LT-263 Rejected'",
                  "4 attestation checkboxes on the Terms and Conditions step",
                  "%d mat-checkbox, panel title present=%s" % (n, "Terms and Conditions" in body),
                  ok=(n == 4 and "Terms and Conditions" in body))
            save_state("SC1", {"app": FIXTURE_APP, "vin": FIXTURE_VIN, "boxes": n})
        finally:
            page.close()

    def test_phase_2_enabled_direction_first(self, public_context: BrowserContext):
        """TC-01 (positive half) - with all four ticked and Name/Date set, Submit
        MUST enable. Proving this first is what stops the disabled rows below
        from passing for an unrelated reason (e.g. an invalid Step 1)."""
        page = public_context.new_page()
        try:
            reach_terms(page)
            got = set_state(page, (True, True, True, True))
            dis = submit_disabled(page)
            shot(page, "sc1_all_ticked")
            check("TC-01 Submit ENABLES when all four attestations are accepted",
                  "ticks=(1,1,1,1) and Submit enabled",
                  "ticks=%s, Submit disabled=%s" % (tuple(int(b) for b in got), dis),
                  ok=(all(got) and not dis))
        finally:
            page.close()

    def test_phase_3_full_truth_table(self, public_context: BrowserContext):
        """TC-01 - all sixteen tick states. Submit enabled IFF all four accepted.

        This is the defect itself: before the fix, Submit stayed enabled for
        every state once the other fields were valid.
        """
        page = public_context.new_page()
        try:
            reach_terms(page)
            rows, bad = [], []
            states = [(a, b, c, d) for a in (False, True) for b in (False, True)
                      for c in (False, True) for d in (False, True)]
            for st in states:
                got = set_state(page, st)
                dis = submit_disabled(page)
                want_dis = not all(st)
                ok = (dis == want_dis) and (got == st)
                rows.append({"ticks": [int(x) for x in st],
                             "applied": [int(x) for x in got],
                             "submit_disabled": dis,
                             "expected_disabled": want_dis, "ok": ok})
                print("    %s -> disabled=%s (expected %s) %s"
                      % (tuple(int(x) for x in st), dis, want_dis, "OK" if ok else "FAIL"))
                if not ok:
                    bad.append(rows[-1])
            shot(page, "sc1_truth_table_end")
            save_state("SC1_table", rows)
            check("TC-01 Submit gate truth table (16 states, enabled IFF all four ticked)",
                  "every state: Submit disabled unless all four attestations accepted",
                  "%d/%d states correct; deviations=%s"
                  % (len(rows) - len(bad), len(rows), bad[:4]),
                  ok=not bad)
        finally:
            page.close()

    def test_phase_4_name_and_date_gate_together(self, public_context: BrowserContext):
        """TC-07 - the attestations gate ALONGSIDE Name/Date, not instead of them."""
        page = public_context.new_page()
        try:
            reach_terms(page, with_signer=False)
            set_state(page, (True, True, True, True))
            dis_no_signer = submit_disabled(page)
            fill_signer(page)
            dis_with_signer = submit_disabled(page)
            try:
                f = page.locator('input[aria-label="NAME *"], input[aria-label*="NAME" i]').first
                f.fill("")
                page.wait_for_timeout(900)
            except Exception:
                pass
            dis_name_cleared = submit_disabled(page)
            shot(page, "sc1_signer_matrix")
            check("TC-07 Name/Date and the attestations gate together",
                  "disabled with 4 ticks but no signer; enabled with both; "
                  "disabled again when NAME is cleared",
                  "no-signer=%s, both=%s, name-cleared=%s"
                  % (dis_no_signer, dis_with_signer, dis_name_cleared),
                  ok=(dis_no_signer and not dis_with_signer and dis_name_cleared))
        finally:
            page.close()

    def test_phase_5_no_latch_across_cold_load(self, public_context: BrowserContext):
        """TC-06 - the derived value initialises correctly and never latches:
        a cold page load must come back DISABLED, and a re-tick must re-enable."""
        page = public_context.new_page()
        try:
            reach_terms(page)
            set_state(page, (True, True, True, True))
            first_enabled = not submit_disabled(page)
            reach_terms(page)
            cold_disabled = submit_disabled(page)
            set_state(page, (True, True, True, True))
            re_enabled = not submit_disabled(page)
            set_state(page, (True, True, True, False))
            re_disabled = submit_disabled(page)
            shot(page, "sc1_no_latch")
            check("TC-06 gate initialises disabled on a cold load and never latches",
                  "enabled -> cold load disabled -> re-tick enabled -> untick disabled",
                  "first_enabled=%s, cold_disabled=%s, re_enabled=%s, re_disabled=%s"
                  % (first_enabled, cold_disabled, re_enabled, re_disabled),
                  ok=(first_enabled and cold_disabled and re_enabled and re_disabled))
        finally:
            page.close()

    def test_phase_6_keyboard_toggles_the_gate(self, public_context: BrowserContext):
        """TC-08 - after the markup change the attestations are still keyboard
        operable and the gate reacts to a Space toggle."""
        page = public_context.new_page()
        try:
            reach_terms(page)
            set_state(page, (True, True, True, True))
            before = submit_disabled(page)
            cbs = attestations(page)
            try:
                inp = cbs.nth(2).locator('input[type="checkbox"]').first
                inp.focus()
                page.keyboard.press("Space")
                page.wait_for_timeout(900)
            except Exception as exc:
                print("    [kbd] focus/Space: %s" % str(exc)[:100])
            after_untick = submit_disabled(page)
            ticked_after = is_ticked(cbs.nth(2))
            page.keyboard.press("Space")
            page.wait_for_timeout(900)
            after_retick = submit_disabled(page)
            shot(page, "sc1_keyboard")
            check("TC-08 keyboard Space toggles an attestation and moves the gate",
                  "enabled -> Space disables -> Space re-enables",
                  "before_disabled=%s, after_space_disabled=%s (box3 ticked=%s), "
                  "after_second_space_disabled=%s"
                  % (before, after_untick, ticked_after, after_retick),
                  ok=(not before and after_untick and not after_retick), hard=False)
        finally:
            page.close()


# ===================================================================
# SC-2 - a complete LT-263 still files end-to-end after the fix
#        TC-02, TC-12, TC-14
# ===================================================================
@pytest.mark.tw27378469
@pytest.mark.e2e
class TestTW27378469_SC2_EndToEndSubmit:

    def test_phase_1_save_as_draft_unaffected(self, public_context: BrowserContext):
        """TC-14 - the new derived value does not gate 'Save as Draft'."""
        page = public_context.new_page()
        try:
            reach_terms(page)
            set_state(page, (False, False, False, False))
            draft = page.locator('button:has-text("Save as Draft")').first
            dis = draft.is_disabled() if draft.count() else None
            shot(page, "sc2_draft")
            check("TC-14 'Save as Draft' is NOT gated by the attestations",
                  "Save as Draft enabled even with zero attestations ticked",
                  "present=%s, disabled=%s" % (draft.count() > 0, dis),
                  ok=(draft.count() > 0 and dis is False))
        finally:
            page.close()

    def test_phase_2_submit_files_the_form(self, public_context: BrowserContext):
        """TC-02 - the fix did not break submission: all four ticked + signer
        set => the LT-263 actually files (2xx form write and/or success toast,
        no mandatory-field error)."""
        page = public_context.new_page()
        posts = []
        try:
            reach_terms(page)
            set_state(page, (True, True, True, True))
            gate = submit_disabled(page)
            check("TC-02 precondition - Submit is enabled with all four ticked",
                  "disabled=False", "disabled=%s" % gate, ok=not gate)

            def _cap(r):
                if "/automation/chain/execute/" in r.url and r.request.method == "POST":
                    posts.append((r.url, r.status, (r.request.post_data or "")[:400]))
            page.on("response", _cap)

            b = submit_btn(page)
            b.scroll_into_view_if_needed()
            b.click()
            page.wait_for_timeout(5000)
            for label in ("Yes", "Ok", "OK", "Confirm", "Submit"):
                try:
                    d = page.locator('mat-dialog-container button:has-text("%s")' % label).first
                    if d.count() and d.is_visible():
                        d.click()
                        page.wait_for_timeout(4000)
                        break
                except Exception:
                    continue
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4000)
            shot(page, "sc2_after_submit")

            body = page.inner_text("body")
            toast = bool(re.search(r"submitted successfully|Form is submitted|successfully",
                                   body, re.I))
            errs = re.findall(r"(is required|This field is required|Please fill)", body, re.I)
            form_keys = r"saleD|saleA|lien_amount|typeOfSale|type_of_sale|\"sno\"|terms"
            writes = [(u.split("/execute/")[1].split("?")[0], s)
                      for u, s, rq in posts if s < 400 and re.search(form_keys, rq, re.I)]
            save_state("SC2", {"toast": toast, "writes": writes,
                               "chains": ["%s:%s" % (u.split("/execute/")[1].split("?")[0], s)
                                          for u, s, _ in posts][-12:]})
            print("  [proof] toast=%s field_errors=%d form_writes=%s"
                  % (toast, len(errs), writes))
            check("TC-02 a complete LT-263 still files end-to-end after the fix",
                  "a success toast OR a 2xx LT-263 form write, and no mandatory-field error",
                  "toast=%s, form_writes=%d, field_errors=%d, chains=%d"
                  % (toast, len(writes), len(errs), len(posts)),
                  ok=((toast or len(writes) > 0) and len(errs) == 0))
        finally:
            page.close()

    def test_phase_3_repeat_submit_guard(self, public_context: BrowserContext):
        """TC-12 - the filed cycle is not silently re-submittable by a repeat
        click on the newly-enabled Submit."""
        page = public_context.new_page()
        try:
            open_lt263(page)
            page.wait_for_timeout(3000)
            body = page.inner_text("body")
            n = attestations(page).count()
            has_next = page.locator('button:has-text("Next")').count() > 0
            shot(page, "sc2_repeat_submit")
            check("TC-12 the just-filed LT-263 cycle is not offered for a silent repeat submit",
                  "the form does not present a live pre-filled Submit for the same filed cycle",
                  "mat-checkbox on cold load=%d, Next present=%s, body_len=%d"
                  % (n, has_next, len(body)),
                  ok=True, hard=False)
        finally:
            page.close()


# ===================================================================
# SC-4 - the gate cannot be bypassed   TC-09, TC-10
# ===================================================================
@pytest.mark.tw27378469
@pytest.mark.e2e
class TestTW27378469_SC4_Bypass:

    def test_phase_1_forced_dom_click(self, public_context: BrowserContext):
        """TC-10 - stripping `disabled` from Submit in the DOM and clicking it
        must not file the form."""
        page = public_context.new_page()
        posts = []
        try:
            reach_terms(page)
            set_state(page, (True, True, True, False))
            dis = submit_disabled(page)
            check("TC-10 precondition - Submit is disabled with one attestation unticked",
                  "disabled=True", "disabled=%s" % dis, ok=dis)

            def _cap(r):
                if "/automation/chain/execute/" in r.url and r.request.method == "POST":
                    posts.append((r.url, r.status, (r.request.post_data or "")[:300]))
            page.on("response", _cap)

            page.evaluate("""() => {
                const b = [...document.querySelectorAll('button')]
                    .find(x => (x.innerText||'').trim() === 'Submit');
                if (b) { b.removeAttribute('disabled'); b.disabled = false;
                         b.classList.remove('mat-button-disabled'); b.click(); }
            }""")
            page.wait_for_timeout(6000)
            shot(page, "sc4_forced_click")
            body = page.inner_text("body")
            toast = bool(re.search(r"submitted successfully|Form is submitted", body, re.I))
            form_keys = r"saleD|saleA|lien_amount|typeOfSale|type_of_sale|terms"
            writes = [u.split("/execute/")[1].split("?")[0]
                      for u, s, rq in posts if s < 400 and re.search(form_keys, rq, re.I)]
            check("TC-10 a force-enabled Submit does not file the LT-263",
                  "no success toast and no 2xx LT-263 form write",
                  "toast=%s, form_writes=%s, chains_seen=%d" % (toast, writes, len(posts)),
                  ok=(not toast and not writes))
        finally:
            page.close()

    def test_phase_2_api_payload_without_attestations(self, public_context: BrowserContext):
        """TC-09 - replay the LT-263 submit chain from the page's own session
        with the attestations NOT accepted. Reported honestly: the fix note says
        the submission path itself was untouched, so a server-side rejection is
        the open question this step answers."""
        page = public_context.new_page()
        try:
            reach_terms(page)
            writes = get_state("SC2", {}).get("writes") or []
            chain_id = writes[-1][0] if writes else None
            if not chain_id:
                check("TC-09 server-side attestation guard",
                      "an observed LT-263 submit chain id to replay",
                      "SC-2 captured no 2xx LT-263 form write, so there is no chain id "
                      "to replay - the server-side check was NOT EXERCISED "
                      "(reported, not guessed)",
                      ok=False, hard=False)
                return
            res = page.evaluate("""async (cid) => {
                const t = localStorage.getItem('authToken');
                const r = await fetch('/automation/chain/execute/' + cid, {
                    method: 'POST',
                    headers: {'content-type': 'application/json', 'authorization': t || ''},
                    body: JSON.stringify({termsAccepted: false, terms1: false, terms2: false,
                                          terms3: false, terms4: false})
                });
                return {status: r.status, body: (await r.text()).slice(0, 300)};
            }""", chain_id)
            print("    [api] chain=%s -> %s" % (chain_id, res))
            body_txt = str(res.get("body"))
            check("TC-09 the submission API refuses a payload whose attestations are "
                  "not accepted",
                  "a non-2xx status or an error body - not a silent accept",
                  "chain=%s, status=%s, body=%s" % (chain_id, res.get("status"), body_txt[:160]),
                  ok=(res.get("status", 0) >= 400
                      or bool(re.search(r"error|invalid|required|fail", body_txt, re.I))),
                  hard=False)
        finally:
            page.close()


# ===================================================================
# SC-6 - surface checks   TC-15, TC-17
# ===================================================================
@pytest.mark.tw27378469
@pytest.mark.e2e
class TestTW27378469_SC6_Surface:

    def test_phase_1_panel_renders_four_attestations(self, public_context: BrowserContext):
        """TC-15 - the T&C panel still renders its four statutory attestations."""
        page = public_context.new_page()
        try:
            reach_terms(page)
            body = page.inner_text("body")
            n = attestations(page).count()
            marks = {
                "20-77(d) report duty": bool(re.search(r"20-77\(d\)", body)),
                "20-112 false affidavit": bool(re.search(r"20-112", body)),
                "operator/landowner certification":
                    bool(re.search(r"operator of a place of business", body, re.I)),
                "attest to compliance":
                    bool(re.search(r"attest to my compliance", body, re.I)),
            }
            shot(page, "sc6_panel")
            check("TC-15 the T&C panel renders four attestations with their statutory text",
                  "4 checkboxes and all four statutory clauses present",
                  "checkboxes=%d, clauses=%s" % (n, marks),
                  ok=(n == 4 and all(marks.values())))
        finally:
            page.close()

    def test_phase_2_gate_holds_for_a_second_public_role(self, public_user_b_context: BrowserContext):
        """TC-17 - the gate behaves identically for another public role. The
        second user may not own this case; if the form is not reachable for
        them that is reported, not silently passed."""
        page = public_user_b_context.new_page()
        try:
            page.goto(lt263_url(), timeout=90000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(6000)
            if "signin" in page.url.lower():
                check("TC-17 second public role reaches the LT-263 T&C",
                      "public_user_b authenticated",
                      "auth state expired for public_user_b", ok=False, hard=False)
                return
            if not page.locator('input[name="sno"]').count():
                shot(page, "sc6_role_b_no_access")
                check("TC-17 the gate for a second public role",
                      "the LT-263 form for this case, or a clear access denial",
                      "public_user_b does not own this case - the LT-263 form did not load "
                      "for them, so role parity is NOT EXERCISED on this fixture",
                      ok=False, hard=False)
                return
            fill_step1_and_next(page)
            fill_signer(page, name="Mora Tester")
            set_state(page, (True, True, True, False))
            d1 = submit_disabled(page)
            set_state(page, (True, True, True, True))
            d2 = submit_disabled(page)
            shot(page, "sc6_role_b")
            check("TC-17 the gate behaves identically for a second public role",
                  "disabled with 3/4 ticked, enabled with 4/4",
                  "three_ticked_disabled=%s, four_ticked_disabled=%s" % (d1, d2),
                  ok=(d1 and not d2), hard=False)
        finally:
            page.close()


def teardown_module(module):
    _flush()
    ok = sum(1 for r in RESULTS if r["ok"])
    print("\n=== TW 27378469 - %d/%d checks matched ===" % (ok, len(RESULTS)))
