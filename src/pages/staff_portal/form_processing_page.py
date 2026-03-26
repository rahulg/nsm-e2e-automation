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
