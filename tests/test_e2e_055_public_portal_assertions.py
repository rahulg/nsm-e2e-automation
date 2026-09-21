"""
E2E-055: Public Portal — UI Assertions
Verifies key UI elements, navigation, and content across the Public Portal.
Phases 1-8 and 13 are read-only; phases 9-12 and 14 write (see below).

Runs green on QA and STAGE with no skips (both verified 2026-08-11).

Phases:
  1. Sign-on Page      — logged-out sign-in screen: New Users / Returning Users
                         text, Welcome note, footer, link destinations, Register nav
  2. Dashboard         — tabs, layout, header elements, Start Here button
  3. Case Listing      — Notice & Storage tab, application list, search input
  4. Payments Tab      — tab navigation, payment history visible
  5. Sold/Completed    — tab navigation, content area rendered
  6. Messages Tab      — tab navigation, inbox area visible
  7. Profile Page      — navigation, user info, and the ACH tab's Drawdown block
                         (balance + Add Funds where the business has bank details;
                         asserted absent where it does not)
  8. Navigation        — browser Back returns to dashboard (no in-app home link)
  9. Edit My Details   — (WRITE) update first/last/title -> success toast
 10. Edit Company      — (WRITE) update company details -> success toast
 11. Address Book      — (WRITE) add an address then delete it + edit an address
 12. Edit User         — (WRITE) modify a non-owner user (phone + role) in Users
                         list, provisioning one first if the business has none
 13. LT-260 Form       — Start here -> form text + VIN-lookup validation popups
 14. Individual User   — (WRITE) a SECOND tab signed in as the environment's
                         individual account (QA: Automation_act, stage:
                         rahulg_indi31@yopmail.com): My Details edit, ACH bank
                         information, Drawdown Add Funds

Phases 9-12 and 14 MODIFY data (edit details, add and delete an address, change a
user's phone/role, rewrite bank details, credit the drawdown wallet). They are not
read-only.

Phases 9 and 10 restore what they changed. Phases 11 and 12 are net-zero by
construction: each CREATES the row it operates on (an Address Book entry; a Users
entry, only where the business has no non-owner user) and removes it again, so
neither depends on account data it did not put there, and neither can delete
anything real. That replaced a pair of data-precondition skips which fired on QA
and STAGE both — meaning the delete path had never once executed on any env.

Phase 14 deliberately does NOT restore (user instruction, 2026-08-10). Every
phase-14 run therefore leaves the individual account carrying a fresh random name,
address, NC zip, phone, bank account name, account type, routing number and account
number, plus a drawdown balance $10-$99 higher than it found it. Treat none of that
account's profile or bank data as fixed.

Performance note:
  Phases 1-13 run in ONE tab (the class-scoped ``portal_page`` fixture) on a
  logged-OUT context. Phase 1 asserts the sign-in screen there (a stored session
  would bypass it straight to the dashboard), then phase 2 signs in through NCID in
  that same tab and phases 2-13 continue on it. Phase 14 is the one exception: it
  needs a DIFFERENT account, so it opens its own context/tab (``individual_page``).
  ``_ensure_dashboard`` re-navigates only when a previous test left the page
  elsewhere, and signs in only when the tab has no session yet. Readiness is
  detected by waiting for a real element rather than ``networkidle``, which never
  settles reliably on this Angular SPA. ``_ensure_individual_profile`` and
  ``_go_to_lt260`` apply the same rule to phases 14 and 13, which previously paid
  a full SPA cold boot per test to reach a page already on screen.

  Full run, measured with both envs running concurrently: QA 9:02 -> 5:05-6:48,
  STAGE 7:44 -> 4:34-6:20, while going from 3 skips to none. The spread is
  environment load, not the test — treat the slower end as the honest figure.
  The single biggest win was phase 7, which spent 73 s of its 73 s hunting for an
  'Accounts' tab and a 'Drawdown' link this portal does not have — each miss
  costing a ``networkidle`` timeout — and then asserted nothing.
"""

import os
import random
import re

import pytest
from playwright.sync_api import Browser, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from scripts.auth_helpers import login_public_portal, select_company_if_prompted
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

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL  # this is the sign-in URL
# The env holds the PRE-redirect sign-in route (/ncdot-nsm-signin); the app then
# rewrites it to /ncshp-nss-signin. Strip either form so derived URLs don't carry
# a sign-in path inside them.
_BASE_URL = re.sub(
    r"/ncdot-nsm-signin/?$|/ncshp-nss-signin/?$", "", PP_DASHBOARD_URL
)  # https://nsm-qa-public.nc.verifi.dev
PROFILE_URL = f"{_BASE_URL}/ncdmv-nsm/my-profile"

# Forms capture times in the BROWSER's timezone; the system under test is NC-only.
# Matches the suite-wide convention in tests/conftest.py.
NC_TIMEZONE = "America/New_York"

# The public account belongs to several businesses (QA: G-Car Garages New, Piedmont
# Recovery Services, Piedmont Towing, Triangle Garage) and the sign-in prompt lists
# them in an order the test must not depend on. Pin the one this file writes to:
# phases 10-12 edit company details, addresses and users, so "whichever business
# came first" would silently move those writes — and it did, until this was pinned
# (taking the first option landed on G-Car, which is also the business other E2E
# tests select by name). Falls back to the first option where it isn't offered
# (STAGE has a different business list).
#
# The business must be one this account is an ADMIN of, which is a stricter
# requirement than "a business it belongs to". 'Triangle Garage' was pinned here
# first and made phases 10-12 fail on QA: daniel_scott is only a Standard User
# there, so the portal renders the profile read-only — no company Edit button, and
# the Address Book / Users tabs come back as plain tables with no Edit/Delete at
# all. Audited across all four QA businesses on 2026-08-07: G-Car Garages New and
# Piedmont Recovery Services expose the full admin controls, Triangle Garage does
# not. Piedmont wins over G-Car because phase 10 renames the business it runs
# against, and G-Car is the one other E2E tests select by name.
#
# Pinned PER ENV, because the QA choice exists only on QA: STAGE's rahulg_biz11 is
# offered 'Piedmont Auto Body' and 'Piedmont Towing' (probed 2026-08-11), so asking
# there for 'Piedmont Recovery Services' fell through to select_company_if_prompted's
# "not offered — use the first option" fallback, and the write phases edited whichever
# business the portal happened to list first. Every other env therefore pins the
# business its own .env names, which is the one the rest of the suite treats as
# canonical for that environment.
PINNED_COMPANY = {"qa": "Piedmont Recovery Services"}.get(
    os.getenv("NSM_ENV", "qa"), ENV.PUBLIC_BUSINESS_NAME
)


# ── Dashboard navigation (authenticated) ──────────────────────────────────────

def _sign_in(page: Page, username: str = "", password: str = "",
             company: str = PINNED_COMPANY, attempts: int = 2):
    """Sign in through NCID on the CURRENT tab (phase 1 leaves it logged out).

    The class runs in a single logged-out tab so phase 1 can assert the sign-on
    screen; phase 2 onwards need a session, so the first dashboard navigation
    performs the real sign-in here rather than opening a second, pre-authenticated
    tab. Uses the same helper that generates the suite's stored auth states.

    Defaults to the primary business account. Phase 14 passes the individual
    account's credentials and ``company=""`` (that account belongs to no business,
    so it is never shown the select-company prompt).

    The ``login_public_portal`` timeout is swallowed on purpose: that helper ends
    on ``wait_for_load_state("networkidle")``, which this Angular SPA does not
    reliably reach — an otherwise successful sign-in was seen failing there. The
    ``wait_for_url`` below is the real proof of success, so a genuinely failed
    login still fails the test, just at that line instead.

    Retried once, from a fresh sign-in screen. QA's path runs through NCID, a
    third-party redirect chain (PingFederate), and a slow hop can leave the tab
    short of the dashboard with nothing actually wrong: a cold first sign-in timed
    out this way on 2026-08-11 while the two tests after it authenticated the same
    account without trouble. Bad credentials still fail — they fail twice, and the
    second failure is raised.
    """
    last_error = None
    for attempt in range(attempts):
        try:
            login_public_portal(
                page,
                username or ENV.PUBLIC_PORTAL_USERNAME,
                password or ENV.PUBLIC_PORTAL_PASSWORD,
                os.getenv("NSM_ENV", "qa"),
            )
        except PlaywrightTimeoutError:
            pass
        select_company_if_prompted(page, company=company)
        try:
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=60_000)
            return
        except PlaywrightTimeoutError as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            _go_to_signin(page)  # restart clean; don't inherit a half-done redirect
    raise last_error  # pragma: no cover - loop always returns or raises


def _resolve_auth_state(page: Page, ready, timeout_ms: int = 40_000) -> str:
    """Poll until this tab settles into either ``ready`` or the sign-in screen.

    A fixed sleep cannot tell "already signed in, SPA still booting" from "signed
    out" — for the first few seconds both show neither element. Racing the two
    keeps the signed-in path free of extra waiting and stops a slow boot from
    being read as signed-out (which made ``_sign_in`` hunt for a Sign-In button
    that was never going to appear, failing phases 8 and 13).
    """
    # QA signs in through NCID only; STAGE puts a username/password form on the same
    # screen (and still shows NCID buttons). Either element means "not signed in".
    signin = page.get_by_role("button", name=re.compile(r"Sign In with NCID", re.I)).or_(
        page.locator('input[name="pass"]')
    )
    waited = 0
    while waited < timeout_ms:
        for name, loc in (("ready", ready), ("signin", signin)):
            try:
                if loc.first.is_visible():
                    return name
            except Exception:  # locator not attached yet
                pass
        page.wait_for_timeout(500)
        waited += 500
    return "unknown"


def _go_to_dashboard(page: Page):
    """Navigate to the public dashboard and wait for it to be interactive.

    Signs in first when the tab has no session yet (the portal bounces an
    unauthenticated request back to the sign-in screen). Readiness is the Notice &
    Storage tab appearing — a real signal — instead of ``networkidle``, which
    stalls until timeout on this SPA.
    """
    page.goto(PP_DASHBOARD_URL, timeout=90_000, wait_until="domcontentloaded")
    ready = page.get_by_role("tab", name=re.compile(r"Notice & Storage", re.I)).or_(
        page.locator('button:has-text("Notice & Storage")')
    )
    if _resolve_auth_state(page, ready) == "signin":
        _sign_in(page)
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    try:
        ready.first.wait_for(state="visible", timeout=20_000)
    except Exception:
        page.wait_for_timeout(2000)


# The SPA raises a full-screen backdrop while a tab fetches its data. It is not
# merely cosmetic: it swallows pointer events, so a click issued underneath it is
# retried by Playwright until the call times out and then reported as
# "<div class=cdk-overlay-backdrop ...> intercepts pointer events" — which reads
# like a missing element, not a busy page.
_LOADER_OVERLAY = ".exp-loader-overlay-backdrop"


def _wait_for_loader_gone(page: Page, timeout_ms: int = 30_000):
    """Wait out the loading overlay. No-op when it was never raised.

    ``state="hidden"`` is satisfied by a detached element, so a fast load that
    never shows the backdrop returns immediately rather than burning the timeout.
    """
    try:
        page.locator(_LOADER_OVERLAY).first.wait_for(state="hidden", timeout=timeout_ms)
    except Exception:
        pass  # overlay stuck or never attached — let the caller's own wait decide


def _click_past_loader(page: Page, click):
    """Run a click with the loading overlay waited out, retrying once.

    The retry matters as much as the wait: the overlay can be raised BETWEEN the
    two by a fetch the previous step kicked off. On STAGE (2026-08-11) this took
    out the Payments and Messages tabs, and once those were waited for, the
    dashboard's "Start here" button next — its account carries enough rows for a
    fetch to outlast the click. QA usually loads fast enough to hide the race.
    """
    _wait_for_loader_gone(page)
    try:
        click()
    except PlaywrightTimeoutError:
        _wait_for_loader_gone(page)
        click()


def _ensure_dashboard(page: Page):
    """Re-navigate to the dashboard only if we're not already there."""
    if "dashboard" not in page.url.lower():
        _go_to_dashboard(page)
    _wait_for_loader_gone(page)


# ── Sign-on page (logged out) ─────────────────────────────────────────────────

def _go_to_signin(page: Page):
    """Open the public sign-in screen (logged out) and wait for it to render.

    ``.first``: STAGE renders the NCID button twice (once per consent block), so an
    unqualified locator trips Playwright's strict mode there. QA renders one.
    """
    page.goto(PP_DASHBOARD_URL, timeout=90_000, wait_until="domcontentloaded")
    try:
        page.get_by_role("button", name=re.compile(r"Sign In with NCID", re.I)).first.wait_for(
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
    """Navigate to the My Profile area (authenticated).

    Signs in first if this tab has no session yet, so the profile phases still
    work when run on their own (``-k phase9``) instead of after phase 2.
    """
    page.goto(PROFILE_URL, timeout=90_000, wait_until="domcontentloaded")
    ready = page.get_by_role("tab", name=re.compile(r"My Profile", re.I))
    if _resolve_auth_state(page, ready) == "signin":
        _sign_in(page)
        page.goto(PROFILE_URL, timeout=90_000, wait_until="domcontentloaded")
    try:
        ready.first.wait_for(state="visible", timeout=20_000)
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


def _open_users_tab(page: Page, attempts: int = 3):
    """Open the Users sub-tab and wait for the user cards to render.

    dispatch_event('click') fires the Angular handler without Playwright's
    post-click navigation wait, which stalls on this SPA's heavy Users list.

    Retries with a fresh profile load: on a slow run the tab click can land before
    the profile finishes rendering and the list then never paints, which failed
    phase 12 once purely on timing.

    The settle below is short because it is not the gate — the Edit-button wait
    underneath it is, and it allows 20 s. A longer fixed sleep here only slowed
    every run down by the amount the slowest run needed.
    """
    edits = _row_buttons(page, _EDIT_BTN)
    for attempt in range(attempts):
        tab = page.get_by_role("tab", name=re.compile(r"^Users$", re.I)).first
        try:
            tab.wait_for(state="visible", timeout=30_000)
            tab.dispatch_event("click")
            page.wait_for_timeout(1200)
            edits.first.wait_for(state="visible", timeout=20_000)
            return
        except Exception:
            if attempt == attempts - 1:
                raise
            _go_to_profile(page)


_USER_FIELD_LABELS = ("First Name", "Last Name", "Role", "Email Address",
                      "Location", "Phone Number")
# Lines that are chrome, never a field's value — what follows an EMPTY field
_USER_NON_VALUES = frozenset(_USER_FIELD_LABELS) | {
    "Edit", "Delete", "Save", "Cancel", "+ Add Another User", "CONTACT",
}


def _users_on_page(page: Page) -> list[dict]:
    """Parse the rendered Users tab into one dict per user card, in card order.

    Read from the rendered text rather than per-card locators: the low-code form
    builder wraps every field in generated ``exp-field``/``wis-field-*`` elements
    with no stable per-row hook to anchor on.

    Label-walking, not a fixed regex over label/value pairs: an EMPTY field prints
    its label with no value line under it, so consecutive labels are normal. A
    regex expecting a value between every pair silently dropped whole cards — QA's
    'G-Car Garages New' has a user with no Location AND no Phone, which made this
    read 1 user instead of 2 and skipped phase 12 (fixed 2026-08-07).
    """
    lines = [ln.strip() for ln in page.locator("body").inner_text().split("\n")]

    cards: list[dict] = []
    current: dict = {}
    for i, line in enumerate(lines):
        if line not in _USER_FIELD_LABELS:
            continue
        # A repeated label means the previous card ended and a new one started
        key = line.lower().replace(" ", "_").replace("_address", "")
        if key in current:
            cards.append(current)
            current = {}
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        # A card's LAST field, when empty, is followed by the next card's title —
        # arbitrary text no stop-list can catch. What gives it away is what comes
        # after: a title is always followed by that card's Edit/Delete pair.
        starts_next_card = lines[i + 2:i + 4] == ["Edit", "Delete"]
        current[key] = "" if (nxt in _USER_NON_VALUES or starts_next_card) else nxt
    if current:
        cards.append(current)

    return [
        {
            "role": c.get("role", ""),
            "email": c.get("email", ""),
            "location": c.get("location", ""),
            "phone": c.get("phone_number", ""),
        }
        for c in cards
        if c.get("email")  # a card without an email isn't a user row
    ]


def _aria_input(page: Page, label: str):
    """A profile-form field, matched on the ``aria-label`` the designer emits.

    The ``name`` attributes on these forms are generated
    (``__text_field13301_775483_31842``) so they cannot be hard-coded, and the
    labels are not wired to their inputs with ``for``/``id``, so ``get_by_label``
    finds nothing either. ``aria-label`` is the one stable hook, carried as
    "First Name *" — hence the prefix match, which keeps the required-marker out
    of the caller's business.

    Used by the individual account's My Details form (phase 14) AND by the
    business account's Add-Location / Add-User forms (phases 11-12). Those add
    forms carry generated names on BOTH envs — QA and STAGE were probed on
    2026-08-11 and emit byte-identical markup — unlike the corresponding EDIT
    forms, which do ship stable names (``locationName``, ``address``, ``zip``).
    """
    return page.locator(f'input[aria-label^="{label}"]:visible').first


_DELETE_BTN = re.compile(r"^\s*Delete\s*$", re.I)
_EDIT_BTN = re.compile(r"^\s*Edit\s*$", re.I)


def _row_buttons(page: Page, label_re):
    """Row action buttons that are actually ON SCREEN.

    Must be visibility-scoped, because Angular Material keeps a tab panel in the
    DOM once it has been visited: after phase 11 switches from My Profile to
    Address Book, ``get_by_role("button", name="Delete")`` also matches the
    HIDDEN Delete on the retained My Profile panel's company card. That card's
    Delete is permanently disabled (one company), and being earlier in the DOM it
    takes index 0 — shifting every index by one against ``_addresses_on_page`` /
    ``_users_on_page``, which read ``inner_text()`` and so see only rendered rows.

    QA failed exactly this way on 2026-08-11: the delete test resolved its target
    to the company card's Delete and reported "expected to be enabled / Actual
    value: disabled". It passed on other runs only because the panel had not been
    instantiated yet — the same latent misalignment, landing on the right row by
    luck.
    """
    return page.locator("button:visible").filter(has_text=label_re)


def _addresses_on_page(page: Page) -> list[str]:
    """Location names of the Address Book cards, in card order.

    Read from rendered text for the same reason ``_users_on_page`` is: the
    low-code builder gives the cards no stable per-row hook. Each card prints
    "Location Name" followed by its value, so the label positions ARE the card
    order — which is what makes a name resolvable to a Delete-button index.
    """
    lines = [ln.strip() for ln in page.locator("body").inner_text().split("\n")]
    return [
        lines[i + 1]
        for i, line in enumerate(lines)
        if line == "Location Name" and i + 1 < len(lines)
    ]


def _select_by_aria(page: Page, aria_prefix: str, option: str):
    """Pick ``option`` in the mat-select whose aria-label starts with ``aria_prefix``."""
    select = page.locator(f'mat-select[aria-label^="{aria_prefix}"]:visible').first
    select.click()
    page.wait_for_timeout(800)
    page.get_by_role(
        "option", name=re.compile(rf"^\s*{re.escape(option)}\s*$", re.I)
    ).first.click()
    page.wait_for_timeout(800)


def _add_address(page: Page) -> str:
    """Create an Address Book entry and return its Location Name.

    Exists because BOTH envs ship exactly ONE address and the portal disables
    Delete on the last remaining one (QA and STAGE both probed 2026-08-11), so
    the delete test had nothing it was allowed to delete and skipped everywhere
    — the delete path was never actually covered on either env. Provisioning the
    row the test then deletes makes it self-sufficient and net-zero.

    The add form's inputs carry generated ``name`` attributes, so every field is
    reached by aria-label (see ``_aria_input``).

    Two things this must NOT do, both learned the hard way on QA (2026-08-11):

    1. Reuse ``generate_location_name()``. It picks from six fixed names, one of
       which ('South Facility') was already QA's real address — and the caller
       resolves its row by ``names.index(...)``, which returns the FIRST match.
       A collision would therefore have pointed the delete at the account's own
       address. The name is made unique and obviously disposable instead.
    2. Leave the form's "Mailing Address" checkbox checked. The mailing address
       is the one row the portal refuses to delete, so a new row that takes that
       flag is undeletable — which is precisely how a failed run left an orphan
       on QA that could not then be removed by hand either (the flag had to be
       moved to another row through its Edit form first).

    Only the open form's checkbox carries ``name="isMailingAddress"``; the ones
    rendered on the read-only cards have no name and are display-only (the mailing
    card's is disabled outright). Selecting by name therefore cannot touch a real
    card, which an index-based lookup could. The click goes to the enclosing
    ``mat-checkbox`` because Material's own overlay swallows clicks aimed at the
    underlying input.
    """
    name = f"E055 Temp {_rand_digits(5)}"
    addr = generate_address()

    page.get_by_role(
        "button", name=re.compile(r"Add Another Location", re.I)
    ).first.click()
    _aria_input(page, "Location Name").wait_for(state="visible", timeout=30_000)

    mailing = page.locator('input[name="isMailingAddress"]:visible')
    if mailing.count() and mailing.first.is_checked():
        mailing.first.locator("xpath=ancestor::mat-checkbox[1]").click()
        page.wait_for_timeout(500)

    _aria_input(page, "Location Name").fill(name)
    _aria_input(page, "Address").fill(addr["street"])
    _aria_input(page, "Zip").fill(addr["zip"])
    # The zip drives the same city/state lookup as everywhere else (TW 27302845);
    # saving mid-lookup writes a stale city.
    page.wait_for_timeout(2500)

    city = _aria_input(page, "City")
    if not city.input_value():  # lookup didn't populate it — fill it ourselves
        city.fill(addr["city"])
    state = page.locator('mat-select[aria-label^="State"]:visible').first
    if not state.inner_text().strip():
        _select_by_aria(page, "State", "North Carolina")

    _click_save(page)
    expect(page.locator("body")).to_contain_text(name, timeout=20_000)
    page.wait_for_timeout(1500)
    return name


def _add_user(page: Page) -> str:
    """Create a Users-tab user and return its email address.

    Only used when the business has no user other than the signed-in account —
    STAGE's 'Piedmont Auto Body' has exactly one (probed 2026-08-11), which made
    phase 12 skip there while QA's three-user business ran it. The caller deletes
    this user again, so the row count is unchanged either way; that is the whole
    reason it is created rather than reusing a leftover from a previous run.
    """
    email = f"e055auto{_rand_digits(8)}@yopmail.com"

    page.get_by_role("button", name=re.compile(r"Add Another User", re.I)).first.click()
    _aria_input(page, "First Name").wait_for(state="visible", timeout=30_000)

    _aria_input(page, "First Name").fill(generate_first_name())
    _aria_input(page, "Last Name").fill(generate_last_name())
    _aria_input(page, "Email Address").fill(email)
    _fill_phone(page.locator('input[type="tel"]:visible').first, _rand_phone_digits())
    _select_by_aria(page, "Role", "Standard User")

    _click_save(page)
    expect(page.locator("body")).to_contain_text(email, timeout=20_000)
    page.wait_for_timeout(1500)
    return email


def _remove_address_if_present(page: Page, name: str):
    """Best-effort removal of a provisioned address after a failed delete test.

    Deliberately swallows everything: it runs from a ``finally`` while a real
    assertion error is already propagating, and a cleanup that raises would
    replace that error with a far less useful one. Reloads first because the
    failure may have left the page anywhere.
    """
    try:
        _go_to_profile(page)
        _open_profile_tab(page, re.compile(r"Address Book", re.I))
        names = _addresses_on_page(page)
        if name in names:
            _delete_card_at(page, names.index(name))
            page.wait_for_timeout(2000)
    except Exception:
        pass


def _delete_card_at(page: Page, index: int):
    """Click the Delete on card ``index`` and confirm, then wait for it to go.

    Returns the Delete-button count from before the click so the caller can
    assert the list actually shrank.
    """
    deletes = _row_buttons(page, _DELETE_BTN)
    before = deletes.count()
    deletes.nth(index).click()
    page.wait_for_timeout(800)
    page.get_by_role("button", name=re.compile(r"^\s*yes\s*$", re.I)).first.click()
    return before


def _profile_input(page: Page, label: str, name: str = ""):
    """A visible input on a profile form, matched by designer ``name`` OR by label.

    The portal's forms come out of a low-code designer that does not emit a stable
    ``name`` on every environment. QA's My Details form ships generated names —
    ``__text_field8176_88928_505286``, a fresh value per deploy — while STAGE still
    emits ``firstName``/``lastName``/``title`` (both observed 2026-08-07). Hard-coding
    either one fails on the other env, and hard-coding QA's generated name would
    break on its next deploy.

    ``or_`` rather than an if/else on ``count()``: it keeps Playwright's auto-wait,
    so a slow-rendering form still resolves instead of being read as "no name
    attribute, use the label". Where both match they are the same element, and the
    label is matched as a prefix so an optional suffix ("Title (optional)") or a
    required marker still hits.
    """
    by_label = page.get_by_label(re.compile(rf"^\s*{re.escape(label)}", re.I))
    if not name:
        return by_label.first
    return page.locator(f'input[name="{name}"]:visible').or_(by_label).first


def _own_email(page: Page) -> str:
    """The signed-in account's own email, read off the My Details card.

    Phase 12 must never edit the signed-in user's own card: flipping that Role from
    Admin to Standard User would strip this account's admin rights on the business,
    and every later run would find the write controls gone — exactly the state QA's
    'Triangle Garage' is in (see ``PINNED_COMPANY``). It is one click away from
    being unrecoverable by this suite, so it is guarded by identity rather than by
    position: card ORDER is not a safe proxy, the owner being the FIRST card on
    'G-Car Garages New' but the THIRD on 'Piedmont Recovery Services' (both
    observed 2026-08-07).

    Must be called on the My Profile tab, where My Details is rendered.
    """
    m = re.search(r"Email Address\s*\n\s*(\S+@\S+)", page.locator("body").inner_text())
    return m.group(1).strip().lower() if m else ""


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
    """Dashboard -> '+ Start here' -> the LT-260 form (Vehicle Details).

    Returns early when this tab is already sitting on a usable LT-260 form. All
    four phase-13 tests drive the same form, and each used to travel back through
    the dashboard to reach it: ``_ensure_dashboard`` sees an ``lt-260`` URL, reads
    it as "not the dashboard", and pays a full SPA load plus another Start-here
    click — three times over, for a form that was already on screen.

    "Usable" means the VIN field is present AND no error popup is left open, so a
    test that ended mid-dialog still gets a genuinely fresh form rather than the
    previous test's leftovers. The field is cleared on the way out for the same
    reason.
    """
    vin_field = page.locator('input[name="sno"]')
    if re.search(r"lt-?260", page.url, re.I):
        try:
            if vin_field.is_visible() and not _vin_error_dialog(page).is_visible():
                vin_field.fill("")
                return
        except Exception:
            pass  # mid-navigation / detached — fall through to the full path
    _ensure_dashboard(page)
    _click_past_loader(
        page,
        lambda: page.locator(
            'button:has-text("Start here"), a:has-text("Start here")'
        ).first.click(),
    )
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


# ── Individual-account profile helpers (phase 14, WRITE operations) ───────────
#
# The individual account's profile is a DIFFERENT page from the business one used
# by phases 9-12: its sub-tabs are My Profile / ACH / Reports (no Address Book, no
# Users), My Details carries the address block inline, and Drawdown lives on the
# ACH tab rather than behind its own link.

ACH_FIELDS = (
    "account_name",
    "bank_routing_number",
    "bank_routing_number_reentered",
    "bank_account_number",
    "bank_account_number_reentered",
)
ACCOUNT_TYPES = ("Checking", "Savings")

ACH_CONFIRM_TEXT = re.compile(r"save your bank information", re.I)
MY_DETAILS_SAVED = "The details have been saved successfully"
BANK_SAVED = "The bank information has been saved successfully"


def _go_to_individual_profile(page: Page, attempts: int = 3):
    """Hard-load My Profile on the INDIVIDUAL account and wait for it to render.

    Readiness is the ACH tab, which only the individual layout has — so it doubles
    as proof the expected account is the one signed in.

    The whole load is retried because a slow cold boot leaves an empty ``<body>``
    rather than an error, and nothing in the DOM distinguishes that from "still
    loading" except more time. QA has been measured booting this route in 15 s on a
    good day and over 40 s on a bad one (2026-08-10), so the per-attempt wait is
    deliberately far longer than the 20 s the business-profile helper uses.
    """
    ach = page.get_by_role("tab", name=re.compile(r"^\s*ACH\s*$", re.I)).first
    last_error = None
    for _ in range(attempts):
        page.goto(PROFILE_URL, timeout=120_000, wait_until="domcontentloaded")
        try:
            ach.wait_for(state="visible", timeout=90_000)
            page.wait_for_timeout(2500)
            return
        except Exception as exc:  # blank body — reload and give it another go
            last_error = exc
    raise AssertionError(
        f"individual My Profile never rendered after {attempts} loads "
        f"(url={page.url}): {last_error}"
    )


def _ensure_individual_profile(page: Page):
    """Load the individual My Profile only when this tab is not already on it.

    Phase 14's three tests run back-to-back in ONE tab, and each used to force a
    full ``_go_to_individual_profile`` — an SPA cold boot measured at 15-40 s on
    QA — even when the test before it had left the page exactly where it was
    needed. Mirrors ``_ensure_profile``/``_ensure_dashboard`` for phases 2-13.

    Readiness is the ACH tab, the same signal the full loader uses, so a page
    sitting in an unexpected state (blank body after a slow boot, navigated away,
    logged out) falls through to the full load and self-heals instead of failing
    on a missing field further down.
    """
    if "my-profile" in page.url.lower():
        try:
            if page.get_by_role(
                "tab", name=re.compile(r"^\s*ACH\s*$", re.I)
            ).first.is_visible():
                return
        except Exception:
            pass  # not attached / mid-navigation — fall through to the full load
    _go_to_individual_profile(page)


def _open_ach_tab(page: Page):
    """Switch to the ACH tab and wait for the bank form to paint."""
    page.get_by_role("tab", name=re.compile(r"^\s*ACH\s*$", re.I)).first.click()
    page.locator('input[name="account_name"]:visible').wait_for(
        state="visible", timeout=45_000
    )
    page.wait_for_timeout(1500)


def _zip_input(page: Page):
    """The Zip field on the individual My Details form.

    Zip is the single field the designer ships with NO ``aria-label`` — its
    "Zip *" label is a bare ``<label>`` with no ``for``, so neither
    ``_aria_input`` nor ``get_by_label`` can reach it. What identifies it is that
    absence: every other visible text input on the form does carry an aria-label.
    The count is asserted rather than ``.first``-ed so that a deploy which adds a
    second unlabelled input fails loudly instead of silently editing the wrong
    box; the aria-label branch means a deploy that FIXES the label just works.
    """
    labelled = page.locator('input[aria-label^="Zip"]:visible')
    if labelled.count():
        return labelled.first
    unlabelled = page.locator('input[type="text"]:not([aria-label]):visible')
    count = unlabelled.count()
    assert count == 1, (
        f"expected exactly 1 unlabelled text input (the Zip field) on the My "
        f"Details form, found {count} — the form's markup has changed"
    )
    return unlabelled.first


def _confirm_yes(page: Page, text_pattern):
    """Click Yes on the confirmation overlay matching ``text_pattern``."""
    pane = page.locator(".cdk-overlay-pane").filter(has_text=text_pattern).first
    pane.wait_for(state="visible", timeout=30_000)
    pane.get_by_role("button", name=re.compile(r"^\s*Yes\s*$", re.I)).first.click()


def _click_save(page: Page):
    """Click the form's Save, first asserting it actually armed.

    Save stays ``disabled`` until the low-code layer registers a real value change,
    so a silently-unfilled field would otherwise surface as a missing toast rather
    than as the field problem it is.

    Visibility-scoped for the same reason as ``_row_buttons``: a retained tab panel
    can hold its own Save, and picking that one would fail the enabled-check below
    while the real, armed button sat on screen untouched.
    """
    save = _row_buttons(page, re.compile(r"^\s*Save\s*$", re.I)).first
    expect(save).to_be_enabled(timeout=15_000)
    save.click()


def _rand_digits(n: int) -> str:
    return "".join(str(random.randint(0, 9)) for _ in range(n))


def _write_my_details(page: Page, first: str, last: str, address: str,
                      zip_code: str, phone_digits: str):
    """Fill the open My Details form. Leaves Save to the caller."""
    _aria_input(page, "First Name").fill(first)
    _aria_input(page, "Last Name").fill(last)
    _aria_input(page, "Address").fill(address)
    _zip_input(page).fill(zip_code)
    # The zip drives a city/state lookup that fires once the 5th digit lands
    # (TW 27302845). Saving mid-lookup writes a stale city.
    page.wait_for_timeout(2500)
    _fill_phone(page.locator('input[type="tel"]:visible').first, phone_digits)
    page.wait_for_timeout(800)


def _open_my_details_edit(page: Page):
    """Reload the profile and open the My Details edit form."""
    _go_to_individual_profile(page)
    _row_buttons(page, _EDIT_BTN).first.click()
    _aria_input(page, "First Name").wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(1000)


def _select_account_type(page: Page, account_type: str):
    select = page.locator("mat-select:visible").first
    if select.inner_text().strip().lower() == account_type.lower():
        return  # already selected — reopening the panel would only risk a misclick
    select.click()
    page.wait_for_timeout(1000)
    page.get_by_role(
        "option", name=re.compile(rf"^\s*{re.escape(account_type)}\s*$", re.I)
    ).first.click()
    page.wait_for_timeout(1000)


def _write_ach(page: Page, values: dict, account_type: str):
    """Fill the bank-information form. Leaves Save to the caller."""
    page.locator('input[name="account_name"]:visible').fill(values["account_name"])
    _select_account_type(page, account_type)
    for name in ACH_FIELDS[1:]:
        page.locator(f'input[name="{name}"]:visible').fill(values[name])
    page.wait_for_timeout(800)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="class")
def portal_page(browser: Browser) -> Page:
    """ONE tab for the whole class, started LOGGED OUT on the sign-in screen.

    Phase 1 asserts the sign-on page here; phase 2's first dashboard navigation
    signs in through NCID on this same tab (see ``_sign_in``) and every later
    phase continues in it. No stored auth state is used — a stored session would
    redirect straight past the sign-in screen phase 1 exists to check.
    """
    ctx = browser.new_context(timezone_id=NC_TIMEZONE)
    page = ctx.new_page()
    _go_to_signin(page)
    yield page
    ctx.close()


@pytest.fixture(scope="class")
def individual_page(browser: Browser) -> Page:
    """A SECOND tab, in its own context, signed in as the INDIVIDUAL public user.

    Phase 14 exercises the individual account for the target environment —
    ``INDIVIDUAL_PUBLIC_USERNAME`` in ``.env.<env>``, i.e. ``Automation_act`` on QA
    and ``rahulg_indi31@yopmail.com`` on stage — whose profile
    differs from the business one every other phase uses, so it cannot share
    ``portal_page`` — two accounts cannot be signed in to one context at once.
    Its own context also keeps phase 14's writes from disturbing phases 1-13 if
    they are run in the same session.
    """
    if not (ENV.INDIVIDUAL_PUBLIC_USERNAME and ENV.INDIVIDUAL_PUBLIC_PASSWORD):
        pytest.skip("INDIVIDUAL_PUBLIC_USERNAME/PASSWORD not set for this environment")

    ctx = browser.new_context(timezone_id=NC_TIMEZONE)
    page = ctx.new_page()
    _go_to_signin(page)
    _sign_in(
        page,
        ENV.INDIVIDUAL_PUBLIC_USERNAME,
        ENV.INDIVIDUAL_PUBLIC_PASSWORD,
        company="",  # individual accounts belong to no business — never prompted
    )
    yield page
    ctx.close()


@pytest.mark.e2e
@pytest.mark.public_portal
class TestE2E055PublicPortalAssertions:
    """E2E-055: Public Portal UI assertions — read-only, no data created."""

    # ── Phase 1: Sign-on Page (logged out) ────────────────────────────────────

    def test_phase1_signin_new_users_section(self, portal_page: Page):
        """New Users / Returning Users section text is displayed on the sign-in page."""
        page = portal_page
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

    def test_phase1_signin_welcome_note(self, portal_page: Page):
        """The Welcome note describing the N&S process is displayed."""
        page = portal_page
        _ensure_signin(page)
        body = page.locator("body")
        expect(body).to_contain_text("Welcome", timeout=10_000)
        expect(body).to_contain_text(
            "The North Carolina State Highway Patrol Notice and Storage process is mandated by law"
        )
        expect(body).to_contain_text(
            "ISU N&S Section will notify a reporter by mail and email"
        )

    def test_phase1_signin_footer(self, portal_page: Page):
        """Footer contact details and standard NC.gov links are displayed."""
        page = portal_page
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

    def test_phase1_signin_links_point_to_correct_destinations(self, portal_page: Page):
        """Sign-in page links resolve to their correct external destinations.

        Verified via href (these are target=_blank external links). Covers the
        Register-section AND Sign-In-with-NCID-section Terms/Privacy links, the
        'Create an NCID' / 'About NCID' NCID links, and the Video/PDF guides.
        """
        page = portal_page
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

        # Both primary CTAs are present (``.first``: STAGE renders each of these
        # twice — its sign-in screen adds a username/password form alongside the
        # NCID path — which would otherwise trip Playwright's strict mode)
        expect(
            page.get_by_role("button", name=re.compile(r"Sign In with NCID", re.I)).first
        ).to_be_visible()
        expect(
            page.get_by_role("button", name=re.compile(r"^Register$", re.I)).first
        ).to_be_visible()

    def test_phase1_signin_register_opens_registration(self, portal_page: Page):
        """The Register button opens the 'Register Your Facility' page."""
        page = portal_page
        _ensure_signin(page)
        page.get_by_role("button", name=re.compile(r"^Register$", re.I)).first.click()
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

    def test_phase2_dashboard_loads(self, portal_page: Page):
        """Dashboard page loads and URL contains 'dashboard'."""
        page = portal_page
        _ensure_dashboard(page)
        expect(page).to_have_url(re.compile(r"dashboard", re.I), timeout=15_000)

    def test_phase2_dashboard_tabs_visible(self, portal_page: Page):
        """All four main tabs are visible on the dashboard."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)

        expect(dashboard.notice_storage_tab).to_be_visible(timeout=15_000)
        expect(dashboard.payments_tab).to_be_visible(timeout=10_000)
        expect(dashboard.sold_completed_tab).to_be_visible(timeout=10_000)
        expect(dashboard.messages_tab).to_be_visible(timeout=10_000)

    def test_phase2_start_here_button_visible(self, portal_page: Page):
        """'Start here' button is visible on the dashboard."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        expect(dashboard.start_here_button).to_be_visible(timeout=15_000)

    def test_phase2_header_business_name_visible(self, portal_page: Page):
        """Business name is displayed in the portal header."""
        page = portal_page
        _ensure_dashboard(page)
        header_biz = page.locator(
            'app-header, mat-toolbar, header, nav, '
            '[class*="header" i], [class*="toolbar" i], [class*="navbar" i]'
        ).first
        expect(header_biz).to_be_visible(timeout=15_000)

        # Header carries some text (portal title / user / business name)
        expect(header_biz).to_contain_text(re.compile(r"[A-Za-z]"), timeout=10_000)

    def test_phase2_search_input_visible(self, portal_page: Page):
        """Search / VIN input is visible on the dashboard."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        expect(dashboard.search_input).to_be_visible(timeout=15_000)

    # ── Phase 3: Case Listing ──────────────────────────────────────────────────

    def test_phase3_notice_storage_tab_shows_listing(self, portal_page: Page):
        """Notice & Storage tab renders application listing."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        _click_past_loader(page, dashboard.click_notice_storage_tab)

        # Either applications are listed or an empty-state message is shown
        applications = dashboard.application_list
        empty_state = page.locator(
            'text="No applications", text="No records", '
            '[class*="empty" i], [class*="no-data" i]'
        ).first

        # Poll instead of a fixed sleep: clicking the tab re-renders the list, and
        # a heavy account takes longer than a second to repaint it (STAGE's has 191
        # requests — a 1s wait counted zero cards there while the list was mid-render).
        has_apps = has_empty = False
        waited = 0
        while waited < 25_000:
            has_apps = applications.count() > 0
            try:
                has_empty = empty_state.is_visible()
            except Exception:
                has_empty = False
            if has_apps or has_empty:
                break
            page.wait_for_timeout(500)
            waited += 500

        assert has_apps or has_empty, "Notice & Storage tab shows neither applications nor empty state"

    def test_phase3_application_list_has_vin_column(self, portal_page: Page):
        """Application listing shows VIN or reference number for each entry."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        _click_past_loader(page, dashboard.click_notice_storage_tab)
        page.wait_for_timeout(1000)

        if dashboard.application_list.count() > 0:
            vin_text = page.locator(
                '[class*="vin" i], [class*="reference" i], '
                'td:nth-child(1), [class*="group-block"] span'
            ).first
            expect(vin_text).to_be_visible(timeout=10_000)

    def test_phase3_search_accepts_input(self, portal_page: Page):
        """Search input accepts text and is interactive."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        expect(dashboard.search_input).to_be_visible(timeout=15_000)
        expect(dashboard.search_input).to_be_enabled(timeout=5_000)
        dashboard.search_input.fill("TEST123")
        assert dashboard.search_input.input_value() == "TEST123"
        dashboard.search_input.fill("")

    # ── Phase 4: Payments Tab ──────────────────────────────────────────────────

    def test_phase4_payments_tab_navigates(self, portal_page: Page):
        """Clicking Payments tab loads payment history content area."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        _click_past_loader(page, dashboard.click_payments_tab)

        content = page.locator(
            '[class*="payment" i], table, '
            '[class*="history" i], [class*="tab-content" i], '
            'mat-tab-body'
        ).first
        expect(content).to_be_visible(timeout=15_000)

    # ── Phase 5: Sold / Completed Tab ──────────────────────────────────────────

    def test_phase5_sold_tab_navigates(self, portal_page: Page):
        """Clicking Sold/Completed tab renders its content area."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        _click_past_loader(page, dashboard.click_sold_completed_tab)

        content = page.locator(
            '[class*="sold" i], [class*="completed" i], '
            'mat-tab-body, [class*="tab-content" i]'
        ).first
        expect(content).to_be_visible(timeout=15_000)

    # ── Phase 6: Messages Tab ──────────────────────────────────────────────────

    def test_phase6_messages_tab_navigates(self, portal_page: Page):
        """Clicking Messages tab renders inbox/message area."""
        page = portal_page
        _ensure_dashboard(page)
        dashboard = PublicDashboardPage(page)
        _click_past_loader(page, dashboard.click_messages_tab)

        content = page.locator(
            'mat-tab-body:visible, [class*="inbox" i]:visible, '
            '[class*="message" i]:visible, [class*="tab-content" i]:visible'
        ).first
        expect(content).to_be_visible(timeout=15_000)

    # ── Phase 7: Profile Page ──────────────────────────────────────────────────

    def test_phase7_profile_page_navigates(self, portal_page: Page):
        """My Profile link navigates to the profile page."""
        page = portal_page
        _ensure_dashboard(page)  # start from the dashboard so the link nav is meaningful
        PublicProfilePage(page).navigate_to_profile()
        expect(page).to_have_url(re.compile(r"profile|account|my-profile", re.I), timeout=15_000)

    def test_phase7_profile_shows_user_info(self, portal_page: Page):
        """Profile page displays user/business information."""
        page = portal_page
        _ensure_profile(page)  # no reload if a prior phase-7 test is already here
        user_info = page.locator(
            '[class*="profile" i] span, [class*="user-info" i], '
            '[class*="name" i], [class*="email" i], '
            'input[name*="name" i], input[name*="email" i]'
        ).first
        expect(user_info).to_be_visible(timeout=15_000)

    def test_phase7_drawdown_balance_section_visible(self, portal_page: Page):
        """Drawdown balance lives on the profile's ACH tab — assert it there.

        This was routed through ``PublicProfilePage.navigate_to_drawdown()``, which
        hunts for an 'Accounts' tab and a 'Drawdown' link this portal does not have
        and pays a ``wait_for_load_state("networkidle")`` for each miss — a state
        this SPA never reaches, so every miss cost its full timeout: 73 s on QA
        (measured 2026-08-11) to reach a page one tab-click away.

        It also could not fail. ``expect_balance_displayed()`` swallows its own
        assertion error, and the balance carries no ``class*="balance"``/``"wallet"``
        hook on either env (probed 2026-08-11), so the locator matched nothing and
        the silent fallback waved the test through regardless of what was on screen.

        The Drawdown block is gated on bank information existing: STAGE's business
        has ACH configured and renders "Drawdown / Current Balance: $… / Add Funds",
        QA's has an empty bank form and renders no Drawdown block at all. Both
        states are asserted rather than tolerated, so a business that later gains
        bank details starts exercising the balance assertion on its own.
        """
        page = portal_page
        _go_to_profile(page)
        _open_profile_tab(page, re.compile(r"^\s*ACH\s*$", re.I))

        # The ACH surface itself is unconditional on both envs.
        expect(page.locator("body")).to_contain_text("Bank Information", timeout=20_000)
        expect(
            page.locator('input[name="account_name"]:visible')
        ).to_be_visible(timeout=15_000)

        balance_label = page.get_by_text(re.compile(r"Current Balance", re.I))
        add_funds = page.get_by_role("button", name=re.compile(r"^\s*Add Funds\s*$", re.I))

        if balance_label.count():  # drawdown wallet configured for this business
            expect(balance_label.first).to_be_visible(timeout=10_000)
            expect(add_funds.first).to_be_visible(timeout=10_000)
            shown = re.search(r"\$\s?[\d,]+(?:\.\d{2})?", page.locator("body").inner_text())
            assert shown, "Drawdown block is rendered but shows no dollar amount"
        else:  # no bank information -> the whole block must be absent, not empty
            expect(add_funds).to_have_count(0)

    # ── Phase 8: Navigation ────────────────────────────────────────────────────

    def test_phase8_navigation_returns_to_dashboard(self, portal_page: Page):
        """Returning to the dashboard from My Profile works.

        This portal has NO in-app 'home'/logo link back to the dashboard: the
        header logo points to the external NCSHP website (ncshp.gov) and the
        portal banner is a non-interactive 'disableHeader' element (verified via
        DOM inspection). The supported way back is browser navigation, so we
        verify that going Back from the profile restores the dashboard and it
        re-renders.
        """
        page = portal_page
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

    def test_phase9_edit_my_details(self, portal_page: Page):
        """My Details edit: set random first name, last name, title -> save.

        The first/last name MUST be restored afterwards: this runs as the shared
        daniel_scott account, and its display name ("Daniel Scott") is asserted by
        E2E-012/024/038 attribution checks. Leaving a random name behind corrupts
        the QA account for every later run (this happened — it got stuck as
        "James Smith" and broke E2E-038 phase 4).
        """
        page = portal_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state

        # 'My Details' is the first Edit button on the My Profile tab
        _row_buttons(page, _EDIT_BTN).first.click()
        page.wait_for_timeout(1000)

        first_input = _profile_input(page, "First Name", "firstName")
        last_input = _profile_input(page, "Last Name", "lastName")
        title_input = _profile_input(page, "Title", "title")
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
            # Restore the original identity regardless of assertion outcome.
            # Resolved through _profile_input, not a raw input[name="firstName"]:
            # the read side above already goes through it because the designer does
            # not emit that name on every environment, and a restore that cannot
            # find its fields fails inside `finally`, masking the real result.
            _go_to_profile(page)
            _row_buttons(page, _EDIT_BTN).first.click()
            page.wait_for_timeout(1000)
            _profile_input(page, "First Name", "firstName").fill(orig_first)
            _profile_input(page, "Last Name", "lastName").fill(orig_last)
            _profile_input(page, "Title", "title").fill(orig_title)
            page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
            _expect_saved_toast(page, "The details have been saved successfully")

    # ── Phase 10: Edit Company Details (WRITE) ─────────────────────────────────

    def test_phase10_edit_company_details(self, portal_page: Page):
        """Company details edit: name, location, address, NC zip, contact, phone.

        Every field is restored afterwards, the NAME above all: this form renames
        the BUSINESS ITSELF, so an unrestored run retires the name ``PINNED_COMPANY``
        looks for at sign-in and the next run silently lands on a different company
        (this happened — a run renamed 'Triangle Garage' to a random Faker name, and
        the sign-in after it fell back to the first business in the list). Other E2E
        tests also select their business by name, so leaving a random one behind is
        not local to this file. Same reasoning as phase 9's name restore.
        """
        page = portal_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state
        addr = generate_address()

        # Company Details is the second Edit button on the My Profile tab
        _row_buttons(page, _EDIT_BTN).nth(1).click()
        page.wait_for_timeout(1000)

        text_fields = ("name", "location", "address", "zip", "contact_person")
        original = {
            f: page.locator(f'input[name="{f}"]:visible').input_value() for f in text_fields
        }
        original_phone = re.sub(
            r"\D", "", page.locator('input[name="contact_phone"]:visible').input_value()
        )

        try:
            page.locator('input[name="name"]:visible').fill(generate_company_name())
            page.locator('input[name="location"]:visible').fill(generate_location_name())
            page.locator('input[name="address"]:visible').fill(addr["street"])
            page.locator('input[name="zip"]:visible').fill(addr["zip"])
            page.wait_for_timeout(1500)  # let the zip -> city auto-lookup finish
            page.locator('input[name="contact_person"]:visible').fill(generate_full_name())
            _fill_phone(page.locator('input[name="contact_phone"]:visible'), _rand_phone_digits())

            page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
            _expect_saved_toast(page, "The details have been saved successfully")
        finally:
            # Put the business back regardless of assertion outcome
            _go_to_profile(page)
            _row_buttons(page, _EDIT_BTN).nth(1).click()
            page.wait_for_timeout(1000)
            for field, value in original.items():
                page.locator(f'input[name="{field}"]:visible').fill(value)
            page.wait_for_timeout(1500)  # zip -> city lookup again before saving
            if original_phone:
                _fill_phone(page.locator('input[name="contact_phone"]:visible'), original_phone)
            page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
            _expect_saved_toast(page, "The details have been saved successfully")

    # ── Phase 11: Address Book (WRITE) ─────────────────────────────────────────

    def test_phase11_address_book_delete(self, portal_page: Page):
        """Add an address, then delete it (confirm with Yes).

        Provisions the row it deletes rather than hunting for a deletable one.
        Both envs ship exactly ONE address and the portal disables Delete on the
        last remaining entry (QA and STAGE both probed 2026-08-11), so the previous
        "skip when nothing is deletable" guard fired on BOTH — this path had never
        actually run anywhere. Creating the row first makes the test self-sufficient,
        identical across envs, and net-zero: it only ever deletes what it added, so
        it can never destroy real account data or drain the book toward empty.

        The ``finally`` is what makes "net-zero" true even when the test fails
        mid-way. Without it, a failure after the add leaves the provisioned row
        behind for every later run to trip over — which is exactly what happened
        on QA on 2026-08-11, orphaning an 'E055'-style row that had taken the
        mailing flag and so could not be deleted by hand either.
        """
        page = portal_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state
        _open_profile_tab(page, re.compile(r"Address Book", re.I))
        _row_buttons(page, _DELETE_BTN).first.wait_for(
            state="visible", timeout=15_000
        )

        added = _add_address(page)
        removed = False
        try:
            # Re-read from a clean server load: the saved form leaves its own labels
            # in the DOM, desynchronising card order from Delete-button order.
            _go_to_profile(page)
            _open_profile_tab(page, re.compile(r"Address Book", re.I))
            names = _addresses_on_page(page)
            assert added in names, f"provisioned address {added!r} missing from {names}"
            index = names.index(added)

            deletes = _row_buttons(page, _DELETE_BTN)
            # A second address is what unlocks Delete — assert that, since it is the
            # product behaviour that used to make this test unrunnable.
            expect(deletes.nth(index)).to_be_enabled(timeout=10_000)
            before = _delete_card_at(page, index)

            expect(
                _row_buttons(page, _DELETE_BTN)
            ).to_have_count(before - 1, timeout=15_000)
            expect(page.locator("body")).not_to_contain_text(added, timeout=10_000)
            removed = True
        finally:
            if not removed:
                _remove_address_if_present(page, added)

    def test_phase11_address_book_edit(self, portal_page: Page):
        """Edit an address: random location name, address, NC zip -> save.

        Asserts the saved VALUES land in the Address Book list rather than a
        success toast: STAGE saves the address silently (no toast at all, verified
        2026-08-07) while QA pops one, so the toast can't be the cross-env signal —
        the persisted row can.
        """
        page = portal_page
        _go_to_profile(page)  # write tests reload for a clean, isolated form state
        _open_profile_tab(page, re.compile(r"Address Book", re.I))
        addr = generate_address()
        new_location = generate_location_name()

        _row_buttons(page, _EDIT_BTN).first.click()
        page.wait_for_timeout(1000)

        page.locator('input[name="locationName"]:visible').fill(new_location)
        page.locator('input[name="address"]:visible').fill(addr["street"])
        page.locator('input[name="zip"]:visible').fill(addr["zip"])
        page.wait_for_timeout(1500)  # let the zip -> city auto-lookup finish before saving

        page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()

        try:
            expect(page.locator("body")).to_contain_text(new_location, timeout=15_000)
        except AssertionError:
            # Fall back to a server reload in case the list didn't refresh in place
            _go_to_profile(page)
            _open_profile_tab(page, re.compile(r"Address Book", re.I))
            expect(page.locator("body")).to_contain_text(new_location, timeout=15_000)
        expect(page.locator("body")).to_contain_text(addr["street"], timeout=10_000)

    # ── Phase 12: Edit User (WRITE) ────────────────────────────────────────────

    def test_phase12_edit_existing_user(self, portal_page: Page):
        """Modify an EXISTING user in the Users list: new phone + flipped Role.

        Targets the first card that is NOT the signed-in account — see
        ``_own_email`` for why that is matched by email and not by position (the
        owner is card 1 on one QA business and card 3 on another, and demoting our
        own Admin role would lock this suite out of the business for good).

        Why phone + Role rather than the name: Save on this form only arms when the
        low-code layer registers a real value change, and editing First/Last Name
        never arms it — worse, a name edit wedges the form so a following Role
        change can't arm Save either (reproduced 2026-08-07: fields ng-valid/ng-dirty,
        no mat-error, Save still disabled=true). Suspected product defect, not filed.
        Re-entering the phone and flipping the Role each arm Save on their own.

        The Role flip is self-inverting (Admin <-> Standard User), so repeat runs
        toggle one user back and forth instead of accumulating state — unlike the
        previous add-user version of this phase, which left a fresh @yopmail.com
        account on the business every single run.

        When the business has NO user other than the signed-in one, the test creates
        one, edits that, and deletes it again in the ``finally``. STAGE's business
        has exactly one user (probed 2026-08-11) and used to skip here, so this phase
        only ever ran on QA; provisioning covers both envs without leaving an account
        behind the way the old add-user version did.
        """
        page = portal_page
        _go_to_profile(page)  # full reload: the heavy Users tab needs a clean load
        own = _own_email(page)  # read on My Profile, before the tab switch
        _open_users_tab(page)

        users = _users_on_page(page)
        # Never our own card. Without an own-email read, fall back to "anything but
        # the first", the previous (weaker) assumption.
        def _non_owner_indexes(cards: list[dict]) -> list[int]:
            if own:
                return [i for i, u in enumerate(cards) if u["email"].lower() != own]
            return list(range(1, len(cards)))

        others = _non_owner_indexes(users)
        provisioned = ""
        if not others:
            provisioned = _add_user(page)
            _go_to_profile(page)
            _open_users_tab(page)
            users = _users_on_page(page)
            others = _non_owner_indexes(users)
            assert others, (
                f"provisioned {provisioned} but the Users list still shows no "
                f"non-owner card: {[u['email'] for u in users]}"
            )
        index = others[0]
        target = users[index]
        new_role = "Standard User" if target["role"].lower() == "admin" else "Admin"
        digits = _rand_phone_digits()
        expected_phone = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

        try:
            # Open that card's inline edit form (Edit buttons follow card order)
            _row_buttons(page, _EDIT_BTN).nth(index).click()
            page.wait_for_timeout(2500)

            # ``phoneNo``/``mat-select`` order hold on QA; the ``or_`` fallbacks keep
            # this working on an env whose designer emits generated names here the
            # way the Add-User form does on both (see ``_aria_input``).
            _fill_phone(
                page.locator('input[name="phoneNo"]:visible')
                .or_(page.locator('input[type="tel"]:visible'))
                .first,
                digits,
            )
            page.wait_for_timeout(500)

            # Role is the first mat-select in the open card (Location is the second)
            page.locator('mat-select[aria-label^="Role"]:visible').or_(
                page.locator("mat-select:visible")
            ).first.click()
            page.wait_for_timeout(800)
            page.get_by_role(
                "option", name=re.compile(rf"^\s*{re.escape(new_role)}\s*$", re.I)
            ).first.click()
            page.wait_for_timeout(1500)

            save = page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first
            expect(save).to_be_enabled(timeout=10_000)
            save.click()
            page.wait_for_timeout(1500)  # let the POST leave; the reload below re-waits

            # Assert the OUTCOME from a fresh server load, not a toast: this form's save
            # does not refresh the list in place, so the edit only shows after reloading
            # the profile and re-opening the tab.
            _go_to_profile(page)
            _open_users_tab(page)
            after = {u["email"]: u for u in _users_on_page(page)}
            assert target["email"] in after, (
                f"user {target['email']} disappeared from the Users list after the edit"
            )
            edited = after[target["email"]]
            assert edited["role"] == new_role, (
                f"role not saved: expected {new_role!r}, list shows {edited['role']!r}"
            )
            assert edited["phone"] == expected_phone, (
                f"phone not saved: expected {expected_phone!r}, list shows {edited['phone']!r}"
            )
        finally:
            # Remove the user this test created, pass or fail, so the business ends
            # the run with the same roster it started with.
            if provisioned:
                _go_to_profile(page)
                _open_users_tab(page)
                emails = [u["email"].lower() for u in _users_on_page(page)]
                if provisioned.lower() in emails:
                    _delete_card_at(page, emails.index(provisioned.lower()))
                    expect(page.locator("body")).not_to_contain_text(
                        provisioned, timeout=15_000
                    )

    # ── Phase 13: LT-260 Form via "Start here" ─────────────────────────────────

    def test_phase13_lt260_form_text(self, portal_page: Page):
        """'+ Start here' opens the LT-260 form with the expected guidance text."""
        page = portal_page
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

    def test_phase13_vin_lookup_oiq_error(self, portal_page: Page):
        """'VIN123' (contains I) -> error popup including the O/I/Q guidance.

        The lookup-failed toast is asserted only when it appears: for this SHORT
        VIN, STAGE never raises it (the length check short-circuits before the
        lookup) while QA does. The popup itself is raised by both, so that is what
        this test requires. The 17-char case below does toast on both envs.
        """
        page = portal_page
        _go_to_lt260(page)
        _vin_lookup(page, "VIN123")

        try:
            expect(
                page.get_by_text("The VIN could not be found during the lookup", exact=False).first
            ).to_be_visible(timeout=8_000)
        except AssertionError:
            pass  # STAGE: no toast for a sub-17-character VIN

        dialog = _vin_error_dialog(page)
        expect(dialog).to_be_visible(timeout=10_000)
        expect(dialog).to_contain_text("THE VIN ENTERED MAY HAVE AN ERROR")
        expect(dialog).to_contain_text("does not include the letters")  # O/I/Q guidance
        expect(dialog).to_contain_text("be decoded by our VIN decoding service")
        expect(dialog).to_contain_text("not 17 characters long")
        expect(dialog).to_contain_text("upload an image of the VIN")

        page.get_by_role("button", name=re.compile(r"^\s*Cancel\s*$", re.I)).first.click()
        page.wait_for_timeout(1000)

    def test_phase13_vin_lookup_undecodable_error(self, portal_page: Page):
        """A 17-char junk VIN (no I/O/Q) -> toast + 'could not be decoded' popup.

        The app does NOT show the 'not 17 characters long' line here (the VIN is
        exactly 17 chars) nor the O/I/Q line (no such letters), so we don't assert
        them.
        """
        page = portal_page
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

    def test_phase13_vin_lookup_disabled_for_overlong_vin(self, portal_page: Page):
        """A VIN longer than 17 characters disables the VIN Lookup button."""
        page = portal_page
        _go_to_lt260(page)
        vin_input = page.locator('input[name="sno"]')
        vin_input.click()
        vin_input.fill("sxzcxvxcvxzbbcxzbxcvxzvxzcvzxvxc")  # 32 chars
        page.wait_for_timeout(800)
        expect(page.locator('button:has-text("VIN Lookup")').first).to_be_disabled(timeout=10_000)

    # ── Phase 14: Individual account — profile, ACH, drawdown (WRITE) ─────────

    def test_phase14_individual_edit_my_details(self, individual_page: Page):
        """My Details edit on the INDIVIDUAL account: name, address, NC zip, phone.

        NOT restored (user instruction, 2026-08-10) — unlike phases 9 and 10, which
        put the business account back. Each run leaves the environment's individual
        account (QA: ``Automation_act``, stage: ``rahulg_indi31@yopmail.com``)
        carrying the random name, address, NC zip and phone it last wrote. Anything
        that expects this account to read "Automation Act" or "Automation script"
        will see whatever the most recent run left instead.
        """
        page = individual_page
        _open_my_details_edit(page)
        addr = generate_address()

        _write_my_details(
            page,
            first=generate_first_name(),
            last=generate_last_name(),
            address=addr["street"],
            zip_code=addr["zip"],
            phone_digits=_rand_phone_digits(),
        )
        _click_save(page)
        _expect_saved_toast(page, MY_DETAILS_SAVED)

    def test_phase14_individual_edit_bank_information(self, individual_page: Page):
        """ACH bank information: account name, type, 9-digit routing, 17-digit account.

        Both "Reenter" fields get the same value as the field they confirm —
        mismatched pairs fail validation and never arm Save.

        Save raises an "Are you sure you want to save your bank information?"
        confirmation; the success toast only follows the Yes. Skipping that click
        leaves the overlay up, which silently blocks everything behind it —
        including the Add Funds button the next test needs.

        NOT restored (user instruction, 2026-08-10) — the account keeps the random
        account name, type, routing and account numbers this test writes. Add Funds
        was verified to still work against random bank details (2026-08-10), so
        phase 14 stays self-consistent; what changes is that the account no longer
        holds the funding details it was set up with.
        """
        page = individual_page
        _ensure_individual_profile(page)
        _open_ach_tab(page)

        routing = _rand_digits(9)
        account = _rand_digits(17)
        new_values = {
            "account_name": generate_full_name(),
            "bank_routing_number": routing,
            "bank_routing_number_reentered": routing,
            "bank_account_number": account,
            "bank_account_number_reentered": account,
        }

        _write_ach(page, new_values, random.choice(ACCOUNT_TYPES))
        _click_save(page)
        _confirm_yes(page, ACH_CONFIRM_TEXT)
        _expect_saved_toast(page, BANK_SAVED)

    def test_phase14_individual_add_funds(self, individual_page: Page):
        """Drawdown -> Add Funds: credit a random 2-digit amount to the wallet.

        NOT restored — the portal offers no matching debit, so every run of this
        test leaves the account $10-$99 richer. That is inherent to the flow, not
        an oversight; the amount is kept to two digits to bound the drift.

        The toast quotes the amount back, so asserting it (rather than a generic
        "success") also proves the value that reached the server was the value
        typed.
        """
        page = individual_page
        _ensure_individual_profile(page)
        _open_ach_tab(page)

        amount = random.randint(10, 99)
        page.get_by_role("button", name=re.compile(r"^\s*Add Funds\s*$", re.I)).first.click()

        dialog = page.locator(".cdk-overlay-pane").filter(
            has_text=re.compile(r"Add Funds", re.I)
        ).first
        dialog.wait_for(state="visible", timeout=30_000)
        dialog.locator("input:visible").first.fill(str(amount))
        page.wait_for_timeout(800)

        save = dialog.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first
        expect(save).to_be_enabled(timeout=15_000)
        save.click()

        _expect_saved_toast(
            page,
            f"Your Drawdown account has been successfully credited with ${amount}",
        )
