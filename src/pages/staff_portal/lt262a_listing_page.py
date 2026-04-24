"""
Staff Portal LT-262A Listing Page — Mobile Home workflow.

LT-262A is the mobile home variant of LT-262. When processed, it directly
issues LT-265 and LT-265A (skipping LT-263 entirely).
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
        """Search by VIN using column filters (Show Filters → VIN field)."""
        show_filters_btn = self.page.locator('button:has-text("Show Filters")').first
        try:
            show_filters_btn.wait_for(state="visible", timeout=5_000)
            show_filters_btn.click()
            self.page.wait_for_timeout(1000)
        except Exception:
            pass  # Filters may already be visible

        vin_filter = self.page.locator('input[name="vin"]').first
        try:
            vin_filter.wait_for(state="visible", timeout=5_000)
            vin_filter.fill("")
            self.page.wait_for_timeout(300)
            vin_filter.fill(vin)
            vin_filter.press("Enter")
        except Exception:
            # Fallback: generic search input
            search = self.page.locator(
                'input[placeholder*="Search using VIN"], input[placeholder*="Search" i], input[placeholder*="VIN" i]'
            ).first
            search.fill(vin)
            search.press("Enter")

        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def select_application(self, index: int = 0):
        self.vin_links.nth(index).click(force=True)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_applications_visible(self):
        expect(self.application_rows.first).to_be_visible(timeout=15_000)

    # ===== Actions =====

    def issue_lt265_and_lt265a(self):
        """Click 'Issue LT-265 and LT-265A' button → confirm in modal → verify banner."""
        issue_btn = self.page.locator(
            'button:has-text("Issue LT-265 and LT-265A"), '
            'button:has-text("Issue LT-265A"), '
            'button:has-text("Issue LT-265")'
        ).first
        issue_btn.scroll_into_view_if_needed(timeout=10_000)
        issue_btn.click()
        self.page.wait_for_timeout(2000)

        # Confirmation modal → click Issue
        modal_issue_btn = self.page.locator(
            'mat-dialog-container button:has-text("Issue")'
        ).first
        modal_issue_btn.wait_for(state="visible", timeout=10_000)
        modal_issue_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(3000)

    # ===== Assertions =====

    def expect_success_banner(self):
        """Verify green success banner after issuing."""
        banner = self.page.locator(
            '[class*="success" i], [class*="toast" i], [class*="snack" i]'
        ).first
        expect(banner).to_be_visible(timeout=15_000)

    def expect_status_processed(self):
        """Verify status on the detail page is Processed."""
        expect(
            self.page.get_by_text(re.compile(r"Processed", re.I)).first
        ).to_be_visible(timeout=15_000)

    def verify_vehicle_details_visible(self):
        """Verify vehicle details section is visible."""
        expect(
            self.page.get_by_text(re.compile(r"Description of Vehicle|Vehicle Details", re.I)).first
        ).to_be_visible(timeout=15_000)
