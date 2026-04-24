import re

from playwright.sync_api import Page
from src.config.env import ENV


class StaffLoginPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self):
        self.page.goto(ENV.STAFF_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

    def login(self, username: str = None, password: str = None):
        self.goto()

        # Step 1: Click "Log in with" button — leads to IC Login intermediate page
        self.page.locator('button:has-text("Log in with")').click()
        self.page.wait_for_load_state("networkidle")

        # Step 2: Click verifi logo on intermediate page — (//img[@alt='Expertly'])[2]
        # Wait explicitly before clicking to handle slow headless CI rendering
        img = self.page.locator("//img[@alt='Expertly']").nth(1)
        img.wait_for(state="visible", timeout=30_000)
        img.click()
        self.page.locator("input#loginId").wait_for(state="visible", timeout=30_000)

        # Step 2: Enter username
        self.page.locator("input#loginId").fill(username or ENV.STAFF_PORTAL_USERNAME)

        # Step 3: Enter password
        self.page.locator("input#password-box-id").fill(password or ENV.STAFF_PORTAL_PASSWORD)

        # Step 4: Click "Log In" — wait for redirect back to the portal
        self.page.locator('button:has-text("Log In")').click()
        self.page.wait_for_url(re.compile(r"verifi\.dev", re.I), timeout=60_000)
        self.page.wait_for_load_state("domcontentloaded")
