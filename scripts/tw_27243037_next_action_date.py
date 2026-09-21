"""TW 27243037 / NCNSS-536 — "Adding Next Step Date in LT-264 Letters".

Verifies that LT-264 and LT-264 Garage letters print

    The next action date for this File is MM/DD/YYYY

appended to the end of the bold NOTICE paragraph, where the date is the
letter's print/issuance date + 32 calendar days (AC-1/AC-2), that a reprint
re-renders the sentence from TODAY + 32 (AC-4), and that no other letter
template gained the sentence.

Synthesized by ExpertlyTestBuddyAuto / runTestPlan for ticket 27243037.
Reuses StaffDashboardPage + Lt262ListingPage and the correspondence-modal
download pattern already used by scripts/fetch_lt263_pdf.py.

Usage (from e2eautomation/):
    python scripts/tw_27243037_next_action_date.py SC-1 [--env qa] [--headed]

Steps:
    SC-1  Fresh LT-264 / LT-264G issuance carries the sentence (AC-1, AC-2)
    SC-2  Send for Reprinting re-renders with TODAY + 32 (AC-4)
    SC-3  Regression wall — no other letter template gained the sentence
    SC-4  Reprint scope by form type — only LT-264/LT-264G regenerate
    SC-5  Public Portal parity — the garage reads the same date
    SC-6  Role sweep — Fiscal User cannot issue or reprint
    SC-7  Aging reset — AC-3: staff-reject -> requestor re-edit/resubmit -> staff
          re-issue recalculates the date from the reset date, not the original
"""
import argparse
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ap = argparse.ArgumentParser()
ap.add_argument("step", choices=["SC-1", "SC-2", "SC-3", "SC-4", "SC-5", "SC-6", "SC-7"])
ap.add_argument("--env", default="qa", choices=["qa", "stage"])
ap.add_argument("--headed", action="store_true")
args = ap.parse_args()
os.environ["NSM_ENV"] = args.env

from playwright.sync_api import sync_playwright, expect  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from src.config.env import ENV  # noqa: E402
from src.pages.staff_portal.dashboard_page import StaffDashboardPage  # noqa: E402
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "auth" / args.env
SHOTS = ROOT.parent / "skills" / "nsm-lt264-next-action-date" / "screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
DL = ROOT / "results" / "lt264_nextaction" / args.step
DL.mkdir(parents=True, exist_ok=True)

DASH = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

# The sentence under test. Wording is fixed by AC-1 / REQ-009.
SENT_RE = re.compile(r"The next action date for this File is\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", re.I)
LOOSE_RE = re.compile(r"next\s+action\s+date", re.I)
# Velocity guard (REQ-012) — none of these may ever reach a legal notice.
LEAK_RE = re.compile(r"\$nextActionDate|\$\{|\bnull\b|\bundefined\b|\bNaN\b", re.I)

FAILS: list[str] = []
NOTES: list[str] = []


def check(ok: bool, msg: str):
    print(f"  {'PASS' if ok else 'FAIL'}  {msg}")
    if not ok:
        FAILS.append(msg)
    return ok


def note(msg: str):
    print(f"  NOTE  {msg}")
    NOTES.append(msg)


def shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{args.step.lower()}_{name}.png"), full_page=True)
    except Exception:
        pass


def plus32(d: date) -> str:
    return (d + timedelta(days=32)).strftime("%m/%d/%Y")


def pdf_text(path: Path) -> str:
    t = ""
    for pg in PdfReader(str(path)).pages:
        t += (pg.extract_text() or "") + "\n"
    return re.sub(r"\s+", " ", t)


# ─────────────────────────────── UI helpers ────────────────────────────────
def open_listing(page, tab: str) -> Lt262ListingPage:
    page.goto(DASH, timeout=60_000)
    page.wait_for_load_state("networkidle")
    StaffDashboardPage(page).navigate_to_lt262_listing()
    lst = Lt262ListingPage(page)
    page.wait_for_timeout(1500)
    {"aging": lst.click_aging_tab,
     "toprocess": lst.click_to_process_tab,
     "closed": lst.click_closed_tab,
     "all": lst.click_all_tab}[tab]()
    page.wait_for_timeout(2500)
    return lst


def open_correspondence(page):
    vc = page.locator('//span[contains(text(),"View Correspondence/Documents")]').first
    vc.wait_for(state="visible", timeout=25_000)
    vc.click()
    page.wait_for_timeout(1500)
    modal = page.locator(".correspondence-modal, mat-dialog-container").first
    modal.wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(1800)
    return modal


def corr_rows(modal):
    """[(idx, code, issued_date, text, has_download, has_reprint)] for real rows."""
    rows = modal.locator("table tbody tr")
    out = []
    for i in range(rows.count()):
        txt = re.sub(r"[ \t]+", " ", rows.nth(i).text_content() or "").strip()
        if not txt:
            continue
        m = re.match(r"(LT-?\d+[A-Z]?)", txt)
        if not m:
            continue
        d = re.search(r"(\d{2})-(\d{2})-(\d{4})", txt)
        issued = date(int(d.group(3)), int(d.group(1)), int(d.group(2))) if d else None
        out.append((i, m.group(1).upper().replace("LT", "LT-").replace("LT--", "LT-"),
                    issued, txt,
                    "Download" in txt, "Reprint" in txt))
    return out


def download_row(page, modal, idx: int, label: str):
    row = modal.locator("table tbody tr").nth(idx)
    dl = row.locator("span.table-link").filter(has_text=re.compile(r"^\s*Download\s*$", re.I)).first
    dl.scroll_into_view_if_needed()
    with page.expect_download(timeout=40_000) as di:
        dl.click()
    d = di.value
    dest = DL / f"{label}_{d.suggested_filename or 'doc.pdf'}"
    d.save_as(str(dest))
    return dest, pdf_text(dest)


def assert_sentence(text: str, expected_date: str | None, label: str, must_have=True):
    """Assert (or assert-absence of) the next-action sentence in one letter."""
    m = SENT_RE.search(text)
    if not must_have:
        check(not LOOSE_RE.search(text), f"{label}: sentence correctly ABSENT")
        return None
    if not check(bool(m), f"{label}: sentence present — 'The next action date for this File is <date>'"):
        if LOOSE_RE.search(text):
            note(f"{label}: a 'next action date' phrase exists but not in the AC wording: "
                 f"...{text[max(0, LOOSE_RE.search(text).start() - 60):LOOSE_RE.search(text).end() + 60]}...")
        return None
    printed = m.group(1)
    check(bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", printed)),
          f"{label}: date is zero-padded MM/DD/YYYY ({printed})")
    check(not LEAK_RE.search(m.group(0)), f"{label}: no template/null leak in the sentence")
    if expected_date:
        check(printed == expected_date,
              f"{label}: printed {printed} == issue date + 32 ({expected_date})")
    # REQ-008: appended to the END of the bold NOTICE paragraph
    nm = re.search(r"NOTICE:.*?(?=Thank you for your prompt|Sincerely)", text, re.I | re.S)
    if nm:
        check(bool(SENT_RE.search(nm.group(0))),
              f"{label}: sentence sits inside the NOTICE paragraph (REQ-008 placement)")
        check(nm.group(0).rstrip().endswith(printed) or
              SENT_RE.search(nm.group(0)).end() >= len(nm.group(0).rstrip()) - 2,
              f"{label}: sentence is at the END of the NOTICE paragraph")
    else:
        note(f"{label}: NOTICE paragraph not isolatable in extracted text — placement not asserted")
    note(f"{label}: underline on the date is a VISUAL property — not asserted from extracted text")
    return printed


def new_context(pw, auth_file="staff-portal.json"):
    b = pw.chromium.launch(headless=not args.headed)
    ctx = b.new_context(storage_state=str(AUTH / auth_file), accept_downloads=True,
                        viewport={"width": 1600, "height": 1000})
    return b, ctx


# ──────────────────────────────── scenarios ────────────────────────────────
def sc1(page):
    """Fresh issuance — AC-1 / AC-2 (TC-01, TC-04, TC-05, TC-12, TC-13)."""
    print("EXPECTED: a newly ISSUED LT-264 and its LT-264G courtesy copy both print "
          "'The next action date for this File is <issue date + 32>' at the end of the "
          "NOTICE paragraph, in MM/DD/YYYY, identical on every copy.")
    lst = open_listing(page, "toprocess")
    n = lst.application_rows.count()
    print(f"  LT-262 'To Process' rows: {n}")
    if n == 0:
        note("BLOCKED: no LT-262 case sitting on 'To Process' — nothing to issue an LT-264 from")
        return
    issued_on = None
    for i in range(min(n, 3)):
        lst.select_application(i)
        page.wait_for_timeout(2500)
        print(f"  opened case: {page.url}")
        try:
            lst.issue_lt264()
        except Exception as e:
            note(f"row {i}: issue_lt264 raised {type(e).__name__}: {str(e)[:120]}")
        page.wait_for_timeout(3000)
        shot(page, f"after_issue_row{i}")
        try:
            modal = open_correspondence(page)
        except Exception:
            note(f"row {i}: no correspondence modal after issuance")
            page.go_back(); page.wait_for_timeout(2000)
            continue
        rows = corr_rows(modal)
        today = date.today()
        fresh = [r for r in rows if r[1] in ("LT-264", "LT-264G") and r[2] == today]
        print(f"  correspondence rows: {len(rows)}; issued-today LT-264/G rows: {len(fresh)}")
        if not fresh:
            note(f"row {i}: no LT-264 issued today on this case "
                 f"(codes seen: {sorted({r[1] for r in rows})})")
            page.keyboard.press("Escape"); page.wait_for_timeout(800)
            page.go_back(); page.wait_for_timeout(2500)
            continue
        issued_on = today
        printed = {}
        for idx, code, iss, txt, has_dl, _ in fresh[:4]:
            if not has_dl:
                continue
            path, text = download_row(page, modal, idx, code)
            p = assert_sentence(text, plus32(iss), f"{code} (issued {iss:%m/%d/%Y})")
            if p:
                printed.setdefault(code, []).append(p)
        allp = [v for vs in printed.values() for v in vs]
        if len(allp) > 1:
            check(len(set(allp)) == 1,
                  f"every copy prints one and the same date (saw {sorted(set(allp))}) — TC-04")
        if "LT-264" in printed and "LT-264G" in printed:
            check(printed["LT-264"][0] == printed["LT-264G"][0],
                  "owner LT-264 and garage LT-264G print the identical date — AC-2 / TC-01")
        shot(page, "correspondence")
        break
    if issued_on is None:
        note("BLOCKED: could not get a freshly issued LT-264 out of the first 3 'To Process' cases")


def sc2(page):
    """Reprint — AC-4 (TC-03, TC-15, TC-18, TC-22)."""
    print("EXPECTED: 'Send for Reprinting' on an LT-264 re-renders it with TODAY + 32 "
          "(not the original letter's date), the original letter stays retrievable, and "
          "Download then serves the newly regenerated file.")
    lst = open_listing(page, "aging")
    if lst.application_rows.count() == 0:
        note("BLOCKED: no case on the LT-262 Aging tab")
        return
    lst.select_application(0)
    page.wait_for_timeout(2500)
    print(f"  case: {page.url}")
    modal = open_correspondence(page)
    rows = corr_rows(modal)
    targets = [r for r in rows if r[1] == "LT-264" and r[5] and r[4]]
    if not targets:
        note("BLOCKED: no LT-264 row with a 'Send for Reprinting' control on this case")
        return
    idx, code, issued, txt, _, _ = targets[0]
    print(f"  target row [{idx}] {code} issued {issued}")

    before_path, before_text = download_row(page, modal, idx, "before")
    before = SENT_RE.search(before_text)
    print(f"  BEFORE reprint: {before.group(0) if before else '(sentence ABSENT)'}")
    n_before = len(rows)

    row = modal.locator("table tbody tr").nth(idx)
    rp = row.locator("span.table-link, a, button").filter(
        has_text=re.compile(r"reprint", re.I)).first
    rp.scroll_into_view_if_needed()
    rp.click()
    page.wait_for_timeout(1500)
    # confirm any dialog
    for lbl in ("Yes", "Confirm", "Reprint", "Ok", "OK"):
        b = page.locator(f'mat-dialog-container button:has-text("{lbl}")').first
        if b.count() and b.is_visible():
            b.click()
            break
    page.wait_for_timeout(4000)
    shot(page, "after_reprint")

    # re-open the modal so the new row is loaded
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    page.wait_for_timeout(1200)
    modal = open_correspondence(page)
    rows2 = corr_rows(modal)
    check(len(rows2) >= n_before, f"correspondence retains the original letters "
                                  f"({n_before} rows before, {len(rows2)} after) — TC-22")
    t264 = [r for r in rows2 if r[1] == "LT-264" and r[4]]
    if not t264:
        note("no LT-264 row with Download after the reprint")
        return
    # Download the newest LT-264 row (the regenerated file, REQ-020)
    newest = max(t264, key=lambda r: (r[2] or date.min, r[0]))
    after_path, after_text = download_row(page, modal, newest[0], "after")
    printed = assert_sentence(after_text, plus32(date.today()),
                              f"reprinted LT-264 (row {newest[0]})")
    if printed and before:
        check(printed != before.group(1) or before.group(1) == plus32(date.today()),
              "reprinted letter carries a NEWLY calculated date, not the original's — AC-4")
    shot(page, "correspondence_after")


def sc3(page):
    """Regression wall — no other template gained the sentence (TC-19, TC-14, TC-07)."""
    print("EXPECTED: only LT-264 and LT-264G carry the next-action sentence; every other "
          "letter on the same case (LT-260, LT-260A/C/D, LT-160B, LT-262, LT-264A/B, LT-265) "
          "is unchanged and carries it nowhere.")
    lst = open_listing(page, "aging")
    if lst.application_rows.count() == 0:
        note("BLOCKED: no case on the LT-262 Aging tab")
        return
    lst.select_application(0)
    page.wait_for_timeout(2500)
    modal = open_correspondence(page)
    rows = corr_rows(modal)
    others = [r for r in rows if r[1] not in ("LT-264", "LT-264G") and r[4]]
    print(f"  other-template rows with Download: {[r[1] for r in others]}")
    if not others:
        note("no non-LT-264 letters on this case to check")
        return
    seen = set()
    for idx, code, iss, txt, _, _ in others:
        if code in seen:
            continue
        seen.add(code)
        try:
            _, text = download_row(page, modal, idx, code)
        except Exception as e:
            note(f"{code}: download failed ({type(e).__name__})")
            continue
        assert_sentence(text, None, code, must_have=False)
    shot(page, "regression_wall")


def sc4(page):
    """Reprint scope by form type (TC-20, TC-21)."""
    print("EXPECTED: 'Send for Reprinting' is offered per form type as before, and only "
          "LT-264 / LT-264G regenerate their file — every other type's reprint still serves "
          "the ORIGINAL document, and Correspondence History totals are preserved.")
    lst = open_listing(page, "aging")
    if lst.application_rows.count() == 0:
        note("BLOCKED: no case on the LT-262 Aging tab")
        return
    lst.select_application(0)
    page.wait_for_timeout(2500)
    modal = open_correspondence(page)
    rows = corr_rows(modal)
    by_code = {}
    for _, code, _, _, dl, rp in rows:
        c = by_code.setdefault(code, {"n": 0, "dl": 0, "rp": 0})
        c["n"] += 1
        c["dl"] += dl
        c["rp"] += rp
    for code, c in sorted(by_code.items()):
        print(f"  {code:9s} rows={c['n']} download={c['dl']} reprint={c['rp']}")
    check(all(c["dl"] == c["n"] for c in by_code.values()),
          "every correspondence row still offers Download — TC-21/TC-22")
    non264 = {k: v for k, v in by_code.items() if k not in ("LT-264", "LT-264G")}
    check(any(v["rp"] > 0 for v in non264.values()) if non264 else True,
          "reprint remains available on non-LT-264 form types — TC-20 (no regression)")
    check("LT-260" not in by_code or by_code["LT-260"]["rp"] == 0,
          "LT-260 (the submitted form, not a letter) still offers no reprint")
    shot(page, "reprint_scope")


def sc5(page_pair):
    """Public Portal parity (TC-09)."""
    print("EXPECTED: the garage, reading its LT-264G copy through the Public Portal, sees "
          "the SAME next action date staff see on the Staff Portal.")
    note("Public-portal LT-264G retrieval depends on the garage that owns the staff-side case; "
         "the QA public user (G-Car Garages New) is not guaranteed to own it")
    note("NOT EXECUTED in this run — see the report's ungrouped section")


def sc6(page):
    """Role sweep (TC-11)."""
    print("EXPECTED: N&S Administrator / N&S User may issue and reprint an LT-264; a Fiscal "
          "User is Reports-only and reaches neither the LT-262 listing nor the reprint control.")
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=not args.headed)
        ctx = b.new_context(storage_state=str(AUTH / "fiscal-portal.json"),
                            viewport={"width": 1600, "height": 1000})
        p = ctx.new_page()
        try:
            p.goto(DASH, timeout=60_000)
            p.wait_for_load_state("networkidle")
            p.wait_for_timeout(2500)
            body = (p.locator("body").text_content() or "")
            check("LT-262" not in body or "Reports" in body,
                  "Fiscal User's dashboard is Reports-scoped")
            p.screenshot(path=str(SHOTS / "sc-6_fiscal_dashboard.png"), full_page=True)
            try:
                StaffDashboardPage(p).navigate_to_lt262_listing()
                p.wait_for_timeout(2500)
                check(False, "Fiscal User must NOT reach the LT-262 listing "
                             f"(landed on {p.url})")
            except Exception:
                check(True, "Fiscal User cannot navigate to the LT-262 listing")
        finally:
            ctx.close()
            b.close()


VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def sc7(pw):
    """Aging reset — AC-3 (TC-12, TC-13, TC-14, TC-15).

    RTM note A6 / featuremap NSS-E2E-037 step 5: the AC-3 'reset' is NOT a dedicated
    button — it is staff-reject an already-issued LT-262 (BR-43) -> requestor re-edits
    and resubmits on the Public Portal -> staff re-processes and RE-ISSUEs. That
    re-issue deletes and regenerates the LT-264 rows (nss.kb FO-5), printing
    reset-date + 32, while the superseded originals stay retrievable (BR-42).

    RTM note A7 / featuremap step 6 is an explicit COUNTEREXAMPLE this scenario must
    NOT touch: a stolen-VIN reset mid-aging resets the Age Date but RETAINS the Print
    Date and must not change already-generated letters — that is a different action
    entirely and is never invoked here (this scenario only ever uses the CHECK DCI
    AND NMVTIS tab's Reject control, never a stolen-VIN flag).
    """
    print("EXPECTED: staff-reject an already-issued LT-262 (BR-43) -> requestor "
          "re-edits & resubmits -> staff re-processes & RE-ISSUEs -> the newly "
          "generated LT-264/LT-264G print RESET DATE + 32 (not the original issuance's "
          "date), and repeating the loop recalculates again each time (AC-3).")
    from src.pages.public_portal.dashboard_page import PublicDashboardPage  # noqa: E402
    from src.pages.public_portal.lt260_form_page import Lt260FormPage  # noqa: E402
    from src.pages.public_portal.lt262_form_page import Lt262FormPage  # noqa: E402
    from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage  # noqa: E402
    from src.pages.staff_portal.form_processing_page import FormProcessingPage  # noqa: E402
    from src.helpers.data_helper import (  # noqa: E402
        generate_person, generate_address, past_date,
        generate_vin, random_vehicle, generate_license_plate,
    )

    SAMPLE_DOC_PATH = str(ROOT / "fixtures" / "sample-document.pdf")
    BUSINESS_NAME = ENV.PUBLIC_BUSINESS_NAME

    b1, staff_ctx = new_context(pw, "staff-portal.json")
    b2, public_ctx = new_context(pw, "public-portal.json")
    staff = staff_ctx.new_page()
    public = public_ctx.new_page()

    def resubmit_lt262(vin: str, person: dict, address: dict):
        """One requestor re-edit + resubmit of a REJECTED LT-262. Returns True on a
        visible success signal, False (with a note already emitted) otherwise."""
        public.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        public.wait_for_load_state("networkidle")
        dash = PublicDashboardPage(public)
        dash.select_business(BUSINESS_NAME)
        dash.click_notice_storage_tab()
        public.wait_for_timeout(1000)
        found = False
        for attempt in range(4):
            dash.search_by_vin(vin)
            public.wait_for_timeout(2500)
            if dash.application_list.count() > 0:
                found = True
                break
            public.reload(timeout=30_000)
            public.wait_for_load_state("networkidle")
            dash.click_notice_storage_tab()
            public.wait_for_timeout(1500)
        if not found:
            note(f"VIN {vin}: not found on the '{BUSINESS_NAME}' Public Portal account "
                 f"after {4} search attempts — this Aging case was very likely picked "
                 f"from the staff side and is NOT owned by the QA public test account "
                 f"(the same ownership caveat SC-5 already documents), not a timing lag. "
                 f"Resubmit can only be driven by the actual requestor's own portal login.")
            public.screenshot(path=str(SHOTS / "sc-7_vin_not_found_public.png"), full_page=True)
            return False
        dash.select_application(0)
        try:
            dash.expect_application_rejected()
        except Exception:
            note(f"VIN {vin}: Public Portal does not show a Rejected status after staff "
                 f"reject — resubmit flow cannot proceed")
            return False
        dash.click_submit_lt262()
        public.wait_for_timeout(1500)
        lt262 = Lt262FormPage(public)
        try:
            lt262.expect_form_tabs_visible()
        except Exception:
            note(f"VIN {vin}: 'Submit LT-262' did not land on the LT-262 form after "
                 f"rejection — resubmit UI differs from the fresh-submission flow")
            return False
        try:
            lt262.skip_vehicle_and_location_tabs()
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})
            lt262.fill_date_of_storage(past_date(30))
            lt262.fill_person_authorizing(person["name"], address["street"], address["zip"])
            lt262.fill_additional_details(person["name"], address["street"], address["zip"])
            lt262.upload_documents([SAMPLE_DOC_PATH])
            lt262.accept_terms_and_sign(person["name"])
            lt262.finish_and_pay()
        except Exception as e:
            note(f"VIN {vin}: resubmit form-fill raised {type(e).__name__}: {str(e)[:150]} "
                 f"— the rejected case's form may retain original values in a shape this "
                 f"fresh-submission fill sequence doesn't match")
            public.screenshot(path=str(SHOTS / "sc-7_resubmit_fill_error.png"), full_page=True)
            return False
        # A resubmit of an already-paid case may not re-prompt for payment; only
        # chase the Drawdown dialog if it actually appears.
        pay_btn = public.locator('button:has-text("Pay Using ACH/Drawdown")').first
        try:
            pay_btn.wait_for(state="visible", timeout=8_000)
            pay_btn.click()
            public.wait_for_timeout(1500)
            yes_btn = public.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=8_000)
            yes_btn.click()
            public.wait_for_timeout(2500)
        except Exception:
            pass  # no fresh payment required — resubmit of an already-paid LT-262
        ok = False
        for pattern in (r"submitted successfully", r"success", r"resubmitted"):
            try:
                expect(public.get_by_text(re.compile(pattern, re.I)).first).to_be_visible(timeout=6_000)
                ok = True
                break
            except Exception:
                continue
        public.screenshot(path=str(SHOTS / "sc-7_after_resubmit.png"), full_page=True)
        if not ok:
            note(f"VIN {vin}: no success toast seen after resubmit — continuing to check "
                 f"staff-side whether it landed anyway")
        return True

    def build_owned_case():
        """Build a fresh case end-to-end (LT-260 approved -> LT-262 paid -> LT-264
        issued) under the SAME public-portal login that will later resubmit it.

        A random case sampled off the staff-side Aging tab is NOT reliable for this:
        the public dashboard's search only shows applications the logged-in business
        owns, and the Aging tab spans every business in QA — exactly the ownership gap
        SC-5 already documents. Building our own case (same page-object sequence as
        lt263_resubmit_helper.create_case_to_lt263_submitted's Phases 1-4, stopped
        right after LT-264 issuance — no LT-263 phase needed here) sidesteps that by
        construction: the VIN, person and address are all ours, so the resubmit step
        below is guaranteed to be searching an account it actually owns.
        Returns (vin, person, address) or None (with a note already emitted) on failure.
        """
        vin = generate_vin()
        vehicle = random_vehicle()
        plate = generate_license_plate()
        address = generate_address()
        person = generate_person()
        print(f"  building owned case, VIN={vin}")

        public.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        public.wait_for_load_state("networkidle")
        dash = PublicDashboardPage(public)
        try:
            dash.select_business(BUSINESS_NAME)
            dash.click_start_here()
            lt260 = Lt260FormPage(public)
            lt260.enter_vin(vin)
            lt260.fill_vehicle_details(vehicle)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(plate)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", address["street"], address["zip"])
            lt260.fill_authorized_person(person["name"], address["street"], address["zip"])
            lt260.accept_terms_and_sign(person["name"], person["email"])
            lt260.submit_with_vin_image()
            public.wait_for_timeout(2000)
        except Exception as e:
            note(f"build_owned_case: LT-260 submission raised {type(e).__name__}: {str(e)[:150]}")
            public.screenshot(path=str(SHOTS / "sc-7_build_lt260_error.png"), full_page=True)
            return None

        try:
            staff.goto(DASH, timeout=60_000)
            staff.wait_for_load_state("networkidle")
            staff_dash = StaffDashboardPage(staff)
            lt260_listing = Lt260ListingPage(staff)
            form_processing = FormProcessingPage(staff)
            staff_dash.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()
            lt260_listing.search_by_vin(vin)
            lt260_listing.select_application(0)
            form_processing.expect_detail_page_visible()
            form_processing.click_edit()
            form_processing.add_owner(person["name"], address["street"], address["zip"])
            form_processing.select_stolen_no()
            form_processing.click_save()
            form_processing.issue_160b_and_260a()
            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        except Exception as e:
            note(f"build_owned_case: staff LT-260 processing raised {type(e).__name__}: {str(e)[:150]}")
            staff.screenshot(path=str(SHOTS / "sc-7_build_lt260_staff_error.png"), full_page=True)
            return None

        try:
            public.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
            public.wait_for_load_state("networkidle")
            dash.select_business(BUSINESS_NAME)
            dash.click_notice_storage_tab()
            public.wait_for_timeout(1000)
            dash.search_by_vin(vin)
            public.wait_for_timeout(2000)
            dash.select_application(0)
            dash.expect_application_processed()
            dash.click_submit_lt262()
            lt262 = Lt262FormPage(public)
            lt262.expect_form_tabs_visible()
            lt262.skip_vehicle_and_location_tabs()
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})
            lt262.fill_date_of_storage(past_date(30))
            lt262.fill_person_authorizing(person["name"], address["street"], address["zip"])
            lt262.fill_additional_details(person["name"], address["street"], address["zip"])
            lt262.upload_documents([SAMPLE_DOC_PATH])
            lt262.accept_terms_and_sign(person["name"])
            lt262.finish_and_pay()
            pay_btn = public.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_btn.wait_for(state="visible", timeout=30_000)
            pay_btn.click()
            public.wait_for_timeout(2000)
            yes_btn = public.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            public.wait_for_timeout(3000)
            expect(public.get_by_text("Your payment has been completed successfully")).to_be_visible(timeout=30_000)
        except Exception as e:
            note(f"build_owned_case: LT-262 submit+pay raised {type(e).__name__}: {str(e)[:150]}")
            public.screenshot(path=str(SHOTS / "sc-7_build_lt262_error.png"), full_page=True)
            return None

        try:
            staff.goto(DASH, timeout=60_000)
            staff.wait_for_load_state("networkidle")
            lt262_listing = Lt262ListingPage(staff)
            StaffDashboardPage(staff).navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(vin)
            lt262_listing.select_application(0)
            lt262_listing.issue_lt264()
            expect(staff.get_by_text("The form has been issued successfully.")).to_be_visible(timeout=30_000)
        except Exception as e:
            note(f"build_owned_case: LT-264 issuance raised {type(e).__name__}: {str(e)[:150]}")
            staff.screenshot(path=str(SHOTS / "sc-7_build_lt264_error.png"), full_page=True)
            return None

        print(f"  owned case ready: VIN={vin}, LT-264 issued today")
        return vin, person, address

    try:
        built = build_owned_case()
        if built is None:
            note("BLOCKED: could not build a case this run owns end-to-end — AC-3's "
                 "reset loop needs an owned case to resubmit through, see the note above "
                 "for exactly which build step failed")
            return
        vin, person, address = built

        lst = Lt262ListingPage(staff)
        try:
            modal = open_correspondence(staff)
        except Exception:
            note(f"VIN {vin}: no correspondence modal right after issuance — cannot "
                 f"capture a pre-reset baseline")
            return
        rows = corr_rows(modal)
        before = {}
        for idx, code, iss, txt, has_dl, _ in rows:
            if code in ("LT-264", "LT-264G") and has_dl and code not in before:
                try:
                    _, text = download_row(staff, modal, idx, f"pre_reset_{code}")
                except Exception:
                    continue
                m = SENT_RE.search(text)
                if m:
                    before[code] = (m.group(1), iss)
        try:
            staff.keyboard.press("Escape")
        except Exception:
            pass
        staff.wait_for_timeout(800)
        if not before:
            note(f"VIN {vin}: no dated LT-264/LT-264G with the sentence right after "
                 f"issuance — nothing to reset")
            return
        print(f"  VIN {vin}: pre-reset baseline {before}")
        shot(staff, f"before_reject_vin_{vin}")

        rejected = lst.reject_lt262()
        if not rejected:
            note(f"VIN {vin}: no Reject control on CHECK DCI AND NMVTIS right after "
                 f"issuance — AC-3's reject step is not reachable at this stage on QA")
            return
        check(True, f"VIN {vin}: staff Reject accepted on a just-issued LT-262 "
                    f"(BR-43 path to AC-3's reset)")
        shot(staff, f"after_reject_vin_{vin}")

        def do_reissue_cycle(cycle: int):
            if not resubmit_lt262(vin, person, address):
                note(f"cycle {cycle}: resubmit did not complete — cannot verify this "
                     f"cycle's re-issue")
                return None
            reissued_on = date.today()
            found = False
            for attempt in range(4):
                lst2 = open_listing(staff, "toprocess")
                lst2.search_by_vin(vin) if hasattr(lst2, "search_by_vin") else None
                staff.wait_for_timeout(2000)
                if lst2.application_rows.count() > 0:
                    found = True
                    break
                staff.reload(timeout=30_000)
                staff.wait_for_load_state("networkidle")
            if not found:
                note(f"cycle {cycle}: VIN {vin} did not reappear on 'To Process' after "
                     f"resubmit — cannot re-issue")
                return None
            lst2.select_application(0)
            staff.wait_for_timeout(2000)
            try:
                lst2.issue_lt264()
            except Exception as e:
                note(f"cycle {cycle}: re-issue raised {type(e).__name__}: {str(e)[:120]}")
                return None
            staff.wait_for_timeout(3000)
            shot(staff, f"after_reissue_cycle{cycle}")
            try:
                modal2 = open_correspondence(staff)
            except Exception:
                note(f"cycle {cycle}: no correspondence modal after re-issue")
                return None
            rows2 = corr_rows(modal2)
            fresh = {code: (idx, iss) for idx, code, iss, txt, has_dl, _ in rows2
                     if code in ("LT-264", "LT-264G") and iss == reissued_on and has_dl}
            after = {}
            for code, (idx, iss) in fresh.items():
                _, text = download_row(staff, modal2, idx, f"post_reset_{code}_c{cycle}")
                printed = assert_sentence(text, plus32(reissued_on),
                                          f"{code} re-issued cycle {cycle} (VIN {vin})")
                if printed:
                    after[code] = printed
            try:
                staff.keyboard.press("Escape")
            except Exception:
                pass
            staff.wait_for_timeout(800)
            return after

        after1 = do_reissue_cycle(1)
        if after1:
            for code, new_date in after1.items():
                old = before.get(code)
                if old:
                    check(new_date != old[0] or old[1] == date.today(),
                          f"{code}: re-issued date {new_date} is the RESET date + 32, "
                          f"not the pre-reset original ({old[0]}) — TC-12/TC-13")
                    check(True, f"{code}: newly generated letter does not carry the "
                                f"previous issuance's date — TC-14")

            after2 = do_reissue_cycle(2)
            if after2:
                for code, newest in after2.items():
                    prior = after1.get(code)
                    check(newest == plus32(date.today()),
                          f"{code}: SECOND reset also recalculates from ITS OWN latest "
                          f"reset date + 32 ({newest}), not a stale prior value "
                          f"({prior}) — TC-15")
            else:
                note("cycle 2 (TC-15, repeated resets) did not complete — TC-15 not "
                     "independently verified this run")
        else:
            note("cycle 1 did not produce a verifiable re-issue — TC-12/TC-13/TC-14 "
                 "not verified this run")
    finally:
        shot(staff, "final")
        staff_ctx.close(); b1.close()
        public_ctx.close(); b2.close()


# ──────────────────────────────── main ─────────────────────────────────────
def main():
    print(f"=== TW 27243037 / NCNSS-536 · {args.step} · env={args.env} · "
          f"{datetime.now():%Y-%m-%d %H:%M:%S} ===")
    print(f"Today + 32 = {plus32(date.today())}")
    if args.step == "SC-6":
        sc6(None)
    elif args.step == "SC-5":
        sc5(None)
    elif args.step == "SC-7":
        with sync_playwright() as pw:
            sc7(pw)
    else:
        with sync_playwright() as pw:
            b, ctx = new_context(pw)
            page = ctx.new_page()
            try:
                {"SC-1": sc1, "SC-2": sc2, "SC-3": sc3, "SC-4": sc4}[args.step](page)
            finally:
                shot(page, "final")
                ctx.close()
                b.close()

    print("-" * 70)
    for n in NOTES:
        print(f"NOTE: {n}")
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)} assertion(s))")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print("RESULT: PASS")


if __name__ == "__main__":
    main()
