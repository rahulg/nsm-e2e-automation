"""
E2E-058: NCOA Report
Staff Portal — System Generated Reports → NCOA Report (National Change of Address).

Flow:
  1. [Staff Portal] Log in via saved auth session, open the dashboard
  2. Navigate to Reports → click 'NCOA Report' (grid auto-loads; it is slow, so poll for rows)
  3. Verify the column headers: File Number, VIN, Form Type, PDF Name, Recipient,
     Recipient Address, Updated Name, Updated Address, Letter Date, Mail Date, Print Date,
     NCOA Code, NCOA Description, Unique Identifier — and >=1 data row
  4. Click 'Show Filters' → for each text column, type a value drawn from the live data
     into that column's filter and assert the grid filters down to matching rows only
  5. Hover 'Download Options' → click PDF span → verify a .pdf file downloads
  6. Hover 'Download Options' → click XLSX span → verify a .xlsx file downloads

The NCOA Report is permission-gated / not deployed for every account+environment; when the
report link is absent the test skips rather than hard-failing.

Downloaded files are saved under C:/automation/artifacts/e2e_058_ncoa_report/.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect, TimeoutError as PWTimeoutError

from src.config.env import ENV
from src.pages.staff_portal.dashboard_page import StaffDashboardPage


SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

DOWNLOADS_DIR = Path(r"C:/automation/artifacts/e2e_058_ncoa_report")

# Expected column headers, in order.
EXPECTED_COLUMNS = [
    "File Number",
    "VIN",
    "Form Type",
    "PDF Name",
    "Recipient",
    "Recipient Address",
    "Updated Name",
    "Updated Address",
    "Letter Date",
    "Mail Date",
    "Print Date",
    "NCOA Code",
    "NCOA Description",
    "Unique Identifier",
]

# Text-input column filters — (column index, filter input name, human label).
# Letter/Mail/Print Date (cols 8-10) use Start/End date pickers; those controls are
# checked for presence separately (see the date-filter assertion in the test).
TEXT_FILTERS = [
    (0, "file_number", "File Number"),
    (1, "vin", "VIN"),
    (2, "form_type", "Form Type"),
    (3, "pdf_name", "PDF Name"),
    (4, "recipient", "Recipient"),
    (5, "recipient_address", "Recipient Address"),
    (6, "updated_name", "Updated Name"),
    (7, "updated_address", "Updated Address"),
    (11, "reason_code", "NCOA Code"),
    (12, "reason", "NCOA Description"),
    (13, "uniqueidentifier", "Unique Identifier"),
]


def _normalize(s) -> str:
    """Uppercase and strip everything but letters/digits so spacing/punctuation can't
    cause a false filter mismatch."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def snapshot_table(page):
    """Return the grid as a 2D list of cell texts via a single atomic DOM read.

    Reading cell-by-cell with Playwright locators races the grid's async re-render: a row
    can detach mid-iteration and text_content() then blocks on the 30s auto-wait. One
    synchronous evaluate() captures a consistent snapshot with no auto-waiting."""
    return page.evaluate(
        """() => {
            const t = document.querySelector('table');
            if (!t) return [];
            const rows = Array.from(t.querySelectorAll('tr')).filter(r => r.querySelector('td'));
            return rows.map(r =>
                Array.from(r.querySelectorAll('td')).map(td => (td.textContent || '').trim())
            );
        }"""
    )


def column_values(page, idx):
    """Return the text of column `idx` across every data row (including blank spacer cells)."""
    return [row[idx] for row in snapshot_table(page) if idx < len(row)]


def nonempty_values(page, idx):
    """Non-empty values of column `idx` (a record may span a primary + blank spacer row)."""
    return [v for v in column_values(page, idx) if v.strip()]


def wait_for_column(page, idx, predicate, tries=15, delay=400):
    """Poll column `idx`'s non-empty values until `predicate(values)` holds, then return them.

    The filter grid re-queries asynchronously (debounced), so mere read-stability is not
    enough — a read taken before the query fires looks 'stable' at the pre-change state.
    Waiting on an explicit condition (row count reached, all rows match, etc.) avoids that."""
    last = nonempty_values(page, idx)
    for _ in range(tries):
        if predicate(last):
            return last
        page.wait_for_timeout(delay)
        last = nonempty_values(page, idx)
    return last


def open_ncoa_report(page):
    """Open Reports → NCOA Report and wait for the (slow) auto-loading grid to populate.

    The NCOA Report is permission-gated / not deployed for every account+environment; skip
    rather than hard-fail when its link is absent."""
    StaffDashboardPage(page).navigate_to_reports()
    ncoa_link = page.locator('//span[contains(text(),"NCOA Report")]').first
    try:
        ncoa_link.wait_for(state="visible", timeout=15_000)
    except PWTimeoutError:
        pytest.skip("NCOA Report is not available for this account/environment")
    ncoa_link.click()
    page.wait_for_load_state("networkidle")
    # The grid auto-loads but is slow — poll up to ~25s for the first rows.
    for _ in range(25):
        if snapshot_table(page):
            break
        page.wait_for_timeout(1000)


def _first_meaningful(values):
    """First value that carries at least one letter/digit (skips blanks and '-' placeholders)."""
    return next((v for v in values if re.search(r"[A-Za-z0-9]", v or "")), "")


def _filter_token(value: str) -> str:
    """Filter on the first whitespace token of a live cell value — a single word/id that is
    guaranteed present in that row (keeps address/name filters robust)."""
    value = (value or "").strip()
    return value.split()[0] if value else value


def apply_filter(page, input_name: str, col_idx: int, token: str, norm_token: str):
    """Type `token` into the named column filter, apply it, and wait until the grid reflects
    the filter (every non-empty cell in the column matches the token). Returns the rows."""
    f = page.locator(f'input[name="{input_name}"]').first
    f.wait_for(state="visible", timeout=10_000)
    f.fill("")
    f.fill(token)
    f.press("Enter")
    page.wait_for_load_state("networkidle")
    return wait_for_column(
        page, col_idx,
        lambda vals: bool(vals) and all(norm_token in _normalize(v) for v in vals),
    )


def clear_filter(page, input_name: str, ref_idx: int, baseline: int):
    """Clear the named column filter and wait until the grid resets to the baseline count."""
    f = page.locator(f'input[name="{input_name}"]').first
    f.fill("")
    f.press("Enter")
    page.wait_for_load_state("networkidle")
    wait_for_column(page, ref_idx, lambda vals: len(vals) == baseline)


def download_report(page, download_options, label: str, ext: str, attempts: int = 3,
                    dl_timeout: int = 30_000):
    """Hover 'Download Options' and click the given format span, retrying on popover flakiness.

    The CDK overlay popover can re-render mid-click (closes/repositions on hover loss),
    which surfaces as 'element is not stable' or 'element was detached from the DOM'.
    Re-hovering and re-locating the span fresh on each attempt works around that. `dl_timeout`
    is generous because the export is generated server-side and can lag the click.
    """
    last_error = None
    for attempt in range(attempts):
        try:
            download_options.hover()
            overlay = page.locator(".cdk-overlay-pane").first
            overlay.wait_for(state="visible", timeout=10_000)

            span = overlay.locator(
                f'span.popover-span:has-text("{label}"), span:has-text("{label}")'
            ).first
            expect(span).to_be_visible(timeout=10_000)
            span.hover()
            page.wait_for_timeout(300)

            with page.expect_download(timeout=dl_timeout) as download_info:
                span.click(timeout=10_000)
            download = download_info.value
            name = download.suggested_filename
            assert name, f"{label} file should have a filename"
            assert name.lower().endswith(ext), f"Expected {ext} extension, got: {name}"
            return download
        except Exception as e:
            last_error = e
            page.keyboard.press("Escape")
            page.mouse.move(0, 0)
            page.wait_for_timeout(500)
    raise last_error


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.report
class TestE2E058NCOAReport:
    """E2E-058: NCOA Report — verify columns, per-column filtering, PDF & XLSX download."""

    def test_phase_1_ncoa_report(self, staff_context: BrowserContext):
        """Phase 1: Reports → NCOA Report → verify columns → filter each column → download PDF + XLSX."""
        page = staff_context.new_page()
        try:
            # (1) + (2) Open the NCOA Report.
            go_to_staff_dashboard(page)
            open_ncoa_report(page)

            # (3) Verify every expected column header is present.
            for col in EXPECTED_COLUMNS:
                expect(
                    page.locator(f'table thead th:has-text("{col}")').first
                ).to_be_visible(timeout=10_000)

            # Verify at least one data row rendered.
            assert snapshot_table(page), "NCOA Report has no data rows"

            # (4) Show Filters, then validate each text-column filter with live data.
            show_filters = page.locator('//span[contains(text(),"Show Filters")]').first
            show_filters.wait_for(state="visible", timeout=10_000)
            show_filters.click()
            page.locator('input[name="start"]').first.wait_for(state="visible", timeout=10_000)

            # Confirm the three date-range filter controls exist (Letter / Mail / Print Date).
            assert page.locator('input[name="start"]').count() >= 3, (
                "Expected Start-Date filter inputs for the three date columns"
            )
            assert page.locator('input[name="end"]').count() >= 3, (
                "Expected End-Date filter inputs for the three date columns"
            )

            baseline = len(nonempty_values(page, 0))
            assert baseline >= 1, "NCOA Report grid has no rows once filters are shown"

            for col_idx, input_name, label in TEXT_FILTERS:
                # Pick a meaningful value in this column (skip blanks / '-' placeholders).
                source = _first_meaningful(nonempty_values(page, col_idx))
                if not source:
                    print(f"  [E2E-058] filter '{label}': no filterable value in data — skipped")
                    continue
                token = _filter_token(source)
                norm_token = _normalize(token)
                if not norm_token:
                    print(f"  [E2E-058] filter '{label}': token {token!r} not filterable — skipped")
                    continue

                filtered = apply_filter(page, input_name, col_idx, token, norm_token)

                assert filtered, (
                    f"Filtering '{label}' by {token!r} returned no rows — filter appears broken"
                )
                mismatched = [v for v in filtered if norm_token not in _normalize(v)]
                assert not mismatched, (
                    f"Filter '{label}'={token!r} returned rows not matching the filter: {mismatched}"
                )
                print(f"  [E2E-058] filter '{label}' by {token!r} -> {len(filtered)} matching row(s)")

                clear_filter(page, input_name, 0, baseline)
                assert len(nonempty_values(page, 0)) == baseline, (
                    f"Grid did not reset after clearing the '{label}' filter"
                )

            # (5) + (6) Download PDF and XLSX via the Download Options popover.
            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
            download_options = page.locator('button:has-text("Download Options")').first
            download_options.wait_for(state="visible", timeout=10_000)

            pdf_download = download_report(page, download_options, "PDF", ".pdf")
            pdf_download.save_as(str(DOWNLOADS_DIR / pdf_download.suggested_filename))

            xlsx_download = download_report(page, download_options, "XLSX", ".xlsx")
            xlsx_download.save_as(str(DOWNLOADS_DIR / xlsx_download.suggested_filename))
        finally:
            page.close()
