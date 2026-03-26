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
        try:
            self.search_input.wait_for(state="visible", timeout=10_000)
        except Exception:
            pass
        self.search_input.click()
        self.search_input.fill("")
        self.page.wait_for_timeout(300)
        self.search_input.fill(vin)
        self.search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1500)

    def select_application(self, index: int = 0):
        self.vin_links.nth(index).click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_applications_visible(self):
        expect(self.application_rows.first).to_be_visible(timeout=15_000)

    def expect_vehicle_sold(self, vin: str):
        self.search_by_vin(vin)
        self.expect_applications_visible()
