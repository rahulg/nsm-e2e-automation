import re
from datetime import datetime
from playwright.sync_api import Page, expect


class Lt262FormPage:
    """LT-262 Form Page — Public Portal.

    Structure:
      Outer tabs: LT-262-Form Details | Additional Details | Supporting Documents | Terms and Conditions | Fee Due
      Inner tabs (within Form Details): A. Vehicle | B. Location | C. Lien | D. Date of Storage | E. Name/Address

    Tab C uses checkboxes (Labor, Materials, Towing, Storage, Other) with dollar amount inputs.
    Terms uses bare input[checkbox] (not mat-checkbox), NAME and DATE fields.
    Fee Due has "Finish and Pay" button.
    """

    def __init__(self, page: Page):
        self.page = page

        # Outer form tabs
        self.form_details_tab = page.locator('[role="tab"]:has-text("LT-262-Form Details")')
        self.additional_details_tab = page.locator('[role="tab"]:has-text("Additional Details")')
        self.supporting_docs_tab = page.locator('[role="tab"]:has-text("Supporting Documents")')
        self.terms_tab = page.locator('[role="tab"]:has-text("Terms and Conditions")')
        self.fee_due_tab = page.locator('[role="tab"]:has-text("Fee Due")')

        # Inner tabs (within LT-262-Form Details)
        self.tab_a = page.locator('[role="tab"]:has-text("DESCRIPTION OF VEHICLE")')
        self.tab_b = page.locator('[role="tab"]:has-text("LOCATION OF VEHICLE")')
        self.tab_c = page.locator('[role="tab"]:has-text("DESCRIPTION OF LIEN")')
        self.tab_d = page.locator('[role="tab"]:has-text("DATE OF STORAGE")')
        self.tab_e = page.locator('[role="tab"]:has-text("NAME AND ADDRESS")')

        # Navigation buttons
        self.next_button = page.locator('button:has-text("Next")').first
        self.back_button = page.locator('button:has-text("Back")').first
        self.finish_and_pay_button = page.locator('button:has-text("Finish and Pay")').first

    def _wait_for_loader(self):
        """Wait for the loading overlay to disappear."""
        try:
            self.page.locator(".cdk-overlay-backdrop.exp-loader-overlay-backdrop").wait_for(
                state="hidden", timeout=10_000
            )
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    def _click_inner_tab(self, tab):
        """Click an inner tab using dispatch_event to bypass overlays."""
        tab.dispatch_event("click")
        self.page.wait_for_timeout(1000)

    def _click_outer_tab(self, tab):
        """Click an outer tab using dispatch_event to bypass overlays."""
        tab.dispatch_event("click")
        self.page.wait_for_timeout(1000)

    def _click_next(self):
        """Click Next button to advance to the next tab, preserving form state."""
        next_btn = self.page.locator('button:has-text("Next")').first
        next_btn.scroll_into_view_if_needed(timeout=5_000)
        next_btn.click()
        self.page.wait_for_timeout(2000)

    def click_form_details_tab(self):
        self._click_outer_tab(self.form_details_tab)

    def click_additional_details_tab(self):
        self._click_next()

    def click_supporting_docs_tab(self):
        self._click_next()

    def click_terms_tab(self):
        self._click_next()

    def click_fee_due_tab(self):
        self._click_next()

    def expect_form_tabs_visible(self):
        """Wait for the form to be ready."""
        expect(self.form_details_tab).to_be_visible(timeout=15_000)
        self._wait_for_loader()

    # ===== Navigate through inner tabs A and B (pre-filled, just advance) =====

    def skip_vehicle_and_location_tabs(self):
        """Advance past Tab A (Vehicle) and Tab B (Location) — pre-filled from LT-260."""
        # Tab A: DESCRIPTION OF VEHICLE — already visible on form load
        self._click_next()  # A → B
        # Tab B: LOCATION OF VEHICLE
        self._click_next()  # B → C

    # ===== Tab C: DESCRIPTION OF LIEN =====

    def fill_lien_charges(self, charges: dict):
        """Fill Tab C lien charges. Must be called after skip_vehicle_and_location_tabs().
        charges keys: 'storage', 'towing', 'labor', 'materials', 'other'
        """
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

        self._click_next()  # C → D

    # ===== Tab D: DATE OF STORAGE =====

    def fill_date_of_storage(self, date_str: str):
        """Fill Tab D with the storage date. Must be called after fill_lien_charges()."""
        date_input = self.page.locator('input[placeholder="MM/DD/YYYY"]').first
        date_input.fill(date_str)
        self.page.wait_for_timeout(300)
        self._click_next()  # D → E

    # ===== Tab E: NAME AND ADDRESS =====

    def fill_person_authorizing(self, name: str, address: str, zip_code: str, city: str = "Raleigh"):
        """Fill Tab E. Must be called after fill_date_of_storage()."""
        self.page.locator('input[placeholder="Name"]').first.fill(name)
        self.page.locator('input[placeholder="Physical Address"]').first.fill(address)
        self.page.locator('input[placeholder="Zip"]').first.fill(zip_code)
        self.page.locator('input[placeholder="City"]').first.fill(city)
        self.page.wait_for_timeout(300)

    # ===== Additional Details (outer tab) =====

    def fill_additional_details(self, name: str, address: str, zip_code: str,
                                city: str = "Raleigh", state: str = "North Carolina",
                                phone: str = "9195551234"):
        """Fill the Additional Details outer tab — person proposing to sell vehicle."""
        self.click_additional_details_tab()
        self.page.locator('input[aria-label="Name *"]').first.fill(name)
        self.page.locator('input[aria-label="Address *"]').first.fill(address)

        # Zip field has no aria-label — find it via parent div with class zip-row-reverse
        zip_field = self.page.locator('.zip-row-reverse input[type="text"]').first
        try:
            zip_field.wait_for(state="visible", timeout=5_000)
            zip_field.fill(zip_code)
        except Exception:
            # Fallback: find the input between Address and City by index
            text_inputs = self.page.locator('mat-form-field input[type="text"]')
            # Index: 0=Reference#, 1=Name, 2=Address, 3=Zip, 4=City
            text_inputs.nth(3).fill(zip_code)

        self.page.locator('input[aria-label="City *"]').first.fill(city)
        self.page.wait_for_timeout(500)

        # State dropdown
        state_select = self.page.locator('mat-select[aria-label="State *"]')
        try:
            state_select.click()
            self.page.wait_for_timeout(500)
            self.page.locator(f'mat-option:has-text("{state}")').first.click()
            self.page.wait_for_timeout(500)
        except Exception:
            pass

        # Phone
        phone_input = self.page.locator('input[type="tel"]').first
        try:
            phone_input.scroll_into_view_if_needed(timeout=5_000)
            phone_input.click()
            phone_input.fill(phone)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

    # ===== Supporting Documents (outer tab) =====

    def upload_documents(self, file_paths: list):
        """Upload documents via the Supporting Documents tab."""
        self.click_supporting_docs_tab()
        self.page.wait_for_timeout(500)
        file_input = self.page.locator('input[type="file"]').first
        file_input.set_input_files(file_paths)
        self.page.wait_for_timeout(1000)

    # ===== Terms and Conditions (outer tab) =====

    def accept_terms_and_sign(self, name: str):
        """Accept terms checkboxes and fill signature fields.
        The Terms tab uses bare input[checkbox] (not mat-checkbox), NAME and DATE fields.
        """
        self.click_terms_tab()
        self.page.wait_for_timeout(1000)

        # Check all unchecked checkboxes in the terms tab
        # These are bare input[type="checkbox"], wrapped in mat-checkbox
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

        # Fill NAME
        name_input = self.page.locator('input[aria-label="NAME *"]').first
        name_input.fill(name)

        # Fill DATE if empty
        try:
            date_input = self.page.locator('input[aria-label="DATE *"]').first
            date_value = date_input.input_value()
            if not date_value:
                today = datetime.now().strftime("%m/%d/%Y")
                date_input.fill(today)
        except Exception:
            pass

    # ===== Fee Due (outer tab) =====

    def finish_and_pay(self):
        """Advance to Fee Due tab via Next and click 'Finish and Pay'."""
        self.click_fee_due_tab()  # Next from Terms → Fee Due
        self.page.wait_for_timeout(1000)

        # Click Finish and Pay
        self.finish_and_pay_button.scroll_into_view_if_needed(timeout=5_000)
        self.finish_and_pay_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(5000)

    def expect_fee_displayed(self):
        """Verify the fee amount is shown on Fee Due tab."""
        self.click_fee_due_tab()
        locator = self.page.get_by_text(re.compile(r"\$\d", re.I)).first
        expect(locator).to_be_visible(timeout=10_000)

    # ===== Navigation helpers =====

    def click_next(self):
        """Click Next button to advance within inner tabs."""
        self.next_button.click()
        self.page.wait_for_timeout(1000)
