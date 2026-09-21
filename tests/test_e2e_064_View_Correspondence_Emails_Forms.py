"""
E2E-064: View Correspondence — Emails & Forms

Cross-portal lifecycle test spanning the Public Portal and the Staff Portal, run
under the SECOND individual public user ("Bowers" — ENV.INDIVIDUAL_PUBLIC_USER_B_*,
whose registered inbox is bowers@mailinator.com), where every phase also verifies
the real correspondence EMAIL it triggered by opening the Mailinator public inbox
directly (go to mailinator.com → type the address → GO → open the message).

Phases (run in file order — each depends on the case state the previous one left):

  1.  [Public Portal]  Create & submit LT-260 (individual user — no business select).
                        Email check: "LT-260 Form Submitted for <VIN>".
  2.  [Staff Portal]   Process LT-260 — add owner, STOLEN = No, issue LT-160B / LT-260A;
                        reprint LT-160B & LT-260A and confirm a newer Date Issued
                        timestamp (dated today) is appended below the existing one.
                        Email check: "LT-160B Form Issued for <VIN>".
  3.  [Public Portal]  Submit LT-262 (skip the pre-filled A–E tabs) + supporting doc,
                        pay via ACH/Drawdown.
                        Email checks: "LT-262 Form Submitted for <VIN>" AND
                        "ACH Payment Received for LT-262 Form(s) in NSS" (VIN in body).
  4.  [Staff Portal]   Process LT-262 → CHECK DCI → issue LT-264; reprint LT-264 & LT-264G.
                        Email check: "LT-264 Form Issued for <VIN>".
  5.  [Staff Portal]   Track LT-264 — log receipt, judicial-hearing decision; reprint LT-264B.
                        Email checks: "LT-264B Form Issued for <VIN>" AND
                        "LT-263 Form Issued for <VIN>".
  5A. [Public Portal]  Submit LT-263 — sale type, sale date (today + 21d), lien amount.
                        Email check: "LT-263 Form Submitted for <VIN>".
  6.  [Staff Portal]   Review LT-263 (To Process) → Generate LT-265; reprint LT-265.
                        Email check: "LT-265 Form Issued for <VIN>".

Mailinator is a third-party public inbox with its own rate limiting. A missing
email is a real failure; only an explicit Mailinator rate-limit / unavailable
page makes the email step pytest.skip (infra, not an NSM defect) — the same
policy test_e2e_060_individual_registration.py uses.
"""

import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    past_date,
    generate_person,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage
from src.pages.staff_portal.sold_listing_page import SoldListingPage

# pytest -s pipes stdout straight to the console; on Windows that's cp1252, which
# can't encode glyphs that turn up in portal text / diagnostics (arrows, dashes,
# the header's decorative chars) — an otherwise-passing step then dies in a
# print(). Force UTF-8 with replacement, same guard scripts/submit_lt263.py uses.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ─── Shared test data ───
TEST_VIN = generate_vin()
VIN_RE = re.escape(TEST_VIN)
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# The individual "Bowers" account's registered inbox — a mailinator.com address.
USER_B_EMAIL = ENV.INDIVIDUAL_PUBLIC_USER_B_EMAIL

# Public Portal: use signin URL — with stored auth state it auto-redirects to dashboard
PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL

# Staff Portal dashboard URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def open_public_case_by_vin(dashboard, page):
    """Public dashboard → Notice & Storage tab → search this run's VIN → open row 0.
    Caller asserts the case's expected status afterwards."""
    dashboard.click_notice_storage_tab()
    page.wait_for_timeout(1000)
    dashboard.search_by_vin(TEST_VIN)
    page.wait_for_timeout(2000)
    dashboard.select_application(0)


# ─── Mailinator public-inbox verification ───────────────────────────────────

MAILINATOR_HOME = "https://www.mailinator.com"
_MAILINATOR_INBOX_URL = "https://www.mailinator.com/v4/public/inboxes.jsp?to={inbox}"


def _dismiss_mailinator_cookie_banner(page):
    """Best-effort dismissal of Mailinator's cookie-consent banner (never fatal)."""
    for sel in (
        ".osano-cm-accept-all",
        "#onetrust-accept-btn-handler",
        'button:has-text("Accept")',
        'button:has-text("AGREE")',
    ):
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1_000):
                btn.click(timeout=2_000)
                page.wait_for_timeout(400)
                return
        except Exception:
            pass


def _mailinator_rate_limited(page) -> bool:
    """True only when Mailinator itself is throwing a limit / outage page — a
    reachable-but-empty inbox is NOT this case (that stays a real failure)."""
    try:
        body = page.evaluate("() => document.body ? document.body.innerText : ''").lower()
    except Exception:
        body = ""
    return any(
        s in body
        for s in (
            "too many requests",
            "rate limit",
            "temporarily unavailable",
            "503 service",
            "error 429",
            "request blocked",
        )
    )


def _open_mailinator_inbox(page, email: str):
    """Follow the documented flow: open mailinator.com, type the address, click GO.

    Falls back to the direct public-inbox URL if the home-page form has changed or
    isn't reachable. Mailinator ignores the @domain part, but pass only the local
    part to be safe.
    """
    inbox = email.split("@", 1)[0]
    try:
        page.goto(MAILINATOR_HOME, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        _dismiss_mailinator_cookie_banner(page)
        field = page.locator(
            '#inbox_field, input[placeholder*="inbox" i], input[placeholder*="Team" i]'
        ).first
        field.wait_for(state="visible", timeout=8_000)
        field.fill(inbox)
        go_btn = page.locator('button:has-text("GO"), a:has-text("GO")').first
        if go_btn.count() and go_btn.is_visible():
            go_btn.click()
        else:
            page.keyboard.press("Enter")
        page.wait_for_url(re.compile(r"inboxes\.jsp", re.I), timeout=20_000)
    except Exception:
        page.goto(
            _MAILINATOR_INBOX_URL.format(inbox=inbox),
            timeout=60_000,
            wait_until="domcontentloaded",
        )
    # Give the Angular inbox time to render its rows.
    page.wait_for_timeout(3000)
    try:
        page.locator("tr").filter(has_text=re.compile(r"\S")).first.wait_for(
            state="visible", timeout=10_000
        )
    except Exception:
        pass


def _read_mailinator_message_body(page, row) -> str:
    """Open the given inbox row and return the rendered message body text.

    Mailinator renders the HTML body inside an iframe (#html_msg_body); a plain-text
    message uses #text_msg_body / #msg_body instead. Reading (not clicking any link
    in) the message keeps the flow on this one tab. `row` must be a locator that
    resolves live to a real, subject-matching message row (see verify_mailinator_emails)
    — never a bare positional tr, whose index drifts as the inbox re-renders.
    """
    try:
        row.scroll_into_view_if_needed(timeout=4_000)
    except Exception:
        pass
    try:
        row.click(timeout=15_000)
    except Exception:
        try:
            row.click(timeout=5_000, force=True)
        except Exception:
            return ""
    page.wait_for_timeout(3500)

    body = ""
    for fsel in ("#html_msg_body", "iframe#html_msg_body", "iframe[src*='fetchpublic']", "#msg_iframe"):
        try:
            frame = page.frame_locator(fsel)
            frame.locator("body").wait_for(state="attached", timeout=6_000)
            txt = frame.locator("body").inner_text()
            if txt.strip():
                body = txt
                break
        except Exception:
            continue

    if not body.strip():
        for sel in ("#text_msg_body", "#msg_body", "#pre_msg_body", ".message-body", "pre"):
            try:
                el = page.locator(sel).first
                if el.count() and el.is_visible():
                    txt = el.inner_text()
                    if txt.strip():
                        body = txt
                        break
            except Exception:
                continue
    return body


def verify_mailinator_emails(page, email, checks, retries: int = 12, wait_s: int = 12):
    """Confirm one Mailinator message per (subject_pattern, [body_patterns]) tuple.

    For every check, filter the inbox to rows whose visible text matches
    `subject_pattern` (a live locator — re-resolved on every action, so it never
    lands on Mailinator's invisible spacer <tr>s the way a positional .nth(i)
    does), open each visible match, and require every `body_pattern` to be present
    in the message body — so a check keyed on a subject that carries no VIN (the
    ACH-payment notification) still binds to THIS run by matching the VIN in the
    body. Re-polls up to `retries` times while mail is still in flight.

    Raises AssertionError if any check is unmet; pytest.skip only when Mailinator
    itself is rate-limiting / unavailable.
    """
    inbox = email.split("@", 1)[0]
    assert inbox, "INDIVIDUAL_PUBLIC_USER_B_EMAIL is not set — cannot verify emails"

    remaining = list(range(len(checks)))

    for attempt in range(retries):
        _open_mailinator_inbox(page, email)
        if _mailinator_rate_limited(page):
            pytest.skip(
                f"mailinator.com is rate-limiting / unavailable for inbox {inbox!r} — "
                "the inbox cannot be read. Mailinator infra limit, not an NSM defect."
            )

        for idx in list(remaining):
            subject_pattern, body_patterns = checks[idx]
            matches = page.locator("tr").filter(
                has_text=re.compile(subject_pattern, re.I)
            )
            for k in range(matches.count()):
                r = matches.nth(k)
                try:
                    if not r.is_visible():
                        continue
                except Exception:
                    continue
                body = _read_mailinator_message_body(page, r)
                if body and all(re.search(p, body, re.I) for p in body_patterns):
                    remaining.remove(idx)
                    break

        if not remaining:
            return
        if attempt < retries - 1:
            time.sleep(wait_s)

    missing = [checks[i][0] for i in remaining]
    raise AssertionError(
        f"Mailinator inbox {inbox!r}: no message satisfying {missing} after "
        f"{retries} passes (~{retries * wait_s}s)."
    )


def form_email(code: str, verb: str, body_phrase: str = None):
    """(subject_pattern, [body_patterns]) for an NSS "<form> Form <verb> for <VIN>"
    correspondence email. `verb` is "Submitted" or "Issued"; `body_phrase` overrides
    the in-body headline (issuance mails read "Issuance of LT-XXX")."""
    return (
        rf"LT-?{code} Form {verb} for {VIN_RE}",
        [body_phrase or rf"LT-?{code} Form {verb}", VIN_RE],
    )


def assert_emails(page, *checks):
    """Assert every (subject_pattern, [body_patterns]) check lands in Bowers'
    Mailinator inbox — see verify_mailinator_emails."""
    verify_mailinator_emails(page, USER_B_EMAIL, list(checks))


# ─── Correspondence-modal reprint verification ──────────────────────────────

def _open_correspondence_modal(page):
    """Click 'View Correspondence/Documents' and return the opened modal locator."""
    link = page.locator('//span[contains(text(),"View Correspondence/Documents")]').first
    link.wait_for(state="visible", timeout=25_000)
    link.click()
    page.wait_for_timeout(1500)
    modal = page.locator(".correspondence-modal, mat-dialog-container").first
    modal.wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(1800)
    return modal


def _correspondence_timestamps(modal, form_code: str):
    """Return (row_locator, [Date Issued timestamps, top-to-bottom]) for the first
    correspondence row matching `form_code` ('LT-160B', 'LT-264G', etc).

    A reprinted letter doesn't get its own new row — the new Date Issued timestamp
    is appended into the SAME row's cell, stacked below whatever was already there
    (confirmed live on QA 2026-08-21: an already-reprinted LT-260A row read
    "08-03-2026 04:33 AM08-20-2026 07:21 AM" — two timestamps run together in one
    cell, oldest first). So identifying a reprint means comparing timestamp COUNTS
    on the same row, not looking for a new row.
    """
    rows = modal.locator("table tbody tr")
    for i in range(rows.count()):
        row = rows.nth(i)
        txt = re.sub(r"[ \t]+", " ", row.text_content() or "").strip()
        if not txt:
            continue
        m = re.match(r"(LT-?\d+[A-Z]?)", txt)
        if not m:
            continue
        code = m.group(1).upper().replace("LT", "LT-").replace("LT--", "LT-")
        if code == form_code:
            timestamps = re.findall(r"\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}\s*[AP]M", txt)
            return row, timestamps
    return None, []


def verify_reprint_appends_newer_date(page, form_codes: list):
    """Open 'View Correspondence/Documents' and, for each code in `form_codes`,
    click 'Send for Reprinting' on its row and confirm the Date Issued cell now
    carries at least one new timestamp below whatever was already there, that
    everything already there is unchanged (only appended to, never reordered or
    rewritten), and that the newly appended timestamp(s) are dated today.

    Deliberately not asserting an exact "+1" count: on QA, some correspondence
    rows (LT-260A, confirmed live 2026-08-21) pick up extra timestamps beyond
    their own reprints. The three properties below are what the ask ("newest
    below the old, dated today") actually requires and hold regardless.
    """
    modal = _open_correspondence_modal(page)
    for code in form_codes:
        row, before = _correspondence_timestamps(modal, code)
        assert row is not None, f"No correspondence row found for {code}"

        reprint_btn = row.locator("span.table-link, a, button").filter(
            has_text=re.compile(r"reprint", re.I)
        ).first
        assert reprint_btn.count() > 0, f"{code}: no 'Send for Reprinting' control on its row"
        reprint_btn.scroll_into_view_if_needed()
        reprint_btn.click()
        page.wait_for_timeout(1500)
        for label in ("Yes", "Confirm", "Reprint", "Ok", "OK"):
            confirm_btn = page.locator(f'mat-dialog-container button:has-text("{label}")').first
            if confirm_btn.count() and confirm_btn.is_visible():
                confirm_btn.click()
                break
        page.wait_for_timeout(4000)

        # Close and reopen the modal so the freshly appended timestamp is loaded
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
        modal = _open_correspondence_modal(page)
        row_after, after = _correspondence_timestamps(modal, code)
        assert row_after is not None, f"{code}: correspondence row disappeared after reprinting"
        assert len(after) > len(before), (
            f"{code}: expected at least one new Date Issued timestamp after "
            f"reprinting (had {before}, now {after})"
        )
        assert after[: len(before)] == before, (
            f"{code}: existing timestamp(s) changed after reprinting — expected "
            f"the original(s) to stay put and only new ones appended below "
            f"(had {before}, now {after})"
        )
        today_str = datetime.now().strftime("%m-%d-%Y")
        new_entries = after[len(before):]
        assert all(ts.startswith(today_str) for ts in new_entries), (
            f"{code}: newly appended timestamp(s) {new_entries} are not dated "
            f"today ({today_str}) — expected a fresh reprint timestamp"
        )

    page.keyboard.press("Escape")
    page.wait_for_timeout(800)


# ─── LT-263 form-details helpers (Phase 5A) ─────────────────────────────────

def _satisfy_lt263_form_details(page, sale_date_str: str):
    """Fill any still-empty required / Angular-invalid control on the LT-263
    'Form Details' panel so its Next button can enable.

    Phase 5A's fixed fields (Type of Sale, Sale Date, Lien Amount) are the same as
    the proven lt263_resubmit_helper flow — but that flow runs against a business /
    garage case, which inherits extra first-tab values from facility data. An
    individual-user (Bowers) case can leave those blank, leaving Next disabled.
    This sweep is deliberately narrow: it only touches controls Material has
    flagged invalid, or that carry [required] / aria-required, and logs every fill.
    """
    panel = page.locator("mat-tab-body.mat-tab-body-active, form").first

    selects = panel.locator(
        'mat-select[required], mat-select[aria-required="true"], '
        'mat-form-field.mat-form-field-invalid mat-select'
    )
    for i in range(selects.count()):
        s = selects.nth(i)
        try:
            if not s.is_visible() or (s.inner_text() or "").strip():
                continue
            s.click()
            page.wait_for_timeout(400)
            opt = page.locator("mat-option").first
            if opt.count():
                label = (opt.inner_text() or "").strip()
                opt.click()
                page.wait_for_timeout(400)
                print(f"  [phase5a] filled required select -> {label!r}")
        except Exception:
            page.keyboard.press("Escape")

    fields = panel.locator(
        'input[required], input[aria-required="true"], textarea[required], '
        'mat-form-field.mat-form-field-invalid input, '
        'mat-form-field.mat-form-field-invalid textarea'
    )
    for i in range(fields.count()):
        f = fields.nth(i)
        try:
            if not f.is_visible() or not f.is_editable():
                continue
            if (f.input_value() or "").strip():
                continue
            hint = " ".join(
                (f.get_attribute(a) or "")
                for a in ("placeholder", "aria-label", "name", "formcontrolname")
            ).lower()
            if "date" in hint or "mm/dd" in hint or (f.get_attribute("type") == "date"):
                value = sale_date_str
            elif any(k in hint for k in ("amount", "fee", "cost", "value", "price")):
                value = "100"
            elif "time" in hint:
                value = "10:00 AM"
            elif "zip" in hint:
                value = "27601"
            else:
                value = "Raleigh"
            f.fill(value)
            page.wait_for_timeout(150)
            print(f"  [phase5a] filled required field ({hint.strip()!r}) -> {value!r}")
        except Exception:
            continue

    # Required checkbox groups (e.g. "Lien For *") live outside any mat-form-field,
    # so Material never marks them invalid — Next just stays disabled. If nothing
    # in the panel is checked, tick the first visible option.
    cbs = panel.locator("mat-checkbox")
    n_cb = cbs.count()
    if n_cb:
        any_checked = any(
            "mat-checkbox-checked" in (cbs.nth(i).get_attribute("class") or "")
            for i in range(n_cb)
        )
        if not any_checked:
            for i in range(n_cb):
                c = cbs.nth(i)
                try:
                    if c.is_visible():
                        c.locator("label").click()
                        page.wait_for_timeout(400)
                        print(f"  [phase5a] ticked first checkbox-group option "
                              f"({(c.inner_text() or '').strip()!r}) as safety net")
                        break
                except Exception:
                    continue

    page.keyboard.press("Tab")
    page.wait_for_timeout(600)


def _check_lien_for(page, option: str = "Storage"):
    """Tick one option in the LT-263 'Lien For *' required checkbox group
    (Labor / Materials / Towing / Storage / Other). Confirmed live on QA
    2026-08-31 as the sole reason Next stays disabled for an individual-user
    case — it is not wrapped in a mat-form-field, so it never surfaces as a
    mat-form-field-invalid. Storage matches the storage-lien nature of the case.
    """
    cb = page.locator("mat-checkbox").filter(
        has_text=re.compile(rf"^\s*{re.escape(option)}\s*$", re.I)
    ).first
    try:
        cb.wait_for(state="visible", timeout=10_000)
    except Exception:
        cb = page.locator(f'mat-checkbox:has-text("{option}")').first
        cb.wait_for(state="visible", timeout=10_000)
    if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
        cb.locator("label").click()
        page.wait_for_timeout(600)
        print(f"  [phase5a] Lien For -> {option} ticked")


def _dump_lt263_next_blockers(page) -> list:
    """Screenshot + list the Material fields still marked invalid on the LT-263
    Form Details panel, so a still-disabled Next fails with something actionable."""
    try:
        RESULTS_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(RESULTS_DIR / "e2e064_phase5a_next_disabled.png"))
    except Exception:
        pass
    labels = []
    inv = page.locator("mat-form-field.mat-form-field-invalid")
    for i in range(min(inv.count(), 20)):
        try:
            labels.append(re.sub(r"\s+", " ", inv.nth(i).inner_text() or "").strip()[:80])
        except Exception:
            pass
    print(f"  [phase5a] LT-263 Next still disabled - invalid fields: {labels}")
    return labels


@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.fixed
@pytest.mark.smoke
class TestE2E064ViewCorrespondenceEmailsForms:
    """E2E-064: LT-260 → LT-262 → LT-264 → LT-263 → LT-265 lifecycle, each phase
    cross-checked against the real correspondence email in Mailinator."""

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_create_lt260(self, individual_public_user_b_context: BrowserContext):
        """Phase 1: [Public Portal] user B (Bowers) — create LT-260, fill form, submit;
        then assert the "LT-260 Form Submitted" email lands in bowers@mailinator.com."""
        page = individual_public_user_b_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Individual user has no business selection — go straight to Start here
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)

            # Enter VIN (no VIN lookup — modal will appear at submit)
            lt260.enter_vin(TEST_VIN)

            # Fill vehicle details
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])

            # Fill authorized person (Tab 2)
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Accept terms and sign (Tab 3)
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            # Submit — VIN image modal appears at submit
            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)

            # Soft check — redirect back to dashboard may not always happen; don't fail the phase
            try:
                page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
            except Exception:
                print("  WARN: did not redirect back to dashboard after LT-260 submit - continuing")

            # Email check — "LT-260 Form Submitted for <VIN>"
            assert_emails(page, form_email("260", "Submitted"))
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Process LT-260, issue LT-160B / LT-260A
    # ========================================================================
    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] add owner, STOLEN = No, issue LT-160B / LT-260A,
        reprint both, then assert the "LT-160B Form Issued" email arrives."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            # Navigate to LT-260 listing → To Process tab
            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()

            # Search for our specific VIN
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)

            # Verify detail page loaded
            form_processing.expect_detail_page_visible()

            # Click Edit
            form_processing.click_edit()

            # Add owner under "Owner(s) Check"
            form_processing.add_owner(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Select STOLEN = No
            form_processing.select_stolen_no()

            # Save
            form_processing.click_save()

            # Issue LT-160B and LT-260A
            form_processing.issue_160b_and_260a()

            # Verify success toast and Processed status
            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()

            # View Correspondence → Send for Reprinting on LT-160B & LT-260A → the
            # Date Issued column gets a new (today-dated) timestamp appended below the old
            verify_reprint_appends_newer_date(page, ["LT-160B", "LT-260A"])

            # Email check — "LT-160B Form Issued for <VIN>"
            assert_emails(page, form_email("160B", "Issued", r"Issuance of LT-?160B"))
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Submit LT-262 & pay
    # ========================================================================
    def test_phase_3_public_portal_submit_lt262(self, individual_public_user_b_context: BrowserContext):
        """Phase 3: [Public Portal] submit LT-262 (skip pre-filled A–E), upload doc,
        pay via ACH/Drawdown; then assert the "LT-262 Form Submitted" and
        "ACH Payment Received for LT-262" emails arrive."""
        page = individual_public_user_b_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Individual user — no select_business(). Open the Phase 1 case.
            open_public_case_by_vin(dashboard, page)
            dashboard.expect_application_processed()

            # Click "Submit LT-262"
            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()

            # Skip the pre-filled inner tabs A, B, C, D, E via Next
            lt262.skip_prefilled_form_detail_tabs()

            # Fill Additional Details (advances off Tab E via its own Next)
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

            # Upload supporting document
            lt262.upload_documents([SAMPLE_DOC_PATH])

            # Accept terms and sign
            lt262.accept_terms_and_sign(PERSON["name"])

            # Finish and pay — redirects to cart page
            lt262.finish_and_pay()

            # Click "Pay Using ACH/Drawdown" on the cart page
            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            # Confirm drawdown modal: "Are you sure you want to use your Drawdown balance?"
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text("Your payment has been completed successfully")
            expect(success_banner).to_be_visible(timeout=30_000)

            # Verify redirect to dashboard (VIN then shows "LT-262 Submitted")
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)

            # Email checks — LT-262 submitted + ACH payment received (VIN bound via body)
            assert_emails(
                page,
                form_email("262", "Submitted"),
                (
                    r"ACH Payment Received for LT-?262 Form",
                    [r"ACH Payment Received for LT-?262 Form", r"Payment Amount\s*:\s*\$", VIN_RE],
                ),
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Process LT-262 → Issue LT-264
    # ========================================================================
    def test_phase_4_staff_portal_process_lt262(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] verify LT-262, CHECK DCI → Issue LT-264, reprint
        LT-264 & LT-264G; then assert the "LT-264 Form Issued" email arrives."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → To Process tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()

            # Search for our specific VIN
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify lien details on REVIEW LT-262 tab
            lt262_listing.verify_lien_details_visible()

            # Navigate to CHECK DCI AND NMVTIS → verify owner details
            lt262_listing.verify_owner_details_visible()

            # Issue LT-264 (clicks button → modal → Issue → success)
            lt262_listing.issue_lt264()

            # Issued banner (or auto-switch to TRACK LT-264) — waits out the issuance overlay
            lt262_listing.expect_lt264_issued()

            # Verify redirected to TRACK LT-264 tab
            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=10_000)

            # View Correspondence → Send for Reprinting on LT-264 & LT-264G
            verify_reprint_appends_newer_date(page, ["LT-264", "LT-264G"])

            # Email check — "LT-264 Form Issued for <VIN>"
            assert_emails(page, form_email("264", "Issued", r"Issuance of LT-?264\b"))
        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Staff Portal — Track LT-264, court hearings
    # ========================================================================
    def test_phase_5_staff_portal_track_lt264(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] log receipt of signed LT-264, judicial-hearing
        decision, reprint LT-264B; then assert the "LT-264B Form Issued" and
        "LT-263 Form Issued" emails arrive."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → find application in Aging tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_aging_tab()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(8000)
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.court_hearing_tab.click()
                page.wait_for_load_state("networkidle")
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            # Go to TRACK LT-264 tab
            lt262_listing.click_track_lt264_tab()
            page.wait_for_timeout(2000)

            # Check checkbox under "Log Receipt of Signed LT-264 Letters"
            log_receipt_cb = page.locator('mat-checkbox').first
            if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
                log_receipt_cb.locator("label").click()
                page.wait_for_timeout(1000)

            # Second checkbox appears after first is checked — "Select recipients requesting judicial hearing"
            hearing_cb = page.locator('mat-checkbox').nth(1)
            hearing_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
                hearing_cb.locator("label").click()
                page.wait_for_timeout(500)

            # Click Save (enabled after checking boxes on TRACK LT-264)
            save_btn = page.locator('button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=30_000)
            save_btn.scroll_into_view_if_needed()
            save_btn.click()
            page.wait_for_timeout(2000)

            # Confirm modal — click Yes
            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Wait for redirect to REVIEW COURT HEARINGS — wait for its unique content
            possessory_text = page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
            # TRACK Save generates LT-264B under the loading overlay — can exceed 30s on a loaded QA
            Lt262ListingPage(page).wait_for_loader_gone()
            possessory_text.wait_for(state="visible", timeout=60_000)
            page.wait_for_timeout(2000)

            # Check "Judgment in action of Possessory Lien" checkbox
            possessory_cb = page.locator('mat-checkbox').first
            possessory_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
                possessory_cb.locator("label").click()
                page.wait_for_timeout(1000)

            # Click Save (enabled after checking the checkbox)
            save_btn2 = page.locator('button:has-text("Save")').first
            save_btn2.wait_for(state="visible", timeout=30_000)
            save_btn2.scroll_into_view_if_needed()
            save_btn2.click()
            page.wait_for_timeout(2000)

            # Confirm modal — click Yes
            yes_btn2 = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn2.wait_for(state="visible", timeout=10_000)
            yes_btn2.click()
            page.wait_for_timeout(3000)

            # Verify green success banner
            success_banner = page.get_by_text(re.compile(r"success", re.I)).first
            expect(success_banner).to_be_visible(timeout=30_000)

            # Click Next button (appears after successful save)
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=30_000)
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            # Verify modal with waiting message
            waiting_msg = page.get_by_text("Waiting for the requester to submit LT-263.")
            expect(waiting_msg).to_be_visible(timeout=10_000)

            # Dismiss the waiting-message dialog so it doesn't block the correspondence link
            ok_btn = page.locator(
                'mat-dialog-container button:has-text("OK"), mat-dialog-container button:has-text("Close")'
            ).first
            if ok_btn.count() and ok_btn.is_visible():
                ok_btn.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

            # View Correspondence → Send for Reprinting on LT-264B
            verify_reprint_appends_newer_date(page, ["LT-264B"])

            # Email checks — LT-264B issued + LT-263 issued (form made available to requester)
            assert_emails(
                page,
                form_email("264B", "Issued", r"Issuance of LT-?264B"),
                form_email("263", "Issued", r"Issuance of LT-?263"),
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 5A: Public Portal — Submit LT-263
    # ========================================================================
    def test_phase_5a_public_portal_submit_lt263(self, individual_public_user_b_context: BrowserContext):
        """Phase 5A: [Public Portal] submit LT-263 — sale type, sale date, lien amount;
        then assert the "LT-263 Form Submitted" email arrives."""
        page = individual_public_user_b_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            # Individual user — no select_business(). Open the case.
            open_public_case_by_vin(dashboard, page)

            # Verify status is "LT-262 Processed" and Submit LT-263 button is available
            expect(page.get_by_text(re.compile(r"LT-262 Processed", re.I)).first).to_be_visible(timeout=30_000)
            dashboard.expect_lt263_available()

            # Click "Submit LT-263"
            dashboard.click_submit_lt263()
            page.wait_for_timeout(2000)

            # Verify LT-263 form page
            expect(page.get_by_text(re.compile(r"LT-263.*Form Details", re.I)).first).to_be_visible(timeout=30_000)

            # Select "Type of Sale" → Public
            sale_type_dropdown = page.locator('mat-select[aria-label*="Type of Sale" i]').first
            try:
                sale_type_dropdown.wait_for(state="visible", timeout=5_000)
                sale_type_dropdown.click()
                page.wait_for_timeout(500)
                page.locator('mat-option:has-text("Public")').first.click()
                page.wait_for_timeout(500)
            except Exception:
                # Fallback: may be radio buttons instead of dropdown
                lt263 = Lt263FormPage(page)
                lt263.select_public_sale()

            # Enter Sale Date (21 days from today in MM/DD/YYYY format)
            sale_date = (datetime.now() + timedelta(days=21)).strftime("%m/%d/%Y")
            sale_date_input = page.locator(
                'input[aria-label*="Sale Date" i], input[placeholder*="MM/DD/YYYY"]'
            ).first
            sale_date_input.wait_for(state="visible", timeout=10_000)
            sale_date_input.fill(sale_date)
            page.wait_for_timeout(500)

            # Enter Lien Amount
            lien_amount_input = page.locator(
                'input[aria-label*="Lien Amount" i], input[name*="lien" i][name*="amount" i]'
            ).first
            lien_amount_input.wait_for(state="visible", timeout=10_000)
            lien_amount_input.fill("800")
            page.wait_for_timeout(500)

            # "Lien For *" — required checkbox group (Labor/Materials/Towing/Storage/
            # Other), outside any mat-form-field so it never flags invalid; unticked
            # it silently keeps Next disabled for an individual-user case.
            _check_lien_for(page, "Storage")

            # Next can still be disabled for an individual-user case if another
            # first-tab field that a garage case inherits from facility data is left
            # blank (Sale Time, etc.) — fill any such required/invalid control, then
            # wait for Next to enable.
            next_btn = page.locator('button:has-text("Next")').first
            next_btn.wait_for(state="visible", timeout=30_000)
            if not next_btn.is_enabled():
                _satisfy_lt263_form_details(page, sale_date)
            try:
                expect(next_btn).to_be_enabled(timeout=20_000)
            except AssertionError:
                labels = _dump_lt263_next_blockers(page)
                raise AssertionError(
                    "Phase 5A: LT-263 'Next' never enabled after filling Type of Sale, "
                    f"Sale Date, Lien Amount and every flagged required field. Still-invalid "
                    f"fields: {labels or 'none reported by Material'}. "
                    f"Screenshot: results/e2e064_phase5a_next_disabled.png"
                )
            next_btn.scroll_into_view_if_needed()
            next_btn.click()
            page.wait_for_timeout(2000)

            # Terms and Conditions page — check all checkboxes
            expect(page.get_by_text(re.compile(r"Terms and Conditions", re.I)).first).to_be_visible(timeout=30_000)

            mat_checkboxes = page.locator('mat-checkbox')
            cb_count = mat_checkboxes.count()
            for i in range(cb_count):
                cb = mat_checkboxes.nth(i)
                if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
                    cb.locator("label").click()
                    page.wait_for_timeout(200)

            # Fill Name field
            name_input = page.locator(
                'input[aria-label*="Name" i], input[aria-label*="NAME" i]'
            ).first
            name_input.wait_for(state="visible", timeout=10_000)
            name_input.fill(PERSON["name"])

            # Fill Date field
            date_input = page.locator(
                'input[aria-label*="Date" i], input[aria-label*="DATE" i]'
            ).first
            try:
                date_input.wait_for(state="visible", timeout=5_000)
                date_value = date_input.input_value()
                if not date_value:
                    date_input.fill(datetime.now().strftime("%m/%d/%Y"))
            except Exception:
                pass

            # Click Submit
            submit_btn = page.locator('button:has-text("Submit")').first
            submit_btn.wait_for(state="visible", timeout=30_000)
            submit_btn.scroll_into_view_if_needed()
            submit_btn.click()
            page.wait_for_timeout(3000)

            # Soft check — banner is transient and may be missed in CI
            try:
                success_banner = page.get_by_text(re.compile(r"Form is submitted successfully", re.I)).first
                expect(success_banner).to_be_visible(timeout=30_000)
            except Exception:
                print("  WARN: 'Form is submitted successfully' banner not seen - continuing")

            # Soft check — this page does NOT auto-redirect after submit (it stays on
            # the LT-263 form with Submit now disabled), and the public dashboard's
            # own status search is documented to lag by over a minute. The email
            # check below and Phase 6 (staff sees the LT-263 in 'To Process') are the
            # authoritative "it submitted" signals.
            go_to_public_dashboard(page)
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1500)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            try:
                expect(
                    page.get_by_text(re.compile(r"LT-263 (Submitted|Processed)", re.I)).first
                ).to_be_visible(timeout=30_000)
            except Exception:
                print("  WARN: dashboard did not yet show 'LT-263 Submitted' for the VIN - "
                      "continuing (dashboard status is known to lag; email + Phase 6 verify it)")

            # Email check — "LT-263 Form Submitted for <VIN>"
            assert_emails(page, form_email("263", "Submitted"))
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Staff Portal — Review LT-263, Generate LT-265
    # ========================================================================
    def test_phase_6_staff_portal_process_lt263(self, staff_context: BrowserContext):
        """Phase 6: [Staff Portal] verify LT-263 sale details, Generate LT-265,
        reprint LT-265; then assert the "LT-265 Form Issued" email arrives."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)

            # Navigate to LT-263 listing → To Process tab
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()

            # Search for our VIN and select the application
            lt263_listing.search_by_vin(TEST_VIN)
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)

            # Verify sale details are visible on detail page
            lt263_listing.verify_sale_details_visible()
            lt263_listing.verify_lien_amount_visible()

            # Generate LT-265 (clicks body button → Issue modal → confirmation modal → OK)
            lt263_listing.generate_lt265(expected_vin=TEST_VIN)
            page.wait_for_timeout(3000)

            # The LT-265 correspondence row + its 'View Correspondence/Documents'
            # link live on the Sold-listing detail page (the case is now Sold), NOT
            # on the LT-263 To-Process detail page we generated it from. Hop there.
            sold_listing = SoldListingPage(page)
            for attempt in range(4):
                staff_dashboard.navigate_to_sold()
                sold_listing.search_by_vin(TEST_VIN)
                try:
                    sold_listing.expect_applications_visible()
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    print(f"  [phase6] VIN not on Sold listing yet (attempt {attempt + 1}/4) - waiting")
                    page.wait_for_timeout(10_000)
            sold_listing.select_application(0)

            # View Correspondence → Send for Reprinting on LT-265
            verify_reprint_appends_newer_date(page, ["LT-265"])

            # Email check — "LT-265 Form Issued for <VIN>"
            assert_emails(page, form_email("265", "Issued"))
        finally:
            page.close()
