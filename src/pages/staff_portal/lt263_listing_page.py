import re
from playwright.sync_api import Page, expect


class Lt263ListingPage:
    """Staff Portal LT-263 listing and detail page.

    Listing tabs: To Process | Processed (Sold) | Rejected | Draft Paper Forms | Closed | All
    Detail page sections: Description Of Vehicle, Vehicle Sale Information, Lien Information
    Detail page buttons: Close File, Reject, Edit, Generate LT-265, Back
    """

    def __init__(self, page: Page):
        self.page = page

        # Listing tabs
        self.to_process_tab = page.locator('[role="tab"]:has-text("To Process")')
        self.processed_sold_tab = page.locator(
            '[role="tab"]:has-text("Processed (Sold)"), '
            '[role="tab"]:has-text("Processed"), [role="tab"]:has-text("Sold")'
        ).first
        self.rejected_tab = page.locator('[role="tab"]:has-text("Rejected")')
        self.closed_tab = page.locator('[role="tab"]:has-text("Closed")')
        self.all_tab = page.locator('[role="tab"]:has-text("All")')

        # Table
        self.application_rows = page.locator("table.mat-table tr.mat-row, table tbody tr")
        self.vin_links = page.locator("span.table-link, table a, table td a")
        self.search_input = page.locator(
            'input[placeholder*="Search using VIN"], input[placeholder*="Search" i], input[placeholder*="VIN" i]'
        ).first

        # Detail page buttons
        self.generate_lt265_button = page.locator('button:has-text("Generate LT-265")').first
        self.close_file_button = page.locator('button:has-text("Close File")').first
        self.reject_button = page.locator('button:has-text("Reject")').first
        self.edit_button = page.locator('button:has-text("Edit")').first
        self.back_button = page.locator('button:has-text("Back")').first

    # ===== Listing tab navigation =====

    def click_to_process_tab(self):
        self.to_process_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def _click_tab(self, tab_locator, tab_text: str):
        """Click a tab with CDK overlay dismissal and JS fallback."""
        self._dismiss_cdk_overlay()
        try:
            tab_locator.click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            try:
                tab_locator.dispatch_event("click")
            except Exception:
                self.page.evaluate(f"""() => {{
                    const tabs = document.querySelectorAll('[role="tab"]');
                    for (const tab of tabs) {{
                        if (tab.textContent.toLowerCase().includes('{tab_text.lower()}')) {{
                            tab.click();
                            return;
                        }}
                    }}
                }}""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_processed_sold_tab(self):
        self._click_tab(self.processed_sold_tab, "Processed")

    def click_all_tab(self):
        self._click_tab(self.all_tab, "All")

    # ===== Application selection =====

    def select_application(self, index: int = 0):
        self._dismiss_cdk_overlay()
        try:
            self.vin_links.nth(index).click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            self.vin_links.nth(index).click(force=True)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_applications_visible(self):
        expect(self.application_rows.first).to_be_visible(timeout=15_000)

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

    def _js_search(self, vin: str):
        """Trigger search via JS — sets input value and dispatches Angular events."""
        self.page.evaluate(f"""(vin) => {{
            const input = document.querySelector(
                'input[placeholder*="Search using VIN"], input[placeholder*="Search"]'
            );
            if (!input) return;
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(input, '');
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            nativeInputValueSetter.call(input, vin);
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            input.dispatchEvent(new KeyboardEvent('keyup', {{key: 'Enter', keyCode: 13, bubbles: true}}));
            input.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', keyCode: 13, bubbles: true}}));
        }}""", vin)
        self.page.wait_for_timeout(2000)

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

                # Retry 2: JS-based Angular event dispatch
                first_row = self.application_rows.first.text_content() or ""
                if vin not in first_row:
                    self._js_search(vin)
        except Exception:
            pass

    # ===== Detail page assertions =====

    def verify_sale_details_visible(self):
        """Verify 'Vehicle Sale Information' section is visible on detail page."""
        expect(
            self.page.get_by_text(re.compile(r"Vehicle Sale Information|TYPE OF SALE", re.I)).first
        ).to_be_visible(timeout=15_000)

    def verify_lien_amount_visible(self):
        """Verify lien amount is displayed on detail page."""
        expect(
            self.page.get_by_text(re.compile(r"LIEN AMOUNT", re.I)).first
        ).to_be_visible(timeout=10_000)

    def verify_vehicle_description_visible(self):
        """Verify 'Description Of Vehicle' section is visible."""
        expect(
            self.page.get_by_text(re.compile(r"Description Of Vehicle", re.I)).first
        ).to_be_visible(timeout=15_000)

    # ===== Actions =====

    def generate_lt265(self):
        """Click 'Generate LT-265' button on the detail page."""
        self._dismiss_cdk_overlay()
        expect(self.generate_lt265_button).to_be_visible(timeout=10_000)
        try:
            self.generate_lt265_button.click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            self.generate_lt265_button.click(force=True)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def verify_vehicle_sold(self):
        """Verify application shows sold/processed status."""
        expect(
            self.page.get_by_text(re.compile(r"Sold|Processed", re.I)).first
        ).to_be_visible(timeout=15_000)

    def click_closed_tab(self):
        self._click_tab(self.closed_tab, "Closed")

    def click_add_from_paper(self):
        """Click 'Add from Paper' button on the listing page."""
        self._dismiss_cdk_overlay()
        add_paper_btn = self.page.locator('button:has-text("Add from Paper"), button:has-text("Paper")').first
        expect(add_paper_btn).to_be_visible(timeout=10_000)
        try:
            add_paper_btn.click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            add_paper_btn.click(force=True)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def close_file(self, remarks: str = None):
        """Close file with remarks."""
        self._dismiss_cdk_overlay()
        self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        self.page.wait_for_timeout(500)
        try:
            self.close_file_button.wait_for(state="visible", timeout=5_000)
            self.close_file_button.scroll_into_view_if_needed()
            self.close_file_button.click()
        except Exception:
            self._dismiss_cdk_overlay()
            clicked = self.page.evaluate("""() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const txt = btn.textContent.toLowerCase().trim();
                    if (txt.includes('close file') || txt.includes('close case')) {
                        btn.scrollIntoView();
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")
            if not clicked:
                try:
                    self.close_file_button.click(force=True)
                except Exception:
                    self.close_file_button.dispatch_event("click")
        self.page.wait_for_timeout(1000)

        if remarks:
            remarks_input = self.page.locator(
                'textarea, input[placeholder*="remark" i], input[placeholder*="Remark" i]'
            ).first
            try:
                remarks_input.wait_for(state="visible", timeout=5_000)
                remarks_input.fill(remarks)
            except Exception:
                pass

        confirm_btn = self.page.locator(
            'mat-dialog-container button:has-text("Confirm"), '
            'mat-dialog-container button:has-text("Close"), '
            'mat-dialog-container button:has-text("Submit"), '
            'button:has-text("Confirm"), button:has-text("Submit")'
        ).last
        try:
            confirm_btn.wait_for(state="visible", timeout=5_000)
            confirm_btn.click()
        except Exception:
            pass
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
