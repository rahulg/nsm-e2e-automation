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

    # Save debug screenshot so we can inspect the actual STAGE login form in CI
    _save_debug_screenshot(page, "debug_stage_public_login.png")

    # Try Verifi-style fields first (input#loginId), then fall back to broad selectors
    email_selectors = [
        "input#loginId",
        "input[type='email']",
        "input[name*='email' i]",
        "input[placeholder*='email' i]",
        "input[type='text']",
    ]
    email_input = None
    for sel in email_selectors:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                loc.wait_for(state="visible", timeout=5_000)
                email_input = loc
                print(f"  STAGE login: found email field with selector '{sel}'")
                break
            except Exception:
                continue

    if email_input is None:
        _save_debug_screenshot(page, "debug_stage_public_login_no_field.png")
        raise RuntimeError(
            f"STAGE public portal: could not locate email/username input. "
            f"Page URL: {page.url}. Check debug_stage_public_login.png for the actual form."
        )

    email_input.fill(username)

    page.locator("input[type='password']").first.fill(password)

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
