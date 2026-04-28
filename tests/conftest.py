import pytest
from pathlib import Path
from playwright.sync_api import Browser, BrowserContext

AUTH_DIR = Path(__file__).resolve().parent.parent / "auth"


@pytest.fixture(scope="class")
def public_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "public-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def staff_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "staff-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def public_user_b_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "public-portal-user-b.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def lsa_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "lsa-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def fiscal_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "fiscal-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def individual_public_context(browser: Browser) -> BrowserContext:
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "individual-portal.json"))
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def fresh_public_context(browser: Browser) -> BrowserContext:
    """Separate public portal context — same auth as public_context but a new session instance."""
    ctx = browser.new_context(storage_state=str(AUTH_DIR / "public-portal.json"))
    yield ctx
    ctx.close()
