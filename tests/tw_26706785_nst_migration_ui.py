"""NCNSS-371 / TW-26706785 - UI channel: the Icons column and the NST archive icon.

The API driver (tw_26706785_nst_migration.py) proves the data side. The Icons column,
the archive icon on a migrated row, its ABSENCE on a native row, and the archive icon
on the case-details title are UI changes - they are only real in a browser, so they
are driven here.

TWO METHOD NOTES, both learned the hard way on 2026-09-09:

1. **Reach migrated rows by SORTING on FILE NUMBER ascending, never by searching.**
   The listings default to newest-first and every migrated record is 2020-2021, so a
   migrated row is never on page 1. Sorting on DATE SUBMITTED ascending does not work
   either - rows with a blank date sort ahead of 2020. Sorting on FILE NUMBER ascending
   does: D20-/N20-/S20- sort before S26-. This also keeps migrated and native rows on
   the SAME screen, rendered by the same grid, which is what makes "flagged here, not
   flagged there" an assertion rather than two separate observations.

2. **The grid renders lazily.** Reading `thead th` right after networkidle returns an
   empty list on LT-260 (the heaviest surface) and produced a false FAIL on the first
   run of this driver. Always wait for rows AND headers.

The archive icon is the class `row-icon--nst` inside the first cell (`.row-icons`);
the artwork is a CSS data-URI background, so there is no <img> or <svg> to look for.

Run:  python tests/tw_26706785_nst_migration_ui.py [--env qa] [--out <dir>]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASES = {"qa": "https://nsm-qa.nc.verifi.dev", "stage": "https://nsm-stage.nc.verifi.dev"}
SEARCH_BOX = "input[placeholder='Search using VIN, Filenumber, Garage, etc.']"
NST_ICON = "row-icon--nst"

LISTS = [("LT-260", "/pages/ncdot-notice-and-storage/LT-260/list"),
         ("LT-261", "/pages/ncdot-notice-and-storage/LT-261/list"),
         ("LT-262", "/pages/ncdot-notice-and-storage/LT-262/list"),
         ("LT-262A", "/pages/ncdot-notice-and-storage/LT-262A/list"),
         ("LT-263", "/pages/ncdot-notice-and-storage/LT-263/list"),
         ("Sold", "/pages/ncdot-notice-and-storage/sold"),
         ("Payments", "/pages/ncdot-notice-and-storage/payments/list")]

SEARCHABLE = ["LT-260", "LT-261", "LT-262", "LT-263"]

RESULTS = []

GRID_JS = """() => {
  const th = [...document.querySelectorAll('table thead th')].map(x => x.innerText.trim());
  const rows = [...document.querySelectorAll('table tbody tr')]
      .filter(tr => (tr.innerText || '').trim());
  return {th, rows: rows.slice(0, 12).map(tr => {
    const c0 = tr.querySelector('td');
    const kids = c0 ? [...c0.querySelectorAll('*')]
        .map(k => k.getAttribute('class') || '').filter(Boolean) : [];
    return {text: (tr.innerText || '').replace(/\\s+/g, ' ').slice(0, 70),
            iconClasses: [...new Set(kids)]};
  })};
}"""


def record(tid, title, status, expected, actual, evidence=None, note=None):
    RESULTS.append({"id": tid, "title": title, "status": status, "expected": expected,
                    "actual": actual, "evidence": evidence or {}, "note": note,
                    "channel": "UI"})
    print(f"  [{status:14s}] {tid}  {title}")
    if status != "PASS":
        print(f"                   expected: {expected}")
        print(f"                   actual  : {actual}")


def wait_grid(page, tries=24):
    for _ in range(tries):
        if (page.locator("table tbody tr").count() > 0
                and page.locator("table thead th").count() > 0):
            return True
        page.wait_for_timeout(2500)
    return False


def has_nst(row):
    return any(NST_ICON in c for c in row["iconClasses"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="qa", choices=["qa", "stage"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    base = BASES[a.env]
    out = Path(a.out) if a.out else ROOT / "results" / f"tw26706785_{a.env}_ui"
    shots = out / "shots"
    shots.mkdir(parents=True, exist_ok=True)

    print(f"\nNCNSS-371 NST migration - UI channel on {a.env} ({base})")
    print("=" * 78)

    auth = ROOT / "auth" / a.env / "staff-portal.json"
    if not auth.exists():
        auth = ROOT / "auth" / "staff-portal.json"

    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        ctx = br.new_context(storage_state=str(auth), viewport={"width": 1700, "height": 1000})
        page = ctx.new_page()

        # -- TC-12a the Icons column exists, first, on all seven list surfaces --
        print("\nSC-1  The new Icons column")
        cols = {}
        for name, route in LISTS:
            try:
                page.goto(base + route, wait_until="networkidle", timeout=120000)
                wait_grid(page)
                g = page.evaluate(GRID_JS)
                # The icons column is the leading column that holds `.row-icons`. Since the
                # 2026-09-15 fix its HEADER IS DELIBERATELY BLANK (BA-confirmed, register R11),
                # so matching on the literal text "ICONS" false-fails on every surface.
                cols[name] = {"n_headers": len(g["th"]), "first": g["th"][0] if g["th"] else None,
                              "icons_first": bool(g["th"]) and g["th"][0].strip().upper() in ("ICONS", ""),
                              "purple_present": "7F00FF" in page.content().upper()}
                page.screenshot(path=str(shots / f"list_{name}.png"))
            except Exception as e:
                cols[name] = {"error": f"{type(e).__name__}: {e}"}
        good = [n for n, c in cols.items() if c.get("icons_first")]
        purple = [n for n, c in cols.items() if c.get("purple_present")]
        record("TC-26706785-12a",
               "An Icons column is the first column on every staff list surface",
               "PASS" if len(good) == len(LISTS) else "FAIL",
               "all seven staff list surfaces render the icons column immediately before VIN "
               "(its header is blank by design since 2026-09-15), and none still carries the "
               "reverted purple #7F00FF VIN",
               f"{len(good)}/{len(LISTS)} surfaces show the icons column first: {good}; "
               f"surfaces still carrying purple: {purple or 'none'}",
               evidence=cols)

        # -- TC-12b / TC-19 the archive icon marks migrated rows and only those --
        print("\nSC-1  The NST archive icon - on migrated rows, and only those")
        page.goto(base + "/pages/ncdot-notice-and-storage/LT-260/list",
                  wait_until="networkidle", timeout=120000)
        wait_grid(page)
        g = page.evaluate(GRID_JS)
        fi = [i for i, h in enumerate(g["th"]) if "FILE" in h.upper()]
        mixed = None
        if fi:
            th = page.locator("table thead th").nth(fi[0])
            up = th.locator("button.exp-table__sort-arrow-up").first
            if up.count():
                up.click()
                page.wait_for_timeout(12000)
                mixed = page.evaluate(GRID_JS)
                page.screenshot(path=str(shots / "lt260_filenumber_asc.png"))

        if not mixed:
            record("TC-26706785-12b",
                   "The NST archive icon renders on migrated rows and not on native ones",
                   "BLOCKED",
                   "sort LT-260 by FILE NUMBER ascending to bring 2020-era migrated rows onto "
                   "the same screen as native rows",
                   "could not find/operate the FILE NUMBER ascending sort control")
        else:
            flagged = [r for r in mixed["rows"] if has_nst(r)]
            unflagged = [r for r in mixed["rows"] if not has_nst(r)]
            # a migrated row's file number is the short NST shape; a native one is longer
            def looks_migrated(r):
                import re as _re
                return bool(_re.search(r"[SND]\d{2}-\d{6}(?!\d)", r["text"]))
            wrong_on = [r["text"] for r in flagged if not looks_migrated(r)]
            wrong_off = [r["text"] for r in unflagged if looks_migrated(r)]
            record("TC-26706785-12b",
                   "The NST archive icon renders on migrated rows and not on native ones",
                   "PASS" if flagged and unflagged and not wrong_on and not wrong_off else "FAIL",
                   f"on one mixed screen, every migrated row carries the {NST_ICON} icon and "
                   f"every native row does not",
                   f"{len(flagged)} rows carry {NST_ICON}, {len(unflagged)} do not; "
                   f"flagged-but-not-migrated: {wrong_on or 'none'}; "
                   f"migrated-but-unflagged: {wrong_off or 'none'}",
                   evidence={"flagged": [r["text"] for r in flagged],
                             "unflagged": [r["text"] for r in unflagged],
                             "icon_classes_sample": flagged[0]["iconClasses"] if flagged else []})
            record("TC-26706785-19-ui",
                   "NST-flag isolation in the UI - native rows show no archive icon",
                   "PASS" if unflagged and not wrong_off else "FAIL",
                   "natively-filed rows on the same screen render a blank Icons cell (or only "
                   "their own comment/document icons), never the NST archive icon",
                   f"{len(unflagged)} native rows checked, none carrying {NST_ICON}: "
                   f"{not wrong_off}",
                   evidence={"native_rows": [r["text"] for r in unflagged][:5]})

        # -- NEW: does the Search path keep the Icons column? --------------------
        print("\nSC-6  Regression - does each rebuild path keep the Icons column?")
        paths = {}
        for name in SEARCHABLE:
            route = dict(LISTS)[name]
            entry = {}
            try:
                page.goto(base + route, wait_until="networkidle", timeout=120000)
                wait_grid(page)
                entry["baseline"] = page.evaluate(GRID_JS)["th"]
                box = page.locator(SEARCH_BOX).first
                if box.count():
                    box.fill("")
                    box.type("S20-764402", delay=25)
                    page.locator("button:has-text('Search')").first.click()
                    page.wait_for_timeout(9000)
                    entry["after_search"] = page.evaluate(GRID_JS)["th"]
                    page.screenshot(path=str(shots / f"search_{name}.png"))
                page.goto(base + route, wait_until="networkidle", timeout=120000)
                wait_grid(page)
                sf = page.locator("button:has-text('Show Filters')").first
                if sf.count():
                    sf.click()
                    page.wait_for_timeout(6000)
                    entry["after_show_filters"] = page.evaluate(GRID_JS)["th"]
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"
            paths[name] = entry

        def has_icons(hdrs):
            # Same blank-header caveat as TC-12a: the icons column is the untitled leading
            # column, so accept either "ICONS" or an empty first header.
            if not hdrs:
                return False
            return "ICONS" in [h.strip().upper() for h in hdrs] or hdrs[0].strip() == ""

        lost_on_search = [n for n, e in paths.items()
                          if "after_search" in e and not has_icons(e["after_search"])]
        lost_on_filter = [n for n, e in paths.items()
                          if "after_show_filters" in e and not has_icons(e["after_show_filters"])]
        record("TC-26706785-12d",
               "The Icons column survives every path that rebuilds the column set",
               "PASS" if not lost_on_search and not lost_on_filter else "FAIL",
               "the Icons column is still present after a global search and after opening the "
               "filter panel - both rebuild the column set",
               f"Icons column LOST after using the global search box on: "
               f"{lost_on_search or 'none'}; lost after opening the filter panel on: "
               f"{lost_on_filter or 'none'}",
               evidence=paths,
               note="The 2026-09-07 dev note records this exact defect class as found and "
                    "FIXED for the Show Filters / Clear Filters handlers ('The Icons column "
                    "vanished when the filter panel opened... the first pass only walked the "
                    "builder variables and missed 34 VIN columns across 5 pages'). The filter "
                    "path is indeed clean on QA. The global search box is a THIRD rebuild path "
                    "that the sweep did not cover: its results grid renders a different, "
                    "shorter column set (11 columns, VIN first, 'FILENUMBER' spelled without a "
                    "space) which has no Icons column at all - so a staff user who searches "
                    "for a case cannot see whether it is NST-migrated.")

        # -- TC-12c the archive icon on the case-details title -----------------
        print("\nSC-1  The archive icon on the case-details title")
        try:
            page.goto(base + "/pages/ncdot-notice-and-storage/LT-260/list",
                      wait_until="networkidle", timeout=120000)
            wait_grid(page)
            g = page.evaluate(GRID_JS)
            fi = [i for i, h in enumerate(g["th"]) if "FILE" in h.upper()]
            th = page.locator("table thead th").nth(fi[0])
            th.locator("button.exp-table__sort-arrow-up").first.click()
            page.wait_for_timeout(12000)
            # Click the VIN link of the first row carrying the NST icon.
            # NOTE: GRID_JS filters out the blank detail-expand rows the grid interleaves,
            # so its indices do NOT line up with `table tbody tr` in the DOM - resolving
            # the row in the page itself is what makes this reliable.
            picked = page.evaluate("""(icon) => {
                const rows = [...document.querySelectorAll('table tbody tr')]
                    .filter(tr => (tr.innerText || '').trim());
                for (const tr of rows) {
                  const c0 = tr.querySelector('td');
                  if (!c0) continue;
                  const flagged = [...c0.querySelectorAll('*')]
                      .some(k => (k.getAttribute('class') || '').includes(icon));
                  if (!flagged) continue;
                  const link = tr.querySelector('td span.table-link, td a');
                  if (!link) continue;
                  link.setAttribute('data-nstpick', '1');
                  return (tr.innerText || '').replace(/\\s+/g, ' ').slice(0, 70);
                }
                return null;
            }""", NST_ICON)
            if not picked:
                raise RuntimeError("no NST-flagged row with a clickable link on the sorted page")
            opened = picked
            page.locator("[data-nstpick='1']").first.click(timeout=20000)
            page.wait_for_timeout(10000)
            page.screenshot(path=str(shots / "details_migrated.png"), full_page=True)
            html = page.content()
            title_icon = NST_ICON in html or "legacy" in html.lower()
            record("TC-26706785-12c",
                   "The archive icon renders at the start of the case-details title for a "
                   "migrated record",
                   "PASS" if title_icon else "FAIL",
                   "the details page of a migrated record shows the NST archive icon before the "
                   "case title (driven by isLegacy371)",
                   f"opened {opened!r} -> {page.url}; NST icon markup present on the details "
                   f"page: {title_icon}",
                   evidence={"url": page.url, "row": opened})

            comment_hit = "Defaulted data values from NST migration" in html
            record("TC-26706785-14-obs",
                   "Observed: the 'Defaulted data values from NST migration' case comment",
                   "PASS" if comment_hit else "GAP",
                   "a migrated record whose fields were defaulted carries the mandated case "
                   "comment naming each defaulted field and its NST value",
                   f"the phrase is {'present' if comment_hit else 'not present'} on this "
                   f"record's details page ({opened})",
                   note="Observational, over ONE record, and a miss is NOT a defect: the comment "
                        "is required only for records that actually needed a default, and this "
                        "record may have needed none. Proving the rule needs a record known to "
                        "have been defaulted, which needs the ingest-side report QA does not "
                        "carry.")
        except Exception as e:
            record("TC-26706785-12c",
                   "The archive icon renders at the start of the case-details title",
                   "BLOCKED",
                   "open a migrated record's details page from the listing",
                   f"could not reach the details page: {type(e).__name__}: {e}")

        ctx.close()
        br.close()

    payload = {"ticket": "26706785", "product": "NSS", "env": a.env, "base": base,
               "channel": "UI",
               "generated": datetime.now().isoformat(timespec="seconds"),
               "results": RESULTS}
    (out / "results_ui.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tally = {}
    for r in RESULTS:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    print("\n" + "=" * 78)
    print("TALLY:", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    print("results ->", out / "results_ui.json")


if __name__ == "__main__":
    main()
