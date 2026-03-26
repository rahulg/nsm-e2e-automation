"""
Staff Portal Payments Page — for recording mailed payments and viewing payment history.
"""

import re
from playwright.sync_api import Page, expect


class StaffPaymentsPage:
    def __init__(self, page: Page):
        self.page = page

        # Listing tabs
        self.all_payments_tab = page.locator('[role="tab"]:has-text("All Payments")')
        self.pending_tab = page.locator('[role="tab"]:has-text("Pending")')

        # Table
        self.payment_rows = page.locator("table.mat-table tr.mat-row")
        self.search_input = page.locator('input[placeholder*="Search" i]').first

        # Record Mailed Payment button
        self.record_mailed_payment_button = page.locator(
            'button:has-text("Record Mailed Payment"), button:has-text("Record Payment")'
        ).first

        # Payment form fields
        self.check_number_input = page.locator(
            'input[placeholder*="check" i], input[name*="check" i]'
        ).first
        self.amount_input = page.locator(
            'input[placeholder*="amount" i], input[name*="amount" i]'
        ).first
        self.payment_method_select = page.locator(
            'mat-select[name*="method" i], select[name*="method" i]'
        ).first

        # Action buttons
        self.save_button = page.locator(
            'button:has-text("Save"), button:has-text("Record"), button:has-text("Submit")'
        ).first
        self.cancel_button = page.locator('button:has-text("Cancel")').first

    def click_record_mailed_payment(self):
        """Click 'Record Mailed Payment' button."""
        expect(self.record_mailed_payment_button).to_be_visible(timeout=10_000)
        self.record_mailed_payment_button.click()
        self.page.wait_for_timeout(1000)

    def fill_payment_details(self, check_number: str = "12345", amount: str = "16.75"):
        """Fill mailed payment details."""
        try:
            self.check_number_input.fill(check_number)
        except Exception:
            pass
        try:
            self.amount_input.fill(amount)
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    def save_payment(self):
        """Save the payment record."""
        self.save_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def record_mailed_payment(self, check_number: str = "12345", amount: str = "16.75"):
        """Full flow: click record, fill details, save."""
        self.click_record_mailed_payment()
        self.fill_payment_details(check_number, amount)
        self.save_payment()

    def search_payment(self, term: str):
        """Search for a payment."""
        self.search_input.fill(term)
        self.search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def expect_payment_visible(self):
        """Verify at least one payment row is visible."""
        expect(self.payment_rows.first).to_be_visible(timeout=15_000)

    def verify_payment_recorded(self):
        """Verify a payment was successfully recorded (success message)."""
        success = self.page.locator('[class*="success" i], [class*="toast" i], [class*="snack" i]').first
        expect(success).to_be_visible(timeout=15_000)
