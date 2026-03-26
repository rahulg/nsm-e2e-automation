import re
from playwright.sync_api import Page, expect
from src.config.env import ENV

BASE_PATH = "/pages/ncdot-notice-and-storage"


class StaffDashboardPage:
    def __init__(self, page: Page):
        self.page = page

        # Sidebar — href-based selectors
        self.lt260_nav_link = page.locator('a[href*="LT-260/list"]').first
        self.lt261_nav_link = page.locator('a[href*="LT-261/list"]').first
        self.lt262_nav_link = page.locator(f'a[href="{BASE_PATH}/LT-262/list"]').first
        self.lt262a_nav_link = page.locator('a[href*="LT-262A/list"]').first
        self.lt263_nav_link = page.locator('a[href*="LT-263/list"]').first
        self.sold_nav_link = page.locator('a[href*="/sold"]').first
        self.payments_nav_link = page.locator('a[href*="payments/list"], a[href*="payment"]').first
        self.reports_link = page.locator(
            'a[href*="reports/list"], a[href*="reports"], a:has-text("Reports")'
        ).first
        self.nordis_nav_link = page.locator(
            'a[href*="nordis"], a[href*="Nordis"], a:has-text("Nordis"), '
            'a:has-text("Daily Transmission")'
        ).first
        self.global_search_link = page.locator(
            'a[href*="global-search"], a[href*="globalSearch"], '
            'a:has-text("Global Search"), button:has-text("Global Search")'
        ).first

        # Dashboard tabs
        self.kpi_dashboard_tab = page.locator('[role="tab"]:has-text("KPI Dashboard")')
        self.message_center_tab = page.locator('[role="tab"]:has-text("Message Center")')

    def goto(self):
        self.page.goto(ENV.STAFF_PORTAL_URL)
        self.page.wait_for_load_state("networkidle")

    def _dismiss_cdk_overlay(self):
        """Dismiss any CDK overlay that may block sidebar/nav clicks."""
        try:
            self.page.evaluate("""() => {
                const backdrops = document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop, .cdk-overlay-dark-backdrop'
                );
                backdrops.forEach(b => {
                    b.click();
                    b.remove();
                });
            }""")
            self.page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

    def _wait_for_sidebar(self):
        self._dismiss_cdk_overlay()
        self.lt260_nav_link.wait_for(state="visible", timeout=15_000)

    def _click_nav_link(self, link_locator, href_pattern: str = None):
        """Click a sidebar nav link with CDK overlay fallback."""
        try:
            link_locator.click(timeout=10_000)
        except Exception:
            # CDK overlay likely blocking — dismiss and retry
            self._dismiss_cdk_overlay()
            try:
                link_locator.click(timeout=5_000)
            except Exception:
                # JS fallback: direct navigation or force click
                if href_pattern:
                    try:
                        self.page.evaluate(f"""() => {{
                            const links = document.querySelectorAll('a[href*="{href_pattern}"]');
                            if (links.length > 0) links[0].click();
                        }}""")
                    except Exception:
                        link_locator.click(force=True)
                else:
                    link_locator.click(force=True)
        self.page.wait_for_load_state("networkidle")

    def navigate_to_lt260_listing(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.lt260_nav_link, "LT-260/list")

    def navigate_to_lt262_listing(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.lt262_nav_link, "LT-262/list")

    def navigate_to_lt263_listing(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.lt263_nav_link, "LT-263/list")

    def navigate_to_sold(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.sold_nav_link, "/sold")

    def navigate_to_lt261_listing(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.lt261_nav_link, "LT-261/list")

    def navigate_to_lt262a_listing(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.lt262a_nav_link, "LT-262A/list")

    def navigate_to_payments(self):
        self._wait_for_sidebar()
        self._click_nav_link(self.payments_nav_link, "payment")

    def navigate_to_reports(self):
        self._wait_for_sidebar()
        try:
            self.reports_link.wait_for(state="visible", timeout=5_000)
            self.reports_link.click()
        except Exception:
            # URL-based fallback
            base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
            self.page.goto(f"{base}/reports/list", timeout=30_000)
        self.page.wait_for_load_state("networkidle")

    def navigate_to_nordis(self):
        """Navigate to Nordis/Daily Transmission page."""
        self._wait_for_sidebar()
        try:
            self.nordis_nav_link.wait_for(state="visible", timeout=5_000)
            self.nordis_nav_link.click()
        except Exception:
            base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
            # Try multiple URL patterns
            for path in ["nordis", "nordis/list", "daily-transmission", "nca/daily-transmission", "reports/nordis"]:
                try:
                    self.page.goto(f"{base}/{path}", timeout=15_000)
                    self.page.wait_for_load_state("networkidle")
                    if "404" not in (self.page.title() or ""):
                        break
                except Exception:
                    continue
        self.page.wait_for_load_state("networkidle")

    def navigate_to_global_search(self):
        """Navigate to Global Search page."""
        self._wait_for_sidebar()
        self._dismiss_cdk_overlay()
        try:
            self.global_search_link.wait_for(state="visible", timeout=5_000)
            self.global_search_link.click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            try:
                self.global_search_link.click(force=True)
            except Exception:
                base = re.sub(r"(pages/ncdot-notice-and-storage)/.*", r"\1", self.page.url)
                self.page.goto(f"{base}/global-search", timeout=30_000)
        self.page.wait_for_load_state("networkidle")

    def expect_on_dashboard(self):
        expect(self.page).to_have_url(re.compile(r"dashboard", re.I))

    def expect_kpi_visible(self):
        expect(self.kpi_dashboard_tab).to_be_visible(timeout=15_000)
