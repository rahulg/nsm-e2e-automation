import os
import sys
import re
import json
import time
import base64
from pathlib import Path

# Add project root to sys.path so `src.*` imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from playwright.sync_api import Playwright, Browser, BrowserContext, expect
from src.config.env import ENV
from src.pages.public_portal.login_page import PublicLoginPage
from src.pages.staff_portal.login_page import StaffLoginPage

# ─── Headed / Headless toggle ───
headless = not os.getenv("HEADED", "").strip().lower() in ("1", "true", "yes")

# ─── Slow-motion delay (ms) ───
slow_mo = int(os.getenv("SLOWMO", "0"))

# ─── Auth storage paths ───
AUTH_DIR = Path(__file__).resolve().parent / "auth"
PUBLIC_AUTH_PATH = AUTH_DIR / "public-portal.json"
STAFF_AUTH_PATH = AUTH_DIR / "staff-portal.json"

# ─── Token expiry buffer (seconds) ───
# Delete cached auth if token expires within this window
TOKEN_EXPIRY_BUFFER = 300  # 5 minutes


def _is_auth_expired(auth_path: Path) -> bool:
    """Check if cached auth file contains expired JWT tokens.

    Reads the storage state JSON file, extracts any JWT authToken from
    localStorage, decodes its 'exp' claim, and returns True if the token
    has expired (or will expire within TOKEN_EXPIRY_BUFFER seconds).
    Returns True (treat as expired) if the file is missing or unparseable.
    """
    if not auth_path.exists():
        return True

    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True

    # Look for authToken in localStorage across all origins
    for origin in data.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == "authToken":
                token = item.get("value", "")
                try:
                    # JWT format: header.payload.signature — decode payload
                    payload = token.split(".")[1]
                    # Add padding for base64 decoding
                    payload += "=" * (-len(payload) % 4)
                    claims = json.loads(base64.urlsafe_b64decode(payload))
                    exp = claims.get("exp", 0)
                    if time.time() + TOKEN_EXPIRY_BUFFER >= exp:
                        return True
                    return False  # valid, not expired
                except (IndexError, ValueError, json.JSONDecodeError):
                    return True  # malformed token, treat as expired

    # No authToken found — treat as expired for staff portal,
    # but public portal may use cookies only
    return False


def _clear_if_expired(auth_path: Path) -> None:
    """Delete cached auth file if its tokens have expired."""
    if auth_path.exists() and _is_auth_expired(auth_path):
        auth_path.unlink()
        print(f"[auth] Deleted expired auth: {auth_path.name}")


def _ensure_public_auth(playwright: Playwright, username=None, password=None, path=None):
    """Perform Public Portal login and save storage state."""
    auth_path = path or PUBLIC_AUTH_PATH
    _clear_if_expired(auth_path)
    if auth_path.exists():
        return
    auth_path.parent.mkdir(parents=True, exist_ok=True)

    browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
    context = browser.new_context()
    page = context.new_page()

    login_page = PublicLoginPage(page)
    login_page.login(username, password)

    # Wait for redirect back to NSM portal
    page.wait_for_url(re.compile(r"verifi\.dev", re.I), timeout=60_000)
    page.wait_for_load_state("networkidle")

    context.storage_state(path=str(auth_path))
    context.close()
    browser.close()


def _ensure_staff_auth(playwright: Playwright, username=None, password=None, path=None):
    """Perform Staff Portal login and save storage state."""
    auth_path = path or STAFF_AUTH_PATH
    _clear_if_expired(auth_path)
    if auth_path.exists():
        return
    auth_path.parent.mkdir(parents=True, exist_ok=True)

    browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
    context = browser.new_context()
    page = context.new_page()

    login_page = StaffLoginPage(page)
    login_page.login(username, password)

    # Wait for redirect to staff dashboard
    page.wait_for_url(re.compile(r"verifi\.dev", re.I), timeout=60_000)
    page.wait_for_load_state("networkidle")

    # Wait for sidebar to confirm SPA fully loaded
    page.locator('a[href*="LT-260/list"]').first.wait_for(state="visible", timeout=30_000)

    # Verify authToken in localStorage
    expect(page.locator("body")).to_be_visible()  # ensure page is ready
    token = page.evaluate("() => localStorage.getItem('authToken')")
    assert token, "authToken not set in localStorage after staff login"

    context.storage_state(path=str(auth_path))
    context.close()
    browser.close()


@pytest.fixture(scope="session")
def auth_setup(playwright: Playwright):
    """Run auth setup once per session for both portals."""
    _ensure_public_auth(playwright)
    _ensure_staff_auth(playwright)


@pytest.fixture(scope="session")
def browser_instance(playwright: Playwright, auth_setup) -> Browser:
    """Single browser instance shared across the entire E2E test session."""
    browser = playwright.chromium.launch(headless=headless, slow_mo=slow_mo)
    yield browser
    browser.close()


@pytest.fixture(scope="session")
def public_context(browser_instance: Browser) -> BrowserContext:
    """Browser context with Public Portal auth state (session-scoped, shared)."""
    context = browser_instance.new_context(storage_state=str(PUBLIC_AUTH_PATH))
    yield context
    context.close()


@pytest.fixture(scope="session")
def staff_context(browser_instance: Browser) -> BrowserContext:
    """Browser context with Staff Portal auth state (session-scoped, shared)."""
    context = browser_instance.new_context(storage_state=str(STAFF_AUTH_PATH))
    yield context
    context.close()


# ─── Function-scoped context fixtures (fresh per test) ───

@pytest.fixture
def fresh_public_context(browser_instance: Browser) -> BrowserContext:
    """Fresh Public Portal context per test — isolated cookies/storage."""
    context = browser_instance.new_context(storage_state=str(PUBLIC_AUTH_PATH))
    yield context
    context.close()


@pytest.fixture
def fresh_staff_context(browser_instance: Browser) -> BrowserContext:
    """Fresh Staff Portal context per test — isolated cookies/storage."""
    context = browser_instance.new_context(storage_state=str(STAFF_AUTH_PATH))
    yield context
    context.close()


@pytest.fixture
def download_staff_context(browser_instance: Browser, tmp_path) -> BrowserContext:
    """Staff Portal context with download support — saves files to tmp_path."""
    context = browser_instance.new_context(
        storage_state=str(STAFF_AUTH_PATH),
        accept_downloads=True,
    )
    yield context
    context.close()


# ─── Multi-user auth helpers ───

@pytest.fixture(scope="session")
def public_user_b_context(playwright: Playwright, browser_instance: Browser) -> BrowserContext:
    """Browser context for secondary Public Portal user (User B)."""
    if not ENV.PUBLIC_USER_B_USERNAME:
        pytest.skip("PUBLIC_USER_B_USERNAME not configured in .env")
    user_b_auth = AUTH_DIR / "public-portal-user-b.json"
    _ensure_public_auth(
        playwright,
        username=ENV.PUBLIC_USER_B_USERNAME,
        password=ENV.PUBLIC_USER_B_PASSWORD,
        path=user_b_auth,
    )
    context = browser_instance.new_context(storage_state=str(user_b_auth))
    yield context
    context.close()


@pytest.fixture(scope="session")
def staff_user_b_context(playwright: Playwright, browser_instance: Browser) -> BrowserContext:
    """Browser context for secondary Staff Portal user (User B)."""
    if not ENV.STAFF_USER_B_USERNAME:
        pytest.skip("STAFF_USER_B_USERNAME not configured in .env")
    user_b_auth = AUTH_DIR / "staff-portal-user-b.json"
    _ensure_staff_auth(
        playwright,
        username=ENV.STAFF_USER_B_USERNAME,
        password=ENV.STAFF_USER_B_PASSWORD,
        path=user_b_auth,
    )
    context = browser_instance.new_context(storage_state=str(user_b_auth))
    yield context
    context.close()
