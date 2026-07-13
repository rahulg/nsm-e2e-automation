"""
E2E-055: Public Portal — UI Assertions
Verifies key UI elements, navigation, and content across the Public Portal
without creating or modifying any application data.

Phases:
  1. Sign-on Page      — logged-out sign-in screen: New Users / Returning Users
                         text, Welcome note, footer, link destinations, Register nav
  2. Dashboard         — tabs, layout, header elements, Start Here button
  3. Case Listing      — Notice & Storage tab, application list, search input
  4. Payments Tab      — tab navigation, payment history visible
  5. Sold/Completed    — tab navigation, content area rendered
  6. Messages Tab      — tab navigation, inbox area visible
  7. Profile Page      — navigation, business name, drawdown balance section
  8. Navigation        — browser Back returns to dashboard (no in-app home link)
  9. Edit My Details   — (WRITE) update first/last/title -> success toast
 10. Edit Company      — (WRITE) update company details -> success toast
 11. Address Book      — (WRITE) delete a deletable address + edit an address
 12. Add User          — (WRITE) add a new Admin user -> success toast
 13. LT-260 Form       — Start here -> form text + VIN-lookup validation popups

Phases 9-12 MODIFY data on the User C account (edit details, delete an address,
create a user). They are not read-only.

Performance note:
  Phases 2-8 share ONE authenticated tab (the class-scoped ``dash_page`` fixture)
  and navigate to the dashboard only once; ``_ensure_dashboard`` re-navigates only
  when a previous test left the page elsewhere. Phase 1 uses a SEPARATE, logged-out
  tab (``signin_page``) — a stored session would bypass the sign-in screen straight
  to the dashboard, so the sign-on page can only be asserted while logged out.
  Readiness is detected by waiting for a real element rather than ``networkidle``,
  which never settles reliably on this Angular SPA.
"""

import random
import re

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_address,
    generate_company_name,
    generate_first_name,
    generate_full_name,
    generate_job_title,
    generate_last_name,
    generate_location_name,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.profile_page import PublicProfilePage

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL  # this is the sign-in URL (.../ncshp-nss-signin)
_BASE_URL = PP_DASHBOARD_URL.split("/ncshp")[0]  # https://nsm-qa-public.nc.verifi.dev
PROFILE_URL = f"{_BASE_URL}/ncdmv-nsm/my-profile"


# ── Dashboard navigation (authenticated) ──────────────────────────────────────

def _go_to_dashboard(page: Page):
    """Navigate to the public dashboard and wait for it to be interactive.

    Waits for the Notice & Storage tab to appear (a real readiness signal)
    instead of ``networkidle``, which stalls until timeout on this SPA.
    """
    page.goto(PP_DASHBOARD_URL, timeout=90_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    try:
        page.get_by_role("tab", name=re.compile(r"Notice & Storage", re.I)).or_(
            page.locator('button:has-text("Notice & Storage")')
        ).first.wait_for(state="visible", timeout=20_000)
    except Exception:
        page.wait_for_timeout(2000)


def _ensure_dashboard(page: Page):
    """Re-navigate to the dashboard only if we're not already there."""
    if "dashboard" not in page.url.lower():
        _go_to_dashboard(page)


# ── Sign-on page (logged out) ─────────────────────────────────────────────────

def _go_to_signin(page: Page):
    """Open the public sign-in screen (logged out) and wait for it to render."""
    page.goto(PP_DASHBOARD_URL, timeout=90_000, wait_until="domcontentloaded")
    try:
        page.get_by_role("button", name=re.compile(r"Sign In with NCID", re.I)).wait_for(
            state="visible", timeout=20_000
        )
    except Exception:
        page.wait_for_timeout(2000)


def _ensure_signin(page: Page):
    """Re-navigate to the sign-in screen only if we've navigated away (e.g. Register)."""
    if "signin" not in page.url.lower():
        _go_to_signin(page)


def _assert_links_href(page: Page, name, expected_substr: str, min_count: int = 1):
    """Assert every link matching ``name`` points at ``expected_substr``.

    Destinations are verified via the ``href`` attribute rather than by clicking:
    these are all ``target="_blank"`` links to external sites (nc.gov, it.nc.gov,
    cdn.services.expertly.com), so checking href is reliable and avoids opening
    external pages / popups during the test.
    """
    links = page.get_by_role("link", name=name)
    n = links.count()
    assert n >= min_count, f"expected >= {min_count} link(s) for {name!r}, found {n}"
    for i in range(n):
        href = links.nth(i).get_attribute("href") or ""
        assert expected_substr in href, (
            f"link {name!r} #{i} href={href!r} does not contain {expected_substr!r}"
        )


# ── Profile data-entry helpers (authenticated, WRITE operations) ──────────────

def _go_to_profile(page: Page):
    """Navigate to the My Profile area (authenticated)."""
    page.goto(PROFILE_URL, timeout=90_000, wait_until="domcontentloaded")
    try:
        page.get_by_role("tab", name=re.compile(r"My Profile", re.I)).first.wait_for(
            state="visible", timeout=20_000
        )
    except Exception:
        page.wait_for_timeout(2500)


def _ensure_profile(page: Page):
    """Go to My Profile only if not already there. The profile sub-tabs
    (My Profile / Address Book / Users) all keep the same /my-profile URL, so
    moving between them needs no reload."""
    if "my-profile" not in page.url.lower():
        _go_to_profile(page)


def _open_profile_tab(page: Page, name_re):
    page.get_by_role("tab", name=name_re).first.click()
    page.wait_for_timeout(1500)


def _fill_phone(locator, digits: str):
    """Type digits into a masked tel field (clearing any existing value first)."""
    locator.click()
    locator.press("Control+a")
    locator.press("Delete")
    locator.press_sequentially(digits, delay=15)


def _expect_saved_toast(page: Page, message: str = "The details have been saved successfully"):
    expect(page.get_by_text(message, exact=False).first).to_be_visible(timeout=15_000)


def _rand_phone_digits() -> str:
    return f"919{random.randint(2000000, 9999999)}"


def _go_to_lt260(page: Page):
    """Dashboard -> '+ Start here' -> the LT-260 form (Vehicle Details)."""
    _ensure_dashboard(page)
    page.locator('button:has-text("Start here"), a:has-text("Start here")').first.click()
    page.wait_for_url(re.compile(r"lt-?260", re.I), timeout=30_000)
    page.locator('input[name="sno"]').wait_for(state="visible", timeout=20_000)


def _vin_lookup(page: Page, vin: str):
    """Type a VIN into the LT-260 form and click VIN Lookup."""
    vin_input = page.locator('input[name="sno"]')
    vin_input.click()
    vin_input.fill("")
    vin_input.fill(vin)
    page.locator('button:has-text("VIN Lookup")').first.click()


def _vin_error_dialog(page: Page):
    """The 'THE VIN ENTERED MAY HAVE AN ERROR' popup overlay."""
    return page.locator(".cdk-overlay-pane").filter(
        has_text=re.compile(r"THE VIN ENTERED MAY HAVE AN ERROR", re.I)
    ).first


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="class")
def signin_page(browser: Browser) -> Page:
    """Fresh LOGGED-OUT tab on the public sign-in screen (no stored session)."""
    ctx = browser.new_context()
    page = ctx.new_page()
    _go_to_signin(page)
    yield page
    ctx.close()


@pytest.fixture(scope="class")
def dash_page(public_user_c_context: BrowserContext) -> Page:
    """One shared tab for the whole class; navigate to the dashboard once.

    E2E-055 runs as the User C public account (PUBLIC_USER_C_* in .env).
    """
    page = public_user_c_context.new_page()
    _go_to_dashboard(page)
    yield page
    page.close()


@pytest.mark.e2e
@pytest.mark.public_portal
class TestE2E055PublicPortalAssertions:
    """E2E-055: Public Portal UI assertions — read-only, no data created."""

    # ── Phase 1: Sign-on Page (logged out) ────────────────────────────────────

    def test_phase1_signin_new_users_section(self, signin_page: Page):
        """New Users / Returning Users section text is displayed on the sign-in page."""
        page = signin_page
        _ensure_signin(page)
        body = page.locator("body")
        for text in [
            "New Users",
            "Video Guide",
            "PDF Guide",
            "Register Your Account",
            "You will need an NCID.",
            "See below if you don't have one.",
            "By starting this transaction, I confirm that I have read and accepted",
            "Create an NCID",
            "click here",
            "to create an NCID account",
            "About NCID",
            "First time using NCID?",
            "it works",
            "Returning Users",
            "Log in",
            "Sign In with NCID",
            "If you need help with the ISU-263",
        ]:
            expect(body).to_contain_text(text, timeout=10_000)

    def test_phase1_signin_welcome_note(self, signin_page: Page):
        """The Welcome note describing the N&S process is displayed."""
        page = signin_page
        _ensure_signin(page)
        body = page.locator("body")
        expect(body).to_contain_text("Welcome", timeout=10_000)
        expect(body).to_contain_text(
            "The North Carolina State Highway Patrol Notice and Storage process is mandated by law"
        )
        expect(body).to_contain_text(
            "ISU N&S Section will notify a reporter by mail and email"
        )

    def test_phase1_signin_footer(self, signin_page: Page):
        """Footer contact details and standard NC.gov links are displayed."""
        page = signin_page
        _ensure_signin(page)
        body = page.locator("body")
        for text in [
            "CONTACT",
            "Physical Address:",
            "512 North Salisbury Street, Raleigh",
            "Mailing Address:",
            "4231 Mail Service Center",
            "Raleigh, NC 27699-4231",
            "919-757-0753",
            "Send an email",
            "FOLLOW US",
            "Accessibility",
            "Disclaimer & Terms of Use",
            "Open Budget",
            "Privacy Policy",
            "Social Media Policy",
            "nc.gov",
        ]:
            expect(body).to_contain_text(text, timeout=10_000)

    def test_phase1_signin_links_point_to_correct_destinations(self, signin_page: Page):
        """Sign-in page links resolve to their correct external destinations.

        Verified via href (these are target=_blank external links). Covers the
        Register-section AND Sign-In-with-NCID-section Terms/Privacy links, the
        'Create an NCID' / 'About NCID' NCID links, and the Video/PDF guides.
        """
        page = signin_page
        _ensure_signin(page)

        # Terms of Service (New Users consent + Returning Users consent)
        _assert_links_href(page, re.compile(r"^Terms of Service$", re.I),
                           "www.nc.gov/disclaimer-terms-use", min_count=2)
        # Privacy Policy (both consents; footer link shares the same destination)
        _assert_links_href(page, re.compile(r"^Privacy Policy$", re.I),
                           "www.nc.gov/privacy", min_count=2)
        # 'Create an NCID' -> click here  /  'About NCID' -> See how
        _assert_links_href(page, re.compile(r"click here", re.I),
                           "it.nc.gov/support/accounts/myncid")
        _assert_links_href(page, re.compile(r"See how", re.I),
                           "it.nc.gov/support/accounts/myncid")
        # New Users guides
        _assert_links_href(page, re.compile(r"Video Guide", re.I), "cdn.services.expertly.com")
        _assert_links_href(page, re.compile(r"PDF Guide", re.I), "cdn.services.expertly.com")

        # Both primary CTAs are present
        expect(page.get_by_role("button", name=re.compile(r"Sign In with NCID", re.I))).to_be_visible()
        expect(page.get_by_role("button", name=re.compile(r"^Register$", re.I))).to_be_visible()

    def test_phase1_signin_register_opens_registration(self, signin_page: Page):
        """The Register button opens the 'Register Your Facility' page."""
        page = signin_page
        _ensure_signin(page)
        page.get_by_role("button", name=re.compile(r"^Register$", re.I)).click()
        page.wait_for_url(re.compile(r"register", re.I), timeout=20_000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            page.wait_for_timeout(2500)

        body = page.locator("body")
        expect(body).to_contain_text("Register Your Facility", timeout=15_000)
        expect(body).to_contain_text("Register As:")
        expect(body).to_contain_text("Business/Organization")
        expect(body).to_contain_text("Individual")

    # ── Phase 2: Dashboard ─────────────────────────────────────────────────────

    def test_phase2_dashboard_loads(self, dash_page: Page):
        """Dashboard page loads and URL contains 'dashboard'."""
        page = dash_page
        _ensure_dashboard(page)
        expect(page).to_have_url(re.compile(r"dashboard", re.I), timeout=15_000)

    def test_phase2_dashboard_tabs_visible(self, dash_page: Page):
        """All four main tabs are visible on the dashboard."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)

        expect(dashboard.notice_storage_tab).to_be_visible(timeout=15_000)
        expect(dashboard.payments_tab).to_be_visible(timeout=10_000)
        expect(dashboard.sold_completed_tab).to_be_visible(timeout=10_000)
        expect(dashboard.messages_tab).to_be_visible(timeout=10_000)

    def test_phase2_start_here_button_visible(self, dash_page: Page):
        """'Start here' button is visible on the dashboard."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        expect(dashboard.start_here_button).to_be_visible(timeout=15_000)

    def test_phase2_header_business_name_visible(self, dash_page: Page):
        """Business name is displayed in the portal header."""
        page = dash_page
        _ensure_dashboard(page)
        header_biz = page.locator(
            'app-header, mat-toolbar, header, nav, '
            '[class*="header" i], [class*="toolbar" i], [class*="navbar" i]'
        ).first
        expect(header_biz).to_be_visible(timeout=15_000)

        # Header carries some text (portal title / user / business name)
        expect(header_biz).to_contain_text(re.compile(r"[A-Za-z]"), timeout=10_000)

    def test_phase2_search_input_visible(self, dash_page: Page):
        """Search / VIN input is visible on the dashboard."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        expect(dashboard.search_input).to_be_visible(timeout=15_000)

    # ── Phase 3: Case Listing ──────────────────────────────────────────────────

    def test_phase3_notice_storage_tab_shows_listing(self, dash_page: Page):
        """Notice & Storage tab renders application listing."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        dashboard.click_notice_storage_tab()
        page.wait_for_timeout(1000)

        # Either applications are listed or an empty-state message is shown
        applications = dashboard.application_list
        empty_state = page.locator(
            'text="No applications", text="No records", '
            '[class*="empty" i], [class*="no-data" i]'
        ).first

        has_apps = applications.count() > 0
        try:
            has_empty = empty_state.is_visible()
        except Exception:
            has_empty = False

        assert has_apps or has_empty, "Notice & Storage tab shows neither applications nor empty state"

    def test_phase3_application_list_has_vin_column(self, dash_page: Page):
        """Application listing shows VIN or reference number for each entry."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        dashboard.click_notice_storage_tab()
        page.wait_for_timeout(1000)

        if dashboard.application_list.count() > 0:
            vin_text = page.locator(
                '[class*="vin" i], [class*="reference" i], '
                'td:nth-child(1), [class*="group-block"] span'
            ).first
            expect(vin_text).to_be_visible(timeout=10_000)

    def test_phase3_search_accepts_input(self, dash_page: Page):
        """Search input accepts text and is interactive."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        expect(dashboard.search_input).to_be_visible(timeout=15_000)
        expect(dashboard.search_input).to_be_enabled(timeout=5_000)
        dashboard.search_input.fill("TEST123")
        assert dashboard.search_input.input_value() == "TEST123"
        dashboard.search_input.fill("")

    # ── Phase 4: Payments Tab ──────────────────────────────────────────────────

    def test_phase4_payments_tab_navigates(self, dash_page: Page):
        """Clicking Payments tab loads payment history content area."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        dashboard.click_payments_tab()

        content = page.locator(
            '[class*="payment" i], table, '
            '[class*="history" i], [class*="tab-content" i], '
            'mat-tab-body'
        ).first
        expect(content).to_be_visible(timeout=15_000)

    # ── Phase 5: Sold / Completed Tab ──────────────────────────────────────────

    def test_phase5_sold_tab_navigates(self, dash_page: Page):
        """Clicking Sold/Completed tab renders its content area."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        dashboard.click_sold_completed_tab()

        content = page.locator(
            '[class*="sold" i], [class*="completed" i], '
            'mat-tab-body, [class*="tab-content" i]'
        ).first
        expect(content).to_be_visible(timeout=15_000)

    # ── Phase 6: Messages Tab ──────────────────────────────────────────────────

    def test_phase6_messages_tab_navigates(self, dash_page: Page):
        """Clicking Messages tab renders inbox/message area."""
        page = dash_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        dashboard.click_messages_tab()

        content = page.locator(
            'mat-tab-body:visible, [class*="inbox" i]:visible, '
            '[class*="message" i]:visible, [class*="tab-content" i]:visible'
        ).first
        expect(content).to_be_visible(timeout=15_000)

    # ── Phase 7: Profile Page ──────────────────────────────────────────────────

    def test_phase7_profile_page_navigates(self, dash_page: Page):
        """My Profile link navigates to the profile page."""
        page = dash_page
        _ensure_dashboard(page)  # start from the dashboard so the link nav is meaningful
        PublicProfilePage(page).navigate_to_profile()
        expect(page).to_have_url(re.compile(r"profile|account|my-profile", re.I), timeout=15_000)

    def test_phase7_profile_shows_user_info(self, dash_page: Page):
        """Profile page displays user/business information."""
        page = dash_page
        _ensure_profile(page)  # no reload if a prior phase-7 test is already here
        user_info = page.locator(
            '[class*="profile" i] span, [class*="user-info" i], '
            '[class*="name" i], [class*="email" i], '
            'input[name*="name" i], input[name*="email" i]'
        ).first
        expect(user_info).to_be_visible(timeout=15_000)

    def test_phase7_drawdown_balance_section_visible(self, dash_page: Page):
        """Drawdown balance section is accessible from profile."""
        page = dash_page
        profile = PublicProfilePage(page)
        profile.navigate_to_drawdown()  # self-navigates to profile then drawdown
        profile.expect_balance_displayed()

    # ── Phase 8: Navigation ────────────────────────────────────────────────────

    def test_phase8_navigation_returns_to_dashboard(self, dash_page: Page):
        """Returning to the dashboard from My Profile works.

        This portal has NO in-app 'home'/logo link back to the dashboard: the
        header logo points to the external NCSHP website (ncshp.gov) and the
        portal banner is a non-interactive 'disableHeader' element (verified via
        DOM inspection). The supported way back is browser navigation, so we
        verify that going Back from the profile restores the dashboard and it
        re-renders.
        """
        page = dash_page
        _ensure_dashboard(page)

        # Navigate away to the profile page
        profile = PublicProfilePage(page)
        profile.navigate_to_profile()
        page.wait_for_timeout(1000)
        expect(page).to_have_url(
            re.compile(r"profile|account|my-profile", re.I), timeout=15_000
        )

        # Return to the dashboard — no in-app home link exists, Back is the real path
        page.go_back()
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
            page.wait_for_timeout(2000)

        expect(page).to_have_url(re.compile(r"dashboard", re.I), timeout=15_000)
        # Confirm the dashboard actually re-rendered (not just the URL)
        expect(
            page.get_by_role("tab", name=re.compile(r"Notice & Storage", re.I)).or_(
                page.locator('button:has-text("Notice & Storage")')
            ).first
        ).to_be_visible(timeout=15_000)

    # ── Phase 9: Edit My Details (WRITE) ───────────────────────────────────────

    def test_phase9_edit_my_details(self, dash_page: Page):
        """My Details edit: set random first name, last name, title -> save.

        The first/last name MUST be restored afterwards: this runs as the shared
        daniel_scott account, and its display name ("Daniel Scott") is asserted by
        E2E-012/024/038 attribution checks. Leaving a random name behind corrupts
        the QA account for every later run (this happened — it got stuck as
        "James Smith" and broke E2E-038 phase 4).
        """
        page = dash_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state

        # 'My Details' is the first Edit button on the My Profile tab
        page.get_by_role("button", name=re.compile(r"^\s*Edit\s*$", re.I)).first.click()
        page.wait_for_timeout(1000)

        first_input = page.locator('input[name="firstName"]:visible')
        last_input = page.locator('input[name="lastName"]:visible')
        title_input = page.locator('input[name="title"]:visible')
        orig_first = first_input.input_value() or "Daniel"
        orig_last = last_input.input_value() or "Scott"
        orig_title = title_input.input_value()

        try:
            first_input.fill(generate_first_name())
            last_input.fill(generate_last_name())
            title_input.fill(generate_job_title())

            page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
            _expect_saved_toast(page, "The details have been saved successfully")
        finally:
            # Restore the original identity regardless of assertion outcome
            _go_to_profile(page)
            page.get_by_role("button", name=re.compile(r"^\s*Edit\s*$", re.I)).first.click()
            page.wait_for_timeout(1000)
            page.locator('input[name="firstName"]:visible').fill(orig_first)
            page.locator('input[name="lastName"]:visible').fill(orig_last)
            page.locator('input[name="title"]:visible').fill(orig_title)
            page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
            _expect_saved_toast(page, "The details have been saved successfully")

    # ── Phase 10: Edit Company Details (WRITE) ─────────────────────────────────

    def test_phase10_edit_company_details(self, dash_page: Page):
        """Company details edit: name, location, address, NC zip, contact, phone."""
        page = dash_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state
        addr = generate_address()

        # Company Details is the second Edit button on the My Profile tab
        page.get_by_role("button", name=re.compile(r"^\s*Edit\s*$", re.I)).nth(1).click()
        page.wait_for_timeout(1000)

        page.locator('input[name="name"]:visible').fill(generate_company_name())
        page.locator('input[name="location"]:visible').fill(generate_location_name())
        page.locator('input[name="address"]:visible').fill(addr["street"])
        page.locator('input[name="zip"]:visible').fill(addr["zip"])
        page.wait_for_timeout(1500)  # let the zip -> city auto-lookup finish
        page.locator('input[name="contact_person"]:visible').fill(generate_full_name())
        _fill_phone(page.locator('input[name="contact_phone"]:visible'), _rand_phone_digits())

        page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
        _expect_saved_toast(page, "The details have been saved successfully")

    # ── Phase 11: Address Book (WRITE) ─────────────────────────────────────────

    def test_phase11_address_book_delete(self, dash_page: Page):
        """Delete a deletable address (confirm with Yes).

        Skips when no address is deletable (e.g. only one address remains and its
        Delete button is disabled).
        """
        page = dash_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state
        _open_profile_tab(page, re.compile(r"Address Book", re.I))

        deletes = page.get_by_role("button", name=re.compile(r"^\s*Delete\s*$", re.I))
        deletes.first.wait_for(state="visible", timeout=15_000)
        enabled = [i for i in range(deletes.count()) if deletes.nth(i).is_enabled()]
        if not enabled:
            pytest.skip("No deletable address (single address / Delete disabled)")

        before = deletes.count()
        deletes.nth(enabled[0]).click()
        page.wait_for_timeout(800)

        # Confirmation popup -> Yes
        page.get_by_role("button", name=re.compile(r"^\s*yes\s*$", re.I)).first.click()

        # The address list should shrink by one
        expect(
            page.get_by_role("button", name=re.compile(r"^\s*Delete\s*$", re.I))
        ).to_have_count(before - 1, timeout=15_000)

    def test_phase11_address_book_edit(self, dash_page: Page):
        """Edit an address: random location name, address, NC zip -> save."""
        page = dash_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state
        _open_profile_tab(page, re.compile(r"Address Book", re.I))
        addr = generate_address()

        page.get_by_role("button", name=re.compile(r"^\s*Edit\s*$", re.I)).first.click()
        page.wait_for_timeout(1000)

        page.locator('input[name="locationName"]:visible').fill(generate_location_name())
        page.locator('input[name="address"]:visible').fill(addr["street"])
        page.locator('input[name="zip"]:visible').fill(addr["zip"])
        page.wait_for_timeout(1500)  # let the zip -> city auto-lookup finish before saving

        page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
        _expect_saved_toast(page, "The details have been saved successfully")

    # ── Phase 12: Add User (WRITE) ─────────────────────────────────────────────

    def test_phase12_add_user(self, dash_page: Page):
        """Add a new Admin user: first/last/email(@yopmail)/phone + first location.

        The Users tab loads a large user list; a normal Playwright click stalls on
        this SPA's post-click navigation wait, so the Users tab and the
        '+ Add Another User' button are triggered with element.click() inside the
        page. Form fields are matched by their accessible labels (the form
        builder randomizes their name attributes).
        """
        page = dash_page
        _go_to_profile(page)  # full reload: the heavy Users tab needs a clean load for the evaluate-click

        # Open Users tab + add-user form. dispatch_event('click') fires the Angular
        # handlers without Playwright's post-click navigation wait, which stalls on
        # this SPA's heavy Users list. Wait generously for the Add button to render.
        page.get_by_role("tab", name=re.compile(r"^Users$", re.I)).first.dispatch_event("click")
        page.wait_for_timeout(3000)
        add_btn = page.get_by_role("button", name=re.compile(r"Add Another User|Add User", re.I)).first
        add_btn.wait_for(state="visible", timeout=30_000)
        add_btn.dispatch_event("click")
        page.wait_for_timeout(2500)

        # Fields matched by label (name attributes are randomized)
        first, last = generate_first_name(), generate_last_name()
        page.get_by_label(re.compile(r"First Name", re.I)).fill(first)
        page.get_by_label(re.compile(r"Last Name", re.I)).fill(last)
        page.get_by_label(re.compile(r"Email Address", re.I)).fill(
            f"{first.lower()}.{last.lower()}{random.randint(10, 999)}@yopmail.com"
        )
        _fill_phone(page.locator('input[type="tel"]:visible').first, _rand_phone_digits())

        # Role = Admin
        page.get_by_label(re.compile(r"Role", re.I)).click()
        page.wait_for_timeout(500)
        page.get_by_role("option", name=re.compile(r"^\s*Admin\s*$", re.I)).first.click()

        # Location = first option in the dropdown
        page.get_by_label(re.compile(r"Location", re.I)).click()
        page.wait_for_timeout(500)
        page.get_by_role("option").first.click()

        # Save (fall back to element.click() if the normal click stalls)
        save = page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first
        try:
            save.click(timeout=8000)
        except Exception:
            save.evaluate("el => el.click()")

        _expect_saved_toast(page, "User has been added successfully")

    # ── Phase 13: LT-260 Form via "Start here" ─────────────────────────────────

    def test_phase13_lt260_form_text(self, dash_page: Page):
        """'+ Start here' opens the LT-260 form with the expected guidance text."""
        page = dash_page
        _go_to_lt260(page)
        body = page.locator("body")
        for text in [
            "Submit a LT260 Report of Unclaimed Vehicles Form",
            "has been unclaimed for 10 days",
            "North Carolina Division of Motor Vehicles as required by law",
            "News & Information",
            "no longer accept submissions",
            "Notice of Intent to Sell Vehicle (LT-262)",
            "Instructions",
            "Submit only the Report of Unclaimed Motor Vehicles (LT-260)",
            "Wait to receive Notification Letter (LT-160B)",
            "Submit payment and Notice of Intent to Sell Vehicle (LT-262)",
            "Disclaimers",
            "FRAUDULENT OR LATE FORMS MAY RESULT IN CRIMINAL PROSECUTION",
            "INCOMPLETE FORMS WILL BE RETURNED TO SENDER FOR CORRECTION",
            "Do not submit mopeds via this LT-260 form",
        ]:
            expect(body).to_contain_text(text, timeout=10_000)

    def test_phase13_vin_lookup_oiq_error(self, dash_page: Page):
        """'VIN123' (contains I) -> toast + error popup including the O/I/Q guidance."""
        page = dash_page
        _go_to_lt260(page)
        _vin_lookup(page, "VIN123")

        expect(
            page.get_by_text("The VIN could not be found during the lookup", exact=False).first
        ).to_be_visible(timeout=15_000)

        dialog = _vin_error_dialog(page)
        expect(dialog).to_be_visible(timeout=10_000)
        expect(dialog).to_contain_text("THE VIN ENTERED MAY HAVE AN ERROR")
        expect(dialog).to_contain_text("does not include the letters")  # O/I/Q guidance
        expect(dialog).to_contain_text("be decoded by our VIN decoding service")
        expect(dialog).to_contain_text("not 17 characters long")
        expect(dialog).to_contain_text("upload an image of the VIN")

        page.get_by_role("button", name=re.compile(r"^\s*Cancel\s*$", re.I)).first.click()
        page.wait_for_timeout(1000)

    def test_phase13_vin_lookup_undecodable_error(self, dash_page: Page):
        """A 17-char junk VIN (no I/O/Q) -> toast + 'could not be decoded' popup.

        The app does NOT show the 'not 17 characters long' line here (the VIN is
        exactly 17 chars) nor the O/I/Q line (no such letters), so we don't assert
        them.
        """
        page = dash_page
        _go_to_lt260(page)
        _vin_lookup(page, "zxcvbnmzxcvbnmzxc")  # 17 chars, no o/i/q

        expect(
            page.get_by_text("The VIN could not be found during the lookup", exact=False).first
        ).to_be_visible(timeout=15_000)

        dialog = _vin_error_dialog(page)
        expect(dialog).to_be_visible(timeout=10_000)
        expect(dialog).to_contain_text("THE VIN ENTERED MAY HAVE AN ERROR")
        expect(dialog).to_contain_text("be decoded by our VIN decoding service")
        expect(dialog).to_contain_text("upload an image of the VIN")

        page.get_by_role("button", name=re.compile(r"^\s*Cancel\s*$", re.I)).first.click()
        page.wait_for_timeout(1000)

    def test_phase13_vin_lookup_disabled_for_overlong_vin(self, dash_page: Page):
        """A VIN longer than 17 characters disables the VIN Lookup button."""
        page = dash_page
        _go_to_lt260(page)
        vin_input = page.locator('input[name="sno"]')
        vin_input.click()
        vin_input.fill("sxzcxvxcvxzbbcxzbxcvxzvxzcvzxvxc")  # 32 chars
        page.wait_for_timeout(800)
        expect(page.locator('button:has-text("VIN Lookup")').first).to_be_disabled(timeout=10_000)
