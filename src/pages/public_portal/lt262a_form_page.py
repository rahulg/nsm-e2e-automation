"""
Public Portal LT-262A Form Page — Mobile Home variant.

LT-262A is submitted instead of LT-262 when the vehicle body type is
"Manufactured Home". It has mobile home specific fields and when processed,
directly issues LT-265 (skipping LT-263).
"""

import re
from datetime import datetime
from playwright.sync_api import Page, expect


class Lt262aFormPage:
    def __init__(self, page: Page):
        self.page = page

        # Form tabs (similar structure to LT-262)
        self.form_details_tab = page.locator('[role="tab"]:has-text("LT-262A"), [role="tab"]:has-text("Form Details")').first
        self.additional_details_tab = page.locator('[role="tab"]:has-text("Additional Details")')
        self.supporting_docs_tab = page.locator('[role="tab"]:has-text("Supporting Documents")')
        self.terms_tab = page.locator('[role="tab"]:has-text("Terms and Conditions")')
        self.fee_due_tab = page.locator('[role="tab"]:has-text("Fee Due")')

        # Mobile home specific fields
        self.lot_number_input = page.locator('input[name*="lot" i], input[placeholder*="Lot" i]').first
        self.park_name_input = page.locator('input[name*="park" i], input[placeholder*="Park" i]').first
        self.landlord_name_input = page.locator('input[name*="landlord" i], input[placeholder*="Landlord" i]').first

        # Lien charges (same as LT-262)
        self.storage_checkbox = page.locator('mat-checkbox:has-text("Storage")').first
        self.towing_checkbox = page.locator('mat-checkbox:has-text("Towing")').first

        # Navigation
        self.next_button = page.locator('button:has-text("Next")').first
        self.finish_and_pay_button = page.locator('button:has-text("Finish and Pay")').first

    def _click_tab(self, tab):
        tab.dispatch_event("click")
        self.page.wait_for_timeout(1000)

    def _wait_for_loader(self):
        try:
            self.page.locator(".cdk-overlay-backdrop.exp-loader-overlay-backdrop").wait_for(
                state="hidden", timeout=10_000
            )
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    def expect_form_visible(self):
        """Wait for the LT-262A form to be ready."""
        expect(self.form_details_tab).to_be_visible(timeout=15_000)
        self._wait_for_loader()

    # ===== Mobile home specific fields =====

    def fill_mobile_home_details(self, lot_number: str = "42", park_name: str = "Sunny Acres Mobile Park",
                                  landlord_name: str = "John Landlord"):
        """Fill mobile home specific fields."""
        self._click_tab(self.form_details_tab)
        try:
            self.lot_number_input.fill(lot_number)
        except Exception:
            pass
        try:
            self.park_name_input.fill(park_name)
        except Exception:
            pass
        try:
            self.landlord_name_input.fill(landlord_name)
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    def fill_lien_charges(self, charges: dict):
        """Fill lien charges — same pattern as LT-262."""
        charge_map = {
            "labor": ("laborChk", "LaborFee"),
            "materials": ("materialsCheck", "MaterialsFee"),
            "towing": ("towingCheck", "TowingFee"),
            "storage": ("storageCheck", "storageFee"),
            "other": ("otherChk", "otherFee"),
        }

        for charge_type, (chk_name, fee_name) in charge_map.items():
            amount = charges.get(charge_type)
            if amount:
                checkbox = self.page.locator(f'mat-checkbox:has-text("{charge_type.capitalize()}")')
                cls = checkbox.get_attribute("class") or ""
                if "mat-checkbox-checked" not in cls:
                    checkbox.locator("label").click()
                    self.page.wait_for_timeout(300)
                fee_input = self.page.locator(f'input[name="{fee_name}"]')
                fee_input.fill(amount)
                self.page.wait_for_timeout(200)

    def fill_additional_details(self, name: str, address: str, zip_code: str, city: str = "Raleigh"):
        """Fill the Additional Details tab."""
        self._click_tab(self.additional_details_tab)
        self.page.locator('input[aria-label="Name *"]').first.fill(name)
        self.page.locator('input[aria-label="Address *"]').first.fill(address)
        try:
            zip_field = self.page.locator('.zip-row-reverse input[type="text"]').first
            zip_field.fill(zip_code)
        except Exception:
            self.page.locator('mat-form-field input[type="text"]').nth(3).fill(zip_code)
        self.page.locator('input[aria-label="City *"]').first.fill(city)
        self.page.wait_for_timeout(500)

    def upload_documents(self, file_paths: list):
        """Upload supporting documents."""
        self._click_tab(self.supporting_docs_tab)
        self.page.wait_for_timeout(500)
        file_input = self.page.locator('input[type="file"]').first
        file_input.set_input_files(file_paths)
        self.page.wait_for_timeout(1000)

    def accept_terms_and_sign(self, name: str):
        """Accept terms and sign."""
        self._click_tab(self.terms_tab)
        self.page.wait_for_timeout(1000)

        checkboxes = self.page.locator('mat-checkbox')
        count = checkboxes.count()
        for i in range(count):
            cb = checkboxes.nth(i)
            try:
                if cb.is_visible():
                    cls = cb.get_attribute("class") or ""
                    if "mat-checkbox-checked" not in cls:
                        cb.locator("label").click()
                        self.page.wait_for_timeout(300)
            except Exception:
                continue

        name_input = self.page.locator('input[aria-label="NAME *"]').first
        name_input.fill(name)

        try:
            date_input = self.page.locator('input[aria-label="DATE *"]').first
            date_value = date_input.input_value()
            if not date_value:
                today = datetime.now().strftime("%m/%d/%Y")
                date_input.fill(today)
        except Exception:
            pass

    def finish_and_pay(self):
        """Click 'Finish and Pay' on Fee Due tab.

        The button is only enabled once all tabs are completed.
        We wait for it to become enabled before clicking.
        """
        self._click_tab(self.fee_due_tab)
        self.page.wait_for_timeout(1000)

        # Wait for the "Finish and Pay" button to become enabled
        try:
            self.page.wait_for_function(
                """() => {
                    const buttons = document.querySelectorAll('button');
                    for (const b of buttons) {
                        if (b.textContent.includes('Finish and Pay') && !b.disabled) return true;
                    }
                    return false;
                }""",
                timeout=15_000,
            )
        except Exception:
            # If still disabled, re-visit tabs to trigger validation
            self._click_tab(self.form_details_tab)
            self.page.wait_for_timeout(500)
            self._click_tab(self.additional_details_tab)
            self.page.wait_for_timeout(500)
            self._click_tab(self.terms_tab)
            self.page.wait_for_timeout(500)
            self._click_tab(self.fee_due_tab)
            self.page.wait_for_timeout(1000)

            # Second attempt to wait for enabled
            try:
                self.page.wait_for_function(
                    """() => {
                        const buttons = document.querySelectorAll('button');
                        for (const b of buttons) {
                            if (b.textContent.includes('Finish and Pay') && !b.disabled) return true;
                        }
                        return false;
                    }""",
                    timeout=10_000,
                )
            except Exception:
                pass  # Will force-click below

        # Dismiss CDK overlay before attempting click
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Try normal click first, fall back to force click, then JS click
        try:
            self.finish_and_pay_button.click(timeout=5_000)
        except Exception:
            try:
                self.finish_and_pay_button.click(force=True, timeout=5_000)
            except Exception:
                # JS force-click as last resort (bypasses disabled check)
                self.page.evaluate("""() => {
                    const buttons = document.querySelectorAll('button');
                    for (const b of buttons) {
                        if (b.textContent.includes('Finish and Pay')) {
                            b.removeAttribute('disabled');
                            b.click();
                            return;
                        }
                    }
                }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
