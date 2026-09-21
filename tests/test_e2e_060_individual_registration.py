"""
E2E-060: Individual Registration — Public Portal (End-to-End)

Full registration flow for a new Individual on the NSM Public Portal.

Phases:
  1. [Public Portal]  Click Register → select Individual → fill profile form
                      → keep entered address at the Address Suggestions dialog
                      → agree to Facility Participation → Save
                      → assert "Your profile details have been successfully registered."
  2. [MyNCID]         Sign In with NCID → Create an Account → Individual → Continue
                      → fill the account form (username, name, email, NANP mobile,
                      password + confirm password)
                      → REGISTER → assert the account-created confirmation
                      ("Verify your email — we sent a verification link…", or the
                      older "Registration Successful" wording)
  3. [Mailinator]     Open the mailinator.com public inbox for EMAIL_USER → find the
                      MyNCID verification email → extract the link after "If the link
                      does not work..." → follow it → assert "Account Created".
                      SKIPS (not fails) only if Mailinator itself is unreachable /
                      rate-limited — that is infra, not an NSM/NCID defect.
  4. [Public Portal]  Sign in with NCID → username → Sign In → password → Sign In
                      → assert successful dashboard redirect.
                      SKIPS if phase 3 skipped (the account is still unverified).
  5. [Public Portal]  (still logged in from phase 4) hover the header account name
                      → My Profile → ACH section → fill Account Name / random
                      Account Type / 9-digit routing / 17-digit account number
                      → Save → confirm YES on the reconfirmation modal
                      → assert the success toast → Add Funds → enter a 3-digit
                      amount → Save → assert the success toast and that the added
                      amount is shown on the page.

The four phases share module-level test data and must run in file order — phase N
depends on the account state produced by phase N-1.

All four phases drive ONE browser page (the class-scoped `reg_page` fixture) and
navigate it between the portal, MyNCID and mailinator. Nothing here needs isolation:
the phases are a single user's continuous journey, and a fresh context per phase
only cost a cold Angular boot each time.

Environment: the portal URL comes from `.env.<NSM_ENV>` (`PUBLIC_PORTAL_URL`),
selected with `pytest --env qa|uat|stage`. Phases 1 and 4 use whatever host that
URL points at; phases 2 and 3 hit the shared MyNCID pre-prod IdP and mailinator.com,
which are the same across every non-prod environment. No stored auth is used —
each run registers a brand-new account, so `reg_page` builds its own context
instead of loading an `auth/<env>/*.json` session.
"""

import os
import re
import random
import string
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, expect

from src.config.env import ENV
from src.pages.public_portal.registration_page import (
    NSMRegistrationPage,
    NSMIndividualRegistrationPage,
    NCIDRegistrationPage,
    NCIDLoginPage,
    expect_ncid_account_activated,
    wait_for_portal_ready,
    safe_body_text,
    _poll_for_text,
)


# ─── Shared test data (consistent across all 4 phases) ───────────────────────

_SUFFIX = "".join(random.choices(string.digits, k=6))
FIRST_NAME = "NSMTest"
LAST_NAME = "Auto" + "".join(random.choices(string.ascii_lowercase, k=4))
EMAIL_USER = f"nsmtest{_SUFFIX}"          # mailinator public inbox name (local part)
EMAIL = f"{EMAIL_USER}@mailinator.com"    # Mailinator public inbox — no reCAPTCHA on reads
STREET_ADDRESS = "123 Main Street"
ZIP_CODE = "27601"                         # Raleigh, NC — auto-populates city/state
# MyNCID's Mobile Number field runs NANP validation ("not a valid US number"
# otherwise), so the central-office code must not start with 0 or 1 — the old
# 919-123-4567 failed on the "123". 919-888-xxxx is format-valid and unassigned.
PHONE = "9198887766"
# Fixed per project convention — every NSM test account uses this password (it is
# the `.env.*` PUBLIC_PORTAL_PASSWORD value). MyNCID's Individual/Citizen form
# requires 14–64 chars with an upper / lower / digit / special; this is exactly 14.
# Read from the env (never committed — this repo is public). REGISTRATION_PASSWORD
# overrides it for the new account only.
PASSWORD = os.getenv("REGISTRATION_PASSWORD") or ENV.PUBLIC_PORTAL_PASSWORD

# Username = last name, padded to at least 6 characters with digits
_raw_username = LAST_NAME
while len(_raw_username) < 6:
    _raw_username += str(random.randint(0, 9))
USERNAME = _raw_username

PP_SIGNIN_URL = ENV.PUBLIC_PORTAL_URL
# The portal host is environment-specific — nsm-qa-public.nc.verifi.dev on QA,
# nsm-uat-public.nc.verifi.dev on UAT, public-nss-stage.verifi-nc.com on stage.
# Phase 4's "we've landed back off the MyNCID IdP" check keys off whatever host
# the configured sign-in URL uses rather than a hard-coded domain, so the same
# test runs unchanged against every environment.
PORTAL_HOST = urlparse(PP_SIGNIN_URL).netloc

# Set by phase 3 when Mailinator itself is unreachable / rate-limited; phase 4
# reads it to skip (rather than fail) a login that can't succeed against an
# unverified NCID account.
_EMAIL_VERIFICATION_SKIPPED = False

# ── Phase 5 — ACH drawdown account ─────────────────────────────────────────
# Bank routing / account numbers must NOT start with a zero (project rule — a
# leading-zero account number gets mangled by downstream numeric handling).
ACH_ACCOUNT_NAME = f"NSM Auto {_SUFFIX}"
ACH_ACCOUNT_NUMBER = str(random.randint(1, 9)) + "".join(random.choices(string.digits, k=16))
ACH_FUND_AMOUNT = str(random.randint(100, 999))     # a 3-digit amount


def _aba_routing_number() -> str:
    """A 9-digit routing number with a valid ABA check digit, never starting with 0.

    First digit 1–3 keeps it inside a plausible Federal Reserve district prefix so
    a form that validates the checksum (or the district) still accepts it.
    """
    body = [random.randint(1, 3), random.randint(0, 9)] + [random.randint(0, 9) for _ in range(6)]
    checksum = (
        3 * (body[0] + body[3] + body[6])
        + 7 * (body[1] + body[4] + body[7])
        + (body[2] + body[5])
    )
    check_digit = (10 - checksum % 10) % 10
    return "".join(map(str, body)) + str(check_digit)


ACH_ROUTING_NUMBER = _aba_routing_number()

# Disposable-mail sites (and some bot filters) challenge obvious automation, so the
# one shared context runs a stock Chrome UA with navigator.webdriver masked.
# Harmless for the portal / MyNCID legs.
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@pytest.fixture(scope="class")
def reg_page(browser: Browser) -> Page:
    """One page shared by every phase of the registration journey."""
    ctx = browser.new_context(user_agent=_CHROME_UA)
    ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    page = ctx.new_page()
    yield page
    ctx.close()


def _goto_portal(page: Page):
    """Put the shared page on the portal sign-in screen, rendered and ready.

    The sign-in route redirects (/ncdot-nsm-signin → /ncshp-nss-signin) behind a
    loading spinner; the page objects' `wait_for_portal_ready` is what makes it
    interactive, so callers that click immediately are safe.
    """
    page.goto(PP_SIGNIN_URL, timeout=90_000, wait_until="domcontentloaded")


@pytest.mark.e2e
@pytest.mark.registration
class TestE2E060IndividualRegistration:

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 1 — NSM Individual profile registration
    # ─────────────────────────────────────────────────────────────────────────

    def test_phase_1_register_individual_profile(self, reg_page: Page):
        """
        Go to sign-in page → Register → Individual → fill form →
        keep original address → agree to Facility Participation Agreement → Save →
        assert toast 'Your profile details have been successfully registered.'
        """
        print(
            f"\n>>> Test data | email={EMAIL} username={USERNAME} "
            f"phone={PHONE} password={PASSWORD}"
        )
        _goto_portal(reg_page)

        nsm = NSMRegistrationPage(reg_page)
        nsm.click_register_on_signin_page()
        nsm.select_individual()

        form = NSMIndividualRegistrationPage(reg_page)
        form.fill_first_name(FIRST_NAME)
        form.fill_last_name(LAST_NAME)
        form.fill_email(EMAIL)
        form.fill_address(STREET_ADDRESS)
        form.fill_zip(ZIP_CODE)
        form.fill_phone(PHONE)

        # ZIP 27601 must back-fill the NC/Raleigh location before submitting.
        assert form.city_value() == "Raleigh", (
            f"ZIP {ZIP_CODE} should auto-populate City=Raleigh, "
            f"got {form.city_value()!r}"
        )
        assert form.state_value() == "North Carolina", (
            f"ZIP {ZIP_CODE} should auto-populate State=North Carolina, "
            f"got {form.state_value()!r}"
        )

        form.click_next()
        form.check_facility_participation_agreement()
        form.click_save()
        form.expect_profile_registered_toast()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2 — MyNCID Individual account creation
    # ─────────────────────────────────────────────────────────────────────────

    def test_phase_2_create_ncid_account(self, reg_page: Page):
        """
        Sign In with NCID → Create an Account → Individual → Continue →
        fill the account form → REGISTER → assert 'Registration Successful'.
        """
        print(
            f"\n>>> Phase 2 | email={EMAIL} username={USERNAME} "
            f"phone={PHONE} password={PASSWORD}"
        )
        _goto_portal(reg_page)

        ncid = NCIDRegistrationPage(reg_page)
        ncid.click_register_now()
        ncid.select_individual_account_type()

        ncid.fill_first_name(FIRST_NAME)
        ncid.fill_last_name(LAST_NAME)
        ncid.fill_username(USERNAME)
        ncid.fill_email(EMAIL)
        # The Individual/Citizen form collects a Mobile Number (NANP-validated)
        # and — on QA/UAT — a required Confirm Password. There is no confirm-email.
        ncid.fill_mobile_number(PHONE)
        ncid.fill_password(PASSWORD)
        ncid.fill_confirm_password(PASSWORD)

        ncid.click_register()
        ncid.expect_registration_successful()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 3 — Email verification via Mailinator
    # ─────────────────────────────────────────────────────────────────────────

    def test_phase_3_verify_email_via_mailinator(self, reg_page: Page):
        """
        Open the mailinator.com public inbox for EMAIL_USER, find the MyNCID
        verification email, extract the link after the 'If the link does not
        work...' marker, follow it, and assert the account is activated.

        Only Mailinator being unreachable / rate-limited raises pytest.skip (infra,
        not a product defect); an email that never arrives is a real failure.
        """
        _verify_email_via_mailinator(reg_page, EMAIL_USER)

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 4 — Login with new NCID credentials
    # ─────────────────────────────────────────────────────────────────────────

    def test_phase_4_login_with_new_credentials(self, reg_page: Page):
        """
        Go to sign-in page → Sign in with NCID → username → Sign In →
        password → Sign In → assert redirect to dashboard.
        """
        if _EMAIL_VERIFICATION_SKIPPED:
            pytest.skip(
                "phase 3 (email verification) was skipped because Mailinator was "
                "unavailable, so the NCID account is unverified and this login "
                "cannot complete — re-run when Mailinator is reachable"
            )
        _goto_portal(reg_page)

        login = NCIDLoginPage(reg_page)
        login.start_from_portal()
        login.sign_in(USERNAME, PASSWORD)

        # Back on the portal (off the IdP) — the SAML hand-back lands on
        # /authentication/validate before routing onward. Match the configured
        # portal host so this holds on QA, UAT and stage alike.
        expect(reg_page).to_have_url(
            re.compile(re.escape(PORTAL_HOST), re.I), timeout=60_000
        )
        wait_for_portal_ready(reg_page)

        body = safe_body_text(reg_page)
        print(f"\n>>> Phase 4 landed on {reg_page.url}\n{body[:500]}")

        # A profile registered in phase 1 under the same email must be recognised.
        assert "profile is not yet registered" not in body.lower(), (
            "Portal did not link the NCID account to the profile registered in "
            f"phase 1 (email={EMAIL}). Landed on {reg_page.url} with: {body[:300]!r}"
        )
        # Deliberately narrow: the portal's own sign-in route is /ncshp-nss-signin,
        # so a bounce back to it must not satisfy "logged in".
        expect(reg_page).to_have_url(
            re.compile(r"dashboard|select.company", re.I),
            timeout=60_000,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 5 — ACH drawdown account + Add Funds
    # ─────────────────────────────────────────────────────────────────────────

    def test_phase_5_drawdown_account_ach(self, reg_page: Page):
        """
        Still logged in from phase 4:
          hover the header account name → My Profile → ACH section →
          fill Account Name / random Account Type / 9-digit routing /
          17-digit account number → Save → YES on the reconfirmation modal →
          assert the success toast → Add Funds → enter a 3-digit amount → Save →
          assert the success toast and that the added amount shows on the page.
        """
        if _EMAIL_VERIFICATION_SKIPPED:
            pytest.skip(
                "phase 4 login did not run (Mailinator was unavailable in phase 3), "
                "so there is no authenticated session for the ACH flow"
            )

        page = reg_page
        if "signin" in page.url.lower() or PORTAL_HOST not in page.url:
            # Phase 4 authenticated this context; the portal should route straight
            # to the dashboard without another NCID round-trip.
            _goto_portal(page)
        wait_for_portal_ready(page)

        picked_type = _open_ach_and_add_account(page)
        print(f"\n>>> Phase 5 ACH: name={ACH_ACCOUNT_NAME!r} type={picked_type!r} "
              f"routing={ACH_ROUTING_NUMBER} account=****{ACH_ACCOUNT_NUMBER[-4:]}")

        assert _poll_for_text(page, ("success", "saved", "added", "created"), 30_000), (
            "No success toast after saving the ACH drawdown account. Page text:\n"
            f"{safe_body_text(page)[:600]!r}"
        )

        shown = _add_funds(page, ACH_FUND_AMOUNT)
        print(f"\n>>> Phase 5 Add Funds: amount={ACH_FUND_AMOUNT} shown_on_ui={shown!r}")

        assert _poll_for_text(page, ("success", "fund", "added"), 30_000), (
            "No success toast after Add Funds. Page text:\n"
            f"{safe_body_text(page)[:600]!r}"
        )
        body = safe_body_text(page)
        assert re.search(rf"\$?\s*{re.escape(ACH_FUND_AMOUNT)}(\.0{{1,2}})?\b", body), (
            f"Added fund amount {ACH_FUND_AMOUNT} is not visible on the UI after the "
            f"Add Funds save. Page text:\n{body[:600]!r}"
        )


# ─── Mailinator public-inbox helper ─────────────────────────────────────────

_MAILINATOR_INBOX_URL = "https://www.mailinator.com/v4/public/inboxes.jsp?to={inbox}"
_SUBJECT_RE = re.compile(r"NCID|Register|Activate|Verif|nc\.gov", re.I)


def _dismiss_cookie_banner(page: Page):
    """Best-effort dismissal of Mailinator's cookie-consent banner (never fatal)."""
    for sel in (
        ".osano-cm-accept-all",
        "#onetrust-accept-btn-handler",
        'button:has-text("Accept")',
        'button:has-text("AGREE")',
    ):
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1_000):
                btn.click(timeout=2_000)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def _skip_if_mailinator_unavailable(page: Page, email_user: str):
    """pytest.skip (don't fail) when Mailinator itself is down / rate-limiting us.

    A reachable-but-empty inbox is NOT this case — that stays a real "email never
    arrived" failure. Only an explicit Mailinator error/limit page skips, and it
    records `_EMAIL_VERIFICATION_SKIPPED` so phase 4 skips too.
    """
    try:
        body = page.evaluate("() => document.body ? document.body.innerText : ''").lower()
    except Exception:
        body = ""
    if any(s in body for s in (
        "too many requests", "rate limit", "temporarily unavailable",
        "503 service", "error 429", "request blocked",
    )):
        global _EMAIL_VERIFICATION_SKIPPED
        _EMAIL_VERIFICATION_SKIPPED = True
        pytest.skip(
            f"mailinator.com is rate-limiting / unavailable for inbox '{email_user}' — "
            "the inbox cannot be read. This is a Mailinator infra limit, not an "
            "NSM/NCID defect. Re-run later."
        )


def _verify_email_via_mailinator(page: Page, email_user: str, retries: int = 12):
    """
    Drive the shared page to the mailinator.com public inbox for email_user, poll
    until the MyNCID verification email arrives, extract the activation URL from
    the mail body, and follow it in the same tab to assert activation succeeded.
    """
    inbox_url = _MAILINATOR_INBOX_URL.format(inbox=email_user)

    row = None
    for attempt in range(retries):
        try:
            page.goto(inbox_url, timeout=60_000, wait_until="domcontentloaded")
        except Exception:
            page.wait_for_timeout(5_000)
            continue
        page.wait_for_timeout(2_500)
        if attempt == 0:
            _dismiss_cookie_banner(page)
        _skip_if_mailinator_unavailable(page, email_user)

        # The public inbox is a table; the MyNCID mail is the row whose subject
        # matches. `has_text` on <tr> is specific enough given the subject regex.
        try:
            candidate = page.locator("tr", has_text=_SUBJECT_RE).first
            candidate.wait_for(state="visible", timeout=4_000)
            row = candidate
            break
        except Exception:
            if attempt < retries - 1:
                time.sleep(10)

    if row is None:
        _skip_if_mailinator_unavailable(page, email_user)
        raise AssertionError(
            f"MyNCID verification email not found in mailinator inbox '{email_user}' "
            f"after {retries} attempts (~{retries * 12}s)"
        )

    row.click()
    page.wait_for_timeout(3_000)
    try:
        page.wait_for_selector("#html_msg_body", timeout=8_000)
    except Exception:
        pass  # body may render without the expected id — the evaluate below copes

    # Pull the activation URL out of the rendered message. Mailinator renders the
    # HTML body inside an iframe (#html_msg_body); fall back to any iframe, then to
    # the page itself. Preferred anchor is the text after "If the link does not
    # work"; a verify-ish <a href> is the fallback. Reading the URL (rather than
    # clicking) keeps the flow on this one tab.
    activation_url = page.evaluate(r"""() => {
        const pickFrom = (doc) => {
            if (!doc || !doc.body) return null;
            const html = doc.body.innerHTML || '';
            const idx = html.toLowerCase().indexOf('if the link does not work');
            if (idx !== -1) {
                const m = html.substring(idx, idx + 1200).match(/https?:\/\/[^\s"'<>]+/);
                if (m) return m[0].replace(/[."'>\]]+$/, '');
            }
            const a = doc.querySelector(
                'a[href*="code-verification"], a[href*="activate"], '
                + 'a[href*="verify"], a[href*="myncid"]'
            );
            if (a) return a.getAttribute('href');
            const any = Array.from(doc.querySelectorAll('a[href^="http"]'))
                .map(x => x.getAttribute('href'))
                .find(h => /verif|activate|code-verification|myncid/i.test(h));
            return any || null;
        };
        const frames = [document.getElementById('html_msg_body'),
                        ...document.querySelectorAll('iframe')];
        for (const f of frames) {
            if (!f) continue;
            let doc = null;
            try { doc = f.contentDocument || (f.contentWindow && f.contentWindow.document); }
            catch (e) { doc = null; }
            const u = pickFrom(doc);
            if (u) return u;
        }
        return pickFrom(document);
    }""")

    assert activation_url, (
        f"Could not extract an activation URL from the MyNCID email in mailinator "
        f"inbox '{email_user}'"
    )
    print(f"\n>>> Activation URL: {activation_url}")

    page.goto(activation_url, timeout=60_000, wait_until="domcontentloaded")
    expect_ncid_account_activated(page)


# ─── Phase 5 — ACH drawdown-account helpers ─────────────────────────────────

def _dump_controls(page: Page, label: str):
    """Print the visible buttons / fields / tabs on the page.

    A first-run selector-discovery aid for the ACH screens, which this suite has
    not driven before — keep the output; it is cheap and makes a locator miss
    self-diagnosing.
    """
    try:
        info = page.evaluate(r"""() => {
            const vis = el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            };
            const txt = el => (el.innerText || el.getAttribute('aria-label') || '')
                .trim().replace(/\s+/g, ' ').slice(0, 60);
            const uniq = a => [...new Set(a.filter(Boolean))];
            return {
                buttons: uniq([...document.querySelectorAll('button,[role=button]')].filter(vis).map(txt)),
                links: uniq([...document.querySelectorAll('a')].filter(vis).map(txt)).slice(0, 40),
                fields: uniq([...document.querySelectorAll('input,mat-select,textarea,select')].map(
                    e => e.getAttribute('aria-label') || e.getAttribute('formcontrolname')
                         || e.getAttribute('name') || e.getAttribute('placeholder') || e.id || '')),
                dialogTitles: uniq([...document.querySelectorAll(
                    'mat-dialog-container h1,mat-dialog-container h2,mat-dialog-container h3,'
                    + '[role=dialog] h1,[role=dialog] h2')].map(txt)),
                tabs: uniq([...document.querySelectorAll(
                    '[role=tab],.mat-tab-label,.mat-mdc-tab,.mat-mdc-tab-link')].map(txt)),
            };
        }""")
    except Exception as exc:  # navigation mid-evaluate, etc.
        info = f"<dump failed: {exc}>"
    print(f"\n>>> [{label}] url={page.url}\n>>> [{label}] {info}\n")


def _first_visible(page: Page, *locators, timeout_ms: int = 8_000):
    """Return the first of `locators` whose `.first` is visible within the budget."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for loc in locators:
            try:
                cand = loc.first
                if cand.is_visible():
                    return cand
            except Exception:
                pass
        page.wait_for_timeout(400)
    return None


def _fill_first(page: Page, selectors, value: str) -> bool:
    """Fill the first matching, visible selector from `selectors`. Returns success."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.is_visible():
                loc.click()
                loc.fill("")
                loc.fill(value)
                page.wait_for_timeout(250)
                return True
        except Exception:
            pass
    return False


def _open_ach_and_add_account(page: Page) -> str:
    """Hover the header account name → My Profile → ACH section, then fill and save
    the drawdown-account form (answering YES on the reconfirmation modal).

    Returns the Account Type label that was randomly chosen.
    """
    _dump_controls(page, "phase5-dashboard")

    # ── header account name → My Profile ────────────────────────────────────
    name_trigger = page.get_by_text(
        re.compile(rf"{re.escape(FIRST_NAME)}\s+{re.escape(LAST_NAME)}", re.I)
    ).first
    try:
        name_trigger.hover(timeout=10_000)
    except Exception:
        pass
    page.wait_for_timeout(1_000)

    profile_item = _first_visible(
        page,
        page.get_by_role("menuitem", name=re.compile(r"my\s*profile", re.I)),
        page.get_by_role("link", name=re.compile(r"my\s*profile", re.I)),
        page.get_by_text(re.compile(r"^\s*my\s*profile\s*$", re.I)),
        timeout_ms=4_000,
    )
    if profile_item is None:
        try:
            name_trigger.click(timeout=5_000)
            page.wait_for_timeout(1_000)
        except Exception:
            pass
        profile_item = _first_visible(
            page,
            page.get_by_role("menuitem", name=re.compile(r"my\s*profile", re.I)),
            page.get_by_text(re.compile(r"^\s*my\s*profile\s*$", re.I)),
            timeout_ms=4_000,
        )
    assert profile_item is not None, (
        "Could not find the 'My Profile' menu item after hovering / clicking the "
        "header account name"
    )
    profile_item.click()
    page.wait_for_timeout(3_000)
    wait_for_portal_ready(page)
    _dump_controls(page, "phase5-my-profile")

    # ── ACH section ────────────────────────────────────────────────────────
    ach_tab = _first_visible(
        page,
        page.get_by_role("tab", name=re.compile(r"\bACH\b|drawdown", re.I)),
        page.get_by_role("link", name=re.compile(r"\bACH\b|drawdown", re.I)),
        page.locator('button:has-text("ACH"), a:has-text("ACH")'),
        page.get_by_text(re.compile(r"\bACH\b", re.I)),
        timeout_ms=10_000,
    )
    assert ach_tab is not None, "Could not find the ACH / Drawdown Account section on My Profile"
    ach_tab.click()
    page.wait_for_timeout(3_000)
    _dump_controls(page, "phase5-ach-section")

    # An existing account may already be present — click an Add / New control first.
    add_ctrl = _first_visible(
        page,
        page.get_by_role("button", name=re.compile(r"add.*account|add ach|new account|add drawdown", re.I)),
        page.locator('button:has-text("Add Account"), button:has-text("Add ACH")'),
        timeout_ms=3_000,
    )
    if add_ctrl is not None:
        add_ctrl.click()
        page.wait_for_timeout(1_500)
        _dump_controls(page, "phase5-ach-form")

    # ── fill the form ──────────────────────────────────────────────────────
    # Exact aria-labels observed on QA: the form also has "Reenter …" confirm
    # fields for both the routing and the account number — Save stays disabled
    # until every one (and Account Type) is filled and matching.
    assert _fill_first(page, [
        'input[aria-label="Account Name*"]',
        'input[aria-label*="Account Name" i]',
        'input[formcontrolname*="ccountName" i]',
    ], ACH_ACCOUNT_NAME), "ACH 'Account Name' field not found"

    picked_type = _select_random_account_type(page)

    assert _fill_first(page, [
        'input[aria-label="Bank Routing Number*"]',
        'input[aria-label*="Bank Routing Number" i]',
    ], ACH_ROUTING_NUMBER), "ACH 'Bank Routing Number' field not found"
    assert _fill_first(page, [
        'input[aria-label="Reenter Bank Routing Number*"]',
        'input[aria-label*="Reenter Bank Routing" i]',
    ], ACH_ROUTING_NUMBER), "ACH 'Reenter Bank Routing Number' field not found"

    assert _fill_first(page, [
        'input[aria-label="Bank Account Number*"]',
        'input[aria-label*="Bank Account Number" i]',
    ], ACH_ACCOUNT_NUMBER), "ACH 'Bank Account Number' field not found"
    assert _fill_first(page, [
        'input[aria-label="Reenter Bank Account Number*"]',
        'input[aria-label*="Reenter Bank Account" i]',
    ], ACH_ACCOUNT_NUMBER), "ACH 'Reenter Bank Account Number' field not found"

    # ── Save → YES on the reconfirmation modal ─────────────────────────────
    page.wait_for_timeout(500)
    save_btn = _first_visible(
        page,
        page.locator('button:has-text("Save")').filter(has_not_text="Saved"),
        page.get_by_role("button", name=re.compile(r"^\s*save\s*$", re.I)),
        timeout_ms=8_000,
    )
    assert save_btn is not None, "ACH form 'Save' button not found"
    try:
        expect(save_btn).to_be_enabled(timeout=10_000)
    except Exception:
        _dump_controls(page, "phase5-ach-save-still-disabled")
        raise AssertionError(
            "ACH 'Save' stayed disabled after filling every field — a validation "
            "rule rejected one of the values (see the dump above)"
        )
    save_btn.click()
    page.wait_for_timeout(1_500)

    yes_btn = _first_visible(
        page,
        page.locator('mat-dialog-container button:has-text("Yes")'),
        page.locator('[role=dialog] button:has-text("Yes")'),
        page.get_by_role("button", name=re.compile(r"^\s*yes\s*$", re.I)),
        timeout_ms=10_000,
    )
    assert yes_btn is not None, "Reconfirmation modal 'YES' button not found after Save"
    yes_btn.click()
    page.wait_for_timeout(2_500)
    return picked_type


def _select_random_account_type(page: Page) -> str:
    """Open the Account Type control and pick one option at random. Returns its label."""
    sel = _first_visible(
        page,
        page.locator('mat-select[aria-label="Account Type*"]'),
        page.locator('mat-select[aria-label*="Account Type" i]'),
        page.locator('mat-select[formcontrolname*="ccountType" i]'),
        page.get_by_label(re.compile(r"account type", re.I)),
        timeout_ms=8_000,
    )
    assert sel is not None, "ACH 'Account Type' dropdown not found"
    sel.click()
    page.wait_for_timeout(800)

    options = page.locator('mat-option, [role="option"]')
    count = options.count()
    assert count > 0, "'Account Type' opened but showed no options"
    idx = random.randrange(count)
    label = (options.nth(idx).inner_text() or "").strip()
    options.nth(idx).click()
    page.wait_for_timeout(500)
    return label


def _add_funds(page: Page, amount: str) -> bool:
    """Click Add Funds, enter `amount`, Save. Returns whether the amount then shows
    somewhere on the page.
    """
    funds_btn = _first_visible(
        page,
        page.get_by_role("button", name=re.compile(r"add\s*funds", re.I)),
        page.locator('button:has-text("Add Funds")'),
        timeout_ms=10_000,
    )
    assert funds_btn is not None, "'Add Funds' button not found"
    funds_btn.click()
    page.wait_for_timeout(2_000)
    _dump_controls(page, "phase5-add-funds")

    assert _fill_first(page, [
        'mat-dialog-container input[aria-label*="Amount" i]',
        '[role=dialog] input[aria-label*="Amount" i]',
        'mat-dialog-container input[formcontrolname*="mount" i]',
        'mat-dialog-container input[type="number"]',
        'mat-dialog-container input:not([type="hidden"])',
        'input[aria-label*="Amount" i]',
    ], amount), "'Amount' field not found in the Add Funds dialog"

    save_btn = _first_visible(
        page,
        page.locator('mat-dialog-container button:has-text("SAVE")'),
        page.locator('mat-dialog-container button:has-text("Save")'),
        page.locator('[role=dialog] button:has-text("Save")'),
        page.get_by_role("button", name=re.compile(r"^\s*save\s*$", re.I)),
        timeout_ms=8_000,
    )
    assert save_btn is not None, "'Save' button not found in the Add Funds dialog"
    save_btn.click()
    page.wait_for_timeout(3_000)

    body = safe_body_text(page)
    return bool(re.search(rf"\$?\s*{re.escape(amount)}(\.0{{1,2}})?\b", body))
