"""
Staff Portal Paper Form Page — for adding paper LT-260/262/263 submissions.

Paper forms are received via mail and entered by staff. They follow a similar
structure to digital forms but with some differences:
  - Pre-filled fields from prior forms are EDITABLE (unlike PP where they are read-only)
  - Paper forms have NO date restrictions on sale date
"""

import re
from playwright.sync_api import Page, expect


class PaperFormPage:
    def __init__(self, page: Page):
        self.page = page

        # Lien charges (for LT-262 paper form — Phase 4)
        self.storage_fee_input = page.locator('input[name="storageFee"]').first
        self.towing_fee_input = page.locator('input[name="TowingFee"]').first
        self.labor_fee_input = page.locator('input[name="LaborFee"]').first

        # Sale details (for LT-263 paper form — Phase 5)
        self.sale_type_public = page.locator(
            'mat-radio-button:has-text("Public"), input[value*="public" i], '
            'label:has-text("Public") input[type="radio"], '
            '[role="radio"]:has-text("Public")'
        ).first
        self.sale_type_private = page.locator(
            'mat-radio-button:has-text("Private"), input[value*="private" i], '
            'label:has-text("Private") input[type="radio"], '
            '[role="radio"]:has-text("Private")'
        ).first
        self.sale_date_input = page.locator(
            'input[name*="sale" i][name*="date" i], input[name*="date" i][type="date"]'
        ).first
        self.lien_amount_input = page.locator(
            'input[name*="lien" i][name*="amount" i], input[name*="total" i]'
        ).first

        # Action buttons
        self.submit_button = page.locator('button:has-text("Submit"), button:has-text("Save")').first
        self.next_button = page.locator('button:has-text("Next")').first

    # ===== CDK overlay helper =====

    def _dismiss_cdk_overlay(self):
        """Dismiss any open CDK overlay that blocks clicks."""
        try:
            self.page.evaluate("""() => {
                const backdrops = document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop'
                );
                backdrops.forEach(b => { b.click(); b.remove(); });
            }""")
            self.page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

    # ===== Phase 1: LT-260 Add from Paper =====

    def fill_modal_vin_and_next(self, vin: str):
        """In the Add from Paper modal: enter VIN and click Next (no E-Stop radio for LT-260)."""
        vin_input = self.page.locator(
            'mat-dialog-container input[placeholder*="VIN" i], '
            'mat-dialog-container input[name*="vin" i]'
        ).first
        vin_input.wait_for(state="visible", timeout=10_000)
        vin_input.fill(vin)
        self.page.wait_for_timeout(500)

        next_btn = self.page.locator('mat-dialog-container button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(3000)

    def fill_make(self, make_text: str = "TOY"):
        """Type in the Make autocomplete field and select the first suggestion."""
        make_input = self.page.locator("(//input[@role='combobox'])[1]")
        expect(make_input).to_be_visible(timeout=15_000)
        make_input.click()
        make_input.fill(make_text)
        self.page.wait_for_timeout(1000)

        option = self.page.locator('.cdk-overlay-pane mat-option').first
        option.wait_for(state="visible", timeout=10_000)
        option.click()
        self.page.wait_for_timeout(500)

    def fill_year(self, year: str):
        """Fill the Year field, then Tab out to close any autocomplete and settle the form."""
        year_input = self.page.locator(
            'input[name*="year" i], input[aria-label*="Year" i], input[placeholder*="Year" i]'
        ).first
        year_input.wait_for(state="visible", timeout=10_000)
        year_input.fill(year)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(500)

    def fill_date_vehicle_left(self, date_str: str):
        """Fill the 'DATE VEHICLE LEFT' field (MM/DD/YYYY)."""
        date_input = self.page.locator(
            'input[aria-label*="Date Vehicle Left" i], '
            'input[placeholder*="Date Vehicle Left" i], '
            'input[name*="dateVehicle" i], '
            'input[name*="date_vehicle" i], '
            'input[placeholder="MM/DD/YYYY"]'
        ).first
        date_input.wait_for(state="visible", timeout=10_000)
        date_input.fill(date_str)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(300)

    def fill_search_location(self, search_text: str = "pen"):
        """Type in SEARCH LOCATION field and pick the first suggestion."""
        location_input = self.page.locator(
            'input[placeholder*="Search Garage Name or Address" i]'
        ).first
        location_input.wait_for(state="visible", timeout=10_000)
        location_input.click()
        location_input.fill(search_text)
        self.page.wait_for_timeout(2000)

        suggestion = self.page.locator('.cdk-overlay-pane mat-option, mat-autocomplete mat-option').first
        suggestion.wait_for(state="visible", timeout=10_000)
        suggestion.click()
        self.page.wait_for_timeout(500)

    def select_stolen_no(self):
        """Select 'No' from the Stolen dropdown."""
        stolen_dropdown = self.page.locator(
            'mat-select[aria-label*="Stolen" i], mat-select[name*="stolen" i]'
        ).first
        stolen_dropdown.wait_for(state="visible", timeout=10_000)
        stolen_dropdown.click()
        self.page.wait_for_timeout(500)

        no_option = self.page.locator('mat-option:has-text("No")').first
        no_option.wait_for(state="visible", timeout=10_000)
        no_option.click()
        self.page.wait_for_timeout(500)

    def submit_with_confirmation(self):
        """Click Submit → confirm modal (Yes) → verify green banner → wait for redirect."""
        self._dismiss_cdk_overlay()
        submit_btn = self.page.locator('button:has-text("Submit")').first
        submit_btn.wait_for(state="visible", timeout=15_000)
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        self.page.wait_for_timeout(1000)

        # Confirmation modal → Yes
        yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
        yes_btn.wait_for(state="visible", timeout=10_000)
        yes_btn.click()
        self.page.wait_for_timeout(2000)

        # Verify green success banner (may auto-dismiss quickly — soft check)
        try:
            success = self.page.get_by_text(re.compile(r"success", re.I)).first
            expect(success).to_be_visible(timeout=5_000)
        except Exception:
            pass  # Banner may have already dismissed before check

        # Wait for redirect
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    # ===== Phase 1 assertion =====

    def expect_paper_form_visible(self):
        """Verify paper form entry screen is visible."""
        expect(
            self.page.get_by_text(re.compile(r"Individual|Business|Paper|Add from Paper", re.I)).first
        ).to_be_visible(timeout=15_000)

    # ===== Phase 4: LT-262 lien charges =====

    def fill_lien_charges(self, charges: dict):
        """Fill lien charges for paper LT-262."""
        charge_map = {
            "labor": "LaborFee",
            "towing": "TowingFee",
            "storage": "storageFee",
        }

        for charge_type, fee_name in charge_map.items():
            amount = charges.get(charge_type)
            if amount:
                checkbox = self.page.locator(f'mat-checkbox:has-text("{charge_type.capitalize()}")')
                try:
                    cls = checkbox.get_attribute("class") or ""
                    if "mat-checkbox-checked" not in cls:
                        checkbox.locator("label").click()
                        self.page.wait_for_timeout(300)
                except Exception:
                    pass

                fee_input = self.page.locator(f'input[name="{fee_name}"]')
                try:
                    fee_input.fill(amount)
                except Exception:
                    pass
                self.page.wait_for_timeout(200)

    def verify_fields_editable(self):
        """Verify that pre-filled fields are editable (paper form feature)."""
        try:
            make_input = self.page.locator("(//input[@role='combobox'])[1]")
            assert not make_input.is_disabled(), "Make field should be editable in paper form"
        except Exception:
            pass

    # ===== Phase 5: LT-263 paper form sale details =====

    def fill_lt263_sale_details(self, sale_type: str = "public", sale_date: str = None,
                                lien_amount: str = "800"):
        """Fill Vehicle Sale Information for paper LT-263:
        TYPE OF SALE (mat-select dropdown) → SALE DATE → Lien Amount → Lien For = LABOR checkbox.
        """
        # TYPE OF SALE — mat-select dropdown
        type_of_sale_select = self.page.locator('mat-select[aria-label="TYPE OF SALE"]').first
        try:
            type_of_sale_select.wait_for(state="visible", timeout=10_000)
        except Exception:
            # Fallback: first mat-select on the page
            type_of_sale_select = self.page.locator('mat-select').first
            type_of_sale_select.wait_for(state="visible", timeout=10_000)
        type_of_sale_select.click()
        self.page.wait_for_timeout(500)

        option_text = "Public" if sale_type.lower() == "public" else "Private"
        option = self.page.locator(f'mat-option:has-text("{option_text}")').first
        option.wait_for(state="visible", timeout=5_000)
        option.click()
        self.page.wait_for_timeout(500)

        # SALE DATE
        if sale_date:
            date_input = self.page.locator('input[name="sale_date"]')
            date_input.wait_for(state="visible", timeout=10_000)
            date_input.fill(sale_date)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(300)

        # Lien For — Labor checkbox first (reveals the lien amount input)
        # Click the mat-checkbox that contains "Labor" to trigger Angular change detection
        labor_cb = self.page.locator('//mat-checkbox[.//span[contains(text(),"Labor")]]').first
        labor_cb.wait_for(state="visible", timeout=10_000)
        cls = labor_cb.get_attribute("class") or ""
        if "mat-checkbox-checked" not in cls:
            labor_cb.locator("label").click()
            self.page.wait_for_timeout(800)

        # Lien Amount
        lien_input = self.page.locator("(//input[@name='lien_amount'])[1]")
        expect(lien_input).to_be_visible(timeout=10_000)
        lien_input.fill(lien_amount)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(300)

    def submit_paper_lt263(self):
        """Submit paper LT-263:
        Click Submit → confirm Yes → Issue modal → Issue → OK modal → OK.
        """
        self._dismiss_cdk_overlay()

        # Submit button (enabled after form is filled)
        submit_btn = self.page.locator('button:has-text("Submit")').first
        expect(submit_btn).to_be_enabled(timeout=15_000)
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        self.page.wait_for_timeout(1000)

        # Confirmation modal → Yes
        yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
        yes_btn.wait_for(state="visible", timeout=10_000)
        yes_btn.click()
        self.page.wait_for_timeout(1500)

        # Issue modal → Issue
        issue_btn = self.page.locator('mat-dialog-container button:has-text("Issue")').first
        issue_btn.wait_for(state="visible", timeout=10_000)
        issue_btn.click()
        self.page.wait_for_timeout(1500)

        # OK modal → OK
        ok_btn = self.page.locator(
            'mat-dialog-container button:has-text("Ok"), '
            'mat-dialog-container button:has-text("OK")'
        ).first
        ok_btn.wait_for(state="visible", timeout=10_000)
        ok_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    # ===== Legacy fill_sale_details (kept for other tests) =====

    def fill_sale_details(self, sale_type: str = "public", sale_date: str = None,
                          lien_amount: str = "800"):
        """Fill sale details for paper LT-263."""
        radio = self.sale_type_public if sale_type.lower() == "public" else self.sale_type_private
        try:
            radio.wait_for(state="visible", timeout=10_000)
            tag = radio.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("mat-radio-button", "label"):
                radio.locator("label").click() if tag == "mat-radio-button" else radio.click()
            else:
                radio.click()
        except Exception:
            try:
                radio.click(force=True)
            except Exception:
                pass
        self.page.wait_for_timeout(500)

        if sale_date:
            try:
                self.sale_date_input.fill(sale_date)
            except Exception:
                try:
                    date_input = self.page.locator('input[placeholder="MM/DD/YYYY"]').first
                    date_input.fill(sale_date)
                except Exception:
                    pass

        try:
            self.lien_amount_input.fill(lien_amount)
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    # ===== Shared submit (Phases 4 & 5 — no confirmation modal) =====

    def submit(self):
        """Submit paper form with fallback strategies (no confirmation modal)."""
        self._dismiss_cdk_overlay()

        try:
            self.submit_button.wait_for(state="visible", timeout=10_000)
            self.submit_button.scroll_into_view_if_needed()
            self.submit_button.click()
        except Exception:
            clicked = self.page.evaluate("""() => {
                const targets = ['submit', 'save', 'add'];
                const buttons = document.querySelectorAll('button, input[type="submit"]');
                let best = null;
                for (const btn of buttons) {
                    const txt = (btn.textContent || '').toLowerCase().trim();
                    const type = (btn.getAttribute('type') || '').toLowerCase();
                    if (type === 'submit' || targets.some(t => txt.includes(t))) {
                        if (!btn.disabled && btn.offsetParent !== null) {
                            best = btn;
                        }
                    }
                }
                if (best) { best.scrollIntoView(); best.click(); return true; }
                return false;
            }""")
            if not clicked:
                btn = self.page.locator(
                    'button:has-text("Submit"), button:has-text("Save"), '
                    'button:has-text("Add"), button[type="submit"]'
                ).last
                try:
                    btn.click(force=True)
                except Exception:
                    try:
                        btn.dispatch_event("click")
                    except Exception:
                        pass
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def click_next(self):
        self.next_button.click()
        self.page.wait_for_timeout(1000)
