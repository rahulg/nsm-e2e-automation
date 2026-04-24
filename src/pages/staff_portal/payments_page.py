"""
Staff Portal Payments Page — for recording mailed payments and viewing payment history.
"""

import re
from playwright.sync_api import Page, expect


class StaffPaymentsPage:
    def __init__(self, page: Page):
        self.page = page

        # Listing page
        self.record_mailed_payment_button = page.locator(
            'button:has-text("Record Mailed Payment")'
        ).first
        self.payment_rows = page.locator("table.mat-table tr.mat-row")
        self.search_input = page.locator('input[placeholder*="Search" i]').first

    # ── Listing page ────────────────────────────────────────────────────────

    def click_record_mailed_payment(self):
        """Click 'Record Mailed Payment' on the payments listing page."""
        expect(self.record_mailed_payment_button).to_be_visible(timeout=15_000)
        self.record_mailed_payment_button.click()
        self.page.wait_for_load_state("networkidle")

    # ── Record Mailed Payment form (new page) ────────────────────────────────

    def enter_vin_and_add(self, vin: str):
        """Enter VIN in the mat-chip-list input and press Enter to add it as a chip."""
        vin_input = self.page.locator('input[id*="mat-chip-list-input"]')
        expect(vin_input).to_be_visible(timeout=15_000)
        vin_input.click()
        vin_input.press_sequentially(vin, delay=50)
        self.page.wait_for_timeout(500)
        vin_input.press("Enter")
        self.page.wait_for_timeout(1000)

    def select_payment_type_check(self):
        """Under 'Payment Details', open Payment Type dropdown and select Check."""
        payment_type_select = self.page.locator('mat-select[aria-label="Payment Type"]')
        expect(payment_type_select).to_be_visible(timeout=10_000)
        payment_type_select.click()
        self.page.wait_for_timeout(500)

        check_option = self.page.locator('mat-option:has-text("Check")').first
        expect(check_option).to_be_visible(timeout=5_000)
        check_option.click()
        self.page.wait_for_timeout(500)

    def fill_payer_name(self, payer_name: str):
        """Fill Business/Payer Name field."""
        payer_input = self.page.locator('input[name="payerName"]')
        expect(payer_input).to_be_visible(timeout=10_000)
        payer_input.fill(payer_name)

    def fill_date_check_received(self, date_str: str):
        """Fill Date Check Was Received field (format: MM/DD/YYYY)."""
        from datetime import datetime
        # Normalise YYYY-MM-DD → MM/DD/YYYY if needed
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                date_str = datetime.strptime(date_str, fmt).strftime("%m/%d/%Y")
                break
            except ValueError:
                continue
        date_input = self.page.locator('input[name="receivedDate"]')
        expect(date_input).to_be_visible(timeout=10_000)
        date_input.fill(date_str)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(500)

    def fill_check_number(self, check_number: str):
        """Fill Check Number field."""
        check_input = self.page.locator('input[name="paymentNumber"]')
        expect(check_input).to_be_visible(timeout=10_000)
        check_input.fill(check_number)

    def submit_payment(self):
        """Click Submit → confirm modal (Yes) → green banner → redirect to listing."""
        submit_btn = self.page.locator('button:has-text("Submit")').last
        expect(submit_btn).to_be_enabled(timeout=10_000)
        submit_btn.click()
        self.page.wait_for_timeout(1000)

        # Confirmation modal → Yes
        yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
        expect(yes_btn).to_be_visible(timeout=10_000)
        yes_btn.click()

        # Green success banner
        success_banner = self.page.locator(
            '[class*="success" i], [class*="snack" i], [class*="toast" i]'
        ).first
        expect(success_banner).to_be_visible(timeout=15_000)

        # Redirected back to payment listing
        self.page.wait_for_load_state("networkidle")

    def record_mailed_payment(
        self,
        vin: str,
        payer_name: str = "Test Garage Inc",
        check_number: str = "12345",
        date_received: str = None,
    ):
        """Full flow: click Record Mailed Payment → enter VIN → add → fill details → submit."""
        from src.helpers.data_helper import past_date
        if date_received is None:
            date_received = past_date(1)

        self.click_record_mailed_payment()
        self.enter_vin_and_add(vin)
        self.select_payment_type_check()
        self.fill_payer_name(payer_name)
        self.fill_date_check_received(date_received)
        self.fill_check_number(check_number)
        self.submit_payment()

    # ── Listing helpers ──────────────────────────────────────────────────────

    def search_payment(self, term: str):
        """Search for a payment by VIN or payer name."""
        self.search_input.fill(term)
        self.search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def expect_payment_visible(self):
        """Verify at least one payment row is visible."""
        expect(self.payment_rows.first).to_be_visible(timeout=15_000)
