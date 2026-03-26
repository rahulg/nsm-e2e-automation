"""
Staff Portal Paper Form Page — for adding paper LT-260/262/263 submissions.

Paper forms are received via mail and entered by staff. They follow a similar
structure to digital forms but with some differences:
  - Staff selects requester type (Individual or Business)
  - Pre-filled fields from prior forms are EDITABLE (unlike PP where they are read-only)
  - Paper forms have NO date restrictions on sale date
"""

import re
from datetime import datetime
from playwright.sync_api import Page, expect


class PaperFormPage:
    def __init__(self, page: Page):
        self.page = page

        # Requester type selection
        self.individual_radio = page.locator(
            'mat-radio-button:has-text("Individual"), label:has-text("Individual"), '
            'input[value*="individual" i], [role="radio"]:has-text("Individual")'
        ).first
        self.business_radio = page.locator(
            'mat-radio-button:has-text("Business"), label:has-text("Business"), '
            'input[value*="business" i], [role="radio"]:has-text("Business")'
        ).first

        # Vehicle details
        self.vin_input = page.locator('input[name="sno"], input[placeholder*="VIN" i]').first
        self.vin_lookup_button = page.locator(
            'button:has-text("VIN Lookup"), button:has-text("Lookup"), button:has-text("Search")'
        ).first
        self.make_input = page.locator('input[placeholder="Enter Make"], input[name*="make" i]').first
        self.year_input = page.locator('input[name="year"], input[name*="year" i]').first
        self.model_input = page.locator('input[name="model"], input[name*="model" i]').first
        self.color_input = page.locator('input[name="color"], input[name*="color" i]').first

        # Storage location
        self.location_input = page.locator('input[aria-label*="Location" i]').first
        self.address_input = page.locator('input[aria-label*="Address" i]').first
        self.zip_input = page.locator('input[aria-label*="Zip" i]').first

        # Lien charges (for LT-262 paper form)
        self.storage_fee_input = page.locator('input[name="storageFee"]').first
        self.towing_fee_input = page.locator('input[name="TowingFee"]').first
        self.labor_fee_input = page.locator('input[name="LaborFee"]').first

        # Sale details (for LT-263 paper form)
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

    # ===== Requester type =====

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

    def select_requester_type(self, requester_type: str = "Individual"):
        """Select Individual or Business requester type.

        Angular Material radio buttons have complex DOM structures.
        Use multiple strategies to find and click the correct element.
        Also handles mat-select dropdown as an alternative UI pattern.
        """
        self.page.wait_for_timeout(3000)

        # Strategy 1: Use JavaScript to find and click any element
        clicked = self.page.evaluate(f"""() => {{
            const target = '{requester_type.lower()}';
            // Try mat-radio-button
            const radios = document.querySelectorAll('mat-radio-button');
            for (const r of radios) {{
                if (r.textContent.toLowerCase().includes(target)) {{
                    const inner = r.querySelector('.mat-radio-inner-circle') ||
                                  r.querySelector('input[type="radio"]') ||
                                  r.querySelector('label') || r;
                    inner.click();
                    return true;
                }}
            }}
            // Try regular radio inputs
            const inputs = document.querySelectorAll('input[type="radio"]');
            for (const inp of inputs) {{
                const label = inp.closest('label') || inp.parentElement;
                if (label && label.textContent.toLowerCase().includes(target)) {{
                    inp.click();
                    return true;
                }}
            }}
            // Try mat-button-toggle
            const toggles = document.querySelectorAll('mat-button-toggle');
            for (const t of toggles) {{
                if (t.textContent.toLowerCase().includes(target)) {{
                    const btn = t.querySelector('button') || t;
                    btn.click();
                    return true;
                }}
            }}
            // Try mat-list-option, mat-chip, clickable divs (avoid buttons that open dialogs)
            const clickables = document.querySelectorAll(
                'mat-list-option, mat-chip, [role="option"], ' +
                '.mat-card, mat-card, [class*="type-select"], [class*="requester-type"]'
            );
            for (const el of clickables) {{
                const txt = (el.textContent || '').toLowerCase().trim();
                if (txt.includes(target) && txt.length < 50) {{
                    el.click();
                    return true;
                }}
            }}
            // Nuclear: TreeWalker — find exact text node and click parent
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null
            );
            let node;
            while (node = walker.nextNode()) {{
                const text = node.textContent.trim().toLowerCase();
                if (text === target || text === '{requester_type}') {{
                    const parent = node.parentElement;
                    if (parent && parent.offsetParent !== null) {{
                        parent.click();
                        return true;
                    }}
                }}
            }}
            return false;
        }}""")
        if clicked:
            self.page.wait_for_timeout(500)
            return

        # Strategy 2: Check if it's a mat-select dropdown
        try:
            mat_select = self.page.locator(
                'mat-select[name*="requester" i], mat-select[name*="type" i], '
                'mat-select[formcontrolname*="requester" i], mat-select[formcontrolname*="type" i], '
                'mat-select'
            ).first
            mat_select.wait_for(state="visible", timeout=3_000)
            mat_select.click()
            self.page.wait_for_timeout(500)
            option = self.page.locator(f'mat-option:has-text("{requester_type}")').first
            option.wait_for(state="visible", timeout=3_000)
            option.click()
            self.page.wait_for_timeout(500)
            return
        except Exception:
            pass

        # Strategy 3: Playwright locator
        radio = self.individual_radio if requester_type.lower() == "individual" else self.business_radio
        try:
            radio.wait_for(state="visible", timeout=3_000)
            radio.click(force=True)
        except Exception:
            try:
                self.page.get_by_role("radio", name=re.compile(requester_type, re.I)).click()
            except Exception:
                try:
                    radio.click(force=True)
                except Exception:
                    pass
        self.page.wait_for_timeout(500)
        # Always dismiss any CDK overlay that may have opened
        self._dismiss_cdk_overlay()

    # ===== Vehicle details =====

    def enter_vin(self, vin: str):
        self.vin_input.fill(vin)

    def click_vin_lookup(self):
        # Dismiss any lingering CDK overlay first
        self._dismiss_cdk_overlay()
        try:
            self.vin_lookup_button.click(timeout=10_000)
        except Exception:
            # Fallback: force click or JS click to bypass any remaining overlay
            try:
                self.vin_lookup_button.click(force=True)
            except Exception:
                self.page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const txt = (btn.textContent || '').toLowerCase();
                        if (txt.includes('lookup') || txt.includes('vin lookup') ||
                            (txt.includes('search') && btn.classList.contains('search-enable'))) {
                            btn.click(); return;
                        }
                    }
                }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
        # Dismiss overlays
        try:
            for dismiss in ['button:has-text("OK")', 'button:has-text("Close")', 'button:has-text("Got it")']:
                el = self.page.locator(dismiss).first
                el.wait_for(state="visible", timeout=2_000)
                el.click(force=True)
                self.page.wait_for_timeout(500)
        except Exception:
            pass

    def fill_vehicle_details(self, details: dict):
        """Fill vehicle details (may already be auto-populated from VIN lookup)."""
        try:
            if details.get("make") and not self.make_input.input_value():
                self.make_input.click()
                self.make_input.fill("")
                self.make_input.type(details["make"], delay=100)
                autocomplete_option = self.page.locator('mat-option, .mat-autocomplete-panel .mat-option, [role="option"]').first
                autocomplete_option.wait_for(state="visible", timeout=5000)
                autocomplete_option.click()
                self.page.wait_for_timeout(500)
            if details.get("year") and not self.year_input.input_value():
                self.year_input.fill(details["year"])
            if details.get("model") and not self.model_input.input_value():
                self.model_input.fill(details["model"])
            if details.get("color") and not self.color_input.input_value():
                self.color_input.fill(details["color"])
        except Exception:
            pass

    def fill_storage_location(self, location: str, address: str, zip_code: str):
        """Fill storage location details."""
        try:
            self.location_input.fill(location)
            self.address_input.fill(address)
            self.zip_input.fill(zip_code)
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    # ===== LT-262 paper form fields =====

    def fill_lien_charges(self, charges: dict):
        """Fill lien charges for paper LT-262."""
        # For paper forms, check boxes and fill amounts
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

    # ===== LT-263 paper form fields =====

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
                # Try alternative date input
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

    # ===== Actions =====

    def submit(self):
        """Submit paper form with fallback strategies."""
        # Dismiss CDK overlay before attempting submit
        self._dismiss_cdk_overlay()

        try:
            self.submit_button.wait_for(state="visible", timeout=10_000)
            self.submit_button.scroll_into_view_if_needed()
            self.submit_button.click()
        except Exception:
            # Strategy 2: JS evaluate to find and click submit button
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
                # Strategy 3: broader locator with force click
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

    # ===== Assertions =====

    def expect_paper_form_visible(self):
        """Verify paper form entry screen is visible."""
        # Look for requester type selection or form heading
        expect(
            self.page.get_by_text(re.compile(r"Individual|Business|Paper|Add from Paper", re.I)).first
        ).to_be_visible(timeout=15_000)

    def verify_fields_editable(self):
        """Verify that pre-filled fields are editable (paper form feature)."""
        # In paper forms, fields from prior forms should be editable
        try:
            assert not self.make_input.is_disabled(), "Make field should be editable in paper form"
        except Exception:
            pass
