import re
from playwright.sync_api import Page
from src.config.env import ENV


def navigate_to_public_portal_section(page: Page, section: str):
    nav_map = {
        "dashboard": "Dashboard",
        "create-lt260": "Create LT-260",
        "my-profile": "My Profile",
        "message-center": "Message Center",
        "reports": "Reports",
        "support-help": "Support Help",
    }
    label = nav_map.get(section, section)
    page.locator(f'a:has-text("{label}"), [class*="nav"] :has-text("{label}"), [class*="sidebar"] :has-text("{label}"), [class*="menu"] :has-text("{label}")').first.click()
    page.wait_for_load_state("networkidle")


def navigate_to_staff_portal_section(page: Page, section: str):
    nav_map = {
        "dashboard": "Dashboard",
        "lt-260": "LT-260",
        "lt-261": "LT-261",
        "lt-262": "LT-262",
        "lt-263": "LT-263",
        "global-search": "Global Search",
        "user-management": "User Management",
        "configuration": "Configuration",
        "reports": "Reports",
        "correspondence": "Correspondence",
        "facility-management": "Facility Management",
        "message-center": "Message Center",
    }
    label = nav_map.get(section, section)
    page.locator(f'a:has-text("{label}"), [class*="nav"] :has-text("{label}"), [class*="sidebar"] :has-text("{label}"), [class*="menu"] :has-text("{label}")').first.click()
    page.wait_for_load_state("networkidle")


def go_to_public_portal(page: Page):
    page.goto(ENV.PUBLIC_PORTAL_URL)
    page.wait_for_load_state("networkidle")


def go_to_staff_portal(page: Page):
    dashboard_url = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)
    page.goto(dashboard_url)
    page.wait_for_load_state("networkidle")


def click_tab(page: Page, tab_name: str):
    page.locator(f'[role="tab"]:has-text("{tab_name}"), button:has-text("{tab_name}"), a:has-text("{tab_name}")').first.click()
    page.wait_for_load_state("networkidle")
