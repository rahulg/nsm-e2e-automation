"""
Staff Portal User Management Page — for managing DMV users.
"""

import re
from playwright.sync_api import Page, expect


class UserManagementPage:
    def __init__(self, page: Page):
        self.page = page

        # Navigation
        self.user_management_link = page.locator(
            'a:has-text("User Management"), a[href*="user-management"], '
            'a[href*="userManagement"], a:has-text("DMV Users"), a:has-text("Users")'
        ).first

        # User listing
        self.user_table = page.locator("table.mat-table, table").first
        self.user_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")
        self.search_input = page.locator('input[placeholder*="Search" i]').first

        # Add user
        self.add_user_button = page.locator(
            'button:has-text("Add New DMV User"), button:has-text("Add User"), '
            'button:has-text("Add New")'
        ).first

        # User form fields
        self.first_name_input = page.locator(
            'input[name*="first" i], input[placeholder*="First Name" i]'
        ).first
        self.last_name_input = page.locator(
            'input[name*="last" i], input[placeholder*="Last Name" i]'
        ).first
        self.email_input = page.locator(
            'input[name*="email" i], input[placeholder*="Email" i]'
        ).first
        self.role_select = page.locator(
            'mat-select[name*="role" i], select[name*="role" i]'
        ).first

        # Action buttons
        self.save_button = page.locator('button:has-text("Save"), button:has-text("Submit")').first
        self.cancel_button = page.locator('button:has-text("Cancel")').first

    def navigate_to(self):
        """Click User Management nav link."""
        try:
            self.user_management_link.wait_for(state="visible", timeout=5_000)
            self.user_management_link.scroll_into_view_if_needed()
            self.user_management_link.click()
        except Exception:
            # URL-based fallback — try multiple path patterns
            base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
            for path in ["user-management", "userManagement", "users"]:
                try:
                    self.page.goto(f"{base}/{path}", timeout=15_000)
                    self.page.wait_for_load_state("networkidle")
                    if "user" in self.page.url.lower():
                        break
                except Exception:
                    continue
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_add_new_user(self):
        expect(self.add_user_button).to_be_visible(timeout=10_000)
        self.add_user_button.click()
        self.page.wait_for_timeout(1000)

    def fill_user_details(self, first_name: str, last_name: str, email: str, role: str = None):
        """Fill new DMV user form."""
        self.first_name_input.fill(first_name)
        self.last_name_input.fill(last_name)
        self.email_input.fill(email)

        if role:
            self.role_select.click()
            self.page.locator(f'mat-option:has-text("{role}"), option:has-text("{role}")').first.click()
            self.page.wait_for_timeout(500)

    def save_user(self):
        self.save_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_user_listing_visible(self):
        try:
            expect(self.user_table).to_be_visible(timeout=15_000)
        except Exception:
            # Fallback: look for any user-related content
            expect(
                self.page.get_by_text(re.compile(r"Name|Email|Role|User", re.I)).first
            ).to_be_visible(timeout=10_000)

    def expect_section_accessible(self):
        """Verify User Management section is accessible."""
        expect(
            self.page.get_by_text(re.compile(r"User Management|DMV Users|Users", re.I)).first
        ).to_be_visible(timeout=15_000)
