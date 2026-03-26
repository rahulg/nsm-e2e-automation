"""
Staff Portal LT-262A Listing Page — Mobile Home workflow.

LT-262A is the mobile home variant of LT-262. When processed, it directly
issues LT-265 (skipping LT-263 entirely).
"""

import re
from playwright.sync_api import Page, expect


class Lt262aListingPage:
    def __init__(self, page: Page):
        self.page = page

        # Listing tabs
        self.to_process_tab = page.locator('[role="tab"]:has-text("To Process")')
        self.processed_tab = page.locator('[role="tab"]:has-text("Processed")')
        self.all_tab = page.locator('[role="tab"]:has-text("All")')

        # Table
        self.application_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")
        self.vin_links = page.locator("span.table-link, table a, table td a")
        self.search_input = page.locator(
            'input[placeholder*="Search using VIN"], input[placeholder*="Search" i], input[placeholder*="VIN" i]'
        ).first

        # Detail page buttons
        self.issue_lt265_button = page.locator('button:has-text("Issue LT-265"), button:has-text("Generate LT-265")').first
        self.reject_button = page.locator('button:has-text("Reject")').first
        self.back_button = page.locator('button:has-text("Back")').first

    # ===== Listing navigation =====

    def click_to_process_tab(self):
        self.to_process_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_processed_tab(self):
        self.processed_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

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

    # ===== Actions =====

    def issue_lt265(self):
        """Issue LT-265 directly from LT-262A (skips LT-262/LT-263)."""
        expect(self.issue_lt265_button).to_be_visible(timeout=10_000)
        self.issue_lt265_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    # ===== Assertions =====

    def verify_mobile_home_details_visible(self):
        """Verify mobile home specific details are shown."""
        expect(
            self.page.get_by_text(re.compile(r"Manufactured Home|Mobile Home|LT-262A", re.I)).first
        ).to_be_visible(timeout=15_000)

    def verify_vehicle_details_visible(self):
        """Verify vehicle details section is visible."""
        expect(
            self.page.get_by_text(re.compile(r"Description of Vehicle|Vehicle Details", re.I)).first
        ).to_be_visible(timeout=15_000)
