"""TW-27171126 / NCNSS-521 — gap coverage for the VIN-highlight test plan.

The main driver (tw_27171126_vin_highlight.py) proves the palette, the scope clause, the
hold and the API contract. It does not reach the list-operation, cross-form and
environment cases of the 35-case plan, and its AC-3 "over-fire" verdict is computed from
LT-260/261 tabs only — a VIN whose prior terminal case lives on LT-262/262A/263 looks
like a false positive to it. Each mode here closes one of those gaps.

    python tests/tw_27171126_vin_highlight_gaps.py --mode overfire    # TC_007, TC_011-013, TC_027
    python tests/tw_27171126_vin_highlight_gaps.py --mode unrelated   # TC_034
    python tests/tw_27171126_vin_highlight_gaps.py --mode detail260   # TC_005, TC_035
    python tests/tw_27171126_vin_highlight_gaps.py --mode listops     # TC_023, TC_024, TC_025
    python tests/tw_27171126_vin_highlight_gaps.py --mode env         # TC_022, TC_030, TC_033
    python tests/tw_27171126_vin_highlight_gaps.py --mode browsers    # TC_032

Same EXPECTED:/ACTUAL: -> MATCH|MISMATCH contract as the main driver.
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

import tests.tw_27171126_vin_highlight as drv  # noqa: E402
from tests.tw_27171126_vin_highlight import (  # noqa: E402
    BASE_URL, BASE_PATH, LT260_LIST_URL, LT261_LIST_URL, ORANGE, NORMAL, VIN_RE,
    check, shot, classify, click_tab, ctx_page, open_listing, settle, vin_cells,
)

# The four VINs the main driver's history mode reported as AC-3 over-fires. Its ground
# truth is the LT-260/261 Rejected/Closed tabs only, so a cross-form rejection reads as a
# false positive — that is exactly what this mode disambiguates.
SUSPECTS = ["6BVSTXY205L7TJ0HF", "RUTHYPUP8EEUFJSKM", "60WT9E201SEFVR7S6",
            "ERUN4HBTE6DAD0R2R"]

OTHER_FORMS = ["LT-262", "LT-262A", "LT-263"]
TERMINAL_RE = re.compile(r"reject|closed", re.I)

# The filter drawer's VIN box (probed live: input[name=vin] inside the Show Filters panel).
JS_SORT_VIN = (
    "(dir) => { const th = [...document.querySelectorAll('thead th')]"
    ".find(e => (e.innerText||'').trim().toUpperCase().startsWith('VIN'));"
    " if (!th) return false;"
    " const b = th.querySelector(dir === 'up' ? '.exp-table__sort-arrow-up'"
    " : '.exp-table__sort-arrow-down');"
    " if (!b) return false; b.click(); return true; }"
)


def form_url(form):
    return f"{BASE_URL}{BASE_PATH}/{form}/list"


def open_filters(page):
    """Reveal the filter drawer. 'Show Filters' TOGGLES, so clicking it when the drawer is
    already open closes it — check for the VIN box first or successive calls flip-flop."""
    box = page.locator("input[name='vin']").first
    try:
        if box.count() and box.is_visible():
            return True
    except Exception:
        pass
    try:
        page.get_by_text("Show Filters", exact=False).first.click(timeout=10_000)
        page.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def filter_by_vin(page, vin):
    """Type `vin` into the listing filter drawer and apply. True when the filter ran."""
    if not open_filters(page):
        return False
    box = page.locator("input[name='vin']").first
    try:
        box.wait_for(state="visible", timeout=10_000)
        box.fill(vin)
    except Exception:
        return False
    for label in ("Apply", "Search", "Filter"):
        try:
            btn = page.get_by_role("button", name=re.compile(rf"^\s*{label}\s*$", re.I)).first
            if btn.count():
                btn.click(timeout=5000)
                page.wait_for_timeout(4000)
                return True
        except Exception:
            continue
    box.press("Enter")
    page.wait_for_timeout(4000)
    return True


# ───────────────────────── TC_007 / TC_011-013 / TC_027 ──────────────────────────
def vin_history(page, vin):
    """Cross-form case history for `vin`: (facet counts, visible 'FORM Status' strings).

    The staff global search is reachable by URL and reports a per-form hit count plus a
    STATUS column of the form "LT-260 Processed" — the only surface that spans every form
    for one VIN. GlobalSearchPage is deliberately not used: its navigate_to()/search()
    both block on a hard networkidle, which this Angular app never reaches.
    """
    page.goto(f"{BASE_URL}{BASE_PATH}/global-search?search={vin}", timeout=60_000)
    settle(page)
    page.wait_for_timeout(5000)
    flat = re.sub(r"\s+", " ", page.inner_text("body"))
    counts = {m.group(1): int(m.group(2))
              for m in re.finditer(r"(LT-26[0-3]A?)\s+(\d+)", flat)}
    rows = page.evaluate(
        "() => [...document.querySelectorAll('tbody tr')].map(r =>"
        " [...r.querySelectorAll('td')].map(c => c.innerText.trim()))")
    statuses = sorted({r[8] for r in rows if len(r) > 8 and r[8]})
    return counts, statuses


def vin_on_tab(page, form, tab, vin):
    """Is `vin` present on `form`'s `tab`? None when the filter could not be trusted."""
    open_listing(page, form_url(form))
    if not click_tab(page, tab):
        return None
    if not filter_by_vin(page, vin):
        return None
    page.wait_for_timeout(2000)
    cells = vin_cells(page)
    others = {c["text"].upper() for c in cells} - {vin.upper()}
    if others:                      # the filter clearly did not apply — do not guess
        print(f"    NOTE: {form}/{tab} filter returned foreign VINs {list(others)[:3]}")
        return None
    return any(c["text"].upper() == vin.upper() for c in cells)


def mode_overfire(page):
    """Are the four 'over-fire' VINs actually backed by a cross-form terminal case?

    The main driver harvests only the LT-260/261 tabs, so an LT-262/262A/263 rejection on
    the same VIN is invisible to it and reads as a false positive. Global search gives the
    per-form hit counts; the terminal tabs of each hit form, filtered to the VIN, give the
    status the search table does not show for other forms.
    """
    verdicts = {}
    for vin in SUSPECTS:
        try:
            counts, statuses = vin_history(page, vin)
        except Exception as exc:
            verdicts[vin] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"  {vin}: HISTORY LOOKUP FAILED — {type(exc).__name__}: {exc}")
            continue
        terminal = sorted({s for s in statuses if TERMINAL_RE.search(s)})
        # Any form the search counts but whose rows the table did not show has to be
        # checked on its own Rejected / Closed tabs.
        unseen = [f for f, n in counts.items()
                  if n and not any(s.startswith(f) for s in statuses)]
        for form in unseen:
            for tab in ("Rejected", "Closed"):
                present = vin_on_tab(page, form, tab, vin)
                if present:
                    terminal.append(f"{form} {tab}")
        verdicts[vin] = {"counts": counts, "visible": statuses,
                         "checked": unseen, "terminal": sorted(set(terminal))}
        print(f"  {vin}: counts={counts} visible={statuses} "
              f"cross-form-checked={unseen} -> terminal={sorted(set(terminal))}")
    shot(page, "overfire-globalsearch")

    justified = {v: d for v, d in verdicts.items() if d.get("terminal")}
    unjustified = {v: d for v, d in verdicts.items() if v not in justified}
    check("each VIN the main driver flagged as an AC-3 'over-fire' is in fact backed by a "
          "Rejected/Closed case on SOME form (LT-260/261/262/262A/263) — i.e. the highlight "
          "is correct cross-form behaviour and not a false positive (TC_011-013, TC_027)",
          (f"{len(justified)}/{len(verdicts)} justified by cross-form history; "
           f"UNJUSTIFIED (would be a real over-fire): "
           f"{ {v: d for v, d in unjustified.items()} }"
           if unjustified else
           f"all {len(justified)} carry a terminal case cross-form: "
           f"{ {v: d['terminal'] for v, d in justified.items()} }"),
          bool(justified) and not unjustified)

    # TC_007 / TC_008: a normal-coloured VIN must have no terminal case anywhere.
    cells, _ = drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=2)
    _, normal, _ = classify(cells)
    wrong, sampled = [], []
    for c in normal[:3]:
        vin = c["text"]
        try:
            counts, statuses = vin_history(page, vin)
        except Exception as exc:
            print(f"  {vin}: history lookup failed ({type(exc).__name__}) — not sampled")
            continue
        sampled.append(vin)
        term = [s for s in statuses if TERMINAL_RE.search(s)]
        print(f"  {vin} (normal): counts={counts} statuses={statuses}")
        if term:
            wrong.append((vin, term))
    shot(page, "overfire-normal-vins")
    check("a VIN rendered in the normal colour on To Process has NO Rejected/Closed case in "
          "its cross-form history — an approved-only / clean VIN is never highlighted "
          "(TC_007, TC_008)",
          (f"{len(wrong)} normal VIN(s) DO have terminal history: {wrong}" if wrong
           else f"none of the {len(sampled)} sampled normal VINs ({sampled}) shows a "
                f"Rejected/Closed status in its cross-form history"),
          bool(sampled) and not wrong)
    return page


# ─────────────────────────────────── TC_034 ──────────────────────────────────────
def mode_unrelated(page):
    """No VIN highlighting may appear on the LT-262 / LT-262A / LT-263 listings at all."""
    leaked = {}
    scanned = {}
    for form in OTHER_FORMS:
        url = form_url(form)
        for tab in ("To Process", "Rejected", "Closed"):
            cells, reachable = drv.cells_on_tab(page, url, tab, tries=2)
            if not reachable:
                print(f"NOTE: {form} '{tab}' not reachable — skipped")
                continue
            scanned[f"{form}/{tab}"] = len(cells)
            orange, _, _ = classify(cells)
            if orange:
                leaked[f"{form}/{tab}"] = [c["text"] for c in orange][:5]
        shot(page, f"unrelated-{form}")
    check("the VIN highlight does not regress onto the unrelated LT-262 / LT-262A / LT-263 "
          "listings — the enhancement is scoped to LT-260 and LT-261 only (TC_034)",
          (f"orange VINs leaked onto {leaked}" if leaked
           else f"zero orange VIN cells across {len(scanned)} tab(s): {scanned}"),
          bool(scanned) and not leaked)
    return page


# ────────────────────────────── TC_005 / TC_035 ──────────────────────────────────
def mode_detail260(page):
    """The LT-260 detail page must carry the same highlight as its listing row, and the
    listing must still be correct after coming back."""
    cells, _ = drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=3)
    orange, normal, _ = classify(cells)
    check("the LT-260 To Process tab offers both a flagged and a clean VIN so the detail "
          "page can be compared in both states (TC_005 precondition)",
          f"{len(orange)} orange / {len(normal)} normal", bool(orange))
    if not orange:
        return page

    before = {c["text"]: c["color"] for c in cells}
    for label, group, want in (("flagged", orange, ORANGE), ("clean", normal, NORMAL)):
        if not group:
            print(f"NOTE: no {label} VIN on LT-260 To Process — detail check skipped")
            continue
        vin = group[0]["text"]
        drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=2)
        try:
            page.get_by_text(vin, exact=True).first.click(timeout=20_000)
            page.wait_for_timeout(6000)
            settle(page)
        except Exception as exc:
            shot(page, f"detail260-{label}-nav-failed")
            check(f"the {label} LT-260 row for VIN {vin} opens its detail page",
                  f"the row click did not navigate ({type(exc).__name__}); on {page.url}", False)
            continue
        shot(page, f"detail260-{label}")
        colours = page.evaluate(
            """(vin) => [...document.querySelectorAll('*')]
                 .filter(e => e.children.length === 0 &&
                              (e.innerText || '').trim().toUpperCase() === vin)
                 .map(e => getComputedStyle(e).color)""", vin.upper())
        check(f"on the LT-260 detail page the VIN field of the {label} case {vin} renders "
              f"{want} — the detail page reflects the listing highlight (TC_005)",
              (f"the VIN element(s) compute to {sorted(set(colours))}" if colours
               else f"the VIN {vin} was not found as a leaf element on {page.url}"),
              bool(colours) and want in colours)

    # TC_035 — returning to the list leaves the highlighting unchanged.
    after_cells, _ = drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=3)
    after = {c["text"]: c["color"] for c in after_cells}
    shot(page, "detail260-back-to-list")
    common = set(before) & set(after)
    drifted = [v for v in common if before[v] != after[v]]
    check("after opening a detail page and returning, the listing highlights are identical — "
          "the two surfaces stay consistent (TC_035)",
          (f"{len(drifted)} VIN(s) changed colour: {drifted[:5]}" if drifted
           else f"all {len(common)} VINs kept their colour across the round trip"),
          bool(common) and not drifted)
    return page


# ────────────────────────── TC_023 / TC_024 / TC_025 ─────────────────────────────
def mode_listops(page):
    baseline_cells, _ = drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=3)
    baseline = {c["text"]: c["color"] for c in baseline_cells}
    orange, _, _ = classify(baseline_cells)
    check("a flagged VIN is present on LT-260 To Process to drive the search / sort / "
          "pagination cases (TC_023-025 precondition)",
          f"{len(orange)} orange of {len(baseline_cells)} rows", bool(orange))
    if not orange:
        return page
    target = orange[0]["text"]

    # TC_023 — filter the listing down to the flagged VIN.
    drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=1)
    ran = filter_by_vin(page, target)
    found = [c for c in vin_cells(page) if c["text"].upper() == target.upper()]
    shot(page, "listops-search")
    check(f"searching the LT-260 To Process listing for the flagged VIN {target} returns it "
          f"and it is STILL highlighted {ORANGE} — search does not drop the flag (TC_023)",
          (f"filter applied={ran}; {len(found)} matching row(s), colour(s) "
           f"{sorted({c['color'] for c in found})}" if found
           else f"filter applied={ran}; the VIN did not come back in the filtered result"),
          bool(found) and all(c["color"] == ORANGE for c in found))

    # TC_024 — sorting must not move the highlight to the wrong rows.
    drifted_sort = {}
    for direction in ("up", "down"):
        drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=2)
        if not page.evaluate(JS_SORT_VIN, direction):
            print(f"NOTE: no VIN sort-{direction} control found — skipped")
            continue
        page.wait_for_timeout(5000)
        for c in vin_cells(page):
            if c["text"] in baseline and baseline[c["text"]] != c["color"]:
                drifted_sort[c["text"]] = (baseline[c["text"]], c["color"])
    shot(page, "listops-sorted")
    check("sorting the listing by VIN keeps every VIN's colour bound to its own row — the "
          "highlight follows the data, not the row index (TC_024)",
          (f"{len(drifted_sort)} VIN(s) changed colour after sorting: "
           f"{list(drifted_sort.items())[:5]}" if drifted_sort
           else "no VIN seen both before and after the sort changed colour"),
          not drifted_sort)

    # TC_025 — page 2+ must render the same two-colour palette.
    drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=2)
    pages_seen, bad_pages, orange_seen = 1, {}, len(orange)
    while pages_seen < 3:
        if not page.evaluate(drv.JS_NEXT_PAGE):
            break
        page.wait_for_timeout(5000)
        pages_seen += 1
        cells = vin_cells(page)
        o, n, other = classify(cells)
        orange_seen += len(o)
        if other:
            bad_pages[pages_seen] = sorted({c["color"] for c in other})
    shot(page, "listops-page-n")
    check("paging through the To Process listing keeps rendering the specified palette on "
          "every page — highlighting is not confined to page 1 (TC_025)",
          (f"unexpected colours on page(s) {bad_pages}" if bad_pages
           else f"{pages_seen} page(s) traversed, {orange_seen} orange row(s) seen in total, "
                f"no third colour on any page"),
          pages_seen > 1 and not bad_pages)
    return page


# ───────────────────────── TC_022 / TC_030 / TC_033 ──────────────────────────────
def mode_env(page, pw=None, holder=None):
    # TC_030 — how long the flagged listing takes to become readable.
    started = time.time()
    cells, _ = drv.cells_on_tab(page, LT260_LIST_URL, "To Process", tries=3)
    elapsed = time.time() - started
    orange, _, _ = classify(cells)
    shot(page, "env-perf")
    check("the LT-260 To Process listing loads and paints its highlights within an "
          "acceptable time on a populated environment (TC_030, threshold 30s end-to-end "
          "including the tab click and Angular's deferred row render)",
          f"{len(cells)} rows ({len(orange)} highlighted) readable after {elapsed:.1f}s",
          elapsed < 30)

    # TC_033 — the highlight must survive a responsive re-layout.
    drifted = {}
    before = {c["text"]: c["color"] for c in cells}
    for w, h in ((1280, 720), (1024, 768), (768, 1024), (390, 844)):
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(2500)
        for c in vin_cells(page):
            if c["text"] in before and before[c["text"]] != c["color"]:
                drifted[f"{w}x{h}:{c['text']}"] = (before[c["text"]], c["color"])
        shot(page, f"env-responsive-{w}x{h}")
    page.set_viewport_size({"width": 1280, "height": 720})
    check("the VIN highlight stays applied and correctly coloured as the viewport is resized "
          "down to a mobile width — no responsive breakpoint drops the styling (TC_033)",
          (f"colour changed at {list(drifted)[:5]}" if drifted
           else "colours identical at 1280x720, 1024x768, 768x1024 and 390x844"),
          not drifted)

    # TC_022 — a brand-new session (real credential login, no stored state) sees the same
    # highlighting: it is persisted server-side, not a client-session artefact.
    from src.helpers.login_helper import login_to_staff_portal  # noqa: E402
    browser = pw.chromium.launch(headless=True)
    holder.append(browser)
    fresh = browser.new_context(timezone_id="America/New_York").new_page()
    fresh.set_default_timeout(30_000)
    try:
        login_to_staff_portal(fresh)
        fresh_cells, _ = drv.cells_on_tab(fresh, LT260_LIST_URL, "To Process", tries=3)
        shot(fresh, "env-fresh-login")
        f_map = {c["text"]: c["color"] for c in fresh_cells}
        common = set(before) & set(f_map)
        mismatched = [v for v in common if before[v] != f_map[v]]
        f_orange, _, _ = classify(fresh_cells)
        check("after a full logout / fresh credential login the same VINs are still "
              "highlighted — the flag is server-derived and survives the session (TC_022)",
              (f"{len(mismatched)} VIN(s) differ between sessions: {mismatched[:5]}"
               if mismatched else
               f"{len(common)} VIN(s) common to both sessions, all identical; "
               f"{len(f_orange)} highlighted in the fresh session"),
              bool(common) and not mismatched)
    except Exception as exc:
        shot(fresh, "env-fresh-login-failed")
        check("after a full logout / fresh credential login the highlight persists (TC_022)",
              f"the fresh-login leg could not run ({type(exc).__name__}: {exc})", False)
    return page


# ─────────────────────────────────── TC_032 ──────────────────────────────────────
def mode_browsers(page, pw=None, holder=None):
    """Chrome / Edge share Chromium; Firefox is the meaningful second engine here."""
    results = {}
    for name in ("chromium", "firefox", "webkit"):
        try:
            browser = getattr(pw, name).launch(headless=True)
            holder.append(browser)
            ctx = browser.new_context(
                storage_state=str(E2E_ROOT / "auth" / os.environ["NSM_ENV"]
                                  / "staff-portal.json"),
                timezone_id="America/New_York")
            bp = ctx.new_page()
            bp.set_default_timeout(45_000)
            cells, _ = drv.cells_on_tab(bp, LT260_LIST_URL, "To Process", tries=3)
            o, n, other = classify(cells)
            results[name] = {"rows": len(cells), "orange": sorted(c["text"] for c in o),
                             "other_colours": sorted({c["color"] for c in other})}
            shot(bp, f"browser-{name}")
        except Exception as exc:
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
        print(f"  {name}: {results[name]}")

    ok = {k: v for k, v in results.items() if "error" not in v and v["rows"]}
    sets = {k: tuple(v["orange"]) for k, v in ok.items()}
    consistent = len(set(sets.values())) <= 1
    palette_ok = all(not v["other_colours"] for v in ok.values())
    check("the same VINs are highlighted, in the same palette, on every rendering engine — "
          "Chromium (Chrome/Edge), Firefox and WebKit (TC_032)",
          (f"engines that rendered: {list(ok)}; highlighted sets "
           f"{ {k: len(v) for k, v in sets.items()} }; "
           f"{'identical' if consistent else 'DIVERGENT: ' + str(sets)}; "
           f"unexpected colours present={not palette_ok}; "
           f"failures={ {k: v['error'] for k, v in results.items() if 'error' in v} }"),
          len(ok) >= 2 and consistent and palette_ok)
    return page


MODES = {"overfire": mode_overfire, "unrelated": mode_unrelated, "detail260": mode_detail260,
         "listops": mode_listops, "env": mode_env, "browsers": mode_browsers}
NEEDS_PW = {"env", "browsers"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=sorted(MODES))
    ap.add_argument("--env", default=os.environ.get("NSM_ENV", "qa"))
    args = ap.parse_args()
    os.environ["NSM_ENV"] = args.env

    drv.clear_stale_shots()
    print(f"[tw-27171126-gaps] mode={args.mode} env={args.env} base={BASE_URL}")
    holder = []
    started = time.time()
    page = None
    try:
        with sync_playwright() as pw:
            page = ctx_page(pw, holder)
            try:
                if args.mode in NEEDS_PW:
                    MODES[args.mode](page, pw=pw, holder=holder)
                else:
                    MODES[args.mode](page)
            finally:
                shot(page, f"final-{args.mode}")
    except Exception as exc:
        check(f"the {args.mode} gap scenario runs to completion against {args.env}",
              f"the run aborted ({type(exc).__name__}: {exc})", False)
    finally:
        for b in holder:
            try:
                b.close()
            except Exception:
                pass

    passed = sum(1 for c in drv._checks if c)
    print(f"\nSUMMARY: {passed}/{len(drv._checks)} checks passed in {time.time() - started:.0f}s")
    sys.exit(0 if drv._checks and passed == len(drv._checks) else 1)


if __name__ == "__main__":
    main()
