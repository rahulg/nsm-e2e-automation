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
    _save_debug_screenshot(page, "debug_ncid_01_username_page.png")
    page.locator("#identifierInput").fill(username)
    # PingFederate renders Next as <a class="ping-button"> or <button class="ping-button"> depending on version
    page.locator(
        'a.ping-button:has-text("Next"), button.ping-button:has-text("Next"), '
        'button:has-text("Next"), input[value="Next"]'
    ).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    _save_debug_screenshot(page, "debug_ncid_02_password_page.png")
    page.locator("#password").fill(password)
    page.locator(
        'a.ping-button:has-text("Sign On"), button.ping-button:has-text("Sign On"), '
        'button:has-text("Sign On"), input[value="Sign On"]'
    ).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)


def _login_public_simple(page, username: str, password: str) -> None:
    """STAGE: Direct email+password form on landing page — no SSO redirect."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Screenshot immediately after page load — shows what's actually on screen
    _save_debug_screenshot(page, "debug_stage_public_01_landed.png")
    print(f"  STAGE login: page URL after load = {page.url}")
    print(f"  STAGE login: page title = {page.title()}")

    page.locator("//input[@name='email']").wait_for(state="visible", timeout=30_000)
    page.locator("//input[@name='email']").fill(username)
    page.locator("//input[@name='pass']").fill(password)

    _save_debug_screenshot(page, "debug_stage_public_02_filled.png")

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
