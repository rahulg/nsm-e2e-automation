"""
Staff Portal Sold Listing Page — view sold/completed vehicles.
"""

import re
from playwright.sync_api import Page, expect


class SoldListingPage:
    def __init__(self, page: Page):
        self.page = page

        # Table
        self.application_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")
        self.vin_links = page.locator("span.table-link, table a, table td a")
        self.search_input = page.locator(
            'input[placeholder*="Search using VIN"], input[placeholder*="Search" i], input[placeholder*="VIN" i]'
        ).first

    def search_by_vin(self, vin: str):
        # Click "Show Filters" to reveal column filter fields
        show_filters_btn = self.page.locator('button:has-text("Show Filters")').first
        try:
            show_filters_btn.wait_for(state="visible", timeout=5_000)
            show_filters_btn.click()
            self.page.wait_for_timeout(1000)
        except Exception:
            pass  # Filters may already be visible

        # Enter VIN in the VIN column filter field
        vin_filter = self.page.locator('input[name="vin"]').first
        try:
            vin_filter.wait_for(state="visible", timeout=5_000)
            vin_filter.fill("")
            self.page.wait_for_timeout(300)
            vin_filter.fill(vin)
            self.page.wait_for_timeout(500)
            vin_filter.press("Enter")
        except Exception:
            # Fallback to old search input
            self.search_input.fill("")
            self.page.wait_for_timeout(300)
            self.search_input.fill(vin)
            self.search_input.press("Enter")

        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def select_application(self, index: int = 0):
        self.vin_links.nth(index).click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_applications_visible(self):
        expect(self.application_rows.first).to_be_visible(timeout=15_000)

    def expect_vehicle_sold(self, vin: str):
        self.search_by_vin(vin)
        self.expect_applications_visible()

    def verify_lt265_in_correspondence(self, entry: str = "LT-265"):
        """Click 'View Correspondence/Documents' → verify Correspondence History modal
        has the expected entry → close the modal.

        Args:
            entry: The correspondence entry to look for. Use "LT-265" for standard
                   workflow (E2E-005) and "LT-265A" for mobile home workflow (E2E-003).
        """
        view_corr = self.page.locator(
            '//span[contains(text(),"View Correspondence/Documents")]'
        ).first
        expect(view_corr).to_be_visible(timeout=15_000)
        view_corr.click()
        self.page.wait_for_timeout(1500)

        # Modal: "Correspondence History"
        modal = self.page.locator('mat-dialog-container').first
        expect(modal).to_be_visible(timeout=10_000)
        expect(
            self.page.get_by_text(re.compile(r"Correspondence History", re.I)).first
        ).to_be_visible(timeout=10_000)

        # Verify the expected entry is present
        expected_entry = self.page.get_by_text(re.compile(re.escape(entry), re.I)).first
        expect(expected_entry).to_be_visible(timeout=10_000)

        # Close modal
        try:
            close_btn = self.page.locator(
                'mat-dialog-container button:has-text("Close"), '
                '[mat-dialog-close]'
            ).first
            close_btn.click(timeout=5_000)
        except Exception:
            self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)
