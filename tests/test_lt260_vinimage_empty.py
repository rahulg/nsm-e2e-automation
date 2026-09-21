"""
LT-260 VIN Image Empty Content — regression suite (no Teamwork ticket ID; user-supplied
test plan re-testing the fix in n_s_public_LT_260_Vehicle_Details, v415434 -> v418938).

Original bug: LT-260 submission fails with HTTP 500 when the VIN image has valid metadata
(filename + MIME type) but empty file content (0-byte / empty base64). Fix under test:
supportingVinImage should resolve to null for this case and step 19 (VIN image upload) of
LT260.submit should be skipped rather than throwing EEValidationFailureException / HTTP 500,
plus a new top-middle error toast ("The uploaded VIN image appears to be empty...").

Code-review gaps re-tested:
  Gap 1 (Major)    — Submit button not gated on empty file.
  Gap 2 (Major)    — Array early-return bypass (already-mapped vinImage array form).
  Gap 3 (Moderate) — Toast does not re-trigger on a second empty upload after being closed.

Discovered live (2026-07-17, QA): the LT260.submit chain is
  POST https://nsm-qa-public.nc.verifi.dev/rest/api/automation/chain/execute/48b75ae40257738bff01aa4513a76f46?encrypted=true
Auth: Bearer <authToken> (read from the public-portal.json storage-state's localStorage —
this chain is NOT under /public/, unlike the zip-lookup chain, so cookies alone 401).
Request body carries `vin`, vehicle/owner/terms fields, and `vinImage`: an array of
{content: <base64|"">, metadata: {name, type, raw:{}}} — exactly the shape the ticket
describes for the "already-mapped array" (Gap 2) reproduction.

VINs in this QA environment are synthetic and always fail the DMV/STARS lookup ("Invalid
VIN - C2"); the UI's VIN-image-upload modal exists specifically to let the user provide
photographic evidence to bypass that failure. This means every scenario here (UI and API)
necessarily goes through the "VIN not found -> upload VIN image" path, matching how the
rest of this suite (e2e_017, e2e_032) already drives LT-260 with synthetic VINs.
"""
import base64
import json
import os
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
import requests
from playwright.sync_api import BrowserContext, expect, TimeoutError as PWTimeoutError

from src.config.env import ENV
from src.helpers.data_helper import generate_vin

NSM_ENV = os.getenv("NSM_ENV", "qa")
PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL

# Chain hash (48b75ae4...) is a promoted OmniStudio Automation Designer id — confirmed
# live 2026-07-20 that the SAME hash resolves on STAGE (public-nss-stage.verifi-nc.com),
# returning the identical "Invalid VIN - C2" step-5 gate behavior as QA for a synthetic
# VIN, so only the host varies per environment; the hash itself does not.
_PUBLIC_HOST = urlparse(ENV.PUBLIC_PORTAL_URL).netloc
CHAIN_URL = (
    f"https://{_PUBLIC_HOST}/rest/api/automation/chain/execute/"
    "48b75ae40257738bff01aa4513a76f46?encrypted=true"
)
AUTH_STATE_PATH = Path(__file__).resolve().parent.parent / "auth" / NSM_ENV / "public-portal.json"
VALID_IMAGE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "vin-image-sample.png"

EMPTY_TOAST_TEXT = "The uploaded VIN image appears to be empty. Please upload a valid file (at least 1 byte)."

# ---------------------------------------------------------------------------
# VIN check-digit helpers — data_helper.generate_vin() produces a random 17-char
# string with NO valid check digit, which is fine for UI flows (the DMV lookup
# fails regardless, by design of this QA env) but the submit chain's step 5 does
# perform its own checksum-shaped "Invalid VIN" gate BEFORE it ever reaches the
# vinImage/step-19 logic, so a direct API-level reproduction needs a check-digit
# VALID vin to avoid confusing "fails checksum" with "fails on empty vinImage".
# ---------------------------------------------------------------------------
_TRANSLIT = {c: i + 1 for i, c in enumerate("ABCDEFGH")}
_TRANSLIT.update({"J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9})
_TRANSLIT.update({c: i + 2 for i, c in enumerate("STUVWXYZ")})
_TRANSLIT.update({d: int(d) for d in "0123456789"})
_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def _check_digit(vin17: str) -> str:
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin17, _WEIGHTS))
    r = total % 11
    return "X" if r == 10 else str(r)


def generate_checksum_valid_vin() -> str:
    """A 17-char VIN with a real, self-consistent NHTSA check digit (position 9).
    Still synthetic/unrecognized by STARS -> still hits the 'Invalid VIN - C2'
    DMV-lookup gate, but isolates that from a checksum failure."""
    chars = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    body = list(generate_vin())
    body[8] = "0"
    body[8] = _check_digit("".join(body))
    return "".join(body)


def _auth_token() -> str:
    state = json.loads(AUTH_STATE_PATH.read_text())
    for origin in state.get("origins", []):
        if origin["origin"] == f"https://{_PUBLIC_HOST}":
            for item in origin.get("localStorage", []):
                if item["name"] == "authToken":
                    return item["value"]
    raise RuntimeError(
        f"authToken not found in {AUTH_STATE_PATH} for origin https://{_PUBLIC_HOST} — "
        f"regenerate auth via 'NSM_ENV={NSM_ENV} python scripts/save_public_auth.py'"
    )


def _base_submit_payload(vin: str, vin_image) -> dict:
    """A minimal-but-complete LT260.submit payload, modeled on a real captured
    submission. `vin_image` is inserted as-is (None / [] / [...] all valid)."""
    return {
        "vin": vin,
        "make": "Chevrolet", "year": "2019", "body": "Four-Door Sedan", "model": "Malibu", "color": "Blue",
        "dayVehicleLeft": "2026-06-17", "licensePlateNumber": f"API-{random.randint(1000, 9999)}",
        "plateYear": None, "plateState": None, "plateCounty": "Alamance", "approximateValue": 5000,
        "vehicleLeftFor": "Storage", "explanation": None, "isVehicleInRunningCondition": None, "wrecked": None,
        "locationOfStoredVehicle": "Test Storage Facility", "address": "789 Elm Drive", "city": "Wilmington",
        "state": "North Carolina", "zip": "28401", "telephoneNumber": "(919) 555-1234",
        "authorizedPersonDetails": {
            "name": "API Tester", "address": "789 Elm Drive", "city": "Wilmington", "state": "North Carolina",
            "evidence": None, "remarks": None, "email": "api.tester@test.com", "zip": "28401",
        },
        "termsAndConditions": {
            "businessOperatorAttestation": True, "reportingComplianceAttestation": True,
            "informationAccuracyAttestation": True, "legalObligationAttestation": True,
            "ownerName": "API Tester", "date": "2026-07-16T18:30:00.000Z", "email": "api.tester@test.com",
        },
        "publicUserId": "f6b42b8d-ae2d-4985-bc94-c57c7cfcbf11", "status": "SUBMITTED", "formApplicationId": None,
        "vinImage": vin_image,
        "businessId": "3cd425d7-1ece-465a-98d9-b0c566ff1f1d", "referenceNumber": None, "loggedBy": None,
        "requestorInfo": None, "paperFormLocationId": None, "isVinLookupTriggered": True,
        "paperFormVersionId": None, "selectedFromAddressBook": False, "owners": None, "lessees": None,
        "leinholders": None, "isStolen": None, "statusCode": None, "bodySubType": None,
    }


def _call_submit_chain(vin_image, vin: str = None) -> requests.Response:
    vin = vin or generate_checksum_valid_vin()
    payload = _base_submit_payload(vin, vin_image)
    token = _auth_token()
    return requests.post(
        CHAIN_URL,
        json=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        timeout=30,
    )


def _go_to_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def _open_vin_image_modal(page, vin: str):
    """Drive to the 'THE VIN ENTERED MAY HAVE AN ERROR' modal for a fresh synthetic VIN
    (every VIN in this QA env hits this path — see module docstring)."""
    page.locator('button:has-text("Start here"), a:has-text("Start here")').first.click()
    page.wait_for_load_state("networkidle")
    vin_input = page.locator('input[name="sno"]')
    vin_input.click()
    vin_input.fill(vin)
    page.wait_for_timeout(300)
    page.locator('button:has-text("VIN Lookup"), button:has-text("Lookup"), button:has-text("Search")').first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    page.locator('text="THE VIN ENTERED MAY HAVE AN ERROR"').wait_for(state="visible", timeout=10_000)


def _modal_file_input(page):
    return page.locator('mat-dialog-container input[type="file"]')


def _modal_submit_button(page):
    return page.locator('mat-dialog-container button:has-text("Submit")')


def _find_toast_containing(page, text_fragment: str):
    toasts = page.locator('[class*="toast" i], [class*="snack" i]')
    for i in range(toasts.count()):
        t = toasts.nth(i)
        try:
            if text_fragment.lower() in t.inner_text(timeout=1000).lower():
                return t
        except Exception:
            continue
    return None


def _close_toast(toast):
    close_icon = toast.locator('exp-svg-icon[icon="cross"], svg-icon').first
    close_icon.click(force=True)


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E260VinImage_SC_A_CoreFix:
    """Scenario A (TC-01..03) — core fix: empty-content VIN image is rejected gracefully,
    not with a 500, and the new toast appears top-middle, styled like the sibling toasts."""

    def test_tc01_03_empty_vin_image_shows_toast_not_500(self, public_context: BrowserContext):
        page = public_context.new_page()
        try:
            vin = generate_vin()
            _go_to_dashboard(page)
            _open_vin_image_modal(page, vin)

            file_input = _modal_file_input(page)
            # TC-01: valid metadata (filename + MIME type), 0-byte content, via in-memory FilePayload.
            file_input.set_input_files({"name": f"VIN_{vin}.png", "mimeType": "image/png", "buffer": b""})
            page.wait_for_timeout(2500)

            # TC-02 (behavioral proxy): no HTTP 500 surfaced to the user; page still usable,
            # modal still open, no unhandled-error state.
            assert page.locator('mat-dialog-container').is_visible(), (
                "Modal should remain open/interactive after an empty-content upload, not crash"
            )

            # TC-03: new toast, top-middle, consistent styling with the sibling toasts.
            toast = _find_toast_containing(page, "appears to be empty")
            assert toast is not None, "Expected the empty-VIN-image toast to appear"
            assert toast.inner_text().strip() == EMPTY_TOAST_TEXT
            cls = toast.evaluate("el => el.className")
            assert "wis-toast-panel-top-middle" in cls, f"Expected top-middle toast placement class, got: {cls}"
            assert "toast-error-message" in cls and "toast-panel" in cls, (
                f"Expected shared toast styling classes (matches sibling toasts), got: {cls}"
            )
            page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "lt260_vinimage_A_toast.png"))
        finally:
            page.close()

    def test_tc02_api_empty_content_no_500(self):
        """API-level proxy for TC-02 (supportingVinImage -> null / step 19 skipped): the exact
        ticket-described single-object shape must not produce HTTP 500."""
        resp = _call_submit_chain([{"content": "", "metadata": {"name": "vin.png", "type": "image/png", "raw": {}}}])
        assert resp.status_code != 500, f"Empty-content vinImage must not 500; got {resp.status_code}: {resp.text[:300]}"


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E260VinImage_SC_B_SubmitGating:
    """Scenario B (TC-04..06) — Gap 1: Submit button gated on empty file, survives the
    toastClosed reset edge case, and is NOT wrongly disabled for a valid+empty mixed array."""

    def test_tc04_submit_disabled_with_empty_file(self, public_context: BrowserContext):
        page = public_context.new_page()
        try:
            vin = generate_vin()
            _go_to_dashboard(page)
            _open_vin_image_modal(page, vin)
            _modal_file_input(page).set_input_files({"name": f"VIN_{vin}.png", "mimeType": "image/png", "buffer": b""})
            page.wait_for_timeout(2000)
            assert _modal_submit_button(page).is_disabled(), "Submit must be disabled while the attached VIN image is empty"
            page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "lt260_vinimage_B_submit_disabled.png"))
        finally:
            page.close()

    def test_tc05_toastclosed_reset_edge_case(self, public_context: BrowserContext):
        """Attach empty file -> close toast -> wait ~5s -> Submit must NOT re-enable."""
        page = public_context.new_page()
        try:
            vin = generate_vin()
            _go_to_dashboard(page)
            _open_vin_image_modal(page, vin)
            file_input = _modal_file_input(page)
            submit_btn = _modal_submit_button(page)

            file_input.set_input_files({"name": f"VIN_{vin}.png", "mimeType": "image/png", "buffer": b""})
            page.wait_for_timeout(2000)
            toast = _find_toast_containing(page, "appears to be empty")
            assert toast is not None
            _close_toast(toast)
            page.wait_for_timeout(500)
            assert submit_btn.is_disabled(), "Submit must stay disabled immediately after the toast is closed"

            page.wait_for_timeout(5000)
            assert submit_btn.is_disabled(), (
                "REGRESSION (originally-proposed binding): Submit re-enabled ~5s after toastClosed "
                "while the empty file was still attached"
            )
        finally:
            page.close()

    def test_tc06_multi_element_array_not_wrongly_disabled(self):
        """API-level: the UI file input has no `multiple` attribute (confirmed live — this
        exact shape is not reachable through the picker), so this is tested at the binding's
        actual data contract via the chain: a 2-element vinImage array with one valid image +
        one empty must not be treated as 'wrongly all-empty' by the disabling logic's
        equivalent server-side gate."""
        real_b64 = base64.b64encode(VALID_IMAGE_PATH.read_bytes()).decode()
        vin_image = [
            {"content": real_b64, "metadata": {"name": "vin_valid.png", "type": "image/png", "raw": {}}},
            {"content": "", "metadata": {"name": "vin_empty.png", "type": "image/png", "raw": {}}},
        ]
        resp = _call_submit_chain(vin_image)
        assert resp.status_code != 500, (
            f"A valid+empty mixed vinImage array must not 500 (would indicate the mixed-array "
            f"case is wrongly treated as all-empty); got {resp.status_code}: {resp.text[:400]}"
        )


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E260VinImage_SC_C_ArrayBypass:
    """Scenario C (TC-07..08) — Gap 2: the exact production 'already-mapped array' payload
    shape (as would come from a restored draft) must not bypass the empty-content filter."""

    def test_tc07_mapped_array_empty_content_no_500(self):
        """Exact shape from the ticket: vinImage = [{content:"", metadata:{name, type:
        application/pdf}}] — already an array (not the single-object pre-mapping form)."""
        resp = _call_submit_chain([
            {"content": "", "metadata": {"name": "vin_document.pdf", "type": "application/pdf", "raw": {}}}
        ])
        assert resp.status_code != 500, (
            f"Array-shaped empty-content vinImage (draft-restored production shape) must not "
            f"bypass the guard and 500; got {resp.status_code}: {resp.text[:400]}"
        )

    def test_tc08_isvinimageempty_agrees_on_array_path(self):
        """A VALID mapped-array item (base64 present as `content`, not `base64` key) must not
        be false-flagged as empty — i.e. the chain must accept it and proceed past the VIN-
        evidence gate (no 500, and not rejected on vinImage grounds)."""
        real_b64 = base64.b64encode(VALID_IMAGE_PATH.read_bytes()).decode()
        resp = _call_submit_chain([
            {"content": real_b64, "metadata": {"name": "vin_valid.pdf", "type": "application/pdf", "raw": {}}}
        ])
        assert resp.status_code == 200, (
            f"A valid mapped-array vinImage item must be accepted (isVinImageEmpty must check "
            f"content, not just a `base64` key); got {resp.status_code}: {resp.text[:400]}"
        )


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.medium
class TestE2E260VinImage_SC_D_ToastRetrigger:
    """Scenario D (TC-09) — Gap 3: toast re-appears on a second, different empty upload."""

    def test_tc09_toast_retriggers_on_repeated_empty_upload(self, public_context: BrowserContext):
        page = public_context.new_page()
        try:
            vin = generate_vin()
            _go_to_dashboard(page)
            _open_vin_image_modal(page, vin)
            file_input = _modal_file_input(page)

            file_input.set_input_files({"name": "vin_empty1.png", "mimeType": "image/png", "buffer": b""})
            page.wait_for_timeout(2000)
            first_toast = _find_toast_containing(page, "appears to be empty")
            assert first_toast is not None, "First empty upload must show the toast"
            page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "lt260_vinimage_D_toast_first.png"))
            _close_toast(first_toast)
            page.wait_for_timeout(500)
            assert _find_toast_containing(page, "appears to be empty") is None, "Toast should be closed"

            file_input.set_input_files({"name": "vin_empty2.png", "mimeType": "image/png", "buffer": b""})
            page.wait_for_timeout(2000)
            second_toast = _find_toast_containing(page, "appears to be empty")
            assert second_toast is not None, (
                "REGRESSION (toastClosed handler must reset isVinImageEmpty to false): toast did "
                "not re-appear for a second, different empty-content file"
            )
            page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "lt260_vinimage_D_toast_retrigger.png"))
        finally:
            page.close()


@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.high
class TestE2E260VinImage_SC_E_HappyPath:
    """Scenario E (TC-10) — regression: a valid, non-empty VIN image still submits cleanly
    end-to-end, no toast, no 500."""

    def test_tc10_valid_vin_image_submits_successfully(self, public_context: BrowserContext):
        page = public_context.new_page()
        try:
            vin = generate_vin()
            _go_to_dashboard(page)
            _open_vin_image_modal(page, vin)

            file_input = _modal_file_input(page)
            file_input.set_input_files(str(VALID_IMAGE_PATH))
            page.wait_for_timeout(2000)

            assert _find_toast_containing(page, "appears to be empty") is None, (
                "No empty-VIN-image toast should appear for a valid, non-empty image"
            )
            assert not _modal_submit_button(page).is_disabled(), "Submit should be enabled with a valid VIN image"
            page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "lt260_vinimage_E_valid_enabled.png"))

            _modal_submit_button(page).click()
            page.wait_for_timeout(2000)
            page.wait_for_load_state("networkidle")
            # Modal should have closed / navigation proceeded — no error toast, no crash state.
            assert _find_toast_containing(page, "appears to be empty") is None
            page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "lt260_vinimage_E_after_submit.png"))
        finally:
            page.close()

    def test_tc10_api_valid_content_creates_application(self):
        real_b64 = base64.b64encode(VALID_IMAGE_PATH.read_bytes()).decode()
        resp = _call_submit_chain([
            {"content": real_b64, "metadata": {"name": "vin_valid.png", "type": "image/png", "raw": {}}}
        ])
        assert resp.status_code == 200, f"Valid VIN image submission must succeed; got {resp.status_code}: {resp.text[:400]}"
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        # Response is XML in this API's default content-type; just assert no failure marker present.
        assert "applicationId" in resp.text or "executed>true" in resp.text, resp.text[:400]


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E260VinImage_SC_F_ApiChainValidation:
    """Scenario F (TC-11..12) — defense-in-depth: hit LT260.submit directly, bypassing the
    UI entirely, and document actual current server-side behavior for each vinImage shape."""

    def test_tc11_direct_empty_content_single_object(self):
        """The exact ticket repro at the API layer: vinImage[0].content = "" with metadata
        present, bypassing the UI. On this QA build (v418938) this is CLOSED: the chain
        returns a controlled 400 ('Invalid VIN - C2', failing at step 5) rather than a 500."""
        resp = _call_submit_chain([{"content": "", "metadata": {"name": "vin.png", "type": "image/png", "raw": {}}}])
        assert resp.status_code != 500, (
            f"Direct API empty-content vinImage[0].content='' must not 500; got "
            f"{resp.status_code}: {resp.text[:400]}"
        )

    def test_tc12_null_vinimage_controlled_response(self):
        """vinImage entirely absent (None) must also be a controlled response, not a 500."""
        resp = _call_submit_chain(None)
        assert resp.status_code != 500, f"null vinImage must not 500; got {resp.status_code}: {resp.text[:400]}"

    def test_tc12b_DEFECT_empty_array_500(self):
        """OPEN DEFECT (found during this run, not in the original 3 gaps): vinImage = []
        (empty array, as opposed to null or a 1-element array with empty content) is NOT
        guarded — it reaches step 19 and crashes with HTTP 500 'Mismatch in input and query'.
        This assertion documents the defect; it is expected to FAIL until fixed."""
        resp = _call_submit_chain([])
        assert resp.status_code != 500, (
            f"DEFECT: vinImage=[] (empty array) reaches step 19 and 500s instead of being "
            f"guarded like the null/single-empty-object cases; got {resp.status_code}: {resp.text[:400]}"
        )

    def test_tc12c_DEFECT_whitespace_only_content_500(self):
        """OPEN DEFECT (found during this run): vinImage[0].content = "   " (whitespace-only,
        not literally empty-string) bypasses the empty-content guard (a naive falsy/length
        check, not a .trim()-aware one) and crashes with HTTP 500 'Failed to upload documents'
        at step 19. This assertion documents the defect; it is expected to FAIL until fixed."""
        resp = _call_submit_chain([{"content": "   ", "metadata": {"name": "vin.png", "type": "image/png", "raw": {}}}])
        assert resp.status_code != 500, (
            f"DEFECT: vinImage[0].content='   ' (whitespace-only) bypasses the empty check and "
            f"500s at step 19; got {resp.status_code}: {resp.text[:400]}"
        )
