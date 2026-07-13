"""
TW 27302845 — ZIP lookup length-5 guard: no append / no request storm.

Prod incident: the Staff Portal ZIP/city-state lookup chain `_cityStateLookupWithZipCode`
(chain id 49c86332fc3a6af7655f9ca5e6d27295) fired ~537 requests in ~30 s, each APPENDING a
digit to the ZIP (28306 -> 283066 -> ... up to 290+ chars), causing HTTP 500 surges.
Fix (QA 2026-07-10): a Step-1 guard — the lookup executes ONLY when ZIP length == 5.

ACs verified here:
  - request payload always holds only the CURRENT zip value (replace, never append)
  - exactly one request per completed 5-digit entry; ZERO requests for len<5 / len>5
  - no retry loop on unknown ZIP or backend failure
  - guard enforced API-direct (controlled non-500 response, lookup not executed)
  - scope pinned to the ZIP lookup ONLY (Public Portal registration Address Auto Suggest
    UNCHANGED — no new min-length suppression)

Live-discovered facts (QA, 2026-07-10, synthesis probes):
  - Chain endpoint (staff + public portals, same chain id):
      POST https://<host>/rest/api/public/automation/chain/execute/
           49c86332fc3a6af7655f9ca5e6d27295?encrypted=true
    payload: {"zipCode":"<zip>"}  — NO authorization header (public endpoint).
  - Staff LT-260 paper form: ZIP field = input[name="zip"] (first visible one is the
    VEHICLE LOCATION section); City = input[name="city"]; County free-text =
    input[name="county_val"] (hidden/replaced by a dropdown control for NC ZIPs,
    visible free text for non-NC ZIPs). No separate State input on this form.
  - 28306 -> City 'Fayetteville' (NC); 10001 -> City 'New York' (non-NC).
  - API-direct: len 4 / len 6 -> HTTP 400 "Invalid ZIP/postal code" failing at STEP 1
    (guard fires); 290-char -> HTTP 500 "Query too long - 290/256" failing at STEP 2
    (guard BYPASSED — defect); unknown 00000 -> HTTP 500 (chain wraps downstream 400).
  - Public registration (logged out, /ncdmv-nsm/register): ZIP field uses the SAME chain;
    the Address* field fires NO suggestion requests at any input length (suggest/verify
    appears to be submit-time only — the Keep-Original modal is not reachable without
    creating a real user).

Scenarios (ExpertlyTestBuddy plan.json, ticket 27302845):
  SC-1 [Critical] Staff LT-260 happy-path decode + single-request assertion (TC-01,02,03,17)
  SC-2 [Critical] Guard boundary + incident replay (TC-04,05,06,07,08)
  SC-3 [High]     Failure handling — unknown ZIP / backend 500, no retry (TC-09,10)
  SC-4 [High]     Shared surfaces — LT-261, LT-262/262A, Public LT-260 (TC-11,12,13)
  SC-5 [High]     Scope regression — registration Address Auto Suggest (TC-14)
  SC-6 [High]     API-direct Step-1 guard, no HTTP 500 (TC-15)
  SC-7 [Medium]   Burst rate — ~1 request per entry, zero chain 500s (TC-16)

Negative goals PASS when the guard/rejection actually fires. MISMATCH = genuine FAIL —
assertions are NOT relaxed to go green; product misbehavior is reported as a defect.
All flows are read-only: no form is ever submitted, no user/record is created.
"""

import json
import re
import time
from pathlib import Path

import pytest
import requests as pyrequests
from playwright.sync_api import Browser, BrowserContext

from src.config.env import ENV
from src.helpers.data_helper import generate_vin
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt261_page import Lt261Page
from src.pages.staff_portal.paper_form_page import PaperFormPage


CHAIN_ID = "49c86332fc3a6af7655f9ca5e6d27295"

SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)
PP_REGISTER_URL = re.sub(r"/ncshp-nss-signin$", "/ncdmv-nsm/register", ENV.PUBLIC_PORTAL_URL)

NC_ZIP = "28306"          # the incident ZIP — decodes to Fayetteville, NC (county dropdown)
NON_NC_ZIP = "10001"      # New York — county stays free text
UNKNOWN_ZIP = "00000"     # valid length, not decodable
LONG_290 = ("28306" * 58)  # 290-char numeric paste string (longest observed prod value)
VALID_NC_ZIPS = ["28306", "27601", "28801", "27513", "28202", "27604", "28540", "27858"]

SCREENSHOTS = Path(__file__).resolve().parent.parent / "screenshots"
SCREENSHOTS.mkdir(exist_ok=True)


# ─────────────────────────── shared helpers ───────────────────────────

class ZipChainCapture:
    """Capture every request/response on the _cityStateLookupWithZipCode chain plus
    client-side page errors. The core assertion of every scenario is request COUNT and
    payload CONTENT, so this is attached before any typing happens."""

    def __init__(self, page):
        self.requests = []    # {url, body, zip}
        self.responses = []   # {url, status}
        self.page_errors = []
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("pageerror", lambda e: self.page_errors.append(str(e)))

    def _on_request(self, req):
        try:
            if CHAIN_ID in req.url and req.method == "POST":
                body = req.post_data or ""
                zip_val = None
                try:
                    zip_val = json.loads(body).get("zipCode")
                except Exception:
                    pass
                self.requests.append({"url": req.url, "body": body, "zip": zip_val})
        except Exception:
            pass

    def _on_response(self, resp):
        try:
            if CHAIN_ID in resp.url:
                self.responses.append({"url": resp.url, "status": resp.status})
        except Exception:
            pass

    @property
    def count(self) -> int:
        return len(self.requests)

    def zips_since(self, n: int):
        return [r["zip"] for r in self.requests[n:]]

    def statuses(self):
        return [r["status"] for r in self.responses]


def check(tag: str, expected: str, actual: str, ok: bool) -> bool:
    print(f"[{tag}] EXPECTED: {expected} | ACTUAL: {actual} -> {'MATCH' if ok else 'MISMATCH'}")
    return ok


def shot(page, name: str) -> str:
    path = SCREENSHOTS / f"tw27302845_{name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        try:
            page.screenshot(path=str(path))
        except Exception:
            pass
    return str(path)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def open_lt260_paper_form(page, vin: str):
    """e2e_005 navigation: dashboard -> LT-260 listing -> Add from Paper -> modal VIN+Next."""
    go_to_staff_dashboard(page)
    StaffDashboardPage(page).navigate_to_lt260_listing()
    Lt260ListingPage(page).click_add_from_paper()
    PaperFormPage(page).fill_modal_vin_and_next(vin)
    page.wait_for_timeout(1500)


def zip_box(page, timeout: int = 20_000):
    """First VISIBLE zip input = the Vehicle/Storage-Location section ZIP field
    (the form contains other hidden input[name=zip] copies)."""
    box = page.locator('input[name="zip"]:visible, input[aria-label*="Zip" i]:visible').first
    box.wait_for(state="visible", timeout=timeout)
    box.scroll_into_view_if_needed()
    return box


def visible_value(page, selectors) -> str:
    return page.evaluate(
        """(sels) => {
            for (const sel of sels) {
                const es = [...document.querySelectorAll(sel)].filter(e => e.offsetParent);
                if (es.length) return es[0].value;
            }
            return null;
        }""",
        selectors,
    )


def city_value(page):
    return visible_value(page, ['input[name="city"]', 'input[aria-label*="City" i]'])


def county_freetext_visible(page) -> bool:
    """True when the free-text county input is the active control (non-NC ZIP);
    False when it is hidden/replaced by the NC county dropdown control."""
    return page.evaluate(
        """() => {
            const es = [...document.querySelectorAll('input[name="county_val"]')]
                .filter(e => e.offsetParent);
            return es.length > 0;
        }"""
    )


def enter_zip(page, box, value: str, per_char_delay: int = 150, settle_ms: int = 3500):
    box.click()
    box.press_sequentially(value, delay=per_char_delay)
    page.wait_for_timeout(settle_ms)


def clear_zip(page, box, settle_ms: int = 1200):
    box.click()
    box.fill("")
    page.wait_for_timeout(settle_ms)


def guard_spotcheck(page, cap: ZipChainCapture, tag: str) -> dict:
    """Shared-surface spot-check: 0 requests at 4 chars, exactly 1 at the 5th char,
    payload holds the current 5-digit value, City populates. Returns result dict."""
    box = zip_box(page)
    clear_zip(page, box, settle_ms=800)
    n0 = cap.count
    box.press_sequentially(NC_ZIP[:4], delay=200)
    page.wait_for_timeout(2500)
    at4 = cap.count - n0
    box.press_sequentially(NC_ZIP[4], delay=100)
    page.wait_for_timeout(3500)
    new = cap.requests[n0:]
    at5 = len(new) - at4
    payloads = [r["zip"] for r in new]
    city = city_value(page)
    ok = (at4 == 0) and (at5 == 1) and payloads == [NC_ZIP] and bool(city)
    check(
        tag,
        f"0 chain requests at 4 chars, exactly 1 at 5th char with payload '{NC_ZIP}', City populates",
        f"at4chars={at4}, at5thChar={at5}, payloads={payloads}, city={city!r}",
        ok,
    )
    if new:
        print(f"[{tag}] chain URL: {new[0]['url']}")
    return {"at4": at4, "at5": at5, "payloads": payloads, "city": city, "ok": ok}


def discover_chain_endpoint(staff_context: BrowserContext) -> dict:
    """Open the staff LT-260 paper form, type a valid ZIP, and capture one REAL UI request
    to the lookup chain — returns its URL + parsed payload (SC-6/SC-7 use this instead of
    hardcoding the endpoint)."""
    page = staff_context.new_page()
    try:
        cap = ZipChainCapture(page)
        open_lt260_paper_form(page, generate_vin())
        box = zip_box(page)
        enter_zip(page, box, NC_ZIP)
        assert cap.count >= 1, (
            "EXPECTED: one live UI request to the zip lookup chain for endpoint discovery | "
            "ACTUAL: none captured — cannot discover the endpoint"
        )
        req = cap.requests[0]
        print(f"[discovery] chain endpoint: {req['url']}")
        print(f"[discovery] payload shape: {req['body']}")
        return {"url": req["url"], "body": json.loads(req["body"])}
    finally:
        page.close()


# ============================================================================
# SC-1 [Critical] — Staff LT-260 paper: happy-path decode + single request
# Covers: TC-01, TC-02, TC-03, TC-17
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.critical
class TestTW27302845_SC1_HappyPathDecode:
    """Valid ZIP fires exactly ONE lookup with the current value; City populates;
    NC -> county dropdown, non-NC -> county free text; manual City override does
    not re-trigger the lookup."""

    def test_sc1_happy_path_decode(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        results = []
        try:
            cap = ZipChainCapture(page)
            open_lt260_paper_form(page, generate_vin())
            box = zip_box(page)
            # Baseline page errors from form load/navigation (e.g. the pre-existing
            # 'document.getElementByClassName is not a function' app error) are recorded
            # but not attributed to the ZIP interaction — only NEW errors are gated.
            baseline_errors = len(cap.page_errors)
            if baseline_errors:
                print(f"[SC-1] pre-existing page errors at form load (not ZIP-related, "
                      f"informational): {cap.page_errors}")

            # TC-01 / TC-02: NC ZIP 28306 -> exactly ONE request, payload == current zip
            n0 = cap.count
            enter_zip(page, box, NC_ZIP)
            new = cap.requests[n0:]
            city = city_value(page)
            county_ft = county_freetext_visible(page)
            results.append(check(
                "TC-01/02",
                f"exactly 1 lookup request, payload zip == '{NC_ZIP}', City populates",
                f"requests={len(new)}, payloads={[r['zip'] for r in new]}, city={city!r}",
                len(new) == 1 and new[0]["zip"] == NC_ZIP and bool(city),
            ))
            if new:
                print(f"[TC-02] discovered chain URL: {new[0]['url']}")
                print(f"[TC-02] payload: {new[0]['body']}")
            # NC ZIP -> County becomes a dropdown (free-text county input hidden)
            results.append(check(
                "TC-01 county",
                "NC ZIP -> County control is a dropdown (free-text county_val hidden)",
                f"county free-text visible={county_ft}",
                county_ft is False,
            ))
            shot(page, "SC1_nc_zip_28306")

            # TC-03: non-NC ZIP 10001 -> one request, City populates, county FREE TEXT
            clear_zip(page, box)
            n1 = cap.count
            enter_zip(page, box, NON_NC_ZIP)
            new = cap.requests[n1:]
            city = city_value(page)
            county_ft = county_freetext_visible(page)
            results.append(check(
                "TC-03",
                f"one request payload '{NON_NC_ZIP}', City populates, County stays FREE TEXT",
                f"requests={len(new)}, payloads={[r['zip'] for r in new]}, city={city!r}, "
                f"countyFreeText={county_ft}",
                len(new) == 1 and new[0]["zip"] == NON_NC_ZIP and bool(city) and county_ft,
            ))
            shot(page, "SC1_non_nc_zip_10001")

            # TC-17: manually override the populated City -> editable, NO new lookup request
            n2 = cap.count
            city_input = page.locator('input[name="city"]:visible, input[aria-label*="City" i]:visible').first
            city_input.click()
            city_input.fill("QA Override City")
            page.wait_for_timeout(2500)
            after_override = city_value(page)
            new_reqs = cap.count - n2
            results.append(check(
                "TC-17",
                "City manually overridable; override does NOT re-trigger a lookup request",
                f"city={after_override!r}, newChainRequests={new_reqs}",
                after_override == "QA Override City" and new_reqs == 0,
            ))
            shot(page, "SC1_city_override")

            new_errors = cap.page_errors[baseline_errors:]
            assert new_errors == [], (
                f"client page errors raised DURING the ZIP interactions: {new_errors}"
            )
            assert all(results), "SC-1: one or more EXPECTED|ACTUAL checks MISMATCHED (see log)"
        finally:
            page.close()


# ============================================================================
# SC-2 [Critical] — Guard boundary + incident replay
# Covers: TC-04, TC-05, TC-06, TC-07, TC-08
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.critical
class TestTW27302845_SC2_GuardBoundary:
    """Progressive typing, 4/5/6-char boundary, rapid retype (incident replay),
    290-char paste — payload always the CURRENT value, count bounded."""

    def test_sc2_guard_boundary_and_incident_replay(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        results = []
        try:
            cap = ZipChainCapture(page)
            open_lt260_paper_form(page, generate_vin())
            box = zip_box(page)

            # TC-04: progressive typing 2-8-3-0 -> ZERO requests at len 1..4; 5th char fires 1
            n0 = cap.count
            box.click()
            box.press_sequentially("2830", delay=300)
            page.wait_for_timeout(2500)
            at4 = cap.count - n0
            box.press_sequentially("6", delay=100)
            page.wait_for_timeout(3500)
            at5 = cap.count - n0 - at4
            payloads5 = cap.zips_since(n0)
            results.append(check(
                "TC-04",
                "0 requests for lengths 1-4; exactly 1 at the 5th char with payload '28306'",
                f"at1to4={at4}, at5th={at5}, payloads={payloads5}",
                at4 == 0 and at5 == 1 and payloads5 == [NC_ZIP],
            ))
            shot(page, "SC2_progressive_typing")

            # TC-05: backspace to 4 -> none; retype 5th (may legitimately re-fire once);
            # add a 6th char -> no NEW request; no payload ever >5 chars
            n1 = cap.count
            box.click()
            box.press("End")
            box.press("Backspace")           # "2830"
            page.wait_for_timeout(2500)
            after_bs = cap.count - n1
            box.press_sequentially("6", delay=100)   # "28306" again — completed entry
            page.wait_for_timeout(3000)
            after_retype = cap.count - n1 - after_bs
            n2 = cap.count
            resp_before_6th = len(cap.responses)
            box.press_sequentially("6", delay=100)   # "283066" — 6 chars
            page.wait_for_timeout(3000)
            after_6th = cap.count - n2
            statuses_6th = [r["status"] for r in cap.responses[resp_before_6th:]]
            if after_6th:
                print(f"[TC-05 evidence] 6th-char request payload(s): "
                      f"{cap.zips_since(n2)}, response status(es): {statuses_6th}")
            payloads_bs = cap.zips_since(n1)
            results.append(check(
                "TC-05",
                "backspace-to-4 fires 0; re-completed 5-digit entry fires <=1 (payload '28306'); "
                "6th char fires 0 NEW and no payload >5 chars",
                f"afterBackspace={after_bs}, afterRetype5th={after_retype}, after6th={after_6th}, "
                f"payloads={payloads_bs}",
                after_bs == 0 and after_retype <= 1 and after_6th == 0
                and all(p == NC_ZIP for p in payloads_bs),
            ))
            shot(page, "SC2_boundary_456")

            # TC-06 / TC-07: incident replay — rapid edit/retype; every payload holds ONLY
            # the current value (never a 283066/2830628306-style concatenation); bounded count
            entries = ["28306", "10001", "27601", "28801", "28306"]
            n3 = cap.count
            for e in entries:
                box.click()
                box.fill("")
                page.wait_for_timeout(300)
                box.press_sequentially(e, delay=60)
                page.wait_for_timeout(700)
            page.wait_for_timeout(3500)
            replay = cap.zips_since(n3)
            allowed = set(entries)
            only_current = all(p in allowed and len(p or "") == 5 for p in replay)
            bounded = 1 <= len(replay) <= len(entries) + 2
            results.append(check(
                "TC-06/07",
                f"every payload is a CURRENT 5-char value from {sorted(allowed)} (no appends, "
                f"no >5-char zip), count bounded ~1/entry (1..{len(entries) + 2})",
                f"count={len(replay)}, payloads={replay}",
                only_current and bounded,
            ))
            max_len_seen = max((len(r["zip"] or "") for r in cap.requests), default=0)
            results.append(check(
                "TC-07",
                "no captured request ever carries a >5-char zip",
                f"max payload length seen across ALL SC-2 requests={max_len_seen}",
                max_len_seen <= 5,
            ))
            shot(page, "SC2_incident_replay")

            # TC-08: paste the 290-char numeric string -> zero lookup requests, no JS error
            box.click()
            box.fill("")
            page.wait_for_timeout(800)
            n4 = cap.count
            err_baseline = len(cap.page_errors)
            resp_before_paste = len(cap.responses)
            box.fill(LONG_290)   # single input event — same value-shape as a paste
            page.wait_for_timeout(4000)
            after_paste = cap.count - n4
            field_val = box.input_value()
            errors = cap.page_errors[err_baseline:]
            if after_paste:
                paste_payloads = [(len(r["zip"] or ""), (r["zip"] or "")[:20] + "...")
                                  for r in cap.requests[n4:]]
                paste_statuses = [r["status"] for r in cap.responses[resp_before_paste:]]
                print(f"[TC-08 evidence] paste fired {after_paste} request(s), payload "
                      f"(len, head): {paste_payloads}, response status(es): {paste_statuses} "
                      f"— the incident's 290-char value STILL produces a chain request")
            results.append(check(
                "TC-08",
                "290-char numeric paste -> 0 lookup requests, no client page errors",
                f"requests={after_paste}, fieldLen={len(field_val)}, pageErrors={errors}",
                after_paste == 0 and not errors,
            ))
            shot(page, "SC2_290char_paste")

            # TC-08 (recovery): correct back to a valid 5-digit ZIP -> normal single request
            box.fill("")
            page.wait_for_timeout(800)
            n5 = cap.count
            box.press_sequentially("27601", delay=120)
            page.wait_for_timeout(3500)
            recovery = cap.zips_since(n5)
            results.append(check(
                "TC-08 recovery",
                "correcting to valid 5-digit ZIP resumes normal single-request behavior",
                f"requests={len(recovery)}, payloads={recovery}, city={city_value(page)!r}",
                len(recovery) == 1 and recovery == ["27601"],
            ))
            shot(page, "SC2_recovery")

            assert all(results), "SC-2: one or more EXPECTED|ACTUAL checks MISMATCHED (see log)"
        finally:
            page.close()


# ============================================================================
# SC-3 [High] — Failure handling: unknown ZIP + backend failure, no retry loop
# Covers: TC-09, TC-10
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.high
class TestTW27302845_SC3_FailureHandling:
    """Unknown ZIP and a forced backend 500 each produce exactly ONE request, no
    automatic retry over a >=30 s network watch, no zip-value mutation, form usable."""

    def test_sc3_unknown_zip_no_retry(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        results = []
        try:
            cap = ZipChainCapture(page)
            open_lt260_paper_form(page, generate_vin())
            box = zip_box(page)

            # TC-09: unknown 5-digit ZIP -> exactly one request, graceful no-populate
            n0 = cap.count
            enter_zip(page, box, UNKNOWN_ZIP)
            first_count = cap.count - n0
            city_after = city_value(page)
            results.append(check(
                "TC-09",
                f"exactly 1 request for unknown ZIP '{UNKNOWN_ZIP}', graceful no-populate",
                f"requests={first_count}, payloads={cap.zips_since(n0)}, city={city_after!r}",
                first_count == 1 and not city_after,
            ))
            statuses = cap.statuses()
            print(f"[TC-09] chain response status(es) for unknown ZIP: {statuses} "
                  f"(observation: a 5xx here is API-layer behavior, gated in SC-6 reporting)")

            # NO automatic retry: watch the network >=30 s
            page.wait_for_timeout(31_000)
            retries = cap.count - n0 - first_count
            results.append(check(
                "TC-09 no-retry",
                "NO automatic retry request appears over a >=30 s network watch",
                f"additional requests in 31s={retries}",
                retries == 0,
            ))

            # City/State manually enterable after the failed lookup
            city_input = page.locator('input[name="city"]:visible, input[aria-label*="City" i]:visible').first
            city_input.click()
            city_input.fill("Manual City Entry")
            page.wait_for_timeout(800)
            manual_ok = city_value(page) == "Manual City Entry"
            results.append(check(
                "TC-09 manual",
                "City remains manually enterable after unknown-ZIP lookup",
                f"city={city_value(page)!r}",
                manual_ok,
            ))
            shot(page, "SC3_unknown_zip")
            assert all(results), "SC-3 (unknown ZIP): one or more checks MISMATCHED (see log)"
        finally:
            page.close()

    def test_sc3_backend_failure_no_retry_loop(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        results = []
        attempts = []
        try:
            cap = ZipChainCapture(page)

            def force_500(route):
                attempts.append(route.request.post_data)
                route.fulfill(status=500, content_type="application/json",
                              body='{"message":"QA simulated backend failure"}')

            page.route(f"**/chain/execute/{CHAIN_ID}*", force_500)
            open_lt260_paper_form(page, generate_vin())
            box = zip_box(page)

            # TC-10: valid ZIP against a failing backend -> ONE failed request, no retry loop
            enter_zip(page, box, "27601")
            first_attempts = len(attempts)
            results.append(check(
                "TC-10",
                "exactly 1 lookup attempt against the failing backend",
                f"attempts={first_attempts}, bodies={attempts}",
                first_attempts == 1,
            ))

            page.wait_for_timeout(31_000)
            results.append(check(
                "TC-10 no-retry",
                "NO retry loop: no additional attempts over a >=30 s watch",
                f"attempts after 31s={len(attempts)}",
                len(attempts) == first_attempts,
            ))

            # ZIP value NOT mutated by the failure path; form still usable
            zip_val = box.input_value()
            results.append(check(
                "TC-10 value",
                "zip field value NOT mutated by the failure path (still '27601')",
                f"zip field={zip_val!r}",
                zip_val == "27601",
            ))
            city_input = page.locator('input[name="city"]:visible, input[aria-label*="City" i]:visible').first
            city_input.click()
            city_input.fill("Backend Down City")
            page.wait_for_timeout(800)
            results.append(check(
                "TC-10 usable",
                "form still completable manually after backend failure",
                f"city={city_value(page)!r}",
                city_value(page) == "Backend Down City",
            ))
            shot(page, "SC3_backend_failure")
            page.unroute(f"**/chain/execute/{CHAIN_ID}*")
            assert all(results), "SC-3 (backend failure): one or more checks MISMATCHED (see log)"
        finally:
            page.close()


# ============================================================================
# SC-4 [High] — Shared surfaces: LT-261, LT-262/262A, Public LT-260
# Covers: TC-11, TC-12, TC-13
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.high
class TestTW27302845_SC4_SharedSurfaces:
    """The single shared ZIP-lookup helper behaves identically (guard + populate) on
    every consuming surface."""

    def test_sc4_lt261_estop_zip_guard(self, staff_context: BrowserContext):
        """TC-11: LT-261 (E-Stop) storage-location ZIP — guard + populate spot-check."""
        page = staff_context.new_page()
        try:
            cap = ZipChainCapture(page)
            go_to_staff_dashboard(page)
            StaffDashboardPage(page).navigate_to_lt261_listing()
            lt261 = Lt261Page(page)
            lt261.click_add_from_estop()
            lt261.fill_modal_vin_next(generate_vin())
            page.wait_for_timeout(1500)

            res = guard_spotcheck(page, cap, "TC-11 LT-261 E-Stop")
            shot(page, "SC4_lt261_estop")
            assert res["ok"], (
                "EXPECTED: LT-261 E-Stop ZIP behaves identically to Staff LT-260 "
                "(0 req <5 chars, 1 at 5, populate) | ACTUAL: see EXPECTED|ACTUAL log"
            )
        finally:
            page.close()

    def test_sc4_lt262_paper_zip_guard(self, staff_context: BrowserContext):
        """TC-12: LT-262 (or LT-262A) paper-form location ZIP — guard + populate spot-check.

        Reachability: LT-262 'Add from Paper' requires a VIN with an issued LT-160B and no
        existing LT-262 (BR-26) — fresh VINs bounce back to the listing. We harvest VINs
        from the LT-260 Processed tab and try each; if none opens the form this is a
        documented environment blocker, not a guard failure."""
        page = staff_context.new_page()
        try:
            cap = ZipChainCapture(page)
            go_to_staff_dashboard(page)
            dash = StaffDashboardPage(page)
            dash.navigate_to_lt260_listing()
            page.wait_for_timeout(2000)
            try:
                page.locator('[role="tab"]:has-text("Processed")').first.click()
                page.wait_for_timeout(2500)
            except Exception:
                pass
            rows = page.evaluate(
                """() => Array.from(document.querySelectorAll('table tr, mat-row'))
                       .slice(0, 12).map(r => r.innerText)"""
            )
            vins = []
            for r in rows:
                m = re.search(r"\b[A-HJ-NPR-Z0-9]{17}\b", r)
                if m and m.group(0) not in vins:
                    vins.append(m.group(0))
            print(f"[TC-12] harvested LT-260 Processed VIN candidates: {vins[:6]}")

            opened = None
            for vin in vins[:6]:
                dash.navigate_to_lt262_listing()
                page.wait_for_timeout(1500)
                try:
                    page.locator(
                        'button:has-text("Add From Paper"), button:has-text("Add from Paper")'
                    ).first.click(timeout=10_000)
                    page.wait_for_timeout(1000)
                    vi = page.locator(
                        'mat-dialog-container input[placeholder*="VIN" i], '
                        'mat-dialog-container input[name*="vin" i]'
                    ).first
                    vi.wait_for(state="visible", timeout=8_000)
                    vi.fill(vin)
                    page.wait_for_timeout(500)
                    page.locator('mat-dialog-container button:has-text("Next")').first.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(3000)
                    has_zip = page.locator('input[name="zip"]:visible').count() > 0
                    if has_zip:
                        opened = vin
                        break
                    print(f"[TC-12] VIN {vin}: modal bounced (not LT-262-paper eligible)")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(800)
                except Exception as exc:
                    print(f"[TC-12] VIN {vin}: attempt failed ({type(exc).__name__}: {exc})")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(800)

            if not opened:
                shot(page, "SC4_lt262_blocked")
                pytest.skip(
                    "TC-12 BLOCKED (environment, not product): no QA VIN reachable for "
                    "LT-262 'Add from Paper' — every harvested LT-260-Processed VIN bounced "
                    "at the modal (needs issued LT-160B + no existing LT-262, BR-26). The "
                    "shared helper guard is proven on LT-260/LT-261/Public-LT-260 surfaces."
                )

            print(f"[TC-12] LT-262 paper form opened with VIN {opened}")
            res = guard_spotcheck(page, cap, "TC-12 LT-262 paper")
            shot(page, "SC4_lt262_paper")
            # Abandon the form WITHOUT submitting (read-only mandate)
            assert res["ok"], (
                "EXPECTED: LT-262 paper-form ZIP behaves identically (guard + populate) | "
                "ACTUAL: see EXPECTED|ACTUAL log"
            )
        finally:
            page.close()

    def test_sc4_public_lt260_zip_guard(self, public_context: BrowserContext):
        """TC-13: Public Portal LT-260 storage-location ZIP — guard + populate spot-check."""
        page = public_context.new_page()
        try:
            cap = ZipChainCapture(page)
            page.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
            page.wait_for_load_state("networkidle")
            start = page.locator(
                'button:has-text("Start here"), a:has-text("Start here"), '
                'button:has-text("Start Here")'
            ).first
            start.wait_for(state="visible", timeout=25_000)
            start.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)

            # The storage-location ZIP may only render after choosing Reason = storage
            try:
                zip_box(page, timeout=8_000)
            except Exception:
                from src.pages.public_portal.lt260_form_page import Lt260FormPage
                try:
                    Lt260FormPage(page).select_reason_storage()
                    page.wait_for_timeout(1500)
                except Exception:
                    pass

            res = guard_spotcheck(page, cap, "TC-13 Public LT-260")
            shot(page, "SC4_public_lt260")
            # Abandon the form WITHOUT submitting (read-only mandate)
            assert res["ok"], (
                "EXPECTED: Public LT-260 ZIP behaves identically to the staff surfaces "
                "(single shared helper) | ACTUAL: see EXPECTED|ACTUAL log"
            )
        finally:
            page.close()


# ============================================================================
# SC-5 [High] — Scope regression: registration Address Auto Suggest UNCHANGED
# Covers: TC-14
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.high
class TestTW27302845_SC5_AddrAutoSuggestRegression:
    """The 07-09 scope decision pins the length guard to the ZIP lookup ONLY. On the
    logged-out registration surface we verify: (a) typing a partial address is not
    suppressed/broken and behavior is length-INDEPENDENT (no new min-length differential),
    (b) the registration ZIP field's shared-chain lookup still works. The suggestion ->
    Keep-Original modal is submit-time only and is NOT driven (would create a real user)."""

    def test_sc5_registration_address_autosuggest(self, browser: Browser):
        ctx = browser.new_context()   # logged OUT — new-user registration surface
        page = ctx.new_page()
        results = []
        try:
            cap = ZipChainCapture(page)
            all_reqs = []
            page.on(
                "request",
                lambda r: all_reqs.append({"url": r.url, "m": r.method, "body": r.post_data})
                if not re.search(r"\.(js|css|png|svg|woff2?|ico|json)(\?|$)", r.url)
                else None,
            )
            page.goto(PP_REGISTER_URL, timeout=60_000)
            page.wait_for_load_state("networkidle")
            page.get_by_text("Business/Organization").first.click()
            page.wait_for_timeout(2500)

            addr = page.locator('input[aria-label="Address*"]:visible').first
            addr.wait_for(state="visible", timeout=15_000)

            # TC-14a: type a SHORT partial (4 chars — under any 5-char ZIP shape), then a
            # LONG partial; capture suggestion-ish activity + overlay options for each.
            observations = {}
            for label, query in (("short(4ch)", "512 "), ("long(19ch)", "512 North Salisbury")):
                addr.click()
                addr.fill("")
                page.wait_for_timeout(500)
                n0 = len(all_reqs)
                addr.press_sequentially(query, delay=120)
                page.wait_for_timeout(4000)
                new = all_reqs[n0:]
                opts = [t.strip() for t in
                        page.locator(".cdk-overlay-pane mat-option").all_text_contents()]
                observations[label] = {"requests": len(new), "options": len(opts)}
                print(f"[TC-14] address input {label} {query!r}: network requests={len(new)}, "
                      f"suggestion options={len(opts)}")
                for r in new[:5]:
                    print(f"    {r['m']} {r['url'][:140]} | {(r['body'] or '')[:120]}")

            # No NEW min-length suppression = behavior must be length-INDEPENDENT
            length_independent = (
                (observations["short(4ch)"]["requests"] > 0)
                == (observations["long(19ch)"]["requests"] > 0)
                and (observations["short(4ch)"]["options"] > 0)
                == (observations["long(19ch)"]["options"] > 0)
            )
            results.append(check(
                "TC-14 length-independence",
                "address-typing behavior identical for short vs long input "
                "(no new min-length suppression differential)",
                f"observations={observations}",
                length_independent,
            ))
            results.append(check(
                "TC-14 no client break",
                "typing partial addresses raises no client page errors, form stays usable",
                f"pageErrors={cap.page_errors}, addressValue={addr.input_value()!r}",
                not cap.page_errors and addr.input_value() == "512 North Salisbury",
            ))
            if observations["long(19ch)"]["options"] == 0:
                print(
                    "[TC-14] OBSERVATION: no typeahead suggestion overlay and no suggestion "
                    "endpoint fires at ANY input length on this build — the registration "
                    "Address 'Auto Suggest' (Keep-Original vs recommended modal) appears to be "
                    "a SUBMIT-time verification, which is not driven here because it would "
                    "create a real user. Logged as not-driven, not asserted as pass/fail."
                )

            # TC-14b (reachable hard proof the shared chain is intact on this surface):
            # the registration ZIP field uses the SAME lookup chain — one request at 5
            # digits, City auto-populates.
            zipbox = page.locator(
                'input[aria-label=""][name^="____text_field"]:visible'
            ).first
            if zipbox.count() == 0:
                zipbox = page.locator('input[aria-label*="Zip" i]:visible').first
            n0 = cap.count
            zipbox.click()
            zipbox.press_sequentially(NC_ZIP[:4], delay=180)
            page.wait_for_timeout(2500)
            at4 = cap.count - n0
            zipbox.press_sequentially(NC_ZIP[4], delay=100)
            page.wait_for_timeout(3500)
            at5 = cap.count - n0 - at4
            reg_city = visible_value(page, ['input[aria-label="City*"]'])
            results.append(check(
                "TC-14 zip-side",
                "registration ZIP field: shared chain fires once at 5 digits (guard active), "
                "City auto-populates — surface functional post-fix",
                f"at4chars={at4}, at5thChar={at5}, payloads={cap.zips_since(n0)}, "
                f"city={reg_city!r}",
                at4 == 0 and at5 == 1 and bool(reg_city),
            ))
            shot(page, "SC5_registration_autosuggest")

            # Read-only mandate: never click Register/Submit here.
            assert all(results), "SC-5: one or more EXPECTED|ACTUAL checks MISMATCHED (see log)"
        finally:
            page.close()
            ctx.close()


# ============================================================================
# SC-6 [High] — API-direct chain guard: len != 5 short-circuits, no HTTP 500
# Covers: TC-15
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.high
class TestTW27302845_SC6_ApiDirectGuard:
    """Invoke the chain endpoint DIRECTLY (endpoint discovered live from a real UI
    request) with len-4 / len-6 / 290-char zips -> each must exit at the Step-1 guard
    with a controlled NON-500 response; len-5 '28306' -> normal city/state result."""

    def test_sc6_api_direct_guard(self, staff_context: BrowserContext):
        discovered = discover_chain_endpoint(staff_context)
        url = discovered["url"]
        payload_shape = discovered["body"]
        zip_key = next((k for k, v in payload_shape.items() if v == NC_ZIP), "zipCode")
        print(f"[TC-15] replaying against {url} with key {zip_key!r}")

        results = []
        outcomes = {}
        for label, zip_val in (
            ("len4 '2830'", "2830"),
            ("len6 '283066'", "283066"),
            ("290-char numeric", LONG_290),
        ):
            r = pyrequests.post(url, json={zip_key: zip_val}, timeout=45)
            body = r.text[:300].replace("\n", " ")
            executed = "<executed>true</executed>" in r.text
            outcomes[label] = r.status_code
            results.append(check(
                f"TC-15 {label}",
                "Step-1 guard exits: lookup NOT executed, controlled NON-500 response",
                f"status={r.status_code}, lookupExecuted={executed}, body={body!r}",
                r.status_code != 500 and not executed,
            ))

        # control: len-5 valid zip -> lookup executes normally with city/state
        r = pyrequests.post(url, json={zip_key: NC_ZIP}, timeout=45)
        has_city = re.search(r"<city>([^<]+)</city>", r.text)
        results.append(check(
            "TC-15 len5 control",
            f"'{NC_ZIP}' executes normally -> HTTP 200 with city/state result",
            f"status={r.status_code}, city={has_city.group(1) if has_city else None!r}",
            r.status_code == 200 and bool(has_city),
        ))

        # extra observation (not gated by TC-15): unknown-but-len-5 zip status
        r = pyrequests.post(url, json={zip_key: UNKNOWN_ZIP}, timeout=45)
        print(f"[TC-15 observation] unknown len-5 ZIP '{UNKNOWN_ZIP}' -> HTTP {r.status_code} "
              f"({r.text[:160].strip()!r}) — a 500 here means unknown ZIPs still surface as "
              f"chain 5xx (feeds 5XX alarms) even though the UI stays graceful.")

        assert all(results), (
            f"SC-6: API-direct Step-1 guard violated for at least one length variant "
            f"(statuses: {outcomes}) — see EXPECTED|ACTUAL log; a 500 for a len!=5 payload "
            f"is the incident failure mode recurring API-direct (PRODUCT DEFECT)"
        )


# ============================================================================
# SC-7 [Medium] — Burst rate: ~1 request per completed entry, zero chain 500s
# Covers: TC-16
# ============================================================================
@pytest.mark.tw27302845
@pytest.mark.regression
@pytest.mark.medium
class TestTW27302845_SC7_BurstRate:
    """Scripted burst of rapid UI entries + API-direct calls: request volume stays
    ~1 per completed valid entry (nothing approaching the incident's ~537/30 s ≈ 40 req/s),
    zero lookup-chain HTTP 500s during the burst."""

    def test_sc7_burst_rate_and_no_500s(self, staff_context: BrowserContext):
        discovered = discover_chain_endpoint(staff_context)
        url = discovered["url"]
        zip_key = next((k for k, v in discovered["body"].items() if v == NC_ZIP), "zipCode")

        page = staff_context.new_page()
        results = []
        try:
            cap = ZipChainCapture(page)
            open_lt260_paper_form(page, generate_vin())
            box = zip_box(page)

            # UI leg: 8 rapid completed entries (valid NC/non-NC zips), minimal think time
            t0 = time.time()
            n0 = cap.count
            for z in VALID_NC_ZIPS:
                box.click()
                box.fill("")
                page.wait_for_timeout(200)
                box.press_sequentially(z, delay=40)
                page.wait_for_timeout(500)
            page.wait_for_timeout(4000)
            ui_window = time.time() - t0
            ui_reqs = cap.requests[n0:]
            ui_payloads = [r["zip"] for r in ui_reqs]
            ui_rate = len(ui_reqs) / max(ui_window, 1)

            results.append(check(
                "TC-16 UI volume",
                f"~1 request per completed entry ({len(VALID_NC_ZIPS)} entries -> "
                f"{len(VALID_NC_ZIPS)}..{len(VALID_NC_ZIPS) * 2} requests), all payloads 5-char "
                f"current values, rate nowhere near the incident's ~40 req/s",
                f"requests={len(ui_reqs)} in {ui_window:.1f}s ({ui_rate:.2f} req/s), "
                f"payloads={ui_payloads}",
                len(VALID_NC_ZIPS) <= len(ui_reqs) <= len(VALID_NC_ZIPS) * 2
                and all(p in VALID_NC_ZIPS for p in ui_payloads)
                and ui_rate < 5,
            ))

            ui_statuses = cap.statuses()
            results.append(check(
                "TC-16 UI 500s",
                "zero lookup-chain HTTP 500s from the UI burst",
                f"statuses={ui_statuses}",
                all(s != 500 for s in ui_statuses),
            ))
            shot(page, "SC7_ui_burst")

            # API leg: 20 rapid direct calls mixing valid / guarded len-4 / len-6 payloads
            api_statuses = []
            t1 = time.time()
            for i in range(20):
                z = ["27601", "2830", "283066", "28801"][i % 4]
                try:
                    r = pyrequests.post(url, json={zip_key: z}, timeout=30)
                    api_statuses.append(r.status_code)
                except Exception as exc:
                    api_statuses.append(f"EXC:{type(exc).__name__}")
            api_window = time.time() - t1
            five_hundreds = [s for s in api_statuses if s == 500]
            results.append(check(
                "TC-16 API burst",
                "20 rapid mixed API calls -> zero HTTP 500s (guarded lengths return "
                "controlled 4xx, valid zips 200)",
                f"statuses={api_statuses} in {api_window:.1f}s",
                len(five_hundreds) == 0,
            ))

            total = len(ui_reqs) + len(api_statuses)
            print(
                f"[TC-16] total burst volume: {total} requests over ~"
                f"{ui_window + api_window:.0f}s — incident baseline was ~537 requests / 30 s "
                f"(~40 req/s) from ONE user session."
            )
            print(
                "[TC-16] NOTE (REQ-007 partial — expected): the prod 5XX monitoring-alarm "
                "configuration is not verifiable on QA; alarm-fire verification requires the "
                "post-prod-deploy check."
            )
            assert all(results), "SC-7: one or more EXPECTED|ACTUAL checks MISMATCHED (see log)"
        finally:
            page.close()
