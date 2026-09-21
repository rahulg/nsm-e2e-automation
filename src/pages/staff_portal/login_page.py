"""
Staff Portal Login Page — Verifi SSO credential login.

`src/helpers/login_helper.py` has always imported StaffLoginPage from here, but the module
did not exist, so ANY import of login_helper raised ModuleNotFoundError. The only casualty in
practice is the small set of tests that need a genuine credential login rather than a stored
storage_state — notably NCNSS-521 TC_022 ("the highlight survives a real logout / login"),
which aborted mid-scenario on STAGE 2026-08-10 with:

    ModuleNotFoundError: No module named 'src.pages.staff_portal.login_page'

The flow below is the one proven by scripts/save_staff_auth.py, which logs in successfully on
qa/stage/uat: the portal's own login page hosts a "Log in with verifi" button that reveals an
inline credentials form. Two details are load-bearing and are why a naive fill() fails:

  * the SSO button renders a spinner while its config loads asynchronously — clicking before
    that spinner detaches is a silent no-op, because the click handler is not wired up yet;
  * the post-login redirect must be awaited before the caller inspects the page, otherwise the
    caller races it and sees the login URL.
"""

from playwright.sync_api import Page

from src.config.env import ENV


class StaffLoginPage:
    _SSO_SPAN = "//span[contains(text(),'Log in with')]"
    _LOGIN_ID = "input#loginId"
    _PASSWORD = "input#password-box-id"
    _SUBMIT = (
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Sign In"), button:has-text("Login"), '
        'button:has-text("Log In"), button:has-text("Sign on"), '
        'exp-button button'
    )
    _LANDED = "**/pages/ncdot-notice-and-storage/**"

    def __init__(self, page: Page):
        self.page = page

    def open(self):
        self.page.goto(ENV.STAFF_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            # This Angular app polls in the background, so networkidle is a settle-hint
            # rather than a precondition — never let it be what fails a login.
            self.page.wait_for_timeout(2000)
        self.page.wait_for_timeout(1500)

    def _reveal_credential_form(self):
        sso = self.page.locator(self._SSO_SPAN)
        sso.wait_for(state="visible", timeout=15_000)
        try:
            self.page.locator("button .loader").first.wait_for(state="detached", timeout=15_000)
        except Exception:
            pass
        sso.click()
        self.page.locator(self._LOGIN_ID).wait_for(state="visible", timeout=40_000)

    def login(self, username: str = None, password: str = None):
        """Log in with real credentials and wait for the post-login redirect to land."""
        username = username or ENV.STAFF_PORTAL_USERNAME
        password = password or ENV.STAFF_PORTAL_PASSWORD

        if self._LOGIN_ID not in (self.page.url or "") and not self.page.locator(
                self._LOGIN_ID).count():
            self.open()
            self._reveal_credential_form()

        self.page.locator(self._LOGIN_ID).fill(username)
        self.page.locator(self._PASSWORD).fill(password)
        self.page.wait_for_timeout(300)
        self.page.locator(self._SUBMIT).first.click()

        self.page.wait_for_url(self._LANDED, timeout=45_000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            self.page.wait_for_timeout(2000)

        if "/login" in self.page.url:
            raise AssertionError(
                f"EXPECTED: the staff portal to be reached after a credential login | "
                f"ACTUAL: still on the login page ({self.page.url})")
        return self.page
