"""Generate auth/{env}/individual-portal.json by logging in as the individual public user."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from scripts.auth_helpers import login_public_portal
from src.config.env import ENV

ENV_NAME = os.getenv("NSM_ENV", "qa")
AUTH_DIR = Path(__file__).resolve().parent.parent / "auth" / ENV_NAME
AUTH_DIR.mkdir(parents=True, exist_ok=True)
AUTH_PATH = AUTH_DIR / "individual-portal.json"
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

        login_public_portal(page, ENV.INDIVIDUAL_PUBLIC_USERNAME, ENV.INDIVIDUAL_PUBLIC_PASSWORD, ENV_NAME)

        print(f"Post-login URL: {page.url}")
        context.storage_state(path=str(AUTH_PATH))
        print(f"Auth state saved to: {AUTH_PATH}")

        browser.close()


if __name__ == "__main__":
    main()
