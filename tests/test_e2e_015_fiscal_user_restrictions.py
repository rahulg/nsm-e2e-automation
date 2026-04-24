"""
E2E-015: Fiscal User Access Restriction Validation

Phases:
  1. [Staff Portal] Login as Fiscal User → lands on Reports page → sidebar has Reports only
  2. [Staff Portal] Verify System Generated Reports section → open Daily Deposit Report
                    → select today's date → Generate → verify table columns
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import today_date

SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_staff_portal(page):
    """Navigate to staff portal dashboard — fiscal user session redirects to Reports."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


@pytest.mark.e2e
@pytest.mark.multiuser
@pytest.mark.high
class TestE2E015FiscalUserRestrictions:
    """E2E-015: Fiscal User — only Reports accessible, all other areas restricted"""

    # ========================================================================
    # PHASE 1: Login → Reports landing page → sidebar restrictions
    # ========================================================================
    def test_phase_1_fiscal_user_reports_only_sidebar(self, fiscal_context: BrowserContext):
        """Phase 1: Fiscal user lands on Reports page, sidebar shows only Reports"""
        page = fiscal_context.new_page()
        try:
            go_to_staff_portal(page)

            # Fiscal user should be redirected directly to the Reports page
            expect(page).to_have_url(re.compile(r"reports", re.I), timeout=30_000)

            # ── Sidebar: Reports IS present ──
            reports_link = page.locator('a:has-text("Reports"), [role="menuitem"]:has-text("Reports")').first
            expect(reports_link).to_be_visible(timeout=10_000)

            # ── Sidebar: LT-260 is NOT present ──
            lt260_link = page.locator(
                'a[href*="LT-260"], a:has-text("LT-260"), [role="menuitem"]:has-text("LT-260")'
            ).first
            expect(lt260_link).not_to_be_visible(timeout=5_000)

            # ── Sidebar: User Management is NOT present ──
            user_mgmt_link = page.locator(
                'a[href*="user-management"], a:has-text("User Management"), '
                '[role="menuitem"]:has-text("User Management")'
            ).first
            expect(user_mgmt_link).not_to_be_visible(timeout=5_000)

        finally:
            page.close()

    # ========================================================================
    # PHASE 2: System Generated Reports → Daily Deposit → Generate → verify columns
    # ========================================================================
    def test_phase_2_daily_deposit_report_columns(self, fiscal_context: BrowserContext):
        """Phase 2: System Generated Reports visible → open Daily Deposit → generate → verify columns"""
        page = fiscal_context.new_page()
        try:
            go_to_staff_portal(page)
            expect(page).to_have_url(re.compile(r"reports", re.I), timeout=30_000)
            page.wait_for_load_state("networkidle")

            # ── Verify "System Generated Reports" section heading ──
            system_reports_heading = page.locator(
                ':has-text("System Generated Reports")'
            ).last
            expect(system_reports_heading).to_be_visible(timeout=10_000)

            # ── Verify Daily Revenue Report is present ──
            daily_revenue = page.locator(
                'a:has-text("Daily Revenue"), button:has-text("Daily Revenue"), '
                '[class*="report"]:has-text("Daily Revenue"), td:has-text("Daily Revenue"), '
                'li:has-text("Daily Revenue"), span:has-text("Daily Revenue")'
            ).first
            expect(daily_revenue).to_be_visible(timeout=10_000)

            # ── Verify Daily Deposit Report is present ──
            daily_deposit = page.locator(
                'a:has-text("Daily Deposit"), button:has-text("Daily Deposit"), '
                '[class*="report"]:has-text("Daily Deposit"), td:has-text("Daily Deposit"), '
                'li:has-text("Daily Deposit"), span:has-text("Daily Deposit")'
            ).first
            expect(daily_deposit).to_be_visible(timeout=10_000)

            # ── Click Daily Deposit Report ──
            daily_deposit.click()
            page.wait_for_load_state("networkidle")

            # Wait for the loading spinner to disappear before interacting
            try:
                page.locator('mat-spinner, [class*="spinner"], [class*="loading"]').first.wait_for(
                    state="hidden", timeout=20_000
                )
            except Exception:
                pass
            page.wait_for_timeout(2000)

            # ── Select today's date in the date selector ──
            today = today_date()
            # Click the calendar icon (mat-datepicker-toggle) to open the date picker
            cal_toggle = page.locator('mat-datepicker-toggle button, button[aria-label*="calendar" i], button[aria-label*="date" i]').first
            cal_toggle.wait_for(state="visible", timeout=10_000)
            cal_toggle.click()
            page.wait_for_timeout(1000)

            # Click "Today" button in the open calendar overlay if present, else type date directly
            today_btn = page.locator('button:has-text("Today"), .mat-calendar-body-today').first
            try:
                today_btn.wait_for(state="visible", timeout=3_000)
                today_btn.click()
                page.wait_for_timeout(500)
            except Exception:
                # No "Today" button — close calendar and type date into the input directly
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                date_input = page.locator('input[matInput]').first
                date_input.fill(today, force=True)
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
            page.wait_for_timeout(500)

            # ── Click Generate Report button ──
            generate_btn = page.locator(
                'button:has-text("Generate"), button:has-text("Generate Report")'
            ).first
            generate_btn.wait_for(state="visible", timeout=10_000)
            generate_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

            # ── Verify required table columns ──
            expected_columns = [
                "Branch",
                "Branch Description",
                "Cash",
                "Checks",
                "Credit/Debit",
                "PrePay",
                "Total",
            ]
            for col in expected_columns:
                col_header = page.locator(
                    f'th:has-text("{col}"), mat-header-cell:has-text("{col}"), '
                    f'td:has-text("{col}"), [role="columnheader"]:has-text("{col}")'
                ).first
                expect(col_header).to_be_visible(timeout=10_000), f"Column '{col}' not found in report"

        finally:
            page.close()
