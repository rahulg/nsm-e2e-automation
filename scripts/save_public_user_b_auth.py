"""Generate auth/public-portal-user-b.json by logging in as PUBLIC_USER_B (mora_333) via NCID."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from src.config.env import ENV

AUTH_PATH = Path(__file__).resolve().parent.parent / "auth" / "public-portal-user-b.json"
IS_CI = os.getenv("CI") == "true"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_CI, slow_mo=0 if IS_CI else 300)
        context = browser.new_context()
        page = context.new_page()

        print(f"Navigating to {ENV.PUBLIC_PORTAL_URL} ...")
        page.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Click "Sign In with NCID"
        page.locator('button:has-text("Sign In with NCID")').click()
        page.wait_for_url(re.compile(r"myncid|login\.myncidpp", re.I), timeout=30_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        # Enter username
        page.locator("#identifierInput").fill(ENV.PUBLIC_USER_B_USERNAME)
        page.locator('a.ping-button:has-text("Next")').click()
        page.wait_for_load_state("networkidle")

        # Enter password
        page.locator("#password").fill(ENV.PUBLIC_USER_B_PASSWORD)
        page.locator('a.ping-button:has-text("Sign On")').click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        print(f"Post-login URL: {page.url}")
        context.storage_state(path=str(AUTH_PATH))
        print(f"Auth state saved to: {AUTH_PATH}")

        browser.close()


if __name__ == "__main__":
    main()
