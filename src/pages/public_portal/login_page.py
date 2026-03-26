import re
from playwright.sync_api import Page
from src.config.env import ENV


class PublicLoginPage:
    def __init__(self, page: Page):
        self.page = page

    def goto(self):
        self.page.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        self.page.wait_for_load_state("networkidle")

    def login(self, username: str = None, password: str = None):
        self.goto()

        # Step 1: Click "Sign In with NCID"
        self.page.locator('button:has-text("Sign In with NCID")').click()
        self.page.wait_for_url(re.compile(r"myncid|login\.myncidpp", re.I), timeout=30_000)
        self.page.wait_for_load_state("networkidle")

        # Step 2: Enter username
        self.page.locator("#identifierInput").fill(username or ENV.PUBLIC_PORTAL_USERNAME)

        # Step 3: Click "Next"
        self.page.locator('a.ping-button:has-text("Next")').click()
        self.page.wait_for_load_state("networkidle")

        # Step 4: Enter password
        self.page.locator("#password").fill(password or ENV.PUBLIC_PORTAL_PASSWORD)

        # Step 5: Click "Sign On"
        self.page.locator('a.ping-button:has-text("Sign On")').click()
        self.page.wait_for_load_state("networkidle")
