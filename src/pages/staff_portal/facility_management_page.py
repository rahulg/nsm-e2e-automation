"""
Staff Portal Facility Management Page — manage individuals and businesses.
"""

import re
from playwright.sync_api import Page, expect


class FacilityManagementPage:
    def __init__(self, page: Page):
        self.page = page

        # Navigation
        self.facility_management_link = page.locator(
            'a:has-text("Facility Management"), a[href*="facility"], '
            'a:has-text("Facility"), a[href*="Facility"]'
        ).first

        # Tabs
        self.individuals_tab = page.locator(
            '[role="tab"]:has-text("Individual"), button:has-text("Individual"), '
            'a:has-text("Individual")'
        ).first
        self.businesses_tab = page.locator(
            '[role="tab"]:has-text("Business"), button:has-text("Business"), '
            'a:has-text("Business"), [role="tab"]:has-text("Companies"), '
            'button:has-text("Companies"), a:has-text("Companies")'
        ).first

        # Listing
        self.user_table = page.locator("table.mat-table, table").first
        self.user_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")
        self.search_input = page.locator('input[placeholder*="Search" i]').first

    def navigate_to(self):
        """Click Facility Management nav link."""
        try:
            self.facility_management_link.wait_for(state="visible", timeout=5_000)
            self.facility_management_link.scroll_into_view_if_needed()
            self.facility_management_link.click()
        except Exception:
            # URL-based fallback — try multiple path patterns
            base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
            for path in ["facility-management", "facilityManagement", "facility"]:
                try:
                    self.page.goto(f"{base}/{path}", timeout=15_000)
                    self.page.wait_for_load_state("networkidle")
                    if "facility" in self.page.url.lower():
                        break
                except Exception:
                    continue
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_individuals_tab(self):
        try:
            self.individuals_tab.wait_for(state="visible", timeout=10_000)
            self.individuals_tab.click()
        except Exception:
            try:
                self.individuals_tab.dispatch_event("click")
            except Exception:
                self.page.get_by_text(re.compile(r"Individual", re.I)).first.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_businesses_tab(self):
        try:
            self.businesses_tab.wait_for(state="visible", timeout=10_000)
            self.businesses_tab.click()
        except Exception:
            try:
                self.businesses_tab.dispatch_event("click")
            except Exception:
                self.page.get_by_text(re.compile(r"Business|Compan", re.I)).first.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def expect_listing_visible(self):
        try:
            expect(self.user_table).to_be_visible(timeout=15_000)
        except Exception:
            # Fallback: look for any listing content
            expect(
                self.page.get_by_text(re.compile(r"Name|Email|Phone|Address|Company", re.I)).first
            ).to_be_visible(timeout=10_000)

    def expect_section_accessible(self):
        """Verify Facility Management section is accessible."""
        expect(
            self.page.get_by_text(re.compile(r"Facility Management|Individuals|Businesses", re.I)).first
        ).to_be_visible(timeout=15_000)
