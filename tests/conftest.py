import os
import re
import pytest
from pathlib import Path
from playwright.sync_api import Browser, BrowserContext, Page


_AUTH_BASE = Path(__file__).resolve().parent.parent / "auth"

# The system under test is NC-only, and forms capture times in the BROWSER's timezone
# (LT-263 Sale Time, LT-262A Sale Hour). Running from a machine in another zone skews
# the value that lands on the generated PDF — a live IST run put 10:00 AM on the form
# and 23:30 on the LT-263 PDF. Pin every context to NC time so runs are portable and
# any Sale Hour finding is a real defect, not a laptop-location artifact.
NC_TIMEZONE = "America/New_York"


def pytest_collection_modifyitems(items):
    """Force the staff-portal logout phase to run dead last.

    test_e2e_063's phase 19 (`test_phase19_dmv_user_logout`) logs out, which
    invalidates the shared staff session SERVER-SIDE. pytest's fixture/param
    reorderer otherwise floats some `test_phase14_listing_behaviour[...]` cases
    after it (visible in `--collect-only`), and they then fail on the killed
    session. A stable sort that only lifts the logout item(s) to the end fixes it
    without disturbing any other ordering; it's a no-op for runs that don't
    collect that test.
    """
    items.sort(key=lambda it: 1 if "test_phase19_dmv_user_logout" in it.nodeid else 0)


def _auth_dir() -> Path:
    # Read at fixture-call time so --env flag is already applied via pytest_configure
    return _AUTH_BASE / os.getenv("NSM_ENV", "qa")


def _new_context(browser: Browser, auth_file: str) -> BrowserContext:
    ctx = browser.new_context(
        storage_state=str(_auth_dir() / auth_file),
        timezone_id=NC_TIMEZONE,
    )
    # QA/STAGE page loads have been running 15-25s under normal conditions
    # (Angular bundle + background polling), which leaves little headroom under
    # Playwright's 30s default action timeout. Raise it so a slow-but-working
    # page doesn't read as a failure; call sites with their own explicit
    # timeout= are unaffected. Bumped again 2026-08-21: after a full day of
    # automated runs against the shared STAGE test accounts, listing/search
    # queries (VIN search, correspondence tables) were seen exceeding even 60s
    # under accumulated test-data volume.
    ctx.set_default_timeout(90_000)
    return ctx


@pytest.fixture(scope="class")
def public_context(browser: Browser) -> BrowserContext:
    ctx = _new_context(browser, "public-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def staff_context(browser: Browser) -> BrowserContext:
    ctx = _new_context(browser, "staff-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def public_user_b_context(browser: Browser) -> BrowserContext:
    ctx = _new_context(browser, "public-portal-user-b.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def lsa_context(browser: Browser) -> BrowserContext:
    ctx = _new_context(browser, "lsa-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def fiscal_context(browser: Browser) -> BrowserContext:
    ctx = _new_context(browser, "fiscal-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def individual_public_context(browser: Browser) -> BrowserContext:
    ctx = _new_context(browser, "individual-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def individual_public_user_b_context(browser: Browser) -> BrowserContext:
    """Second individual public user (INDIVIDUAL_PUBLIC_USER_B_* — "Bowers" on QA).

    Distinct from public_user_b_context, which is a BUSINESS account
    (mora333@yopmail.com / Kelly Sherk). This one is an individual submitter whose
    registered email is a mailinator.com address (bowers@mailinator.com), used by
    E2E-064 to verify the real correspondence emails per phase.

    Regenerate the session with:  python scripts/save_individual_user_b_auth.py
    """
    ctx = _new_context(browser, "individual-portal-user-b.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def fresh_public_context(browser: Browser) -> BrowserContext:
    """Separate public portal context — same auth as public_context but a new session instance."""
    ctx = _new_context(browser, "public-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="class")
def public_user_c_context(browser: Browser) -> BrowserContext:
    """E2E-055 context — reuses the public-portal.json (User A) session; no separate User C account exists."""
    ctx = _new_context(browser, "public-portal.json")
    yield ctx
    ctx.close()


@pytest.fixture(scope="session")
def staff_session_context(browser: Browser) -> BrowserContext:
    """One staff-authenticated context for the whole session (see staff_page)."""
    ctx = _new_context(browser, "staff-portal.json")
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
