"""TW-27171126 / NCNSS-521 - "Highlight the VIN of an LT-260/LT-261 whose VIN has a
previously rejected or closed case, and hold auto-processing" verification driver.

Standalone (non-pytest) Playwright driver used by the nsm-lt260-vin-highlight skill and by
ExpertlyTestBuddy / runTestPlan. Each --mode maps to one scenario of the ticket's test plan
and prints the mandatory EXPECTED: / ACTUAL: -> MATCH|MISMATCH pairs that runTestPlan's
report parser scrapes.

    python tests/tw_27171126_vin_highlight.py --mode listing260   # SC-1
    python tests/tw_27171126_vin_highlight.py --mode listing261   # SC-2
    python tests/tw_27171126_vin_highlight.py --mode hold         # SC-3
    python tests/tw_27171126_vin_highlight.py --mode history      # SC-4
    python tests/tw_27171126_vin_highlight.py --mode contract     # SC-5
    python tests/tw_27171126_vin_highlight.py --mode safety       # SC-6
    python tests/tw_27171126_vin_highlight.py --mode roles        # SC-7

The colours under test come straight from the test-case document: a flagged VIN must compute
to rgb(230, 163, 77) (the date-picker orange) and an unflagged one to rgb(36, 90, 125).

Screenshots land in skills/nsm-lt260-vin-highlight/screenshots/ (runTestPlan contract:
`glob:screenshots/*.png`), numbered NN_ in execution order so the report can name the failing
step. Stale shots are cleared at the start of every invocation - the shared-screenshots-dir
hazard documented in runTestPlan/SKILL.md.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("NSM_ENV", "qa")
E2E_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(E2E_ROOT))
os.chdir(E2E_ROOT)

from playwright.sync_api import sync_playwright  # noqa: E402

from src.config.env import ENV  # noqa: E402

BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
BASE_PATH = "/pages/ncdot-notice-and-storage"
LT260_LIST_URL = BASE_URL + BASE_PATH + "/LT-260/list"
LT261_LIST_URL = BASE_URL + BASE_PATH + "/LT-261/list"
PUBLIC_URL = re.sub(r"/login$", "", ENV.PUBLIC_PORTAL_URL)

SHOTS = E2E_ROOT.parent / "skills" / "nsm-lt260-vin-highlight" / "screenshots"

# AC-1: the same orange as the date-picker chips; normal VINs stay the standard link blue.
ORANGE = "rgb(230, 163, 77)"
NORMAL = "rgb(36, 90, 125)"
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{11,17}$")

# Every tab other than "To Process" must be highlight-free (the AC-1 scope clause). Bounded to
# the three tabs that can actually hold a flagged VIN so a board-triggered run stays in budget.
OTHER_TABS_260 = ["Processed", "Rejected", "Closed"]
OTHER_TABS_261 = ["Processed", "Rejected", "Closed"]

JS_TAB_CLICK = (
    "(name) => { const t = [...document.querySelectorAll('[role=tab]')]"
    ".find(e => e.innerText.trim().toLowerCase().startsWith(name.toLowerCase()));"
    " if (t) { t.click(); return true; } return false; }"
)

# Harvest the FIRST cell of every row together with the computed colour of whatever element
# actually carries the VIN text (the implementation embeds the highlight inside the cell, so
# the colour may live on a span/a inside the td rather than on the td itself).
JS_VIN_CELLS = """
() => {
  const out = [];
  for (const tr of document.querySelectorAll('tbody tr')) {
    const td = tr.querySelector('td');
    if (!td) continue;
    const text = (td.innerText || '').trim();
    if (!text) continue;
    // deepest element still carrying the full VIN text
    let el = td;
    for (;;) {
      const kid = [...el.children].find(c => (c.innerText || '').trim() === text);
      if (!kid) break;
      el = kid;
    }
    const cs = getComputedStyle(el);
    out.push({
      text: text,
      color: cs.color,
      bg: cs.backgroundColor,
      tag: el.tagName.toLowerCase(),
      cls: el.className || '',
      html: td.innerHTML.slice(0, 400),
      textContent: (td.textContent || '').trim(),
    });
  }
  return out;
}
"""

JS_ROWS = "els => els.map(r => Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim()))"
JS_NEXT_PAGE = (
    "() => { const b = document.querySelector('button[aria-label=\"Next page\"]');"
    " if (b && !b.disabled) { b.click(); return true; } return false; }"
)

_shot_n = 0
_checks = []


def shot(page, label):
    global _shot_n
    _shot_n += 1
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{_shot_n:02d}_{label}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        print(f"[shot] {path}")
    except Exception as exc:                                    # pragma: no cover
        print(f"[shot] FAILED {label}: {exc}")


def check(expected, actual, ok):
    _checks.append(bool(ok))
    print(f"EXPECTED: {expected}")
    print(f"ACTUAL: {actual} -> {'MATCH' if ok else 'MISMATCH'}")


def clear_stale_shots():
    if SHOTS.exists():
        for f in SHOTS.glob("*.png"):
            try:
                f.unlink()
            except OSError:
                pass


def ctx_page(pw, holder, state="staff-portal.json"):
    browser = pw.chromium.launch(headless=True)
    holder.append(browser)
    ctx = browser.new_context(
        storage_state=str(E2E_ROOT / "auth" / os.environ["NSM_ENV"] / state),
        timezone_id="America/New_York",
    )
    page = ctx.new_page()
    page.set_default_timeout(30_000)
    return page


def settle(page, timeout=18_000):
    """networkidle is best-effort on this Angular app (it polls in the background), so never
    let a hard wait_for_load_state be the thing that aborts a scenario."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        page.wait_for_timeout(2500)


def open_listing(page, url):
    page.goto(url, timeout=60_000)
    settle(page)
    try:
        page.wait_for_selector("[role=tab]", timeout=25_000)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def click_tab(page, name, tries=5):
    for _ in range(tries):
        if page.evaluate(JS_TAB_CLICK, name):
            page.wait_for_timeout(3500)
            return True
        page.wait_for_timeout(2000)
    return False


def vin_cells(page):
    try:
        return [c for c in page.evaluate(JS_VIN_CELLS) if VIN_RE.match(c["text"].upper())]
    except Exception as exc:
        print(f"NOTE: VIN-cell harvest failed: {exc}")
        return []


def cells_on_tab(page, url, tab, tries=3):
    """(cells, tab_reachable) for `tab` of `url`, retrying the open+click.

    The Angular listing renders its rows well after networkidle and intermittently returns
    an empty tbody on the first click (observed live 2026-08-05: the same tab yielded 10
    rows in one step and 0 in the next). An empty first read is a harness artefact, not a
    product verdict, so retry before reporting it.
    """
    reachable = False
    for i in range(tries):
        open_listing(page, url)
        if not click_tab(page, tab):
            continue
        reachable = True
        page.wait_for_timeout(2000 + 2000 * i)
        cells = vin_cells(page)
        if cells:
            return cells, True
        print(f"NOTE: '{tab}' rendered 0 VIN rows on attempt {i + 1}/{tries} - retrying")
    return [], reachable


def classify(cells):
    orange = [c for c in cells if c["color"] == ORANGE]
    normal = [c for c in cells if c["color"] == NORMAL]
    other = [c for c in cells if c["color"] not in (ORANGE, NORMAL)]
    return orange, normal, other


def harvest_history(page, url, tabs, max_pages=1):
    """VIN -> set(tab) for the terminal tabs, used as the ground truth for 'has prior history'."""
    hist = {}
    for tab in tabs:
        cells, reachable = cells_on_tab(page, url, tab, tries=2)
        if not reachable:
            print(f"NOTE: tab '{tab}' not present - skipped")
            continue
        for c in cells:
            hist.setdefault(c["text"].upper(), set()).add(tab)
        pages_read = 1
        while pages_read < max_pages:
            for r in page.eval_on_selector_all("tbody tr", JS_ROWS):
                if r and VIN_RE.match(r[0].upper()):
                    hist.setdefault(r[0].upper(), set()).add(tab)
            pages_read += 1
            if not page.evaluate(JS_NEXT_PAGE):
                break
            page.wait_for_timeout(3000)
    return hist


# ───────────────────────────── shared listing assertions ─────────────────────────────
def assert_listing(page, url, form, other_tabs, deep=True):
    cells, reachable = cells_on_tab(page, url, "To Process")
    if not reachable:
        check(f"the {form} 'To Process' tab is reachable in the Staff Portal",
              f"no tab whose label starts with 'To Process' was found at {url}", False)
        shot(page, f"{form}-no-toprocess-tab")
        return None
    shot(page, f"{form}-to-process")

    check(f"the {form} To Process tab renders at least one VIN whose colour can be read",
          f"{len(cells)} VIN cell(s) harvested from {url}", bool(cells))
    if not cells:
        return None

    orange, normal, other = classify(cells)
    print(f"PALETTE: {len(orange)} orange / {len(normal)} normal / {len(other)} other; "
          f"distinct colours = {sorted({c['color'] for c in cells})}")
    check(f"every VIN on the {form} To Process tab renders in exactly one of the two "
          f"specified colours - flagged {ORANGE} or normal {NORMAL} (AC-1, mock comparison)",
          (f"{len(orange)} orange + {len(normal)} normal of {len(cells)}"
           + (f"; UNEXPECTED colours {sorted({c['color'] for c in other})} on "
              f"{[c['text'] for c in other][:5]}" if other else "; no third colour")),
          not other)
    check(f"the highlight actually fires on {form} To Process - at least one VIN is painted "
          f"orange {ORANGE} because it carries a prior rejected/closed case (AC-1)",
          (f"{len(orange)} orange VIN(s): {[c['text'] for c in orange][:5]}" if orange
           else f"zero orange VINs among {len(cells)} rows - either no flagged VIN is "
                f"currently on this tab, or the highlight is not rendering"),
          bool(orange))

    if not deep:
        return cells

    # AC-1 scope clause: no other tab of the same form may show the highlight.
    leaked = {}
    for tab in other_tabs:
        tab_cells, reachable = cells_on_tab(page, url, tab, tries=2)
        if not reachable:
            print(f"NOTE: tab '{tab}' not present on this build - skipped")
            continue
        o, _, _ = classify(tab_cells)
        if o:
            leaked[tab] = [c["text"] for c in o][:5]
    shot(page, f"{form}-other-tabs")
    check(f"the orange highlight appears on the {form} 'To Process' tab and on NO other tab "
          f"({', '.join(other_tabs)}) - the AC-1 scope clause",
          (f"orange VINs leaked onto {leaked}" if leaked
           else f"zero orange VIN cells across {other_tabs}"),
          not leaked)
    return cells


# ─────────────────────────────── SC-1 · LT-260 listing ────────────────────────────────
def mode_listing260(page):
    cells = assert_listing(page, LT260_LIST_URL, "LT-260", OTHER_TABS_260)
    if not cells:
        return page

    # Cross-check the flag against the real terminal-status population (AC-3 ground truth).
    hist = harvest_history(page, LT260_LIST_URL, ["Rejected", "Closed"])
    cells, _ = cells_on_tab(page, LT260_LIST_URL, "To Process")
    orange, normal, _ = classify(cells)
    wrong_blue = [c["text"] for c in normal if c["text"].upper() in hist]
    check("a VIN that this environment shows in an LT-260 Rejected/Closed tab is NOT left "
          "unhighlighted on To Process (no false negative against the observable history)",
          (f"{len(wrong_blue)} VIN(s) with visible LT-260 terminal history still render normal: "
           f"{wrong_blue[:5]}" if wrong_blue
           else f"none of the {len(normal)} normal VINs appears in the observable "
                f"Rejected/Closed population ({len(hist)} VINs)"),
          not wrong_blue)
    print(f"NOTE: only the LT-260 Rejected/Closed tabs are observable from the UI; a VIN whose "
          f"prior terminal case is an LT-262/262A/263 is legitimately orange without appearing "
          f"in this harvest, so the reverse direction is not asserted here (see mode=history).")

    # In-place refresh persistence (TC-07).
    before = {c["text"]: c["color"] for c in cells}
    page.reload()
    settle(page)
    click_tab(page, "To Process")
    after_cells = vin_cells(page)
    if not after_cells:                       # empty first read after a reload is a harness
        after_cells, _ = cells_on_tab(page, LT260_LIST_URL, "To Process", tries=2)
    after = {c["text"]: c["color"] for c in after_cells}
    shot(page, "lt260-after-reload")
    common = set(before) & set(after)
    drifted = [v for v in common if before[v] != after[v]]
    check("the highlight survives an in-place re-render of the listing (reload / tab "
          "re-entry) - it is data-driven, not a one-shot paint (TC-07)",
          (f"{len(drifted)} VIN(s) changed colour across the refresh: {drifted[:5]}"
           if drifted else f"all {len(common)} re-rendered VINs kept their colour"),
          bool(common) and not drifted)
    return page


# ─────────────────────── SC-2 · LT-261 listing + both detail pages ────────────────────
def mode_listing261(page):
    cells = assert_listing(page, LT261_LIST_URL, "LT-261", OTHER_TABS_261)
    if not cells:
        return page
    orange, normal, _ = classify(cells)

    # AC-2 - the same highlight on the read-only detail page.
    for label, group, want in (("flagged", orange, ORANGE), ("clean", normal, NORMAL)):
        if not group:
            print(f"NOTE: no {label} VIN available on LT-261 To Process - detail-page check "
                  f"for that class not attempted this run")
            continue
        vin = group[0]["text"]
        cells_on_tab(page, LT261_LIST_URL, "To Process", tries=2)
        try:
            page.get_by_text(vin, exact=True).first.click(timeout=20_000)
            page.wait_for_timeout(6000)
            settle(page)
        except Exception as exc:
            shot(page, f"lt261-detail-{label}-nav-failed")
            check(f"the {label} LT-261 row for VIN {vin} opens its read-only detail page",
                  f"the row click did not navigate ({type(exc).__name__}); still on {page.url}",
                  False)
            continue
        shot(page, f"lt261-detail-{label}")
        colours = page.evaluate(
            """(vin) => [...document.querySelectorAll('*')]
                 .filter(e => e.children.length === 0 &&
                              (e.innerText || '').trim().toUpperCase() === vin)
                 .map(e => getComputedStyle(e).color)""", vin.upper())
        check(f"on the LT-261 read-only detail page the VIN field of the {label} case {vin} "
              f"renders {want} (AC-2 - the same condition as the listing)",
              (f"the VIN element(s) compute to {sorted(set(colours))}" if colours
               else f"the VIN {vin} was not found as a leaf element on {page.url}"),
              bool(colours) and want in colours)
    return page


# ──────────────────────────────── SC-3 · the hold ─────────────────────────────────────
def mode_hold(page, budget_s=200):
    from tests.test_e2e_004_sheriff_inspector_lt261 import create_lt261  # noqa: E402
    from src.pages.staff_portal.lt261_page import Lt261Page  # noqa: E402

    started = time.time()
    # PRE-2: a VIN that this environment already shows in a terminal status.
    hist = harvest_history(page, LT261_LIST_URL, ["Rejected", "Closed"], max_pages=1)
    if not hist:
        hist = harvest_history(page, LT260_LIST_URL, ["Rejected", "Closed"], max_pages=1)
    check("this environment offers at least one VIN with a prior Rejected/Closed case, so the "
          "hold can be exercised at all (PRE-2)",
          f"{len(hist)} VIN(s) harvested from the Rejected/Closed tabs: {list(hist)[:5]}",
          bool(hist))
    if not hist:
        return page

    # A VIN that already carries an ACTIVE LT-261 cannot have a second E-Stop raised on it:
    # the 'Add from Paper' modal simply never advances past its Next button. Because this
    # scenario CREATES such a case, always taking sorted(hist)[0] made the mode a one-shot -
    # every re-run picked the VIN the previous run had just consumed and failed in the modal
    # rather than on the behaviour under test. Walk the candidates instead, and only report a
    # submit failure once no flagged VIN is left. (CONFIRMED on STAGE 2026-08-10.)
    candidates = sorted(hist)
    shot(page, "flagged-vin-source")
    vin, submitted, last_exc = None, False, None
    for cand in candidates:
        print(f"USING flagged VIN {cand} (seen in {sorted(hist[cand])})")
        try:
            create_lt261(page, cand, "NCNSS-521 Hold Officer", "E-Stop", stolen=False)
            page.wait_for_timeout(4000)
            vin, submitted = cand, True
            break
        except Exception as exc:
            last_exc = exc
            print(f"NOTE: {cand} could not take a new E-Stop "
                  f"({type(exc).__name__}) - it most likely already has an active LT-261; "
                  f"trying the next flagged VIN")
    if not submitted:
        vin = candidates[0]
        shot(page, "lt261-submit-failed")
        check("a new LT-261 E-Stop on a flagged VIN SAVES successfully - the hold runs "
              "asynchronously and is failure-tolerated, it must never fail the submit (TC-13)",
              f"no flagged VIN of {len(candidates)} could take a new E-Stop; last failure "
              f"({type(last_exc).__name__}: {last_exc})", False)
    if submitted:
        shot(page, "lt261-submitted")
        body = ""
        try:
            body = page.inner_text("body")
        except Exception:
            pass
        errored = bool(re.search(r"(went wrong|error occurred|failed to|could not be saved)",
                                 body, re.I))
        check("a new LT-261 E-Stop on a flagged VIN SAVES successfully - no error toast, no "
              "failed submit (the hold is runAsync / exitOnFailure tolerated) (TC-13)",
              ("an error banner is present on the page after submit"
               if errored else "the submit completed with no error banner"),
              not errored)
        try:
            Lt261Page(page).expect_no_lt265_issue_popup()
            check("no LT-265 / LT-265A is auto-issued for the held case - the auto-process "
                  "edge is blocked (AC-4)",
                  "no LT-265 auto-issue popup fired after submit", True)
        except Exception as exc:
            shot(page, "lt265-popup")
            check("no LT-265 / LT-265A is auto-issued for the held case - the auto-process "
                  "edge is blocked (AC-4)",
                  f"the LT-265 auto-issue assertion failed ({type(exc).__name__}: {exc})", False)

    if time.time() - started > budget_s:
        print(f"NOTE: time budget ({budget_s}s) reached - reporting the landing check from the "
              f"listing without further waits.")
    # AC-4: the record must stay on To Process, orange, and not on Processed / Vehicle Sold.
    open_listing(page, LT261_LIST_URL)
    found_tab, colour = None, None
    for tab in ["To Process", "Processed", "Stolen"]:
        if not click_tab(page, tab):
            continue
        for c in vin_cells(page):
            if c["text"].upper() == vin.upper():
                found_tab, colour = tab, c["color"]
                break
        if found_tab:
            break
    shot(page, "lt261-landing-tab")
    check(f"the newly created LT-261 for the flagged VIN {vin} stays on the 'To Process' tab "
          f"for manual staff review - it is NOT auto-processed to Processed / Vehicle Sold (AC-4)",
          (f"the row was found on the '{found_tab}' tab" if found_tab
           else "the new row was not located on any of To Process / Processed / Stolen"),
          found_tab == "To Process")
    if found_tab == "To Process":
        check(f"that held row's VIN renders orange {ORANGE} on To Process, so staff can see "
              f"why it was held (AC-1 + AC-4 together)",
              f"the VIN computes to {colour}", colour == ORANGE)
    return page


# ──────────────────────────── SC-4 · prior-status matrix ──────────────────────────────
def mode_history(page):
    hist260 = harvest_history(page, LT260_LIST_URL, ["Rejected", "Closed", "Processed"])
    hist261 = harvest_history(page, LT261_LIST_URL, ["Rejected", "Closed", "Processed"])
    terminal = {v for v, tabs in list(hist260.items()) + list(hist261.items())
                if tabs & {"Rejected", "Closed"}}
    non_terminal = {v for v, tabs in list(hist260.items()) + list(hist261.items())
                    if not (tabs & {"Rejected", "Closed"})}
    print(f"POPULATION: {len(terminal)} VIN(s) with a Rejected/Closed case, "
          f"{len(non_terminal)} with only non-terminal history")
    check("the QA population contains both flagged (Rejected/Closed) and non-flagged history, "
          "so the AC-3 matrix has something to discriminate between",
          f"{len(terminal)} terminal-history VINs vs {len(non_terminal)} non-terminal",
          bool(terminal) and bool(non_terminal))

    results = {}
    for url, form in ((LT260_LIST_URL, "LT-260"), (LT261_LIST_URL, "LT-261")):
        cells, reachable = cells_on_tab(page, url, "To Process", tries=2)
        if not reachable:
            continue
        for c in cells:
            results[(form, c["text"].upper())] = c["color"]
    shot(page, "history-matrix")

    false_neg = [k for k, col in results.items() if k[1] in terminal and col != ORANGE]
    false_pos = [k for k, col in results.items()
                 if col == ORANGE and k[1] in non_terminal and k[1] not in terminal]
    check("every To Process VIN that this environment shows in a Rejected or Closed status "
          "renders orange - no flagged status is missed (AC-3, BR-19 / BR-43)",
          (f"{len(false_neg)} miss(es): {false_neg[:5]}" if false_neg
           else f"all {len([1 for k, c in results.items() if k[1] in terminal])} matching "
                f"To Process rows are orange"),
          not false_neg)
    check("a VIN whose only observable history is non-terminal (Processed / in flight) is NOT "
          "highlighted - the flag does not over-fire (AC-3)",
          (f"{len(false_pos)} over-fire(s): {false_pos[:5]}" if false_pos
           else "no VIN with only non-terminal history renders orange"),
          not false_pos)
    print("NOTE: the ticket's worked example (LT-260 approved, LT-262 later rejected, LT-260 "
          "refiled) needs an LT-262 rejection on the same VIN; the LT-262 tabs are a separate "
          "listing surface and are not harvested by this mode - it is asserted only to the "
          "extent that the LT-260/261 observable history allows.")
    return page


# ───────────────────────── SC-5 · hasPriorRejectedLT260 contract ──────────────────────
def mode_contract(page):
    seen = []

    def on_response(resp):
        try:
            if resp.request.method not in ("POST", "GET"):
                return
            ct = (resp.headers or {}).get("content-type", "")
            if "json" not in ct:
                return
            body = resp.text()
            if "hasPriorRejected" in body:
                seen.append((resp.url, body[:20000]))
        except Exception:
            pass

    page.on("response", on_response)
    cells260, _ = cells_on_tab(page, LT260_LIST_URL, "To Process", tries=2)
    cells261, _ = cells_on_tab(page, LT261_LIST_URL, "To Process", tries=2)
    page.wait_for_timeout(3000)
    shot(page, "contract-listings")

    check("the read chains behind the LT-260 and LT-261 listings return the new "
          "hasPriorRejectedLT260 flag in their payload (the single source of the highlight)",
          (f"{len(seen)} response(s) carry the flag: "
           f"{[u.split('?')[0][-70:] for u, _ in seen][:4]}" if seen
           else "no listing response contained 'hasPriorRejected' - either the field is named "
                "differently on this build or it is computed server-side without being exposed"),
          bool(seen))

    values = []
    for _, body in seen:
        for m in re.finditer(r'"hasPriorRejected\w*"\s*:\s*(true|false|"[^"]*"|\d+)', body):
            values.append(m.group(1))
    if values:
        check("hasPriorRejectedLT260 is a strict boolean on the wire (a string or numeric "
              "encoding would make every consumer's truthiness check environment-dependent)",
              f"observed values {sorted(set(values))} across {len(values)} occurrence(s)",
              set(values) <= {"true", "false"})
        n_true = values.count("true")
        orange = len([c for c in cells260 + cells261 if c["color"] == ORANGE])
        check("the number of rows the API flags true agrees with the number of VINs actually "
              "painted orange - the UI is driven by the contract, not by a second rule",
              f"API reported true for {n_true} row(s); {orange} VIN(s) render orange "
              f"across the two To Process tabs",
              n_true == orange)
    print("NOTE: the expression index application_form_details_upper_idx (TC-16) and the "
          "gate-ordering assertion (TC-12) are DB / chain-internal and are not observable from "
          "the Staff Portal UI or its network traffic - they are reported as not verified by "
          "this run rather than guessed at.")
    check("the index-existence and gate-ordering test cases (TC-16, TC-12) are verified by "
          "this run",
          "not verifiable from the UI channel - no DB or Automation-Designer access from this "
          "suite; these two remain open and are called out in the report",
          False)
    return page


# ─────────────────────────── SC-6 · raw VIN / injection safety ────────────────────────
def mode_safety(page):
    cells, _ = cells_on_tab(page, LT260_LIST_URL, "To Process")
    orange = [c for c in cells if c["color"] == ORANGE]
    target = (orange or cells)
    check("a VIN cell is available to inspect for the HTML-string residual risk (OQ-521-5)",
          f"{len(cells)} cell(s) harvested, {len(orange)} of them highlighted", bool(target))
    if not target:
        return page

    c = target[0]
    cells_on_tab(page, LT260_LIST_URL, "To Process", tries=1)
    shot(page, "safety-cell")
    print(f"CELL innerHTML: {c['html'][:200]}")
    check("the highlighted VIN cell's textContent is still the bare VIN - the markup the "
          "implementation now injects must not leak into the value downstream consumers read "
          "(TC-19)",
          f"textContent = '{c['textContent']}' (innerHTML is "
          f"{'markup' if '<' in c['html'] else 'plain text'})",
          bool(VIN_RE.match(c["textContent"].upper())))

    # The cell must contain no executable node and no inline handler.
    risky = page.evaluate(
        """() => {
             const out = {scripts: 0, handlers: []};
             for (const td of document.querySelectorAll('tbody tr td:first-child')) {
               out.scripts += td.querySelectorAll('script').length;
               for (const el of [td, ...td.querySelectorAll('*')])
                 for (const a of el.attributes || [])
                   if (a.name.startsWith('on')) out.handlers.push(a.name);
             }
             return out;
           }""")
    check("no VIN cell contains a script node or an inline event handler - garage-entered VIN "
          "text flowing into an innerHTML sink must render as text, never execute (TC-20)",
          f"{risky['scripts']} script node(s), inline handlers {risky['handlers'][:5] or 'none'}",
          risky["scripts"] == 0 and not risky["handlers"])

    # A downstream consumer must still receive the raw VIN: route by clicking the cell.
    vin = c["text"]
    try:
        page.get_by_text(vin, exact=True).first.click(timeout=20_000)
        page.wait_for_timeout(6000)
        shot(page, "safety-routed")
        check(f"clicking the highlighted VIN {vin} routes to that case's detail page - the row "
              f"handler still receives the raw VIN, not the markup (TC-19 downstream consumer)",
              f"landed on {page.url}",
              "/details" in page.url or "LT-260" in page.url)
    except Exception as exc:
        shot(page, "safety-route-failed")
        check(f"clicking the highlighted VIN {vin} routes to that case's detail page (TC-19)",
              f"the click did not navigate ({type(exc).__name__}); still on {page.url}", False)

    # Global Search is the other consumer of that cell's value.
    try:
        from src.pages.staff_portal.global_search_page import GlobalSearchPage  # noqa: E402
        gs = GlobalSearchPage(page)
        gs.navigate_to()
        gs.search(vin)
        page.wait_for_timeout(5000)
        shot(page, "safety-global-search")
        body = page.inner_text("body")
        check(f"Global Search on the highlighted VIN {vin} finds the case - the raw VIN, not "
              f"the injected markup, is what the search index and the search box exchange (TC-19)",
              f"the VIN renders {body.count(vin)} time(s) on the results surface",
              body.count(vin) >= 1)
    except Exception as exc:
        check(f"Global Search on the highlighted VIN {vin} finds the case (TC-19)",
              f"the Global Search leg could not run ({type(exc).__name__}: {exc})", False)
    return page


# ───────────────────────────── SC-7 · roles & portal scope ────────────────────────────
def mode_roles(page, pw=None, holder=None):
    cells, ok260 = cells_on_tab(page, LT260_LIST_URL, "To Process")
    shot(page, "roles-admin-lt260")
    check("as N&S Administrator the LT-260 To Process listing is reachable and renders VINs "
          "(the role that is supposed to see the highlight)",
          f"tab reachable={ok260}; {len(cells)} VIN cell(s) rendered", ok260 and bool(cells))

    fpage = ctx_page(pw, holder, state="fiscal-portal.json")
    denied = {}
    for url, form in ((LT260_LIST_URL, "LT-260"), (LT261_LIST_URL, "LT-261")):
        try:
            fpage.goto(url, timeout=60_000)
            settle(fpage)
            fpage.wait_for_timeout(2500)
            fcells = vin_cells(fpage)
            denied[form] = (fpage.url, len(fcells))
        except Exception as exc:
            denied[form] = (f"navigation blocked ({type(exc).__name__})", 0)
    shot(fpage, "roles-fiscal-denied")
    leaked = {f: v for f, v in denied.items() if v[1] > 0}
    check("a Fiscal User cannot reach the LT-260 / LT-261 listings at all - no rows, therefore "
          "no VIN and no highlight is exposed to that role (TC-21)",
          (f"the Fiscal session rendered VIN rows: {leaked}" if leaked
           else f"zero VIN rows for the Fiscal session: {denied}"),
          not leaked)

    ppage = ctx_page(pw, holder, state="public-portal.json")
    try:
        ppage.goto(PUBLIC_URL, timeout=60_000)
        settle(ppage)
        ppage.wait_for_timeout(3000)
        shot(ppage, "roles-public-portal")
        pcells = ppage.evaluate(JS_VIN_CELLS)
        p_orange = [c for c in pcells if c["color"] == ORANGE]
        check("the Public / garage portal is completely unchanged - no VIN is highlighted "
              "there and the garage is given no hint that its case is held (TC-22)",
              (f"{len(p_orange)} orange VIN cell(s) on the public portal: "
               f"{[c['text'] for c in p_orange][:5]}" if p_orange
               else f"zero orange cells across {len(pcells)} public-portal cell(s)"),
              not p_orange)
    except Exception as exc:
        check("the Public / garage portal shows no highlight (TC-22)",
              f"the public-portal leg could not run ({type(exc).__name__}: {exc})", False)
    return page


MODES = {"listing260": mode_listing260, "listing261": mode_listing261, "hold": mode_hold,
         "history": mode_history, "contract": mode_contract, "safety": mode_safety,
         "roles": mode_roles}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=sorted(MODES))
    ap.add_argument("--env", default=os.environ.get("NSM_ENV", "qa"))
    args = ap.parse_args()
    os.environ["NSM_ENV"] = args.env

    clear_stale_shots()
    print(f"[tw-27171126] mode={args.mode} env={args.env} base={BASE_URL}")
    print(f"[tw-27171126] flagged colour {ORANGE} · normal colour {NORMAL}")
    holder = []
    started = time.time()
    page = None
    try:
        with sync_playwright() as pw:
            page = ctx_page(pw, holder)
            try:
                if args.mode == "roles":
                    MODES[args.mode](page, pw=pw, holder=holder)
                else:
                    MODES[args.mode](page)
            finally:
                shot(page, f"final-{args.mode}")
    except Exception as exc:
        # A crash IS a mismatch - print the pair, never a bare traceback.
        check(f"the {args.mode} scenario runs to completion against {args.env} and reports its "
              f"NCNSS-521 verdicts",
              f"the run aborted ({type(exc).__name__}: {exc})", False)
    finally:
        for b in holder:
            try:
                b.close()
            except Exception:
                pass

    passed = sum(1 for c in _checks if c)
    print(f"\nSUMMARY: {passed}/{len(_checks)} checks passed in {time.time() - started:.0f}s")
    sys.exit(0 if _checks and passed == len(_checks) else 1)


if __name__ == "__main__":
    main()
