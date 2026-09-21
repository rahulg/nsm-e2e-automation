"""Generate auth/{env}/individual-portal-user-b.json by logging in as the SECOND
individual public user (INDIVIDUAL_PUBLIC_USER_B_* — "Bowers" on QA, whose
registered email is a mailinator.com address).

Same shape as save_individual_auth.py — only the credential pair and the output
file name differ.
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from scripts.auth_helpers import login_public_portal
from src.config.env import ENV

ENV_NAME = os.getenv("NSM_ENV", "qa")
AUTH_DIR = Path(__file__).resolve().parent.parent / "auth" / ENV_NAME
AUTH_DIR.mkdir(parents=True, exist_ok=True)
AUTH_PATH = AUTH_DIR / "individual-portal-user-b.json"
IS_CI = os.getenv("CI") == "true"


def wait_for_session(page, timeout: int = 60_000) -> None:
    """Block until the portal has really established a session, then (and only then) save.

    Same fix as save_individual_auth.py's wait_for_session — the NCID SSO hand-back
    lands on '/authentication/validate?code=...' BEFORE the app has exchanged that
    code for a token. Saving there produces a storage_state with no authToken, so
    every later run bounces straight back to /ncdot-nsm-signin. Wait for the
    dashboard route AND for authToken to be written, and fail loudly rather than
    persist a useless state file.
    """
    try:
        page.wait_for_url(re.compile(r"dashboard", re.I), timeout=timeout)
    except Exception:  # noqa: BLE001
        print(f"  WARN: never reached a dashboard URL (at {page.url}) — checking token anyway")

    try:
        page.wait_for_function(
            "() => !!window.localStorage.getItem('authToken')", timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Individual-portal-user-b login did not produce an authToken in "
            f"localStorage (final URL: {page.url}) — refusing to save an "
            f"unauthenticated state file"
        ) from exc

    page.wait_for_load_state("networkidle")


def main():
    if not ENV.INDIVIDUAL_PUBLIC_USER_B_USERNAME or not ENV.INDIVIDUAL_PUBLIC_USER_B_PASSWORD:
        raise EnvironmentError(
            "INDIVIDUAL_PUBLIC_USER_B_USERNAME / INDIVIDUAL_PUBLIC_USER_B_PASSWORD "
            f"are not set in .env.{ENV_NAME} — cannot generate {AUTH_PATH.name}."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=IS_CI, slow_mo=0 if IS_CI else 300)
        context = browser.new_context()
        page = context.new_page()

        print(f"Navigating to {ENV.PUBLIC_PORTAL_URL} ...")
        page.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        login_public_portal(
            page,
            ENV.INDIVIDUAL_PUBLIC_USER_B_USERNAME,
            ENV.INDIVIDUAL_PUBLIC_USER_B_PASSWORD,
            ENV_NAME,
        )

        wait_for_session(page)

        print(f"Post-login URL: {page.url}")
        context.storage_state(path=str(AUTH_PATH))
        print(f"Auth state saved to: {AUTH_PATH}")

        browser.close()


if __name__ == "__main__":
    main()
