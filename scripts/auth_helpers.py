"""Public portal login strategies — dispatches to NCID (QA) or simple form (STAGE)."""
import os
import re
from pathlib import Path


def login_public_portal(page, username: str, password: str, env: str) -> None:
    if env == "stage":
        _login_public_simple(page, username, password)
    else:
        _login_public_ncid(page, username, password)


def _login_public_ncid(page, username: str, password: str) -> None:
    """QA: NCID SSO — Sign In with NCID button → myncid redirect → 2-step form."""
    page.locator('button:has-text("Sign In with NCID")').click()
    page.wait_for_url(re.compile(r"myncid|login\.myncidpp", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.locator("#identifierInput").fill(username)
    page.locator('a.ping-button:has-text("Next")').click()
    page.wait_for_load_state("networkidle")
    page.locator("#password").fill(password)
    page.locator('a.ping-button:has-text("Sign On")').click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)


def _login_public_simple(page, username: str, password: str) -> None:
    """STAGE: Direct email+password form on landing page — no SSO redirect."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    page.locator("//input[@name='email']").fill(username)
    page.locator("//input[@name='pass']").fill(password)

    page.locator(
        "button[type='submit'], input[type='submit'], "
        "button:has-text('Sign In'), button:has-text('Login'), "
        "button:has-text('Log In'), exp-button button"
    ).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)


def _save_debug_screenshot(page, filename: str) -> None:
    env_name = os.getenv("NSM_ENV", "qa")
    screenshot_dir = Path(__file__).resolve().parent.parent / "auth" / env_name
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    path = screenshot_dir / filename
    try:
        page.screenshot(path=str(path))
        print(f"  DEBUG screenshot saved to: {path}")
    except Exception as e:
        print(f"  DEBUG screenshot failed: {e}")
