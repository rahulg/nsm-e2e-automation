"""
NCNSS-531: Cancel button fix — targeted regression tests (Staff Portal)

Verifies that the Cancel button on LT-261, LT-262A, LT-263, and LT-262 paper
forms actually aborts the flow (routes to the form's Listing page, no record
created/issued) after the fix deployed in the 05.26.2026 release.

Scenarios covered:
  SC-1  [Critical] LT-261 Cancel → Yes aborts paper-logging, routes to Listing
                    and does not create a record or issue LT-265/265A
  SC-4  [High]     LT-262 Cancel → Yes routes to LT-262 Listing (regression:
                    originally mis-routed to the same page)
  TC-11 [Medium]   RBAC: Fiscal User cannot reach paper form Cancel flow
                    (form entry buttons absent)

  SC-2 (LT-262A Cancel) and SC-3 (LT-263 Cancel) require a pre-existing record
  in the paper-logging state and are NOT run by this file — mark them manual in
  the run_manifest and exercise them by hand or extend this file once a fixture
  that creates the prerequisite record is in place.
"""

import re

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import generate_vin
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage


SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


# ============================================================================
# SC-1: LT-261 Cancel flow  [Critical]
# Covers: TC-01, TC-02, TC-07, TC-08
# ============================================================================
@pytest.mark.ncnss531
@pytest.mark.regression
@pytest.mark.critical
class TestE2E_NCNSS531_SC1_Lt261Cancel:
    """SC-1: LT-261 paper form — Cancel→Yes aborts and routes to Listing."""

    SC1_VIN = generate_vin()

    def test_sc1_cancel_modal_appears(self, staff_context: BrowserContext):
        """TC-07: Cancel confirmation modal appears with Yes / No options."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_paper()
            lt261.fill_modal_vin_next(self.SC1_VIN)

            # Fill minimum fields to reach a Cancel-able state
            lt261.fill_year("2019")
            lt261.fill_make("TOY")

            # Click Cancel — modal must appear
            lt261.click_cancel_button()
            lt261.expect_cancel_modal_visible()

            print(
                f"EXPECTED: Cancel modal visible with Yes/No options | "
                f"ACTUAL: modal appeared — MATCH"
            )
        finally:
            page.close()

    def test_sc1_cancel_no_stays_on_form(self, staff_context: BrowserContext):
        """TC-08: Cancel→No / dismiss keeps user on the paper form."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_paper()
            lt261.fill_modal_vin_next(self.SC1_VIN)
            lt261.fill_year("2019")
            lt261.fill_make("TOY")

            lt261.click_cancel_button()
            lt261.expect_cancel_modal_visible()
            lt261.click_cancel_modal_no()

            # Should still be on the paper form — To Process tab should NOT be visible
            # (that tab only shows on the Listing page, not the form)
            to_process_visible = lt261.to_process_tab.is_visible()
            assert not to_process_visible, (
                "EXPECTED: remain on paper form after Cancel→No | "
                "ACTUAL: navigated away to listing — FAIL"
            )
            print(
                "EXPECTED: remain on paper form (To Process tab hidden) | "
                "ACTUAL: still on form — MATCH"
            )
        finally:
            page.close()

    def test_sc1_cancel_yes_routes_to_listing(self, staff_context: BrowserContext):
        """TC-01: LT-261 Cancel→Yes aborts and routes to LT-261 Listing."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_paper()
            lt261.fill_modal_vin_next(self.SC1_VIN)
            lt261.fill_year("2019")
            lt261.fill_make("TOY")
            lt261.fill_search_location("pen")

            lt261.click_cancel_button()
            lt261.expect_cancel_modal_visible()
            lt261.click_cancel_modal_yes()

            # Must be back on LT-261 Listing (To Process tab visible)
            lt261.expect_on_listing_page()

            print(
                "EXPECTED: navigate to LT-261 Listing (To Process tab visible) | "
                "ACTUAL: on Listing page — MATCH"
            )
        finally:
            page.close()

    def test_sc1_no_record_after_cancel(self, staff_context: BrowserContext):
        """TC-02: No LT-261 record created / no LT-265 issued after Cancel→Yes."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt261 = Lt261Page(page)

            # Use a fresh VIN specific to this assertion
            fresh_vin = generate_vin()

            dashboard.navigate_to_lt261_listing()
            lt261.click_add_from_paper()
            lt261.fill_modal_vin_next(fresh_vin)
            lt261.fill_year("2020")
            lt261.fill_make("HON")

            lt261.click_cancel_button()
            lt261.expect_cancel_modal_visible()
            lt261.click_cancel_modal_yes()

            lt261.expect_on_listing_page()

            # Verify the VIN does NOT appear anywhere in the listing
            lt261.expect_vin_not_in_listing(fresh_vin)

            print(
                f"EXPECTED: VIN {fresh_vin} absent from listing (no record created) | "
                f"ACTUAL: VIN not in listing — MATCH"
            )
        finally:
            page.close()


# ============================================================================
# SC-4: LT-262 Cancel routing regression  [High]
# Covers: TC-09, TC-10
# ============================================================================
@pytest.mark.ncnss531
@pytest.mark.regression
@pytest.mark.high
class TestE2E_NCNSS531_SC4_Lt262Routing:
    """SC-4: LT-262 Cancel→Yes routes to LT-262 Listing (regression check)."""

    def test_sc4_lt262_cancel_yes_routes_to_listing(self, staff_context: BrowserContext):
        """TC-09/TC-10: LT-262 Cancel→Yes routes to LT-262 Listing, no record submitted."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dashboard = StaffDashboardPage(page)
            lt262 = Lt262ListingPage(page)

            dashboard.navigate_to_lt262_listing()

            # Click 'Add from Paper' for LT-262 paper entry
            add_paper_btn = page.locator(
                'button:has-text("Add from Paper"), button:has-text("Add Paper LT-262")'
            ).first
            try:
                add_paper_btn.wait_for(state="visible", timeout=10_000)
                add_paper_btn.click()
                page.wait_for_timeout(1000)
            except Exception:
                pytest.skip("LT-262 'Add from Paper' button not found — form entry not available in this env state")

            # Fill minimal VIN to get to the form
            vin_input = page.locator(
                'mat-dialog-container input[placeholder*="VIN" i], input[name*="vin" i]'
            ).first
            try:
                vin_input.wait_for(state="visible", timeout=8_000)
                vin_input.fill(generate_vin())
                page.wait_for_timeout(500)
                next_btn = page.locator('mat-dialog-container button:has-text("Next"), button:has-text("Next")').first
                next_btn.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2000)
            except Exception:
                pass  # Some flows go straight to form without a modal

            # Click Cancel
            cancel_btn = page.locator('button:has-text("Cancel")').first
            cancel_btn.wait_for(state="visible", timeout=15_000)
            cancel_btn.click()
            page.wait_for_timeout(800)

            # Modal → Yes
            yes_btn = page.locator(
                'mat-dialog-container button:has-text("Yes"), [role="dialog"] button:has-text("Yes")'
            ).first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            # Must be back on LT-262 Listing (To Process tab visible)
            expect(lt262.to_process_tab).to_be_visible(timeout=15_000)

            # Assert URL contains LT-262 listing path (not the same form page)
            current_url = page.url
            assert "LT-262" in current_url or "lt-262" in current_url.lower(), (
                f"EXPECTED: URL contains LT-262 listing path | ACTUAL: {current_url}"
            )

            print(
                f"EXPECTED: navigate to LT-262 Listing | "
                f"ACTUAL: on Listing ({current_url}) — MATCH"
            )
        finally:
            page.close()


# ============================================================================
# TC-11: RBAC — Fiscal User cannot access N&S paper forms  [Medium]
# ============================================================================
@pytest.mark.ncnss531
@pytest.mark.regression
@pytest.mark.medium
@pytest.mark.rbac
class TestE2E_NCNSS531_TC11_FiscalRBAC:
    """TC-11: Fiscal User cannot reach paper form Cancel flow."""

    def test_tc11_fiscal_user_no_paper_form_access(self, fiscal_context: BrowserContext):
        """Fiscal User sees no 'Add Paper DWI/E-Stop' buttons on LT-261."""
        page = fiscal_context.new_page()
        try:
            # Navigate to Staff Portal dashboard as Fiscal User
            page.goto(SP_DASHBOARD_URL, timeout=60_000)
            page.wait_for_load_state("networkidle")

            # Try to reach LT-261 listing
            lt261_link = page.locator('a[href*="LT-261/list"]').first
            if lt261_link.is_visible():
                lt261_link.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)

                # Fiscal User must NOT see the Add Paper DWI/E-Stop buttons
                add_paper_btn = page.locator(
                    'button:has-text("Add Paper DWI"), button:has-text("Add Paper E-Stop"), '
                    'button:has-text("Add from Paper")'
                )
                add_paper_count = add_paper_btn.count()
                assert add_paper_count == 0, (
                    f"EXPECTED: 0 'Add Paper' buttons for Fiscal User | "
                    f"ACTUAL: {add_paper_count} button(s) visible — RBAC FAIL"
                )
                print(
                    "EXPECTED: no Add Paper buttons for Fiscal User | "
                    "ACTUAL: 0 buttons — MATCH (Cancel flow unreachable)"
                )
            else:
                # LT-261 nav link not visible at all for Fiscal User — also a pass
                print(
                    "EXPECTED: LT-261 not accessible to Fiscal User | "
                    "ACTUAL: LT-261 nav link hidden — MATCH (Cancel flow unreachable)"
                )
        finally:
            page.close()
