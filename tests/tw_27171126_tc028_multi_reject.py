"""TC_028 — "Verify highlight after multiple historical rejections".

The QA population carries at most ONE terminal case per VIN, so this case could not be
observed against existing data (see VIN_HIGHLIGHT_QA_REPORT.md). This driver seeds the
condition instead: one VIN, submitted and rejected TWICE, then submitted a third time.

    python tests/tw_27171126_tc028_multi_reject.py --env qa
    python tests/tw_27171126_tc028_multi_reject.py --env qa --vin RUTHXXXXXXXXXXXXX  # resume

What it asserts on the third submission:
  * the VIN is highlighted orange on LT-260 To Process (the flag still fires once a VIN
    has accumulated more than one rejection — it does not toggle or reset);
  * it appears EXACTLY ONCE on To Process. This is the real risk in "multiple history":
    hasPriorRejectedLT260 is computed by joining the case history, and a join that fans
    out returns one listing row per prior rejection instead of one per open case.
  * the Rejected tab really does hold both earlier cases, so the precondition is proved
    rather than assumed.
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
from src.config.test_data import (  # noqa: E402
    APPROX_VEHICLE_VALUE, REJECTION_REASONS, STORAGE_LOCATION_NAME,
)
from src.helpers.data_helper import (  # noqa: E402
    generate_address, generate_license_plate, generate_person, generate_vin,
    past_date, random_vehicle,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage  # noqa: E402
from src.pages.public_portal.lt260_form_page import Lt260FormPage  # noqa: E402
from src.pages.staff_portal.dashboard_page import StaffDashboardPage  # noqa: E402
from src.pages.staff_portal.form_processing_page import FormProcessingPage  # noqa: E402
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage  # noqa: E402

import tests.tw_27171126_vin_highlight as drv  # noqa: E402
from tests.tw_27171126_vin_highlight import (  # noqa: E402
    LT260_LIST_URL, NORMAL, ORANGE, check, classify, shot, vin_cells,
)
from tests.tw_27171126_vin_highlight_gaps import filter_by_vin  # noqa: E402

# Pinned rather than random_vehicle(): this driver submits the SAME vehicle three times,
# and a reproducible make/body keeps a seeding failure diagnosable.
VEHICLE = {"make": "Honda", "year": "2020", "body": "SUV", "model": "CR-V",
           "color": "Black"}
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

PP_URL = ENV.PUBLIC_PORTAL_URL
SP_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard",
                ENV.STAFF_PORTAL_URL)


def dismiss_overlays(page):
    """Close any open mat-autocomplete / mat-select panel.

    A half-completed vehicle block leaves its option panel open, and the
    cdk-overlay-backdrop then swallows every later click on the form — which is how a
    single missed Make option cascades into a timeout on 'Date Vehicle Left'.
    """
    for _ in range(3):
        if not page.locator(".cdk-overlay-backdrop.cdk-overlay-dark-backdrop").count():
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
    try:
        page.evaluate("""() => document.querySelectorAll(
            '.cdk-overlay-backdrop').forEach(b => b.remove())""")
    except Exception:
        pass


def fill_vehicle_block(page, lt260, details):
    """Fill Make/Body/Year/Model/Colour, tolerating an already-populated block.

    Delegates to the page object. On a resubmission the VIN lookup pre-fills the vehicle
    block and the Make autocomplete offers nothing, which is a legitimate no-op here —
    fill_vehicle_details() raises in that case (correctly, since other callers want to
    know), so this driver swallows it. Since the page object now closes its own option
    panel on failure, a raise no longer leaves a backdrop blocking the rest of the form.
    """
    try:
        lt260.fill_vehicle_details(details)
    except Exception as exc:
        print(f"    NOTE: vehicle block not re-filled ({type(exc).__name__}: "
              f"{str(exc).splitlines()[0][:140]})")
    dismiss_overlays(page)


def ctx_page(pw, holder, state):
    browser = pw.chromium.launch(headless=True)
    holder.append(browser)
    ctx = browser.new_context(
        storage_state=str(E2E_ROOT / "auth" / os.environ["NSM_ENV"] / state),
        timezone_id="America/New_York")
    page = ctx.new_page()
    page.set_default_timeout(45_000)
    return page


def submit_lt260(page, vin, attempt):
    """Submit one LT-260 on `vin` from the public portal."""
    page.goto(PP_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=45_000)
    drv.settle(page)

    dashboard = PublicDashboardPage(page)
    dashboard.select_business()
    dashboard.click_start_here()

    lt260 = Lt260FormPage(page)
    lt260.enter_vin(vin)
    lt260.click_vin_lookup()
    # After the first submission the VIN lookup pre-fills the vehicle block; re-filling is
    # harmless, and every step closes its own overlay so a miss cannot block the rest.
    fill_vehicle_block(page, lt260, VEHICLE)
    lt260.fill_date_vehicle_left(past_date(30))
    lt260.fill_license_plate(PLATE)
    lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
    dismiss_overlays(page)
    lt260.select_reason_storage()
    lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
    lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
    lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
    shot(page, f"tc028-preSubmit{attempt}")
    lt260.submit()
    page.wait_for_timeout(5000)
    shot(page, f"tc028-submit{attempt}")
    print(f"  submitted LT-260 #{attempt} for {vin} — now at {page.url}")


def reject_lt260(page, vin, attempt):
    """Staff-reject the open LT-260 for `vin`."""
    page.goto(SP_URL, timeout=60_000)
    drv.settle(page)

    StaffDashboardPage(page).navigate_to_lt260_listing()
    listing = Lt260ListingPage(page)
    listing.click_to_process_tab()
    listing.search_by_vin(vin)
    listing.select_application(0)
    FormProcessingPage(page).expect_detail_page_visible()
    listing.reject_application(REJECTION_REASONS)
    page.wait_for_timeout(4000)
    shot(page, f"tc028-reject{attempt}")
    print(f"  rejected LT-260 #{attempt} for {vin}")


def rows_on_tab(page, tab, vin):
    """Every VIN cell matching `vin` on `tab`, with the listing filtered to it."""
    drv.open_listing(page, LT260_LIST_URL)
    if not drv.click_tab(page, tab):
        return None
    if not filter_by_vin(page, vin):
        return None
    page.wait_for_timeout(2500)
    return [c for c in vin_cells(page) if c["text"].upper() == vin.upper()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=os.environ.get("NSM_ENV", "qa"))
    ap.add_argument("--vin", help="reuse an already-seeded VIN instead of creating one")
    ap.add_argument("--rejections", type=int, default=2)
    args = ap.parse_args()
    os.environ["NSM_ENV"] = args.env

    drv.clear_stale_shots()
    vin = args.vin or generate_vin()
    started = time.time()
    print(f"[tc028] env={args.env} VIN={vin} target rejections={args.rejections}")

    holder = []
    try:
        with sync_playwright() as pw:
            public = ctx_page(pw, holder, "public-portal.json")
            staff = ctx_page(pw, holder, "staff-portal.json")

            if not args.vin:
                for i in range(1, args.rejections + 1):
                    submit_lt260(public, vin, i)
                    reject_lt260(staff, vin, i)

            # PRE: the VIN must really carry more than one rejection, else the case is
            # not testing what it claims to.
            rejected = rows_on_tab(staff, "Rejected", vin)
            shot(staff, "tc028-rejected-tab")
            check(f"the seeded VIN {vin} carries MORE THAN ONE rejected LT-260, so the "
                  f"'multiple historical rejections' precondition genuinely holds (TC_028 "
                  f"precondition)",
                  (f"{len(rejected)} rejected row(s) on the LT-260 Rejected tab"
                   if rejected is not None
                   else "the Rejected tab could not be read (tab or filter unavailable)"),
                  bool(rejected) and len(rejected) >= 2)

            # The case under test: a fresh LT-260 on that twice-rejected VIN.
            submit_lt260(public, vin, args.rejections + 1)

            cells = rows_on_tab(staff, "To Process", vin)
            shot(staff, "tc028-to-process")
            check(f"the newly submitted LT-260 for the twice-rejected VIN {vin} appears on "
                  f"To Process and is HIGHLIGHTED orange {ORANGE} — accumulated rejection "
                  f"history still fires the flag (TC_028)",
                  (f"{len(cells)} row(s), colour(s) {sorted({c['color'] for c in cells})}"
                   if cells else
                   "the VIN did not appear on To Process after the third submission"),
                  bool(cells) and all(c["color"] == ORANGE for c in cells))

            check(f"that VIN appears EXACTLY ONCE on To Process — the prior-rejection "
                  f"lookup must not fan out one listing row per historical rejection "
                  f"(TC_028, duplicate-row risk)",
                  (f"{len(cells)} matching row(s) on To Process" if cells is not None
                   else "To Process could not be read"),
                  bool(cells) and len(cells) == 1)
    except Exception as exc:
        check(f"the TC_028 multi-rejection scenario runs to completion against {args.env}",
              f"the run aborted ({type(exc).__name__}: {exc})", False)
    finally:
        for b in holder:
            try:
                b.close()
            except Exception:
                pass

    passed = sum(1 for c in drv._checks if c)
    print(f"\nSEEDED VIN: {vin}")
    print(f"SUMMARY: {passed}/{len(drv._checks)} checks passed in {time.time() - started:.0f}s")
    sys.exit(0 if drv._checks and passed == len(drv._checks) else 1)


if __name__ == "__main__":
    main()
