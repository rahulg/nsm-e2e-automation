"""
Public Portal LT-262A Form Page — Mobile Home variant.

LT-262A form navigates via Next buttons through multiple sections:
  Sections A–D : click Next (no data entry)
  Section E    : Notice of Sale — future date (21 days), address, place of sale → Next
  Section F    : Phone → Next
  Section G    : Next
  Terms        : check all, name, date → Submit
"""

from datetime import datetime, timedelta
from playwright.sync_api import Page, expect


class Lt262aFormPage:
    def __init__(self, page: Page):
        self.page = page
        self.next_button = page.locator('button:has-text("Next")').first
        self.submit_button = page.locator('button:has-text("Submit")').first

    def _click_next(self):
        """Click Next button and wait for page to settle."""
        self.next_button.scroll_into_view_if_needed(timeout=10_000)
        self.next_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def expect_form_visible(self):
        """Wait for LT-262A form to load."""
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def click_next_sections(self, count: int = 1):
        """Click Next 'count' times for sections that need no data entry."""
        for _ in range(count):
            self._click_next()

    def fill_section_e_notice_of_sale(self, address: str, place_of_sale: str, zip_code: str = "27601"):
        """Fill Section E — Notice of Sale Information.

        Date of sale must be at least 21 days in the future.
        Fills: date, address, place of sale → click Next.
        """
        sale_date = (datetime.now() + timedelta(days=21)).strftime("%m/%d/%Y")

        # Date of Sale field
        date_field = self.page.locator(
            'input[aria-label*="Date" i], input[name*="date" i], input[placeholder*="date" i]'
        ).first
        try:
            date_field.scroll_into_view_if_needed(timeout=5_000)
            date_field.click()
            date_field.fill(sale_date)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Address field
        address_field = self.page.locator(
            'input[aria-label*="Address" i], input[placeholder*="Address" i], input[name*="address" i]'
        ).first
        try:
            address_field.scroll_into_view_if_needed(timeout=5_000)
            address_field.click()
            address_field.fill(address)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Place of Sale field
        place_field = self.page.locator(
            'input[aria-label*="Place of Sale" i], input[placeholder*="Place of Sale" i], input[name*="place" i]'
        ).first
        try:
            place_field.scroll_into_view_if_needed(timeout=5_000)
            place_field.click()
            place_field.fill(place_of_sale)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Zip field
        zip_field = self.page.locator(
            'input[aria-label*="Zip" i], input[placeholder*="Zip" i], input[name*="zip" i]'
        ).first
        try:
            zip_field.scroll_into_view_if_needed(timeout=5_000)
            zip_field.click()
            zip_field.fill(zip_code)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        self._click_next()

    def fill_phone(self, phone: str = "9195551234"):
        """Fill Phone field then click Next."""
        phone_field = self.page.locator(
            'input[type="tel"], input[aria-label*="Phone" i], input[placeholder*="Phone" i], input[name*="phone" i], input[formcontrolname*="phone" i]'
        ).first
        phone_field.wait_for(state="visible", timeout=10_000)
        phone_field.scroll_into_view_if_needed(timeout=5_000)
        phone_field.click()
        phone_field.fill("")
        phone_field.press_sequentially(phone, delay=50)
        self.page.wait_for_timeout(500)
        expect(self.next_button).to_be_enabled(timeout=10_000)
        self._click_next()

    def accept_terms_and_submit(self, name: str):
        """Check all terms checkboxes, fill name + date, click Submit."""
        self.page.wait_for_timeout(1000)

        # Check all visible unchecked checkboxes
        checkboxes = self.page.locator("mat-checkbox")
        count = checkboxes.count()
        for i in range(count):
            cb = checkboxes.nth(i)
            try:
                if cb.is_visible():
                    cls = cb.get_attribute("class") or ""
                    if "mat-checkbox-checked" not in cls:
                        cb.locator("label").click()
                        self.page.wait_for_timeout(200)
            except Exception:
                continue

        # Fill NAME
        name_field = self.page.locator('input[aria-label="NAME *"]').first
        try:
            name_field.scroll_into_view_if_needed(timeout=5_000)
            name_field.click()
            name_field.fill(name)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Fill DATE if empty
        date_field = self.page.locator('input[aria-label="DATE *"]').first
        try:
            date_field.scroll_into_view_if_needed(timeout=5_000)
            val = date_field.input_value()
            if not val:
                date_field.click()
                date_field.fill(datetime.now().strftime("%m/%d/%Y"))
                self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Submit
        self.submit_button.scroll_into_view_if_needed(timeout=5_000)
        self.submit_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_success_banner(self):
        """Verify green success banner after submission."""
        banner = self.page.locator(
            '[class*="success" i], [class*="toast" i], [class*="snack" i], '
            '[class*="banner" i], [class*="alert" i]'
        ).first
        expect(banner).to_be_visible(timeout=15_000)
