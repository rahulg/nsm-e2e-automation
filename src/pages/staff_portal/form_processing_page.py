import re
from playwright.sync_api import Page, expect


class FormProcessingPage:
    """Generic staff form processing page for LT-260 details."""

    def __init__(self, page: Page):
        self.page = page

        # Sections
        self.vehicle_details_section = page.get_by_text("Vehicle Details").first
        self.vehicle_storage_section = page.get_by_text("Vehicle Storage Details").first
        self.owners_check_section = page.get_by_text(re.compile(r"Owner.*Check", re.I)).first

        # Action buttons
        self.close_file_button = page.locator(
            'button:has-text("Close File"), button:has-text("Close Case"), '
            'button:has-text("Close")'
        ).first
        self.reject_button = page.locator('button:has-text("Reject")').first
        self.edit_button = page.locator('button:has-text("Edit")').first

    def expect_detail_page_visible(self):
        expect(self.vehicle_details_section).to_be_visible(timeout=15_000)

    def expect_owners_visible(self):
        expect(self.owners_check_section).to_be_visible(timeout=10_000)

    def click_edit(self):
        """Click Edit button on the detail page."""
        self.edit_button.wait_for(state="visible", timeout=10_000)
        self.edit_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def add_owner(self, name: str, address: str, zip_code: str,
                  address2: str = "Suite 100"):
        """Click +Add Owner, fill owner details."""
        add_owner_btn = self.page.get_by_text(re.compile(r"Add Owner", re.I)).first
        add_owner_btn.scroll_into_view_if_needed(timeout=10_000)
        add_owner_btn.click()
        self.page.wait_for_timeout(2000)

        # Owner fields use name pattern: owner_<field>__id-XXXX
        # Use aria-label to target the newly added owner fields
        owner_name = self.page.locator('input[name*="owner_name"]').last
        owner_name.scroll_into_view_if_needed(timeout=5_000)
        owner_name.click()
        owner_name.fill(name)
        self.page.wait_for_timeout(300)

        owner_addr = self.page.locator('input[name*="owner_address__"]').last
        owner_addr.click()
        owner_addr.fill(address)
        self.page.wait_for_timeout(300)

        owner_addr2 = self.page.locator('input[name*="owner_address2"]').last
        owner_addr2.click()
        owner_addr2.fill(address2)
        self.page.wait_for_timeout(300)

        owner_zip = self.page.locator('input[name*="owner_zip"]').last
        owner_zip.click()
        owner_zip.fill(zip_code)
        self.page.wait_for_timeout(500)

    def select_stolen_no(self):
        """Click STOLEN dropdown and select No."""
        stolen_dropdown = self.page.locator('mat-select[aria-label="Stolen"]')
        stolen_dropdown.scroll_into_view_if_needed(timeout=5_000)
        stolen_dropdown.click()
        self.page.wait_for_timeout(500)
        self.page.locator('mat-option:has-text("No")').first.click()
        self.page.wait_for_timeout(500)

    def select_stolen_yes(self):
        """Click STOLEN dropdown and select Yes."""
        stolen_dropdown = self.page.locator('mat-select[aria-label="Stolen"]')
        stolen_dropdown.scroll_into_view_if_needed(timeout=5_000)
        stolen_dropdown.click()
        self.page.wait_for_timeout(500)
        self.page.locator('mat-option:has-text("Yes")').first.click()
        self.page.wait_for_timeout(500)

    def expect_status_stolen(self):
        """Verify the detail page shows 'Stolen' status."""
        stolen_status = self.page.get_by_text(re.compile(r"\bStolen\b", re.I)).first
        expect(stolen_status).to_be_visible(timeout=15_000)

    def select_rented_mobile_home(self):
        """Select 'RENTED' radio option for Rented Mobile Home on LT-260 edit form."""
        rented_radio = self.page.locator(
            '//mat-radio-button[.//span[contains(text(),"RENTED")] or .//span[contains(text(),"Rented")]]'
        ).first
        rented_radio.scroll_into_view_if_needed(timeout=5_000)
        rented_radio.locator("label").click()
        self.page.wait_for_timeout(500)

    def click_save(self):
        """Click Save button at the bottom of the page."""
        save_btn = self.page.locator('button:has-text("Save")').first
        save_btn.scroll_into_view_if_needed(timeout=5_000)
        save_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def issue_160b_and_260a(self):
        """Click 'Issue 160B and 260A' button, then click Issue in the modal."""
        issue_btn = self.page.locator(
            'button:has-text("Issue 160B and 260A"), '
            'button:has-text("Issue 160B"), '
            'button:has-text("160B")'
        ).first
        issue_btn.scroll_into_view_if_needed(timeout=5_000)
        issue_btn.click()
        self.page.wait_for_timeout(2000)

        # Click Issue in the modal
        modal_issue_btn = self.page.locator(
            'mat-dialog-container button:has-text("Issue")'
        ).first
        modal_issue_btn.wait_for(state="visible", timeout=10_000)
        modal_issue_btn.click()
        self.page.wait_for_timeout(3000)

    def expect_issued_success_toast(self):
        """Verify green toast: 'The form has been issued successfully.'"""
        toast = self.page.locator(
            'text="The form has been issued successfully."'
        )
        expect(toast).to_be_visible(timeout=15_000)

    def expect_status_processed(self):
        """Verify the page shows 'Processed' status."""
        processed = self.page.get_by_text(re.compile(r"Processed", re.I)).first
        expect(processed).to_be_visible(timeout=15_000)

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

    def close_file(self, remarks: str = None):
        """Close file with optional remarks."""
        self._dismiss_cdk_overlay()
        self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        self.page.wait_for_timeout(500)

        # Strategy 1: Try the standard Close File button
        try:
            self.close_file_button.wait_for(state="visible", timeout=5_000)
            self.close_file_button.scroll_into_view_if_needed()
            self.close_file_button.click()
        except Exception:
            # Strategy 2: JS find and click — broad text matching
            clicked = self.page.evaluate("""() => {
                const buttons = document.querySelectorAll('button, a');
                for (const btn of buttons) {
                    const txt = btn.textContent.toLowerCase().trim();
                    if (txt.includes('close file') || txt.includes('close case') ||
                        (txt.includes('close') && !txt.includes('close modal') &&
                         !txt.includes('close dialog') && txt.length < 30)) {
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
                    try:
                        self.close_file_button.dispatch_event("click")
                    except Exception:
                        # Last resort: get_by_text
                        self.page.get_by_text(
                            re.compile(r"Close File|Close Case", re.I)
                        ).first.click()
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
