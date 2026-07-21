"""
Staff Portal LT-261 Page — Sheriff/Inspector Standalone workflow.

LT-261 is a staff-only form for vehicles reported by law enforcement.
Flow:
  Listing → Add from Paper → Modal (VIN + E-Stop) → Form → Submit → Confirm → Listing

Waiting policy: this page object waits on observable conditions (overlay opened /
closed, dialog opened / closed, option list rendered, network settled, checkbox
actually checked) rather than fixed sleeps. Helpers prefixed `_wait_` encapsulate
those conditions; they swallow timeouts where the condition is a settle-hint
rather than a precondition required for correctness, so a missing spinner or an
already-closed overlay never fails a test on its own.
"""

import re
import time
from playwright.sync_api import Page, expect


class Lt261Page:
    # Overlay-hosted option list (mat-autocomplete / mat-select panels)
    _OVERLAY_OPTION = ".cdk-overlay-pane mat-option"
    _DIALOG = "mat-dialog-container"
    _BUSY = "mat-spinner, mat-progress-bar, .mat-progress-spinner, .mat-progress-bar"

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

    # ===== Wait helpers =====

    def _wait_options_visible(self, timeout: int = 15_000):
        """Wait for an autocomplete/select option panel to render."""
        self.page.locator(self._OVERLAY_OPTION).first.wait_for(state="visible", timeout=timeout)

    def _wait_options_closed(self, timeout: int = 8_000):
        """Wait for the option panel to close after a selection (settle-hint)."""
        try:
            self.page.locator(self._OVERLAY_OPTION).first.wait_for(state="hidden", timeout=timeout)
        except Exception:
            pass

    def _wait_dialog_visible(self, timeout: int = 15_000):
        self.page.locator(self._DIALOG).first.wait_for(state="visible", timeout=timeout)

    def _wait_dialog_closed(self, timeout: int = 15_000):
        """Wait for a dialog to dismiss (settle-hint — a dialog that legitimately
        stays open, e.g. an unexpected LT-265 popup, must be asserted by the caller)."""
        try:
            self.page.locator(self._DIALOG).first.wait_for(state="hidden", timeout=timeout)
        except Exception:
            pass

    def _wait_network_settled(self, timeout: int = 30_000):
        """Network quiet + no visible busy indicator."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        try:
            self.page.wait_for_function(
                f"() => !document.querySelector('{self._BUSY}')", timeout=8_000
            )
        except Exception:
            pass

    def _wait_form_loaded(self, timeout: int = 30_000):
        """The paper form is rendered once its Year input exists."""
        self.page.locator("//input[@name='year']").wait_for(state="visible", timeout=timeout)

    def _wait_no_backdrop(self, timeout: int = 5_000):
        try:
            self.page.wait_for_function(
                "() => document.querySelectorAll('.cdk-overlay-backdrop-showing').length === 0",
                timeout=timeout,
            )
        except Exception:
            pass

    # ===== Listing actions =====

    def _dismiss_cdk_overlay(self):
        try:
            self.page.evaluate("""() => {
                document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop'
                ).forEach(b => { b.click(); b.remove(); });
            }""")
        except Exception:
            pass
        try:
            self.page.keyboard.press("Escape")
        except Exception:
            pass
        self._wait_no_backdrop()

    def click_add_from_paper(self):
        """Click 'Add from Paper' button on the LT-261 listing page."""
        btn = self.page.locator('button:has-text("Add from Paper"), button:has-text("Add Paper")').first
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        self._wait_dialog_visible()

    def click_add_from_estop(self):
        """Click 'Add Paper E-Stop' button on the LT-261 listing page."""
        btn = self.page.locator('//span[contains(text(),"Add Paper E-Stop")]')
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        self._wait_dialog_visible()

    def fill_modal_vin_and_estop(self, vin: str):
        """In the Add from Paper modal: enter VIN, select E-Stop radio, click Next."""
        vin_input = self.page.locator('mat-dialog-container input[placeholder*="VIN" i], mat-dialog-container input[name*="vin" i]').first
        vin_input.wait_for(state="visible", timeout=10_000)
        vin_input.fill(vin)

        estop_radio = self.page.locator(
            'mat-dialog-container mat-radio-button:has-text("E-Stop"), '
            'mat-dialog-container label:has-text("E-Stop")'
        ).first
        estop_radio.wait_for(state="visible", timeout=10_000)
        estop_radio.click()

        next_btn = self.page.locator('mat-dialog-container button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()

        # Modal closes, then the paper form renders. Waiting only for the modal to
        # close returns while the form is still blank, so callers that immediately
        # look for a form control (e.g. click_cancel_button) time out.
        self._wait_dialog_closed()
        self._wait_form_loaded()
        self._wait_network_settled()

    def fill_modal_vin_next(self, vin: str):
        """In the Add from E-Stop modal: enter VIN and click Next (no radio selection)."""
        vin_input = self.page.locator('mat-dialog-container input[placeholder*="VIN" i], mat-dialog-container input[name*="vin" i]').first
        vin_input.wait_for(state="visible", timeout=10_000)
        vin_input.fill(vin)

        next_btn = self.page.locator('mat-dialog-container button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()

        # Modal closes, then the paper form renders — wait for both, not a fixed 3s.
        self._wait_dialog_closed()
        self._wait_form_loaded()
        self._wait_network_settled()

    def fill_make(self, make_text: str = "TOY"):
        """Type in the Make autocomplete field and select the first suggestion."""
        make_input = self.page.locator("(//input[@role='combobox'])[2]")
        make_input.wait_for(state="visible", timeout=15_000)
        make_input.click()
        make_input.fill(make_text)

        # Wait for the suggestion list instead of guessing how long lookup takes.
        self._wait_options_visible()
        option = self.page.locator(self._OVERLAY_OPTION).first
        option.click()
        self._wait_options_closed()

    def fill_year(self, year: str):
        """Fill the Year field."""
        year_input = self.page.locator("//input[@name='year']")
        year_input.wait_for(state="visible", timeout=10_000)
        year_input.fill(year)

    def fill_search_location(self, search_text: str = "pen"):
        """Type in SEARCH LOCATION field and pick the first suggestion."""
        location_input = self.page.locator('input[placeholder*="Search Garage Name or Address" i]').first
        location_input.wait_for(state="visible", timeout=10_000)
        location_input.click()
        location_input.fill(search_text)

        # Typeahead hits the network — wait for the option panel, not a fixed 2s.
        suggestion = self.page.locator(
            '.cdk-overlay-pane mat-option, mat-autocomplete mat-option'
        ).first
        suggestion.wait_for(state="visible", timeout=20_000)
        suggestion.click()
        self._wait_options_closed()

    def _use_same_address_checkboxes(self):
        return self.page.locator('mat-checkbox:has-text("USE SAME ADDRESS AS PLACE STORED")')

    def _check_use_same_address(self, index: int):
        """Check the nth 'USE SAME ADDRESS AS PLACE STORED' checkbox if not already checked.

        No-op when the form auto-checks it (DWI). Waits for the input to actually
        report checked rather than sleeping after the click.
        """
        cbs = self._use_same_address_checkboxes()
        cbs.first.wait_for(state="visible", timeout=10_000)
        cb = cbs.nth(index) if cbs.count() > index else cbs.first
        inner = cb.locator("input")
        if not inner.is_checked():
            cb.click()
            expect(inner).to_be_checked(timeout=5_000)

    def check_use_same_address_storage(self):
        """Check 'USE SAME ADDRESS AS PLACE STORED' checkbox in the right panel (location section)."""
        self._check_use_same_address(0)

    def fill_sale_date(self, date_str: str):
        """Fill the Sale Date field (MM/DD/YYYY)."""
        date_input = self.page.locator(
            'input[aria-label*="Sale Date" i], input[placeholder*="Sale Date" i], '
            'input[placeholder*="MM/DD/YYYY"]'
        ).first
        date_input.wait_for(state="visible", timeout=10_000)
        date_input.fill(date_str)
        self.page.keyboard.press("Tab")

    def select_notice_of_sale_reason(self):
        """Select the first option from 'Notice of Sale for Other Reasons' dropdown."""
        dropdown = self.page.locator(
            'mat-select[aria-label*="Notice of Sale" i], '
            'mat-select[aria-label*="Other Reasons" i]'
        ).first
        dropdown.wait_for(state="visible", timeout=10_000)
        dropdown.click()

        self._wait_options_visible()
        self.page.locator("mat-option").first.click()
        self._wait_options_closed()

    def check_agency_use_same_address(self):
        """Check 'USE SAME ADDRESS AS PLACE STORED' under Agency/Department section."""
        self._check_use_same_address(1)

    def fill_agency_name(self, name: str):
        """Fill the NAME field under 'Name and Address of Agency or Department Selling Vehicle'."""
        name_input = self.page.locator(
            "input[placeholder='NAME'], input[aria-label='NAME'], "
            "input[placeholder='Name'], input[aria-label='Name']"
        ).first
        name_input.wait_for(state="visible", timeout=10_000)
        name_input.fill(name)

    def _select_stolen(self, value: str):
        stolen_dropdown = self.page.locator(
            'mat-select[aria-label*="Stolen" i], mat-select[name*="stolen" i]'
        ).first
        stolen_dropdown.wait_for(state="visible", timeout=10_000)
        stolen_dropdown.click()

        self._wait_options_visible()
        option = self.page.locator(f'mat-option:has-text("{value}")').first
        option.wait_for(state="visible", timeout=10_000)
        # dispatch_event bypasses the overlay intercepting the click (pre-existing behaviour)
        option.dispatch_event("click")
        self._wait_options_closed()

    def select_stolen_no(self):
        """Select 'No' from the Stolen dropdown."""
        self._select_stolen("No")

    def select_stolen_yes(self):
        """Select 'Yes' from the Stolen dropdown (NCNSS-27067375)."""
        self._select_stolen("Yes")

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

        # Confirmation modal → Yes (if one appears)
        try:
            yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=8_000)
            yes_btn.click()
        except Exception:
            pass

        # NOTE: _wait_dialog_closed() is a settle-hint and deliberately swallows a
        # timeout — if a defect leaves an LT-265 popup open, expect_no_lt265_issue_popup()
        # must be the thing that reports it, not an incidental wait failure here.
        self._wait_dialog_closed()
        self._wait_network_settled()

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
        """Assert a VIN IS present in the current listing (record was saved, not lost).

        A just-submitted LT-261 is not immediately queryable (~5s of backend lag on
        QA), so the search is retried against a deadline rather than run once. Without
        this, a fast test outruns the backend and mis-reports the lag as the
        NCNSS-27067375 "record vanished" defect.
        """
        try:
            wait_for_vin_in_listing(self.page, self.search_by_vin, vin, "LT-261")
        except AssertionError:
            raise AssertionError(
                f"EXPECTED: VIN {vin} present in the LT-261 listing (record saved, not lost) | "
                f"ACTUAL: 0 rows — the record vanished from the listing (the NCNSS-27067375 defect)"
            ) from None

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

        # Confirmation modal → Yes
        yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
        yes_btn.wait_for(state="visible", timeout=15_000)
        yes_btn.click()
        self._wait_dialog_closed()

        # Verify green success banner (may auto-dismiss quickly — soft check)
        try:
            success = self.page.get_by_text(re.compile(r"success", re.I)).first
            expect(success).to_be_visible(timeout=5_000)
        except Exception:
            pass  # Banner may have already dismissed before check

        # Wait for redirect back to the listing
        self._wait_network_settled()
        try:
            self.to_process_tab.wait_for(state="visible", timeout=15_000)
        except Exception:
            pass

    # ===== Listing navigation =====

    def _wait_listing_settled(self):
        self._wait_network_settled()
        # Either rows rendered or an explicit empty state — whichever the app shows.
        try:
            self.page.wait_for_function(
                """() => {
                    const rows = document.querySelectorAll(
                        'table.mat-table tr.mat-row, table tbody tr'
                    ).length;
                    const empty = /no .*(record|result|data)/i.test(document.body.innerText || '');
                    return rows > 0 || empty;
                }""",
                timeout=15_000,
            )
        except Exception:
            pass

    def click_to_process_tab(self):
        self.to_process_tab.click()
        self._wait_listing_settled()

    def click_processed_tab(self):
        self.processed_tab.click()
        self._wait_listing_settled()

    def search_by_vin(self, vin: str):
        self._dismiss_cdk_overlay()

        # Try column filter (Show Filters pattern used elsewhere)
        show_filters_btn = self.page.locator('button:has-text("Show Filters")').first
        try:
            show_filters_btn.wait_for(state="visible", timeout=5_000)
            show_filters_btn.click()
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

        # Wait for the filtered result set. networkidle fires ~0.8s BEFORE the table
        # re-renders, and the table passes through a transient 0-row state while it
        # repaints — so an empty table is NOT a valid "settled" signal. Wait instead
        # for a positive outcome either way: a row containing the VIN, or the app's
        # explicit "No Records Found" empty state. Callers assert both directions.
        self._wait_network_settled()
        try:
            self.page.wait_for_function(
                """(vin) => {
                    if (/no records found/i.test(document.body.innerText || '')) return true;
                    const rows = Array.from(document.querySelectorAll(
                        'table.mat-table tr.mat-row, table tbody tr'
                    ));
                    return rows.some(r => (r.innerText || '').toUpperCase().includes(vin.toUpperCase()));
                }""",
                arg=vin,
                timeout=20_000,
            )
        except Exception:
            pass

    def select_application(self, index: int = 0):
        self.vin_links.nth(index).click()
        self._wait_network_settled()
        # Detail page is up once the correspondence link or an action bar renders.
        try:
            self.page.locator(
                "//span[contains(text(),'View Correspondence/Documents')] | //button[contains(.,'Cancel')]"
            ).first.wait_for(state="visible", timeout=15_000)
        except Exception:
            pass

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
        try:
            self._wait_dialog_visible(timeout=10_000)
        except Exception:
            pass

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
        self._wait_dialog_closed()
        self._wait_network_settled()

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
        self._wait_dialog_closed(timeout=8_000)

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
        self._wait_dialog_visible()

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

    # ========================================================================
    # DWI paper form + Stolen listing + owner details  (E2E-004 four-phase)
    #
    # Verified against the live QA app rather than inferred:
    #   * "Add Paper DWI" sits beside "Add Paper E-Stop" on the LT-261 listing and
    #     opens the SAME modal (single "Enter VIN" input + Next, no radio). The form
    #     type is carried in the URL: ?paperFormType=DWI vs ?paperFormType=E-Stop.
    #   * The LT-261 listing has a "Stolen" tab (To Process, Processed, Rejected,
    #     Stolen, Draft Paper Forms, Closed, All), rendered at the same /LT-261/list
    #     URL with the same "Show Filters" + VIN column, so search_by_vin() works there.
    #   * There are TWO "USE SAME ADDRESS AS PLACE STORED" checkboxes (location panel
    #     and agency section). Both default checked on DWI, both unchecked on E-Stop.
    #   * Owner details: a top-level `owner_name` input is always present; the
    #     "Owner(s) Check" section's "+ Add Owner" appends `owner_<field>__id-N` inputs.
    # ========================================================================

    USE_SAME_ADDRESS_LABEL = "USE SAME ADDRESS AS PLACE STORED"

    _USE_SAME_ADDRESS_STATES_JS = """() => Array.from(document.querySelectorAll('mat-checkbox'))
        .filter(cb => /USE SAME ADDRESS AS PLACE STORED/i.test(cb.innerText || ''))
        .map(cb => { const i = cb.querySelector('input'); return i ? i.checked : null; })"""

    def _wait_listing_settled(self, timeout: int = 15_000):
        """Listing has painted: rows rendered, or the app's explicit empty state."""
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            pass
        try:
            self.page.wait_for_function(
                """() => {
                    const rows = document.querySelectorAll(
                        'table.mat-table tr.mat-row, table tbody tr'
                    ).length;
                    return rows > 0 || /no records found/i.test(document.body.innerText || '');
                }""",
                timeout=timeout,
            )
        except Exception:
            pass

    # ----- Entry points -----

    def click_add_from_dwi(self):
        """Click 'Add Paper DWI' button on the LT-261 listing page."""
        btn = self.page.locator('//span[contains(text(),"Add Paper DWI")]')
        btn.wait_for(state="visible", timeout=10_000)
        btn.click()
        self._wait_dialog_visible()

    def open_paper_form(self, form_type: str, vin: str):
        """Open the LT-261 paper form of `form_type` ('E-Stop' or 'DWI') for `vin`."""
        if form_type == "DWI":
            self.click_add_from_dwi()
        elif form_type == "E-Stop":
            self.click_add_from_estop()
        else:
            raise ValueError(f"form_type must be 'E-Stop' or 'DWI', got {form_type!r}")
        self.fill_modal_vin_next(vin)

    def expect_form_type(self, form_type: str):
        """Assert the loaded paper form is the requested type (URL carries paperFormType).

        Without this, a broken 'Add Paper DWI' button would silently open an E-Stop
        form and the DWI phase would pass as a duplicate of the E-Stop phase.
        """
        url = self.page.url
        assert f"paperFormType={form_type}" in url, (
            f"EXPECTED: LT-261 paper form of type {form_type} | "
            f"ACTUAL: URL does not carry paperFormType={form_type} -> {url}"
        )

    # ----- "USE SAME ADDRESS AS PLACE STORED" defaults -----

    def use_same_address_states(self) -> list:
        """Checked-state of every 'USE SAME ADDRESS AS PLACE STORED' checkbox, in DOM order."""
        return self.page.evaluate(self._USE_SAME_ADDRESS_STATES_JS)

    def expect_use_same_address_default(self, form_type: str):
        """Assert the DEFAULT checked-state of both 'use same address' checkboxes.

        DWI    -> auto-checked by default
        E-Stop -> NOT auto-checked by default

        Must be called immediately after the form loads, before any checkbox is touched.
        """
        should_be_checked = form_type == "DWI"
        self.page.locator(
            f'mat-checkbox:has-text("{self.USE_SAME_ADDRESS_LABEL}")'
        ).first.wait_for(state="visible", timeout=15_000)
        states = self.use_same_address_states()

        assert states, (
            f"EXPECTED: at least one '{self.USE_SAME_ADDRESS_LABEL}' checkbox on the "
            f"{form_type} form | ACTUAL: none found"
        )
        assert all(s is should_be_checked for s in states), (
            f"EXPECTED: '{self.USE_SAME_ADDRESS_LABEL}' default checked={should_be_checked} "
            f"on a {form_type} form (DWI auto-checks, E-Stop does not) | "
            f"ACTUAL: checkbox states={states}"
        )

    # ----- Owner details -----

    def fill_owner_seized_from(self, name: str):
        """Fill the top-level 'NAME OF OWNER FROM WHOM THE VEHICLE WAS SEIZED' field."""
        owner = self.page.locator('input[name="owner_name"]').first
        owner.wait_for(state="visible", timeout=10_000)
        owner.scroll_into_view_if_needed()
        owner.fill(name)

    def add_owner_details(
        self,
        name: str,
        address: str = "100 Main St",
        address2: str = "Suite 100",
        zip_code: str = "27601",
        city: str = "Raleigh",
    ):
        """Click '+ Add Owner' in the Owner(s) Check section and fill the new owner row."""
        add_btn = self.page.locator('//span[contains(text(),"+ Add Owner")]').first
        add_btn.wait_for(state="visible", timeout=10_000)
        add_btn.scroll_into_view_if_needed()
        add_btn.click()

        # The appended owner row is ready once its name input renders.
        self.page.locator('input[name^="owner_name__"]').last.wait_for(
            state="visible", timeout=15_000
        )

        def _fill(selector: str, value: str, required: bool = True):
            field = self.page.locator(selector).last
            try:
                field.wait_for(state="visible", timeout=5_000)
            except Exception:
                if required:
                    raise
                return
            field.scroll_into_view_if_needed()
            field.fill(value)

        _fill('input[name^="owner_name__"]', name)
        _fill('input[name^="owner_address__"]', address)
        _fill('input[name^="owner_address2__"]', address2, required=False)
        _fill('input[name^="owner_zip__"]', zip_code)

        # City may auto-populate from ZIP (async lookup) — only fill if still empty.
        city_field = self.page.locator('input[name^="owner_city__"]').last
        try:
            city_field.wait_for(state="visible", timeout=5_000)
            try:
                self.page.wait_for_function(
                    """() => {
                        const els = document.querySelectorAll('input[name^="owner_city__"]');
                        const el = els[els.length - 1];
                        return el && el.value.trim().length > 0;
                    }""",
                    timeout=3_000,
                )
            except Exception:
                pass
            if not (city_field.input_value() or "").strip():
                city_field.fill(city)
        except Exception:
            pass

    # ----- Stolen listing -----

    @property
    def stolen_tab(self):
        return self.page.locator('[role="tab"]:has-text("Stolen")').first

    def click_stolen_tab(self):
        """Switch the LT-261 listing to the Stolen tab."""
        self._dismiss_cdk_overlay()
        self.stolen_tab.wait_for(state="visible", timeout=15_000)
        self.stolen_tab.click()
        self._wait_listing_settled()

    def expect_vin_in_stolen_listing(self, vin: str) -> float:
        """Assert `vin` appears in the LT-261 Stolen listing. Returns seconds waited."""
        self.click_stolen_tab()
        waited = wait_for_vin_in_listing(self.page, self.search_by_vin, vin, "LT-261 Stolen")
        expect(
            self.page.get_by_text(re.compile(re.escape(vin), re.I)).first
        ).to_be_visible(timeout=10_000)
        return waited


# ============================================================================
# Listing-appearance polling
# ============================================================================

_VIN_IN_TABLE_JS = """(vin) => Array.from(document.querySelectorAll(
    'table.mat-table tr.mat-row, table tbody tr'
)).some(r => (r.innerText || '').toUpperCase().includes(vin.toUpperCase()))"""


def vin_row_present(page: Page, vin: str) -> bool:
    """True when a table row on the current listing contains `vin`."""
    return bool(page.evaluate(_VIN_IN_TABLE_JS, vin))


def wait_for_vin_in_listing(
    page: Page,
    search_fn,
    vin: str,
    listing: str,
    timeout_s: int = 90,
    poll_ms: int = 2_000,
) -> float:
    """Poll `listing` (re-running `search_fn(vin)`) until `vin` appears. Returns seconds waited.

    A freshly submitted LT-261 is NOT immediately queryable — measured against QA, the
    record takes ~7-8s to reach the LT-261 Processed/Stolen listings and ~4-5s to reach
    Sold. That is backend lag, not a rendering delay, so no per-action wait covers it:
    the search itself must be retried until the record materialises.

    Bounded by `timeout_s` so a record that never appears fails loudly rather than
    hanging. `poll_ms` is a retry interval between backend queries, not a blind sleep.
    """
    started = time.monotonic()
    deadline = started + timeout_s
    attempts = 0
    while True:
        attempts += 1
        search_fn(vin)
        if vin_row_present(page, vin):
            return time.monotonic() - started
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"EXPECTED: VIN {vin} to appear in the {listing} listing within {timeout_s}s | "
                f"ACTUAL: not found after {attempts} searches over "
                f"{time.monotonic() - started:.1f}s"
            )
        page.wait_for_timeout(poll_ms)
