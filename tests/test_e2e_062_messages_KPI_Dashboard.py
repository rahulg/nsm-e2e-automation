"""
E2E-062: Messages/Home — KPI Dashboard & Message Center
Staff Portal — the dashboard landing page and both of its tabs.

Flow (one phase per test method, run in order against a single dashboard tab):

  1. [Staff Portal] Log in via saved auth session, open Messages/Home and assert the
     page headers: page title, both tabs, the seven summary counters and all twelve
     KPI widget titles
  2. KPI Dashboard — LT-260 / LT-262 / LT-263 / LT-262A Paper vs. Digital
     Submissions: select a START DATE and END DATE on the SAME day and verify the
     graph that comes back is correct
  3. Form Status — LT-260 / LT-262 / LT-263 / LT-261 / LT-262A: same
  4. Transaction Volume by Payment Type and Amount Collected by Payment Type: same,
     plus the agreement between the two
  5. Count of Public Users/Garages — switch TYPE between Facilities and Public
     Portal Users, change the YEAR, and verify the chart tracks both controls
  6. [Form listings] LT-260 / 261 / 262 / 262A / 263 -> All tab -> insta filter
     (Today, and yesterday's chip) -> the record count must account for that form's
     'Form Status - X' chart, and the FORM TYPE column must match its
     'X - Paper vs. Digital Submissions' chart
  7. [Payments listing] filtered to a day -> PAYMENT TYPE counts must match
     Transaction Volume, and the PAYMENT AMOUNT column must sum to Amount Collected;
     the two summary counters must restate the same two charts unfiltered
  8. [Facility Management] registrations per year -> reconcile against Count of
     Public Users/Garages
  9. Message Center — assert the Inbox headers and columns. If the grid shows
     'No Records Found' the check stops there (per the test brief); otherwise the
     Show Filters control is exercised against live data.

Phases 6-8 cover all twelve graphs against a listing; nothing on the dashboard is
verified only against itself.

## What "is the graph correct?" means here

Every widget is a **Chart.js v2** canvas, so the rendered series is readable straight
off ``window.Chart.instances`` — labels, values and chart type as real data rather
than pixels (see ``KpiDashboardPage``). That makes five independent claims assertable:

* **Shape** — the expected chart type, one label per value, all values finite and
  non-negative, no duplicate labels.
* **Containment** — a single day's slice can never exceed the unfiltered all-time
  value for the same label, and cannot introduce labels the unfiltered chart lacks.
* **Additivity** — ``day(D-1) + day(D) == range(D-1 .. D)`` per label. This is the
  assertion that actually pins the date filter down: it catches inclusive/exclusive
  boundary bugs, timezone-shifted day windows and double-counted rows, none of which
  a "the chart re-rendered" check would notice. Probe days are chosen from real data
  (see ``_probe_day``) so the sum is non-trivial rather than 0 + 0 == 0.
* **Cross-widget agreement** — Transaction Volume and Amount Collected must report
  the same payment types over the same window; money without a transaction (or the
  reverse) is a defect.
* **Agreement with the records** (phases 6-8) — the strongest of the five, because
  it is the only one that leaves the dashboard. Each chart is held against the grid
  that holds the same records: the form listings under an insta-filter, the Payments
  listing under a date range, Facility Management under a year. Those answer "how
  many, of what type, for how much money?" through a different query than the KPI
  widget, so agreement is real corroboration rather than a chart agreeing with
  itself. Where a chart does not restate its listing exactly, the difference is
  named and accounted for rather than tolerated as a fudge — see
  ``UNCHARTED_STATUSES`` and phase 8's docstring.

Probe days are taken strictly before today so no record created mid-run can shift a
window between the three reads that make up an additivity check.

## Environments

Runs against QA and STAGE unchanged — ``--env qa`` (default) or ``--env stage``. The
checks are written so that nothing here is tied to one environment's data:

* **No hardcoded counts.** Every expectation is a relationship between two live
  readings (chart vs listing, day vs day), never a literal number. The figures quoted
  in comments are evidence for *why* a rule exists, not values under assertion.
* **Days come from the data.** ``_probe_day`` finds a day that actually carries
  records rather than assuming one, and remembers it across widgets so a sparse
  environment does not pay a full day-by-day walk per widget.
* **Empty is not failure.** A widget with no records at all, or an insta-filter chip
  the app disables because a day is empty, is reported and skipped — the shape checks
  still run. Only a contradiction between two live readings fails.
* **Dates come from NC time, not the runner's clock.** conftest pins every context to
  ``America/New_York`` and the app's own 'Today' chip follows that clock, so
  ``_today()`` does too. Using the machine's date instead breaks nightly from a
  non-US timezone — from IST it rolls over ~9.5 hours early, naming a day the app has
  not reached and a 'yesterday' chip that does not exist in the strip.
* **STAGE is much slower.** The Angular bundle boots in ~2 s on QA and 50-60 s on
  STAGE, and the charts land later still, so the readiness budgets scale with
  ``NSM_ENV`` (chart construction, grid record counts, route confirmation). Every
  wait is a poll on a real readiness signal, so the larger budget costs a healthy QA
  run nothing. Listings are opened by direct URL rather than via the dashboard's
  sidebar for the same reason — it skips an entire Angular boot per phase.
* **A cold environment skips, it does not fail.** A non-prod environment scaled to
  zero answers every request with a 'Server Starting' holding page at HTTP 200.
  ``wait_for_app_boot`` rides out a cold start; if the app is still not up, the class
  skips once with that reason instead of nine phases failing on nine symptoms.

The one place an environment could legitimately differ is ``UNCHARTED_STATUSES`` —
if a build charts a status on one environment and drops it on another, the accounting
fails with both figures in the message, which is the right outcome to investigate
rather than absorb.

Runs headless (pytest-playwright's default; ``--headed`` is opt-in). The nine phases
share one browser tab but do not depend on each other's state — each re-establishes
what it needs, and a widget's baseline is re-cleared if anything left a range on it —
so ``-n`` (pytest-xdist, already a dependency) may split them across workers:
measured 9 passed in 3m51s at ``-n 3`` against 7m02s serially on QA.
"""

import datetime
import re
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import BrowserContext, Page, expect

# The timezone every browser context is pinned to. Imported rather than repeated so
# the test's idea of "today" cannot drift from the one the contexts actually run in.
# (``tests`` is a package, so plain ``conftest`` would resolve to the *root* conftest,
# which does not define it.)
from tests.conftest import NC_TIMEZONE
from src.pages.staff_portal.form_listing_page import FormListingPage
from src.pages.staff_portal.kpi_dashboard_page import (
    ALL_WIDGETS,
    DATE_RANGE_WIDGETS,
    FORM_STATUS_WIDGETS,
    MESSAGE_CENTER_COLUMNS,
    PAPER_VS_DIGITAL_WIDGETS,
    PAYMENT_WIDGETS,
    SUMMARY_HEADERS,
    USERS_GARAGES_WIDGET,
    KpiDashboardPage,
)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# How many days back to look for a day that actually carries data, so the same-day
# and additivity checks assert something real instead of 0 + 0 == 0.
MAX_PROBE_DAYS = 7

# Currency values (Amount Collected) are floats — compare to the cent.
MONEY_TOLERANCE = 0.01

# Records may be created on these environments while the run is in flight, so an
# all-time total read from two different pages minutes apart can legitimately differ
# by a few. Per-day comparisons over past days are exact and carry the real signal;
# this only stops a live write from failing the unfiltered sanity check.
LIVE_DRIFT_TOLERANCE = 10

# Payment types the two payment widgets are allowed to report.
KNOWN_PAYMENT_TYPES = {"ONLINE", "Check", "Certified Check", "Money Order", "Cash", "ACH"}

# Bar labels on Count of Public Users/Garages are MM/YY buckets.
MONTH_LABEL_RE = re.compile(r"^(0[1-9]|1[0-2])/(\d{2})$")

# Phase 6 — each form whose listing is cross-checked against its 'Form Status - X'
# chart. The listing's route/sidebar code and the chart's title suffix are the same
# string, which is what lets one loop cover all five.
LISTING_FORMS = ["LT-260", "LT-261", "LT-262", "LT-262A", "LT-263"]

# The listing column the insta filter is expected to narrow, and the one the chart's
# slices are compared against. Not every listing has a STATUS column (LT-263's All tab
# does not), in which case only the totals can be compared.
LISTING_DATE_COLUMN = "DATE SUBMITTED"
LISTING_STATUS_COLUMN = "STATUS"
LISTING_FORM_TYPE_COLUMN = "FORM TYPE"

# Forms whose listing carries a FORM TYPE (Paper / Digital) column, and which
# therefore also have an 'X - Paper vs. Digital Submissions' chart to check against
# it. LT-261 has neither — no FORM TYPE column and no Paper-vs-Digital widget.
PAPER_VS_DIGITAL_FORMS = ["LT-260", "LT-262", "LT-262A", "LT-263"]

# Payments listing columns backing the two payment charts (phase 7).
PAYMENTS_DATE_COLUMN = "RECEIVED DATE"
PAYMENTS_TYPE_COLUMN = "PAYMENT TYPE"
PAYMENTS_AMOUNT_COLUMN = "PAYMENT AMOUNT"

# Facility Management columns backing Count of Public Users/Garages (phase 8).
FACILITY_TYPE_COLUMN = "TYPE"
FACILITY_DATE_COLUMN = "REGISTERED ON"

# Statuses a form's listing shows that its Form Status chart does NOT count.
#
# The naive expectation — "the chart's total equals the listing's count for that day"
# — holds exactly for LT-260, LT-262A and LT-263, and does not for LT-261 and LT-262.
# Measured on QA 2026-08-07 (yesterday = 08/06):
#
#   LT-260   listing 68, chart 68  — nothing dropped
#   LT-261   listing 14, chart  8  — 6 'Stolen' records absent from the chart, even
#                                    though its own UNFILTERED view carries a Stolen
#                                    slice (130). Worth a product question: the slice
#                                    disappears once a date range is applied.
#   LT-262   listing 32, chart 28  — 4 'LT-262 Closed' records absent; the chart has no
#                                    Closed bucket at all (unlike Form Status - LT-260,
#                                    which does). Its 'LT-262 Submitted' slice reads 9
#                                    against 5 rows in that status because the chart
#                                    folds the 2 'Aging' + 2 'Court Hearing' rows in —
#                                    hence this check compares TOTALS, not per-label
#                                    counts, which would encode that grouping as fact.
#   LT-262A  listing  3, chart  3  — matches, though the listing labels those rows
#                                    'LT-262A Processed' where the chart says
#                                    'Vehicle Sold' (another reason to compare totals).
#   LT-263   listing 14, chart 14  — matches; its All tab has no STATUS column.
#
# STAGE (2026-08-08, busiest recent day 08/04) showed the same behaviour with a
# different shape, which is why the leftover is REPORTED rather than asserted:
#
#   LT-260   listing 93, chart 93  — nothing dropped, as on QA
#   LT-261   listing 19, chart 11  — 8 'Stolen' dropped; the QA finding reproduces, so
#                                    it is product behaviour, not QA data
#   LT-262   listing 39, chart 35  — 4 dropped, but labelled 'LT-262 Processed', not
#                                    Closed: on this environment the excluded records
#                                    are indistinguishable from included ones by status
#                                    text alone, so no status table can express them
#   LT-262A  listing 16, chart 12  — 4 'LT-262A Closed' dropped (QA dropped none)
#   LT-263   listing 34, chart 30  — 4 'LT-263 Closed' dropped (QA dropped none, and
#                                    QA's All tab has no STATUS column at all)
#
# So the charts cover a SUBSET of the All tab whose rule varies by form and build.
# Asserting equality would just mean "this environment matches the one the table was
# measured on", so the difference is printed as a FINDING on every run instead.
#
# The opposite direction — chart LARGER than the listing — stays a hard failure: a
# breakdown cannot exceed the population it breaks down, whatever the environment
# holds. As of 2026-08-08 it fires on QA and STAGE for LT-262 and LT-262A, and the
# per-row date assertion in the same phase says why: the insta-filter chip labelled
# '08/06/26' returns rows whose DATE SUBMITTED is 08-07-2026. The chip is filtering a
# different day (or a different date field) from the one it advertises, so the
# listing is answering a different question than the chart. LT-260, LT-261 and LT-263
# pass the identical check on the identical chip, which is what makes this specific
# rather than environmental. Both failures are real; do not silence them to get green.
UNCHARTED_STATUSES = {
    "LT-260": set(),
    "LT-261": {"Stolen"},
    "LT-262": {"LT-262 Closed"},
    "LT-262A": set(),
    "LT-263": set(),
}


def _today() -> datetime.date:
    """Today *in NC time*, which is the only 'today' the system under test knows.

    conftest pins every browser context to ``America/New_York``, and the app's own
    'Today' insta-filter chip follows that clock. The runner's local date does not:
    from a machine in IST, ``date.today()`` rolls over about nine and a half hours
    early, so from ~09:30 IST onwards it names a day the app has not reached. That
    surfaced as the 'Today' chip filtering an empty future day and, past midnight
    IST, as the previous day's chip simply not existing in the strip (measured live
    2026-08-08 00:14 IST = 2026-08-07 14:44 EDT).
    """
    return datetime.datetime.now(ZoneInfo(NC_TIMEZONE)).date()


def _fmt(d: datetime.date) -> str:
    return d.strftime("%m/%d/%Y")


def _assert_chart_shape(snapshot: dict, title: str, expected_type: str):
    """Structural claims that must hold for any rendering of a widget."""
    assert snapshot["type"] == expected_type, (
        f"{title}: expected a {expected_type} chart, got {snapshot['type']!r}"
    )
    labels, data = snapshot["labels"], snapshot["data"]
    assert len(labels) == len(data), (
        f"{title}: {len(labels)} label(s) but {len(data)} value(s) — the graph's "
        f"legend and its data are out of step: labels={labels} data={data}"
    )
    assert len(set(labels)) == len(labels), (
        f"{title}: duplicate labels in the chart legend: {labels}"
    )
    assert all(str(l).strip() for l in labels), f"{title}: blank label in {labels}"
    for label, value in zip(labels, data):
        assert isinstance(value, (int, float)), (
            f"{title}: segment {label!r} is not numeric: {value!r}"
        )
        assert value == value, f"{title}: segment {label!r} is NaN"  # NaN != NaN
        assert value >= 0, f"{title}: segment {label!r} is negative: {value}"


def _as_map(snapshot: dict) -> dict:
    return dict(zip(snapshot["labels"], snapshot["data"]))


def _money(text) -> float:
    """'$16.75' -> 16.75. Blank/absent cells count as zero."""
    cleaned = re.sub(r"[^0-9.\-]", "", str(text or ""))
    return float(cleaned) if cleaned not in ("", "-", ".") else 0.0


def _summary_counter_values(page) -> dict:
    """The seven summary counters as {header: displayed value}.

    Counter titles are <h3>; the value is a sibling inside the same card."""
    return page.evaluate(
        """(headers) => {
            const out = {};
            for (const h of headers) {
                const node = Array.from(document.querySelectorAll('h3, h4, h5, h6, div, span, p'))
                    .find(e => e.children.length === 0 && (e.textContent || '').trim() === h);
                if (!node) { out[h] = null; continue; }
                const card = node.parentElement;
                out[h] = (card.innerText || '').replace(h, '').trim();
            }
            return out;
        }""",
        SUMMARY_HEADERS,
    )


def _check_counter(failures: list, counters: dict, header: str, charted, chart_title: str):
    """A summary counter must restate its chart's unfiltered total."""
    shown = counters.get(header)
    if shown is None:
        failures.append(f"Summary counter {header!r} is missing from Messages/Home")
        return
    if abs(_money(shown) - charted) > MONEY_TOLERANCE:
        failures.append(
            f"Summary counter {header!r} reads {shown!r} but {chart_title!r} totals "
            f"{charted} — the counter and the chart disagree"
        )


# The most recent day already found to carry data. Each probe is a full server
# round trip that re-queries all twelve widgets, so on a sparse environment a naive
# day-by-day walk costs MAX_PROBE_DAYS trips *per widget*. Widgets on one environment
# tend to share their busy days, so the last day that worked is tried first.
_probe_day_hint = None


def _probe_day(kpi: KpiDashboardPage, title: str):
    """Find a single day whose chart carries data, and return ``(date, snapshot)``.

    Returns ``(None, snapshot)`` when no day in the search window has data — an empty
    window is legitimate for a sparse form, so the caller downgrades to shape-only
    checks rather than failing.

    Never probes today: a record created while the test is running would change
    today's window between the three reads an additivity check makes."""
    global _probe_day_hint
    today = _today()
    candidates = [today - datetime.timedelta(days=back) for back in range(1, MAX_PROBE_DAYS + 1)]
    if _probe_day_hint in candidates:
        candidates.remove(_probe_day_hint)
        candidates.insert(0, _probe_day_hint)

    snapshot = None
    for day in candidates:
        snapshot = kpi.set_date_range(title, _fmt(day), _fmt(day))
        if sum(snapshot["data"]) > 0:
            _probe_day_hint = day
            return day, snapshot
    return None, snapshot


def _verify_date_range_widget(
    kpi: KpiDashboardPage,
    title: str,
    expected_type: str = "pie",
    check_baseline=None,
):
    """Full correctness pass over one date-range widget.

    Baseline shape -> same-day slice (shape + containment) -> additivity over the
    probe day and the day before it. ``check_baseline`` receives the unfiltered
    snapshot for the widget-specific legend assertions, so the baseline is read
    once per widget rather than once per caller.

    The baseline is normally *read*, not re-filtered: a widget starts unfiltered, and
    the dashboard re-queries all twelve charts on every committed date change, so a
    blind clear is one of the most expensive no-ops available. The date inputs are
    checked first — a pure DOM read — and cleared only when something actually left a
    range on the widget, which keeps the baseline correct even if the phases run out
    of order (under ``-n``, say) rather than silently comparing against a filtered
    'baseline'."""
    if not kpi.is_date_range_clear(title):
        kpi.clear_date_range(title)
    baseline = kpi.chart(title)
    _assert_chart_shape(baseline, title, expected_type)
    if check_baseline is not None:
        check_baseline(baseline)
    if sum(baseline["data"]) <= 0:
        # No records at all behind this widget. That is an environment data
        # condition, not a defect — the shape checks above still ran, but there is
        # nothing for the date filter to narrow, so stop here rather than fail.
        print(
            f"  [E2E-062] {title}: unfiltered chart is empty on this environment — "
            f"shape verified, date-filter checks skipped (no data to narrow)"
        )
        return
    baseline_map = _as_map(baseline)
    print(f"  [E2E-062] {title}: baseline {baseline_map}")

    # --- same-day slice -------------------------------------------------------
    day, same_day = _probe_day(kpi, title)
    _assert_chart_shape(same_day, title, expected_type)

    if day is None:
        print(
            f"  [E2E-062] {title}: no data in the last {MAX_PROBE_DAYS} days — "
            f"same-day slice verified for shape only (empty window)"
        )
        return

    same_day_map = _as_map(same_day)
    print(f"  [E2E-062] {title}: {_fmt(day)} (same day) {same_day_map}")

    unknown = set(same_day_map) - set(baseline_map)
    assert not unknown, (
        f"{title}: the {_fmt(day)} slice shows label(s) {sorted(unknown)} that the "
        f"unfiltered chart does not have — the filtered graph is not a subset of the whole"
    )
    for label, value in same_day_map.items():
        assert value <= baseline_map[label] + MONEY_TOLERANCE, (
            f"{title}: one day ({_fmt(day)}) reports {value} for {label!r}, more than "
            f"the unfiltered total {baseline_map[label]} — the date filter is not "
            f"narrowing the data"
        )

    # --- additivity: day(D-1) + day(D) == range(D-1 .. D) ---------------------
    previous = day - datetime.timedelta(days=1)
    prev_map = _as_map(kpi.set_date_range(title, _fmt(previous), _fmt(previous)))
    span_snapshot = kpi.set_date_range(title, _fmt(previous), _fmt(day))
    _assert_chart_shape(span_snapshot, title, expected_type)
    span_map = _as_map(span_snapshot)

    for label in set(same_day_map) | set(prev_map) | set(span_map):
        expected = same_day_map.get(label, 0) + prev_map.get(label, 0)
        actual = span_map.get(label, 0)
        assert abs(actual - expected) <= MONEY_TOLERANCE, (
            f"{title}: date range {_fmt(previous)}..{_fmt(day)} reports {actual} for "
            f"{label!r} but the two days individually total {expected} "
            f"({_fmt(previous)}={prev_map.get(label, 0)}, {_fmt(day)}="
            f"{same_day_map.get(label, 0)}) — the range window is off by a boundary "
            f"day, double-counting, or losing rows"
        )
    print(
        f"  [E2E-062] {title}: additivity holds over "
        f"{_fmt(previous)}..{_fmt(day)} {span_map}"
    )
    # The widget is deliberately left filtered — nothing downstream reads it again,
    # and a tidy-up clear would cost another full twelve-chart refresh.


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
class TestE2E062MessagesKPIDashboard:
    """E2E-062: Messages/Home headers, KPI Dashboard graph correctness, Message Center."""

    @pytest.fixture(scope="class")
    def kpi_page(self, staff_context: BrowserContext) -> Page:
        """One Messages/Home tab for the whole class.

        The Angular bundle boots slowly and the twelve charts render later still, so
        re-opening the dashboard per phase would cost more than the assertions do."""
        page = staff_context.new_page()
        page.set_viewport_size({"width": 1600, "height": 1200})
        kpi = KpiDashboardPage(page)
        kpi.goto()
        if kpi.is_booting():
            # The environment is scaled down and still serving its holding page.
            # Skipping once here beats nine phases failing on nine different
            # symptoms of the same outage.
            page.close()
            pytest.skip(
                "Staff portal is still serving its 'Server Starting' page — the "
                "environment is not up, so nothing here can be verified"
            )
        yield page
        page.close()

    # -- Phase 1 ------------------------------------------------------------

    def test_phase_1_messages_home_headers(self, kpi_page: Page):
        """Phase 1: Messages/Home renders its title, both tabs, the summary counters
        and all twelve KPI widget headers."""
        kpi = KpiDashboardPage(kpi_page)

        assert kpi_page.title() == "Messages/Home", (
            f"Expected the Messages/Home page title, got {kpi_page.title()!r}"
        )
        expect(kpi_page.locator('a[href$="/dashboard"]:has-text("Messages/Home")').first
               ).to_be_visible(timeout=15_000)
        expect(kpi.kpi_tab).to_be_visible(timeout=15_000)
        expect(kpi.message_center_tab).to_be_visible(timeout=15_000)

        # Summary counters — header text plus a real value under each one.
        body = kpi_page.inner_text("body")
        for header in SUMMARY_HEADERS:
            assert header in body, f"Summary counter {header!r} is missing from Messages/Home"
            expect(kpi_page.locator(f'text="{header}"').first).to_be_visible(timeout=10_000)
        counter_values = _summary_counter_values(kpi_page)
        for header, value in counter_values.items():
            assert value and re.search(r"\d", value), (
                f"Summary counter {header!r} shows no numeric value (got {value!r})"
            )
        print(f"  [E2E-062] summary counters: {counter_values}")

        # All twelve widget headers.
        for title in ALL_WIDGETS:
            assert kpi.widget_exists(title), f"KPI widget {title!r} is missing from the dashboard"
            expect(kpi_page.locator(f'h5:has-text("{title}")').first).to_be_visible(timeout=10_000)

        # DATE RANGE / START DATE / END DATE labelling on every date-range widget.
        for title in DATE_RANGE_WIDGETS:
            card_text = kpi_page.evaluate(
                """(title) => {
                    const h = Array.from(document.querySelectorAll('h5'))
                        .find(e => (e.textContent || '').trim() === title);
                    let card = h;
                    for (let i = 0; i < 15 && card.parentElement; i++) {
                        card = card.parentElement;
                        if (card.querySelector('canvas')) break;
                    }
                    return (card.innerText || '').trim();
                }""",
                title,
            )
            for label in ("DATE RANGE", "START DATE", "END DATE"):
                assert label in card_text, f"{title}: {label!r} label missing (card reads {card_text!r})"

        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_01_messages_home.png"), full_page=True)
        print(f"  [E2E-062] Messages/Home headers verified — {len(ALL_WIDGETS)} widgets present")

    # -- Phase 2 ------------------------------------------------------------

    def test_phase_2_paper_vs_digital_widgets(self, kpi_page: Page):
        """Phase 2: LT-260 / LT-262 / LT-263 / LT-262A Paper vs. Digital Submissions —
        same-day range and additivity, with the Paper/Digital split verified."""
        kpi = KpiDashboardPage(kpi_page)
        for title in PAPER_VS_DIGITAL_WIDGETS:
            def _paper_digital_split(snapshot, title=title):
                assert snapshot["labels"] == ["Paper", "Digital"], (
                    f"{title}: expected the Paper/Digital split, got {snapshot['labels']}"
                )

            _verify_date_range_widget(kpi, title, check_baseline=_paper_digital_split)
        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_02_paper_vs_digital.png"), full_page=True)

    # -- Phase 3 ------------------------------------------------------------

    def test_phase_3_form_status_widgets(self, kpi_page: Page):
        """Phase 3: Form Status — LT-260 / LT-262 / LT-263 / LT-261 / LT-262A."""
        kpi = KpiDashboardPage(kpi_page)
        for title in FORM_STATUS_WIDGETS:
            def _status_breakdown(snapshot, title=title):
                assert len(snapshot["labels"]) >= 2, (
                    f"{title}: a status breakdown needs more than one slice, got "
                    f"{snapshot['labels']}"
                )

            _verify_date_range_widget(kpi, title, check_baseline=_status_breakdown)
        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_03_form_status.png"), full_page=True)

    # -- Phase 4 ------------------------------------------------------------

    def test_phase_4_payment_type_widgets(self, kpi_page: Page):
        """Phase 4: Transaction Volume and Amount Collected by Payment Type, plus the
        cross-widget agreement between them."""
        kpi = KpiDashboardPage(kpi_page)
        for title in PAYMENT_WIDGETS:
            def _known_payment_types(snapshot, title=title):
                unknown = set(snapshot["labels"]) - KNOWN_PAYMENT_TYPES
                assert not unknown, (
                    f"{title}: unrecognised payment type(s) {sorted(unknown)} — expected "
                    f"a subset of {sorted(KNOWN_PAYMENT_TYPES)}"
                )

            _verify_date_range_widget(kpi, title, check_baseline=_known_payment_types)

        # The two payment widgets describe the same transactions from different
        # angles, so over the same (unfiltered) window they must agree on which
        # payment types exist. Money with no transaction behind it is a defect.
        volume = kpi.clear_date_range("Transaction Volume by Payment Type")
        amount = kpi.clear_date_range("Amount Collected by Payment Type")
        assert set(volume["labels"]) == set(amount["labels"]), (
            f"Transaction Volume reports payment types {sorted(volume['labels'])} but "
            f"Amount Collected reports {sorted(amount['labels'])} — the two payment "
            f"graphs disagree about which payment types exist"
        )
        volume_map, amount_map = _as_map(volume), _as_map(amount)
        for label in volume_map:
            if volume_map[label] == 0:
                assert amount_map[label] == 0, (
                    f"Amount Collected shows {amount_map[label]} for {label!r} while "
                    f"Transaction Volume shows zero transactions of that type"
                )
        print(f"  [E2E-062] payment widgets agree on types: {sorted(volume_map)}")
        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_04_payment_types.png"), full_page=True)

    # -- Phase 5 ------------------------------------------------------------

    def test_phase_5_public_users_and_facilities(self, kpi_page: Page):
        """Phase 5: Count of Public Users/Garages — TYPE (Facilities / Public Portal
        Users) and YEAR both drive the chart."""
        kpi = KpiDashboardPage(kpi_page)
        title = USERS_GARAGES_WIDGET
        this_year = _today().year

        options = kpi.type_options(title)
        for expected in ("Facilities", "Public Portal Users"):
            assert expected in options, (
                f"{title}: TYPE dropdown is missing {expected!r} (offers {options})"
            )

        def _assert_month_buckets(snapshot, year, label):
            _assert_chart_shape(snapshot, f"{title} [{label}]", "bar")
            suffix = f"{year % 100:02d}"
            for month_label in snapshot["labels"]:
                assert MONTH_LABEL_RE.match(month_label), (
                    f"{title} [{label}]: {month_label!r} is not an MM/YY bucket"
                )
                assert month_label.endswith(f"/{suffix}"), (
                    f"{title} [{label}]: bucket {month_label!r} does not belong to the "
                    f"selected year {year} — the YEAR control is not filtering the chart"
                )
            months = [int(m.split("/")[0]) for m in snapshot["labels"]]
            assert months == sorted(months), (
                f"{title} [{label}]: month buckets are out of order: {snapshot['labels']}"
            )

        # --- Facilities -------------------------------------------------------
        facilities_now = kpi.select_type(title, "Facilities")
        assert kpi.selected_type(title) == "Facilities"
        facilities_now = kpi.set_year(title, this_year)
        assert kpi.year_value(title) == str(this_year), (
            f"{title}: YEAR field shows {kpi.year_value(title)!r} after selecting "
            f"{this_year} — the masked input did not take the new value"
        )
        _assert_month_buckets(facilities_now, this_year, f"Facilities {this_year}")
        print(f"  [E2E-062] {title} Facilities {this_year}: {_as_map(facilities_now)}")

        facilities_prev = kpi.set_year(title, this_year - 1)
        _assert_month_buckets(facilities_prev, this_year - 1, f"Facilities {this_year - 1}")
        assert facilities_prev["labels"] != facilities_now["labels"], (
            f"{title}: changing YEAR from {this_year} to {this_year - 1} left the month "
            f"buckets unchanged ({facilities_now['labels']}) — the chart is stale"
        )
        print(f"  [E2E-062] {title} Facilities {this_year - 1}: {_as_map(facilities_prev)}")

        # --- Public Portal Users ---------------------------------------------
        users_prev = kpi.select_type(title, "Public Portal Users")
        assert kpi.selected_type(title) == "Public Portal Users", (
            f"{title}: TYPE still reads {kpi.selected_type(title)!r} after selecting "
            f"Public Portal Users"
        )
        _assert_month_buckets(users_prev, this_year - 1, f"Public Portal Users {this_year - 1}")

        users_now = kpi.set_year(title, this_year)
        _assert_month_buckets(users_now, this_year, f"Public Portal Users {this_year}")
        print(f"  [E2E-062] {title} Public Portal Users {this_year}: {_as_map(users_now)}")

        # Both TYPEs must actually produce data for the current year — an empty
        # series on one of them means the TYPE switch silently broke the query.
        assert sum(users_now["data"]) > 0, (
            f"{title}: Public Portal Users shows no data at all for {this_year}"
        )
        assert sum(facilities_now["data"]) > 0, (
            f"{title}: Facilities shows no data at all for {this_year}"
        )
        # Same window, different populations — the two series must differ somewhere.
        assert _as_map(users_now) != _as_map(facilities_now), (
            f"{title}: Public Portal Users and Facilities return identical series for "
            f"{this_year} — the TYPE control is not being applied"
        )
        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_05_users_garages.png"), full_page=True)

    # -- Phase 6 ------------------------------------------------------------

    def test_phase_6_form_status_matches_listings(
        self, kpi_page: Page, staff_context: BrowserContext
    ):
        """Phase 6: cross-check every Form Status chart against its own listing.

        The earlier phases prove the graphs are *self*-consistent. This one holds each
        one against an independent source of truth: the form's listing -> All tab ->
        insta filter, whose record count is produced by a different query than the KPI
        widget's. Two days are compared per form — Today (as specified) and yesterday,
        which cannot drift mid-run and is normally the non-zero one.

        Every form is checked before any failure is raised, so one form disagreeing
        does not hide the state of the other four."""
        kpi = KpiDashboardPage(kpi_page)
        kpi.open_kpi_dashboard()

        today = _today()
        # "Today" (as specified) plus one day that actually carries records. Yesterday
        # is the obvious second choice but is not always a busy day — on STAGE the most
        # recent day with data was three days back, which made every comparison here a
        # vacuous 0 == 0. Phases 2-4 have already discovered such a day, so reuse it;
        # fall back to yesterday when this phase runs on its own.
        data_day = _probe_day_hint or (today - datetime.timedelta(days=1))
        probes = [("Today", today), (data_day.strftime("%m/%d/%y"), data_day)]

        listing_page = staff_context.new_page()
        listing_page.set_viewport_size({"width": 1600, "height": 1200})
        failures = []
        try:
            for form_code in LISTING_FORMS:
                title = f"Form Status - {form_code}"
                listing = FormListingPage(listing_page, form_code)
                listing.open()
                try:
                    listing.click_all_tab()
                except Exception:
                    failures.append(
                        f"{form_code}: the listing never rendered an 'All' tab, so its "
                        f"chart has no all-status population to be checked against"
                    )
                    continue
                # Fewer page turns when the day's records are collected below.
                listing.set_page_size()

                all_total = listing.wait_for_result_total()
                if not all_total:
                    failures.append(
                        f"{form_code}: the 'All' tab reports no records at all "
                        f"(got {all_total!r}) — nothing to cross-check the chart against"
                    )
                    continue
                print(f"  [E2E-062] {form_code} listing / All: {all_total} record(s)")

                for label, day in probes:
                    # A chip for a day with no records is disabled — clicking it would
                    # just burn the full Playwright timeout.
                    if listing.chip_is_disabled(label):
                        chart = kpi.set_date_range(title, _fmt(day), _fmt(day))
                        print(
                            f"  [E2E-062] {form_code} {label} ({_fmt(day)}): insta-filter "
                            f"chip is disabled (no records that day) — not comparable. "
                            f"KPI {title!r} reports {sum(chart['data'])} {_as_map(chart)}"
                        )
                        continue

                    listing.click_insta_filter(label)
                    listed = listing.wait_for_result_total()
                    if listed is None:
                        failures.append(
                            f"{form_code}: no record count after the {label!r} insta filter"
                        )
                        continue
                    if listed > all_total:
                        failures.append(
                            f"{form_code}: the {label!r} insta filter returned {listed} "
                            f"records, more than the unfiltered All tab's {all_total} — "
                            f"the filter widened the result set"
                        )

                    # Read the day's records so the comparison can be per status,
                    # not just a total (see the module docstring).
                    rows, complete = listing.collect_columns(
                        [LISTING_DATE_COLUMN, LISTING_STATUS_COLUMN, LISTING_FORM_TYPE_COLUMN]
                    )

                    # The insta filter must actually restrict the grid to that day —
                    # give or take a day at the boundary. The grid's timestamps and the
                    # chip's day buckets are not in the same timezone: rows returned by
                    # the '08/06/26' chip displayed as '08-07-2026 02:29 AM', which is
                    # late on 08/06 Eastern (the timezone every context here is pinned
                    # to) but early on 08/07 as rendered. Allowing the adjacent days
                    # keeps that from reading as a broken filter while still catching a
                    # filter that returns an unrelated date.
                    allowed_prefixes = {
                        (day + datetime.timedelta(days=offset)).strftime("%m-%d-%Y")
                        for offset in (-1, 0, 1)
                    }
                    off_day = [
                        r[LISTING_DATE_COLUMN] for r in rows
                        if r[LISTING_DATE_COLUMN]
                        and not any(
                            r[LISTING_DATE_COLUMN].startswith(p) for p in allowed_prefixes
                        )
                    ]
                    if off_day:
                        failures.append(
                            f"{form_code}: the {label!r} insta filter shows row(s) "
                            f"submitted on another day: {off_day[:5]} "
                            f"(expected {expected_prefix})"
                        )

                    # The matching Form Status chart over the same single day.
                    chart = kpi.set_date_range(title, _fmt(day), _fmt(day))
                    charted_map = _as_map(chart)
                    charted = sum(chart["data"])

                    if charted > listed:
                        # The chart and the listing are different subsystems read a few
                        # seconds apart (the chart from the application database, the
                        # grid from its search index), so a case moving mid-run — or an
                        # environment still catching up after a restart — can make them
                        # disagree for a moment. Confirm rather than tolerate: re-read
                        # BOTH sides and only fail if the contradiction survives.
                        listed = listing.wait_for_result_total()
                        charted = sum(kpi.set_date_range(title, _fmt(day), _fmt(day))["data"])
                        if charted > listed:
                            failures.append(
                                f"{form_code}: KPI {title!r} totals {charted} for "
                                f"{_fmt(day)} ({charted_map}) — more than the {listed} "
                                f"record(s) the listing's {label!r} insta filter reports "
                                f"for that day, on a re-read of both. A status breakdown "
                                f"cannot exceed the population it breaks down"
                            )
                        else:
                            print(
                                f"  [E2E-062] {form_code} {label} ({_fmt(day)}): chart/"
                                f"listing disagreement did not survive a re-read "
                                f"(now chart {charted} vs listing {listed}) — treated as "
                                f"data moving under the run, not a defect"
                            )
                            continue

                    if not complete or len(rows) != listed:
                        failures.append(
                            f"{form_code}: read {len(rows)} row(s) for {label!r} but the "
                            f"grid reports {listed} — the accounting below would be based "
                            f"on a partial read"
                        )
                        continue

                    # Account for the day: how much of the listing does the chart cover,
                    # and what is left over?
                    statuses = Counter(
                        r[LISTING_STATUS_COLUMN] for r in rows if r[LISTING_STATUS_COLUMN]
                    )
                    uncharted = UNCHARTED_STATUSES[form_code]
                    unaccounted = {s: n for s, n in statuses.items() if s in uncharted}
                    residual = listed - charted

                    if residual and residual != sum(unaccounted.values()):
                        # The chart covers fewer records than the listing by an amount
                        # the documented exclusions do not explain. Reported, not
                        # failed: the inclusion rule demonstrably varies by form and
                        # environment (see UNCHARTED_STATUSES), so failing here would
                        # only mean "this environment differs from the one this table
                        # was measured on" — which is not a defect this test can judge.
                        print(
                            f"  [E2E-062] FINDING {form_code} {label} ({_fmt(day)}): the "
                            f"listing has {listed} record(s) but {title!r} charts only "
                            f"{charted} {charted_map} — {residual} record(s) are not on "
                            f"the chart. Listing statuses: {dict(statuses)}; documented "
                            f"exclusions for this form: {sorted(uncharted) or 'none'}"
                        )
                    elif listed == 0 and charted == 0:
                        # Both empty agree trivially — say so rather than reporting an
                        # "exact match" that asserted nothing.
                        print(
                            f"  [E2E-062] {form_code} {label} ({_fmt(day)}): no records "
                            f"that day on either side — nothing to compare"
                        )
                    else:
                        print(
                            f"  [E2E-062] {form_code} {label} ({_fmt(day)}): listing {listed}, "
                            f"KPI {charted} {charted_map}"
                            + (
                                f" + {sum(unaccounted.values())} uncharted {unaccounted} "
                                f"= {listed}"
                                if unaccounted
                                else " — exact match"
                            )
                        )

                    # --- Paper vs. Digital, from the listing's FORM TYPE column ---
                    #
                    # Same day, same rows — the ones the Form Status chart counts (so
                    # the uncharted statuses come out here too; LT-262's 4 Closed rows
                    # are all Digital, which is exactly why its chart reads 25 where
                    # the listing shows 29). Unlike Form Status, this comparison can be
                    # made per label: 'Paper' and 'Digital' are the same two values in
                    # the column and in the legend, with no bucket-folding in between.
                    if form_code not in PAPER_VS_DIGITAL_FORMS or listed == 0:
                        continue
                    pvd_title = f"{form_code} - Paper vs. Digital Submissions"
                    pvd = kpi.set_date_range(pvd_title, _fmt(day), _fmt(day))
                    pvd_map = _as_map(pvd)
                    charted_rows = [
                        r for r in rows if r[LISTING_STATUS_COLUMN] not in uncharted
                    ]
                    form_types = Counter(
                        r[LISTING_FORM_TYPE_COLUMN]
                        for r in charted_rows
                        if r[LISTING_FORM_TYPE_COLUMN]
                    )
                    if not form_types:
                        failures.append(
                            f"{form_code}: the listing has no {LISTING_FORM_TYPE_COLUMN} "
                            f"values for {_fmt(day)}, so {pvd_title!r} cannot be checked"
                        )
                        continue
                    # (a) The two charts for a form must cover the SAME record set.
                    # This holds on every form and both environments measured, and it
                    # is what makes the subset behaviour above testable at all: whatever
                    # the charts exclude, they must exclude it consistently.
                    pvd_total = sum(pvd["data"])
                    if pvd_total != charted:
                        failures.append(
                            f"{form_code}: on {_fmt(day)} {title!r} totals {charted} but "
                            f"{pvd_title!r} totals {pvd_total} ({pvd_map}) — the form's two "
                            f"charts disagree about how many records that day holds, so at "
                            f"least one of them is wrong"
                        )

                    # (b) Neither type may exceed the records that exist.
                    invented = {
                        key: (pvd_map.get(key, 0), form_types.get(key, 0))
                        for key in set(pvd_map) | set(form_types)
                        if pvd_map.get(key, 0) > form_types.get(key, 0)
                    }
                    if invented:
                        failures.append(
                            f"{form_code}: KPI {pvd_title!r} reports {pvd_map} for "
                            f"{_fmt(day)} but the listing's {LISTING_FORM_TYPE_COLUMN} "
                            f"column only has {dict(form_types)} — the chart claims more "
                            f"records than exist (chart, listing): {invented}"
                        )

                    if pvd_map == dict(form_types):
                        print(
                            f"  [E2E-062] {form_code} {label} ({_fmt(day)}): "
                            f"Paper vs. Digital {pvd_map} matches the listing's "
                            f"{LISTING_FORM_TYPE_COLUMN} column exactly"
                        )
                    elif not invented:
                        print(
                            f"  [E2E-062] {form_code} {label} ({_fmt(day)}): Paper vs. "
                            f"Digital {pvd_map} is a subset of the listing's "
                            f"{dict(form_types)} — consistent with the "
                            f"{listed - charted} record(s) that form's charts exclude"
                        )

            listing_page.screenshot(
                path=str(RESULTS_DIR / "e2e062_06_listing_insta_filter.png"), full_page=True
            )
        finally:
            listing_page.close()

        assert not failures, "Listing/KPI cross-check failed:\n  - " + "\n  - ".join(failures)

    # -- Phase 7 ------------------------------------------------------------

    def test_phase_7_payment_charts_match_payments_listing(
        self, kpi_page: Page, staff_context: BrowserContext
    ):
        """Phase 7: cross-check both payment charts against the Payments listing.

        Same idea as phase 6, against a different grid. The Payments listing has no
        insta-filter chips, so the day comes from its filter row's RECEIVED DATE
        range instead. Its PAYMENT TYPE column backs Transaction Volume, and summing
        PAYMENT AMOUNT per type backs Amount Collected — the one place in this suite
        where a chart's *money* is verified against the records behind it rather than
        against another chart.

        The two summary counters are tied to the same charts here as well, since
        'Successful Payments Collected' and 'Amount Successfully Collected' are the
        unfiltered totals of exactly these two graphs."""
        kpi = KpiDashboardPage(kpi_page)
        kpi.open_kpi_dashboard()

        payments_page = staff_context.new_page()
        payments_page.set_viewport_size({"width": 1600, "height": 1200})
        failures = []
        try:
            # Straight to the listing — no dashboard boot, no sidebar wait.
            payments = FormListingPage(payments_page, "payments")
            payments.open()

            # (a) Unfiltered totals. These are moving targets: payments land on this
            # environment continuously, so three reads taken minutes apart legitimately
            # differ. The counters are the worst offender — they are computed once when
            # the dashboard loads and never re-queried, so by this phase they are as
            # stale as the run is long (measured 3,516 against a chart's 3,517 and a
            # listing's 3,518 after nine minutes). Reloading puts the counters and the
            # charts back on the same footing: same page, same load, so they must agree.
            all_payments = payments.wait_for_result_total()
            kpi.goto()
            volume_all = kpi.clear_date_range("Transaction Volume by Payment Type")
            amount_all = kpi.clear_date_range("Amount Collected by Payment Type")
            counters = _summary_counter_values(kpi_page)

            charted_volume_all = sum(volume_all["data"])
            drift = abs(charted_volume_all - all_payments)
            if drift > LIVE_DRIFT_TOLERANCE:
                failures.append(
                    f"Transaction Volume by Payment Type totals {charted_volume_all} "
                    f"but the Payments listing holds {all_payments} record(s) — a gap of "
                    f"{drift}, too large to be payments landing mid-run"
                )
            elif drift:
                print(
                    f"  [E2E-062] Payments: chart {charted_volume_all} vs listing "
                    f"{all_payments} — {drift} record(s) of drift while the run was in "
                    f"flight, within tolerance"
                )

            # The counters and the charts came from one page load, so they have no
            # excuse to disagree.
            _check_counter(
                failures, counters, "Successful Payments Collected",
                charted_volume_all, "Transaction Volume by Payment Type",
            )
            _check_counter(
                failures, counters, "Amount Successfully Collected",
                sum(amount_all["data"]), "Amount Collected by Payment Type",
            )
            print(
                f"  [E2E-062] Payments listing: {all_payments} record(s); counters "
                f"{counters.get('Successful Payments Collected')!r} / "
                f"{counters.get('Amount Successfully Collected')!r} restate both charts"
            )

            # (b) Per day: counts and money, per payment type.
            payments.show_filters()
            today = _today()
            probes = [("Today", today), ("yesterday", today - datetime.timedelta(days=1))]
            for label, day in probes:
                payments.set_date_filter(_fmt(day), _fmt(day))
                payments.set_page_size()
                listed = payments.wait_for_result_total()
                rows, complete = payments.collect_columns(
                    [PAYMENTS_DATE_COLUMN, PAYMENTS_TYPE_COLUMN, PAYMENTS_AMOUNT_COLUMN]
                )
                if not complete or len(rows) != listed:
                    failures.append(
                        f"Payments {label} ({_fmt(day)}): read {len(rows)} row(s) but the "
                        f"grid reports {listed} — a partial read cannot be compared"
                    )
                    continue

                off_day = [
                    r[PAYMENTS_DATE_COLUMN] for r in rows
                    if r[PAYMENTS_DATE_COLUMN]
                    and not r[PAYMENTS_DATE_COLUMN].startswith(day.strftime("%m-%d-%Y"))
                ]
                if off_day:
                    failures.append(
                        f"Payments {label}: the RECEIVED DATE filter shows row(s) from "
                        f"another day: {off_day[:5]}"
                    )

                # The chart labels a type 'ONLINE' where the grid says 'Online'.
                counts, money = Counter(), {}
                for row in rows:
                    key = (row[PAYMENTS_TYPE_COLUMN] or "").strip().upper()
                    counts[key] += 1
                    money[key] = money.get(key, 0.0) + _money(row[PAYMENTS_AMOUNT_COLUMN])

                volume = _as_map(kpi.set_date_range(
                    "Transaction Volume by Payment Type", _fmt(day), _fmt(day)))
                amount = _as_map(kpi.set_date_range(
                    "Amount Collected by Payment Type", _fmt(day), _fmt(day)))
                charted_volume = {k.strip().upper(): v for k, v in volume.items()}
                charted_amount = {k.strip().upper(): v for k, v in amount.items()}

                for key in set(charted_volume) | set(counts):
                    if charted_volume.get(key, 0) != counts.get(key, 0):
                        failures.append(
                            f"Payments {label} ({_fmt(day)}): Transaction Volume shows "
                            f"{charted_volume.get(key, 0)} {key} payment(s) but the "
                            f"listing has {counts.get(key, 0)}"
                        )
                for key in set(charted_amount) | set(money):
                    if abs(charted_amount.get(key, 0) - money.get(key, 0.0)) > MONEY_TOLERANCE:
                        failures.append(
                            f"Payments {label} ({_fmt(day)}): Amount Collected shows "
                            f"{charted_amount.get(key, 0)} for {key} but the listing's "
                            f"PAYMENT AMOUNT column sums to {round(money.get(key, 0.0), 2)}"
                        )
                print(
                    f"  [E2E-062] Payments {label} ({_fmt(day)}): {listed} record(s); "
                    f"volume {dict(counts)} and money "
                    f"{ {k: round(v, 2) for k, v in money.items()} } match both charts"
                )

            payments_page.screenshot(
                path=str(RESULTS_DIR / "e2e062_07_payments_listing.png"), full_page=True
            )
        finally:
            payments_page.close()

        assert not failures, "Payments/KPI cross-check failed:\n  - " + "\n  - ".join(failures)

    # -- Phase 8 ------------------------------------------------------------

    def test_phase_8_users_garages_matches_facility_management(
        self, kpi_page: Page, staff_context: BrowserContext
    ):
        """Phase 8: cross-check Count of Public Users/Garages against Facility
        Management's registrations.

        This chart has no single listing that restates it, so the check is built from
        the relationship that the data does support. Facility Management's
        Facilities/Individuals grid, filtered to a year, gives one row per
        registration typed Business or Individual; measured across 2025 and 2026
        (15 months, QA 2026-08-07):

          * ``PublicPortalUsers[m] - Facilities[m] == Individual registrations[m]``
            held in **every** month of both years. The individual half of the chart
            is therefore verified exactly.
          * ``Facilities[m] >= Business registrations[m]`` held everywhere, but not
            as an equality: the chart counted 1 more in 05/2026, and 3 more in
            05/2025 plus 1 in 06/2025. Facility Management deliberately hides
            unregistered dummy/paper garages (BR-96), which would explain a chart
            that counts garages the grid does not show — hence a one-sided bound
            plus a reported delta, rather than an equality that assumes the reason.
        """
        kpi = KpiDashboardPage(kpi_page)
        kpi.open_kpi_dashboard()
        title = USERS_GARAGES_WIDGET

        fm_page = staff_context.new_page()
        fm_page.set_viewport_size({"width": 1600, "height": 1200})
        failures = []
        try:
            # Straight to the listing — no dashboard boot, no sidebar wait.
            facilities = FormListingPage(fm_page, "facility-management")
            facilities.open()
            facilities.show_filters()

            this_year = _today().year
            for year in (this_year, this_year - 1):
                facilities.set_date_filter(f"01/01/{year}", f"12/31/{year}")
                facilities.set_page_size()
                listed = facilities.wait_for_result_total()
                rows, complete = facilities.collect_columns(
                    [FACILITY_TYPE_COLUMN, FACILITY_DATE_COLUMN]
                )
                if not complete or len(rows) != listed:
                    failures.append(
                        f"Facility Management {year}: read {len(rows)} row(s) but the grid "
                        f"reports {listed} — a partial read cannot be compared"
                    )
                    continue

                # 'MM-DD-YYYY hh:mm AM' -> the chart's 'MM/YY' bucket.
                by_type = {"Business": Counter(), "Individual": Counter()}
                for row in rows:
                    registered = row[FACILITY_DATE_COLUMN] or ""
                    if len(registered) < 10:
                        continue
                    bucket = f"{registered[0:2]}/{registered[8:10]}"
                    by_type.setdefault(row[FACILITY_TYPE_COLUMN], Counter())[bucket] += 1

                kpi.select_type(title, "Facilities")
                chart_facilities = _as_map(kpi.set_year(title, year))
                kpi.select_type(title, "Public Portal Users")
                chart_users = _as_map(kpi.chart(title))

                business, individual = by_type["Business"], by_type["Individual"]
                months = set(chart_facilities) | set(chart_users) | set(business) | set(individual)
                deltas = {}
                for month in sorted(months):
                    charted_users = chart_users.get(month, 0)
                    charted_facilities = chart_facilities.get(month, 0)

                    # Individuals: exact.
                    if charted_users - charted_facilities != individual.get(month, 0):
                        failures.append(
                            f"Facility Management {year} {month}: the chart's individual "
                            f"remainder (Public Portal Users {charted_users} - Facilities "
                            f"{charted_facilities} = {charted_users - charted_facilities}) "
                            f"does not equal the {individual.get(month, 0)} Individual "
                            f"registration(s) the listing shows that month"
                        )
                    # Businesses/garages: the chart may count more, never fewer.
                    if charted_facilities < business.get(month, 0):
                        failures.append(
                            f"Facility Management {year} {month}: the chart's Facilities "
                            f"series shows {charted_facilities} but the listing has "
                            f"{business.get(month, 0)} Business registration(s) — the "
                            f"chart is under-counting registered facilities"
                        )
                    elif charted_facilities > business.get(month, 0):
                        deltas[month] = charted_facilities - business.get(month, 0)

                print(
                    f"  [E2E-062] Facility Management {year}: {listed} registration(s) "
                    f"(Business {sum(business.values())}, Individual "
                    f"{sum(individual.values())}); chart Facilities "
                    f"{sum(chart_facilities.values())}, Public Portal Users "
                    f"{sum(chart_users.values())} — individuals reconcile exactly"
                    + (
                        f"; chart counts {sum(deltas.values())} facility/facilities not "
                        f"listed in Facility Management {deltas} (BR-96 dummy/paper garages?)"
                        if deltas else "; facilities reconcile exactly"
                    )
                )

            fm_page.screenshot(
                path=str(RESULTS_DIR / "e2e062_08_facility_management.png"), full_page=True
            )
        finally:
            fm_page.close()

        assert not failures, (
            "Users/Garages vs Facility Management cross-check failed:\n  - "
            + "\n  - ".join(failures)
        )

    # -- Phase 9 ------------------------------------------------------------

    def test_phase_9_message_center(self, kpi_page: Page):
        """Phase 9: Message Center — Inbox headers and columns; stop at 'No Records
        Found', otherwise exercise the filters."""
        kpi = KpiDashboardPage(kpi_page)
        kpi.open_message_center()

        expect(kpi_page.locator('text="Inbox"').first).to_be_visible(timeout=15_000)
        headers = kpi.message_center_headers()
        assert headers[: len(MESSAGE_CENTER_COLUMNS)] == MESSAGE_CENTER_COLUMNS, (
            f"Message Center columns are {headers}, expected {MESSAGE_CENTER_COLUMNS}"
        )
        expect(kpi.show_filters).to_be_visible(timeout=15_000)
        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_09_message_center.png"), full_page=True)

        rows = kpi.message_center_rows()
        if kpi.has_no_records():
            assert not rows, (
                f"Message Center shows 'No Records Found' but the grid still renders "
                f"{len(rows)} row(s): {rows[:3]}"
            )
            print("  [E2E-062] Message Center: 'No Records Found' — stopping here as specified")
            return

        assert rows, "Message Center shows neither data rows nor a 'No Records Found' message"
        print(f"  [E2E-062] Message Center: {len(rows)} row(s); exercising the filters")

        # --- filters ----------------------------------------------------------
        kpi.open_filters()
        filters = kpi.filter_inputs()
        assert filters, "Show Filters did not reveal any filter inputs in the Inbox grid"

        subject_idx = MESSAGE_CENTER_COLUMNS.index("SUBJECT")
        source = next(
            (r[subject_idx] for r in rows if len(r) > subject_idx and r[subject_idx].strip()),
            "",
        )
        assert source, "No non-empty SUBJECT value to filter on"
        token = source.split()[0]

        # Matched to the SUBJECT column by geometry, not list position — the DATE
        # column contributes a Start/End pair, so the Nth input is not the Nth column.
        subject_filter = kpi.filter_input_for("SUBJECT")
        assert subject_filter is not None, (
            f"Could not locate the SUBJECT column's filter input among "
            f"{len(filters)} filter input(s) in the Inbox header"
        )

        subject_filter.fill(token)
        subject_filter.press("Enter")
        kpi_page.wait_for_timeout(3000)
        try:
            kpi_page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass

        filtered = kpi.message_center_rows()
        assert filtered, (
            f"Filtering SUBJECT by {token!r} — a value taken from the live grid — "
            f"returned no rows; the filter appears broken"
        )
        mismatched = [
            r[subject_idx] for r in filtered
            if len(r) > subject_idx and token.lower() not in r[subject_idx].lower()
        ]
        assert not mismatched, (
            f"SUBJECT filter {token!r} returned non-matching row(s): {mismatched[:5]}"
        )
        assert len(filtered) <= len(rows), (
            f"SUBJECT filter {token!r} returned more rows ({len(filtered)}) than the "
            f"unfiltered grid ({len(rows)})"
        )
        print(f"  [E2E-062] Message Center filter SUBJECT={token!r} -> {len(filtered)} row(s)")

        # Clearing the filter must restore the full grid.
        subject_filter.fill("")
        subject_filter.press("Enter")
        kpi_page.wait_for_timeout(3000)
        restored = kpi.message_center_rows()
        assert len(restored) == len(rows), (
            f"Clearing the SUBJECT filter left {len(restored)} row(s), expected the "
            f"original {len(rows)}"
        )
        kpi_page.screenshot(path=str(RESULTS_DIR / "e2e062_10_message_center_filter.png"), full_page=True)
