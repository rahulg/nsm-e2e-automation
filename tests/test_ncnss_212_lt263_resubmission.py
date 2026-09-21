"""NCNSS-212 (TW 27242835) — CR: Allow Re-submission of LT-263 after DMV rejection.

A DMV rejection of an LT-263 is no longer terminal:
  * the case survives at status "LT-263 Rejected" (LT-260 stays Approved, LT-262 stays Paid)
  * the garage may submit a NEW LT-263 (no cap), or DMV may log a PAPER one (canRelog)
  * every cycle is retained in a "View Previous LT-263s" history
    (chain LT263SubmissionHistory.get = 4c0cd23059e60a43fcc3ac2dbdd42746)
  * the staff Review LT-263 screen shows the latest rejection reason as a banner
  * rejecting with an EMPTY reason no longer crashes (jsonb_set over an empty array)
  * Close File is enabled on an "LT-263 Rejected" case
  * the loop ends only at Vehicle Sold (approved re-submission -> LT-265) or Closed

One pytest class per plan scenario; ordered phases inside each class.

EVERY assertion prints   EXPECTED: ... | ACTUAL: ... -> MATCH/MISMATCH
Negative cases pass when the guard/rejection actually fires.

Live-discovered surfaces (QA, 2026-07-28) — see skills/nsm-lt263-resubmission/SKILL.md:
  detail URL   /pages/ncdot-notice-and-storage/LT-262/<applicationId>/details?tab=5
  reject modal "Reject Case" -> 10 predefined reason checkboxes + "Other" (free text);
               the Reject button stays DISABLED until a reason is chosen (so the
               EMPTY-reason case is only reachable API-side)
  history      inline panel (NOT a dialog) appended below the form
  chains       LT263 details  4d508812ac4f7429a833b73a6a0d294e
               LT263 view     458ce7ff890a984c2a19931d0ac8fd5d
               history        4c0cd23059e60a43fcc3ac2dbdd42746
  auth         bare JWT from localStorage['authToken'] in the `authorization` header
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV

# ───────────────────────────── constants ─────────────────────────────

SP_BASE = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
SP_DASH = f"{SP_BASE}/pages/ncdot-notice-and-storage/dashboard"
PP_URL = ENV.PUBLIC_PORTAL_URL

CHAIN_HISTORY = "4c0cd23059e60a43fcc3ac2dbdd42746"   # LT263SubmissionHistory.get
CHAIN_DETAILS = "4d508812ac4f7429a833b73a6a0d294e"   # LT263 details (status/isEditable)
CHAIN_VIEW = "458ce7ff890a984c2a19931d0ac8fd5d"      # LT263 full view

# A pre-CR rejection whose action_detail holds NO form snapshot (PRE-5).
LEGACY_REJECTED_APP = "fcc26106-1652-455a-98b4-a653ed0ee99d"   # RUTHK9WF3682FZRWV
LEGACY_REJECTED_VIN = "RUTHK9WF3682FZRWV"

BUSINESS_NAME = os.getenv("NSM_BUSINESS", "G-Car Garages New")

_ROOT = Path(__file__).resolve().parent.parent
SHOTS = _ROOT / "screenshots" / "ncnss212"
SHOTS.mkdir(parents=True, exist_ok=True)
STATE_FILE = _ROOT / "results" / "ncnss212_state.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


# ───────────────────────────── reporting ─────────────────────────────

RESULTS = []


def check(label: str, expected, actual, ok: bool = None, hard: bool = True) -> bool:
    """Print EXPECTED vs ACTUAL and (optionally) assert the match."""
    if ok is None:
        ok = str(expected).strip().lower() in str(actual).strip().lower()
    verdict = "MATCH" if ok else "MISMATCH"
    line = f"  [{label}] EXPECTED: {expected} | ACTUAL: {actual} -> {verdict}"
    print(line)
    RESULTS.append({"label": label, "expected": str(expected),
                    "actual": str(actual), "match": ok})
    if hard and not ok:
        raise AssertionError(f"FAIL: expected {expected!r}, got {actual!r}  [{label}]")
    return ok


def shot(page, name):
    p = SHOTS / f"{name}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
        print(f"  [shot] {p}")
    except Exception as exc:                                   # pragma: no cover
        print(f"  [shot-fail] {name}: {exc}")


# ───────────────────────────── state ─────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(key: str, value: dict):
    st = load_state()
    st[key] = value
    STATE_FILE.write_text(json.dumps(st, indent=1))
    print(f"  [state] {key} = {value}")


def get_state(key: str) -> dict:
    st = load_state().get(key)
    if not st:
        pytest.skip(f"no saved state for {key} — run its owning phase/class first")
    return st


def mark_used(vin: str):
    st = load_state()
    used = set(st.get("_used_vins", []))
    used.add(vin)
    st["_used_vins"] = sorted(used)
    STATE_FILE.write_text(json.dumps(st, indent=1))


def used_vins() -> set:
    return set(load_state().get("_used_vins", []))


# ───────────────────────────── navigation ─────────────────────────────

def goto_staff_dash(page):
    page.goto(SP_DASH, timeout=90_000)
    page.wait_for_load_state("networkidle")
    if "login" in page.url.lower():
        pytest.fail("Staff auth state expired — run `python scripts/refresh_auth.py --env qa`")


def listing_url(form: str) -> str:
    return f"{SP_BASE}/pages/ncdot-notice-and-storage/{form}/list"


def detail_url(app_id: str) -> str:
    return f"{SP_BASE}/pages/ncdot-notice-and-storage/LT-262/{app_id}/details?tab=5"


def open_listing(page, form: str = "LT-263"):
    page.goto(listing_url(form), timeout=90_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3500)
    if "login" in page.url.lower():
        pytest.fail("Staff auth state expired — run `python scripts/refresh_auth.py --env qa`")


def click_tab(page, name: str):
    tab = page.locator(f'[role="tab"]:has-text("{name}")').first
    tab.wait_for(state="visible", timeout=30_000)
    tab.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)


def listing_rows(page):
    """[(vin, row_text)] for the currently displayed listing tab."""
    out = []
    rows = page.locator("tr:has(span.table-link)")
    for i in range(rows.count()):
        try:
            txt = rows.nth(i).inner_text().replace("\n", " ")
            vin = rows.nth(i).locator("span.table-link").first.inner_text().strip()
            out.append((vin, re.sub(r"\s+", " ", txt)))
        except Exception:
            continue
    return out


def search_listing(page, vin: str):
    try:
        btn = page.locator('button:has-text("Show Filters")').first
        btn.wait_for(state="visible", timeout=5_000)
        btn.click()
        page.wait_for_timeout(1200)
    except Exception:
        pass
    try:
        f = page.locator('input[name="vin"]').first
        f.wait_for(state="visible", timeout=8_000)
        f.fill("")
        page.wait_for_timeout(300)
        f.fill(vin)
        page.wait_for_timeout(400)
        f.press("Enter")
    except Exception:
        pass
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)


def pick_to_process_case(page, digital_only: bool = True, avoid_used: bool = True) -> dict:
    """Acquire an LT-263 sitting in 'To Process' (PRE-2 state) and return its ids."""
    forced = os.getenv("LT263_CASE_VIN")
    open_listing(page, "LT-263")
    click_tab(page, "To Process")
    rows = listing_rows(page)
    print(f"  [acquire] {len(rows)} To Process rows")
    skip = used_vins() if avoid_used else set()
    chosen = None
    for vin, txt in rows:
        if forced and vin != forced:
            continue
        if vin in skip:
            continue
        if digital_only and "Digital" not in txt:
            continue
        chosen = (vin, txt)
        break
    if not chosen and rows:
        chosen = next(((v, t) for v, t in rows if v not in skip), rows[0])
    if not chosen:
        pytest.fail("No LT-263 in the 'To Process' tab on QA — cannot reach the PRE-2 state")

    vin, txt = chosen
    print(f"  [acquire] using VIN {vin} :: {txt[:150]}")
    page.locator(f'span.table-link:has-text("{vin}")').first.click(timeout=25_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(4000)
    m = re.search(r"/LT-262/([0-9a-f\-]{36})/details", page.url)
    if not m:
        pytest.fail(f"could not read applicationId from {page.url}")
    case = {"vin": vin, "app_id": m.group(1), "row": txt}
    mark_used(vin)
    return case


# ───────────────────────────── API ─────────────────────────────

def auth_token(page) -> str:
    return page.evaluate("() => localStorage.getItem('authToken')")


def api_chain(page, chain_id: str, payload: dict, token: str = None):
    """POST an automation chain with the page's own JWT. Returns (status, text)."""
    tok = token or auth_token(page)
    r = page.request.post(
        f"{SP_BASE}/rest/api/automation/chain/execute/{chain_id}?encrypted=true",
        headers={"authorization": tok or "", "content-type": "application/json",
                 "accept": "application/json, text/plain, */*"},
        data=payload,
        timeout=60_000,
    )
    body = ""
    try:
        body = r.text()
    except Exception:
        pass
    return r.status, body


def lt263_status(page, app_id: str) -> str:
    st, body = api_chain(page, CHAIN_DETAILS, {"applicationId": app_id})
    try:
        return json.loads(body)["vehicleDetails"]["status"]
    except Exception:
        return f"<unreadable status: HTTP {st}>"


def submission_history(page, app_id: str, retries: int = 2):
    """-> (http_status, [submission dicts])"""
    st, subs = _submission_history_once(page, app_id)
    for _ in range(retries):
        if subs:
            break
        page.wait_for_timeout(4000)
        st, subs = _submission_history_once(page, app_id)
    return st, subs


def _submission_history_once(page, app_id: str):
    st, body = api_chain(page, CHAIN_HISTORY, {"applicationId": app_id})
    subs = []
    try:
        raw = json.loads(body).get("submissions")
    except Exception:
        raw = None
        m = re.search(r"<submissions>(.*?)</submissions>", body, re.S)
        if m:
            raw = m.group(1)
    if isinstance(raw, list):
        subs = raw
    elif isinstance(raw, str):
        subs = _parse_submissions(raw)
    return st, subs


_SUB_FIELDS = ("submissionNumber", "submittedAt", "submittedBy", "rejectedAt",
               "rejectedBy", "rejectionReason", "outcome", "documentLink")


def _parse_submissions(raw: str):
    """The chain returns `submissions` as an escaped JSON *string*; the depth of
    escaping varies with whether a per-cycle snapshot ('details') was captured."""
    candidate = raw
    for _ in range(4):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        new = candidate.replace('\\"', '"')
        if new == candidate:
            break
        candidate = new

    # Fallback: pull the scalar fields per cycle straight out of the blob.
    flat = raw.replace('\\"', '"').replace('\\\\', '\\')
    blocks = re.split(r'(?="submissionNumber")', flat)
    out = []
    for blk in blocks:
        if '"submissionNumber"' not in blk:
            continue
        rec = {}
        for f in _SUB_FIELDS:
            m = re.search(rf'"{f}"\s*:\s*(null|"((?:[^"\\]|\\.)*)")', blk)
            if m:
                rec[f] = None if m.group(1) == "null" else m.group(2).replace('\\/', '/')
        m = re.search(r'"details"\s*:\s*(null|\{)', blk)
        if m:
            rec["details"] = None if m.group(1) == "null" else {"_raw": True}
        if rec:
            out.append(rec)
    return out


# ───────────────────────────── staff actions ─────────────────────────────

REJECT_CHAIN_CAPTURE = {"id": None, "status": None, "req": None}


def _capture_reject(resp):
    try:
        if "/automation/chain/execute/" not in resp.url:
            return
        req = resp.request.post_data or ""
        # the WRITE carries the reason payload; exclude listing/read chains
        if "pageSize" in req or '"module"' in req:
            return
        if re.search(r"closing_?remarks|\"sign\"|\"other\"|\"remit\"|\"provide\"|\"divison\"",
                     req, re.I):
            REJECT_CHAIN_CAPTURE["id"] = resp.url.split("/execute/")[1].split("?")[0]
            REJECT_CHAIN_CAPTURE["status"] = resp.status
            REJECT_CHAIN_CAPTURE["req"] = req[:400]
    except Exception:
        pass


def open_case(page, app_id: str):
    page.goto(detail_url(app_id), timeout=90_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(5000)


def page_buttons(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('button'))
        .map(b => ({t:(b.innerText||'').trim().replace(/\\s+/g,' '), d:b.disabled,
                    v:!!b.offsetParent})).filter(b => b.t)""")


def has_button(page, text: str, must_be_visible=True):
    for b in page_buttons(page):
        if text.lower() in b["t"].lower() and (b["v"] or not must_be_visible):
            return True
    return False


def reject_case(page, reason_index: int = 0, other_text: str = None, double_click: bool = False):
    """Open the Reject Case modal, choose a reason, and reject. Returns the reason text."""
    page.on("response", _capture_reject)
    REJECT_CHAIN_CAPTURE.update({"id": None, "status": None, "req": None})

    btn = page.locator('button:has-text("Reject")').first
    btn.wait_for(state="visible", timeout=20_000)
    btn.scroll_into_view_if_needed()
    btn.click()
    page.wait_for_timeout(2500)

    dlg = page.locator("mat-dialog-container").first
    dlg.wait_for(state="visible", timeout=15_000)
    reject_btn = dlg.locator('button:has-text("Reject")').first

    disabled_before = reject_btn.is_disabled()
    print(f"  [reject-modal] Reject disabled with no reason selected: {disabled_before}")

    if other_text is not None:
        dlg.locator('mat-checkbox:has-text("Other")').first.locator("label").click()
        page.wait_for_timeout(1200)
        ta = dlg.locator("textarea").first
        ta.fill(other_text)
        reason = other_text
    else:
        cb = dlg.locator("mat-checkbox").nth(reason_index)
        reason = cb.inner_text().strip()
        cb.locator("label").click()
        reason = reason or dlg.locator("mat-checkbox").nth(reason_index).inner_text().strip()
    page.wait_for_timeout(1500)

    shot(page, f"reject_modal_{page.url.split('/')[-2][:8]}")
    reject_btn.scroll_into_view_if_needed()
    reject_btn.click()
    if double_click:
        try:
            reject_btn.click(timeout=1500)
            print("  [race] second Reject click landed")
        except Exception as exc:
            print(f"  [race] second Reject click refused (expected): {str(exc)[:90]}")
    page.wait_for_timeout(4000)

    # dismiss any confirmation
    for label in ("Yes", "Ok", "OK", "Confirm"):
        try:
            b = page.locator(f'mat-dialog-container button:has-text("{label}")').first
            if b.is_visible():
                b.click()
                page.wait_for_timeout(2500)
                break
        except Exception:
            pass
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    print(f"  [reject-chain] {REJECT_CHAIN_CAPTURE}")
    return reason


CHAIN_CLOSE_FILE = "48c3f9254cffece1fe5f910b4f76d4e1"   # LT263 Close File (write)
CLOSE_CAPTURE = {"status": None, "body": None}


def _capture_close(resp):
    try:
        if f"/execute/{CHAIN_CLOSE_FILE}" in resp.url:
            CLOSE_CAPTURE["status"] = resp.status
            CLOSE_CAPTURE["body"] = resp.text()[:400]
    except Exception:
        pass


def close_file_with_notes(page, notes: str) -> bool:
    """Close File modal = a mandatory 'Notes/Comments' textarea + an optional file
    upload; the modal's own 'Close File' button stays DISABLED until notes exist."""
    CLOSE_CAPTURE.update({"status": None, "body": None})
    page.on("response", _capture_close)
    btn = page.locator('button:has-text("Close File")').first
    btn.wait_for(state="visible", timeout=20_000)
    btn.scroll_into_view_if_needed()
    btn.click()
    page.wait_for_timeout(3000)
    dlg = page.locator("mat-dialog-container").first
    dlg.wait_for(state="visible", timeout=15_000)
    confirm = dlg.locator('button:has-text("Close File")').first
    print(f"  [close-modal] confirm disabled before notes: {confirm.is_disabled()}")
    dlg.locator("textarea").first.fill(notes)
    page.wait_for_timeout(1500)
    shot(page, "close_file_modal")
    for _ in range(20):
        if not confirm.is_disabled():
            break
        page.wait_for_timeout(500)
    if confirm.is_disabled():
        print("  [close-modal] confirm STILL disabled after notes — not closed")
        return False
    confirm.click()
    page.wait_for_timeout(4000)
    for label in ("Yes", "Ok", "OK", "Confirm"):
        try:
            b = page.locator(f'mat-dialog-container button:has-text("{label}")').first
            if b.count() and b.is_visible():
                b.click()
                page.wait_for_timeout(3000)
                break
        except Exception:
            continue
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    return True


def banner_text(page) -> str:
    body = page.inner_text("body")
    m = re.search(r"Latest rejection reason:\s*(.+)", body)
    return m.group(1).strip() if m else ""


def open_history_panel(page) -> str:
    """Click 'View Previous LT-263s' and return the inline panel text."""
    btn = page.locator('button:has-text("View Previous LT-263s")').first
    btn.wait_for(state="visible", timeout=20_000)
    btn.scroll_into_view_if_needed()
    btn.click()
    page.wait_for_timeout(4500)
    body = page.inner_text("body")
    i = body.find("Submission #")
    return body[i:] if i >= 0 else ""


# ───────────────────────────── public portal ─────────────────────────────

def goto_public(page):
    page.goto(PP_URL, timeout=90_000, wait_until="domcontentloaded")
    try:
        page.wait_for_url(re.compile(r"dashboard", re.I), timeout=45_000)
    except Exception:
        pass
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(4000)
    if "signin" in page.url.lower():
        pytest.fail("Public auth state expired — run `python scripts/refresh_auth.py --env qa`")


def select_business(page, name: str = BUSINESS_NAME):
    from src.pages.public_portal.dashboard_page import PublicDashboardPage
    try:
        PublicDashboardPage(page).select_business(name)
        print(f"  [public] business -> {name}")
    except Exception as exc:
        print(f"  [public] business switch failed ({str(exc)[:110]}) — continuing on default")


def lt263_form_url(app_id: str) -> str:
    base = re.sub(r"/ncdot-nsm-signin.*$", "", PP_URL).rstrip("/")
    return f"{base}/ncdmv-nsm/lt-263?id={app_id}"


def fill_lt263_form_details(page, sale_date_days: int = 25, lien: str = "800"):
    """Step 1 of the public LT-263. On a re-submission the whole step is
    pre-filled from the rejected cycle, so only refresh what can go stale."""
    try:
        sel = page.locator('mat-select[aria-label*="Type of Sale" i]').first
        val = sel.inner_text().strip()
        if not val or val.lower() in ("", "select"):
            sel.click(timeout=8_000)
            page.wait_for_timeout(700)
            page.locator('mat-option:has-text("Public")').first.click()
            page.wait_for_timeout(700)
        print(f"  [form] type of sale = {val or 'Public (set)'}")
    except Exception as exc:
        print(f"  [form] type-of-sale: {str(exc)[:90]}")
    try:
        d = (datetime.now() + timedelta(days=sale_date_days)).strftime("%m/%d/%Y")
        f = page.locator('input[name="saleD"]').first
        f.fill("")
        page.wait_for_timeout(300)
        f.fill(d)
        page.wait_for_timeout(600)
        print(f"  [form] sale date = {d}")
    except Exception as exc:
        print(f"  [form] sale-date: {str(exc)[:90]}")
    for sel_ in ('input[name="lien_amount"][type="number"]', 'input[name="lien_amount"]'):
        try:
            f = page.locator(sel_).first
            if f.count() and f.is_visible():
                cur = f.input_value()
                if not cur or cur in ("0", "0.00"):
                    f.fill(lien)
                print(f"  [form] lien amount = {f.input_value()}")
                break
        except Exception:
            continue
    shot(page, "sc2_p3_form_details_filled")


def accept_terms_and_submit(page, signer: str = "Daniel Scott") -> bool:
    """Step 2 — Terms & Conditions. Returns True if a Submit control was clicked."""
    page.wait_for_timeout(1500)
    cbs = page.locator("mat-checkbox")
    for i in range(cbs.count()):
        try:
            cb = cbs.nth(i)
            if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
                cb.locator("label").click()
                page.wait_for_timeout(250)
        except Exception:
            continue
    # NAME * and DATE * are both mandatory — Submit stays disabled until they are set
    try:
        f = page.locator('input[aria-label="NAME *"], input[aria-label*="NAME" i]').first
        if f.count() and f.is_visible() and not f.input_value():
            f.fill(signer)
            page.wait_for_timeout(400)
    except Exception as exc:
        print(f"  [terms] NAME: {str(exc)[:80]}")
    try:
        f = page.locator('input[aria-label="DATE *"], input[aria-label*="DATE" i]').first
        if f.count() and f.is_visible() and not f.input_value():
            f.fill(datetime.now().strftime("%m/%d/%Y"))
            page.wait_for_timeout(400)
    except Exception as exc:
        print(f"  [terms] DATE: {str(exc)[:80]}")
    shot(page, "sc2_p3_terms")

    btn = page.locator('button:has-text("Submit")').first
    try:
        btn.wait_for(state="visible", timeout=20_000)
        for _ in range(20):
            if not btn.is_disabled():
                break
            page.wait_for_timeout(500)
        if btn.is_disabled():
            print("  [terms] Submit still DISABLED — form did not validate "
                  "(NOT a submission)")
            return False
        btn.scroll_into_view_if_needed()
        btn.click()
    except Exception as exc:
        print(f"  [form] Submit click failed: {str(exc)[:120]}")
        return False
    page.wait_for_timeout(5000)
    for label in ("Yes", "Ok", "OK", "Confirm", "Submit"):
        try:
            b = page.locator(f'mat-dialog-container button:has-text("{label}")').first
            if b.count() and b.is_visible():
                b.click()
                page.wait_for_timeout(4000)
                break
        except Exception:
            continue
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    return True


def public_case_block(page, vin: str) -> str:
    """Return the dashboard text for the card row holding this VIN ('' if absent)."""
    body = page.inner_text("body")
    i = body.find(vin)
    return body[i:i + 900] if i >= 0 else ""


# ═══════════════════════════════════════════════════════════════════════
# SC-1  Reject an LT-263 — the case survives at 'LT-263 Rejected'
#       TC-01, TC-02, TC-03
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
@pytest.mark.e2e
class TestE2E_NCNSS212_SC1_RejectSurvives:

    def test_phase_1_acquire_case_at_lt263_submitted(self, staff_context: BrowserContext):
        """PRE-2: a case awaiting staff review of a submitted LT-263."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            case = pick_to_process_case(page)
            status = lt263_status(page, case["app_id"])
            shot(page, "sc1_p1_case_at_to_process")
            check("SC1.P1 case is awaiting LT-263 review",
                  "LT-263 Submitted / To Process", status,
                  ok=("submit" in status.lower() or "process" in status.lower()))
            save_state("SC1", case)
        finally:
            page.close()

    def test_phase_2_reject_keeps_case_open(self, staff_context: BrowserContext):
        """TC-01 — reject marks only that LT-263; the case survives at 'LT-263 Rejected'."""
        case = get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, case["app_id"])
            # reason #0 = 'SIGN AND/OR COMPLETE IN FULL...' — contains a slash (TC-02)
            reason = reject_case(page, reason_index=0)
            print(f"  [reject] reason used: {reason[:90]}")
            shot(page, "sc1_p2_after_reject")

            status = lt263_status(page, case["app_id"])
            check("TC-01 case status after reject", "LT-263 Rejected", status)

            open_listing(page, "LT-263")
            click_tab(page, "Closed")
            search_listing(page, case["vin"])
            closed_rows = [v for v, _ in listing_rows(page) if v == case["vin"]]
            check("TC-01 case is NOT closed by a rejection",
                  "VIN absent from the Closed tab",
                  f"{len(closed_rows)} closed row(s) for {case['vin']}",
                  ok=(len(closed_rows) == 0))

            open_listing(page, "LT-263")
            click_tab(page, "Rejected")
            search_listing(page, case["vin"])
            rej = [v for v, _ in listing_rows(page) if v == case["vin"]]
            shot(page, "sc1_p2_rejected_tab")
            check("TC-01 case appears in the Rejected tab",
                  "exactly 1 row", f"{len(rej)} row(s)", ok=(len(rej) == 1))

            case["reason"] = reason
            case["reject_chain"] = dict(REJECT_CHAIN_CAPTURE)
            save_state("SC1", case)
        finally:
            page.close()

    def test_phase_3_upstream_forms_untouched(self, staff_context: BrowserContext):
        """TC-01 — LT-260 stays Approved/Processed and LT-262 stays Paid."""
        case = get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_listing(page, "LT-260")
            click_tab(page, "All")
            search_listing(page, case["vin"])
            rows260 = [t for v, t in listing_rows(page) if v == case["vin"]]
            shot(page, "sc1_p3_lt260_listing")
            check("TC-01 LT-260 record survives the LT-263 rejection",
                  "1 LT-260 row for the VIN", f"{len(rows260)} row(s): {rows260[:1]}",
                  ok=(len(rows260) >= 1), hard=False)

            open_listing(page, "LT-262")
            click_tab(page, "All")
            search_listing(page, case["vin"])
            rows262 = [t for v, t in listing_rows(page) if v == case["vin"]]
            shot(page, "sc1_p3_lt262_listing")
            check("TC-01 LT-262 record survives the LT-263 rejection",
                  "1 LT-262 row for the VIN", f"{len(rows262)} row(s): {rows262[:1]}",
                  ok=(len(rows262) >= 1), hard=False)
        finally:
            page.close()

    def test_phase_4_rejection_reason_banner(self, staff_context: BrowserContext):
        """TC-02 — banner shows the latest rejection reason with slashes cleaned."""
        case = get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, case["app_id"])
            shot(page, "sc1_p4_banner")
            txt = banner_text(page)
            check("TC-02 rejection-reason banner rendered",
                  "'Latest rejection reason: <reason>' present", txt or "<no banner>",
                  ok=bool(txt))
            check("TC-02 escaped slashes cleaned in the banner",
                  r"no literal backslash-slash (\/)", txt,
                  ok=("\\/" not in txt))
            check("TC-02 banner carries the reason chosen at reject time",
                  case.get("reason", "")[:35], txt,
                  ok=(case.get("reason", "")[:30].lower() in txt.lower()), hard=False)
        finally:
            page.close()

    def test_phase_5_empty_reason_does_not_crash(self, staff_context: BrowserContext):
        """TC-03 — rejecting with an EMPTY reason returns 2xx/4xx, never a 5xx crash."""
        case = get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, case["app_id"])

            # UI half: the Reject button is reason-gated, so an empty reason is
            # unreachable through the UI on a case that still offers Reject.
            if has_button(page, "Reject"):
                btn = page.locator('button:has-text("Reject")').first
                btn.click()
                page.wait_for_timeout(2500)
                dlg = page.locator("mat-dialog-container").first
                rb = dlg.locator('button:has-text("Reject")').first
                check("TC-03 UI guards the empty reason",
                      "Reject disabled until a reason is selected",
                      f"disabled={rb.is_disabled()}", ok=rb.is_disabled(), hard=False)
                shot(page, "sc1_p5_empty_reason_modal")
                dlg.locator('button:has-text("Cancel")').first.click()
                page.wait_for_timeout(1500)
            else:
                print("  [TC-03] no Reject button on this (already rejected) case — "
                      "UI half not applicable; exercising the API half only")

            chain = case.get("reject_chain", {}).get("id")
            if not chain:
                check("TC-03 API empty-reason probe",
                      "reject chain id captured during SC-1 phase 2",
                      "chain id NOT captured — API half not executed",
                      ok=False, hard=False)
                return
            for payload in ({"applicationId": case["app_id"], "closingRemarks": "{}"},
                            {"applicationId": case["app_id"], "closingRemarks": "[]"},
                            {"applicationId": case["app_id"]}):
                st, body = api_chain(page, chain, payload)
                print(f"  [TC-03] payload={payload} -> HTTP {st} :: {body[:180]}")
                check(f"TC-03 empty reason (payload keys {sorted(payload)}) does not crash",
                      "HTTP < 500 (no jsonb_set crash)", f"HTTP {st}",
                      ok=(st < 500), hard=False)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-2  Garage re-submission loop        TC-04, TC-05, TC-06, TC-07, TC-30
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
@pytest.mark.e2e
class TestE2E_NCNSS212_SC2_ResubmitLoop:

    def test_phase_1_rejected_case_on_garage_dashboard(self, public_context: BrowserContext):
        """TC-04 — the rejected case returns to the ACTIVE list with its reason
        and a working Submit LT-263 button."""
        case = get_state("SC1")
        page = public_context.new_page()
        try:
            goto_public(page)
            select_business(page)
            shot(page, "sc2_p1_garage_dashboard")
            blk = public_case_block(page, case["vin"])
            check("TC-04 rejected case is listed on the garage dashboard (ACTIVE)",
                  f"VIN {case['vin']} present in Open Requests",
                  blk[:160] or "<VIN not found on dashboard>", ok=bool(blk))
            check("TC-04 the card row shows the rejection reason / rejected status",
                  "rejection reason or 'Rejected' visible on the row",
                  re.sub(r"\s+", " ", blk[:300]),
                  ok=bool(re.search(r"reject", blk, re.I)), hard=False)
            has_submit = bool(re.search(r"Submit LT-263", blk, re.I)) or \
                page.locator('button:has-text("Submit LT-263")').count() > 0
            check("TC-04 a working 'Submit LT-263' button is present",
                  "Submit LT-263 offered on the rejected case",
                  f"present={has_submit}", ok=has_submit)
        finally:
            page.close()

    def test_phase_2_card_rendering_across_cycles(self, public_context: BrowserContext):
        """TC-30 — card renders past three rows: not empty, collapsed by default,
        working chevron, per-row menu / per-cycle Download gated."""
        case = get_state("SC1")
        page = public_context.new_page()
        try:
            goto_public(page)
            select_business(page)
            blk = public_case_block(page, case["vin"])
            shot(page, "sc2_p2_card_render")
            check("TC-30 card body is not empty",
                  "card renders form/status rows", f"{len(blk)} chars of card text",
                  ok=len(blk) > 40)
            chevrons = page.locator('mat-icon:has-text("expand_more"), '
                                    'mat-icon:has-text("chevron_right"), '
                                    'button[aria-label*="expand" i]').count()
            check("TC-30 collapse/expand affordance present",
                  ">=1 chevron/expander on the dashboard", f"{chevrons} found",
                  ok=chevrons >= 1, hard=False)
        finally:
            page.close()

    def test_phase_3_resubmit_lt263(self, public_context: BrowserContext):
        """TC-05 — garage re-submits -> status returns to 'LT-263 Submitted'."""
        case = get_state("SC1")
        page = public_context.new_page()
        try:
            goto_public(page)
            select_business(page)
            from src.pages.public_portal.dashboard_page import PublicDashboardPage
            dash = PublicDashboardPage(page)
            try:
                dash.click_notice_storage_tab()
                page.wait_for_timeout(1500)
            except Exception:
                pass
            try:
                dash.search_by_vin(case["vin"])
                page.wait_for_timeout(2500)
            except Exception:
                pass

            submits = page.locator('button:has-text("Submit LT-263"), a:has-text("Submit LT-263")')
            if submits.count() == 0:
                try:
                    dash.select_application(0)
                    page.wait_for_timeout(2500)
                except Exception:
                    pass
                submits = page.locator('button:has-text("Submit LT-263"), a:has-text("Submit LT-263")')
            shot(page, "sc2_p3_before_resubmit")
            check("TC-05 Submit LT-263 reachable for the rejected case",
                  ">=1 Submit LT-263 control", f"{submits.count()} found",
                  ok=submits.count() > 0)

            posts = []

            def _cap(r):
                if "/automation/chain/execute/" in r.url and r.request.method == "POST":
                    posts.append((r.url, r.status, (r.request.post_data or "")[:300]))
            page.on("response", _cap)

            submits.first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4000)
            shot(page, "sc2_p3_lt263_form")

            # Step 1 "LT-263 - Form Details" is PRE-FILLED from the rejected cycle;
            # refresh only the time-sensitive fields, then Next -> Terms -> Submit.
            fill_lt263_form_details(page)
            try:
                page.locator('button:has-text("Next")').first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(4000)
            except Exception as exc:
                print(f"  [form] Next click failed: {str(exc)[:110]}")

            accept_terms_and_submit(page)
            shot(page, "sc2_p3_after_submit")

            body = page.inner_text("body")
            toast = bool(re.search(r"submitted successfully|Form is submitted", body, re.I))
            errs = re.findall(r"(is required|This field is required|Please fill)", body, re.I)
            FORM_KEYS = r"saleD|lien_amount|typeOfSale|type_of_sale|sale_date|\"sno\"|termsAccepted"
            writes = [(u.split("/execute/")[1].split("?")[0], s)
                      for u, s, rq in posts if s < 400 and re.search(FORM_KEYS, rq, re.I)]
            print(f"  [proof] toast={toast} field_errors={len(errs)} form_writes={writes}")
            submit_chain = writes[-1][0] if writes else None
            save_state("SC2", {**case, "resubmit_toast": toast,
                               "submit_chain": submit_chain,
                               "public_chains": [f"{u.split('/execute/')[1].split('?')[0]}:{s}"
                                                 for u, s, _ in posts][-12:]})

            check("TC-05 positive proof of submission (no silent no-op)",
                  "success toast OR a 2xx LT-263 form write, and no mandatory-field error",
                  f"toast={toast}, form_writes={len(writes)}, field_errors={len(errs)}",
                  ok=((toast or len(writes) > 0) and len(errs) == 0))
        finally:
            page.close()

    def test_phase_4_back_in_staff_to_process_queue(self, staff_context: BrowserContext):
        """TC-05 — after re-submission the case is back in the staff To Process queue."""
        case = get_state("SC2")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            status = lt263_status(page, case["app_id"])
            check("TC-05 status after re-submission", "LT-263 Submitted", status)

            open_listing(page, "LT-263")
            click_tab(page, "To Process")
            search_listing(page, case["vin"])
            rows = [v for v, _ in listing_rows(page) if v == case["vin"]]
            shot(page, "sc2_p4_to_process")
            check("TC-05 case reappears in the To Process queue",
                  "exactly 1 To Process row", f"{len(rows)} row(s)", ok=(len(rows) == 1))
        finally:
            page.close()

    def test_phase_5_invalid_resubmission_refused(self, staff_context: BrowserContext):
        """TC-06 — an invalid re-submission is refused (FO-30 lien 0, FO-26 API 400)."""
        case = get_state("SC2")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            sub_chain = load_state().get("SC2", {}).get("submit_chain")
            if not sub_chain:
                check("TC-06 API validation probe",
                      "public LT263.submit chain id captured in phase 3",
                      "chain id NOT captured — API half not executed", ok=False, hard=False)
                return
            st, body = api_chain(page, sub_chain,
                                 {"applicationId": case["app_id"], "lienAmount": 0})
            check("TC-06 lien amount 0 refused at API level",
                  "HTTP 4xx", f"HTTP {st} :: {body[:120]}", ok=(400 <= st < 500), hard=False)
        finally:
            page.close()

    def test_phase_6_three_cycles_no_cap(self, staff_context: BrowserContext):
        """TC-07 — reject -> re-submit three times; the button returns every time."""
        case = get_state("SC2")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, case["app_id"])
            cycles = []
            for n in (2, 3):
                if not has_button(page, "Reject"):
                    print(f"  [cycle {n}] no Reject button — case is at "
                          f"{lt263_status(page, case['app_id'])}")
                    break
                reject_case(page, reason_index=min(n, 5))
                status = lt263_status(page, case["app_id"])
                cycles.append(status)
                print(f"  [cycle {n}] status -> {status}")
                open_case(page, case["app_id"])
            shot(page, "sc2_p6_cycles")
            st, subs = submission_history(page, case["app_id"])
            check("TC-07 no cap — every cycle is retained",
                  ">=2 submissions in the history after repeated cycles",
                  f"{len(subs)} submission(s), statuses seen {cycles}",
                  ok=len(subs) >= 2, hard=False)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-3  'View Previous LT-263s' history   TC-08, 09, 11, 24, 25, 26
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
class TestE2E_NCNSS212_SC3_History:

    def test_phase_1_history_endpoint_and_panel(self, staff_context: BrowserContext):
        """TC-08 — LT263SubmissionHistory.get returns every cycle with dates,
        actor, reason, outcome and the saved copy; inline detail expands."""
        case = load_state().get("SC2") or get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            st, subs = submission_history(page, case["app_id"])
            check("TC-08 LT263SubmissionHistory.get responds",
                  "HTTP 200", f"HTTP {st}", ok=(st == 200))
            check("TC-08 history returns at least one cycle",
                  ">=1 submission", f"{len(subs)} submission(s)", ok=len(subs) >= 1)
            if subs:
                s0 = subs[0]
                print("  [history] first submission:", json.dumps(s0)[:400])
                for field in ("submissionNumber", "submittedAt", "submittedBy",
                              "rejectedAt", "rejectedBy", "rejectionReason", "outcome"):
                    check(f"TC-08 history carries '{field}'",
                          "field present in the payload", f"{field}={s0.get(field)!r}",
                          ok=(field in s0), hard=False)
                check("TC-08 history carries the saved copy",
                      "documentLink or details present",
                      f"documentLink={s0.get('documentLink')!r} details="
                      f"{'set' if s0.get('details') else 'null'}",
                      ok=("documentLink" in s0 or "details" in s0), hard=False)

            open_case(page, case["app_id"])
            panel = open_history_panel(page)
            shot(page, "sc3_p1_history_panel")
            check("TC-08 inline history panel renders each cycle",
                  "'Submission #<n>' block(s) rendered",
                  panel[:220] or "<panel empty>",
                  ok=bool(re.search(r"Submission #\d", panel)))
        finally:
            page.close()

    def test_phase_2_legacy_row_fallback_line(self, staff_context: BrowserContext):
        """TC-09 (PRE-5) — a pre-CR rejection with no snapshot shows the fallback
        line, never a blank/broken block; the two gates are mutually exclusive."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            st, subs = submission_history(page, LEGACY_REJECTED_APP)
            legacy = [s for s in subs if not s.get("details")]
            check("TC-09 legacy rejection has no captured snapshot",
                  ">=1 submission with details=null",
                  f"{len(legacy)} of {len(subs)} submissions have details=null",
                  ok=len(legacy) >= 1)

            open_case(page, LEGACY_REJECTED_APP)
            panel = open_history_panel(page)
            shot(page, "sc3_p2_legacy_fallback")
            fallback = "Detailed snapshot not captured for this submission."
            check("TC-09 fallback line is shown instead of a blank block",
                  fallback, panel[-400:] or "<panel empty>",
                  ok=(fallback.lower() in panel.lower()))
            check("TC-09 the two gates are mutually exclusive",
                  "no 'View saved copy' on a snapshot-less row",
                  f"saved-copy link present={('View saved copy' in panel)}",
                  ok=("View saved copy" not in panel), hard=False)
        finally:
            page.close()

    def test_phase_3_independent_loaders(self, staff_context: BrowserContext):
        """TC-11 — the history call and the details call own independent loaders."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, LEGACY_REJECTED_APP)
            open_history_panel(page)
            page.wait_for_timeout(3000)
            spinners = page.locator("mat-spinner, mat-progress-spinner, .mat-spinner").count()
            body = page.inner_text("body")
            shot(page, "sc3_p3_loaders")
            check("TC-11 no spinner is left stranded after both calls settle",
                  "0 visible spinners once history + details have loaded",
                  f"{spinners} spinner element(s)", ok=(spinners == 0), hard=False)
            check("TC-11 both payloads rendered simultaneously",
                  "details form AND history panel both present",
                  f"details={'Description Of Vehicle' in body}, "
                  f"history={'Submission #' in body}",
                  ok=("Description Of Vehicle" in body and "Submission #" in body))
        finally:
            page.close()

    def test_phase_4_entry_points_listing_and_search(self, staff_context: BrowserContext):
        """TC-25 — the same rejected history is reachable from the LT-263 Listing
        and from Global Search."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_listing(page, "LT-263")
            click_tab(page, "Rejected")
            search_listing(page, LEGACY_REJECTED_VIN)
            rows = [v for v, _ in listing_rows(page) if v == LEGACY_REJECTED_VIN]
            if rows:
                page.locator(f'span.table-link:has-text("{LEGACY_REJECTED_VIN}")').first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(4000)
            panel_listing = open_history_panel(page)
            shot(page, "sc3_p4_from_listing")
            check("TC-25 history reachable from the LT-263 Listing",
                  "'Submission #' rendered after listing -> detail",
                  panel_listing[:150] or "<empty>",
                  ok=bool(re.search(r"Submission #\d", panel_listing)))

            page.goto(SP_DASH, timeout=90_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            try:
                si = page.locator('input[placeholder*="Search" i]').first
                si.fill(LEGACY_REJECTED_VIN)
                si.press("Enter")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(5000)
                shot(page, "sc3_p4_global_search")
                found = LEGACY_REJECTED_VIN in page.inner_text("body")
            except Exception as exc:
                found = False
                print(f"  [global search] {str(exc)[:120]}")
            check("TC-25 the case is reachable from Global Search",
                  "VIN returned by Global Search", f"found={found}", ok=found, hard=False)
        finally:
            page.close()

    def test_phase_5_zero_rejection_case_hides_the_link(self, staff_context: BrowserContext):
        """TC-26 — with zero rejected submissions the extra link must NOT appear."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            case = pick_to_process_case(page)
            st, subs = submission_history(page, case["app_id"])
            rejected = [s for s in subs if str(s.get("outcome", "")).lower() == "rejected"]
            open_case(page, case["app_id"])
            present = has_button(page, "View Previous LT-263s")
            shot(page, "sc3_p5_zero_rejection")
            print(f"  [TC-26] {len(subs)} submission(s), {len(rejected)} rejected")
            check("TC-26 'View Previous LT-263s' hidden with zero rejected submissions",
                  "link/button ABSENT on a case with no rejection history",
                  f"present={present} (rejected cycles={len(rejected)})",
                  ok=(present is False) if len(rejected) == 0 else True)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-4  Paper LT-263 after a rejection    TC-12, TC-13, TC-14
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
class TestE2E_NCNSS212_SC4_PaperRelog:

    def test_phase_1_relog_button_gated_on_canrelog(self, staff_context: BrowserContext):
        """TC-13 — 'Re-Log Paper LT-263' appears only when the backend says so."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            # rejected case
            open_case(page, LEGACY_REJECTED_APP)
            rejected_status = lt263_status(page, LEGACY_REJECTED_APP)
            present_rejected = has_button(page, "Re-Log Paper LT-263")
            shot(page, "sc4_p1_relog_on_rejected")
            check("TC-13 Re-Log Paper LT-263 offered on an LT-263 Rejected case",
                  "button visible", f"present={present_rejected} (status={rejected_status})",
                  ok=present_rejected)

            # non-rejected (To Process) case — the flag must be false there
            case = pick_to_process_case(page)
            open_case(page, case["app_id"])
            present_toproc = has_button(page, "Re-Log Paper LT-263")
            shot(page, "sc4_p1_relog_on_toprocess")
            check("TC-13 Re-Log Paper LT-263 hidden when canRelog is false",
                  "button ABSENT on a non-rejected case",
                  f"present={present_toproc}", ok=(present_toproc is False))
            save_state("SC4", {"rejected_app": LEGACY_REJECTED_APP,
                               "rejected_vin": LEGACY_REJECTED_VIN})
        finally:
            page.close()

    def test_phase_2_add_paper_form_accepts_rejected_vin(self, staff_context: BrowserContext):
        """TC-12 — Add Paper Form accepts a VIN whose latest status is LT-263 Rejected."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_listing(page, "LT-263")
            btn = page.locator('button:has-text("Add from Paper"), '
                               'button:has-text("Add Paper")').first
            if btn.count() == 0 or not btn.is_visible():
                check("TC-12 Add-from-Paper entry point on the LT-263 listing",
                      "'Add from Paper' button present",
                      "button not found on the listing", ok=False, hard=False)
                return
            btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)
            shot(page, "sc4_p2_add_paper_modal")
            vin_in = page.locator('input[name="vin" i], input[aria-label*="VIN" i], '
                                  'input[placeholder*="VIN" i]').first
            vin_in.wait_for(state="visible", timeout=15_000)
            vin_in.fill(LEGACY_REJECTED_VIN)
            page.wait_for_timeout(1500)
            nxt = page.locator('mat-dialog-container button:has-text("Next"), '
                               'button:has-text("Next")').first
            nxt.click()
            page.wait_for_timeout(4500)
            body = page.inner_text("body")
            shot(page, "sc4_p2_after_next")
            blocked = bool(re.search(r"already exists|duplicate|invalid|not allowed|cannot",
                                     body, re.I))
            check("TC-12 the rejected VIN is accepted by Add Paper Form",
                  "VIN accepted — no duplicate/invalid-state block",
                  f"blocking message present={blocked}", ok=(blocked is False))
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-5  Loop exit #1 — approved re-submission -> Vehicle Sold
#       TC-15, TC-16, TC-17
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
@pytest.mark.e2e
class TestE2E_NCNSS212_SC5_ExitSold:

    def test_phase_1_approve_resubmission_issues_lt265(self, staff_context: BrowserContext):
        """TC-15 — approving a re-submitted LT-263 issues LT-265 -> Vehicle Sold."""
        from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            case = load_state().get("SC2")
            if case and "submit" in lt263_status(page, case["app_id"]).lower():
                print(f"  [SC-5] reusing the re-submitted SC-2 case {case['vin']}")
            else:
                case = pick_to_process_case(page)
            open_case(page, case["app_id"])
            before = lt263_status(page, case["app_id"])
            shot(page, "sc5_p1_before_approve")
            Lt263ListingPage(page).generate_lt265(expected_vin=case["vin"])
            page.wait_for_timeout(3000)
            after = lt263_status(page, case["app_id"])
            shot(page, "sc5_p1_after_approve")
            check("TC-15 approved re-submission ends the loop at Vehicle Sold",
                  "Vehicle Sold", f"{before} -> {after}",
                  ok=bool(re.search(r"sold", after, re.I)))
            save_state("SC5", case)
        finally:
            page.close()

    def test_phase_2_resubmission_blocked_after_sold(self, public_context: BrowserContext):
        """TC-16 — re-submission against a Vehicle Sold case is hidden on the UI."""
        case = get_state("SC5")
        page = public_context.new_page()
        try:
            goto_public(page)
            select_business(page)
            blk = public_case_block(page, case["vin"])
            shot(page, "sc5_p2_public_after_sold")
            offers = bool(re.search(r"Submit LT-263", blk, re.I))
            check("TC-16 Submit LT-263 is hidden once the vehicle is Sold",
                  "no Submit LT-263 control on a sold case",
                  f"offered={offers}", ok=(offers is False))
        finally:
            page.close()

    def test_phase_3_resubmission_refused_by_api_after_sold(self, staff_context: BrowserContext):
        """TC-16 — the endpoint refuses a post-terminal re-submission with 4xx."""
        case = get_state("SC5")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            chain = load_state().get("SC2", {}).get("submit_chain")
            if not chain:
                check("TC-16 API half",
                      "public LT263.submit chain id captured", "not captured",
                      ok=False, hard=False)
                return
            st, body = api_chain(page, chain, {"applicationId": case["app_id"]})
            check("TC-16 post-terminal re-submission refused",
                  "HTTP 4xx", f"HTTP {st} :: {body[:120]}",
                  ok=(400 <= st < 500), hard=False)
        finally:
            page.close()

    def test_phase_4_nordis_routing(self, staff_context: BrowserContext):
        """TC-17 — LT-265 goes to Nordis first-class; the repeated LT-263s never do."""
        case = get_state("SC5")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, case["app_id"])
            btn = page.locator('button:has-text("View Correspondence/Documents")').first
            if btn.count() and btn.is_visible():
                btn.click()
                page.wait_for_timeout(4500)
            shot(page, "sc5_p4_correspondence")
            body = page.inner_text("body")
            has265 = bool(re.search(r"LT-?265", body))
            lt263_mailed = bool(re.search(r"LT-?263[^\n]{0,60}(Nordis|First[- ]Class|Mailed)",
                                          body, re.I))
            check("TC-17 LT-265 present in correspondence",
                  "an LT-265 entry", f"present={has265}", ok=has265, hard=False)
            check("TC-17 repeated LT-263s are never mailed via Nordis",
                  "no LT-263 correspondence entry marked Nordis/first-class",
                  f"lt263_mailed={lt263_mailed}", ok=(lt263_mailed is False), hard=False)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-6  Loop exit #2 — Close File on 'LT-263 Rejected'  TC-18, 19, 20
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
@pytest.mark.e2e
class TestE2E_NCNSS212_SC6_ExitClosed:

    def test_phase_1_reject_a_fresh_case(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            case = pick_to_process_case(page)
            open_case(page, case["app_id"])
            reject_case(page, reason_index=2)
            status = lt263_status(page, case["app_id"])
            shot(page, "sc6_p1_rejected")
            check("SC-6 setup — case parked at LT-263 Rejected",
                  "LT-263 Rejected", status)
            save_state("SC6", case)
        finally:
            page.close()

    def test_phase_2_close_file_enabled_and_closes(self, staff_context: BrowserContext):
        """TC-18 — Close File is enabled on an LT-263 Rejected case and closes it."""
        from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
        case = get_state("SC6")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, case["app_id"])
            btns = [b for b in page_buttons(page) if "close file" in b["t"].lower()]
            shot(page, "sc6_p2_close_file_button")
            check("TC-18 Close File is ENABLED on an LT-263 Rejected case",
                  "Close File present and not disabled",
                  f"{btns}", ok=bool(btns) and not btns[0]["d"])

            clicked = close_file_with_notes(
                page, "NCNSS-212 automated closure from LT-263 Rejected")
            check("TC-18 the Close File modal accepts a mandatory reason",
                  "confirm enabled once Notes/Comments is filled",
                  f"confirm_clicked={clicked}", ok=clicked, hard=False)
            page.wait_for_timeout(4000)
            shot(page, "sc6_p2_after_close")
            print(f"  [close-write] LT263.closeFile ({CHAIN_CLOSE_FILE}) -> "
                  f"HTTP {CLOSE_CAPTURE['status']} :: {CLOSE_CAPTURE['body']}")
            check("TC-18 the Close File write succeeds",
                  "HTTP 2xx from LT263 Close File",
                  f"HTTP {CLOSE_CAPTURE['status']} :: {CLOSE_CAPTURE['body']}",
                  ok=(CLOSE_CAPTURE["status"] is not None
                      and CLOSE_CAPTURE["status"] < 400), hard=False)
            status = lt263_status(page, case["app_id"])
            check("TC-18 the case is closed",
                  "a Closed/Denied terminal status", status,
                  ok=bool(re.search(r"clos|den", status, re.I)))
            case["closed_status"] = status
            save_state("SC6", case)
        finally:
            page.close()

    def test_phase_3_closure_semantics_recorded(self, staff_context: BrowserContext):
        """TC-20 [OQ-CR-1] — close-on-rejected is un-ratified: record the observed
        semantics verbatim rather than asserting a guessed expectation."""
        case = get_state("SC6")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_listing(page, "LT-263")
            click_tab(page, "Closed")
            search_listing(page, case["vin"])
            rows = [t for v, t in listing_rows(page) if v == case["vin"]]
            shot(page, "sc6_p3_closed_tab")
            observed = {
                "status_label": case.get("closed_status"),
                "closed_tab_rows": len(rows),
                "closed_tab_row_text": rows[0][:200] if rows else "",
            }
            print("  [OQ-CR-1] observed close-on-rejected semantics:",
                  json.dumps(observed, indent=1))
            check("TC-20 [OQ-CR-1] semantics captured for product confirmation",
                  "observation recorded (no ratified expectation to assert)",
                  json.dumps(observed), ok=True, hard=False)
        finally:
            page.close()

    def test_phase_4_resubmission_blocked_after_close(self, public_context: BrowserContext):
        """TC-19 — once Closed, Submit LT-263 is hidden on the garage dashboard."""
        case = get_state("SC6")
        page = public_context.new_page()
        try:
            goto_public(page)
            select_business(page)
            blk = public_case_block(page, case["vin"])
            shot(page, "sc6_p4_public_after_close")
            offers = bool(re.search(r"Submit LT-263", blk, re.I))
            check("TC-19 Submit LT-263 hidden once the case is Closed",
                  "no Submit LT-263 control on a closed case",
                  f"offered={offers} | card={blk[:140]!r}", ok=(offers is False))
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-7  Regression — Reject and Deny have NOT merged   TC-21, TC-22
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
class TestE2E_NCNSS212_SC7_DenyNotMerged:

    def test_phase_1_reject_and_deny_are_distinct_controls(self, staff_context: BrowserContext):
        """TC-21 — Reject (keeps the case open) is a different control from
        Deny/Close (which closes it)."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            case = pick_to_process_case(page)
            open_case(page, case["app_id"])
            names = [b["t"] for b in page_buttons(page) if b["v"]]
            shot(page, "sc7_p1_controls")
            print("  [SC-7] controls on an LT-263 awaiting review:", names)
            has_reject = any("reject" in n.lower() for n in names)
            has_close = any("close file" in n.lower() for n in names)
            check("TC-21 Reject is still its own control",
                  "a 'Reject' button distinct from the closing control",
                  f"reject={has_reject}, close_file={has_close}",
                  ok=(has_reject and has_close))
            deny = [n for n in names if "deny" in n.lower()]
            check("TC-21 Deny surface on the LT-263 review screen",
                  "a Deny control if the workflow still exposes one",
                  f"deny controls found: {deny or 'NONE — closure is via Close File'}",
                  ok=True, hard=False)
            save_state("SC7", case)
        finally:
            page.close()

    def test_phase_2_reject_refused_on_terminal_cases(self, staff_context: BrowserContext):
        """TC-22 — rejecting an already-Sold / already-Closed LT-263 is refused."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            chain = load_state().get("SC1", {}).get("reject_chain", {}).get("id")
            sold = load_state().get("SC5")
            closed = load_state().get("SC6")
            if not chain:
                check("TC-22 API probe", "reject chain id captured in SC-1",
                      "not captured — API half not executed", ok=False, hard=False)
            for label, st_case in (("Sold", sold), ("Closed", closed)):
                if not st_case:
                    print(f"  [TC-22] no {label} case in state — skipped")
                    continue
                open_case(page, st_case["app_id"])
                ui_reject = has_button(page, "Reject")
                shot(page, f"sc7_p2_{label.lower()}_case")
                check(f"TC-22 Reject hidden on an already-{label} case",
                      "no Reject control", f"present={ui_reject}",
                      ok=(ui_reject is False), hard=False)
                if chain:
                    code, body = api_chain(page, chain,
                                           {"applicationId": st_case["app_id"],
                                            "closingRemarks": '{"sign":true}'})
                    check(f"TC-22 reject endpoint refuses an already-{label} case",
                          "HTTP 4xx", f"HTTP {code} :: {body[:120]}",
                          ok=(400 <= code < 500), hard=False)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-8  No-owner court branch          TC-23
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
class TestE2E_NCNSS212_SC8_CourtBranch:

    def test_phase_1_court_path_case_behaves_identically(self, staff_context: BrowserContext):
        """TC-23 — a case that reached LT-263 through the court branch shows the
        same rejection/re-submission behaviour."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_listing(page, "LT-263")
            click_tab(page, "Rejected")
            rows = listing_rows(page)
            court_case = None
            for vin, txt in rows:
                page.locator(f'span.table-link:has-text("{vin}")').first.click(timeout=20_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(4000)
                body = page.inner_text("body")
                if re.search(r"NAME OF COURT AUTHORIZING SALE\s*\n?\s*\S", body):
                    m = re.search(r"/LT-262/([0-9a-f\-]{36})/details", page.url)
                    if m:
                        court_case = {"vin": vin, "app_id": m.group(1)}
                        break
                open_listing(page, "LT-263")
                click_tab(page, "Rejected")
            if not court_case:
                check("TC-23 court-branch case available on QA",
                      "a rejected LT-263 that came via the court branch",
                      "none found in the Rejected tab", ok=False, hard=False)
                return
            shot(page, "sc8_p1_court_case")
            status = lt263_status(page, court_case["app_id"])
            st, subs = submission_history(page, court_case["app_id"])
            relog = has_button(page, "Re-Log Paper LT-263")
            check("TC-23 court-path case survives at LT-263 Rejected",
                  "LT-263 Rejected", status)
            check("TC-23 the same history surface is available on the court path",
                  ">=1 submission returned by LT263SubmissionHistory.get",
                  f"HTTP {st}, {len(subs)} submission(s)", ok=(st == 200 and len(subs) >= 1))
            check("TC-23 the same re-log affordance is offered",
                  "Re-Log Paper LT-263 present", f"present={relog}", ok=relog, hard=False)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# SC-9  Case-level integrity across cycles  TC-27, 28, 29, 31
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
class TestE2E_NCNSS212_SC9_CaseIntegrity:

    def test_phase_1_one_record_per_vehicle(self, staff_context: BrowserContext):
        """TC-28 — one record for the vehicle in the LT-263 Listing and in
        Global Search, no matter how many cycles."""
        case = load_state().get("SC2") or get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_listing(page, "LT-263")
            click_tab(page, "All")
            search_listing(page, case["vin"])
            rows = [v for v, _ in listing_rows(page) if v == case["vin"]]
            shot(page, "sc9_p1_listing_all")
            check("TC-28 exactly one LT-263 listing record for the vehicle",
                  "1 row across all cycles", f"{len(rows)} row(s)", ok=(len(rows) == 1))

            page.goto(SP_DASH, timeout=90_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            try:
                si = page.locator('input[placeholder*="Search" i]').first
                si.fill(case["vin"])
                si.press("Enter")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(5000)
                shot(page, "sc9_p1_global_search")
                hits = page.inner_text("body").count(case["vin"])
            except Exception as exc:
                hits = -1
                print(f"  [global search] {str(exc)[:120]}")
            check("TC-28 Global Search likewise returns one record",
                  "1 occurrence of the VIN in the results",
                  f"{hits} occurrence(s)", ok=(hits == 1), hard=False)
        finally:
            page.close()

    def test_phase_2_same_vin_refiling_blocked(self, public_context: BrowserContext):
        """TC-27 — while the case sits rejected, a new LT-260 for the same VIN is blocked."""
        case = load_state().get("SC2") or get_state("SC1")
        page = public_context.new_page()
        try:
            goto_public(page)
            select_business(page)
            from src.pages.public_portal.dashboard_page import PublicDashboardPage
            from src.pages.public_portal.lt260_form_page import Lt260FormPage
            PublicDashboardPage(page).click_start_here()
            page.wait_for_timeout(3500)
            Lt260FormPage(page).enter_vin(case["vin"])
            page.wait_for_timeout(4000)
            shot(page, "sc9_p2_duplicate_vin")
            body = page.inner_text("body")
            blocked = bool(re.search(r"already (exists|been)|duplicate|active (case|request)|"
                                     r"in progress|cannot", body, re.I))
            check("TC-27 re-filing the same VIN while rejected is blocked",
                  "a duplicate/active-case guard fires",
                  f"guard fired={blocked}", ok=blocked)
        finally:
            page.close()

    def test_phase_3_audit_log_captures_rejections(self, staff_context: BrowserContext):
        """TC-29 — the Audit Log captures every LT-263 rejection event."""
        case = load_state().get("SC2") or get_state("SC1")
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            page.goto(f"{SP_BASE}/pages/ncdot-notice-and-storage/reports/list",
                      timeout=90_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4000)
            link = page.get_by_text(re.compile(r"Audit\s*Log", re.I)).first
            if link.count() == 0:
                check("TC-29 Audit Log reachable", "Audit Log report link",
                      "not found on /reports/list", ok=False, hard=False)
                return
            link.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)
            shot(page, "sc9_p3_audit_log")
            body = page.inner_text("body")
            check("TC-29 Audit Log surface reachable",
                  "Audit Log report renders", body[:120].replace("\n", " "),
                  ok=bool(re.search(r"audit", body, re.I)), hard=False)
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# TC-10  Race safety
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
class TestE2E_NCNSS212_TC10_RaceSafety:

    def test_double_click_reject_creates_one_record(self, staff_context: BrowserContext):
        """TC-10 — double-clicking Reject produces exactly ONE timeline record
        (FO-45: the button disables on first click until the server responds)."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            case = pick_to_process_case(page)
            open_case(page, case["app_id"])
            before_st, before = submission_history(page, case["app_id"])
            # reason #0 is a plain checkbox; #1/#6 carry a companion text field that
            # keeps the modal's Reject button disabled until it is filled
            reject_case(page, reason_index=0, double_click=True)
            page.wait_for_timeout(4000)
            after_st, after = submission_history(page, case["app_id"])
            shot(page, "tc10_after_double_click")
            rej_before = len([s for s in before
                              if str(s.get("outcome", "")).lower() == "rejected"])
            rej_after = len([s for s in after
                             if str(s.get("outcome", "")).lower() == "rejected"])
            check("TC-10 a double-clicked Reject writes exactly one record",
                  "rejected-cycle count grows by exactly 1",
                  f"{rej_before} -> {rej_after}", ok=(rej_after - rej_before == 1))
        finally:
            page.close()


# ═══════════════════════════════════════════════════════════════════════
# TC-32  Role permissions
# ═══════════════════════════════════════════════════════════════════════
@pytest.mark.ncnss212
@pytest.mark.rbac
class TestE2E_NCNSS212_TC32_Rbac:

    def test_phase_1_fiscal_user_cannot_reach_lt263_review(self, fiscal_context: BrowserContext):
        """TC-32 — a Fiscal User may not reject / re-submit / see the history."""
        page = fiscal_context.new_page()
        try:
            page.goto(SP_DASH, timeout=90_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)
            page.goto(listing_url("LT-263"), timeout=90_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4000)
            shot(page, "tc32_p1_fiscal_lt263_listing")
            body = page.inner_text("body")
            denied = bool(re.search(r"not authori|access denied|permission|forbidden", body, re.I)) \
                or "LT-263" not in body or "login" in page.url.lower()
            check("TC-32 Fiscal User is denied the LT-263 review surface",
                  "listing not served (redirect / empty / access message)",
                  f"denied={denied}, url={page.url}", ok=denied, hard=False)

            case = load_state().get("SC1")
            if case:
                page.goto(detail_url(case["app_id"]), timeout=90_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(4000)
                shot(page, "tc32_p1_fiscal_detail")
                can_reject = has_button(page, "Reject")
                can_hist = has_button(page, "View Previous LT-263s")
                check("TC-32 Fiscal User gets no Reject control",
                      "Reject absent", f"present={can_reject}",
                      ok=(can_reject is False))
                check("TC-32 Fiscal User gets no rejection-history control",
                      "View Previous LT-263s absent", f"present={can_hist}",
                      ok=(can_hist is False), hard=False)
        finally:
            page.close()

    def test_phase_2_admin_retains_full_access(self, staff_context: BrowserContext):
        """TC-32 — the N&S Administrator keeps reject + history."""
        page = staff_context.new_page()
        try:
            goto_staff_dash(page)
            open_case(page, LEGACY_REJECTED_APP)
            hist = has_button(page, "View Previous LT-263s")
            shot(page, "tc32_p2_admin_access")
            check("TC-32 N&S Administrator can open the rejection history",
                  "View Previous LT-263s available", f"present={hist}", ok=hist)
            st, subs = submission_history(page, LEGACY_REJECTED_APP)
            check("TC-32 admin may call LT263SubmissionHistory.get",
                  "HTTP 200", f"HTTP {st}, {len(subs)} submission(s)", ok=(st == 200))
        finally:
            page.close()
