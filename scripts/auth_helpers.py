"""Public portal login strategies — dispatches to NCID (QA) or simple form (STAGE)."""
import re


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
    """STAGE: Simple form — Email + Password directly on landing page, no redirect."""
    page.locator(
        "input[type='email'], input[name*='email' i], input[placeholder*='email' i]"
    ).first.fill(username)
    page.locator("input[type='password']").first.fill(password)
    page.locator(
        "button[type='submit'], button:has-text('Sign In'), button:has-text('Login')"
    ).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
