"""
E2E-012: Drawdown Recharge
PP: My Profile → ACH tab → Add Funds ($50) → verify green banner →
PP: My Profile → ACH tab → View Drawdown Account History →
    verify top entry has today's date, category=Drawdown Recharge, Credit Amount=$50.00

Phases:
  1. [Public Portal]  Hover username → My Profile → ACH tab → Add Funds $50 → verify banner
  2. [Public Portal]  My Profile → ACH tab → View Drawdown Account History →
                      verify top row: today's date, Drawdown Recharge, $50.00
"""

import re
from datetime import datetime

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.pages.public_portal.dashboard_page import PublicDashboardPage


PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


BUSINESS_NAME = "G-Car Garages New"


def navigate_to_ach_tab(page):
    """Select business → hover over username → click My Profile → click ACH tab."""
    dashboard = PublicDashboardPage(page)
    dashboard.select_business(BUSINESS_NAME)

    username = page.locator("//span[contains(text(),'Daniel Scott')]")
    username.wait_for(state="visible", timeout=15_000)
    username.hover()
    page.wait_for_timeout(500)

    page.get_by_text("My Profile").click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    ach_tab = page.locator('[role="tab"]:has-text("ACH")')
    ach_tab.wait_for(state="visible", timeout=15_000)
    ach_tab.click()
    page.wait_for_timeout(1000)


@pytest.mark.e2e
@pytest.mark.alternate
@pytest.mark.high
@pytest.mark.payment
class TestE2E012DrawdownRecharge:
    """E2E-012: Drawdown Recharge — add $50, verify banner and account history"""

    # ========================================================================
    # PHASE 1: Public Portal — Add Funds $50 via My Profile → ACH tab
    # ========================================================================
    def test_phase_1_add_drawdown_funds(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Hover username → My Profile → ACH tab →
        Add Funds → enter $50 → Save → verify green banner"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            navigate_to_ach_tab(page)

            # Click "Add Funds" button under Drawdown section
            add_funds_btn = page.locator("//span[contains(text(),'Add Funds')]")
            add_funds_btn.wait_for(state="visible", timeout=15_000)
            add_funds_btn.click()
            page.wait_for_timeout(1000)

            # Enter 50 in the Amount field
            amount_input = page.locator('mat-dialog-container input').first
            amount_input.wait_for(state="visible", timeout=10_000)
            amount_input.fill("50")
            page.wait_for_timeout(500)

            # Click Save
            save_btn = page.locator('mat-dialog-container button:has-text("Save")').first
            save_btn.wait_for(state="visible", timeout=10_000)
            save_btn.click()
            page.wait_for_timeout(2000)

            # Verify green success banner
            success_banner = page.get_by_text(
                "Your Drawdown account has been successfully credited with $50"
            )
            expect(success_banner).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Public Portal — View Drawdown Account History
    # ========================================================================
    def test_phase_2_verify_drawdown_history(self, public_context: BrowserContext):
        """Phase 2: [Public Portal] My Profile → ACH tab →
        View Drawdown Account History → verify top entry:
        today's date, category=Drawdown Recharge, Credit Amount=$50.00"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            navigate_to_ach_tab(page)

            # Click "View Drawdown Account History" — opens in a new tab
            history_link = page.get_by_text("View Drawdown Account History")
            history_link.wait_for(state="visible", timeout=15_000)

            with page.context.expect_page() as new_page_info:
                history_link.click()
            history_page = new_page_info.value
            history_page.wait_for_load_state("networkidle")
            history_page.wait_for_timeout(3000)

            # Verify "Drawdown Account History" table heading is visible
            expect(
                history_page.get_by_text(re.compile(r"Drawdown Account History", re.I)).first
            ).to_be_visible(timeout=15_000)

            # Today's date in MM-DD-YYYY format (as used by the table)
            today = datetime.now().strftime("%m-%d-%Y")

            # Top row of the history table (mat-table uses <tr mat-row="">)
            first_row = history_page.locator("tr[mat-row]").first
            first_row.wait_for(state="visible", timeout=15_000)

            # Verify today's date in the row
            expect(first_row.get_by_text(today)).to_be_visible(timeout=10_000)

            # Verify category = Drawdown Recharge
            expect(
                first_row.get_by_text(re.compile(r"Drawdown Recharge", re.I))
            ).to_be_visible(timeout=10_000)

            # Verify Credit Amount ($) = $50.00
            expect(
                first_row.get_by_text(re.compile(r"\$50\.00", re.I))
            ).to_be_visible(timeout=10_000)

            history_page.close()
        finally:
            page.close()
