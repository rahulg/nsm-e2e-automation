"""Generate auth/staff-portal.json by logging in as the primary staff user via Verifi login."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from src.config.env import ENV

AUTH_PATH = Path(__file__).resolve().parent.parent / "auth" / "staff-portal.json"
IS_CI = os.getenv("CI") == "true"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_CI, slow_mo=0 if IS_CI else 300)
        context = browser.new_context()
        page = context.new_page()

        print(f"Navigating to {ENV.STAFF_PORTAL_URL} ...")
        page.goto(ENV.STAFF_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Click the "Log in with verifi" button to open the inline Verifi credentials form
        page.locator("//span[contains(text(),'Log in with')]").click()

        # Wait for the inline verifi form to actually appear (not a fixed sleep)
        try:
            page.locator("input#loginId").wait_for(state="visible", timeout=40_000)
        except Exception:
            screenshot_path = Path(__file__).resolve().parent.parent / "auth" / "debug_staff_login.png"
            page.screenshot(path=str(screenshot_path))
            print(f"  DEBUG screenshot saved to: {screenshot_path}")
            raise

        print(f"After verifi click URL: {page.url}")

        # Fill credentials (input#loginId / input#password-box-id appear inline after click)
        page.locator("input#loginId").fill(ENV.STAFF_PORTAL_USERNAME)
        page.locator("input#password-box-id").fill(ENV.STAFF_PORTAL_PASSWORD)
        page.wait_for_timeout(500)

        page.locator(
            'button[type="submit"], input[type="submit"], '
            'button:has-text("Sign In"), button:has-text("Login"), '
            'button:has-text("Log In"), button:has-text("Sign on"), '
            'exp-button button'
        ).first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        print(f"Post-login URL: {page.url}")
        context.storage_state(path=str(AUTH_PATH))
        print(f"Auth state saved to: {AUTH_PATH}")

        browser.close()


if __name__ == "__main__":
    main()
