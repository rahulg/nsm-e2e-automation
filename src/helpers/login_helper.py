from playwright.sync_api import Browser, BrowserContext
from src.pages.public_portal.login_page import PublicLoginPage
from src.pages.staff_portal.login_page import StaffLoginPage


def create_public_portal_context(browser: Browser) -> BrowserContext:
    return browser.new_context(storage_state="./auth/public-portal.json")


def create_staff_portal_context(browser: Browser) -> BrowserContext:
    return browser.new_context(storage_state="./auth/staff-portal.json")


def login_to_public_portal(page, username=None, password=None):
    login_page = PublicLoginPage(page)
    login_page.login(username, password)


def login_to_staff_portal(page, username=None, password=None):
    login_page = StaffLoginPage(page)
    login_page.login(username, password)
