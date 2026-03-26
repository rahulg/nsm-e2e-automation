"""
Staff Portal Global Search Page — search across all form types and statuses.
"""

import re
from playwright.sync_api import Page, expect


class GlobalSearchPage:
    def __init__(self, page: Page):
        self.page = page

        # Navigation
        self.global_search_link = page.locator(
            'a:has-text("Global Search"), a[href*="global-search"]'
        ).first

        # Search
        self.search_input = page.locator(
            'input[placeholder*="Global Search" i], input[placeholder*="Search" i], '
            'input[aria-label*="Search" i]'
        ).first
        self.search_button = page.locator(
            'button:has-text("Search"), button[type="submit"]'
        ).first

        # Results
        self.results_table = page.locator("table.mat-table, table, [class*='search-result']").first
        self.result_rows = page.locator(
            "table.mat-table tr.mat-row, table tbody tr, "
            "[class*='search-result'] [class*='row'], mat-card"
        )
        self.vin_links = page.locator("span.table-link, a[class*='link']")

    def navigate_to(self):
        self._dismiss_cdk_overlay()
        try:
            self.global_search_link.wait_for(state="visible", timeout=5_000)
            self.global_search_link.scroll_into_view_if_needed()
            self.global_search_link.click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            # Fallback: URL-based navigation
            try:
                base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
                self.page.goto(f"{base}/global-search", timeout=30_000)
            except Exception:
                # Last resort: try broader link selectors or force click
                link = self.page.locator('a[href*="global"], a:has-text("Search")').first
                try:
                    link.scroll_into_view_if_needed()
                    link.click()
                except Exception:
                    link.click(force=True)
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

    def _js_search(self, term: str):
        """Trigger search via JS — sets input value and dispatches Angular events."""
        self.page.evaluate(f"""(term) => {{
            const inputs = document.querySelectorAll(
                'input[placeholder*="Search"], input[type="search"], input[aria-label*="Search"]'
            );
            const input = inputs[0];
            if (!input) return;
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(input, '');
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            nativeInputValueSetter.call(input, term);
            input.dispatchEvent(new Event('input', {{bubbles: true}}));
            input.dispatchEvent(new Event('change', {{bubbles: true}}));
            input.dispatchEvent(new KeyboardEvent('keyup', {{key: 'Enter', keyCode: 13, bubbles: true}}));
            input.dispatchEvent(new KeyboardEvent('keydown', {{key: 'Enter', keyCode: 13, bubbles: true}}));
            // Also try clicking any search button
            const btn = document.querySelector('button[type="submit"], button:has(mat-icon)');
            if (btn) btn.click();
        }}""", term)
        self.page.wait_for_timeout(3000)

    def search(self, term: str):
        self._dismiss_cdk_overlay()
        try:
            self.search_input.wait_for(state="visible", timeout=10_000)
        except Exception:
            # Fallback: try broader search input selector
            self.search_input = self.page.locator(
                'input[placeholder*="Search" i], input[type="search"], input[aria-label*="Search" i]'
            ).first
            self.search_input.wait_for(state="visible", timeout=10_000)
        self.search_input.fill("")
        self.page.wait_for_timeout(300)
        self.search_input.fill(term)

        # Try clicking search button first, then Enter key
        try:
            self.search_button.click(timeout=3_000)
        except Exception:
            self.search_input.press("Enter")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(3000)

        # If no results, try alternative approaches
        try:
            self.result_rows.first.wait_for(state="visible", timeout=5_000)
        except Exception:
            # Retry with type() for debounce-based search
            self.search_input.fill("")
            self.page.wait_for_timeout(500)
            self.search_input.type(term, delay=50)
            self.page.wait_for_timeout(1000)
            self.search_input.press("Enter")
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(3000)

            # If still no results, try JS Angular event dispatch
            try:
                self.result_rows.first.wait_for(state="visible", timeout=3_000)
            except Exception:
                self._js_search(term)
                self.page.wait_for_load_state("networkidle")
                self.page.wait_for_timeout(2000)

    def select_result(self, index: int = 0):
        self.vin_links.nth(index).click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def expect_results_visible(self):
        try:
            expect(self.result_rows.first).to_be_visible(timeout=15_000)
        except Exception:
            # Fallback: look for any result content (text, cards, accordion)
            result_content = self.page.locator(
                'table tbody tr, mat-card, [class*="result"], '
                '[class*="search-result"], mat-expansion-panel, '
                '[class*="row"]:has-text("LT-")'
            ).first
            expect(result_content).to_be_visible(timeout=10_000)

    def expect_no_results(self):
        """Verify no search results — look for 'No results' text or empty table."""
        try:
            expect(self.result_rows).to_have_count(0, timeout=5_000)
        except Exception:
            # May show a "No results found" message instead
            no_results = self.page.get_by_text(
                re.compile(r"No results|No records|Not found|No data", re.I)
            ).first
            expect(no_results).to_be_visible(timeout=5_000)

    def get_all_results_text(self) -> str:
        """Get combined text of all search result content on the page."""
        # Wait for any search results to appear
        self.page.wait_for_timeout(1000)

        try:
            # Try table rows first
            text = ""
            count = self.result_rows.count()
            for i in range(min(count, 20)):
                text += (self.result_rows.nth(i).text_content() or "") + " "
            if text.strip():
                return text
        except Exception:
            pass

        # Fallback: get all visible text in the results area
        try:
            content = self.page.locator(
                '[class*="search-result"], [class*="result"], '
                '.mat-card, mat-expansion-panel, table'
            ).first
            return content.text_content() or ""
        except Exception:
            pass

        # Last resort: get text from the main content area
        try:
            main = self.page.locator(
                'mat-sidenav-content, .main-content, main, [role="main"]'
            ).first
            return main.text_content() or ""
        except Exception:
            return ""

    def get_status_text(self, index: int = 0) -> str:
        try:
            return self.result_rows.nth(index).text_content() or ""
        except Exception:
            return ""
