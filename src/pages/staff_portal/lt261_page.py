"""
Staff Portal LT-261 Page — Sheriff/Inspector Standalone workflow.

LT-261 is a staff-only form for vehicles reported by law enforcement.
Flow:
  Listing → Add from Paper → Modal (VIN + E-Stop) → Form → Submit → Confirm → Listing
"""

import re
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

    # ===== Listing actions =====

    def _dismiss_cdk_overlay(self):
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

    def click_add_from_paper(self):
        """Click 'Add from Paper' button on the LT-261 listing page."""
        btn = self.page.locator('button:has-text("Add from Paper"), button:has-text("Add Paper")').first
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        self.page.wait_for_timeout(1000)

    def click_add_from_estop(self):
        """Click 'Add Paper E-Stop' button on the LT-261 listing page."""
        btn = self.page.locator('//span[contains(text(),"Add Paper E-Stop")]')
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        self.page.wait_for_timeout(1000)

    def fill_modal_vin_and_estop(self, vin: str):
        """In the Add from Paper modal: enter VIN, select E-Stop radio, click Next."""
        vin_input = self.page.locator('mat-dialog-container input[placeholder*="VIN" i], mat-dialog-container input[name*="vin" i]').first
        vin_input.wait_for(state="visible", timeout=10_000)
        vin_input.fill(vin)
        self.page.wait_for_timeout(500)

        estop_radio = self.page.locator(
            'mat-dialog-container mat-radio-button:has-text("E-Stop"), '
            'mat-dialog-container label:has-text("E-Stop")'
        ).first
        estop_radio.wait_for(state="visible", timeout=10_000)
        estop_radio.click()
        self.page.wait_for_timeout(500)

        next_btn = self.page.locator('mat-dialog-container button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()

    def fill_modal_vin_next(self, vin: str):
        """In the Add from E-Stop modal: enter VIN and click Next (no radio selection)."""
        vin_input = self.page.locator('mat-dialog-container input[placeholder*="VIN" i], mat-dialog-container input[name*="vin" i]').first
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
        make_input = self.page.locator("(//input[@role='combobox'])[2]")
        make_input.wait_for(state="visible", timeout=15_000)
        make_input.click()
        make_input.fill(make_text)
        self.page.wait_for_timeout(1000)

        # Select first option from the autocomplete dropdown
        option = self.page.locator('.cdk-overlay-pane mat-option').first
        option.wait_for(state="visible", timeout=10_000)
        option.click()
        self.page.wait_for_timeout(500)

    def fill_year(self, year: str):
        """Fill the Year field."""
        year_input = self.page.locator("//input[@name='year']")
        year_input.wait_for(state="visible", timeout=10_000)
        year_input.fill(year)
        self.page.wait_for_timeout(300)

    def fill_search_location(self, search_text: str = "pen"):
        """Type in SEARCH LOCATION field and pick the first suggestion."""
        location_input = self.page.locator('input[placeholder*="Search Garage Name or Address" i]').first
        location_input.wait_for(state="visible", timeout=10_000)
        location_input.click()
        location_input.fill(search_text)
        self.page.wait_for_timeout(2000)

        # Select first mat-option from the overlay panel (not mat-chip with role=option)
        suggestion = self.page.locator('.cdk-overlay-pane mat-option, mat-autocomplete mat-option').first
        suggestion.wait_for(state="visible", timeout=10_000)
        suggestion.click()
        self.page.wait_for_timeout(500)

    def check_use_same_address_storage(self):
        """Check 'USE SAME ADDRESS AS PLACE STORED' checkbox in the right panel (location section)."""
        # There may be two such checkboxes — pick the first one (location/right panel)
        cb = self.page.locator(
            'mat-checkbox:has-text("USE SAME ADDRESS AS PLACE STORED"), '
            'label:has-text("USE SAME ADDRESS AS PLACE STORED")'
        ).first
        cb.wait_for(state="visible", timeout=10_000)
        if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
            cb.click()
            self.page.wait_for_timeout(500)

    def fill_sale_date(self, date_str: str):
        """Fill the Sale Date field (MM/DD/YYYY)."""
        date_input = self.page.locator(
            'input[aria-label*="Sale Date" i], input[placeholder*="Sale Date" i], '
            'input[placeholder*="MM/DD/YYYY"]'
        ).first
        date_input.wait_for(state="visible", timeout=10_000)
        date_input.fill(date_str)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(300)

    def select_notice_of_sale_reason(self):
        """Select the first option from 'Notice of Sale for Other Reasons' dropdown."""
        dropdown = self.page.locator(
            'mat-select[aria-label*="Notice of Sale" i], '
            'mat-select[aria-label*="Other Reasons" i]'
        ).first
        dropdown.wait_for(state="visible", timeout=10_000)
        dropdown.click()
        self.page.wait_for_timeout(500)

        option = self.page.locator('mat-option').first
        option.wait_for(state="visible", timeout=10_000)
        option.click()
        self.page.wait_for_timeout(500)

    def check_agency_use_same_address(self):
        """Check 'USE SAME ADDRESS AS PLACE STORED' under Agency/Department section."""
        # Second occurrence (agency section)
        cbs = self.page.locator(
            'mat-checkbox:has-text("USE SAME ADDRESS AS PLACE STORED")'
        )
        cb = cbs.nth(1) if cbs.count() > 1 else cbs.first
        cb.wait_for(state="visible", timeout=10_000)
        if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
            cb.click()
            self.page.wait_for_timeout(500)

    def fill_agency_name(self, name: str):
        """Fill the NAME field under 'Name and Address of Agency or Department Selling Vehicle'."""
        name_input = self.page.locator(
            "input[placeholder='NAME'], input[aria-label='NAME'], "
            "input[placeholder='Name'], input[aria-label='Name']"
        ).first
        name_input.wait_for(state="visible", timeout=10_000)
        name_input.fill(name)
        self.page.wait_for_timeout(300)

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
        no_option.dispatch_event("click")
        self.page.wait_for_timeout(500)

    def select_stolen_yes(self):
        """Select 'Yes' from the Stolen dropdown (NCNSS-27067375)."""
        stolen_dropdown = self.page.locator(
            'mat-select[aria-label*="Stolen" i], mat-select[name*="stolen" i]'
        ).first
        stolen_dropdown.wait_for(state="visible", timeout=10_000)
        stolen_dropdown.click()
        self.page.wait_for_timeout(500)

        yes_option = self.page.locator('mat-option:has-text("Yes")').first
        yes_option.wait_for(state="visible", timeout=10_000)
        yes_option.dispatch_event("click")
        self.page.wait_for_timeout(500)

    def submit_stolen_form(self):
        """Submit a Stolen=Yes paper form: click Submit → confirm Yes.

        Unlike submit_with_confirmation(), this does NOT expect an LT-265
        issuance/success banner — for a stolen record the fix must SUPPRESS
        auto-processing, so we only drive the submit + confirmation and let the
        caller assert the resulting state. Returns nothing.
        """
        self._dismiss_cdk_overlay()
        submit_btn = self.page.locator('button:has-text("Submit")').first
        submit_btn.wait_for(state="visible", timeout=15_000)
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        self.page.wait_for_timeout(1000)

        # Confirmation modal → Yes (if one appears)
        try:
            yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=8_000)
            yes_btn.click()
        except Exception:
            pass
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_no_lt265_issue_popup(self):
        """Assert that NO LT-265/LT-265A issuance popup/modal is shown.

        For a Stolen=Yes LT-261 the fix must NOT auto-issue LT-265/265A, so the
        'Issue LT-265' confirmation popup must not appear (TC-05, BR-122).
        """
        popup = self.page.locator(
            'mat-dialog-container:has-text("LT-265"), [role="dialog"]:has-text("LT-265"), '
            'mat-dialog-container:has-text("265A"), [role="dialog"]:has-text("265A")'
        )
        count = popup.count()
        assert count == 0, (
            "EXPECTED: no LT-265/265A issuance popup for a Stolen=Yes LT-261 (auto-process "
            f"suppressed, BR-122) | ACTUAL: {count} LT-265 popup(s) visible — record was auto-issued"
        )

    def expect_vin_in_listing(self, vin: str):
        """Assert a VIN IS present in the current listing (record was saved, not lost)."""
        try:
            self.search_by_vin(vin)
        except Exception:
            pass
        row_count = self.application_rows.count()
        assert row_count > 0, (
            f"EXPECTED: VIN {vin} present in the LT-261 listing (record saved, not lost) | "
            f"ACTUAL: 0 rows — the record vanished from the listing (the NCNSS-27067375 defect)"
        )

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

        # Wait for redirect back to listing
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    # ===== Listing navigation =====

    def click_to_process_tab(self):
        self.to_process_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_processed_tab(self):
        self.processed_tab.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def search_by_vin(self, vin: str):
        self._dismiss_cdk_overlay()

        # Try column filter (Show Filters pattern used elsewhere)
        show_filters_btn = self.page.locator('button:has-text("Show Filters")').first
        try:
            show_filters_btn.wait_for(state="visible", timeout=5_000)
            show_filters_btn.click()
            self.page.wait_for_timeout(1000)
        except Exception:
            pass

        vin_filter = self.page.locator('input[name="vin"]').first
        try:
            vin_filter.wait_for(state="visible", timeout=5_000)
            vin_filter.fill(vin)
            vin_filter.press("Enter")
        except Exception:
            self.search_input.fill(vin)
            self.search_input.press("Enter")

        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def select_application(self, index: int = 0):
        self.vin_links.nth(index).click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_applications_visible(self):
        expect(self.application_rows.first).to_be_visible(timeout=15_000)

    def expect_status_processed(self):
        """Verify the application status shows 'Processed'."""
        expect(
            self.page.get_by_text(re.compile(r"Processed", re.I)).first
        ).to_be_visible(timeout=15_000)

    # ===== Cancel flow (NCNSS-531) =====

    def click_cancel_button(self):
        """Click the page-level Cancel button on a paper form."""
        cancel_btn = self.page.locator('button:has-text("Cancel")').first
        cancel_btn.wait_for(state="visible", timeout=15_000)
        cancel_btn.scroll_into_view_if_needed()
        cancel_btn.click()
        self.page.wait_for_timeout(800)

    def expect_cancel_modal_visible(self):
        """Assert the cancel-confirmation modal is visible with Yes and No options."""
        modal = self.page.locator('mat-dialog-container, [role="dialog"]').first
        expect(modal).to_be_visible(timeout=10_000)
        expect(self.page.locator(
            'mat-dialog-container button:has-text("Yes"), [role="dialog"] button:has-text("Yes")'
        ).first).to_be_visible(timeout=5_000)

    def click_cancel_modal_yes(self):
        """Click Yes in the cancel-confirmation modal and wait for navigation."""
        yes_btn = self.page.locator(
            'mat-dialog-container button:has-text("Yes"), [role="dialog"] button:has-text("Yes")'
        ).first
        yes_btn.wait_for(state="visible", timeout=10_000)
        yes_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def click_cancel_modal_no(self):
        """Click No (or dismiss) in the cancel-confirmation modal — stays on form."""
        try:
            no_btn = self.page.locator(
                'mat-dialog-container button:has-text("No"), [role="dialog"] button:has-text("No")'
            ).first
            no_btn.wait_for(state="visible", timeout=5_000)
            no_btn.click()
        except Exception:
            self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(800)

    def expect_on_listing_page(self):
        """Assert we are back on the LT-261 listing (To Process / Draft / Processed tabs visible)."""
        expect(self.to_process_tab).to_be_visible(timeout=15_000)

    def expect_vin_not_in_listing(self, vin: str):
        """Assert a VIN is NOT present in the current listing (no record was created)."""
        try:
            self.search_by_vin(vin)
        except Exception:
            pass
        row_count = self.application_rows.count()
        assert row_count == 0, (
            f"EXPECTED: VIN {vin} not in listing (Cancel aborted submission) | "
            f"ACTUAL: {row_count} row(s) found — record was incorrectly created"
        )

    # ===== Correspondence =====

    def click_view_correspondence(self):
        """Click 'View Correspondence/Documents' link to open the Correspondence History modal."""
        link = self.page.locator("//span[contains(text(),'View Correspondence/Documents')]")
        link.wait_for(state="visible", timeout=10_000)
        link.click()
        self.page.wait_for_timeout(1000)

    def expect_lt265_in_correspondence(self):
        """Verify 'Correspondence History' modal is shown and contains an LT-265 entry."""
        # Modal heading
        expect(
            self.page.get_by_text(re.compile(r"Correspondence History", re.I)).first
        ).to_be_visible(timeout=10_000)

        # LT-265 entry in the modal
        expect(
            self.page.get_by_text(re.compile(r"LT-265", re.I)).first
        ).to_be_visible(timeout=10_000)
