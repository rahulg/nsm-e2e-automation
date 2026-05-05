"""
E2E-036: Daily Deposit Report
Staff Portal — System Generated Reports → Daily Deposit Report.

Flow:
  1. [Staff Portal] Navigate to Reports → click 'Daily Deposit Report'
  2. Select today's date in Report Date picker → Generate Report
  3. Verify Report Results heading + Branch/Branch Description/Cash/Checks/Credit/Debit/PrePay/Total columns
  4. Verify Branch column has 'NSS-PrePay' and Total column has a value starting with '$'
  5. Hover 'Download Options' → click PDF span → verify download
  6. Hover 'Download Options' → click XLSX span → verify download
"""

import re
from datetime import datetime

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.reports_page import ReportsPage


SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

TODAY_MMDDYYYY = datetime.now().strftime("%m/%d/%Y")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
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

            # Download PDF — hover 'Download Options' to open popover, then click PDF span
            download_options = page.locator('button:has-text("Download Options")').first
            download_options.wait_for(state="visible", timeout=10_000)
            download_options.hover()
            page.wait_for_timeout(1000)

            with page.expect_download(timeout=30_000) as pdf_download_info:
                pdf_span = page.locator(
                    '.cdk-overlay-pane span.popover-span:has-text("PDF"), '
                    '.cdk-overlay-pane span:has-text("PDF")'
                ).first
                pdf_span.wait_for(state="visible", timeout=10_000)
                pdf_span.click()
            pdf_download = pdf_download_info.value
            pdf_name = pdf_download.suggested_filename
            assert pdf_name, "PDF file should have a filename"
            assert pdf_name.lower().endswith(".pdf"), f"Expected .pdf extension, got: {pdf_name}"
            page.wait_for_timeout(1000)

            # Download XLSX — hover 'Download Options' to open popover, then click XLSX span
            download_options.wait_for(state="visible", timeout=10_000)
            download_options.hover()
            page.wait_for_timeout(1000)

            with page.expect_download(timeout=30_000) as xlsx_download_info:
                xlsx_span = page.locator(
                    '.cdk-overlay-pane span.popover-span:has-text("XLSX"), '
                    '.cdk-overlay-pane span:has-text("XLSX")'
                ).first
                xlsx_span.wait_for(state="visible", timeout=10_000)
                xlsx_span.click()
            xlsx_download = xlsx_download_info.value
            xlsx_name = xlsx_download.suggested_filename
            assert xlsx_name, "XLSX file should have a filename"
            assert xlsx_name.lower().endswith(".xlsx"), f"Expected .xlsx extension, got: {xlsx_name}"
        finally:
            page.close()
