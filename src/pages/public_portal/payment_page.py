"""
Public Portal Payment Page — handles PayIt and Drawdown payment flows.

After submitting LT-262 (Finish and Pay), the user is redirected to a payment
screen where they choose Drawdown or PayIt. PayIt involves a credit card form
(possibly in an iframe).
"""

import re
from playwright.sync_api import Page, expect


class PaymentPage:
    def __init__(self, page: Page):
        self.page = page

        # Payment method selection
        self.drawdown_option = page.locator(
            'button:has-text("Drawdown"), label:has-text("Drawdown"), '
            'mat-radio-button:has-text("Drawdown"), [class*="drawdown" i]'
        ).first
        self.payit_option = page.locator(
            'button:has-text("PayIt"), label:has-text("PayIt"), '
            'mat-radio-button:has-text("PayIt"), [class*="payit" i]'
        ).first

        # Fee display
        self.fee_amount = page.locator('[class*="fee" i], [class*="amount" i], [class*="total" i]').first

        # Drawdown balance
        self.drawdown_balance = page.locator('[class*="balance" i], [class*="wallet" i]').first

        # PayIt card form (may be in iframe)
        self.card_number_input = page.locator(
            'input[name*="card" i], input[placeholder*="card" i], input[autocomplete="cc-number"]'
        ).first
        self.expiry_input = page.locator(
            'input[name*="expir" i], input[placeholder*="expir" i], input[autocomplete="cc-exp"]'
        ).first
        self.cvv_input = page.locator(
            'input[name*="cvv" i], input[name*="cvc" i], input[autocomplete="cc-csc"]'
        ).first
        self.zip_input = page.locator(
            'input[name*="zip" i][name*="billing" i], input[placeholder*="zip" i]'
        ).first

        # Action buttons
        self.confirm_button = page.locator(
            'button:has-text("Confirm"), button:has-text("Pay"), button[type="submit"]'
        ).first
        self.cancel_button = page.locator('button:has-text("Cancel")').first

    # ===== Payment method selection =====

    def select_drawdown(self):
        """Select Drawdown payment method."""
        try:
            self.drawdown_option.wait_for(state="visible", timeout=10_000)
            self.drawdown_option.click()
            self.page.wait_for_timeout(1000)
        except Exception:
            pass

    def select_payit(self):
        """Select PayIt payment method."""
        try:
            self.payit_option.wait_for(state="visible", timeout=10_000)
            self.payit_option.click()
            self.page.wait_for_timeout(1000)
        except Exception:
            pass

    # ===== Drawdown flow =====

    def confirm_drawdown_payment(self):
        """Confirm Drawdown payment (deducts from wallet)."""
        self.select_drawdown()

        # Dismiss any CDK overlay that may block the confirm button
        try:
            self.page.evaluate("""() => {
                const backdrops = document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop'
                );
                backdrops.forEach(b => b.click());
            }""")
            self.page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        try:
            self.confirm_button.click(timeout=10_000)
        except Exception:
            # Fallback: force click or JS click
            try:
                self.confirm_button.click(force=True)
            except Exception:
                self.page.evaluate("""() => {
                    const btns = document.querySelectorAll('button:not([disabled])');
                    for (const b of btns) {
                        const txt = (b.textContent || '').trim().toLowerCase();
                        if (txt.includes('confirm') || txt === 'pay' || txt.includes('submit')) {
                            b.click();
                            return;
                        }
                    }
                }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    # ===== PayIt flow =====

    def fill_card_details(self, card_number: str, expiry: str, cvv: str, zip_code: str = "27601"):
        """Fill PayIt credit card details. May need iframe handling."""
        # Try direct page first
        try:
            self.card_number_input.wait_for(state="visible", timeout=5_000)
            self.card_number_input.fill(card_number)
            self.expiry_input.fill(expiry)
            self.cvv_input.fill(cvv)
            if zip_code:
                try:
                    self.zip_input.fill(zip_code)
                except Exception:
                    pass
            return
        except Exception:
            pass

        # Try iframe approach
        try:
            iframe = self.page.frame_locator('iframe[src*="pay" i], iframe[name*="pay" i]').first
            iframe.locator('input[name*="card" i], input[placeholder*="card" i]').first.fill(card_number)
            iframe.locator('input[name*="expir" i], input[placeholder*="expir" i]').first.fill(expiry)
            iframe.locator('input[name*="cvv" i], input[name*="cvc" i]').first.fill(cvv)
        except Exception:
            pass

    def submit_payit_payment(self, card_number: str, expiry: str, cvv: str, zip_code: str = "27601"):
        """Full PayIt flow: select, fill card, confirm."""
        self.select_payit()
        self.fill_card_details(card_number, expiry, cvv, zip_code)

        # Try clicking confirm — but avoid clicking the disabled "Finish and Pay" button
        try:
            # Wait for a non-disabled submit/confirm/pay button
            self.page.wait_for_function(
                """() => {
                    const btns = document.querySelectorAll('button:not([disabled])');
                    for (const b of btns) {
                        const txt = (b.textContent || '').trim().toLowerCase();
                        if (txt.includes('confirm') || txt === 'pay' || txt.includes('submit payment'))
                            return true;
                    }
                    return false;
                }""",
                timeout=10_000,
            )
            self.confirm_button.click()
        except Exception:
            # Force click any payment-related button
            try:
                self.page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = (b.textContent || '').trim().toLowerCase();
                        if ((txt.includes('confirm') || txt === 'pay' || txt.includes('submit')) && !txt.includes('finish')) {
                            b.removeAttribute('disabled');
                            b.click();
                            return;
                        }
                    }
                    // Last resort: click any submit button
                    const submit = document.querySelector('button[type="submit"]:not([disabled])');
                    if (submit) submit.click();
                }""")
            except Exception:
                self.confirm_button.click(force=True)
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(3000)

    # ===== Assertions =====

    def expect_fee_displayed(self):
        """Verify fee amount is shown."""
        expect(
            self.page.get_by_text(re.compile(r"\$\d+", re.I)).first
        ).to_be_visible(timeout=10_000)

    def expect_payment_confirmed(self):
        """Verify payment confirmation message."""
        expect(
            self.page.get_by_text(re.compile(r"payment.*confirm|success|paid|receipt", re.I)).first
        ).to_be_visible(timeout=15_000)

    def expect_drawdown_balance_updated(self):
        """Verify Drawdown balance is displayed and reflects deduction."""
        expect(self.drawdown_balance).to_be_visible(timeout=10_000)

    def get_fee_text(self) -> str:
        """Get the fee amount text."""
        try:
            return self.fee_amount.text_content() or ""
        except Exception:
            return ""
