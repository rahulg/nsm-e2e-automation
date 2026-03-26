"""
Public Portal Shopping Cart Page — for batch payment of LT-262 applications.
"""

import re
from playwright.sync_api import Page, expect


class ShoppingCartPage:
    def __init__(self, page: Page):
        self.page = page

        # Cart navigation
        self.cart_icon = page.locator(
            '[class*="cart" i], a:has-text("Cart"), button:has-text("Cart")'
        ).first

        # Cart items
        self.cart_items = page.locator('[class*="cart-item" i], table tbody tr')
        self.cart_total = page.locator('[class*="total" i]').first

        # Actions
        self.checkout_button = page.locator(
            'button:has-text("Checkout"), button:has-text("Pay"), button:has-text("Proceed")'
        ).first
        self.remove_button = page.locator(
            'button:has-text("Remove"), button:has-text("Delete")'
        ).first

    def navigate_to_cart(self):
        try:
            self.cart_icon.wait_for(state="visible", timeout=5_000)
            self.cart_icon.click()
        except Exception:
            # URL-based fallback
            current_url = self.page.url
            for pattern, replacement in [
                (r"(ncdmv-nsm)/.*", r"\1/cart"),
                (r"(ncdmv-nsm)/.*", r"\1/shopping-cart"),
                (r"/dashboard.*", "/cart"),
            ]:
                try:
                    cart_url = re.sub(pattern, replacement, current_url)
                    if cart_url != current_url:
                        self.page.goto(cart_url, timeout=30_000)
                        self.page.wait_for_load_state("networkidle")
                        if "cart" in self.page.url.lower():
                            break
                except Exception:
                    continue
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def expect_cart_empty(self):
        """Verify cart is empty. Check for empty cart text or zero cart items."""
        try:
            # First check if "empty cart" message is displayed
            empty_msg = self.page.locator(
                'text=/empty|no items|cart is empty/i'
            ).first
            empty_msg.wait_for(state="visible", timeout=5_000)
        except Exception:
            # Fallback: check that cart-specific items have count 0
            cart_specific = self.page.locator('[class*="cart-item" i]')
            try:
                expect(cart_specific).to_have_count(0, timeout=5_000)
            except Exception:
                # Last resort: check the original combined locator
                expect(self.cart_items).to_have_count(0, timeout=5_000)

    def expect_cart_not_empty(self):
        expect(self.cart_items.first).to_be_visible(timeout=10_000)

    def get_item_count(self) -> int:
        return self.cart_items.count()

    def checkout(self):
        self.checkout_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
