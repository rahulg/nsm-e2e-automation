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

        # Step 1: Click "Log in with" button
        self.page.locator('button:has-text("Log in with")').click()
        self.page.wait_for_timeout(1000)

        # Step 2: Enter username
        self.page.locator("input#loginId").fill(username or ENV.STAFF_PORTAL_USERNAME)

        # Step 3: Enter password
        self.page.locator("input#password-box-id").fill(password or ENV.STAFF_PORTAL_PASSWORD)

        # Step 4: Click "Log In"
        self.page.locator('button:has-text("Log In")').click()
        self.page.wait_for_load_state("networkidle")
