"""
Staff Portal Correspondence Page — view and manage correspondence/documents.
"""

import re
from playwright.sync_api import Page, expect


class CorrespondencePage:
    def __init__(self, page: Page):
        self.page = page

        # Correspondence modal/section
        self.view_correspondence_button = page.get_by_text("View Correspondence/Documents").first
        self.correspondence_table = page.locator(".correspondence-modal table tbody tr")
        self.close_button = page.locator(
            ".correspondence-modal button.mat-dialog-close, "
            ".correspondence-modal button:has-text('Close')"
        ).first

    def open_correspondence(self):
        self.view_correspondence_button.click()
        self.page.wait_for_timeout(1500)

    def expect_correspondence_visible(self):
        expect(self.correspondence_table.first).to_be_visible(timeout=10_000)

    def expect_letter_present(self, letter_type: str):
        """Verify a specific letter type exists in correspondence."""
        letter = self.page.locator(".correspondence-modal").get_by_text(letter_type).first
        expect(letter).to_be_visible(timeout=10_000)

    def close(self):
        try:
            self.close_button.click()
            self.page.wait_for_timeout(500)
        except Exception:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(500)

    def get_letter_count(self) -> int:
        return self.correspondence_table.count()
