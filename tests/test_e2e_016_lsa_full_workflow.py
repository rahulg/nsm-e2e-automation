"""
E2E-016: Location Storage Admin (LSA) Full Workflow
Uses STAFF_USER_B credentials (LSA role). Auth is temporary — not persisted between runs.

Phases:
  1. [Staff Portal] Login as LSA → dashboard shows Messages/Home heading
                   + LT-260, LT-261, LT-262, LT-262A, LT-263, Sold, Payment in sidebar
  2. [Staff Portal] Click LT-260 in sidebar → land on LT-260 listing → click first entry
  3. [Staff Portal] Click User Management → "User Management" heading
                   + "DMV Users" and "DMV Roles" tabs visible
  4. [Staff Portal] Click Configuration → "Configuration" heading
                   + "LT-262 Fee" and "Letterhead" tabs visible
  5. [Staff Portal] Click Facility Management → "Facilities/Individuals" heading visible
  6. [Staff Portal] Reports → System Generated Reports → Daily Deposit → date → Generate
                   → verify table columns (same as E2E-015 Phase 2)
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import today_date
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage

SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


@pytest.mark.e2e
@pytest.mark.multiuser
@pytest.mark.high
@pytest.mark.fixed
class TestE2E016LSAFullWorkflow:
    """E2E-016: LSA — all admin capabilities in one session"""

    # ========================================================================
    # PHASE 1: Dashboard — heading + sidebar links
    # ========================================================================
    def test_phase_1_verify_dashboard(self, lsa_context: BrowserContext):
        """Phase 1: LSA lands on dashboard showing Messages/Home heading and full sidebar."""
        page = lsa_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # ── Dashboard heading: "Messages" or "Home" ──
            heading = page.locator(
                ':has-text("Messages"), :has-text("Home")'
            ).first
            expect(heading).to_be_visible(timeout=15_000)

            # ── Sidebar nav links ──
            sidebar_items = [
                ("LT-260",  'a[href*="LT-260"], a:has-text("LT-260")'),
                ("LT-261",  'a[href*="LT-261"], a:has-text("LT-261")'),
                ("LT-262",  'a[href*="LT-262"], a:has-text("LT-262")'),
                ("LT-262A", 'a[href*="LT-262A"], a:has-text("LT-262A")'),
                ("LT-263",  'a[href*="LT-263"], a:has-text("LT-263")'),
                ("Sold",    'a[href*="sold"], a:has-text("Sold")'),
                ("Payment", 'a[href*="payment"], a:has-text("Payment")'),
            ]
            for label, selector in sidebar_items:
                link = page.locator(selector).first
                expect(link).to_be_visible(timeout=10_000), f"Sidebar link '{label}' not visible"

        finally:
            page.close()

    # ========================================================================
    # PHASE 2: LT-260 listing → click first entry
    # ========================================================================
    def test_phase_2_lt260_listing(self, lsa_context: BrowserContext):
        """Phase 2: Click LT-260 in sidebar → LT-260 landing page → click first entry."""
        page = lsa_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)

            # Navigate to LT-260 listing
            staff_dashboard.navigate_to_lt260_listing()

            # Switch to "All" tab to ensure records are always present
            lt260_listing.click_all_tab()

            # Click the first entry in the listing
            lt260_listing.select_application(0)

            # Verify we landed on the detail page
            expect(page.get_by_text(re.compile(r"Vehicle Details", re.I)).first).to_be_visible(timeout=15_000)

        finally:
            page.close()

    # ========================================================================
    # PHASE 3: User Management → heading + tabs
    # ========================================================================
    def test_phase_3_user_management(self, lsa_context: BrowserContext):
        """Phase 3: Click User Management → heading visible + DMV Users & DMV Roles tabs."""
        page = lsa_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Navigate via sidebar
            user_mgmt_link = page.locator(
                'a:has-text("User Management"), a[href*="user-management"]'
            ).first
            user_mgmt_link.wait_for(state="visible", timeout=10_000)
            user_mgmt_link.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            # ── "User Management" heading ──
            expect(
                page.get_by_text(re.compile(r"^User Management$", re.I)).first
            ).to_be_visible(timeout=15_000)

            # ── "DMV Users" tab ──
            expect(
                page.locator('[role="tab"]:has-text("DMV Users"), button:has-text("DMV Users")').first
            ).to_be_visible(timeout=10_000)

            # ── "DMV Roles" tab ──
            expect(
                page.locator('[role="tab"]:has-text("DMV Roles"), button:has-text("DMV Roles")').first
            ).to_be_visible(timeout=10_000)

        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Configuration → heading + tabs
    # ========================================================================
    def test_phase_4_configuration(self, lsa_context: BrowserContext):
        """Phase 4: Click Configuration → heading visible + LT-262 Fee & Letterhead tabs."""
        page = lsa_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Navigate via sidebar
            config_link = page.locator(
                'a:has-text("Configuration"), a[href*="configuration"]'
            ).first
            config_link.wait_for(state="visible", timeout=10_000)
            config_link.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            # ── "Configuration" heading ──
            expect(
                page.get_by_text(re.compile(r"^Configuration$", re.I)).first
            ).to_be_visible(timeout=15_000)

            # ── "LT-262 Fee" tab ──
            expect(
                page.locator('[role="tab"]:has-text("LT-262 Fee"), button:has-text("LT-262 Fee")').first
            ).to_be_visible(timeout=10_000)

            # ── "Letterhead" tab ──
            expect(
                page.locator('[role="tab"]:has-text("Letterhead"), button:has-text("Letterhead")').first
            ).to_be_visible(timeout=10_000)

        finally:
            page.close()

    # ========================================================================
    # PHASE 5: Facility Management → heading
    # ========================================================================
    def test_phase_5_facility_management(self, lsa_context: BrowserContext):
        """Phase 5: Click Facility Management → 'Facilities/Individuals' heading visible."""
        page = lsa_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Navigate via sidebar
            facility_link = page.locator(
                'a:has-text("Facility Management"), a[href*="facility"]'
            ).first
            facility_link.wait_for(state="visible", timeout=10_000)
            facility_link.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            # ── "Facilities/Individuals" heading ──
            expect(
                page.get_by_text(re.compile(r"Facilities/Individuals", re.I)).first
            ).to_be_visible(timeout=15_000)

        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Reports → Daily Deposit → Generate → verify columns
    # (mirrors E2E-015 Phase 2)
    # ========================================================================
    def test_phase_6_daily_deposit_report(self, lsa_context: BrowserContext):
        """Phase 6: System Generated Reports → Daily Deposit → generate → verify columns."""
        page = lsa_context.new_page()
        try:
            go_to_staff_dashboard(page)

            # Navigate to Reports via sidebar
            staff_dashboard = StaffDashboardPage(page)
            staff_dashboard.navigate_to_reports()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            # ── "System Generated Reports" section heading ──
            system_reports_heading = page.locator(':has-text("System Generated Reports")').last
            expect(system_reports_heading).to_be_visible(timeout=10_000)

            # ── Daily Revenue Report is present ──
            daily_revenue = page.locator(
                'a:has-text("Daily Revenue"), button:has-text("Daily Revenue"), '
                'td:has-text("Daily Revenue"), span:has-text("Daily Revenue"), '
                'li:has-text("Daily Revenue")'
            ).first
            expect(daily_revenue).to_be_visible(timeout=10_000)

            # ── Daily Deposit Report is present ──
            daily_deposit = page.locator(
                'a:has-text("Daily Deposit"), button:has-text("Daily Deposit"), '
                'td:has-text("Daily Deposit"), span:has-text("Daily Deposit"), '
                'li:has-text("Daily Deposit")'
            ).first
            expect(daily_deposit).to_be_visible(timeout=10_000)

            # ── Click Daily Deposit Report ──
            daily_deposit.click()
            page.wait_for_load_state("networkidle")

            # Wait for loading spinner to disappear
            try:
                page.locator('mat-spinner, [class*="spinner"], [class*="loading"]').first.wait_for(
                    state="hidden", timeout=20_000
                )
            except Exception:
                pass
            page.wait_for_timeout(2000)

            # ── Select today's date ──
            today = today_date()
            cal_toggle = page.locator(
                'mat-datepicker-toggle button, button[aria-label*="calendar" i], button[aria-label*="date" i]'
            ).first
            cal_toggle.wait_for(state="visible", timeout=10_000)
            cal_toggle.click()
            page.wait_for_timeout(1000)

            today_btn = page.locator('button:has-text("Today"), .mat-calendar-body-today').first
            try:
                today_btn.wait_for(state="visible", timeout=3_000)
                today_btn.click()
                page.wait_for_timeout(500)
            except Exception:
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
                date_input = page.locator('input[matInput]').first
                date_input.fill(today, force=True)
                page.wait_for_timeout(300)
                page.keyboard.press("Enter")
            page.wait_for_timeout(500)

            # ── Click Generate Report ──
            generate_btn = page.locator('//button[contains(text()," Generate Report ")]')
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
                expect(col_header).to_be_visible(timeout=10_000), f"Column '{col}' not found"

        finally:
            page.close()
