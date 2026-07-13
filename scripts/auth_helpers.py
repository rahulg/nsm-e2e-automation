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
    # PingFederate button text varies by version: "Next" (older) or "Sign In" (newer)
    page.locator(
        'a.ping-button:has-text("Sign In"), button.ping-button:has-text("Sign In"), '
        'button:has-text("Sign In"), input[value="Sign In"], '
        'a.ping-button:has-text("Next"), button.ping-button:has-text("Next"), '
        'button:has-text("Next"), input[value="Next"]'
    ).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    _save_debug_screenshot(page, "debug_ncid_02_password_page.png")
    page.locator("#password").fill(password)
    # PingFederate button text varies by version: "Sign On" (older) or "Sign In" (newer)
    page.locator(
        'a.ping-button:has-text("Sign In"), button.ping-button:has-text("Sign In"), '
        'button:has-text("Sign In"), input[value="Sign In"], '
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


def select_company_if_prompted(page, timeout: int = 15_000) -> None:
    """After public-portal login, some users land on /select-company (multi-company
    accounts) instead of the dashboard. Pick the first company and continue.

    No-ops if the account isn't prompted (single-company users skip straight
    to the dashboard).
    """
    try:
        page.wait_for_url(re.compile(r"select-company", re.I), timeout=timeout)
    except Exception:
        return  # not prompted -- already past this step

    page.wait_for_load_state("networkidle")
    page.locator("mat-select").first.click()
    page.locator("mat-option").first.wait_for(state="visible", timeout=timeout)
    page.locator("mat-option").first.click()
    page.wait_for_timeout(500)

    page.get_by_role("button", name=re.compile(r"^\s*Go To Dashboard\s*$", re.I)).click()
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=timeout)
    page.wait_for_load_state("networkidle")


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
