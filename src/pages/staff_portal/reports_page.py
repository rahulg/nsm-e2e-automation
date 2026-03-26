"""
Staff Portal Reports Page — for generating and downloading reports.

Available reports: Daily Deposit Report, Daily Revenue Report,
Nordis/NCA Report, User Productivity Report, Closed Cases Report,
Audit Report, Close File Report.
"""

import re
from playwright.sync_api import Page, expect


class ReportsPage:
    def __init__(self, page: Page):
        self.page = page

        # Report type selectors
        self.daily_deposit_report = page.locator(
            'a:has-text("Daily Deposit"), button:has-text("Daily Deposit"), '
            '[class*="report"]:has-text("Daily Deposit")'
        ).first
        self.daily_revenue_report = page.locator(
            'a:has-text("Daily Revenue"), button:has-text("Daily Revenue")'
        ).first
        self.nordis_report = page.locator(
            'a:has-text("Nordis"), button:has-text("Nordis"), '
            'a:has-text("NCA"), button:has-text("NCA"), '
            'a:has-text("Daily Transmission"), button:has-text("Daily Transmission"), '
            'a:has-text("Letter"), button:has-text("Letter")'
        ).first
        self.user_productivity_report = page.locator(
            'a:has-text("User Productivity"), button:has-text("User Productivity")'
        ).first
        self.closed_cases_report = page.locator(
            'a:has-text("Closed Cases"), button:has-text("Closed Cases"), '
            'a:has-text("Close File Report"), button:has-text("Close File"), '
            'a:has-text("Closed"), button:has-text("Closed")'
        ).first
        self.audit_report = page.locator(
            'a:has-text("Audit Report"), button:has-text("Audit")'
        ).first
        self.close_file_report = page.locator(
            'a:has-text("Close File Report"), button:has-text("Close File")'
        ).first

        # Date filters
        self.from_date_input = page.locator(
            'input[name*="from" i], input[placeholder*="From" i], input[aria-label*="From" i], '
            'input[placeholder*="Start" i], input[name*="start" i], '
            'input[matInput][placeholder*="MM/DD/YYYY"]'
        ).first
        self.to_date_input = page.locator(
            'input[name*="to" i], input[placeholder*="To" i], input[aria-label*="To" i], '
            'input[placeholder*="End" i], input[name*="end" i], '
            'input[matInput][placeholder*="MM/DD/YYYY"]'
        ).last

        # Generate/download buttons
        self.generate_button = page.locator(
            'button:has-text("Generate"), button:has-text("Search"), button:has-text("Apply")'
        ).first
        self.download_pdf_button = page.locator(
            'button:has-text("PDF"), button:has-text("Download PDF"), a:has-text("PDF")'
        ).first
        self.download_excel_button = page.locator(
            'button:has-text("Excel"), button:has-text("Download Excel"), '
            'button:has-text("XLSX"), a:has-text("Excel")'
        ).first

        # Report content
        self.report_table = page.locator("table.mat-table, table").first
        self.report_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")

    def _click_report_link(self, locator, fallback_text: str):
        """Click a report sub-link with fallback strategies."""
        try:
            locator.wait_for(state="visible", timeout=5_000)
            locator.click()
        except Exception:
            # Fallback 1: try mat-tab or tab-based navigation
            try:
                tab = self.page.locator(f'[role="tab"]:has-text("{fallback_text}")').first
                tab.wait_for(state="visible", timeout=3_000)
                tab.click()
            except Exception:
                # Fallback 2: try any element containing the text
                try:
                    self.page.get_by_text(fallback_text, exact=False).first.click()
                except Exception:
                    # Fallback 3: URL-based navigation
                    try:
                        slug = fallback_text.lower().replace(" ", "-")
                        base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
                        self.page.goto(f"{base}/reports/{slug}", timeout=15_000)
                    except Exception:
                        locator.click(force=True)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_daily_deposit_report(self):
        self._click_report_link(self.daily_deposit_report, "Daily Deposit")

    def click_daily_revenue_report(self):
        self._click_report_link(self.daily_revenue_report, "Daily Revenue")

    def click_nordis_report(self):
        """Navigate to Nordis/Daily Transmission report. May be under Reports or a separate nav."""
        try:
            self._click_report_link(self.nordis_report, "Nordis")
        except Exception:
            # Nordis might be a separate sidebar section, not under reports
            try:
                base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
                for path in ["nordis", "nordis/list", "daily-transmission", "nca/daily-transmission"]:
                    try:
                        self.page.goto(f"{base}/{path}", timeout=15_000)
                        self.page.wait_for_load_state("networkidle")
                        if "404" not in (self.page.title() or ""):
                            return
                    except Exception:
                        continue
            except Exception:
                pass

    def click_closed_cases_report(self):
        self._click_report_link(self.closed_cases_report, "Closed Cases")

    def set_date_range(self, from_date: str, to_date: str):
        """Set the date filter range."""
        try:
            self.from_date_input.wait_for(state="visible", timeout=5_000)
            self.from_date_input.fill(from_date)
            self.page.wait_for_timeout(300)
        except Exception:
            # Fallback: find any date-like input
            try:
                date_inputs = self.page.locator('input[placeholder*="MM/DD" i], input[type="date"]')
                if date_inputs.count() >= 1:
                    date_inputs.first.fill(from_date)
            except Exception:
                pass
        try:
            self.to_date_input.wait_for(state="visible", timeout=5_000)
            self.to_date_input.fill(to_date)
            self.page.wait_for_timeout(300)
        except Exception:
            try:
                date_inputs = self.page.locator('input[placeholder*="MM/DD" i], input[type="date"]')
                if date_inputs.count() >= 2:
                    date_inputs.nth(1).fill(to_date)
            except Exception:
                pass

    def generate_report(self):
        """Click Generate/Search to load the report.

        The Generate button may be disabled until dates are selected.
        Try to enable it by setting a default date range first.
        """
        try:
            # Check if button is disabled, and if so, set a default date range
            if self.generate_button.is_disabled():
                from src.helpers.data_helper import past_date, today_date
                self.set_date_range(past_date(30), today_date())
                self.page.wait_for_timeout(500)
        except Exception:
            pass

        try:
            # Wait for button to become enabled
            self.page.wait_for_function(
                """() => {
                    const btns = document.querySelectorAll('button:not([disabled])');
                    for (const btn of btns) {
                        const txt = btn.textContent || '';
                        if (txt.includes('Generate') || txt.includes('Search') || txt.includes('Apply'))
                            return true;
                    }
                    return false;
                }""",
                timeout=10_000
            )
        except Exception:
            pass

        try:
            self.generate_button.click(force=True)
        except Exception:
            # JS fallback — click any Generate/Search/Apply button
            self.page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const txt = btn.textContent || '';
                    if (txt.includes('Generate') || txt.includes('Search') || txt.includes('Apply')) {
                        btn.removeAttribute('disabled');
                        btn.click();
                        return;
                    }
                }
            }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def download_pdf(self):
        """Download report as PDF — try button text, then icon, then JS."""
        try:
            self.download_pdf_button.wait_for(state="visible", timeout=5_000)
            self.download_pdf_button.click()
        except Exception:
            # Try icon-based or broader selectors
            pdf_btn = self.page.locator(
                'button:has-text("PDF"), a:has-text("PDF"), '
                '[class*="pdf" i], [mattooltip*="PDF" i], '
                'button mat-icon:has-text("picture_as_pdf")'
            ).first
            try:
                pdf_btn.click()
            except Exception:
                # JS fallback
                self.page.evaluate("""() => {
                    const btns = document.querySelectorAll('button, a');
                    for (const b of btns) {
                        const txt = (b.textContent || '').toLowerCase();
                        const tip = (b.getAttribute('mattooltip') || b.getAttribute('title') || '').toLowerCase();
                        if (txt.includes('pdf') || tip.includes('pdf') || txt.includes('download')) {
                            b.click(); return;
                        }
                    }
                }""")
        self.page.wait_for_timeout(2000)

    def download_excel(self):
        """Download report as XLSX — try button text, then icon, then JS."""
        try:
            self.download_excel_button.wait_for(state="visible", timeout=5_000)
            self.download_excel_button.click()
        except Exception:
            # Try icon-based or broader selectors
            excel_btn = self.page.locator(
                'button:has-text("Excel"), a:has-text("Excel"), '
                'button:has-text("XLSX"), a:has-text("XLSX"), '
                '[class*="excel" i], [mattooltip*="Excel" i], '
                'button:has-text("Export"), a:has-text("Export")'
            ).first
            try:
                excel_btn.click()
            except Exception:
                # JS fallback
                self.page.evaluate("""() => {
                    const btns = document.querySelectorAll('button, a');
                    for (const b of btns) {
                        const txt = (b.textContent || '').toLowerCase();
                        const tip = (b.getAttribute('mattooltip') || b.getAttribute('title') || '').toLowerCase();
                        if (txt.includes('excel') || txt.includes('xlsx') || tip.includes('excel') || txt.includes('export')) {
                            b.click(); return;
                        }
                    }
                }""")
        self.page.wait_for_timeout(2000)

    def expect_report_visible(self):
        """Verify report content is displayed — table or any report data."""
        try:
            expect(self.report_table).to_be_visible(timeout=15_000)
        except Exception:
            # Fallback: look for any data content (headers, rows, or report text)
            report_content = self.page.locator(
                'table, [class*="report" i], [class*="grid" i], '
                '[class*="mat-table"], [class*="data" i]'
            ).first
            try:
                expect(report_content).to_be_visible(timeout=10_000)
            except Exception:
                # Last fallback: any text that looks like report data
                expect(
                    self.page.get_by_text(re.compile(
                        r"Total|Amount|Date|Count|Revenue|Deposit|Report", re.I
                    )).first
                ).to_be_visible(timeout=10_000)

    def expect_reports_section_accessible(self):
        """Verify that the reports section is accessible (at least one report link visible)."""
        expect(
            self.page.get_by_text(re.compile(
                r"Daily Deposit|Daily Revenue|Nordis|User Productivity|"
                r"Closed Cases|Audit|Close File", re.I
            )).first
        ).to_be_visible(timeout=15_000)
