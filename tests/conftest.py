import os
import re
import pytest
from pathlib import Path
from playwright.sync_api import Browser, BrowserContext, Page


_AUTH_BASE = Path(__file__).resolve().parent.parent / "auth"


def _auth_dir() -> Path:
    # Read at fixture-call time so --env flag is already applied via pytest_configure
    return _AUTH_BASE / os.getenv("NSM_ENV", "qa")


@pytest.fixture(scope="class")
def public_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(_auth_dir() / "public-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def staff_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(_auth_dir() / "staff-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def public_user_b_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(_auth_dir() / "public-portal-user-b.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def lsa_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(_auth_dir() / "lsa-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def fiscal_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(_auth_dir() / "fiscal-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def individual_public_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(_auth_dir() / "individual-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def fresh_public_context(browser: Browser) -> BrowserContext:
    """Separate public portal context — same auth as public_context but a new session instance."""
    ctx = browser.new_context(storage_state=str(_auth_dir() / "public-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def public_user_c_context(browser: Browser) -> BrowserContext:
    """E2E-055 context — reuses the public-portal.json (User A) session; no separate User C account exists."""
    ctx = browser.new_context(storage_state=str(_auth_dir() / "public-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="session")
def staff_session_context(browser: Browser) -> BrowserContext:
    """One staff-authenticated context for the whole session (see staff_page)."""
    ctx = browser.new_context(storage_state=str(_auth_dir() / "staff-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="session")
def staff_page(staff_session_context: BrowserContext) -> Page:
    """A single staff-portal tab shared for the whole session.

    Opening a new page per test reloads the Angular bundle cold every time. Tests
    that use this fixture load the dashboard once and then navigate in-app via the
    sidebar. Used by E2E-004; other tests keep their own per-class contexts.
    """
    from src.config.env import ENV  # imported lazily: NSM_ENV is set by pytest_configure

    dashboard_url = re.sub(
        r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
    )
    page = staff_session_context.new_page()
    page.goto(dashboard_url, timeout=60_000)
    page.wait_for_load_state("networkidle")
    yield page
    page.close()
