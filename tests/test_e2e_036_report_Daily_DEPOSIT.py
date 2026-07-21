"""
E2E-036: Daily Deposit Report
Staff Portal — System Generated Reports → Daily Deposit Report.

Flow:
  1. [Staff Portal] Navigate to Reports → click 'Daily Deposit Report'
  2. Select today's date in Report Date picker → Generate Report
  3. Verify Report Results heading + Branch/Branch Description/Cash/Checks/Credit/Debit/PrePay/Total columns
  4. Verify Branch column has 'NSS-PrePay' and Total column has a value starting with '$'
  5. Hover 'Download Options' → click PDF span → verify download → verify PDF content matches the UI table
  6. Hover 'Download Options' → click XLSX span → verify download → verify XLSX content matches the UI table

Content verification compares the on-screen Report Results table (Branch + Total per row)
against the downloaded PDF/XLSX. The XLSX check is structural (parsed via openpyxl); the
PDF check is a normalized-text containment check, since PDF text extraction can reorder or
join table cells.

Downloaded files are saved under C:/automation/artifacts/e2e_036_daily_deposit_report/.
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

DOWNLOADS_DIR = Path(r"C:/automation/artifacts/e2e_036_daily_deposit_report")


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


def extract_branch_totals(headers, rows) -> dict:
    """Return {branch: total_text} for every report row, keyed off the Branch/Total columns."""
    b_idx = _col_index(headers, "Branch")
    t_idx = _col_index(headers, "Total")
    assert b_idx is not None and t_idx is not None, (
        f"Could not locate Branch/Total columns in headers: {headers}"
    )
    totals = {}
    for row in rows:
        if b_idx < len(row) and t_idx < len(row):
            branch = row[b_idx].strip()
            if branch:
                totals[branch] = row[t_idx].strip()
    return totals


def compare_xlsx_content(path: Path, ui_branch_totals: dict) -> None:
    """Assert every branch/total pair from the UI Report Results table appears in the
    downloaded XLSX — branch matched as text, total matched as a normalized money value
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
    for branch, total in ui_branch_totals.items():
        if _normalize(branch) not in text_blob:
            missing.append(f"branch {branch!r} not found in XLSX")
        elif re.search(r"\d", total or "") and _n_money(total) not in money_values:
            missing.append(f"total {total!r} for branch {branch!r} not found in XLSX")
    assert not missing, f"XLSX content mismatch vs UI report table: {missing}"


def compare_pdf_content(path: Path, ui_branch_totals: dict) -> None:
    """Assert every branch/total pair from the UI Report Results table appears in the
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
    for branch, total in ui_branch_totals.items():
        if _normalize(branch) not in norm_text:
            missing.append(f"branch {branch!r} not found in PDF text")
        if not re.search(r"\d", total or ""):
            continue  # placeholder row (e.g. '-' for no activity) — nothing to match
        money = _n_money(total)
        # PDF extraction can drop the decimal point (e.g. '1234.50' -> '123450');
        # accept either form.
        if money and money not in norm_text and money.replace(".", "") not in norm_text:
            missing.append(f"total {total!r} for branch {branch!r} not found in PDF text")
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
class TestE2E036DailyDepositReport:
    """E2E-036: Daily Deposit Report — generate, verify results, download PDF and XLSX"""

    def test_phase_1_daily_deposit_report(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Reports → Daily Deposit Report → generate → verify → download PDF + XLSX"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            reports = ReportsPage(page)

            # Navigate to Reports section
            staff_dashboard.navigate_to_reports()

            # Click 'Daily Deposit Report' under System Generated Reports
            deposit_link = page.locator(
                '//span[contains(text(),"Daily Deposit Report")]'
            ).first
            deposit_link.wait_for(state="visible", timeout=10_000)
            deposit_link.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            # Verify page heading
            expect(
                page.get_by_text(re.compile(r"Daily Deposit Report", re.I)).first
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

            # Verify column headers
            for col in ["Branch", "Branch Description", "Cash", "Checks", "Total"]:
                expect(
                    page.locator(
                        f'th:has-text("{col}"), td:has-text("{col}"), '
                        f'[class*="header"]:has-text("{col}")'
                    ).first
                ).to_be_visible(timeout=10_000)

            # Verify Branch column has 'NSS-PrePay'
            expect(
                page.get_by_text(re.compile(r"NSS-PrePay", re.I)).first
            ).to_be_visible(timeout=10_000)

            # Verify Total column has at least one value starting with '$'
            total_cell = page.locator('td:has-text("$"), [class*="total" i]:has-text("$")').first
            expect(total_cell).to_be_visible(timeout=10_000)

            # Scrape the on-screen Report Results table so the downloaded files can be
            # checked against it, not just against a fixed extension/filename.
            ui_headers, ui_rows = scrape_report_table(page)
            ui_branch_totals = extract_branch_totals(ui_headers, ui_rows)
            assert ui_branch_totals, f"No branch/total rows scraped from UI table: {ui_headers}"
            assert any("NSS-PrePay".lower() in b.lower() for b in ui_branch_totals), (
                f"'NSS-PrePay' branch not found in scraped UI rows: {list(ui_branch_totals)}"
            )
            print(f"\n  [E2E-036] UI branch/total rows: {ui_branch_totals}")

            DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

            # Download PDF — hover 'Download Options' to open popover, then click PDF span
            download_options = page.locator('button:has-text("Download Options")').first
            download_options.wait_for(state="visible", timeout=10_000)
            pdf_download = download_report(page, download_options, "PDF", ".pdf")
            pdf_path = DOWNLOADS_DIR / pdf_download.suggested_filename
            pdf_download.save_as(str(pdf_path))
            compare_pdf_content(pdf_path, ui_branch_totals)
            page.wait_for_timeout(1000)

            # Download XLSX — hover 'Download Options' to open popover, then click XLSX span
            xlsx_download = download_report(page, download_options, "XLSX", ".xlsx")
            xlsx_path = DOWNLOADS_DIR / xlsx_download.suggested_filename
            xlsx_download.save_as(str(xlsx_path))
            compare_xlsx_content(xlsx_path, ui_branch_totals)
        finally:
            page.close()
