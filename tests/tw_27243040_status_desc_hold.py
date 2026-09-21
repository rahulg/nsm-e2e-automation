"""TW 27243040 — "Out-of-state title cancellation holds auto-processing" (Status
Desc gate), NSM/NSS Staff Portal.

CR: STARS reports a vehicle's title as "Cancelled to [State]" where state != NC ->
LT-260/LT-261 auto-issuance/auto-processing is HELD for manual staff review instead
of auto-completing. A new STATUS DESC field (textarea, formcontrolname/name=
"title_description" — confirmed live on QA 2026-08-19 via DOM exploration, present
on both the LT-260 and LT-261 'Add from Paper' forms) is staff-editable and sourced
from STARS's titleStatusDesc, but can also be typed directly on the paper-logging
form — the same code path a real STARS out-of-state response takes. Typing
"Title Cancelled to Ohio" into it therefore exercises the gate without needing to
control real STARS/DMV data.

Synthesized by ExpertlyTestBuddyAuto / runTestPlan for ticket 27243040. Reuses
Lt260ListingPage / PaperFormPage / FormProcessingPage (LT-260) and Lt261Page
(LT-261), mirroring the create-and-verify pattern already used by
test_e2e_005_paper_form_e2e.py (LT-260 owner path auto-issues to Processed) and
test_e2e_004_sheriff_inspector_lt261.py (LT-261 E-Stop paper flow).

Usage (from e2eautomation/):
    python tests/tw_27243040_status_desc_hold.py --mode sc1 --env qa
    python tests/tw_27243040_status_desc_hold.py --mode sc2 --env qa
    python tests/tw_27243040_status_desc_hold.py --mode sc4 --env qa

Modes:
    sc1  Out-of-state LT-260: auto-issuance held, Status Desc + red reason banner
    sc2  Out-of-state LT-261: auto-processing held; best-effort Stolen=Yes compose
    sc4  Control arm: blank Status Desc LT-260 still auto-issues (regression guard)
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("--mode", required=True, choices=["sc1", "sc2", "sc4"])
ap.add_argument("--env", default="qa", choices=["qa", "stage"])
ap.add_argument("--headed", action="store_true")
args = ap.parse_args()
os.environ["NSM_ENV"] = args.env

from playwright.sync_api import sync_playwright  # noqa: E402

from src.config.env import ENV  # noqa: E402
from src.helpers.data_helper import generate_vin, generate_person, future_date  # noqa: E402
from src.pages.staff_portal.dashboard_page import StaffDashboardPage  # noqa: E402
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage  # noqa: E402
from src.pages.staff_portal.paper_form_page import PaperFormPage  # noqa: E402
from src.pages.staff_portal.form_processing_page import FormProcessingPage  # noqa: E402
from src.pages.staff_portal.lt261_page import Lt261Page  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "auth" / args.env
SHOTS = ROOT.parent / "skills" / "nsm-out-of-state-title-hold" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
# Clear stale PNGs at the START of every invocation (per the aut's documented
# glob:screenshots/*.png contract — a shared dir must not leak a prior mode's evidence).
for f in SHOTS.glob(f"{args.mode}_*.png"):
    try:
        f.unlink()
    except Exception:
        pass

BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
DASH = BASE_URL + "/pages/ncdot-notice-and-storage/dashboard"

OUT_OF_STATE_DESC = "Title Cancelled to Ohio"
REASON_HEADING_RE = re.compile(r"Case was not auto-processed because", re.I)
OUT_OF_STATE_REASON_RE = re.compile(
    r"Cancelled to Other State|out-?of-?state DMV|contact the out-of-state", re.I
)
STOLEN_REASON_RE = re.compile(r"Vehicle is Stolen|vehicle.*stolen", re.I)
STATUS_DESC_LABEL_RE = re.compile(r"STATUS\s*DESC", re.I)
# Negative lookbehind excludes "auto-processed"/"auto processed" (the reason-block
# heading text) so this only matches a genuine standalone status of "Processed".
PROCESSED_RE = re.compile(r"(?<!auto-)(?<!auto )\bProcessed\b", re.I)

FAILS: list[str] = []
NOTES: list[str] = []
CHECKS = 0


def check(ok: bool, msg: str):
    global CHECKS
    CHECKS += 1
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        FAILS.append(msg)
    return ok


def note(msg: str):
    print(f"  NOTE  {msg}")
    NOTES.append(msg)


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{args.mode}_{name}.png"), full_page=True)
    except Exception:
        pass


def go_to_staff_dashboard(page):
    page.goto(DASH, timeout=60_000)
    page.wait_for_load_state("networkidle")


def fill_status_desc(page, text: str):
    """Fill the STATUS DESC textarea (formcontrolname/name='title_description').
    Confirmed live on QA 2026-08-19 (both LT-260 and LT-261 Add-from-Paper forms) —
    no existing page object/selector for this field anywhere in the repo, so it is
    located here directly rather than duplicated per page object."""
    ta = page.locator('textarea[name="title_description"]').first
    ta.wait_for(state="visible", timeout=15_000)
    ta.scroll_into_view_if_needed()
    ta.fill(text)
    page.keyboard.press("Tab")
    page.wait_for_timeout(400)


def read_body(page) -> str:
    return page.locator("body").inner_text()


def has_reason_banner(body: str, reason_re: "re.Pattern"):
    return bool(REASON_HEADING_RE.search(body)), bool(reason_re.search(body))


# ─────────────────────────────── LT-260 (SC-1 / SC-4) ──────────────────────────
def fill_lt260_paper_form(page, vin, person, status_desc: str | None):
    """Add from Paper (LT-260): Year, Make, Date Vehicle Left, Search Location,
    + Add Owner, [Status Desc], Stolen=No."""
    from src.helpers.data_helper import past_date

    dash = StaffDashboardPage(page)
    lst = Lt260ListingPage(page)
    pf = PaperFormPage(page)

    go_to_staff_dashboard(page)
    dash.navigate_to_lt260_listing()
    lst.click_add_from_paper()
    pf.fill_modal_vin_and_next(vin)

    pf.fill_year("2018")
    pf.fill_make("TOY")
    pf.fill_date_vehicle_left(past_date(30))
    pf.fill_search_location("Garage")
    pf.fill_storage_contact_if_blank()
    pf.add_owner(person["name"], "100 Main St", "27601")

    if status_desc:
        fill_status_desc(page, status_desc)

    pf.select_stolen_no()
    return pf


def sc1(page):
    """Out-of-state LT-260: auto-issuance held, Status Desc + red reason banner render
    correctly. Covers TC-01, 04, 06, 07, 08, 09, 14."""
    print("EXPECTED: an LT-260 whose STATUS DESC reads an out-of-state cancellation "
          "('Title Cancelled to Ohio') does NOT auto-issue LT-160B/LT-260A (case stays "
          "off the Processed tab), the case screen renders the STATUS DESC value, and a "
          "red 'Case was not auto-processed because:' block names the out-of-state reason.")
    vin = generate_vin()
    person = generate_person()
    print(f"  VIN={vin}")

    fill_lt260_paper_form(page, vin, person, OUT_OF_STATE_DESC)
    shot(page, "01_filled")

    pf = PaperFormPage(page)
    pf.submit_with_confirmation()
    page.wait_for_timeout(2500)
    shot(page, "02_after_submit")

    body = read_body(page)
    check(bool(STATUS_DESC_LABEL_RE.search(body)),
          "STATUS DESC label renders on the post-submit case screen (REQ-003,006,044)")
    check(OUT_OF_STATE_DESC in body or "Cancelled to Ohio" in body,
          f"the typed Status Desc value ('{OUT_OF_STATE_DESC}') is shown back on the case screen")

    heading_seen, reason_seen = has_reason_banner(body, OUT_OF_STATE_REASON_RE)
    check(heading_seen, "'Case was not auto-processed because:' block is present (REQ-004,012)")
    check(reason_seen, "the out-of-state reason text is present in the block (REQ-004,012)")

    not_processed = not PROCESSED_RE.search(body)
    check(not_processed,
          "the case does NOT show a 'Processed' status right after submit -- auto-issuance was HELD")

    # Cross-check against the LT-260 'To Process' tab (independent of the detail-page text scrape)
    go_to_staff_dashboard(page)
    StaffDashboardPage(page).navigate_to_lt260_listing()
    lst = Lt260ListingPage(page)
    lst.click_to_process_tab()
    try:
        lst.search_by_vin(vin)
        page.wait_for_timeout(2000)
        on_to_process = lst.application_rows.count() > 0
    except Exception:
        on_to_process = None
    shot(page, "03_to_process_tab")
    if on_to_process is not None:
        check(on_to_process, "VIN appears on the LT-260 'To Process' tab (held for manual review), "
                              "not auto-issued straight to Processed")
    else:
        note("could not confirm via the To Process tab search (non-fatal — the detail-page checks above stand)")


def sc4(page):
    """Control arm: blank Status Desc LT-260 still auto-issues exactly as before this
    CR (unaffected-path regression guard). Covers TC-02."""
    print("EXPECTED: an LT-260 with STATUS DESC left BLANK auto-issues LT-160B/LT-260A "
          "and reaches the Processed status exactly as it did before this CR (owner-path "
          "auto-issuance, per test_e2e_005 Phase 1/2).")
    vin = generate_vin()
    person = generate_person()
    print(f"  VIN={vin}")

    fill_lt260_paper_form(page, vin, person, None)
    shot(page, "01_filled")

    pf = PaperFormPage(page)
    pf.submit_with_confirmation()
    page.wait_for_timeout(2500)
    shot(page, "02_after_submit")

    fp = FormProcessingPage(page)
    try:
        fp.expect_status_processed()
        processed = True
    except Exception:
        processed = False
    body = read_body(page)
    heading_seen = bool(REASON_HEADING_RE.search(body))
    check(processed, "the control-arm case (no cancellation) reaches 'Processed' -- "
                      "auto-issuance is UNAFFECTED by this CR (TC-02)")
    check(not heading_seen, "no 'Case was not auto-processed because:' block on the "
                            "unaffected control-arm case")
    shot(page, "03_final")


# ─────────────────────────────── LT-261 (SC-2) ─────────────────────────────────
def fill_lt261_paper_form(lt261: Lt261Page, page, officer_name: str, owner_name: str,
                           status_desc: str | None):
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")
    try:
        lt261.check_use_same_address_storage()
        lt261.fill_sale_date(future_date(21))
        lt261.select_notice_of_sale_reason()
        lt261.check_agency_use_same_address()
        lt261.fill_agency_name(officer_name)
    except Exception as exc:
        note(f"optional sale/agency section step skipped ({type(exc).__name__}: {exc})")
    lt261.fill_owner_seized_from(owner_name)
    lt261.add_owner_details(name=owner_name)

    if status_desc:
        fill_status_desc(page, status_desc)


def sc2(page):
    """Out-of-state LT-261: auto-processing held, composes with the Stolen hold.
    Covers TC-03, 05, 19, 23 (23 best-effort)."""
    print("EXPECTED: an E-Stop LT-261 whose STATUS DESC reads an out-of-state "
          "cancellation does NOT auto-process (no LT-265/LT-265A, vehicle not Sold), "
          "shows STATUS DESC beside Stolen (no Status Code row on LT-261), and the same "
          "reason block/wording as the LT-260 arm. Best-effort: editing Stolen=Yes on "
          "the same case should then show BOTH reasons, one per line.")
    vin = generate_vin()
    officer = generate_person()
    print(f"  VIN={vin}")

    go_to_staff_dashboard(page)
    StaffDashboardPage(page).navigate_to_lt261_listing()
    lt261 = Lt261Page(page)
    lt261._wait_listing_settled()
    lt261.open_paper_form("E-Stop", vin)
    fill_lt261_paper_form(lt261, page, officer["name"], f"Owner {officer['name']}", OUT_OF_STATE_DESC)
    shot(page, "01_filled")

    lt261.select_stolen_no()
    lt261.submit_with_confirmation()
    page.wait_for_timeout(2500)
    shot(page, "02_after_submit_listing")

    # submit_with_confirmation() redirects to the LT-261 'To Process' LISTING (unlike
    # LT-260, which redirects to the case detail page) -- confirmed live 2026-08-19.
    # Open the just-submitted case's OWN detail page before scraping Status Desc /
    # the reason banner, and cross-check its tab placement from THIS listing state
    # (avoids a false 'Processed' match against the Processed TAB LABEL itself).
    lt261.search_by_vin(vin)
    page.wait_for_timeout(1500)
    on_to_process = lt261.application_rows.count() > 0
    shot(page, "03_to_process_search")
    check(on_to_process, "VIN appears on the LT-261 'To Process' tab right after submit "
                          "-- auto-processing was HELD, not silently completed")

    if on_to_process:
        lt261.select_application(0)
        page.wait_for_timeout(2000)
        shot(page, "04_detail_page")
        body = read_body(page)
        check(bool(STATUS_DESC_LABEL_RE.search(body)),
              "STATUS DESC renders on the LT-261 case screen beside Stolen (REQ-033)")
        heading_seen, reason_seen = has_reason_banner(body, OUT_OF_STATE_REASON_RE)
        check(heading_seen, "'Case was not auto-processed because:' block is present on the LT-261 arm")
        check(reason_seen, "the out-of-state reason text matches the LT-260 arm's wording")
    else:
        # Not held -> follow it to the Processed tab and capture WHY: either the field
        # never persisted, or it persisted but the gate itself didn't fire. Distinguishing
        # the two is the whole point of a defect finding vs. a vague "FAIL".
        note("VIN NOT found on 'To Process' -- the case was not held. Following it to the "
             "Processed tab to determine whether Status Desc persisted at all.")
        go_to_staff_dashboard(page)
        StaffDashboardPage(page).navigate_to_lt261_listing()
        lt261_p = Lt261Page(page)
        lt261_p._wait_listing_settled()
        lt261_p.processed_tab.click()
        page.wait_for_timeout(1500)
        lt261_p.search_by_vin(vin)
        page.wait_for_timeout(2000)
        on_processed = lt261_p.application_rows.count() > 0
        shot(page, "05_processed_tab_search")
        check(on_processed, "the VIN was submitted at all -- located it on SOME LT-261 tab "
                             "for evidence-gathering (setup check, not the CR's own assertion)")
        if on_processed:
            lt261_p.select_application(0)
            page.wait_for_timeout(2000)
            shot(page, "06_processed_detail_page")
            body = read_body(page)
            idx = body.upper().find("STATUS DESC")
            desc_context = body[max(0, idx - 5):idx + 60] if idx >= 0 else "(label not found)"
            persisted = OUT_OF_STATE_DESC.lower() in body.lower() or "cancelled to ohio" in body.lower()
            heading_seen = bool(REASON_HEADING_RE.search(body))
            print(f"  DEFECT EVIDENCE: case screen Status Desc context: {desc_context!r}")
            print(f"EXPECTED: the LT-261 case does NOT auto-process to 'Processed' when "
                  f"STATUS DESC reads an out-of-state cancellation (TC-03/05/19, mirrors the "
                  f"LT-260 arm in SC-1) | ACTUAL: case IS 'Processed'; typed Status Desc "
                  f"persisted={persisted}; reason-banner heading present={heading_seen} -> MISMATCH")
            check(False, "DEFECT: on LT-261 'Add from Paper' (E-Stop), the out-of-state gate did "
                         "NOT hold the case -- it auto-processed to 'Processed' with no "
                         "'Case was not auto-processed because:' block, " +
                         ("even though the typed Status Desc value DID persist to the case screen "
                          "(so the block/gate logic itself is the gap)" if persisted else
                          "and the typed Status Desc value ('Title Cancelled to Ohio') did NOT "
                          "persist at all -- the case screen shows Status Desc context "
                          f"{desc_context!r} instead, so the field-capture step on THIS "
                          "less-common first-time-VIN LT-261 path (REQ-037, plan.json SC-3 "
                          "step 2) is the more likely root cause, not the gate logic per se"))
        else:
            note("VIN not found on To Process OR Processed after two searches -- inconclusive; "
                 "not asserting a defect without evidence")

    # Best-effort TC-23: edit the same case to Stolen=Yes, expect BOTH reasons to compose.
    try:
        go_to_staff_dashboard(page)
        StaffDashboardPage(page).navigate_to_lt261_listing()
        lt261_l2 = Lt261Page(page)
        lt261_l2._wait_listing_settled()
        lt261_l2.search_input.fill(vin)
        page.wait_for_timeout(2000)
        lt261_l2.select_application(0)
        page.wait_for_timeout(2000)
        fp = FormProcessingPage(page)
        fp.click_edit()
        fp.select_stolen_yes()
        fp.click_save()
        page.wait_for_timeout(2500)
        shot(page, "04_after_stolen_edit")
        body2 = read_body(page)
        both = bool(OUT_OF_STATE_REASON_RE.search(body2)) and bool(STOLEN_REASON_RE.search(body2))
        check(both, "after editing Stolen=Yes on the same case, BOTH the stolen reason and "
                    "the out-of-state reason render together (REQ-005,009,020,023 -- TC-23)")
    except Exception as exc:
        note(f"TC-23 (Stolen=Yes composition) not completed this run -- Edit/Save on the "
             f"LT-261 case screen raised {type(exc).__name__}: {str(exc)[:150]}. The core "
             f"out-of-state hold above (TC-03/05/19) is unaffected by this gap.")


def new_context(pw):
    b = pw.chromium.launch(headless=not args.headed)
    ctx = b.new_context(storage_state=str(AUTH / "staff-portal.json"),
                        viewport={"width": 1600, "height": 1000})
    return b, ctx


def main():
    print(f"=== TW 27243040 · {args.mode} · env={args.env} ===")
    with sync_playwright() as pw:
        b, ctx = new_context(pw)
        page = ctx.new_page()
        try:
            {"sc1": sc1, "sc2": sc2, "sc4": sc4}[args.mode](page)
        finally:
            shot(page, "final")
            ctx.close()
            b.close()

    print("-" * 70)
    for n in NOTES:
        print(f"NOTE: {n}")
    print(f"checks: {CHECKS - len(FAILS)}/{CHECKS} passed")
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)} assertion(s))")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: PASS")


if __name__ == "__main__":
    main()
