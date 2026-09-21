"""
NSM Staff Portal — UI Assertions (CROSS-ENVIRONMENT: QA / STAGE)

Runs UNCHANGED against QA and STAGE. Nothing environment-specific lives in
this file — hosts, routes and credentials come from `.env.qa` / `.env.stage`
via `src.config.env.ENV`, and the auth session comes from the shared
`staff_context` fixture (tests/conftest.py). The environment is chosen the
same way as every other test in this suite, by ONE flag:

    python -m pytest tests/test_e2e_063_staff_portal_assertions.py               # qa (default)
    python -m pytest tests/test_e2e_063_staff_portal_assertions.py --env=stage
    NSM_ENV=stage    pytest tests/test_e2e_063_staff_portal_assertions.py        # equivalent to --env=stage
    python -m pytest tests/test_e2e_063_staff_portal_assertions.py --headed      # visible browser

Cross-environment design rules applied here:
  * Timeouts are NAMED BUDGETS scaled per environment (`nsm_env.timeout`), never
    literals — STAGE has been observed to run/boot slower than QA.
  * Assertions are STRUCTURAL, never data-valued. Where a check genuinely needs
    a minimum dataset (pagination, page-size, filtering), the test SKIPS with a
    reason on a smaller environment rather than failing — a small QA dataset is
    a legitimate environment difference, not a bug.
  * Failures carry environment context (`nsm_env.check` / `nsm_env.describe`)
    so a red test says WHICH environment and WHAT value it saw.

Login is SSO via Expertly (the sign-in page says "Use your NC DOT/DMV
credentials to log in"), but this suite never drives that flow directly — the
`staff_context` fixture supplies an already-authenticated session (a stored
Playwright storage_state per environment) so tests start from the dashboard.

Phases (numbering starts at 3 — phases 1/2 (nav + dashboard KPIs) were dropped):
  3. LT-260 Listing — the heading + Add-from-Paper/Download actions, the status
     tabs (To Process..All), the 12 table columns, and the results/pagination
     controls.

Almost every phase here is READ-ONLY (no writes to the account). The exceptions,
all at the end and all self-contained:
  * phase 16 edits the LT-262 processing fee and then edits it straight back —
    fenced to QA/STAGE, restored in a try/finally, future-dated so the fee LT-262
    payments actually charge never moves (see its docstring for the two residues:
    the Effective Date can't be walked back; Fee History accrues an audit row).
  * phase 17 opens the "Add DMV User" form and Cancels — no user is created.
  * phase 19 (LAST) logs out. This ends the session AND invalidates the stored
    auth/<env>/staff-portal.json server-side, so its finally block re-mints it via
    scripts/save_staff_auth.py. It lives in its own class (TestE2E063Logout) at the
    end of the file so pytest can't schedule anything after it — see that class.
"""

import datetime as dt
import os
import re
import subprocess
import sys

import pytest
from playwright.sync_api import BrowserContext, Page, expect

from pathlib import Path
from urllib.parse import urlsplit

from src.config.env import ENV

# ══ CROSS-ENVIRONMENT SUPPORT ══════════════════════════════════════════════
#
# This file started as a straight copy of the standalone C:\automation\
# Staff_assertions.py harness — its own `import nsm_env` module (a separate
# timeout/assert/credential helper) and hardcoded STAFF_CONFIG login table for
# qa/uat/prod. Neither exists in this repo, and this suite already has its own
# way to switch environments, so it's rewired to that instead:
#
#   python -m pytest tests/test_e2e_063_staff_portal_assertions.py --env=qa     # default
#   python -m pytest tests/test_e2e_063_staff_portal_assertions.py --env=stage
#
# `--env` (repo-root conftest.py, choices qa/stage) sets NSM_ENV, which
# `src.config.env.ENV` reads to load `.env.qa` / `.env.stage`, and which
# `tests/conftest.py`'s `staff_context` fixture reads to pick the matching
# stored session under auth/<env>/staff-portal.json. No in-suite login flow is
# needed any more — `dash_page` below just opens a tab on that
# already-authenticated context.

_ENV_TIMEOUTS = {
    "login": 60_000,
    "form": 20_000,
    "route": 30_000,
    "data": 30_000,
    "assert": 30_000,
    "action": 15_000,
}

# STAGE has been observed to boot/re-query more slowly than QA elsewhere in
# this suite; scale the named budgets rather than keep a second timeout table.
_ENV_SCALE = {"qa": 1.0, "stage": 1.4}


def _env_name() -> str:
    return os.getenv("NSM_ENV", "qa")


def _env_scaled(ms: int) -> int:
    return int(ms * _ENV_SCALE.get(_env_name(), 1.0))


def _env_timeout(name: str) -> int:
    return _env_scaled(_ENV_TIMEOUTS[name])


def _env_describe(page: Page) -> str:
    return f"[{_env_name()}] {page.url}"


def _env_check(condition: bool, expected: str, actual, page: Page) -> None:
    if not condition:
        raise AssertionError(f"{_env_describe(page)}: expected {expected}; got {actual!r}")


class nsm_env:
    """Drop-in shim for the standalone module this file used to import, so the
    ~115 `nsm_env.xxx(...)` call sites below didn't need touching one by one."""

    timeout = staticmethod(_env_timeout)
    scaled = staticmethod(_env_scaled)
    describe = staticmethod(_env_describe)
    check = staticmethod(_env_check)


def _staff_base_url() -> str:
    parts = urlsplit(ENV.STAFF_PORTAL_URL)
    return f"{parts.scheme}://{parts.netloc}"


def _staff_dashboard_url() -> str:
    # The app prefix is the same on every environment (unlike the public
    # portal, where the sign-in route and app prefix genuinely disagree).
    return f"{_staff_base_url()}/pages/ncdot-notice-and-storage/dashboard"

# ── LT-26x form-listing column shapes (phases 3-7) ───────────────────────────
# The three observed column layouts, built from a shared 11-column base so the
# "Form Type" / "LT-260 Submitted On" variants stay in sync.
_LT_COLS_NO_FORMTYPE = [
    "VIN", "File Number", "Date Submitted", "Submitter Name", "Vehicle Year",
    "Vehicle Make", "Vehicle Model", "Vehicle Location", "License Plate Number",
    "Updated By", "Updated Date",
]
# LT-260: the base + a "Form Type" column (before the two Updated columns).
_LT_COLS_FORMTYPE = _LT_COLS_NO_FORMTYPE[:-2] + ["Form Type"] + _LT_COLS_NO_FORMTYPE[-2:]
# LT-262/262A/263: also carry an "LT-260 Submitted On" column.
_LT_COLS_WITH_LT260 = (
    _LT_COLS_NO_FORMTYPE[:-2] + ["Form Type", "LT-260 Submitted On"] + _LT_COLS_NO_FORMTYPE[-2:]
)

# Per-section spec: nav label, a heading regex (or None + a url regex, for Sold),
# the tabs, the table columns, distinctive action buttons, and whether the section
# is a paginated listing (so the results/rows/pagination check applies).
SECTION_SPECS = {
    "LT-260": dict(
        nav="LT-260",
        heading=r"LT-260 \(Report of Unclaimed",
        tabs=["To Process", "Processed", "Rejected", "Stolen", "Draft Paper Forms", "Closed", "All"],
        columns=_LT_COLS_FORMTYPE,
        actions=["Add from Paper", "Download Options"],
        listing=True,
    ),
    "LT-261": dict(
        nav="LT-261",
        heading=r"LT-261 \(Sheriff Sale",
        tabs=["To Process", "Processed", "Rejected", "Stolen", "Draft Paper Forms", "Closed", "All"],
        columns=_LT_COLS_NO_FORMTYPE,
        actions=["Add Paper DWI", "Add Paper E-Stop"],
        listing=True,
    ),
    "LT-262": dict(
        nav="LT-262",
        heading=r"LT-262 \(Notice of Intent to Sell",
        tabs=["To Process", "Aging", "Court Hearing", "Processed", "Rejected",
              "Pending Payment", "Draft Paper Forms", "Closed", "All"],
        columns=_LT_COLS_WITH_LT260,
        actions=["Add From Paper"],
        listing=True,
    ),
    "LT-262A": dict(
        nav="LT-262A",
        heading=r"LT-262A \(Notice of Intent to Sell",
        tabs=["To Process", "Processed", "Rejected", "Draft Paper Forms", "Closed", "All"],
        columns=_LT_COLS_WITH_LT260,
        actions=["Add From Paper"],
        listing=True,
    ),
    "LT-263": dict(
        nav="LT-263",
        heading=r"LT-263 \(Notice of Sale",
        tabs=["To Process", "Processed (Sold)", "Rejected", "Draft Paper Forms", "Closed", "All"],
        columns=_LT_COLS_WITH_LT260,
        actions=["Add From Paper"],
        listing=True,
    ),
    "Sold": dict(
        nav="Sold",
        heading=None,
        url=r"/sold",
        tabs=[],
        columns=_LT_COLS_NO_FORMTYPE,
        actions=["Download Options"],
        listing=True,
    ),
    "Payments": dict(
        nav="Payments",
        heading=r"^Payments$",
        tabs=["Payment Transaction History", "Payments Missing Forms"],
        columns=[
            "VIN", "File Number", "Business/Individual Name", "Payment Type",
            "Payment Method", "Payment Amount", "Received By", "Received Date",
            "Reference Number", "PayIt Transaction ID", "Status",
        ],
        actions=["Record Mailed Payment"],
        listing=True,
    ),
    "Reports": dict(
        nav="Reports",
        heading=r"^Reports$",
        tabs=["VERIFI Reports", "System Generated Reports"],
        columns=["Report Name", "Created Date", "Last Updated Date"],
        actions=["Recent Reports"],
        listing=False,
    ),
    "Configuration": dict(
        nav="Configuration",
        heading=r"^Configuration$",
        tabs=["LT-262 Fee", "Letterhead"],
        columns=["Fee Type", "Fee Amount", "Effective Date"],
        actions=["View History"],
        listing=False,
    ),
    "User Management": dict(
        nav="User Management",
        heading=r"^User Management$",
        tabs=["DMV Users", "DMV Roles"],
        columns=["First Name", "Last Name", "Email Address", "Business Unit",
                 "Role", "Enabled", "Last Logged In"],
        actions=["Add DMV User"],
        listing=True,
    ),
    "Facility Management": dict(
        nav="Facility Management",
        # Escape the slash: Playwright serializes the pattern into /.../  so a bare
        # '/' would break the JS regex delimiter.
        heading=r"Facilities\/Individuals",
        tabs=["Facilities/Individuals", "Facility Users"],
        columns=["Business/Individual Name", "Type", "Address", "Registered On"],
        actions=["Download Options"],
        listing=True,
    ),
}


# ── Per-tab columns for the multi-tab LT-26x listings (phases 4-7) ────────────
# The "To Process" default tab is already checked by each section's phase test;
# these maps drive the per-tab coverage of every *other* status tab, mirroring
# LT-260's treatment. Column sets vary by tab (confirmed live):
#   * "Draft Paper Forms" uses "Date Created" instead of "Date Submitted"
#     (and, on LT-262/262A, "Updated At" instead of "Updated Date");
#   * "All" adds a "Status" column — except on LT-263, which is uniform.

def _draft_cols(base: list, updated_at: bool = False) -> list:
    cols = ["Date Created" if c == "Date Submitted" else c for c in base]
    if updated_at:
        cols = ["Updated At" if c == "Updated Date" else c for c in cols]
    return cols


LT26X_TAB_COLUMNS = {
    "LT-260": {
        "Processed": _LT_COLS_FORMTYPE,
        "Rejected": _LT_COLS_FORMTYPE,
        "Stolen": _LT_COLS_FORMTYPE,
        "Draft Paper Forms": _draft_cols(_LT_COLS_FORMTYPE),
        "Closed": _LT_COLS_FORMTYPE,
        "All": _LT_COLS_FORMTYPE + ["Status"],
    },
    "LT-261": {
        "Processed": _LT_COLS_NO_FORMTYPE,
        "Rejected": _LT_COLS_NO_FORMTYPE,
        "Stolen": _LT_COLS_NO_FORMTYPE,
        "Draft Paper Forms": _draft_cols(_LT_COLS_NO_FORMTYPE),
        "Closed": _LT_COLS_NO_FORMTYPE,
        "All": _LT_COLS_NO_FORMTYPE + ["Status"],
    },
    "LT-262": {
        "Aging": _LT_COLS_WITH_LT260,
        "Court Hearing": _LT_COLS_WITH_LT260,
        "Processed": _LT_COLS_WITH_LT260,
        "Rejected": _LT_COLS_WITH_LT260,
        "Pending Payment": _LT_COLS_WITH_LT260,
        "Draft Paper Forms": _draft_cols(_LT_COLS_WITH_LT260, updated_at=True),
        "Closed": _LT_COLS_WITH_LT260,
        "All": _LT_COLS_WITH_LT260 + ["Status"],
    },
    "LT-262A": {
        "Processed": _LT_COLS_WITH_LT260,
        "Rejected": _LT_COLS_WITH_LT260,
        "Draft Paper Forms": _draft_cols(_LT_COLS_WITH_LT260, updated_at=True),
        "Closed": _LT_COLS_WITH_LT260,
        "All": _LT_COLS_WITH_LT260 + ["Status"],
    },
    "LT-263": {
        "Processed (Sold)": _LT_COLS_WITH_LT260,
        "Rejected": _LT_COLS_WITH_LT260,
        "Draft Paper Forms": _LT_COLS_WITH_LT260,
        "Closed": _LT_COLS_WITH_LT260,
        "All": _LT_COLS_WITH_LT260,
    },
}

# Columns for the NON-default tab of the two-tab admin sections (their default tab's
# columns are in SECTION_SPECS[...]["columns"]). Drives per-tab coverage for phases
# 9/12/13, which loop every tab in one visit like the LT-26x sections.
SECTION_OTHER_TAB_COLUMNS = {
    "Payments": {
        "Payments Missing Forms": [
            "VIN", "Payment Type", "Payment Amount", "Received By", "Received Date", "Reference Number",
        ],
    },
    "User Management": {
        "DMV Roles": ["Business Unit", "Role"],
    },
    "Facility Management": {
        "Facility Users": ["Name", "Role", "Email Address", "Facility Name", "Last Logged In"],
    },
    # Reports' two tabs share the report-list shape...
    "Reports": {
        "System Generated Reports": ["Report Name", "Created Date", "Last Updated Date"],
    },
    # ...whereas Configuration's tabs are different tables entirely.
    "Configuration": {
        "Letterhead": ["Letterhead Field", "Value", "Effective Date"],
    },
}

# ── Record detail views (opened from a listing by clicking a VIN) ─────────────
# Per form: the URL it lands on, a heading regex identifying the form, and the
# sub-sections EVERY record of that form renders. Deliberately conservative —
# anything that varies per record is left out (status-gated action buttons,
# Owner/Lienholder blocks, LT-261's E-Stop-vs-DWI subtitle).
RECORD_DETAIL_SPECS = {
    "LT-260": dict(
        url=r"/LT-260/[^/]+/details",
        heading=r"LT-260 \(Report of Unclaimed",
        sections=["Vehicle Details", "Vehicle Storage Details", "Authorized Person",
                  "Requestor Information"],
    ),
    "LT-261": dict(
        url=r"/LT-261/[^/]+/details",
        # Subtitle varies by record type (E-Stop vs DWI) — match the form prefix only.
        heading=r"^LT-261 \(",
        sections=["Vehicle Details"],
    ),
    "LT-262": dict(
        url=r"/LT-262/[^/]+/details",
        heading=r"LT-262 \(Notice of Intent to Sell a Vehicle",
        sections=["Description of Vehicle", "Location of Vehicle", "Description of Lien"],
    ),
    "LT-262A": dict(
        url=r"/LT-262A/[^/]+/details",
        heading=r"LT-262A \(Notice of Intent to Sell a Manufactured Home",
        sections=["Description of Vehicle", "Location of Vehicle", "Description of Lien"],
    ),
    "LT-263": dict(
        # An LT-263 is a step inside the LT-262 case, so it opens on the LT-262 route
        # (.../LT-262/<id>/details?tab=5). Assert the detail view generically and let the
        # heading establish which form we're looking at.
        url=r"/details",
        heading=r"LT-263 \(Notice of Sale",
        sections=["Description Of Vehicle", "Lien Information"],
    ),
}


def _wait_for_dashboard_ready(page: Page) -> None:
    """Wait for the staff dashboard to be genuinely interactive.

    'Interactive' means the LEFT NAV has rendered, not merely that the URL is the
    dashboard route. Called by `_ensure_dashboard` (itself the fallback `_open_section`
    reaches for whenever the nav isn't already visible) and by the `dash_page` fixture's
    initial load, so returning early just relocates the failure into whichever test
    triggers that fallback next, where it surfaces as an unrelated 30s locator timeout
    with no hint of the real cause. (Observed exactly once: after leaving the full-page
    correspondence view the route was the dashboard, the nav had not rendered, and the
    FOLLOWING test failed on its first line.) So: reload once to clear a half-rendered
    SPA, then fail here, loudly.
    """
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=nsm_env.timeout("route"))
    nav = page.get_by_role("link", name="Messages/Home", exact=True).first
    try:
        nav.wait_for(state="visible", timeout=nsm_env.timeout("form"))
        return
    except Exception:
        pass

    page.reload(timeout=nsm_env.timeout("login"), wait_until="domcontentloaded")
    _wait_for_no_loader(page)
    try:
        nav.wait_for(state="visible", timeout=nsm_env.timeout("form"))
    except Exception as exc:
        raise AssertionError(
            f"{nsm_env.describe(page)} reached the dashboard route but the left nav "
            f"never rendered (no 'Messages/Home' link), even after a reload."
        ) from exc


def _ensure_dashboard(page: Page) -> None:
    """Re-navigate to the dashboard only if we've navigated away.

    Relies on the still-authenticated session the `staff_context` fixture opened
    with (tests/conftest.py, storage_state from auth/<env>/staff-portal.json).
    """
    if "dashboard" in page.url.lower():
        return
    page.goto(
        _staff_dashboard_url(),
        timeout=nsm_env.timeout("login"),
        wait_until="domcontentloaded",
    )
    _wait_for_dashboard_ready(page)


def _nav_link(page: Page, name: str):
    """A left-nav link, matched exactly (so 'LT-260' doesn't match 'LT-262')."""
    return page.get_by_role("link", name=name, exact=True).first


def _assert_listing_rows_and_pagination(page: Page, label: str) -> None:
    """Assert the listing's results summary, pagination controls, and data rows.

    Tolerant of an empty tab (0 results / 'No records'). The results count and the
    word 'results' are separate DOM nodes that populate slightly after the table
    frame, so wait for the combined '<n> results' (or a no-records state) to appear
    before reading it — otherwise the default landing is read too early.
    """
    page.wait_for_function(
        r"() => /\d[\d,]*\s+results/i.test(document.body.innerText)"
        r" || /No records/i.test(document.body.innerText)",
        timeout=nsm_env.timeout("assert"),
    )
    body = page.locator("body").inner_text()
    match = re.search(r"(\d[\d,]*)\s+results", body, re.I)
    if not match:
        # STRICT everywhere: a listing must report EITHER a total or an explicit
        # empty state. Which of the two appears is environment data; showing
        # neither is a real defect on any environment.
        nsm_env.check(
            bool(re.search(r"No records", body, re.I)),
            f"'{label}' to show either an 'N results' summary or a no-records state",
            body[:200].replace("\n", " "),
            page,
        )
        return  # genuinely empty tab — nothing further to assert

    if int(match.group(1).replace(",", "")) == 0:
        return  # empty tab reported as '0 results'

    # General UI only: the pagination controls render. No assertion on the row COUNT
    # or the actual rows/values — those change every run (see feedback: keep it general).
    expect(page.get_by_role("combobox", name=re.compile(r"Page Size", re.I)).first).to_be_visible(
        timeout=nsm_env.timeout("action")
    )
    expect(page.get_by_role("button", name=re.compile(r"Next page", re.I)).first).to_be_visible()
    expect(page.get_by_role("button", name=re.compile(r"Previous page", re.I)).first).to_be_visible()


def _open_section(page: Page, spec: dict) -> None:
    """Left nav -> a portal section, waiting for its heading (or URL, for Sold).

    Resets scroll to the top on arrival. Without the old "bounce to Messages/Home"
    full-page reload that every test used to do first, a scroll position inherited
    from wherever the PREVIOUS test left off (e.g. deep in a long record-detail view
    opened from far down the 'All' tab) can otherwise carry into the newly-opened
    section and push its tab bar out of the viewport — reproduced live as a
    `Locator.click` timeout on a status tab that Playwright kept reporting as
    "outside of the viewport" even after its own scroll-into-view attempt.
    """
    link = _nav_link(page, spec["nav"])
    try:
        link.wait_for(state="visible", timeout=nsm_env.timeout("action"))
    except Exception:
        _ensure_dashboard(page)  # re-establish the nav if we drifted off an app page
        link = _nav_link(page, spec["nav"])
    link.click()
    page.evaluate("window.scrollTo(0, 0)")
    if spec.get("heading"):
        page.get_by_role("heading", name=re.compile(spec["heading"], re.I)).first.wait_for(
            state="visible", timeout=nsm_env.timeout("data")
        )
    else:
        page.wait_for_url(re.compile(spec.get("url", re.escape(spec["nav"])), re.I), timeout=nsm_env.timeout("data"))
    _wait_for_no_loader(page)


def _check_section(page: Page, spec: dict) -> None:
    """Navigate to a section and assert its heading, tabs, columns, actions, and
    (for paginated listings) its results/rows/pagination — all read-only."""
    _open_section(page, spec)

    if spec.get("heading"):
        expect(page.get_by_role("heading", name=re.compile(spec["heading"], re.I)).first).to_be_visible(
            timeout=nsm_env.timeout("assert")
        )
    if spec.get("url"):
        expect(page).to_have_url(re.compile(spec["url"], re.I))
    for tab in spec.get("tabs", []):
        expect(page.get_by_role("tab", name=tab, exact=True).first).to_be_visible(timeout=nsm_env.timeout("action"))
    for col in spec.get("columns", []):
        expect(page.get_by_role("columnheader", name=col).first).to_be_visible(timeout=nsm_env.timeout("action"))
    for action in spec.get("actions", []):
        expect(
            page.get_by_role("button", name=re.compile(re.escape(action), re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))
    if spec.get("listing"):
        _assert_listing_rows_and_pagination(page, spec["nav"])


def _wait_for_data_rows(page: Page, timeout: int | None = None) -> None:
    """Wait until the active listing table has at least one real (multi-cell) row.

    Heavier tabs (e.g. LT-262 'All', ~9k rows) re-query slowly after a tab switch or
    a sort, so reading the rows on a fixed sleep can catch an empty intermediate state.

    A raw Playwright timeout here is one of the least informative failures in the
    suite — it says nothing about which environment ran or whether the tab was simply
    empty. Re-raise with that context, and distinguish "this environment has no data
    here" (a legitimate difference) from "the rows never rendered" (a real defect).
    """
    try:
        page.locator("table tbody tr").filter(has=page.locator("td:nth-child(2)")).first.wait_for(
            state="visible", timeout=timeout or nsm_env.timeout("assert")
        )
    except Exception as exc:
        total = _rows_available(page)
        body = page.locator("body").inner_text()
        if total == 0 or re.search(r"No records", body, re.I):
            pytest.skip(
                f"{nsm_env.describe(page)} listing reports no rows "
                f"(total={total}) — nothing to assert on this environment"
            )
        raise AssertionError(
            f"{nsm_env.describe(page)} listing reported total={total} but rendered no "
            f"data rows within {timeout or nsm_env.timeout('assert')}ms: {exc}"
        ) from exc


def _results_range(page: Page):
    """Parse a listing's '<start> - <end> of <total>' summary into (start, end, total).

    Returns None when no summary is shown. The three numbers sit in separate DOM nodes,
    so this reads the composed body text (\\s matches the newlines between them).
    """
    match = re.search(
        r"(\d[\d,]*)\s*-\s*(\d[\d,]*)\s*of\s*(\d[\d,]*)", page.locator("body").inner_text()
    )
    if not match:
        return None
    return tuple(int(g.replace(",", "")) for g in match.groups())


def _open_first_record(page: Page, section_key: str) -> None:
    """Open a section (via the left nav) and click its first record link.

    No explicit "bounce to Messages/Home" here — `_open_section` already falls back to
    `_ensure_dashboard` when the left nav isn't visible from wherever the previous test
    left the page (e.g. a record-detail view), and is a cheap no-op click when the nav
    IS already visible. The record link is a `span.table-link` (never an <a>); rows that
    can't be opened have no such span.

    A no-op nav click also means whichever TAB a prior test left active on this section
    persists (e.g. User Management's own section test ends on 'DMV Roles', which has no
    openable row) — but explicitly re-clicking the DEFAULT tab unconditionally isn't
    the fix: on LT-262 (9 status tabs, likely overflowing into Angular Material's
    horizontal tab-pagination) that same click reproducibly hung, timing out with
    Playwright reporting the already-current 'To Process' tab as permanently "outside
    of the viewport". So the tab is only switched as a FALLBACK, when the tab we
    actually land on has no openable row — never touching tab UI that didn't need it.
    """
    spec = SECTION_SPECS[section_key]
    _open_section(page, spec)
    tabs = spec.get("tabs") or []

    # ENVIRONMENT-RELATIVE: this needs not just a row, but an OPENABLE one. Rows that
    # cannot be opened (drafts) carry no `span.table-link`, so a sparse environment can
    # legitimately have rows and still nothing to open. Skip with context rather than
    # failing on a bare locator timeout.
    link = page.locator("table tbody span.table-link").first
    try:
        link.wait_for(state="visible", timeout=nsm_env.timeout("assert"))
    except Exception:
        if tabs:
            _click_tab(page, tabs[0])  # a leftover non-default tab may explain the miss
            link = page.locator("table tbody span.table-link").first
        try:
            link.wait_for(state="visible", timeout=nsm_env.timeout("assert"))
        except Exception:
            pytest.skip(
                f"{nsm_env.describe(page)} '{section_key}' has no openable record "
                f"(no span.table-link in the listing) — cannot exercise the detail view here"
            )
    _wait_for_no_loader(page)
    link.click()
    _wait_for_no_loader(page)


def _wait_for_no_loader(page: Page, timeout: int | None = None) -> None:
    """Wait for the full-page loading overlay to clear before interacting.

    Heavy listings drop a `cdk-overlay-backdrop exp-loader-overlay-backdrop` over the
    page while querying; clicking through it fails with 'intercepts pointer events'.
    """
    try:
        page.locator(".exp-loader-overlay-backdrop").last.wait_for(
            state="hidden", timeout=timeout or nsm_env.timeout("form")
        )
    except Exception:
        pass  # no loader present (or it lingered) — let the caller's click retry handle it


def _settle(page: Page, ms: int = 800) -> None:
    """Wait for the app to go idle, then a short environment-scaled grace.

    Replaces the blind fixed sleeps this suite used to carry. The loader wait is a
    real CONDITION (the app tells us it has stopped querying); only the residual
    grace for the Angular re-render is time-based, and it scales with the
    environment — the same re-render that settles in 800ms on QA can need
    noticeably longer on a loaded PROD.
    """
    _wait_for_no_loader(page)
    page.wait_for_timeout(nsm_env.scaled(ms))


def _rows_available(page: Page) -> int:
    """Total rows the current listing reports, or 0 when it reports none.

    Used to decide whether an environment's dataset is large enough to exercise a
    behaviour, instead of assuming a PROD-sized dataset.
    """
    rng = _results_range(page)
    return rng[2] if rng else 0


def _require_rows(page: Page, minimum: int, what: str) -> int:
    """Skip (don't fail) when the active environment lacks the data for `what`.

    A smaller QA/UAT dataset is a legitimate environment difference. Failing there
    would be a false alarm; silently passing would hide a real regression. Skipping
    with the observed total says exactly why the check didn't run.
    """
    total = _rows_available(page)
    if total < minimum:
        pytest.skip(
            f"{nsm_env.describe(page)} needs >= {minimum} rows to exercise {what}; "
            f"this environment reports {total}"
        )
    return total


# Sections whose listing is paginated and therefore share the table/paginator
# component. LT-260 is excluded: it has its own dedicated pagination / sorting /
# page-size / filtering tests, so parametrising it too would only duplicate them.
PAGINATED_SECTIONS = [
    "LT-261", "LT-262", "LT-262A", "LT-263", "Sold", "Payments", "User Management",
]

# A VIN-shaped term that cannot match a real record on any environment. VINs are
# 17 chars and never contain I/O/Q; this is deliberately both too short and full of
# excluded letters, so "no results" is a strict expectation rather than a data fact.
_NO_MATCH_TERM = "ZZZZNOSUCHVIN0000"


def _open_section_data_tab(page: Page, section_key: str) -> None:
    """Open a section via the left nav and land on the tab that actually HOLDS data.

    A section's DEFAULT tab is not necessarily populated: on PROD, LT-261's default
    'To Process' tab reports 0 rows while its 'All' tab holds 276. Anything asserting
    listing BEHAVIOUR (paging, sorting) must therefore run on the data-bearing tab or
    it would skip everywhere for the wrong reason. 'All' is that tab where a section
    has one; sections without status tabs (Sold) or with content tabs (Payments,
    User Management) use the tab they land on.
    """
    spec = SECTION_SPECS[section_key]
    _open_section(page, spec)

    tabs = spec.get("tabs") or []
    if "All" in tabs:
        _click_tab(page, "All")
        # A tab switch re-queries server-side, and the ROWS can render before the
        # results summary catches up — so a range read straight after the click can
        # still describe the PREVIOUS tab. That made LT-262A skip as "only one page"
        # (its 'To Process' tab holds <=10) even though its 'All' tab holds 55: it
        # passed in isolation and skipped in sequence, the signature of a race.
        # A skip that hides a real check is worse than a failure, so settle properly.
        _wait_for_no_loader(page)
        _settle(page, 1500)
    _wait_for_data_rows(page)


def _assert_pagination_advances(page: Page, section_key: str) -> None:
    """Next/Previous actually move the '<start> - <end> of <total>' window.

    Section-agnostic: the same paginator component backs every listing, so this is
    the check that would catch a regression in it. Asserts MOVEMENT and that the
    total holds steady — never the numbers themselves, which are environment data.
    """
    before = _results_range(page)
    nsm_env.check(
        bool(before),
        f"{section_key}: an '<start> - <end> of <total>' summary on the listing",
        before,
        page,
    )
    # ENVIRONMENT-RELATIVE: paging needs more than one page of data.
    if before[1] >= before[2]:
        pytest.skip(
            f"{nsm_env.describe(page)} {section_key}: only one page of results "
            f"({before[0]}-{before[1]} of {before[2]}) — nothing to page through"
        )

    _wait_for_no_loader(page)
    page.get_by_role("button", name=re.compile(r"Next page", re.I)).first.click()
    _wait_for_no_loader(page)
    _wait_for_data_rows(page)
    after = _results_range(page)
    nsm_env.check(
        bool(after) and after[0] > before[0],
        f"{section_key}: Next page to advance the window past start={before[0]}",
        after,
        page,
    )
    nsm_env.check(
        after[2] == before[2],
        f"{section_key}: the total to hold steady at {before[2]} while paging",
        after[2],
        page,
    )

    _wait_for_no_loader(page)
    page.get_by_role("button", name=re.compile(r"Previous page", re.I)).first.click()
    _wait_for_no_loader(page)
    _wait_for_data_rows(page)
    back = _results_range(page)
    nsm_env.check(
        bool(back) and back[0] == before[0],
        f"{section_key}: Previous page to return the window to start={before[0]}",
        back,
        page,
    )


def _assert_all_columns_sortable(page: Page, section_key: str) -> None:
    """Every column of the section's listing exposes BOTH sort controls.

    Verified live across all eight paginated sections: every column carries a
    `sortAscButton-<n>` / `sortDescButton-<n>` pair. Those aria-labels are the only
    stable handle on sorting — there is no `aria-sort`, and the buttons' classes and
    `aria-pressed` are identical before and after a sort, so the sorted STATE cannot
    be asserted. Strict on all environments: the column set is structure, not data.
    """
    columns = SECTION_SPECS[section_key].get("columns", [])
    missing = []
    for col in columns:
        header = page.get_by_role("columnheader", name=col).first
        if header.count() == 0:
            missing.append(f"{col}=NO-HEADER")
            continue
        for direction in ("sortAsc", "sortDesc"):
            if header.get_by_role("button", name=re.compile(direction, re.I)).count() == 0:
                missing.append(f"{col}:{direction}")
    nsm_env.check(
        not missing,
        f"{section_key}: asc+desc sort controls on all {len(columns)} columns",
        f"missing {missing}",
        page,
    )


def _run_same_page_checks(page: Page, label: str, checks) -> None:
    """Run several checks that share ONE page visit, without letting a data-driven
    skip in one of them silently drop the others.

    Consolidating checks into a single visit is what removes redundant navigation,
    but it introduces a hazard: a `pytest.skip` raised by one check (e.g. "only one
    page of results" on a small QA dataset) propagates out of the whole test and
    would quietly discard every check after it. So each runs independently — real
    failures still fail the test immediately and loudly, while skips are collected.
    The test is only reported as skipped if NOTHING could be verified.
    """
    skipped = []
    for name, fn in checks:
        try:
            fn()
        except pytest.skip.Exception as exc:
            skipped.append(f"{name} ({exc})")
    if skipped and len(skipped) == len(checks):
        pytest.skip(f"{nsm_env.describe(page)} {label}: every check skipped — "
                    + "; ".join(skipped))
    if skipped:
        # Some checks DID verify their behaviour, so this is a pass, not a skip —
        # but say plainly which ones the environment's data could not exercise.
        print(f"\n[{label}] data-limited, not run: " + "; ".join(skipped))


def _assert_non_vin_sort(page: Page, section_key: str) -> None:
    """Sorting works on a column other than VIN — the listing re-queries and still
    renders rows after both asc and desc.

    The resulting ORDER is deliberately not asserted: it depends entirely on the
    environment's data.
    """
    header = page.get_by_role("columnheader", name="File Number").first
    expect(header).to_be_visible(timeout=nsm_env.timeout("assert"))
    for direction in ("sortAsc", "sortDesc"):
        btn = header.get_by_role("button", name=re.compile(direction, re.I)).first
        expect(btn).to_be_visible(timeout=nsm_env.timeout("action"))
        _wait_for_no_loader(page)
        btn.click()
        _wait_for_no_loader(page)
        _wait_for_data_rows(page)


def _assert_page_size_widens(page: Page, section_key: str) -> None:
    """Changing the page size widens the page: the visible window and the rendered row
    count both grow. Restores 'Show 10' so later checks see the default."""
    before = _results_range(page)
    nsm_env.check(
        bool(before), f"{section_key}: a results summary on the listing", before, page
    )
    # ENVIRONMENT-RELATIVE: widening 10 -> 20 can only be observed when the listing
    # holds more than one default page. With <= 10 total rows the window legitimately
    # does not move — a small-dataset fact rather than a defect.
    _require_rows(page, 11, "a page-size increase (needs more than one page of 10)")
    rows_before = page.locator("table tbody tr").filter(has=page.locator("td:nth-child(2)")).count()

    def _set_page_size(option: str) -> None:
        _wait_for_no_loader(page)
        page.get_by_role("combobox", name=re.compile(r"Page Size", re.I)).first.click()
        _settle(page, 800)
        page.get_by_role("option", name=re.compile(option, re.I)).first.click()
        _wait_for_no_loader(page)
        _wait_for_data_rows(page)

    _set_page_size(r"Show 20")
    after = _results_range(page)
    # STRICT everywhere (given the row guard above): a bigger page size must widen
    # the visible window.
    nsm_env.check(
        bool(after) and after[1] > before[1],
        f"{section_key}: a wider window than end={before[1]} after selecting 'Show 20'",
        after,
        page,
    )

    # The results summary updates BEFORE the extra rows finish rendering, and
    # `_wait_for_data_rows` only waits for the FIRST row — so poll until the rendered
    # row count actually catches up with the widened window.
    data_rows = page.locator("table tbody tr").filter(has=page.locator("td:nth-child(2)"))
    page.wait_for_function(
        "expected => document.querySelectorAll('table tbody tr td:nth-child(2)').length >= expected",
        arg=rows_before + 1,
        timeout=nsm_env.timeout("assert"),
    )
    rows_after = data_rows.count()
    nsm_env.check(
        rows_after > rows_before,
        f"{section_key}: more rendered rows than the {rows_before} shown at page size 10",
        rows_after,
        page,
    )

    _set_page_size(r"Show 10")  # restore the default for whatever runs next


def _assert_filter_narrows_and_clears(page: Page, section_key: str) -> None:
    """A column filter actually filters: typing a VIN into the VIN filter narrows the
    result total, and Clear Filters restores it. The VIN is used only as filter input —
    its value is never asserted."""
    before = _results_range(page)
    nsm_env.check(
        bool(before), f"{section_key}: a results summary on the listing", before, page
    )
    # ENVIRONMENT-RELATIVE: narrowing can only be observed when there is more than one
    # record to narrow away from.
    _require_rows(page, 2, "a filter narrowing the result set")
    term = page.locator("table tbody td.mat-column-vin").first.inner_text().strip()

    # The filter row may already be open: an earlier check toggles it on and the SPA
    # remembers that per section, in which case the control reads "Clear Filters" and
    # no "Show Filters" button exists. Only open it when it's actually hidden.
    vin_header = page.get_by_role("columnheader", name="VIN").first
    if vin_header.get_by_role("textbox").count() == 0:
        _wait_for_no_loader(page)
        page.get_by_role("button", name=re.compile(r"Show Filters", re.I)).first.click()
        _settle(page, 1000)

    vin_filter = vin_header.get_by_role("textbox").first
    vin_filter.fill(term)
    vin_filter.press("Enter")
    _wait_for_no_loader(page)
    _settle(page, 2500)

    filtered = _results_range(page)
    # STRICT everywhere: filtering by one VIN must narrow a multi-row listing.
    nsm_env.check(
        bool(filtered) and filtered[2] < before[2],
        f"{section_key}: a total below {before[2]} after filtering by a single VIN",
        filtered[2] if filtered else None,
        page,
    )

    _wait_for_no_loader(page)
    page.get_by_role("button", name=re.compile(r"Clear Filters", re.I)).first.click()
    _wait_for_no_loader(page)
    _settle(page, 2500)
    restored = _results_range(page)
    # STRICT everywhere: clearing must restore exactly the pre-filter total, whatever
    # that total happens to be in this environment.
    nsm_env.check(
        bool(restored) and restored[2] == before[2],
        f"{section_key}: Clear Filters to restore the total to {before[2]}",
        restored[2] if restored else None,
        page,
    )


def _click_tab(page: Page, tab: str) -> None:
    """Click a status tab (already on the section) and let its listing re-query.

    A nav/sidebar overlay can briefly intercept the click, so retry once.
    """
    tab_loc = page.get_by_role("tab", name=tab, exact=True).first
    tab_loc.wait_for(state="visible", timeout=nsm_env.timeout("action"))
    _wait_for_no_loader(page)
    try:
        tab_loc.click(timeout=nsm_env.timeout("action"))
    except Exception:
        _settle(page, 1000)
        _wait_for_no_loader(page)
        tab_loc.click(timeout=nsm_env.timeout("action"))
    # The tab re-queries its listing server-side behind the same overlay _wait_for_no_loader
    # already watches for elsewhere — wait for it to clear instead of guessing a fixed delay.
    _wait_for_no_loader(page)


def _assert_show_filters(page: Page, section_key: str) -> None:
    """In-place 'Show Filters' check: the toggle injects a filter control into every
    column header (VIN textbox, Date Submitted date pickers) plus a Clear Filters
    button. Assumes filters currently hidden (the caller hasn't toggled them)."""
    vin_header = page.get_by_role("columnheader", name="VIN").first
    vin_header.wait_for(state="visible", timeout=nsm_env.timeout("assert"))
    show_btn = page.get_by_role("button", name=re.compile(r"Show Filters", re.I)).first
    expect(show_btn).to_be_visible(timeout=nsm_env.timeout("action"))
    nsm_env.check(
        vin_header.get_by_role("textbox").count() == 0,
        f"{section_key}: no column filters before 'Show Filters' is clicked",
        f"{vin_header.get_by_role('textbox').count()} filter input(s) already present",
        page,
    )

    _wait_for_no_loader(page)
    show_btn.click()
    _settle(page, 1000)
    expect(vin_header.get_by_role("textbox").first).to_be_visible(timeout=nsm_env.timeout("action"))

    # Date Submitted is a RANGE filter, not a single field: two date inputs plus the
    # two calendar toggles that drive them. (The toolbar's 'Date Picker' button is a
    # filter-mode toggle, not a calendar opener — clicking it renders the filter row
    # and opens no overlay, verified live.)
    date_header = page.get_by_role("columnheader", name="Date Submitted").first
    expect(date_header.get_by_placeholder(re.compile(r"Start Date", re.I)).first).to_be_visible()
    expect(date_header.get_by_placeholder(re.compile(r"End Date", re.I)).first).to_be_visible()
    toggles = date_header.locator("mat-datepicker-toggle, .mat-datepicker-toggle")
    nsm_env.check(
        toggles.count() >= 2,
        f"{section_key}: 2 calendar toggles on the Date Submitted range filter",
        toggles.count(),
        page,
    )
    expect(page.get_by_role("button", name=re.compile(r"Clear Filters", re.I)).first).to_be_visible()


def _assert_vin_sort(page: Page) -> None:
    """In-place VIN sort check: the column exposes asc + desc sort controls and the
    listing re-renders after each. No assertion on the actual order (data changes)."""
    _wait_for_data_rows(page)
    vin_header = page.get_by_role("columnheader", name="VIN").first
    asc_btn = vin_header.get_by_role("button", name=re.compile(r"sortAsc", re.I)).first
    desc_btn = vin_header.get_by_role("button", name=re.compile(r"sortDesc", re.I)).first
    expect(asc_btn).to_be_visible(timeout=nsm_env.timeout("action"))
    expect(desc_btn).to_be_visible()
    _wait_for_no_loader(page)
    asc_btn.click()
    _wait_for_data_rows(page)
    _wait_for_no_loader(page)
    desc_btn.click()
    _wait_for_data_rows(page)


def _check_lt26x_section(page: Page, section_key: str) -> None:
    """Full LT-26x section check in ONE visit, entered via the LEFT-NAV link (which
    also proves the side navigation works). In order, without re-navigating or using
    direct URLs: heading + action buttons; every status tab clicked in turn with its
    columns + pagination; Show Filters; and the VIN sort. All read-only, general-UI.
    """
    spec = SECTION_SPECS[section_key]
    _open_section(page, spec)  # clicks the left-nav link, lands on the default tab

    expect(page.get_by_role("heading", name=re.compile(spec["heading"], re.I)).first).to_be_visible(
        timeout=nsm_env.timeout("assert")
    )
    for action in spec.get("actions", []):
        expect(
            page.get_by_role("button", name=re.compile(re.escape(action), re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))

    # Every status tab: the default (spec["columns"]) then the rest (LT26X_TAB_COLUMNS).
    columns_by_tab = {spec["tabs"][0]: spec["columns"], **LT26X_TAB_COLUMNS[section_key]}
    for tab in spec["tabs"]:
        _click_tab(page, tab)
        for col in columns_by_tab[tab]:
            expect(page.get_by_role("columnheader", name=col).first).to_be_visible(timeout=nsm_env.timeout("action"))
        _assert_listing_rows_and_pagination(page, f"{section_key}/{tab}")

    # Filters were never toggled above, so they're still hidden. The loop ends on the
    # 'All' tab, which is populated for every section — good for the sort check too.
    _assert_show_filters(page, section_key)
    _assert_vin_sort(page)


def _assert_listing_present(page: Page, label: str) -> None:
    """A results summary or a no-records state renders — i.e. the tab's listing loaded.

    Lighter than `_assert_listing_rows_and_pagination`: it skips the Next/Prev/PageSize
    controls, which small lists (e.g. the 4-row DMV Roles tab) may not render.
    """
    page.wait_for_function(
        r"() => /\d[\d,]*\s+results/i.test(document.body.innerText)"
        r" || /No records/i.test(document.body.innerText)",
        timeout=nsm_env.timeout("assert"),
    )


def _check_tabbed_section(page: Page, section_key: str) -> None:
    """One-visit check (via left-nav click) for a two-tab admin section: heading,
    action buttons, then EVERY tab clicked in turn with its own columns. The main
    (default) tab also gets the full pagination-controls check; the others just
    confirm their listing loaded. All read-only, general-UI."""
    spec = SECTION_SPECS[section_key]
    _open_section(page, spec)

    if spec.get("heading"):
        expect(page.get_by_role("heading", name=re.compile(spec["heading"], re.I)).first).to_be_visible(
            timeout=nsm_env.timeout("assert")
        )
    for action in spec.get("actions", []):
        expect(
            page.get_by_role("button", name=re.compile(re.escape(action), re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))

    columns_by_tab = {spec["tabs"][0]: spec["columns"], **SECTION_OTHER_TAB_COLUMNS[section_key]}
    for i, tab in enumerate(spec["tabs"]):
        _click_tab(page, tab)
        for col in columns_by_tab[tab]:
            # Anchor at the start so e.g. "Name" doesn't also match "Facility Name".
            # Escape any '/' (e.g. "Business/Individual Name") — a bare '/' would break
            # the JS regex delimiter Playwright serializes the pattern into.
            pattern = r"^\s*" + re.escape(col).replace("/", r"\/")
            expect(
                page.get_by_role("columnheader", name=re.compile(pattern, re.I)).first
            ).to_be_visible(timeout=nsm_env.timeout("action"))
        # Reports/Configuration aren't paginated listings (no 'N results' summary), so
        # their per-tab check is the columns above and nothing more.
        if spec.get("listing"):
            if i == 0:
                _assert_listing_rows_and_pagination(page, f"{section_key}/{tab}")
            else:
                _assert_listing_present(page, f"{section_key}/{tab}")


def _check_record_detail(page: Page, section_key: str) -> None:
    """Open the first openable record from a section's 'All' tab and assert its detail
    view: the /details URL, the form heading, its always-present sub-sections, and the
    Serial Number/VIN field.

    Two things learned the hard way and encoded here:
      * The VIN is NOT an <a> — it's a `span.table-link` inside the VIN cell. Rows that
        can't be opened (e.g. drafts on 'All') simply have no such span, so this selector
        both clicks the real control and skips them.
      * A nav click onto the route we're already on is a no-op, so any stale
        tab/filter/sort state on the SAME section would otherwise persist — but the
        explicit `_click_tab(page, "All")` right below always resets the tab regardless,
        so no separate "bounce to Messages/Home" is needed first. `_open_section` still
        falls back to `_ensure_dashboard` on its own if the left nav isn't visible (e.g.
        arriving from a record-detail view).

    READ-ONLY: nothing that mutates the record is clicked.
    """
    spec = RECORD_DETAIL_SPECS[section_key]
    _open_section(page, SECTION_SPECS[section_key])
    _click_tab(page, "All")  # always populated, for every LT-26x section
    _wait_for_data_rows(page)

    vin_link = page.locator("table tbody td.mat-column-vin span.table-link").first
    vin_link.wait_for(state="visible", timeout=nsm_env.timeout("assert"))
    _wait_for_no_loader(page)
    vin_link.click()
    _wait_for_no_loader(page)

    expect(page).to_have_url(re.compile(spec["url"], re.I), timeout=nsm_env.timeout("data"))
    expect(
        page.get_by_role("heading", name=re.compile(spec["heading"], re.I)).first
    ).to_be_visible(timeout=nsm_env.timeout("assert"))
    for label in spec["sections"]:
        expect(page.get_by_text(label, exact=False).first).to_be_visible(timeout=nsm_env.timeout("action"))
    expect(page.get_by_text(re.compile(r"Serial Number", re.I)).first).to_be_visible()


# ── Fixtures ─────────────────────────────────────────────────────────────────
#
# Phase 14 is parametrised over PAGINATED_SECTIONS with @pytest.mark.parametrize
# directly on the test (see below), NOT a `params=` fixture. A params fixture made
# pytest batch the per-section instances and float all but the first to the end of
# the collection — past TestE2E063Logout, so `test_phase14_listing_behaviour[...]`
# cases ended up scheduled after the logout killed the session. parametrize keeps
# them in place. It still doesn't touch the class-scoped `dash_page`.

@pytest.fixture(scope="class")
def dash_page(staff_context: BrowserContext) -> Page:
    """The shared tab for the whole class, already signed in.

    `staff_context` (tests/conftest.py) opens with the stored session for the
    active environment (auth/<qa|stage>/staff-portal.json, picked via NSM_ENV) —
    there's no SSO login flow to drive here, just land on the dashboard route.
    """
    page = staff_context.new_page()
    page.goto(_staff_dashboard_url(), timeout=nsm_env.timeout("login"), wait_until="domcontentloaded")
    _wait_for_dashboard_ready(page)
    yield page
    page.close()


# ── Phase 16 helpers: the LT-262 Fee edit dialog ────────────────────────────────
# Only phase 16 writes. Kept out of the class so the read-only phases stay visibly
# free of any mutation helper. Live-confirmed shape of Configuration > "LT-262 Fee":
#   * exactly one data row: Fee Type | Fee Amount ($N.NN) | Effective Date | Edit | View History
#   * "Edit" opens a mat-dialog with three REQUIRED fields — Fee Amount (keeps the
#     leading "$"), Effective Date, Remarks — plus Save / Cancel.
#   * The Effective Date field rejects every typed format ("Invalid date format" on
#     blur); only a calendar pick registers, and TODAY is disabled (the date must be
#     in the future), so the earliest selectable day is tomorrow.
#   * The row shows the LATEST configured fee immediately after Save (not the
#     time-resolved active one), so the round trip is verifiable straight off the row.

def _lt262_fee_row_cells(page: Page) -> tuple[str, str]:
    """(Fee Amount, Effective Date) text of the single LT-262 Fee row."""
    row = page.locator("table tbody tr", has_text="LT-262").first
    expect(row).to_be_visible(timeout=nsm_env.timeout("assert"))
    return (row.locator("td").nth(1).inner_text().strip(),
            row.locator("td").nth(2).inner_text().strip())


def _lt262_fee_edit_save(page: Page, amount: str, remarks: str) -> None:
    """Open Edit, set amount + earliest selectable (future) effective date +
    remarks, then Save. Raises if the dialog stays open (validation blocked)."""
    page.get_by_role("button", name=re.compile(r"^\s*Edit\s*$", re.I)).first.click()
    dlg = page.locator("mat-dialog-container").first
    expect(dlg).to_be_visible(timeout=nsm_env.timeout("assert"))
    _settle(page, 600)

    dlg.locator("textarea").first.fill(remarks)
    dlg.get_by_label(re.compile(r"Fee Amount", re.I)).first.fill(amount)

    dlg.locator('mat-datepicker-toggle button, button[aria-label*="calendar" i]').first.click()
    cal = page.locator("mat-calendar")
    cal.wait_for(state="visible", timeout=nsm_env.timeout("action"))
    tmr = dt.date.today() + dt.timedelta(days=1)
    # platform-independent Material aria-label, e.g. "September 2, 2026" (no zero-pad)
    label = f"{tmr.strftime('%B')} {tmr.day}, {tmr.year}"
    cell = cal.locator(f'button.mat-calendar-body-cell[aria-label="{label}"]')
    if not cell.count():  # month rollover — target day is in next month
        cal.locator('button.mat-calendar-next-button, button[aria-label*="Next" i]').first.click()
        _settle(page, 400)
    cell.first.click()
    _settle(page, 400)

    dlg.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first.click()
    _settle(page, 1500)

    leftover = page.locator("mat-dialog-container").first
    if leftover.count() and leftover.is_visible():
        msg = re.sub(r"\s+", " ", leftover.inner_text()).strip()
        try:
            leftover.get_by_role("button", name=re.compile(r"^\s*Cancel\s*$", re.I)).first.click()
        except Exception:
            pass
        raise AssertionError(f"{nsm_env.describe(page)}: LT-262 Fee Save was blocked — {msg[:200]}")


# ── Phases 18/19 helpers: the top-right account popover ─────────────────────────
# The "<name> ▾" account button is `div.username button.expertly-link-component.dropdown`.
# It's a custom exp-button that SWALLOWS synthetic element clicks — only a real
# mouse click on its caret (its right edge) opens the popover. The button label is
# the signed-in account's display name, which differs per environment, so this
# anchors on the button's bounding box, never its text. The popover
# (`.exp-popover-panel`) holds exactly two items: "My Profile" and "Log Out".

def _open_account_popover(page: Page):
    trigger = page.locator("div.username button.expertly-link-component.dropdown").first
    expect(trigger).to_be_visible(timeout=nsm_env.timeout("assert"))
    pop = page.locator(".exp-popover-panel").filter(
        has_text=re.compile(r"My Profile|Log ?Out", re.I)
    ).first
    for _ in range(4):
        if pop.count() and pop.is_visible():
            break
        box = trigger.bounding_box()
        page.mouse.click(box["x"] + box["width"] - 6, box["y"] + box["height"] / 2)
        page.wait_for_timeout(700)
    expect(pop).to_be_visible(timeout=nsm_env.timeout("action"))
    _settle(page, 300)
    return pop


_SAVE_STAFF_AUTH = Path(__file__).resolve().parent.parent / "scripts" / "save_staff_auth.py"


def _remint_staff_auth() -> None:
    """Re-create auth/<env>/staff-portal.json after phase 19's logout invalidates
    it server-side. NEVER raises — a failure here must not mask the logout
    assertions; it only means the next run needs `python scripts/save_staff_auth.py`
    run by hand first (a plain `pytest` re-run does no auth refresh of its own)."""
    try:
        subprocess.run(
            [sys.executable, str(_SAVE_STAFF_AUTH)],
            cwd=str(_SAVE_STAFF_AUTH.parent.parent),
            env={**os.environ, "CI": "true"},  # headless; NSM_ENV is already inherited
            capture_output=True, timeout=180, check=False,
        )
    except Exception:
        pass


class TestE2E063StaffPortalAssertions:
    """Staff Portal UI assertions — runs against QA or STAGE via `--env`/NSM_ENV.

    Uses the shared, already-authenticated `staff_context` fixture (see
    tests/conftest.py); there is no in-suite login flow.
    """

    # ── Phase 3: LT-260 Listing ──────────────────────────────────────────────────

    def test_phase3_lt260(self, dash_page: Page):
        """LT-260 in one visit (via the left nav): heading, actions, every status tab
        (columns + pagination), Show Filters, and VIN sort."""
        _check_lt26x_section(dash_page, "LT-260")

    def test_phase3_lt260_record_views(self, dash_page: Page):
        """ONE visit to the first LT-260 record, covering every read-only view on it:
        the detail form, the breadcrumbs, and the correspondence log.

        CONSOLIDATED — was 3 tests costing 10 navigations. Each separately bounced to
        the dashboard, re-entered LT-260 via the nav and re-opened the SAME record
        before asserting. Nothing about the record changes between these checks, so
        the re-entry was pure waste. Every assertion is preserved, only relocated.
        """
        page = dash_page
        _check_record_detail(page, "LT-260")  # navigates once, asserts the detail form

        # --- breadcrumbs: same page, no navigation ---
        # Structural: the crumbs name the FORM, not the record, so this is strict on
        # every environment.
        expect(page).to_have_url(
            re.compile(r"/LT-260/[^/]+/details", re.I), timeout=nsm_env.timeout("data")
        )
        expect(
            page.get_by_text(re.compile(r"LT-260 Details", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("assert"))

        # --- correspondence log: opened in place on the same record ---
        # The control is a `span.span-link` (the same span-with-a-click-handler pattern
        # as the listing's `span.table-link`) — NOT a button or link, so get_by_role
        # finds nothing.
        # READ-ONLY: 'Link to Download' is asserted present but never clicked, and the
        # record's Close File / Reject / Edit actions are never touched.
        link = page.locator("span.span-link").filter(
            has_text=re.compile(r"View Correspondence", re.I)
        ).first
        expect(link).to_be_visible(timeout=nsm_env.timeout("assert"))
        _wait_for_no_loader(page)
        link.click()
        _wait_for_no_loader(page)
        _settle(page, 1500)

        for col in ("Correspondence", "Date Issued", "Recipient Name", "Link to Download"):
            expect(
                page.get_by_role("columnheader", name=re.compile(re.escape(col), re.I)).first
            ).to_be_visible(timeout=nsm_env.timeout("action"))

        # The correspondence view covers the left nav, so a nav click cannot get us out
        # of here — return to the dashboard by URL for whatever runs next.
        _ensure_dashboard(page)

    def test_phase3_lt260_listing_behaviour(self, dash_page: Page):
        """ONE visit to the LT-260 listing, covering every interactive listing
        behaviour: sortable columns, sorting a non-VIN column, pagination, page size
        and filtering.

        CONSOLIDATED — was 5 tests costing 10 navigations, each bouncing to the
        dashboard and re-entering LT-260 first. Every assertion is preserved verbatim;
        only the navigation between them is removed.

        ORDER IS DELIBERATE: pure inspection first, then the mutating checks arranged
        so each restores what it changed — pagination returns to page 1, the page size
        is restored to 'Show 10', and the filter is cleared. Sorting is left applied on
        purpose: it changes only row ORDER, which nothing here asserts.
        """
        page = dash_page
        _open_section(page, SECTION_SPECS["LT-260"])
        _wait_for_data_rows(page)

        _run_same_page_checks(page, "LT-260", [
            ("every column sortable", lambda: _assert_all_columns_sortable(page, "LT-260")),
            ("non-VIN column sort",   lambda: _assert_non_vin_sort(page, "LT-260")),
            ("pagination advances",   lambda: _assert_pagination_advances(page, "LT-260")),
            ("page size widens",      lambda: _assert_page_size_widens(page, "LT-260")),
            ("filter narrows/clears", lambda: _assert_filter_narrows_and_clears(page, "LT-260")),
        ])

    # ── Phase 4: LT-261 (Sheriff Sale/DWI) ───────────────────────────────────────

    def test_phase4_lt261(self, dash_page: Page):
        """LT-261 in one visit: heading, actions, every status tab, Show Filters, sort."""
        _check_lt26x_section(dash_page, "LT-261")

    def test_phase4_lt261_record_detail(self, dash_page: Page):
        """Open a LT-261 record and assert its detail view (read-only)."""
        _check_record_detail(dash_page, "LT-261")

    # ── Phase 5: LT-262 (Notice of Intent to Sell) ───────────────────────────────

    def test_phase5_lt262(self, dash_page: Page):
        """LT-262 in one visit: heading, actions, its 9 status tabs, Show Filters, sort."""
        _check_lt26x_section(dash_page, "LT-262")

    def test_phase5_lt262_record_detail(self, dash_page: Page):
        """Open a LT-262 record and assert its detail view (read-only)."""
        _check_record_detail(dash_page, "LT-262")

    def test_phase5_lt262_workflow_steps(self, dash_page: Page):
        """An LT-262 record detail exposes the case's review workflow steps and the
        'LT-262 Details' breadcrumb. Steps are asserted present only — never clicked,
        since working a step mutates the case."""
        page = dash_page
        _open_first_record(page, "LT-262")
        expect(page).to_have_url(re.compile(r"/details", re.I), timeout=nsm_env.timeout("data"))
        expect(page.get_by_text(re.compile(r"LT-262 Details", re.I)).first).to_be_visible(timeout=nsm_env.timeout("assert"))
        for step in ("Review LT-260", "REVIEW LT-262", "REVIEW SUPPORTING DOCUMENTS",
                     "CHECK DCI AND NMVTIS", "TRACK LT-264", "REVIEW COURT HEARINGS",
                     "REVIEW LT-263"):
            expect(page.get_by_text(step, exact=False).first).to_be_visible(timeout=nsm_env.timeout("action"))

    # ── Phase 6: LT-262A (Notice of Intent to Sell) ──────────────────────────────

    def test_phase6_lt262a(self, dash_page: Page):
        """LT-262A in one visit: heading, actions, every status tab, Show Filters, sort."""
        _check_lt26x_section(dash_page, "LT-262A")

    def test_phase6_lt262a_record_detail(self, dash_page: Page):
        """Open a LT-262A record and assert its detail view (read-only)."""
        _check_record_detail(dash_page, "LT-262A")

    # ── Phase 7: LT-263 (Notice of Sale) ─────────────────────────────────────────

    def test_phase7_lt263(self, dash_page: Page):
        """LT-263 in one visit: heading, actions, every status tab, Show Filters, sort."""
        _check_lt26x_section(dash_page, "LT-263")

    def test_phase7_lt263_record_detail(self, dash_page: Page):
        """Open a LT-263 record and assert its detail view (read-only)."""
        _check_record_detail(dash_page, "LT-263")

    # ── Phase 8: Sold ────────────────────────────────────────────────────────────

    def test_phase8_sold_section(self, dash_page: Page):
        """Sold listing: URL, columns, Download Options, pagination (no tabs/heading)."""
        _check_section(dash_page, SECTION_SPECS["Sold"])

    def test_phase8_sold_record_detail(self, dash_page: Page):
        """A Sold row opens the underlying record's detail view.

        Sold is a CROSS-FORM listing: a sold vehicle keeps whichever LT-26x form it came
        in on, so which form row 1 opens is data, not structure (PROD served an LT-263,
        UAT serves LT-261s). Even within one form the parenthesised subtitle is
        per-record — "LT-261 (Notice from DWI)" vs "LT-261 (Notice from Sheriff of
        Execution Stop: E-Stop)". So assert the SHAPE of the detail view and match the
        form prefix only, the same way RECORD_DETAIL_SPECS["LT-261"] does.

        The 'Sold' breadcrumb root is deliberately not asserted: the left nav always
        renders a "Sold" item, so matching that text proves nothing.
        """
        page = dash_page
        _open_first_record(page, "Sold")

        expect(page).to_have_url(
            re.compile(r"/LT-26[0-9A-Z]*/[^/]+/details", re.I), timeout=nsm_env.timeout("data")
        )
        expect(
            page.get_by_text(re.compile(r"LT-26[0-9A-Z]* Details", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("assert"))

        heading = page.get_by_role(
            "heading", name=re.compile(r"^LT-26[0-9A-Z]* \(", re.I)
        ).first
        expect(heading).to_be_visible(timeout=nsm_env.timeout("assert"))

        # Which form this row belongs to is environment DATA (PROD's row 1 is an
        # LT-263 rendered on the LT-262 route with ?tab=5; UAT's are LT-261s), and
        # the sub-section labels differ per form — LT-261 has "Vehicle Details",
        # LT-262/263 have "Description of Vehicle" / "Lien Information". So read the
        # form off the heading and assert THAT form's full known section list.
        # Nothing is weakened: every section the form is known to render is still
        # required; only the choice of which spec applies follows the data.
        heading_text = heading.inner_text().strip()
        match = re.match(r"(LT-26[0-9A-Z]*)\s*\(", heading_text, re.I)
        nsm_env.check(
            bool(match),
            "the detail heading to start with an LT-26x form identifier",
            heading_text,
            page,
        )
        form = match.group(1).upper()
        spec = RECORD_DETAIL_SPECS.get(form)
        nsm_env.check(
            spec is not None,
            f"a known RECORD_DETAIL_SPECS entry for the opened form {form}",
            sorted(RECORD_DETAIL_SPECS),
            page,
        )
        for label in spec["sections"]:
            expect(
                page.get_by_text(label, exact=False).first
            ).to_be_visible(timeout=nsm_env.timeout("action"))
        expect(page.get_by_text(re.compile(r"Serial Number", re.I)).first).to_be_visible()

    # ── Phase 9: Payments ────────────────────────────────────────────────────────

    def test_phase9_payments_section(self, dash_page: Page):
        """Payments in one visit: heading, Record Mailed Payment, and BOTH tabs
        (Payment Transaction History + Payments Missing Forms) with their columns."""
        _check_tabbed_section(dash_page, "Payments")

    def test_phase9_payments_record_detail(self, dash_page: Page):
        """A payment row opens its Payment Details view: the payment fields plus the
        linked LT-262 vehicle details."""
        page = dash_page
        _open_first_record(page, "Payments")
        expect(page).to_have_url(re.compile(r"/payments/", re.I), timeout=nsm_env.timeout("data"))
        expect(
            page.get_by_role("heading", name=re.compile(r"Payment Details", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("assert"))
        for label in ("VIN", "File Number", "Payment Type", "Payment Method", "Amount",
                      "PayIt Transaction ID", "Business/Individual Name"):
            expect(page.get_by_text(label, exact=False).first).to_be_visible(timeout=nsm_env.timeout("action"))

    # ── Phase 10: Reports ────────────────────────────────────────────────────────

    def test_phase10_reports_section(self, dash_page: Page):
        """Reports in one visit: heading, Recent Reports, and BOTH tabs
        (VERIFI Reports + System Generated Reports) with their report-list columns."""
        _check_tabbed_section(dash_page, "Reports")

    def test_phase10_reports_recent_panel(self, dash_page: Page):
        """The Reports page surfaces its 'Recent Reports' panel, and that panel is a
        working Hide/Unhide toggle. Collapsing a panel is view state, not data — nothing
        is mutated, and the panel is restored to its default expanded state afterwards.

        Row COUNT is deliberately NOT asserted. Reports are permission-gated per account
        and the two tabs (VERIFI Reports / System Generated Reports) can legitimately
        render zero rows, so an earlier `rows >= 1` check passed and failed on
        back-to-back runs of the same environment. The listing's columns are asserted
        here instead — they render whether or not the account can see any reports.
        """
        page = dash_page
        _open_section(page, SECTION_SPECS["Reports"])

        panel = page.get_by_role("button", name=re.compile(r"Recent Reports", re.I)).first
        expect(panel).to_be_visible(timeout=nsm_env.timeout("assert"))

        # Ships expanded, so the control offers to Hide.
        expect(page.get_by_text(re.compile(r"^Hide$", re.I)).first).to_be_visible(timeout=nsm_env.timeout("action"))

        _wait_for_no_loader(page)
        panel.click()
        _settle(page, 1200)
        expect(page.get_by_text(re.compile(r"^Unhide$", re.I)).first).to_be_visible(timeout=nsm_env.timeout("action"))

        # Restore the expanded default so this can't leak into a later test.
        _wait_for_no_loader(page)
        panel.click()
        _settle(page, 1200)
        expect(page.get_by_text(re.compile(r"^Hide$", re.I)).first).to_be_visible(timeout=nsm_env.timeout("action"))

        # Listing columns render on both tabs, regardless of row count.
        for col in ("REPORT NAME", "CREATED DATE", "LAST UPDATED DATE"):
            expect(
                page.get_by_role("columnheader", name=re.compile(col, re.I)).first
            ).to_be_visible(timeout=nsm_env.timeout("action"))

    # ── Phase 11: Configuration ──────────────────────────────────────────────────

    def test_phase11_configuration_section(self, dash_page: Page):
        """Configuration in one visit: heading, View History, and BOTH tabs — LT-262 Fee
        (Fee Type/Amount/Effective Date) and Letterhead (Letterhead Field/Value/Effective
        Date), which are different tables."""
        _check_tabbed_section(dash_page, "Configuration")

    def test_phase11_configuration_view_history(self, dash_page: Page):
        """'View History' opens the read-only Fee History dialog with its audit columns.
        The dialog is dismissed afterwards so it can't leak into later tests."""
        page = dash_page
        _open_section(page, SECTION_SPECS["Configuration"])
        # Explicit, not assumed: re-clicking the Configuration nav link is a no-op when
        # we're already on that route, so without this the tab left active by whichever
        # test ran before (e.g. test_phase11_configuration_section ends on Letterhead)
        # would persist and open the WRONG history dialog.
        _click_tab(page, "LT-262 Fee")

        _wait_for_no_loader(page)
        page.get_by_role("button", name=re.compile(r"View History", re.I)).first.click()
        _settle(page, 1500)

        dialog = page.locator(
            "mat-dialog-container, [role='dialog'], .cdk-dialog-container"
        ).first
        expect(dialog).to_be_visible(timeout=nsm_env.timeout("assert"))
        expect(dialog.get_by_text(re.compile(r"Fee History", re.I)).first).to_be_visible()
        for col in ("Item Changed", "Previous Value", "Current Value", "Updated By",
                    "Updated On", "Remarks"):
            expect(dialog.get_by_role("columnheader", name=col).first).to_be_visible(timeout=nsm_env.timeout("action"))

        page.keyboard.press("Escape")  # don't leave the modal open for the next test
        _settle(page, 800)

    # ── Phase 12: User Management ────────────────────────────────────────────────

    def test_phase12_user_management_section(self, dash_page: Page):
        """User Management in one visit: heading, Add DMV User, and BOTH tabs
        (DMV Users + DMV Roles) with their columns."""
        _check_tabbed_section(dash_page, "User Management")

    def test_phase12_user_management_record_detail(self, dash_page: Page):
        """A DMV user row opens its User Details view: the user fields plus the User Role
        and User Status sections. The per-section Edit controls are never clicked."""
        page = dash_page
        _open_first_record(page, "User Management")
        expect(page).to_have_url(re.compile(r"/user-management/[^/]+/details", re.I), timeout=nsm_env.timeout("data"))
        for heading in ("User Details", "User Role", "User Status"):
            expect(
                page.get_by_role("heading", name=re.compile(re.escape(heading), re.I)).first
            ).to_be_visible(timeout=nsm_env.timeout("assert"))
        for label in ("First Name", "Last Name", "Email", "Business Unit", "Role"):
            expect(page.get_by_text(label, exact=False).first).to_be_visible(timeout=nsm_env.timeout("action"))

    # ── Phase 13: Facility Management ─────────────────────────────────────────────

    def test_phase13_facility_management_section(self, dash_page: Page):
        """Facility Management in one visit: heading, and BOTH tabs
        (Facilities/Individuals + Facility Users) with their columns."""
        _check_tabbed_section(dash_page, "Facility Management")

    # ── Phase 14: listing behaviour across EVERY paginated section ────────────────
    #
    # Paging and sorting are driven by ONE shared table component, but until now they
    # were only ever exercised on LT-260 — a regression in that component would have
    # gone unnoticed on the other seven listings. These run on each section's
    # data-bearing tab (see `_open_section_data_tab`: a default tab can legitimately
    # be empty, e.g. LT-261 'To Process' on PROD).

    @pytest.mark.parametrize("listing_section", PAGINATED_SECTIONS)
    def test_phase14_listing_behaviour(self, dash_page: Page, listing_section: str):
        """ONE visit per section covering both shared-component behaviours.

        CONSOLIDATED — was 2 tests costing 6 navigations per section (42 across the
        seven sections). Pagination and sorting were asserted in separate tests that
        each re-entered the same section and re-selected the same data tab, with
        nothing changing in between. Both assertions are preserved.
        """
        _open_section_data_tab(dash_page, listing_section)
        _run_same_page_checks(dash_page, listing_section, [
            ("every column sortable",
             lambda: _assert_all_columns_sortable(dash_page, listing_section)),
            ("pagination advances",
             lambda: _assert_pagination_advances(dash_page, listing_section)),
        ])

    # ── Phase 15: remaining read-only feature gaps ────────────────────────────────

    def test_phase15_global_search_no_results(self, dash_page: Page):
        """Global Search handles a term that matches nothing.

        Only the happy path was covered before. A VIN that cannot exist must still
        land on the Search Results page and report an empty result set rather than
        erroring or rendering stale rows.
        """
        page = dash_page
        _ensure_dashboard(page)

        box = page.get_by_placeholder(re.compile(r"Search using VIN", re.I)).first
        expect(box).to_be_visible(timeout=nsm_env.timeout("assert"))
        box.fill(_NO_MATCH_TERM)
        page.get_by_role("button", name=re.compile(r"^\s*Search\s*$", re.I)).first.click()
        _wait_for_no_loader(page)
        _settle(page, 2000)

        expect(page).to_have_url(
            re.compile(r"global-search", re.I), timeout=nsm_env.timeout("data")
        )
        expect(
            page.get_by_text(re.compile(r"Search Results", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("assert"))

        expect(
            page.get_by_text(re.compile(rf"Searched:\s*{_NO_MATCH_TERM}", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("assert"))

        # STRICT everywhere: this term cannot match real data on ANY environment, so
        # an empty result set is required rather than merely tolerated. The empty
        # state reads "No results found" here — NOT the "No records" wording the
        # listing pages use (verified live; they are different strings).
        rows = page.locator("table tbody tr").filter(has=page.locator("td:nth-child(2)"))
        nsm_env.check(
            rows.count() == 0,
            f"no result rows for the unmatchable term {_NO_MATCH_TERM!r}",
            f"{rows.count()} row(s)",
            page,
        )
        expect(
            page.get_by_text(re.compile(r"No results found", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("assert"))

        # Every per-form counter must read 0 — the counters are what a user reads to
        # see "nothing matched", and a stale non-zero here would be a real defect.
        body = page.locator("body").inner_text()
        for form in ("LT-260", "LT-261", "LT-262", "LT-263", "Payments", "Facilities"):
            match = re.search(rf"{re.escape(form)}\s*\n\s*(\d+)", body)
            nsm_env.check(
                match is not None and match.group(1) == "0",
                f"the {form} result counter to read 0 for an unmatchable term",
                match.group(1) if match else "(counter not found)",
                page,
            )

    def test_phase15_configuration_letterhead_view_history(self, dash_page: Page):
        """The Letterhead tab has its OWN View History audit dialog.

        Only the LT-262 Fee tab's history was covered before. The dialog is dismissed
        afterwards so it cannot leak into a later test.
        """
        page = dash_page
        _open_section(page, SECTION_SPECS["Configuration"])
        _click_tab(page, "Letterhead")
        _settle(page, 1500)

        _wait_for_no_loader(page)
        page.get_by_role("button", name=re.compile(r"View History", re.I)).first.click()
        _settle(page, 1500)

        dialog = page.locator(
            "mat-dialog-container, [role='dialog'], .cdk-dialog-container"
        ).first
        expect(dialog).to_be_visible(timeout=nsm_env.timeout("assert"))
        # The title is what proves this is the LETTERHEAD history and not the LT-262
        # Fee history already covered by test_phase11 — the two dialogs are otherwise
        # identical, sharing all six audit columns.
        expect(
            dialog.get_by_text(re.compile(r"Letterhead History", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))
        for col in ("Item Changed", "Previous Value", "Current Value", "Updated By",
                    "Updated On", "Remarks"):
            expect(
                dialog.get_by_role("columnheader", name=col).first
            ).to_be_visible(timeout=nsm_env.timeout("action"))

        page.keyboard.press("Escape")  # don't leave the modal open for the next test
        _settle(page, 800)

    # ── Phase 16: Configuration — LT-262 Fee edit + revert (the one write test) ───
    #
    # Phase 11 proves the LT-262 Fee tab RENDERS (row, columns, View History). It
    # can't answer "can staff actually change the fee, and does the change take?"
    # This one does: it edits the amount, confirms the row reflects it, then edits
    # it straight back. Runs LAST in the class so no read-only phase sees the churn.
    #
    # Why this is safe to keep in an otherwise read-only suite:
    #   * QA/STAGE only — `--env` offers no prod target, and there is no prod auth.
    #   * The amount is restored in a `finally`, so a failed assertion after the
    #     first save still triggers a best-effort revert.
    #   * The datepicker disables today, so every change is future-dated; the fee
    #     that live LT-262 payments charge (effective since 2025) is untouched for
    #     the whole run — only the "latest configured" row moves and moves back.
    # Two residues that CANNOT be undone and are accepted:
    #   * the Effective Date ratchets forward (past dates are disabled in the
    #     picker), so it is not asserted back to its pre-test value;
    #   * Fee History gains audit rows for the edit and the revert.

    def test_phase16_configuration_lt262_fee_edit_and_revert(self, dash_page: Page):
        """Edit the LT-262 fee to a sentinel (+$1.00), verify the row shows it,
        revert to the original amount, verify the row is back. Then confirm both
        legs are recorded in Fee History. Restore is `finally`-guarded."""
        page = dash_page
        _open_section(page, SECTION_SPECS["Configuration"])
        _click_tab(page, "LT-262 Fee")
        _settle(page, 1200)

        original_amt, _ = _lt262_fee_row_cells(page)
        nsm_env.check(
            bool(re.fullmatch(r"\$\d+\.\d{2}", original_amt)),
            "the LT-262 Fee row to show a '$N.NN' amount before editing",
            original_amt, page,
        )
        sentinel = f"${float(original_amt.lstrip('$')) + 1:.2f}"  # clearly distinct, still sane

        reverted = False
        try:
            _lt262_fee_edit_save(
                page, sentinel,
                "E2E test_e2e_063 phase16 - temporary change, reverted in the next step",
            )
            _settle(page, 1200)
            changed_amt, _ = _lt262_fee_row_cells(page)
            nsm_env.check(
                changed_amt == sentinel,
                f"the LT-262 Fee row to show the edited amount {sentinel!r} after Save",
                changed_amt, page,
            )

            _lt262_fee_edit_save(
                page, original_amt,
                "E2E test_e2e_063 phase16 - revert to the original fee amount",
            )
            _settle(page, 1200)
            back_amt, _ = _lt262_fee_row_cells(page)
            nsm_env.check(
                back_amt == original_amt,
                f"the LT-262 Fee row restored to the original amount {original_amt!r}",
                back_amt, page,
            )
            reverted = True
        finally:
            if not reverted:
                try:
                    if _lt262_fee_row_cells(page)[0] != original_amt:
                        _lt262_fee_edit_save(
                            page, original_amt,
                            "E2E test_e2e_063 phase16 - failsafe revert after a failed assertion",
                        )
                except Exception:
                    pass  # nothing more we can do from here; the assertion failure is the signal

        # The round trip is audited — both the edit and the revert must show in Fee History.
        page.get_by_role("button", name=re.compile(r"View History", re.I)).first.click()
        _settle(page, 1200)
        dialog = page.locator(
            "mat-dialog-container, [role='dialog'], .cdk-dialog-container"
        ).first
        expect(dialog).to_be_visible(timeout=nsm_env.timeout("assert"))
        expect(dialog.get_by_text(re.compile(r"Fee History", re.I)).first).to_be_visible(
            timeout=nsm_env.timeout("action")
        )
        # The sentinel amount is logged (Current Value of the edit row / Previous Value
        # of the revert row). The history table drops the leading "$" on STAGE but
        # keeps it on QA, so match on the numeric part against the dialog's text.
        sentinel_num = sentinel.lstrip("$")
        expect(dialog.locator("table")).to_be_visible(timeout=nsm_env.timeout("action"))
        hist_text = dialog.inner_text()
        nsm_env.check(
            sentinel_num in hist_text,
            f"the edited fee {sentinel} to be recorded in Fee History",
            hist_text[:300].replace("\n", " "),
            page,
        )

        page.keyboard.press("Escape")  # don't leave the modal open for the next test
        _settle(page, 800)

    # ── Phase 17: User Management — view + the "manage" affordances ──────────────
    #
    # Phase 12 proves the DMV Users listing RENDERS (tabs, columns, Add button) and
    # that a user row opens its read-only detail view. It never touches the manage
    # paths. This does — still read-only: it opens the "Add DMV User" form and
    # asserts its fields, then Cancels without creating anyone, and confirms a user
    # detail page exposes an Edit control (never clicked).

    def test_phase17_dmv_users_view_and_manage(self, dash_page: Page):
        """View: the DMV Users listing + Add DMV User action (phase 12 owns the
        column check). Manage: the Add DMV User form fields + Cancel, and the Edit
        affordance on a user's detail page. No user is created or edited."""
        page = dash_page
        _open_section(page, SECTION_SPECS["User Management"])
        _click_tab(page, "DMV Users")
        _settle(page, 800)

        add = page.get_by_role("button", name=re.compile(r"Add DMV User", re.I)).first
        expect(add).to_be_visible(timeout=nsm_env.timeout("action"))
        add.click()
        expect(page).to_have_url(
            re.compile(r"/user-management/add-user", re.I), timeout=nsm_env.timeout("data")
        )
        _settle(page, 800)

        for field in ("first_name", "last_name", "email"):
            expect(page.locator(f'input[name="{field}"]').first).to_be_visible(
                timeout=nsm_env.timeout("action")
            )
        for label in ("Business Unit", "Role"):
            expect(page.locator(f'mat-select[aria-label*="{label}" i]').first).to_be_visible(
                timeout=nsm_env.timeout("action")
            )
        expect(
            page.get_by_role("button", name=re.compile(r"^\s*Add User\s*$", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))

        # leave WITHOUT creating anyone. Cancel's exact routing isn't the point of
        # this check (and it's been seen to just clear the form in place), so click
        # it and then re-enter the section from the nav regardless.
        page.get_by_role("button", name=re.compile(r"^\s*Cancel\s*$", re.I)).first.click()
        _settle(page, 800)
        _open_section(page, SECTION_SPECS["User Management"])
        _settle(page, 800)

        # a user's detail page carries the manage (Edit) affordance — present, not clicked
        _open_first_record(page, "User Management")
        expect(page).to_have_url(
            re.compile(r"/user-management/[^/]+/details", re.I), timeout=nsm_env.timeout("data")
        )
        expect(
            page.get_by_role("button", name=re.compile(r"^\s*Edit\s*$", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))

    # ── Phase 18: DMV User Profile (the signed-in user's own) ───────────────────
    #
    # Distinct from phase 12's /user-management/<id>/details (an admin viewing some
    # OTHER DMV user). This is the account's OWN profile, reached from the top-right
    # popover. Read-only: the Save button is asserted present, never clicked.

    def test_phase18_dmv_user_profile(self, dash_page: Page):
        """'My Profile' opens the signed-in user's own DMV User profile: the
        /my-profile route, the 'DMV User' + 'User Details' headings, the identity
        fields, and a Save control (not clicked)."""
        page = dash_page
        _ensure_dashboard(page)
        _settle(page, 600)

        pop = _open_account_popover(page)
        pop.get_by_text("My Profile", exact=True).first.click()
        expect(page).to_have_url(
            re.compile(r"/my-profile", re.I), timeout=nsm_env.timeout("data")
        )
        _settle(page, 1000)

        for heading in ("DMV User", "User Details"):
            expect(
                page.get_by_role("heading", name=re.compile(re.escape(heading), re.I)).first
            ).to_be_visible(timeout=nsm_env.timeout("assert"))
        for label in ("First Name", "Last Name", "Email Address", "Role", "Business Unit"):
            expect(page.get_by_text(label, exact=False).first).to_be_visible(
                timeout=nsm_env.timeout("action")
            )
        expect(
            page.get_by_role("button", name=re.compile(r"^\s*Save\s*$", re.I)).first
        ).to_be_visible(timeout=nsm_env.timeout("action"))

    # Phase 19 (DMV User Logout) is deliberately NOT here — see TestE2E063Logout
    # at the end of the file for why it needs its own class.


# ── Phase 19 fixture + class ───────────────────────────────────────────────────

@pytest.fixture(scope="class")
def logout_page(staff_context: BrowserContext) -> Page:
    """A dedicated staff tab for the logout phase.

    Its own `staff_context` instance (class-scoped fixtures are per-class), so the
    first class's session is already torn down by the time this runs. A private
    context would buy nothing anyway — logout kills the session server-side for
    every context (verified: a parallel context bounces to /login too).
    """
    page = staff_context.new_page()
    page.goto(_staff_dashboard_url(), timeout=nsm_env.timeout("login"), wait_until="domcontentloaded")
    _wait_for_dashboard_ready(page)
    yield page
    page.close()


class TestE2E063Logout:
    """Phase 19 — DMV User Logout. A SEPARATE class on purpose, and the last one
    in the file.

    phase 14's `listing_section` is a params fixture, and pytest floats its
    per-section instances to the END of TestE2E063StaffPortalAssertions (see
    `--collect-only`). A logout method *inside* that class would have six
    `test_phase14_listing_behaviour[...]` cases scheduled to run AFTER it against a
    killed session. Here, after that class, collection order guarantees logout runs
    dead last.

    Logout invalidates the stored session server-side, so the finally block
    re-mints auth/<env>/staff-portal.json via scripts/save_staff_auth.py — a plain
    `pytest` re-run does no auth refresh of its own. If that re-mint fails, run
    `python scripts/save_staff_auth.py` by hand before the next run.
    """

    def test_phase19_dmv_user_logout(self, logout_page: Page):
        """'Log Out' (top-right account popover) redirects to the sign-in page and
        kills the session — a subsequent dashboard visit bounces back to /login."""
        page = logout_page
        try:
            _ensure_dashboard(page)
            _settle(page, 600)

            pop = _open_account_popover(page)
            pop.get_by_text(re.compile(r"^\s*Log ?Out\s*$", re.I)).first.click()

            login_url = re.compile(r"/login(\?|/|$)", re.I)
            page.wait_for_url(login_url, timeout=nsm_env.timeout("route"))
            expect(page).to_have_url(login_url)

            # prove the session is really gone: a protected route now bounces to the
            # sign-in page (the auth guard runs a beat after load, so wait for the
            # redirect rather than sampling the URL once).
            page.goto(
                _staff_dashboard_url(),
                timeout=nsm_env.timeout("login"),
                wait_until="domcontentloaded",
            )
            try:
                page.wait_for_url(login_url, timeout=nsm_env.timeout("route"))
            except Exception:
                pass
            _settle(page, 800)
            on_login = bool(re.search(r"/login", page.url, re.I))
            has_signin_form = (
                page.get_by_text(re.compile(r"Log in with|NC DOT/DMV", re.I)).count() > 0
                or page.locator("input#loginId").count() > 0
            )
            nsm_env.check(
                on_login or has_signin_form,
                "a post-logout dashboard visit to land on the sign-in page",
                page.url, page,
            )
        finally:
            _remint_staff_auth()
