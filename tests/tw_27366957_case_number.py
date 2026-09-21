"""TW-27366957 — "Duplicate case numbers for LT-261" verification driver.

Standalone (non-pytest) Playwright driver used by the nsm-lt261-case-number skill and
by ExpertlyTestBuddy/runTestPlan. Each --mode maps to one scenario of the ticket's test
plan and prints the mandatory EXPECTED:/ACTUAL: -> MATCH|MISMATCH pairs that
runTestPlan's report parser scrapes.

    python tests/tw_27366957_case_number.py --mode population   # SC-2
    python tests/tw_27366957_case_number.py --mode mint         # SC-1
    python tests/tw_27366957_case_number.py --mode search       # SC-3
    python tests/tw_27366957_case_number.py --mode stolen       # SC-4

Screenshots land in skills/nsm-lt261-case-number/screenshots/ (runTestPlan contract:
`glob:screenshots/*.png`), numbered NN_ in execution order so the report can name the
failing step. Stale error shots are cleared at the start of every invocation — the
shared-screenshots-dir hazard documented in runTestPlan/SKILL.md.
"""

import argparse
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
from src.helpers.data_helper import generate_vin  # noqa: E402

BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
LT261_LIST_URL = BASE_URL + "/pages/ncdot-notice-and-storage/LT-261/list"
DASHBOARD_URL = BASE_URL + "/pages/ncdot-notice-and-storage/dashboard"

SHOTS = E2E_ROOT.parent / "skills" / "nsm-lt261-case-number" / "screenshots"

# The LT-261 case-number mask under test: one letter, 2-digit year prefix, 6 digits.
CASE_NUM_RE = re.compile(r"^[A-Z]\d{2}-\d{6}$")
ANY_CASE_NUM_RE = re.compile(r"\b[A-Z]\d{2}-\d{4,8}\b")

FILE_NUMBER_COL = 1          # VIN | FILE NUMBER | DATE SUBMITTED | ...
HARVEST_TABS = ["Processed", "Stolen", "Rejected", "Closed", "To Process"]

JS_TAB_CLICK = (
    "(name) => { const t = [...document.querySelectorAll('[role=tab]')]"
    ".find(e => e.innerText.trim() === name); if (t) { t.click(); return true; }"
    " return false; }"
)
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
    except Exception as exc:                                  # pragma: no cover
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


def staff_page(pw, browser_holder):
    browser = pw.chromium.launch(headless=True)
    browser_holder.append(browser)
    ctx = browser.new_context(
        storage_state=str(E2E_ROOT / "auth" / os.environ["NSM_ENV"] / "staff-portal.json"),
        timezone_id="America/New_York",
    )
    page = ctx.new_page()
    page.set_default_timeout(30_000)
    return page


def settle(page, timeout=25_000):
    """networkidle is best-effort on this Angular app — it polls in the background, so a
    hard wait_for_load_state() times out intermittently and would abort the whole scenario
    (observed live 2026-08-03). Never let it be the thing that fails a run."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
    except Exception:
        page.wait_for_timeout(3000)


def open_listing(page):
    page.goto(LT261_LIST_URL, timeout=60_000)
    settle(page)
    # The Angular tab strip renders after networkidle — waiting a fixed 4s was confirmed
    # too short on QA (every tab click returned "not present"). Wait for the strip itself.
    try:
        page.wait_for_selector("[role=tab]", timeout=30_000)
    except Exception:
        pass
    page.wait_for_timeout(3000)


def harvest_tab(page, tab, max_pages=5):
    """Return every FILE NUMBER cell rendered on `tab` (following its paginator)."""
    for _ in range(6):
        if page.evaluate(JS_TAB_CLICK, tab):
            break
        page.wait_for_timeout(2500)
    else:
        return None
    page.wait_for_timeout(5000)
    nums, pages_read = [], 0
    while pages_read < max_pages:
        rows = page.eval_on_selector_all("tbody tr", JS_ROWS)
        for r in rows:
            if len(r) > FILE_NUMBER_COL and r[FILE_NUMBER_COL]:
                nums.append(r[FILE_NUMBER_COL])
        pages_read += 1
        if not page.evaluate(JS_NEXT_PAGE):
            break
        page.wait_for_timeout(3500)
    return nums


def numeric(n):
    try:
        return int(n.split("-", 1)[1])
    except (IndexError, ValueError):
        return -1


# ────────────────────────────── SC-2 · population ──────────────────────────────
def mode_population(page):
    open_listing(page)
    shot(page, "lt261-listing")
    all_nums, per_tab = [], {}
    for tab in HARVEST_TABS:
        nums = harvest_tab(page, tab)
        if nums is None:
            print(f"NOTE: tab '{tab}' not present on this build — skipped")
            continue
        per_tab[tab] = len(nums)
        all_nums.extend(nums)
    shot(page, "lt261-population-harvested")

    print(f"HARVESTED: {len(all_nums)} file numbers across {per_tab}")
    check("at least one LT-261 case number is readable from the Staff listing",
          f"{len(all_nums)} file numbers harvested from tabs {list(per_tab)}",
          len(all_nums) > 0)

    malformed = sorted({n for n in all_nums if not CASE_NUM_RE.match(n)})
    check("every LT-261 case number matches the D-format mask ^[A-Z]{1}[0-9]{2}-[0-9]{6}$",
          (f"{len(all_nums) - len(malformed)}/{len(all_nums)} well-formed"
           + (f"; malformed: {malformed[:10]}" if malformed else "; none malformed")),
          not malformed)

    dupes = sorted({n for n in all_nums if all_nums.count(n) > 1})
    check("no LT-261 case number repeats anywhere in the harvested population",
          (f"{len(set(all_nums))} distinct values in {len(all_nums)} rows"
           + (f"; DUPLICATES: {dupes[:10]}" if dupes else "; zero duplicates")),
          not dupes)

    vals = [numeric(n) for n in all_nums if numeric(n) > 0]
    if vals:
        lo, hi = min(vals), max(vals)
        print(f"BAND: observed numeric band {lo}-{hi} across {len(vals)} numbers "
              f"(prefixes: {sorted({n.split('-')[0] for n in all_nums})})")
        # The known deferred collision (OQ-TW-2 / TC-14): the re-started sequence issues
        # low numbers while a legacy band already occupies higher ground under the same
        # prefix. Report the gap rather than asserting it away.
        print(f"NOTE: newest issued number is {hi}; a legacy band above the live sequence "
              f"is the deferred-collision class tracked as TC-27366957-14.")
    return page


# ──────────────────────────────── SC-1 · mint ─────────────────────────────────
def mode_mint(page, want=2, budget_s=150):
    from tests.test_e2e_004_sheriff_inspector_lt261 import create_lt261  # noqa: E402

    open_listing(page)
    before = harvest_tab(page, "Processed") or []
    before_max = max([numeric(n) for n in before] or [0])
    print(f"BASELINE: {len(before)} existing numbers on Processed, highest = {before_max}")
    shot(page, "baseline-listing")

    minted, started = [], time.time()
    for i in range(want):
        if i and time.time() - started > budget_s:
            print(f"NOTE: time budget ({budget_s}s) reached after {i} mint(s) — stopping "
                  f"rather than overrunning the run. Reported coverage is {i} of {want}.")
            break
        vin = generate_vin()
        print(f"MINTING #{i + 1} with VIN {vin} …")
        create_lt261(page, vin, f"CaseNum Officer {i + 1}", "E-Stop", stolen=False)
        page.wait_for_timeout(4000)
        shot(page, f"submitted-{i + 1}")
        open_listing(page)
        rows = []
        for _ in range(6):
            page.evaluate(JS_TAB_CLICK, "Processed")
            page.wait_for_timeout(4000)
            rows = page.eval_on_selector_all("tbody tr", JS_ROWS)
            hit = [r for r in rows if r and r[0].upper() == vin.upper()]
            if hit:
                break
        hit = [r for r in rows if r and r[0].upper() == vin.upper()]
        num = hit[0][FILE_NUMBER_COL] if hit and len(hit[0]) > FILE_NUMBER_COL else ""
        shot(page, f"minted-number-{i + 1}")
        check(f"the freshly submitted LT-261 (VIN {vin}) appears in the listing carrying a "
              f"D-format case number",
              f"case number read back = '{num or '(row not found)'}'",
              bool(num) and bool(CASE_NUM_RE.match(num)))
        if num:
            minted.append(num)

    check("at least one LT-261 was minted this run",
          f"minted {len(minted)}: {minted}", bool(minted))

    if minted:
        check("every freshly minted case number is unique against the pre-existing population",
              f"minted {minted} vs {len(before)} pre-existing; collisions = "
              f"{sorted(set(minted) & set(before)) or 'none'}",
              not (set(minted) & set(before)))
        check("each freshly minted number is strictly greater than the previously highest "
              "issued number (monotonic sequence, nothing re-issued)",
              f"previous max {before_max}; minted {[numeric(n) for n in minted]}",
              all(numeric(n) > before_max for n in minted))
    if len(minted) > 1:
        vals = [numeric(n) for n in minted]
        check("back-to-back LT-261 creations produce distinct, contiguous numbers "
              "(each exactly one greater than the last)",
              f"minted values {vals}; deltas {[b - a for a, b in zip(vals, vals[1:])]}",
              len(set(vals)) == len(vals) and all(b - a == 1 for a, b in zip(vals, vals[1:])))
    return page


# ─────────────────────────────── SC-3 · search ────────────────────────────────
def mode_search(page):
    open_listing(page)
    nums = harvest_tab(page, "Processed") or []
    target = next((n for n in nums if CASE_NUM_RE.match(n)), None)
    check("a D-format LT-261 case number is available to search on",
          f"picked '{target}' from {len(nums)} listing rows", bool(target))
    if not target:
        return page

    # Use the product's own page object — a bare `input[type=text]` resolves to a hidden
    # Angular control on this build (confirmed live 2026-08-03: Locator.fill timed out on
    # a non-editable mat-input), while GlobalSearchPage carries the placeholder/aria
    # selectors plus the debounce + JS-dispatch fallbacks this search box needs.
    from src.pages.staff_portal.global_search_page import GlobalSearchPage  # noqa: E402

    gs = GlobalSearchPage(page)
    gs.navigate_to()
    gs.search(target)
    page.wait_for_timeout(5000)
    shot(page, "global-search-results")

    body = page.inner_text("body")
    hits = body.count(target)
    check(f"Global Search on the case number {target} returns that case (exactly one "
          f"LT-261 record resolves to it)",
          f"the number renders {hits} time(s) in the results surface", hits >= 1)

    # Global Search renders its hits per form-type tab (mat-card / tab-scoped tables), so a
    # bare `tbody tr` scrape reads 0 rows even when the hit is on screen — confirmed live
    # 2026-08-03. Count occurrences on the results surface instead: exactly one is the
    # uniqueness property under test.
    check(f"exactly one record on the Global Search results surface carries the file "
          f"number {target} (the number is a unique discriminator, not a shared key)",
          f"the number occurs {hits} time(s) across the rendered results", hits == 1)

    if hits:
        try:
            page.get_by_text(target, exact=True).first.click(timeout=15_000)
            page.wait_for_timeout(7000)
            shot(page, "routed-to-details")
            check("clicking the result routes to the LT-261 details page for that case",
                  f"landed on {page.url}", "LT-261" in page.url)
        except Exception as exc:
            shot(page, "route-failed")
            check("clicking the result routes to the LT-261 details page for that case",
                  f"row click did not navigate ({type(exc).__name__}: {exc}); still on {page.url}",
                  False)
    return page


# ─────────────────────────────── SC-4 · stolen ────────────────────────────────
def mode_stolen(page):
    from tests.test_e2e_004_sheriff_inspector_lt261 import create_lt261  # noqa: E402
    from src.pages.staff_portal.lt261_page import Lt261Page  # noqa: E402

    open_listing(page)
    before = set(harvest_tab(page, "Processed") or []) | set(harvest_tab(page, "Stolen") or [])
    vin = generate_vin()
    print(f"MINTING stolen E-Stop with VIN {vin} …")
    lt261 = create_lt261(page, vin, "CaseNum Stolen Officer", "E-Stop", stolen=True)
    page.wait_for_timeout(4000)
    shot(page, "stolen-submitted")

    try:
        lt261.expect_no_lt265_issue_popup()
        check("a Stolen = Yes E-Stop is held MANUAL — no LT-265/265A auto-issue popup fires",
              "no LT-265 auto-issue popup appeared", True)
    except Exception as exc:
        check("a Stolen = Yes E-Stop is held MANUAL — no LT-265/265A auto-issue popup fires",
              f"assertion failed ({type(exc).__name__}: {exc})", False)

    open_listing(page)
    num, rows = "", []
    for _ in range(6):
        page.evaluate(JS_TAB_CLICK, "Stolen")
        page.wait_for_timeout(4000)
        rows = page.eval_on_selector_all("tbody tr", JS_ROWS)
        hit = [r for r in rows if r and r[0].upper() == vin.upper()]
        if hit:
            num = hit[0][FILE_NUMBER_COL] if len(hit[0]) > FILE_NUMBER_COL else ""
            break
    shot(page, "stolen-listing")
    check(f"the Stolen = Yes LT-261 (VIN {vin}) is present in the Stolen listing with its "
          "own well-formed D-format case number",
          f"case number read back = '{num or '(row not found)'}'",
          bool(num) and bool(CASE_NUM_RE.match(num)))
    if num:
        check("that number does not collide with any pre-existing LT-261 case number",
              f"'{num}' vs {len(before)} pre-existing numbers; collision = "
              f"{'YES' if num in before else 'none'}",
              num not in before)
    return page


MODES = {"population": mode_population, "mint": mode_mint,
         "search": mode_search, "stolen": mode_stolen}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=sorted(MODES))
    ap.add_argument("--env", default=os.environ.get("NSM_ENV", "qa"))
    args = ap.parse_args()
    os.environ["NSM_ENV"] = args.env

    clear_stale_shots()
    print(f"[tw-27366957] mode={args.mode} env={args.env} base={BASE_URL}")
    holder = []
    started = time.time()
    try:
        with sync_playwright() as pw:
            page = staff_page(pw, holder)
            try:
                MODES[args.mode](page)
            finally:
                shot(page, f"final-{args.mode}")
    except Exception as exc:
        # A crash IS a mismatch — print the pair, never a bare traceback.
        check(f"the {args.mode} scenario runs to completion against QA and reports its "
              "case-number verdicts",
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
