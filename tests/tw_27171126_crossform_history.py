"""Decisive AC-3 check: for each disputed VIN, is there a Rejected/Closed case on ANY form?

Global search validated as a status source (it shows 'LT-260 Rejected' / 'LT-260 Closed'),
but it exposes no LT-262A facet and only tabulates LT-260 rows — so a 262A rejection is
invisible to it. This walks every form's terminal tabs with the VIN filter applied, which
is the same evidence a tester would gather by hand.
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("NSM_ENV", "qa")
E2E_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(E2E_ROOT))
os.chdir(E2E_ROOT)

from playwright.sync_api import sync_playwright  # noqa: E402
from tests.tw_27171126_vin_highlight import ctx_page, click_tab, open_listing, vin_cells  # noqa: E402
from tests.tw_27171126_vin_highlight_gaps import filter_by_vin, form_url  # noqa: E402

# The QA disputed set, kept as the default so the original SC-8 invocation still reproduces.
# The last one is a known-good control (LT-260 Rejected). Any other environment has different
# VINs, so they are accepted as positional arguments:
#     python tests/tw_27171126_crossform_history.py VIN [VIN ...]
QA_DISPUTED = ["6BVSTXY205L7TJ0HF", "RUTHYPUP8EEUFJSKM", "60WT9E201SEFVR7S6",
               "ERUN4HBTE6DAD0R2R", "RUTHE5WYKB6AV7JSU"]
VINS = [v.strip().upper() for v in sys.argv[1:] if v.strip()] or QA_DISPUTED
FORMS = ["LT-260", "LT-261", "LT-262", "LT-262A", "LT-263"]
TABS = ["Rejected", "Closed"]


def main():
    holder = []
    results = {v: [] for v in VINS}
    with sync_playwright() as pw:
        page = ctx_page(pw, holder)
        for form in FORMS:
            for tab in TABS:
                open_listing(page, form_url(form))
                if not click_tab(page, tab):
                    print(f"{form}/{tab}: TAB NOT REACHABLE")
                    continue
                for vin in VINS:
                    try:
                        if not filter_by_vin(page, vin):
                            print(f"{form}/{tab} {vin}: FILTER FAILED")
                            continue
                        page.wait_for_timeout(1500)
                        cells = vin_cells(page)
                        hit = [c["text"] for c in cells if c["text"].upper() == vin.upper()]
                        foreign = {c["text"].upper() for c in cells} - {vin.upper()}
                        if foreign:
                            print(f"{form}/{tab} {vin}: UNTRUSTED (foreign rows "
                                  f"{list(foreign)[:2]})")
                            continue
                        if hit:
                            results[vin].append(f"{form} {tab}")
                            print(f"{form}/{tab} {vin}: PRESENT  <<<")
                    except Exception as exc:
                        print(f"{form}/{tab} {vin}: ERROR {type(exc).__name__}: {exc}")
                # reopen to clear the filter for the next tab
        print("\n=== TERMINAL HISTORY PER VIN ===")
        for v in VINS:
            print(f"  {v}: {results[v] or 'NONE FOUND'}")
        for b in holder:
            b.close()


main()
