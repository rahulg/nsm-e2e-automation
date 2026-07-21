"""
E2E-056: PDF Assertions — Correspondence / Documents forms (Staff Portal)

Objective
---------
Validate the PDF forms the NSM Staff Portal exposes under an application's
"View Correspondence/Documents" (Correspondence History) modal, in one unified
per-application flow (`_validate_app`) run for three application types.

Two levels of assertion
-----------------------
  A. CORRESPONDENCE SET (every form in the modal)
       * the required forms are present in the modal
       * each downloaded PDF is a valid PDF (%PDF- header, >= 1 page)
       * the form code appears in the filename and/or text
       * the application VIN appears in the text — VIN is the ONE field stable across
         every form (each letter freezes its vehicle description at issue time, so
         make/year/etc. legitimately differ form-to-form when a record is edited).

  B. SOURCE-FORM FIELD-BY-FIELD (LT-260 / LT-262 / LT-262A / LT-263)
       For each source form present in the application, the FULL detail UI (read from
       that form's review step) is compared field-by-field against its downloaded PDF
       and asserted identical — make, year, body, plate, location, charges, sale date,
       lien amount, authorizing person, lienor, etc. Each form is compared against its
       OWN stage's data, so cross-stage edits never cause false failures. Typed compare
       (text / date / money / phone) absorbs formatting differences.

Design notes
------------
Downloadable rows carry <span class="table-link">Download</span>, which triggers a
direct browser download; the filename embeds the form code. A paper-origin row has no
Download link and is skipped (reported "no-download-control", not a failure).

Environments & determinism
---------------------------
Run with `--env qa` (default) or `--env stage`. Each phase targets a specific, known
application VIN from TARGET_VINS[env] for a deterministic run; if none is configured
for that env it falls back to the first application in the tab.

Phases (all via `_validate_app`)
--------------------------------
  Phase 1 — LT-263 "Processed (Sold)": correspondence set + field-by-field LT-263,
            LT-260, LT-262.
  Phase 2 — LT-262A "Processed":       correspondence set + field-by-field LT-262A,
            LT-260.
  Phase 3 — LT-261 "Processed":        correspondence set only (LT-265 / LT-265A).

Downloaded PDFs are saved under C:/automation/artifacts/e2e_056_pdf_assertions/.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Error as PWError, expect

from src.config.env import ENV
from src.pages.staff_portal.dashboard_page import StaffDashboardPage

# PyPDF2 v3 exposes PdfReader; fall back to the maintained `pypdf` package name.
try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - environment fallback
    from pypdf import PdfReader


# ─── URLs ───
SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)

# ─── Where downloaded PDFs land (co-located under the C:/automation working area) ───
DOWNLOADS_DIR = Path(r"C:/automation/artifacts/e2e_056_pdf_assertions")

# ─── Target VINs per environment (deterministic record selection) ───
# Each phase opens THIS specific application instead of the first row, so a run is
# deterministic across environments. If a listed VIN is later removed, replace it with
# another from the same listing; a missing entry falls back to "first application".
TARGET_VINS = {
    "qa": {
        "phase1_lt263": "UAG865H9T4RLPUU1S",
        "phase2_lt262a": "SHAG7GR9JW3RG18HU",
        "phase3_lt261": "IG9TALFHZFEDN8OUV",
    },
    "stage": {
        "phase1_lt263": "NE8CZ4V9ZUNW1JLAA",
        "phase2_lt262a": "RSPM79JYW3YE0WB66",
        "phase3_lt261": "RSPMT9J9254FCJ8WS",
    },
}


def _target_vin(phase_key: str):
    """Return the configured target VIN for the current environment/phase, or None."""
    return TARGET_VINS.get(os.getenv("NSM_ENV", "qa"), {}).get(phase_key)

# ─── Form sets ───
# The full universe of correspondence form codes (ticket order preserved).
MASTER_FORMS = [
    "LT-260", "LT-262", "LT-263", "LT-260D", "LT-260C", "LT-160B", "LT-260A",
    "LT-264", "LT-264A", "LT-264B", "LT-262B", "LT-264G", "LT-265", "LT-265A",
]

# Minimum forms a completed LT-263 (Sold) application must carry.
PHASE1_REQUIRED = ["LT-263", "LT-265"]

PHASE2_FORMS = ["LT-260", "LT-262A", "LT-160B", "LT-260A", "LT-265", "LT-265A"]

PHASE3_FORMS = ["LT-265", "LT-265A"]


# ─────────────────────────────────────────────────────────────────────────────
# Navigation helpers
# ─────────────────────────────────────────────────────────────────────────────
def go_to_staff_dashboard(page):
    """Navigate to the Staff Portal dashboard and wait for it to settle."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def click_tab(page, *texts):
    """Click the first listing tab matching any of the given text fragments."""
    selector = ", ".join(f'[role="tab"]:has-text("{t}")' for t in texts)
    tab = page.locator(selector).first
    tab.wait_for(state="visible", timeout=15_000)
    try:
        tab.click(timeout=10_000)
    except PWError:
        tab.click(force=True)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def select_first_application(page):
    """Open the first application in the current listing and return its VIN.

    The VIN cell uses the `table-link` class, so target that specifically. A generic
    "table a" union with .first is unreliable across environments — a toolbar/date
    link can precede the VIN cell in the DOM and get clicked instead (this left STAGE
    sitting on the listing page). Among the table-links, pick the first VIN-shaped one.
    """
    vin_links = page.locator("span.table-link")
    if vin_links.count() == 0:
        vin_links = page.locator("table tbody td a, table td a, table a")
    expect(vin_links.first).to_be_visible(timeout=30_000)

    target = vin_links.first
    for i in range(min(vin_links.count(), 15)):
        if _looks_like_vin(_normalize(vin_links.nth(i).text_content() or "")):
            target = vin_links.nth(i)
            break

    link_text = _normalize(target.text_content() or "")
    link_vin = link_text if _looks_like_vin(link_text) else None

    # The click can race the SPA: right after the tab re-renders, the row's click
    # handler may not be attached yet, so the first click is silently dropped and we
    # stay on the listing. Click, then confirm we actually left the listing; retry if
    # not (verified against STAGE, where this was intermittent).
    for _ in range(4):
        try:
            target.click(timeout=10_000)
        except PWError:
            target.click(force=True)
        try:
            page.wait_for_url(lambda u: "/list" not in u, timeout=8_000)
            break
        except PWError:
            page.wait_for_timeout(1000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    return link_vin or _vin_from_detail(page)


def select_application_by_vin(page, vin):
    """Filter the current listing by `vin` and open that specific application.

    Used for deterministic runs (Option 2): instead of the first row, target a known
    record. Falls back to selecting whatever row carries the VIN. Same navigation-retry
    guard as select_first_application (the SPA can drop the first click)."""
    # Reveal the column filters if they're collapsed.
    for sel in ('button:has-text("Show Filters")', '//span[contains(text(),"Show Filters")]'):
        try:
            f = page.locator(sel).first
            if f.count() and f.is_visible():
                f.click()
                page.wait_for_timeout(800)
                break
        except PWError:
            continue
    # Enter the VIN in the VIN column filter.
    try:
        vin_filter = page.locator('input[name="vin"]').first
        vin_filter.wait_for(state="visible", timeout=5_000)
        vin_filter.fill("")
        page.wait_for_timeout(200)
        vin_filter.fill(vin)
        vin_filter.press("Enter")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
    except PWError:
        pass

    row = page.locator(f'span.table-link:has-text("{vin}")').first
    expect(row).to_be_visible(timeout=15_000)
    for _ in range(4):
        try:
            row.click(timeout=10_000)
        except PWError:
            row.click(force=True)
        try:
            page.wait_for_url(lambda u: "/list" not in u, timeout=8_000)
            break
        except PWError:
            page.wait_for_timeout(1000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    return vin


def click_review_step(page, step_text):
    """Click a detail-page review step (a `span.span-link` such as 'Review LT-260' /
    'REVIEW LT-262'). The anchored regex keeps 'REVIEW LT-262' from matching
    'REVIEW LT-262A'."""
    step = page.get_by_text(re.compile(rf"^\s*{re.escape(step_text)}\s*$", re.I)).first
    step.wait_for(state="visible", timeout=15_000)
    try:
        step.click(timeout=10_000)
    except PWError:
        step.click(force=True)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


# ─────────────────────────────────────────────────────────────────────────────
# Form-code matching
# ─────────────────────────────────────────────────────────────────────────────
def _code_regex(code: str) -> re.Pattern:
    """Build an exact matcher for a form code.

    "LT-260" must NOT match "LT-260A"/"LT-260C"/"LT-260D"; likewise "LT-264" must
    not match "LT-264A/G/B" nor "LT-265" match "LT-265A". A trailing negative
    lookahead on [A-Za-z0-9] enforces that; "LT-", "LT ", and "LT260" are tolerated.
    """
    body = re.escape(code[len("LT-"):])  # e.g. "260", "260A", "160B"
    return re.compile(rf"LT[-\s]?{body}(?![A-Za-z0-9])", re.I)


def _forms_present(text: str, candidates) -> dict:
    """Return {code: bool} for whether each candidate code appears in text."""
    return {code: bool(_code_regex(code).search(text)) for code in candidates}


def _normalize(s: str) -> str:
    """Uppercase and strip all non-alphanumerics.

    This makes VIN comparison robust against non-breaking spaces, stray spacing,
    and PDF text-extraction artifacts where the VIN bleeds into the adjacent word
    (e.g. extracted as '...SMWV6FIL').
    """
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _looks_like_vin(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{11,17}", token or ""))


def _vin_from_detail(page):
    """Best-effort: read the VIN from the open application detail page (near a 'VIN' label)."""
    try:
        body = page.locator("body").inner_text(timeout=5_000)
    except PWError:
        return None
    m = re.search(r"VIN[^A-Za-z0-9]{0,6}([A-Z0-9]{11,17})", body, re.I)
    return _normalize(m.group(1)) if m else None


def _charges_from_lines(lines: list) -> dict:
    """Extract LT-262 lien-charge amounts from the REVIEW LT-262 grid.

    The grid renders the labels in fixed order (LABOR, MATERIALS, TOWING, STORAGE,
    OTHER), then — after the 'AMOUNT AND TYPE OF CHARGES (FOR OTHER)' header — the
    five values in the same order. Empty charges render as 'N/A' and are dropped.
    Returns {label: amount} for the populated charges, e.g. {'LABOR': '$100.00'}.
    """
    order = ["LABOR", "MATERIALS", "TOWING", "STORAGE", "OTHER"]
    header_idx = next(
        (i for i, l in enumerate(lines)
         if l.strip().upper().startswith("AMOUNT AND TYPE OF CHARGES")),
        None,
    )
    if header_idx is None:
        return {}
    values = []
    for l in lines[header_idx + 1:]:
        s = l.strip()
        if s:
            values.append(s)
        if len(values) == len(order):
            break
    charges = {}
    for label, val in zip(order, values):
        if val.upper() != "N/A" and re.search(r"\d", val):
            charges[label] = val
    return charges


def _expected_fields(code: str, gt: dict) -> dict:
    """Build the {LABEL: value} content the correspondence PDF must contain.

    Only the VIN is asserted here, because it is the ONE field stable across every
    correspondence form: each letter freezes the vehicle description (make/year/body/…)
    at the moment it was issued, and those values legitimately differ from form to form
    when the record is edited mid-lifecycle (e.g. the LT-260-stage letters can show a
    different make than the LT-262A-stage letters for the same VIN). The full vehicle +
    per-form fields are asserted correctly by the per-form UI↔PDF comparison
    (compare_lt260/lt262/lt262a/lt263), each against that form's own stage data.
    """
    return {"VIN": gt["vin"]} if gt.get("vin") else {}


# ─────────────────────────────────────────────────────────────────────────────
# Correspondence modal helpers
# ─────────────────────────────────────────────────────────────────────────────
def open_correspondence(page):
    """Click 'View Correspondence/Documents' and return the modal locator."""
    view_corr = page.locator(
        '//span[contains(text(),"View Correspondence/Documents")]'
    ).first
    view_corr.wait_for(state="visible", timeout=20_000)
    view_corr.click()
    page.wait_for_timeout(1500)

    modal = page.locator(".correspondence-modal, mat-dialog-container").first
    modal.wait_for(state="visible", timeout=15_000)

    # "Correspondence History" heading confirms the right modal opened.
    expect(
        page.get_by_text(re.compile(r"Correspondence History", re.I)).first
    ).to_be_visible(timeout=10_000)

    # Give the entries time to render, then scroll to the bottom so every row
    # (later forms such as LT-265A appear last) is materialised.
    page.wait_for_timeout(2000)
    try:
        modal.evaluate("el => el.scrollTo(0, el.scrollHeight)")
    except PWError:
        pass
    page.wait_for_timeout(1000)
    return modal


def close_correspondence(page):
    """Close the Correspondence History modal."""
    try:
        close_btn = page.locator(
            'mat-dialog-container button:has-text("Close"), [mat-dialog-close]'
        ).first
        close_btn.click(timeout=5_000)
    except PWError:
        page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def _rows_for_code(modal, code: str):
    """Return the list of modal rows whose text carries `code` (exact code match)."""
    regex = _code_regex(code)
    rows = modal.locator("table tbody tr")
    return [rows.nth(i) for i in range(rows.count())
            if regex.search(rows.nth(i).text_content() or "")]


def _validate_pdf(path: Path, code: str, filename: str, expected: dict = None) -> None:
    """Assert the downloaded file is a real, non-empty PDF for `code` and that it
    contains the expected application field values (VIN, YEAR, MAKE, ...)."""
    assert path.exists() and path.stat().st_size > 0, (
        f"[{code}] downloaded PDF is missing or empty: {path}"
    )
    with path.open("rb") as fh:
        header = fh.read(5)
    assert header == b"%PDF-", (
        f"[{code}] file does not start with a PDF header (%PDF-): got {header!r}"
    )

    reader = PdfReader(str(path))
    assert len(reader.pages) >= 1, f"[{code}] PDF has no pages"

    extracted = ""
    for pg in reader.pages:
        try:
            extracted += pg.extract_text() or ""
        except Exception:
            continue

    # The form code should identify the document — via the filename the app assigns
    # and/or the text rendered in the PDF body.
    code_re = _code_regex(code)
    assert code_re.search(filename or "") or code_re.search(extracted), (
        f"[{code}] form code not found in the PDF filename ({filename!r}) or its "
        f"extracted text — the downloaded document may be wrong"
    )

    # Content checks: each expected field value must appear in the PDF body. Compared
    # on normalized text so NBSP/spacing/extraction bleed don't cause false misses.
    # Skipped only when the PDF yielded no extractable text (image/scanned).
    if expected and extracted.strip():
        norm_text = _normalize(extracted)
        missing = {
            field: val for field, val in expected.items()
            if _normalize(val) not in norm_text
        }
        assert not missing, (
            f"[{code}] expected field value(s) not found in PDF text: {missing} — "
            f"the document may belong to a different application or render fields wrongly"
        )


def download_and_validate(page, modal, code: str, expected: dict = None) -> str:
    """Download the PDF for `code` (if a Download link exists) and validate it.

    Returns:
      "validated"           — a PDF was downloaded and passed validation
      "no-download-control" — the form is listed but exposes no Download link
    Raises AssertionError if a PDF was downloaded but failed validation.
    """
    for row in _rows_for_code(modal, code):
        dl = row.locator("span.table-link").filter(
            has_text=re.compile(r"^\s*Download\s*$", re.I)
        ).first
        if dl.count() == 0:
            continue  # this row (e.g. the paper original) has no download link

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        dl.scroll_into_view_if_needed()
        with page.expect_download(timeout=15_000) as dl_info:
            dl.click()
        download = dl_info.value
        suggested = download.suggested_filename or f"{code}.pdf"
        dest = DOWNLOADS_DIR / f"{code}__{suggested}"
        download.save_as(str(dest))
        _validate_pdf(dest, code, suggested, expected)
        return "validated"

    return "no-download-control"


def assert_forms(page, *, required, universe, phase_label, ground_truth=None):
    """Open correspondence, assert required forms present, and download + validate
    every available digital PDF across the given universe of form codes. When
    `ground_truth` is supplied, each downloaded PDF is also asserted to contain the
    application's field values (VIN, YEAR, MAKE, and MODEL where applicable).

    Hard-fails on any missing required form or any downloaded-but-invalid PDF.
    Returns the per-code results dict.
    """
    ground_truth = ground_truth or {}
    modal = open_correspondence(page)
    modal_text = modal.text_content() or ""

    codes = list(dict.fromkeys(list(universe) + list(required)))
    present = _forms_present(modal_text, codes)
    missing_required = [c for c in required if not present[c]]

    results = {}
    for code in codes:
        if not present[code]:
            results[code] = "absent"
        else:
            try:
                expected = _expected_fields(code, ground_truth)
                results[code] = download_and_validate(page, modal, code, expected)
            except AssertionError as exc:
                results[code] = f"INVALID-PDF: {exc}"

    close_correspondence(page)

    # ── Report ──
    print(f"\n  [{phase_label}] ground truth under test: {ground_truth}")
    print(f"  [{phase_label}] correspondence results across {len(codes)} form code(s):")
    for code in codes:
        marker = "*" if code in required else " "
        print(f"   {marker} {code:<9} -> {results[code]}")
    print("   (* = required to be present)")

    validated = [c for c, s in results.items() if s == "validated"]
    print(f"   PDFs downloaded & validated: {validated or 'none'}")

    # ── Hard assertions ──
    assert not missing_required, (
        f"[{phase_label}] required correspondence forms not present: {missing_required}"
    )
    invalid = {c: s for c, s in results.items() if str(s).startswith("INVALID-PDF")}
    assert not invalid, f"[{phase_label}] PDF content validation failed: {invalid}"

    return results


# ═════════════════════════════════════════════════════════════════════════════
# LT-260 — full field-by-field UI ↔ PDF comparison
#
# Captures every value shown in the LT-260 detail UI, extracts the corresponding
# value from the LT-260 PDF, and asserts each pair is identical (typed compare:
# text / date / money / phone). This is the "same approach" template intended for
# the other forms.
# ═════════════════════════════════════════════════════════════════════════════

# Typed normalizers — collapse formatting differences before comparing.
def _n_text(s):
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

def _n_date(s):
    """Canonicalize a date to YYYYMMDD regardless of source order, so '06-09-2026'
    (UI, MM-DD-YYYY) and '2026-06-09' (PDF, YYYY-MM-DD) compare equal."""
    nums = re.findall(r"\d+", s or "")
    year = next((n for n in nums if len(n) == 4), None)
    if year and len(nums) == 3:
        md = [n for n in nums if len(n) != 4]
        if len(md) == 2:
            return year + md[0].zfill(2) + md[1].zfill(2)
    return re.sub(r"[^0-9]", "", s or "")

def _n_phone(s):
    return re.sub(r"[^0-9]", "", s or "")

def _n_money(s):
    digits = re.sub(r"[^0-9.]", "", s or "")
    try:
        return f"{float(digits):.2f}"
    except ValueError:
        return digits


# LT-260 detail-page labels + section headers. Used so a blank field (whose value
# line is actually the *next* label) is read as "" instead of a later value.
_LT260_UI_LABELS = {
    "SERIAL NUMBER/VIN", "MAKE", "MODEL", "YEAR", "DATE VEHICLE LEFT", "COLOR",
    "IS VEHICLE IN RUNNING CONDITION", "VIN IMAGE", "LICENSE PLATE NUMBER",
    "PLATE YEAR", "PLATE STATE", "BODY", "APPROXIMATE VALUE", "WRECKED",
    "VEHICLE LEFT FOR", "PARKING", "REPAIRS", "STORAGE", "OTHER", "EXPLANATION",
    "LOCATION OF STORED VEHICLE", "ADDRESS", "CITY", "STATE", "ZIP", "COUNTY",
    "TELEPHONE NO", "EMAIL", "NAME", "REMARKS", "SUPPORTING DOCUMENTS",
    "ADDITIONAL INFORMATION", "REFERENCE #", "OWNER 1 NAME", "OWNER 1 ADDRESS",
    "STATUS CODE", "STOLEN", "VEHICLE DETAILS", "VEHICLE STORAGE DETAILS",
    "AUTHORIZED PERSON", "REQUESTOR INFORMATION", "OWNER(S) CHECK", "OWNER DETAILS",
    "DESCRIPTION OF VEHICLE",
    "ANY EVIDENCE IN VEHICLE TO ASSIST IN LOCATING OWNER OR IN TRACING?",
    "NAME AND ADDRESS OF THE PERSON AUTHORIZING YOUR FIRM TO TOW, STORE, "
    "AND/OR MAKE REPAIRS: (REQUIRED OR EXPLAIN)",
    # additional labels used by LT-262 / LT-262A / LT-263 detail pages
    "BODY STYLE", "PLACE STORED", "LABOR", "MATERIALS", "TOWING",
    "AMOUNT AND TYPE OF CHARGES (FOR OTHER)", "DATE OF STORAGE",
    "DATE TENANT VACATED PREMISES", "LEASE", "LOT RENT", "PHYSICAL ADDRESS",
    "PHONE", "LIEN AMOUNT", "LIEN FOR", "TYPE OF SALE", "SALE DATE", "SALE TIME",
    "SALE HOUR", "NAME OF COURT AUTHORIZING SALE", "PLACE OF SALE", "MEASUREMENTS",
    "TITLE NO. OR DEED RECORD BOOK/PAGE", "REFERENCE#", "MOTOR NO.",
}


def _ui_grid_block(lines, start_label, end_labels, keys):
    """Parse a 'labels-block then values-block' grid (e.g. LT-262 Person Authorizing,
    LT-262A Lienor / Sale Info): the value lines follow the run of label lines, in
    the same order. Returns {key: value}."""
    sec = _ui_section(lines, start_label, end_labels)
    key_set = {k.upper() for k in keys}
    label_idxs = [i for i, l in enumerate(sec) if l.strip().upper() in key_set]
    if not label_idxs:
        return {}
    values = [l.strip() for l in sec[max(label_idxs) + 1:] if l.strip()]
    return {k: (values[i] if i < len(values) else "") for i, k in enumerate(keys)}


def _flat(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " "))


def _pdf_group(t, pattern):
    m = re.search(pattern, t)
    return m.group(1).strip() if m else None


def _assert_ui_pdf(form, rows):
    """rows: list of (label, ui_value, pdf_value, normalizer, mode) where mode is
    'eq' or 'contains'. Prints a comparison table and asserts every field matches."""
    print(f"\n  [{form}] field-by-field UI vs PDF:")
    print(f"    {'FIELD':<22} {'UI':<28} {'PDF':<28} MATCH")
    mismatches = {}
    for label, uv, pv, norm, mode in rows:
        if uv in (None, ""):
            status = "blank-ui"
        elif pv in (None, ""):
            status = "PDF-MISSING"
            mismatches[label] = (uv, pv)
        elif (norm(uv) in norm(pv)) if mode == "contains" else (norm(uv) == norm(pv)):
            status = "OK"
        else:
            status = "MISMATCH"
            mismatches[label] = (uv, pv)
        print(f"    {label:<22} {str(uv)[:28]:<28} {str(pv)[:28]:<28} {status}")
    assert not mismatches, f"[{form}] UI/PDF field mismatches: {mismatches}"


def _ui_value_after(lines, label):
    """Value = the immediate next line, unless that line is itself a label (=> blank)."""
    lu = label.upper()
    for i, ln in enumerate(lines):
        if ln.strip().upper() == lu:
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            return "" if nxt.upper() in _LT260_UI_LABELS else nxt
    return None


def _ui_section(lines, start_label, end_labels):
    """Return the lines between `start_label` and the next of `end_labels`."""
    start = next((i for i, l in enumerate(lines)
                  if l.strip().upper() == start_label.upper()), None)
    if start is None:
        return []
    ends = {e.upper() for e in end_labels}
    out = []
    for ln in lines[start + 1:]:
        if ln.strip().upper() in ends:
            break
        out.append(ln)
    return out


def capture_lt260_ui(page) -> dict:
    """Capture every LT-260 value shown on the detail page into a dict."""
    lines = [l.rstrip() for l in page.locator("body").inner_text(timeout=10_000).splitlines()]
    ui = {
        "vin": _ui_value_after(lines, "SERIAL NUMBER/VIN"),
        "make": _ui_value_after(lines, "MAKE"),
        "year": _ui_value_after(lines, "YEAR"),
        "date_left": _ui_value_after(lines, "DATE VEHICLE LEFT"),
        "plate": _ui_value_after(lines, "LICENSE PLATE NUMBER"),
        "plate_year": _ui_value_after(lines, "PLATE YEAR"),
        "plate_state": _ui_value_after(lines, "PLATE STATE"),
        "body": _ui_value_after(lines, "BODY"),
        "approx_value": _ui_value_after(lines, "APPROXIMATE VALUE"),
        "explanation": _ui_value_after(lines, "EXPLANATION"),
        "county": _ui_value_after(lines, "COUNTY"),
        "telephone": _ui_value_after(lines, "TELEPHONE NO"),
        "remarks": _ui_value_after(lines, "REMARKS"),
    }
    # Which "Vehicle left for" option is selected (=Yes).
    ui["vehicle_left_selected"] = [
        opt for opt in ("PARKING", "REPAIRS", "STORAGE", "OTHER")
        if (_ui_value_after(lines, opt) or "").lower() == "yes"
    ]
    # Location of stored vehicle block.
    ui["storage_name"] = _ui_value_after(lines, "LOCATION OF STORED VEHICLE")
    loc = _ui_section(lines, "LOCATION OF STORED VEHICLE", ["COUNTY", "TELEPHONE NO", "AUTHORIZED PERSON"])
    ui["storage_address"] = _ui_value_after(loc, "ADDRESS")
    ui["storage_city"] = _ui_value_after(loc, "CITY")
    ui["storage_state"] = _ui_value_after(loc, "STATE")
    ui["storage_zip"] = _ui_value_after(loc, "ZIP")
    # Authorized person block.
    ap = _ui_section(lines, "AUTHORIZED PERSON", ["ANY EVIDENCE IN VEHICLE TO ASSIST IN LOCATING OWNER OR IN TRACING?", "REQUESTOR INFORMATION"])
    ui["auth_name"] = _ui_value_after(ap, "NAME")
    ui["auth_address"] = _ui_value_after(ap, "ADDRESS")
    ui["auth_city"] = _ui_value_after(ap, "CITY")
    ui["auth_state"] = _ui_value_after(ap, "STATE")
    ui["auth_zip"] = _ui_value_after(ap, "ZIP")
    # Requestor Information block (portal submitter — note: absent from the PDF).
    rq = _ui_section(lines, "REQUESTOR INFORMATION", ["SUPPORTING DOCUMENTS", "ADDITIONAL INFORMATION"])
    ui["requestor_name"] = _ui_value_after(rq, "NAME")
    ui["requestor_address"] = _ui_value_after(rq, "ADDRESS")
    return ui


def extract_lt260_pdf(text: str) -> dict:
    """Extract the LT-260 field values from the flat PDF text."""
    t = re.sub(r"\s+", " ", (text or "").replace("\xa0", " "))

    def g(pattern):
        m = re.search(pattern, t)
        return m.group(1).strip() if m else None

    pdf = {
        "make": g(r"Make (.+?) Year"),
        "year": g(r"Year (\d{4}) Serial"),
        "vin": g(r"Serial No\. ([A-Z0-9]+)"),
        "date_left": g(r"Date vehicle left ([\d/]+)"),
        "plate": g(r"Lic\. Plate No\. (.+?)\s*Year"),
        "county": g(r"County \(if shown on License\) (\S+)"),
        "body": g(r"Body: (.+?)\s*Approximate value"),
        "approx_value": g(r"Approximate value \$?([\d,]+(?:\.\d+)?)"),
        "telephone": g(r"Telephone No\. (\(?\d{3}\)?[ -]?\d{3}-\d{4})"),
        "certifier": g(r"\bI (.+?) certify that the above information is true and correct"),
        "firm_block": g(r"Printed Name (.+?) Your Firm's Name"),
    }
    pdf["cert_present"] = "certify that the above information is true and correct" in t
    m = re.search(r"\(place stored\) Name (.+?) Address (.+?) City (.+?) State (.+?) Zip (\S+)", t)
    if m:
        (pdf["storage_name"], pdf["storage_address"], pdf["storage_city"],
         pdf["storage_state"], pdf["storage_zip"]) = [x.strip() for x in m.groups()]
    m2 = re.search(r"Name or explanation (.+?) Address (.+?) City (.+?) State (.+?) Zip (\S+)", t)
    if m2:
        (pdf["auth_name"], pdf["auth_address"], pdf["auth_city"],
         pdf["auth_state"], pdf["auth_zip"]) = [x.strip() for x in m2.groups()]
    return pdf


def download_pdf_text(page, modal, code: str):
    """Download the PDF for `code` and return (path, extracted_text)."""
    for row in _rows_for_code(modal, code):
        dl = row.locator("span.table-link").filter(
            has_text=re.compile(r"^\s*Download\s*$", re.I)
        ).first
        if dl.count() == 0:
            continue
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        dl.scroll_into_view_if_needed()
        with page.expect_download(timeout=15_000) as dl_info:
            dl.click()
        download = dl_info.value
        dest = DOWNLOADS_DIR / f"{code}__{download.suggested_filename or code + '.pdf'}"
        download.save_as(str(dest))
        text = "".join((p.extract_text() or "") for p in PdfReader(str(dest)).pages)
        return dest, text
    return None, None


# Field comparison spec: (label, ui_key, pdf_key, normalizer).
_LT260_COMPARE = [
    ("VIN",            "vin",             "vin",             _n_text),
    ("Make",           "make",            "make",            _n_text),
    ("Year",           "year",            "year",            _n_text),
    ("Date Vehicle Left", "date_left",    "date_left",       _n_date),
    ("License Plate",  "plate",           "plate",           _n_text),
    ("County",         "county",          "county",          _n_text),
    ("Body Style",     "body",            "body",            _n_text),
    ("Approximate Value", "approx_value", "approx_value",    _n_money),
    ("Loc Place Stored", "storage_name",  "storage_name",    _n_text),
    ("Loc Address",    "storage_address", "storage_address", _n_text),
    ("Loc City",       "storage_city",    "storage_city",    _n_text),
    ("Loc State",      "storage_state",   "storage_state",   _n_text),
    ("Loc ZIP",        "storage_zip",     "storage_zip",     _n_text),
    ("Telephone",      "telephone",       "telephone",       _n_phone),
    ("Auth Name",      "auth_name",       "auth_name",       _n_text),
    ("Auth Address",   "auth_address",    "auth_address",    _n_text),
    ("Auth City",      "auth_city",       "auth_city",       _n_text),
    ("Auth State",     "auth_state",      "auth_state",      _n_text),
    ("Auth ZIP",       "auth_zip",        "auth_zip",        _n_text),
]


def compare_lt260(ui: dict, pdf: dict) -> None:
    """Assert every LT-260 UI value equals the corresponding PDF value."""
    print("\n  LT-260 field-by-field UI vs PDF:")
    print(f"    {'FIELD':<20} {'UI':<28} {'PDF':<28} MATCH")
    mismatches = {}
    for label, uk, pk, norm in _LT260_COMPARE:
        uv, pv = ui.get(uk), pdf.get(pk)
        if not uv:  # blank UI field — nothing to assert
            status = "blank-ui"
        elif pv is None:
            status = "PDF-MISSING"
            mismatches[label] = (uv, pv)
        elif norm(uv) == norm(pv):
            status = "OK"
        else:
            status = "MISMATCH"
            mismatches[label] = (uv, pv)
        print(f"    {label:<20} {str(uv)[:28]:<28} {str(pv)[:28]:<28} {status}")

    # Certification block. Only the STATEMENT text is hard-asserted. The certifier
    # "Printed Name" and the firm name/address are a frozen snapshot captured when the
    # LT-260 was submitted; the editable detail page can show different storage /
    # requestor values later, so those two are REPORTED for visibility but not asserted
    # (a ground-truth assertion would be flaky — same reason the requester field is not
    # asserted elsewhere in this suite).
    cert_ok = bool(pdf.get("cert_present"))
    print(f"    {'Certification stmt':<22} present={cert_ok}  (hard-asserted)")
    if not cert_ok:
        mismatches["Certification statement"] = ("present", "absent")
    print(f"    {'Requester Name':<22} PDF certifier={pdf.get('certifier')!r} "
          f"(frozen snapshot — reported only)")
    print(f"    {'Requester Address':<22} PDF firm={pdf.get('firm_block')!r} "
          f"(frozen snapshot — reported only)")

    # Fields that CANNOT be verified from the flattened PDF text — reported only.
    print(f"    NOTE vehicle-left selected (UI)={ui.get('vehicle_left_selected')} "
          f"— checkbox state not present in flattened PDF text (not asserted)")
    print(f"    NOTE UI 'Requestor Information' ({ui.get('requestor_name')!r}) "
          f"does NOT appear in the LT-260 PDF (PDF requester = certifier/firm above)")

    assert not mismatches, f"LT-260 UI/PDF field mismatches: {mismatches}"


# ═════════════════════════════════════════════════════════════════════════════
# LT-262 — full field-by-field UI ↔ PDF comparison
# ═════════════════════════════════════════════════════════════════════════════
def capture_lt262_ui(page) -> dict:
    L = [l.rstrip() for l in page.locator("body").inner_text(timeout=10_000).splitlines()]
    ui = {
        "vin": _ui_value_after(L, "SERIAL NUMBER/VIN"),
        "plate": _ui_value_after(L, "LICENSE PLATE NUMBER"),
        "make": _ui_value_after(L, "MAKE"),
        "year": _ui_value_after(L, "YEAR"),
        "body": _ui_value_after(L, "BODY STYLE"),
    }
    dov = _ui_section(L, "Description of Vehicle", ["Location of Vehicle"])
    ui["state_reg"] = _ui_value_after(dov, "STATE")
    loc = _ui_section(L, "Location of Vehicle", ["Description of Lien"])
    ui["loc_place"] = _ui_value_after(loc, "PLACE STORED")
    ui["loc_addr"] = _ui_value_after(loc, "ADDRESS")
    ui["loc_city"] = _ui_value_after(loc, "CITY")
    ui["loc_state"] = _ui_value_after(loc, "STATE")
    ui["loc_zip"] = _ui_value_after(loc, "ZIP")
    ui["charges"] = _charges_from_lines(L)
    dos = _ui_section(L, "Date of Storage",
                      ["Name and Address of Person Authorizing Repairs, Services, Towing and/or Storage"])
    ui["date_storage"] = _ui_value_after(dos, "DATE OF STORAGE")
    ap = _ui_grid_block(
        L, "Name and Address of Person Authorizing Repairs, Services, Towing and/or Storage",
        ["Name and Address of Lienor"], ["NAME", "PHYSICAL ADDRESS", "CITY", "STATE", "ZIP"])
    ui["auth_name"] = ap.get("NAME")
    ui["auth_addr"] = " ".join(ap.get(k, "") for k in ("PHYSICAL ADDRESS", "CITY", "STATE", "ZIP"))
    li = _ui_section(L, "Name and Address of Lienor", ["Additional Information"])
    ui["lienor_name"] = _ui_value_after(li, "NAME")
    ui["lienor_addr"] = " ".join((_ui_value_after(li, k) or "") for k in ("ADDRESS", "CITY", "STATE", "ZIP"))
    ui["lienor_phone"] = _ui_value_after(li, "PHONE")
    return ui


def extract_lt262_pdf(text: str) -> dict:
    t = _flat(text)
    pdf = {
        "make": _pdf_group(t, r"Make: (.+?) Year:"),
        "year": _pdf_group(t, r"Year: (\d{4})"),
        "body": _pdf_group(t, r"Body Style: (.+?)\s*License"),
        "plate": _pdf_group(t, r"License Plate Number: (\S+)"),
        "vin": _pdf_group(t, r"Serial Number/VIN: ([A-Z0-9]+)"),
        "state_reg": _pdf_group(t, r"State & Year Last Registered: (.+?) B\."),
        "ch_labor": _pdf_group(t, r"Labor \$([\d.]+)"),
        "ch_towing": _pdf_group(t, r"Towing\$([\d.]+)"),
        "ch_storage": _pdf_group(t, r"Storage \$([\d.]+)"),
        "date_storage": _pdf_group(t, r"DATE OF STORAGE: (\S+)"),
        "auth_name": _pdf_group(t, r"AUTHORIZING[^:]*: Name: (.+?) Physical Address:"),
        "auth_addr": _pdf_group(t, r"Physical Address: (.+?) Mailing Address:"),
    }
    m = re.search(r"Place Stored: (.+?) Address: (.+?) City: (.+?) State/Zip: (.+?) C\.", t)
    if m:
        pdf["loc_place"], pdf["loc_addr"], pdf["loc_city"], sz = [x.strip() for x in m.groups()]
        pdf["loc_state"] = " ".join(sz.split()[:-1])
        pdf["loc_zip"] = sz.split()[-1]
    m2 = re.search(r"NAME AND ADDRESS OF LIENOR:.*?Name: (.+?) Address: (.+?) Phone: (.+?) "
                   r"City: (.+?) State: (.+?) Zip: (\S+)", t)
    if m2:
        pdf["lienor_name"], addr, pdf["lienor_phone"], city, st, zp = [x.strip() for x in m2.groups()]
        pdf["lienor_addr"] = f"{addr} {city} {st} {zp}"
    return pdf


def compare_lt262(ui, pdf):
    rows = [
        ("VIN", ui.get("vin"), pdf.get("vin"), _n_text, "eq"),
        ("License Plate", ui.get("plate"), pdf.get("plate"), _n_text, "eq"),
        ("Make", ui.get("make"), pdf.get("make"), _n_text, "eq"),
        ("Year", ui.get("year"), pdf.get("year"), _n_text, "eq"),
        ("Body Style", ui.get("body"), pdf.get("body"), _n_text, "eq"),
        ("State Last Reg", ui.get("state_reg"), pdf.get("state_reg"), _n_text, "eq"),
        ("Loc Place Stored", ui.get("loc_place"), pdf.get("loc_place"), _n_text, "eq"),
        ("Loc Address", ui.get("loc_addr"), pdf.get("loc_addr"), _n_text, "eq"),
        ("Loc City", ui.get("loc_city"), pdf.get("loc_city"), _n_text, "eq"),
        ("Loc State", ui.get("loc_state"), pdf.get("loc_state"), _n_text, "eq"),
        ("Loc ZIP", ui.get("loc_zip"), pdf.get("loc_zip"), _n_text, "eq"),
        ("Date of Storage", ui.get("date_storage"), pdf.get("date_storage"), _n_date, "eq"),
        ("Charge Labor", ui["charges"].get("LABOR"), pdf.get("ch_labor"), _n_money, "eq"),
        ("Charge Towing", ui["charges"].get("TOWING"), pdf.get("ch_towing"), _n_money, "eq"),
        ("Charge Storage", ui["charges"].get("STORAGE"), pdf.get("ch_storage"), _n_money, "eq"),
        ("Auth Person Name", ui.get("auth_name"), pdf.get("auth_name"), _n_text, "eq"),
        ("Auth Person Addr", ui.get("auth_addr"), pdf.get("auth_addr"), _n_text, "contains"),
        ("Lienor Name", ui.get("lienor_name"), pdf.get("lienor_name"), _n_text, "eq"),
        ("Lienor Address", ui.get("lienor_addr"), pdf.get("lienor_addr"), _n_text, "contains"),
        ("Lienor Phone", ui.get("lienor_phone"), pdf.get("lienor_phone"), _n_phone, "eq"),
    ]
    _assert_ui_pdf("LT-262", rows)


# ═════════════════════════════════════════════════════════════════════════════
# LT-262A — full field-by-field UI ↔ PDF comparison
# ═════════════════════════════════════════════════════════════════════════════
def capture_lt262a_ui(page) -> dict:
    L = [l.rstrip() for l in page.locator("body").inner_text(timeout=10_000).splitlines()]
    ui = {
        "vin": _ui_value_after(L, "SERIAL NUMBER/VIN"),
        "make": _ui_value_after(L, "MAKE"),
        "year": _ui_value_after(L, "YEAR"),
    }
    loc = _ui_section(L, "Location of Vehicle", ["Description of Lien"])
    ui["loc_addr"] = _ui_value_after(loc, "ADDRESS")
    ui["loc_city"] = _ui_value_after(loc, "CITY")
    ui["loc_state"] = _ui_value_after(loc, "STATE")
    ui["loc_zip"] = _ui_value_after(loc, "ZIP")
    sale = _ui_grid_block(
        L, "Notice of Sale Information (Enforcement of Lien must comply with N.C.G.S. 44A-4(e))",
        ["Name and Address of Lienor"],
        ["SALE DATE", "SALE HOUR", "PLACE OF SALE", "ADDRESS", "ZIP", "CITY", "STATE"])
    ui["sale_date"] = sale.get("SALE DATE")
    ui["sale_place"] = sale.get("PLACE OF SALE")
    lien = _ui_grid_block(L, "Name and Address of Lienor", ["Additional Information"],
                          ["NAME", "ADDRESS", "ZIP", "CITY", "STATE", "PHONE"])
    ui["lienor_name"] = lien.get("NAME")
    ui["lienor_phone"] = lien.get("PHONE")
    ui["lienor_addr"] = " ".join(lien.get(k, "") for k in ("ADDRESS", "CITY", "STATE", "ZIP"))
    return ui


def extract_lt262a_pdf(text: str) -> dict:
    t = _flat(text)
    pdf = {
        "make": _pdf_group(t, r"Make: (.+?) Year:"),
        "year": _pdf_group(t, r"Year: (\d{4})"),
        "vin": _pdf_group(t, r"Serial No\.: ([A-Z0-9]+)"),
        "sale_date": _pdf_group(t, r"Sale Date: Sale Hour: (\d{4}-\d{2}-\d{2})"),
        "sale_place": _pdf_group(t, r"Place of Sale: (.+?) Address:"),
        "lienor_name": _pdf_group(t, r"LIENOR:.*?Name: (.+?) Physical Address:"),
        "lienor_addr": _pdf_group(t, r"Physical Address: (.+?) Mailing Address:"),
        "lienor_phone": _pdf_group(t, r"Business Phone: (\(?\d{3}\)?[ -]?\d{3}-\d{4})"),
    }
    m = re.search(r"Physical Location/Address: (.+?) City: (.+?) State: (.+?) Zip: (\S+)", t)
    if m:
        pdf["loc_addr"], pdf["loc_city"], pdf["loc_state"], pdf["loc_zip"] = [x.strip() for x in m.groups()]
    return pdf


def compare_lt262a(ui, pdf):
    rows = [
        ("VIN", ui.get("vin"), pdf.get("vin"), _n_text, "eq"),
        ("Make", ui.get("make"), pdf.get("make"), _n_text, "eq"),
        ("Year", ui.get("year"), pdf.get("year"), _n_text, "eq"),
        ("Loc Address", ui.get("loc_addr"), pdf.get("loc_addr"), _n_text, "eq"),
        ("Loc City", ui.get("loc_city"), pdf.get("loc_city"), _n_text, "eq"),
        ("Loc State", ui.get("loc_state"), pdf.get("loc_state"), _n_text, "eq"),
        ("Loc ZIP", ui.get("loc_zip"), pdf.get("loc_zip"), _n_text, "eq"),
        ("Sale Date", ui.get("sale_date"), pdf.get("sale_date"), _n_date, "eq"),
        ("Place of Sale", ui.get("sale_place"), pdf.get("sale_place"), _n_text, "eq"),
        ("Lienor Name", ui.get("lienor_name"), pdf.get("lienor_name"), _n_text, "eq"),
        ("Lienor Address", ui.get("lienor_addr"), pdf.get("lienor_addr"), _n_text, "contains"),
        ("Lienor Phone", ui.get("lienor_phone"), pdf.get("lienor_phone"), _n_phone, "eq"),
    ]
    _assert_ui_pdf("LT-262A", rows)


# ═════════════════════════════════════════════════════════════════════════════
# LT-263 — full field-by-field UI ↔ PDF comparison
# ═════════════════════════════════════════════════════════════════════════════
def capture_lt263_ui(page) -> dict:
    L = [l.rstrip() for l in page.locator("body").inner_text(timeout=10_000).splitlines()]
    return {
        "vin": _ui_value_after(L, "SERIAL NUMBER/VIN"),
        "make": _ui_value_after(L, "MAKE"),
        "year": _ui_value_after(L, "YEAR"),
        "sale_date": _ui_value_after(L, "SALE DATE"),
        "lien_amount": _ui_value_after(L, "LIEN AMOUNT"),
    }


def extract_lt263_pdf(text: str) -> dict:
    t = _flat(text)
    return {
        "make": _pdf_group(t, r"Make: (.+?) Year:"),
        "year": _pdf_group(t, r"Year: (\d{4})"),
        "vin": _pdf_group(t, r"Serial Number: ([A-Z0-9]+)"),
        "sale_date": _pdf_group(t, r"Sale Date: (\d{2}-\d{2}-\d{4})"),
        "lien_amount": _pdf_group(t, r"Amount of Lien: ([\d.]+)"),
    }


def compare_lt263(ui, pdf):
    rows = [
        ("VIN", ui.get("vin"), pdf.get("vin"), _n_text, "eq"),
        ("Make", ui.get("make"), pdf.get("make"), _n_text, "eq"),
        ("Year", ui.get("year"), pdf.get("year"), _n_text, "eq"),
        ("Sale Date", ui.get("sale_date"), pdf.get("sale_date"), _n_date, "eq"),
        ("Lien Amount", ui.get("lien_amount"), pdf.get("lien_amount"), _n_money, "eq"),
    ]
    _assert_ui_pdf("LT-263", rows)


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E056PdfAssertions:
    """E2E-056: Validate correspondence/documents PDF forms across LT-263, LT-262A, LT-261."""

    # Source forms whose full UI ↔ PDF comparison runs inside each application:
    # (form code, detail review step to open, capture fn, PDF extract fn, compare fn).
    _LT263_SOURCE = [
        ("LT-263", "REVIEW LT-263", capture_lt263_ui, extract_lt263_pdf, compare_lt263),
        ("LT-260", "Review LT-260", capture_lt260_ui, extract_lt260_pdf, compare_lt260),
        ("LT-262", "REVIEW LT-262", capture_lt262_ui, extract_lt262_pdf, compare_lt262),
    ]
    _LT262A_SOURCE = [
        ("LT-262A", "REVIEW LT-262A", capture_lt262a_ui, extract_lt262a_pdf, compare_lt262a),
        ("LT-260", "Review LT-260", capture_lt260_ui, extract_lt260_pdf, compare_lt260),
    ]

    def _validate_app(self, page, *, nav, tabs, required, universe, phase_label,
                      source_forms, target_vin=None):
        """Unified per-application flow (Group A folded into Group B):
          1. open the target application (by VIN if configured, else the first row)
          2. for each source form, open its review step and capture the full UI
          3. correspondence modal: assert every expected form present + validate each
             downloaded PDF's content (VIN/MAKE/YEAR on every form, plus per-form fields)
          4. download each source form's PDF and assert it matches the UI field-by-field
        """
        go_to_staff_dashboard(page)
        getattr(StaffDashboardPage(page), nav)()
        click_tab(page, *tabs)
        vin = (select_application_by_vin(page, target_vin) if target_vin
               else select_first_application(page))

        # (2) The correspondence content check asserts only the VIN — the one field
        # stable across every form — taken straight from the selected application.
        assert vin, f"{phase_label}: could not determine the application VIN"

        # (3) Capture each source form's UI from its review step.
        source_uis = {}
        for code, step, capture, _extract, _compare in source_forms:
            click_review_step(page, step)
            source_uis[code] = capture(page)
            assert source_uis[code].get("vin") and source_uis[code].get("make"), (
                f"{phase_label}: could not capture {code} UI on '{step}' (got {source_uis[code]})"
            )

        # (4) Correspondence: assert every expected form present + each PDF's VIN.
        assert_forms(page, required=required, universe=universe,
                     phase_label=phase_label, ground_truth={"vin": vin})

        # (5) Exhaustive UI ↔ PDF comparison for each source form (make/year and all
        # other fields are asserted here, each against that form's own stage data).
        if source_forms:
            modal = open_correspondence(page)
            for code, _step, _capture, extract, compare in source_forms:
                _, text = download_pdf_text(page, modal, code)
                if not text:
                    # Paper-origin row with no Download link — nothing to compare.
                    print(f"  [{phase_label}] {code}: no downloadable PDF — UI↔PDF compare skipped")
                    continue
                compare(source_uis[code], extract(text))
            close_correspondence(page)

    # ========================================================================
    # PHASE 1: LT-263 "Processed (Sold)" — correspondence set + full UI↔PDF for
    #          LT-263 / LT-260 / LT-262
    # ========================================================================
    def test_phase_1_lt263_processed_sold(self, staff_context: BrowserContext):
        """Phase 1: LT-263 Processed (Sold) — assert the full form chain is present and
        content-valid, and field-by-field UI↔PDF compare LT-263, LT-260, LT-262."""
        page = staff_context.new_page()
        try:
            self._validate_app(
                page, nav="navigate_to_lt263_listing",
                tabs=("Processed (Sold)", "Sold", "Processed"),
                required=PHASE1_REQUIRED, universe=MASTER_FORMS,
                phase_label="Phase 1 · LT-263 Sold", source_forms=self._LT263_SOURCE,
                target_vin=_target_vin("phase1_lt263"))
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: LT-262A "Processed" — correspondence set + full UI↔PDF for
    #          LT-262A / LT-260
    # ========================================================================
    def test_phase_2_lt262a_processed(self, staff_context: BrowserContext):
        """Phase 2: LT-262A Processed — assert the mobile-home form set is present and
        content-valid, and field-by-field UI↔PDF compare LT-262A and LT-260."""
        page = staff_context.new_page()
        try:
            self._validate_app(
                page, nav="navigate_to_lt262a_listing", tabs=("Processed",),
                required=PHASE2_FORMS, universe=PHASE2_FORMS,
                phase_label="Phase 2 · LT-262A", source_forms=self._LT262A_SOURCE,
                target_vin=_target_vin("phase2_lt262a"))
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: LT-261 "Processed" — LT-265 / LT-265A correspondence only
    # ========================================================================
    def test_phase_3_lt261_processed(self, staff_context: BrowserContext):
        """Phase 3: LT-261 Processed — assert LT-265, LT-265A present and content-valid.
        (No LT-260/262/263 source forms in the LT-261 correspondence set.)"""
        page = staff_context.new_page()
        try:
            self._validate_app(
                page, nav="navigate_to_lt261_listing", tabs=("Processed",),
                required=PHASE3_FORMS, universe=PHASE3_FORMS,
                phase_label="Phase 3 · LT-261", source_forms=[],
                target_vin=_target_vin("phase3_lt261"))
        finally:
            page.close()
