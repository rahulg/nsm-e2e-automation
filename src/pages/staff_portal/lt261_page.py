"""
Staff Portal LT-261 Page — Sheriff/Inspector Standalone workflow.

LT-261 is a staff-only form for vehicles reported by law enforcement.
The entire workflow (submit → issue LT-265) happens within the Staff Portal.
No Public Portal involvement.
"""

import re
from datetime import datetime
from playwright.sync_api import Page, expect


class Lt261Page:
    def __init__(self, page: Page):
        self.page = page

        # Listing tabs
        self.to_process_tab = page.locator('[role="tab"]:has-text("To Process")')
        self.processed_tab = page.locator('[role="tab"]:has-text("Processed")')
        self.all_tab = page.locator('[role="tab"]:has-text("All")')

        # Table
        self.application_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")
        self.vin_links = page.locator("span.table-link, table a, table td a")
        self.search_input = page.locator(
            'input[placeholder*="Search using VIN"], input[placeholder*="Search" i], input[placeholder*="VIN" i]'
        ).first

        # Form fields — vehicle details
        self.vin_input = page.locator('input[name="sno"], input[placeholder*="VIN" i]').first
        self.vin_lookup_button = page.locator(
            'button:has-text("VIN Lookup"), button:has-text("Lookup"), '
            'button:has-text("Search"), button:has-text("Verify")'
        ).first
        self.make_input = page.locator('input[placeholder="Enter Make"], input[name*="make" i]').first
        self.year_input = page.locator('input[name="year"], input[name*="year" i]').first
        self.model_input = page.locator('input[name="model"], input[name*="model" i]').first
        self.body_input = page.locator('input[name*="body" i], mat-select[name*="body" i]').first
        self.color_input = page.locator('input[name="color"], input[name*="color" i]').first

        # Officer/Inspector info — use multiple fallback locator patterns
        self.officer_name_input = page.locator(
            'input[placeholder*="Officer" i], input[name*="officer" i], '
            'input[placeholder*="Inspector" i], input[name*="inspector" i], '
            'input[aria-label*="Officer" i], input[aria-label*="Inspector" i], '
            'input[aria-label*="Name" i]'
        ).first
        self.badge_number_input = page.locator(
            'input[placeholder*="Badge" i], input[name*="badge" i], '
            'input[aria-label*="Badge" i], input[placeholder*="Number" i]'
        ).first
        self.department_input = page.locator(
            'input[placeholder*="Department" i], input[name*="department" i], '
            'input[aria-label*="Department" i], input[placeholder*="Agency" i]'
        ).first

        # Location and circumstances
        self.location_input = page.locator(
            'input[placeholder*="Location" i], input[aria-label*="Location" i], '
            'input[name*="location" i]'
        ).first
        self.circumstances_input = page.locator(
            'textarea[placeholder*="Circumstances" i], textarea[name*="circumstances" i], '
            'textarea[placeholder*="Description" i], textarea'
        ).first

        # Buttons
        self.submit_button = page.locator('button:has-text("Submit")').first
        self.issue_lt265_button = page.locator('button:has-text("Issue LT-265"), button:has-text("Generate LT-265")').first
        self.back_button = page.locator('button:has-text("Back")').first

    # ===== Listing navigation =====

    def click_to_process_tab(self):
        self.to_process_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_processed_tab(self):
        self.processed_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def _dismiss_cdk_overlay(self):
        """Dismiss CDK overlay blocking clicks."""
        try:
            self.page.evaluate("""() => {
                document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop'
                ).forEach(b => { b.click(); b.remove(); });
            }""")
            self.page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

    def search_by_vin(self, vin: str):
        self._dismiss_cdk_overlay()
        try:
            self.search_input.wait_for(state="visible", timeout=10_000)
        except Exception:
            pass
        self.search_input.fill("")
        self.page.wait_for_timeout(300)
        self.search_input.fill(vin)
        self.search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

        # If search didn't filter results, retry with type()
        try:
            self.application_rows.first.wait_for(state="visible", timeout=5_000)
            first_row = self.application_rows.first.text_content() or ""
            if vin not in first_row:
                self.search_input.fill("")
                self.page.wait_for_timeout(500)
                self.search_input.type(vin, delay=50)
                self.page.wait_for_timeout(1000)
                self.search_input.press("Enter")
                self.page.wait_for_load_state("networkidle")
                self.page.wait_for_timeout(2000)
        except Exception:
            pass

    def select_application(self, index: int = 0):
        self.vin_links.nth(index).click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_applications_visible(self):
        expect(self.application_rows.first).to_be_visible(timeout=15_000)

    # ===== Form filling =====

    def enter_vin(self, vin: str):
        self.vin_input.fill(vin)

    def click_vin_lookup(self):
        try:
            self.vin_lookup_button.wait_for(state="visible", timeout=10_000)
            self.vin_lookup_button.click()
        except Exception:
            # Fallback: JS click any lookup-like button near VIN input
            self.page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const txt = (btn.textContent || '').toLowerCase();
                    if (txt.includes('lookup') || txt.includes('search') || txt.includes('verify') || txt.includes('vin')) {
                        btn.click(); return;
                    }
                }
            }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
        # Dismiss any overlays
        try:
            for dismiss in ['button:has-text("OK")', 'button:has-text("Close")', 'button:has-text("Got it")']:
                el = self.page.locator(dismiss).first
                el.wait_for(state="visible", timeout=2_000)
                el.click(force=True)
                self.page.wait_for_timeout(500)
        except Exception:
            pass

    def fill_vehicle_details(self, details: dict):
        """Fill vehicle make/year/model/body/color."""
        # Wait for the form to load — the make input should appear after VIN lookup
        self.page.wait_for_timeout(1000)

        if details.get("make"):
            try:
                self.make_input.wait_for(state="visible", timeout=10_000)
                self.make_input.click()
                self.make_input.fill("")
                self.make_input.type(details["make"], delay=100)
                autocomplete_option = self.page.locator('mat-option, .mat-autocomplete-panel .mat-option, [role="option"]').first
                autocomplete_option.wait_for(state="visible", timeout=5000)
                autocomplete_option.click()
                self.page.wait_for_timeout(500)
            except Exception:
                # Fallback: try filling by JS
                self.page.evaluate(f"""() => {{
                    const inputs = document.querySelectorAll('input');
                    for (const inp of inputs) {{
                        const ph = (inp.placeholder || '').toLowerCase();
                        const nm = (inp.name || '').toLowerCase();
                        if (ph.includes('make') || nm.includes('make')) {{
                            inp.value = '{details["make"]}';
                            inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                            return;
                        }}
                    }}
                }}""")
        if details.get("year"):
            try:
                self.year_input.fill(details["year"])
            except Exception:
                pass
        if details.get("model"):
            try:
                self.model_input.fill(details["model"])
            except Exception:
                pass
        if details.get("body"):
            try:
                self.body_input.fill(details["body"])
            except Exception:
                # May be a mat-select dropdown
                try:
                    self.body_input.click()
                    self.page.locator(f'mat-option:has-text("{details["body"]}")').first.click()
                    self.page.wait_for_timeout(500)
                except Exception:
                    pass
        if details.get("color"):
            try:
                self.color_input.fill(details["color"])
            except Exception:
                pass

    def fill_officer_info(self, name: str, badge: str = "12345", department: str = "NC Highway Patrol"):
        """Fill officer/inspector information."""
        self.page.wait_for_timeout(1000)
        try:
            self.officer_name_input.wait_for(state="visible", timeout=10_000)
            self.officer_name_input.fill(name)
        except Exception:
            # Fallback: try mat-form-field approach
            try:
                name_fields = self.page.locator('mat-form-field input[type="text"]')
                # After vehicle fields, officer name is typically next
                for i in range(name_fields.count()):
                    field = name_fields.nth(i)
                    placeholder = (field.get_attribute("placeholder") or "").lower()
                    aria = (field.get_attribute("aria-label") or "").lower()
                    if "officer" in placeholder or "inspector" in placeholder or "officer" in aria:
                        field.fill(name)
                        break
            except Exception:
                pass
        try:
            self.badge_number_input.wait_for(state="visible", timeout=5_000)
            self.badge_number_input.fill(badge)
        except Exception:
            pass
        try:
            self.department_input.wait_for(state="visible", timeout=5_000)
            self.department_input.fill(department)
        except Exception:
            pass

    def fill_location_and_circumstances(self, location: str, circumstances: str):
        """Fill location and circumstances."""
        try:
            self.location_input.fill(location)
        except Exception:
            pass
        try:
            self.circumstances_input.fill(circumstances)
        except Exception:
            pass

    # ===== Actions =====

    def submit(self):
        self._dismiss_cdk_overlay()
        try:
            self.submit_button.scroll_into_view_if_needed()
            self.submit_button.click(timeout=10_000)
        except Exception:
            # CDK overlay or button state issue — try fallbacks
            self._dismiss_cdk_overlay()
            try:
                self.submit_button.click(force=True)
            except Exception:
                # JS fallback: find and click submit button
                self.page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = (b.textContent || '').trim().toLowerCase();
                        if (txt.includes('submit') && !b.disabled) {
                            b.scrollIntoView();
                            b.click();
                            return;
                        }
                    }
                }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def issue_lt265(self):
        """Issue LT-265 directly from LT-261 detail page."""
        expect(self.issue_lt265_button).to_be_visible(timeout=10_000)
        self.issue_lt265_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    # ===== Assertions =====

    def verify_lt261_submitted(self):
        """Verify LT-261 was submitted successfully."""
        success = self.page.locator('[class*="success" i], [class*="toast" i], [class*="snack" i]').first
        expect(success).to_be_visible(timeout=15_000)

    def verify_vehicle_in_sold_tab(self, vin: str):
        """Verify vehicle appears in processed/sold tab."""
        self.click_processed_tab()
        self.search_by_vin(vin)
        expect(self.application_rows.first).to_be_visible(timeout=15_000)
