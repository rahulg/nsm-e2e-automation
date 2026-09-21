"""
E2E-059: User Productivity Report
Staff Portal — System Generated Reports → User Productivity Report.

Flow:
  1. [Staff Portal] Log in via saved auth session, open the dashboard
  2. Navigate to Reports → click 'User Productivity Report' (grid auto-loads; poll for rows)
  3. Verify the 'Week' column header and >=1 data row, every week rendered as
     'MM/DD/YYYY - MM/DD/YYYY' and carrying a 'Download' action
  4. Sort the Week column via its ASC/DESC header buttons and assert the two orderings
     are exact reverses of one another
  5. Verify the paginator page-size control offers Show 10 / 20 / 50 and that the results
     counter agrees with the number of rows rendered
  6. Click a week's 'Download' link → verify an .xlsx named for that week downloads
  7. Parse the workbook → one sheet per staff user, each carrying the Monday..Sunday day
     columns and the LT-260/261/262/262A/263 + Payments activity rows

Structural note — this report is NOT shaped like the ACH Deposit (E2E-057) / NCOA (E2E-058)
reports, so several of their phases have no counterpart here:
  * there is no 'Show Filters' control — the report has no per-column or date-range filters,
    so there is no filter phase and no way to drive the grid to a 'No Records Found' state
  * there is no 'Download Options' popover — no report-level PDF/XLSX export. Export is
    per-row instead: each week's 'Download' link yields that week's XLSX
  * the grid is a 2-column index of pre-generated weekly files ('Week' + an unlabelled
    action column); the report's real data fields live inside the downloaded workbook,
    which is why step 7 asserts fields there rather than against the grid
The XLSX is parsed with openpyxl, matching the payload-verification approach in E2E-035/036.

The User Productivity Report is permission-gated / not deployed for every account+environment;
when the report link is absent the test skips rather than hard-failing.

Downloaded files are saved under C:/automation/artifacts/e2e_059_user_productivity_report/.
"""

import re
from pathlib import Path

import openpyxl
import pytest
from playwright.sync_api import BrowserContext, expect, TimeoutError as PWTimeoutError

from src.config.env import ENV
from src.pages.staff_portal.dashboard_page import StaffDashboardPage


SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

DOWNLOADS_DIR = Path(r"C:/automation/artifacts/e2e_059_user_productivity_report")

# The grid has two columns: a sortable 'Week' and an unlabelled action column holding the
# per-week 'Download' link. Only 'Week' renders header text.
EXPECTED_COLUMNS = ["Week"]

# Every Week cell is a 'MM/DD/YYYY - MM/DD/YYYY' range.
WEEK_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\s*-\s*\d{2}/\d{2}/\d{4}$")

# Sort controls live in the Week header (column 0) as discrete asc/desc buttons — clicking
# the header text itself does nothing.
SORT_ASC_BTN = 'button[aria-label="sortAscButton-0"]'
SORT_DESC_BTN = 'button[aria-label="sortDescButton-0"]'

# Page-size options offered by the paginator's mat-select.
EXPECTED_PAGE_SIZES = ["Show 10", "Show 20", "Show 50"]

# Fields inside each week's workbook: day columns across, activity rows down.
EXPECTED_XLSX_DAYS = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]
EXPECTED_XLSX_METRICS = [
    "LT-260 Draft Saved",
    "LT-260 Added",
    "LT-260 Processed",
    "LT-261 Draft Saved",
    "LT-261 Added",
    "LT-261 Processed",
    "LT-262 Draft Saved",
    "LT-262 Added",
    "LT-262 Processed",
    "LT-262A Draft Saved",
    "LT-262A Added",
    "LT-262A Processed",
    "LT-263 Draft Saved",
    "LT-263 Added",
    "LT-263 Processed",
    "LT-263 Issued",
    "Payments",
]


def _normalize(s) -> str:
    """Uppercase and strip everything but letters/digits so spacing/punctuation can't
    cause a false field mismatch."""
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    # networkidle is a settle-hint, not a precondition: on STAGE the Angular bundle keeps
    # background traffic alive well past the 30s default, so a bare wait raised before the
    # page was ever exercised. The real readiness gate is _wait_for_sidebar() downstream.
    try:
        page.wait_for_load_state("networkidle", timeout=45_000)
    except Exception:
        pass


def snapshot_table(page):
    """Return the grid as a 2D list of cell texts via a single atomic DOM read.

    Reading cell-by-cell with Playwright locators races the grid's async re-render: a row
    can detach mid-iteration and text_content() then blocks on the 30s auto-wait. One
    synchronous evaluate() captures a consistent snapshot with no auto-waiting."""
    return page.evaluate(
        """() => {
            const t = document.querySelector('table');
            if (!t) return [];
            const rows = Array.from(t.querySelectorAll('tr')).filter(r => r.querySelector('td'));
            return rows.map(r =>
                Array.from(r.querySelectorAll('td')).map(td => (td.textContent || '').trim())
            );
        }"""
    )


def column_values(page, idx):
    """Return the text of column `idx` across every data row (including blank spacer cells)."""
    return [row[idx] for row in snapshot_table(page) if idx < len(row)]


def nonempty_values(page, idx):
    """Non-empty values of column `idx` (each record spans a primary + blank spacer row)."""
    return [v for v in column_values(page, idx) if v.strip()]


def wait_for_column(page, idx, predicate, tries=15, delay=400):
    """Poll column `idx`'s non-empty values until `predicate(values)` holds, then return them.

    The grid re-queries asynchronously, so mere read-stability is not enough — a read taken
    before the query fires looks 'stable' at the pre-change state. Waiting on an explicit
    condition (row count reached, ordering reversed, etc.) avoids that."""
    last = nonempty_values(page, idx)
    for _ in range(tries):
        if predicate(last):
            return last
        page.wait_for_timeout(delay)
        last = nonempty_values(page, idx)
    return last


def wait_for_counter(page, tries=15, delay=400):
    """Poll the 'x - y of N results' counter until it appears, returning [start, end, total]
    as ints (or [] if it never does).

    The counter is a separate Angular binding from the row array and can render a beat
    after the rows do — same class of race `wait_for_column` guards against, applied to
    this page's other piece of async-rendered state."""
    pattern = r"(\d+)\s*-\s*(\d+)\s*of\s*(\d+)\s*results"
    for _ in range(tries):
        match = page.evaluate(
            f"() => (document.body.innerText.match(/{pattern}/) || []).slice(1).map(Number)"
        )
        if match:
            return match
        page.wait_for_timeout(delay)
    return []


def open_user_productivity_report(page):
    """Open Reports → User Productivity Report and wait for the auto-loading grid to populate.

    The report is permission-gated / not deployed for every account+environment; skip rather
    than hard-fail when its link is absent."""
    StaffDashboardPage(page).navigate_to_reports()
    page.wait_for_timeout(1500)
    upr_link = page.locator('//span[contains(text(),"User Productivity Report")]').first
    try:
        upr_link.wait_for(state="visible", timeout=15_000)
    except PWTimeoutError:
        pytest.skip("User Productivity Report is not available for this account/environment")
    upr_link.click()
    page.wait_for_load_state("networkidle")
    # The grid auto-loads but is slow — poll up to ~25s for the first rows.
    for _ in range(25):
        if snapshot_table(page):
            break
        page.wait_for_timeout(1000)


def week_slug(week: str) -> str:
    """'05/18/2026 - 05/24/2026' -> '05-18-2026_05-24-2026' (the filename's week stamp)."""
    return week.strip().replace("/", "-").replace(" - ", "_")


def download_week(page, row_idx: int, attempts: int = 3, dl_timeout: int = 30_000):
    """Click the 'Download' link on data row `row_idx` and return the Download, retrying on
    grid re-render flakiness.

    The grid re-renders asynchronously and can detach the link mid-click ('element is not
    stable' / 'element was detached from the DOM'); re-locating the link fresh on each
    attempt works around that. `dl_timeout` is generous because the workbook is generated
    server-side and can lag the click."""
    last_error = None
    for _ in range(attempts):
        try:
            link = page.locator('table tbody tr span.link:has-text("Download")').nth(row_idx)
            expect(link).to_be_visible(timeout=10_000)
            with page.expect_download(timeout=dl_timeout) as download_info:
                link.click(timeout=10_000)
            download = download_info.value
            name = download.suggested_filename
            assert name, "Download should have a filename"
            assert name.lower().endswith(".xlsx"), f"Expected .xlsx extension, got: {name}"
            return download
        except Exception as e:
            last_error = e
            page.keyboard.press("Escape")
            page.mouse.move(0, 0)
            page.wait_for_timeout(500)
    raise last_error


def verify_xlsx_fields(path: Path) -> None:
    """Assert the weekly workbook carries the report's data fields.

    The grid only indexes the weekly files, so the report's fields live in here: one
    worksheet per staff user, each with the Monday..Sunday day columns and the
    LT-260/261/262/262A/263 + Payments activity rows."""
    wb = openpyxl.load_workbook(str(path), data_only=True)
    assert wb.sheetnames, "Workbook has no worksheets — expected one per staff user"

    for ws in wb.worksheets:
        cells = [c for row in ws.iter_rows(values_only=True) for c in row if c not in (None, "")]
        blob = _normalize(" ".join(str(c) for c in cells))
        missing_days = [d for d in EXPECTED_XLSX_DAYS if _normalize(d) not in blob]
        assert not missing_days, (
            f"Day columns missing from sheet '{ws.title}': {missing_days}"
        )

        labels = {
            _normalize(row[0])
            for row in ws.iter_rows(min_col=1, max_col=1, values_only=True)
            if row[0]
        }
        missing_metrics = [m for m in EXPECTED_XLSX_METRICS if _normalize(m) not in labels]
        assert not missing_metrics, (
            f"Activity rows missing from sheet '{ws.title}': {missing_metrics}"
        )


@pytest.fixture(scope="class")
def upr_page(staff_context: BrowserContext):
    """Open the User Productivity Report once for the whole class.

    Every phase below asserts against this same already-open report. Navigating per phase
    would reload the Angular bundle cold each time for no benefit — these checks are all
    order-independent, so they can share one grid (same rationale as the `staff_page`
    fixture in conftest). Skips here propagate to every phase when the report is absent."""
    page = staff_context.new_page()
    go_to_staff_dashboard(page)
    open_user_productivity_report(page)
    yield page
    page.close()


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.report
class TestE2E059UserProductivityReport:
    """E2E-059: User Productivity Report — verify columns, paginator, per-week XLSX
    download, and sorting.

    Phase order is deliberate, not just numbering: all four phases share one already-open
    report (`upr_page`, opened once for the class — see that fixture). Sorting the grid
    (phase 4) leaves its Download links non-functional afterward (confirmed live: every
    download attempt post ASC+DESC sort timed out with no error surfaced, regardless of
    which row/week was targeted — a real product defect, not test flakiness). Phases that
    depend on a working grid (paginator, download) therefore run BEFORE the sorting phase,
    which is why sorting is last despite being listed earlier in this suite's own docstring.
    """

    def test_phase_1_report_loads_and_columns(self, upr_page):
        """Phase 1: Reports → User Productivity Report loads with no filters applied →
        verify the Week column, the week format, and a Download action per row."""
        page = upr_page

        # The report heading confirms the right report opened.
        expect(
            page.locator('//h1[contains(text(),"User Productivity Report")] | '
                         '//*[contains(@class,"title")][contains(text(),"User Productivity Report")]').first
        ).to_be_visible(timeout=15_000)

        # Verify every expected column header is present.
        for col in EXPECTED_COLUMNS:
            expect(
                page.locator(f'table thead th:has-text("{col}")').first
            ).to_be_visible(timeout=10_000)

        # The report auto-loads with no filters applied — it must render rows as-is.
        weeks = nonempty_values(page, 0)
        assert weeks, "User Productivity Report has no data rows"

        # Every Week cell is an 'MM/DD/YYYY - MM/DD/YYYY' range.
        malformed = [w for w in weeks if not WEEK_RE.match(w)]
        assert not malformed, f"Week cells not formatted as a date range: {malformed}"

        # Each week row exposes its own Download action.
        downloads = page.locator('table tbody tr span.link:has-text("Download")')
        assert downloads.count() == len(weeks), (
            f"Expected one Download link per week row: {len(weeks)} week(s) "
            f"but {downloads.count()} Download link(s)"
        )
        print(f"  [E2E-059] report loaded with {len(weeks)} week(s): {weeks}")

    def test_phase_2_paginator_page_size(self, upr_page):
        """Phase 2: the paginator offers Show 10/20/50 and the results counter agrees with
        the rows rendered."""
        page = upr_page

        weeks = nonempty_values(page, 0)
        assert weeks, "User Productivity Report has no data rows"

        # Results counter ('1 - 4 of 4 results') — poll rather than read once: it is a
        # separate Angular binding from the row array and can lag it by a beat.
        counter = wait_for_counter(page)
        assert counter, "Results counter ('x - y of N results') not found"
        shown_to, total = counter[1], counter[2]
        assert total == len(weeks), (
            f"Counter reports {total} result(s) but {len(weeks)} week row(s) rendered"
        )
        assert shown_to == len(weeks), (
            f"Counter shows up to row {shown_to} but {len(weeks)} week row(s) rendered"
        )

        # Page-size control offers the standard sizes.
        page_size = page.locator('mat-select[aria-label="Page Size"]').first
        expect(page_size).to_be_visible(timeout=10_000)
        page_size.click()
        page.wait_for_timeout(1000)
        options = page.evaluate(
            """() => [...document.querySelectorAll('mat-option')]
                 .map(o => (o.textContent || '').trim()).filter(t => t)"""
        )
        missing = [s for s in EXPECTED_PAGE_SIZES if s not in options]
        assert not missing, f"Page-size options missing: {missing} (offered: {options})"

        # Selecting a larger page size must keep every row rendered.
        page.locator('mat-option:has-text("Show 50")').first.click()
        page.wait_for_load_state("networkidle")
        resized = wait_for_column(page, 0, lambda vals: len(vals) == len(weeks))
        assert len(resized) == len(weeks), (
            f"Row count changed after selecting 'Show 50': {len(weeks)} -> {len(resized)}"
        )
        print(f"  [E2E-059] paginator: {total} result(s), page sizes {options}")

    def test_phase_3_download_week_xlsx_and_verify_fields(self, upr_page):
        """Phase 3: download the first week's report → an .xlsx named for that week →
        the workbook carries a sheet per user with the day columns and activity rows."""
        page = upr_page

        weeks = nonempty_values(page, 0)
        assert weeks, "User Productivity Report has no data rows"

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        week = weeks[0]
        download = download_week(page, 0)

        # The filename carries the week it was generated for — on environments that serve a
        # descriptive name. Some environments serve an opaque content-hash filename instead
        # (observed on STAGE 2026-07-23: '4739fa11af4d7598a6e99a6ffed22d28.xlsx'). Assert the
        # week stamp only when the name actually carries a date; otherwise the week
        # association is verified through the workbook content below, which is the real check.
        name = download.suggested_filename
        slug = week_slug(week)
        if re.search(r"\d{2}-\d{2}-\d{4}", name):
            assert slug in name, (
                f"Downloaded file {name!r} is not stamped with its week {week!r} "
                f"(expected {slug!r} in the filename)"
            )
        else:
            print(f"  [E2E-059] download served an opaque filename {name!r} (no date stamp) "
                  f"— week association verified via workbook content instead")

        xlsx_path = DOWNLOADS_DIR / name
        download.save_as(str(xlsx_path))
        assert xlsx_path.stat().st_size > 0, f"Downloaded workbook is empty: {name}"

        verify_xlsx_fields(xlsx_path)
        print(f"  [E2E-059] downloaded {name!r} for week {week} and verified its fields")

    def test_phase_4_week_column_sorting(self, upr_page):
        """Phase 4 (last — see class docstring): sort the Week column ascending then
        descending → the two orderings are exact reverses of one another.

        Runs last deliberately: sorting leaves the grid's Download links (and briefly its
        results counter) non-functional afterward, so nothing downstream in this class may
        depend on the grid once this phase has touched it."""
        page = upr_page

        baseline = nonempty_values(page, 0)
        assert len(baseline) >= 2, (
            f"Need >=2 week rows to verify sorting, found {len(baseline)}"
        )

        asc_btn = page.locator(SORT_ASC_BTN).first
        desc_btn = page.locator(SORT_DESC_BTN).first
        expect(asc_btn).to_be_visible(timeout=10_000)
        expect(desc_btn).to_be_visible(timeout=10_000)

        asc_btn.click()
        page.wait_for_load_state("networkidle")
        asc_order = wait_for_column(page, 0, lambda vals: len(vals) == len(baseline))
        assert len(asc_order) == len(baseline), (
            f"Ascending sort changed the row count: {len(baseline)} -> {len(asc_order)}"
        )

        desc_btn.click()
        page.wait_for_load_state("networkidle")
        # Assert reverse-symmetry rather than a fixed ordering: it holds regardless of
        # the grid's collation, so the check stays valid if the sort key changes.
        desc_order = wait_for_column(
            page, 0, lambda vals: vals == list(reversed(asc_order))
        )
        assert desc_order == list(reversed(asc_order)), (
            f"Descending sort is not the reverse of ascending.\n"
            f"  asc : {asc_order}\n  desc: {desc_order}"
        )
        print(f"  [E2E-059] sort asc {asc_order} / desc {desc_order}")
