"""Submit an LT-263 (Request Date of Sale) against a freshly-built case.

LT-263 can't be submitted standalone — BR-27 requires DMV to have issued it, which
only happens after the case walks LT-260 -> staff process -> LT-262 + pay -> LT-264
-> court hearing logged. This script drives that whole lifecycle via the shared
helper, pinning the case's addresses to one city, then submits the LT-263.

The portal derives city + county from the ZIP (the LT-260 location tab's ZIP lookup),
so the ZIP is what actually places the case — the city/county entries in CITIES below
are there to document what each ZIP resolves to.

Usage (from e2eautomation/):
    python scripts/submit_lt263.py                          # QA, Charlotte, headless
    python scripts/submit_lt263.py --headed                 # watch it run
    python scripts/submit_lt263.py --city raleigh --env qa
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows consoles default to cp1252, which can't encode glyphs scraped from the
# portal (the header's '▾'). Without this, a diagnostic print can crash the run.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

CITIES = {
    "charlotte":  {"city": "Charlotte",  "state": "NC", "zip": "28202", "county": "Mecklenburg"},
    "raleigh":    {"city": "Raleigh",    "state": "NC", "zip": "27601", "county": "Wake"},
    "durham":     {"city": "Durham",     "state": "NC", "zip": "27701", "county": "Durham"},
    "greensboro": {"city": "Greensboro", "state": "NC", "zip": "27401", "county": "Guilford"},
    "wilmington": {"city": "Wilmington", "state": "NC", "zip": "28401", "county": "New Hanover"},
}

parser = argparse.ArgumentParser()
parser.add_argument("--env", default="qa", choices=["qa", "stage", "uat"])
parser.add_argument("--city", default="charlotte", choices=sorted(CITIES))
parser.add_argument("--street", default="123 Main Street")
parser.add_argument("--lien-amount", default="800")
parser.add_argument("--sale-days-out", type=int, default=21,
                    help="Sale Date offset. Public sale may be sooner; a PRIVATE digital "
                         "sale must be >= 1 month out.")
parser.add_argument("--timezone", default="America/New_York",
                    help="Browser timezone. Must stay on NC time: the LT-263 Sale Time is "
                         "captured in the browser's zone, so running from a non-NC machine "
                         "skews the Sale Hour on the generated PDF.")
parser.add_argument("--headed", action="store_true")
args = parser.parse_args()

os.environ["NSM_ENV"] = args.env

from playwright.sync_api import sync_playwright  # noqa: E402

from src.config.env import ENV  # noqa: E402  (lazy: needs NSM_ENV set first)
from src.helpers.data_helper import generate_person  # noqa: E402
from src.helpers.lt263_resubmit_helper import create_case_to_lt263_submitted  # noqa: E402

AUTH_DIR = Path(__file__).resolve().parent.parent / "auth" / args.env
PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def main():
    location = CITIES[args.city]
    address = {"street": args.street, **location}
    person = generate_person()

    print(f"[submit-lt263] env={args.env}  city={location['city']}, {location['state']} "
          f"{location['zip']} ({location['county']} County)")
    print(f"[submit-lt263] street={address['street']!r}  authorized person={person['name']!r}")
    print(f"[submit-lt263] timezone={args.timezone}")
    print(f"[submit-lt263] public={PP_DASHBOARD_URL}")
    print(f"[submit-lt263] staff={SP_DASHBOARD_URL}")
    start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        public_ctx = browser.new_context(storage_state=str(AUTH_DIR / "public-portal.json"),
                                         timezone_id=args.timezone)
        staff_ctx = browser.new_context(storage_state=str(AUTH_DIR / "staff-portal.json"),
                                        timezone_id=args.timezone)
        public_page = public_ctx.new_page()
        staff_page = staff_ctx.new_page()
        try:
            vin = create_case_to_lt263_submitted(
                public_page, staff_page, go_to_public_dashboard, go_to_staff_dashboard,
                address=address, person=person,
                lien_amount=args.lien_amount, sale_days_out=args.sale_days_out,
            )
        finally:
            elapsed = time.time() - start
            print(f"[submit-lt263] elapsed {elapsed / 60:.1f} min")
            public_page.close()
            staff_page.close()
            public_ctx.close()
            staff_ctx.close()
            browser.close()

    print("=" * 60)
    print(f"  LT-263 SUBMITTED  (verified on the staff LT-263 'To Process' tab)")
    print(f"  VIN:      {vin}")
    print(f"  Location: {location['city']}, {location['state']} {location['zip']}")
    print("=" * 60)
    return vin


if __name__ == "__main__":
    main()
