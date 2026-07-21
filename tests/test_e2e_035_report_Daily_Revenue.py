"""
E2E-035: Daily Revenue Report
Staff Portal — System Generated Reports → Daily Revenue Report.

Flow:
  1. [Staff Portal] Navigate to Reports → click 'Daily Revenue Report'
  2. Select today's date in Report Date picker → Generate Report
  3. Verify Report Results heading + FEE CODE / AMOUNT columns
  4. Verify FEE CODE has '00007NOIC' and AMOUNT starts with '$'
  5. Hover 'Download Options' → click PDF span → verify download → verify PDF content matches the UI table
  6. Hover 'Download Options' → click XLSX span → verify download → verify XLSX content matches the UI table

Content verification compares the on-screen Report Results table (FEE CODE + AMOUNT per row)
against the downloaded PDF/XLSX. The XLSX check is structural (parsed via openpyxl); the
PDF check is a normalized-text containment check, since PDF text extraction can reorder or
join table cells.

Downloaded files are saved under C:/automation/artifacts/e2e_035_daily_revenue_report/.
"""

import re
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.reports_page import ReportsPage

# PyPDF2 v3 exposes PdfReader; fall back to the maintained `pypdf` package name.
try:
    from PyPDF2 import PdfReader
except ImportError:  # pragma: no cover - environment fallback
    from pypdf import PdfReader


SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

TODAY_MMDDYYYY = datetime.now().strftime("%m/%d/%Y")

DOWNLOADS_DIR = Path(r"C:/automation/artifacts/e2e_035_daily_revenue_report")


def _normalize(s) -> str:
    """Uppercase and strip everything but letters/digits/dots, so spacing, currency
    symbols, and thousands separators can't cause a false content mismatch."""
    return re.sub(r"[^A-Z0-9.]", "", str(s or "").upper())


def _n_money(s) -> str:
    """Canonicalize a money value to a fixed 2-decimal string (e.g. '$1,234.5' -> '1234.50')
    so the UI's display formatting and the exported cell's formatting compare equal."""
    digits = re.sub(r"[^0-9.]", "", str(s or ""))
    try:
        return f"{float(digits):.2f}"
    except ValueError:
        return digits


def scrape_report_table(page):
    """Scrape the 'Report Results' table into (headers, rows); rows are lists of cell text."""
    table = page.locator("table").first
    header_cells = table.locator("thead th, thead td, tr.mat-header-row th, tr.mat-header-row td")
    if header_cells.count() == 0:
        header_cells = table.locator("tr").first.locator("th, td")
    headers = [(h.text_content() or "").strip() for h in header_cells.all()]

    rows = []
    for row in table.locator("tbody tr, tr.mat-row").all():
        cells = [(c.text_content() or "").strip() for c in row.locator("td").all()]
        if any(cells):
            rows.append(cells)
    return headers, rows


def _col_index(headers, name):
    name_l = name.lower()
    exact = [i for i, h in enumerate(headers) if h.strip().lower() == name_l]
    if exact:
        return exact[0]
    partial = [i for i, h in enumerate(headers) if name_l in h.lower()]
    return partial[0] if partial else None


def extract_fee_amounts(headers, rows) -> dict:
    """Return {fee_code: amount_text} for every report row, keyed off the FEE CODE/AMOUNT columns."""
    f_idx = _col_index(headers, "FEE CODE")
    a_idx = _col_index(headers, "AMOUNT")
    assert f_idx is not None and a_idx is not None, (
        f"Could not locate FEE CODE/AMOUNT columns in headers: {headers}"
    )
    amounts = {}
    for row in rows:
        if f_idx < len(row) and a_idx < len(row):
            fee_code = row[f_idx].strip()
            if fee_code:
                amounts[fee_code] = row[a_idx].strip()
    return amounts


def compare_xlsx_content(path: Path, ui_fee_amounts: dict) -> None:
    """Assert every fee code/amount pair from the UI Report Results table appears in the
    downloaded XLSX — fee code matched as text, amount matched as a normalized money value
    (numeric cell formatting can differ from the UI's '$1,234.00' display)."""
    wb = openpyxl.load_workbook(str(path), data_only=True)
    cells = [
        c for ws in wb.worksheets
        for row in ws.iter_rows(values_only=True)
        for c in row if c not in (None, "")
    ]
    text_blob = _normalize(" ".join(str(c) for c in cells))
    money_values = {_n_money(c) for c in cells if re.search(r"\d", str(c))}

    missing = []
    for fee_code, amount in ui_fee_amounts.items():
        if _normalize(fee_code) not in text_blob:
            missing.append(f"fee code {fee_code!r} not found in XLSX")
        elif re.search(r"\d", amount or "") and _n_money(amount) not in money_values:
            missing.append(f"amount {amount!r} for fee code {fee_code!r} not found in XLSX")
    assert not missing, f"XLSX content mismatch vs UI report table: {missing}"


def compare_pdf_content(path: Path, ui_fee_amounts: dict) -> None:
    """Assert every fee code/amount pair from the UI Report Results table appears in the
    downloaded PDF's extracted text. Looser than the XLSX check — PDF text extraction can
    reorder or join table cells, so this only checks presence, not row alignment."""
    reader = PdfReader(str(path))
    text = ""
    for pg in reader.pages:
        try:
            text += pg.extract_text() or ""
        except Exception:
            continue
    assert text.strip(), "PDF has no extractable text"
    norm_text = _normalize(text)

    missing = []
    for fee_code, amount in ui_fee_amounts.items():
        if _normalize(fee_code) not in norm_text:
            missing.append(f"fee code {fee_code!r} not found in PDF text")
        if not re.search(r"\d", amount or ""):
            continue  # placeholder row (e.g. '-' for no activity) — nothing to match
        money = _n_money(amount)
        # PDF extraction can drop the decimal point (e.g. '1234.50' -> '123450');
        # accept either form.
        if money and money not in norm_text and money.replace(".", "") not in norm_text:
            missing.append(f"amount {amount!r} for fee code {fee_code!r} not found in PDF text")
    assert not missing, f"PDF content mismatch vs UI report table: {missing}"


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def download_report(page, download_options, label: str, ext: str, attempts: int = 3):
    """Hover 'Download Options' and click the given format span, retrying on popover flakiness.

    The CDK overlay popover can re-render mid-click (closes/repositions on hover loss),
    which surfaces as 'element is not stable' or 'element was detached from the DOM'.
    Re-hovering and re-locating the span fresh on each attempt works around that.
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

            with page.expect_download(timeout=15_000) as download_info:
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
@pytest.mark.fixed
@pytest.mark.smoke
class TestE2E035DailyRevenueReport:
    """E2E-035: Daily Revenue Report — generate, verify results, download PDF and XLSX"""

    def test_phase_1_daily_revenue_report(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Reports → Daily Revenue Report → generate → verify → download PDF + XLSX"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            reports = ReportsPage(page)

            # Navigate to Reports section
            staff_dashboard.navigate_to_reports()

            # Click 'Daily Revenue Report' under System Generated Reports
            reports.click_daily_revenue_report()

            # Verify page heading
            expect(
                page.get_by_text(re.compile(r"Daily Revenue Report", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Fill Report Date with today's date in MM/DD/YYYY format
            date_input = page.locator(
                'input[matInput][placeholder*="MM/DD/YYYY"], '
                'input[placeholder*="MM/DD/YYYY"], '
                'input[aria-label*="Report Date" i], '
                'input[aria-label*="Date" i]'
            ).first
            date_input.wait_for(state="visible", timeout=10_000)
            date_input.click()
            date_input.fill(TODAY_MMDDYYYY)
            page.keyboard.press("Tab")
            page.wait_for_timeout(500)

            # Click the Generate Report button (class mr1 distinguishes it from Generate LT-215)
            generate_btn = page.locator(
                'button.mr1:has-text("Generate Report"), '
                'button[class*="mr1"]:has-text("Generate")'
            ).first
            try:
                generate_btn.wait_for(state="visible", timeout=5_000)
                generate_btn.click()
            except Exception:
                page.get_by_role("button", name="Generate Report").click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)

            # Verify "Report Results" heading
            expect(
                page.get_by_text(re.compile(r"Report Results", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Verify FEE CODE and AMOUNT column headers
            expect(
                page.locator(
                    'th:has-text("FEE CODE"), td:has-text("FEE CODE"), '
                    '[class*="header"]:has-text("FEE CODE")'
                ).first
            ).to_be_visible(timeout=10_000)
            expect(
                page.locator(
                    'th:has-text("AMOUNT"), td:has-text("AMOUNT"), '
                    '[class*="header"]:has-text("AMOUNT")'
                ).first
            ).to_be_visible(timeout=10_000)

            # Verify FEE CODE value '00007NOIC' is present in results
            expect(
                page.get_by_text(re.compile(r"00007NOIC", re.I)).first
            ).to_be_visible(timeout=10_000)

            # Verify AMOUNT column has at least one value starting with '$'
            amount_cell = page.locator('td:has-text("$"), [class*="amount" i]:has-text("$")').first
            expect(amount_cell).to_be_visible(timeout=10_000)

            # Scrape the on-screen Report Results table so the downloaded files can be
            # checked against it, not just against a fixed extension/filename.
            ui_headers, ui_rows = scrape_report_table(page)
            ui_fee_amounts = extract_fee_amounts(ui_headers, ui_rows)
            assert ui_fee_amounts, f"No fee code/amount rows scraped from UI table: {ui_headers}"
            assert any("00007NOIC".lower() in fc.lower() for fc in ui_fee_amounts), (
                f"'00007NOIC' fee code not found in scraped UI rows: {list(ui_fee_amounts)}"
            )
            print(f"\n  [E2E-035] UI fee code/amount rows: {ui_fee_amounts}")

            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

            # Download PDF — hover 'Download Options' to open popover, then click PDF span
            download_options = page.locator('button:has-text("Download Options")').first
            download_options.wait_for(state="visible", timeout=10_000)
            pdf_download = download_report(page, download_options, "PDF", ".pdf")
            pdf_path = DOWNLOADS_DIR / pdf_download.suggested_filename
            pdf_download.save_as(str(pdf_path))
            compare_pdf_content(pdf_path, ui_fee_amounts)
            page.wait_for_timeout(1000)

            # Download XLSX — hover 'Download Options' to open popover, then click XLSX span
            xlsx_download = download_report(page, download_options, "XLSX", ".xlsx")
            xlsx_path = DOWNLOADS_DIR / xlsx_download.suggested_filename
            xlsx_download.save_as(str(xlsx_path))
            compare_xlsx_content(xlsx_path, ui_fee_amounts)
        finally:
            page.close()
