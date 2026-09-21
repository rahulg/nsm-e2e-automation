"""Staff Portal — Messages/Home page (KPI Dashboard + Message Center tabs).

The Messages/Home page is the staff dashboard landing page. It carries two Material
tabs:

  * **KPI Dashboard** — seven summary counters plus twelve chart widgets. Every chart
    is a **Chart.js v2** canvas, so the *rendered* series is readable straight off
    ``window.Chart.instances`` (``Chart.getChart`` does not exist in v2). Reading the
    live chart config — instead of OCR-ing the canvas or trusting a screenshot — is
    what makes "is the graph correct?" an assertable question: labels, dataset values
    and chart type all come back as real data.
  * **Message Center** — an Inbox grid (SUBJECT / DATE / MESSAGE) with a Show Filters
    toggle.

Two DOM facts drive the design here:

1. **Widget controls have randomised ``name`` attributes.** The date pickers are named
   ``__date_field110709_637904_752683`` and friends — regenerated on every render — so
   nothing can be selected by name. Widgets are therefore located by their ``<h5>``
   title and everything else (date inputs, canvas, mat-select) is resolved *within*
   that card, positionally: the first datepicker input is START DATE, the second is
   END DATE.

2. **A filter change destroys and recreates the Chart instance.** The instance id
   changes (observed 38 -> 51 on a single date apply, since all twelve widgets
   re-render together). :meth:`KpiDashboardPage.set_date_range` uses that id churn as
   the readiness signal rather than a fixed sleep.

The year control on 'Count of Public Users/Garages' is a masked numeric field where
Playwright's ``fill()`` *appends* rather than replaces ("2026" + "2025" -> "20262025",
which silently leaves the chart on its old year). :meth:`set_year` clears it with
Ctrl+A/Delete and types instead.
"""

import os
import re

from playwright.sync_api import Page, expect

from src.config.env import ENV


def _is_stage() -> bool:
    """Read at call time so this cannot race conftest's NSM_ENV setup."""
    return os.getenv("NSM_ENV", "qa").lower() == "stage"


SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)

# The twelve chart widgets on the KPI Dashboard, in render order.
PAPER_VS_DIGITAL_WIDGETS = [
    "LT-260 - Paper vs. Digital Submissions",
    "LT-262 - Paper vs. Digital Submissions",
    "LT-263 - Paper vs. Digital Submissions",
    "LT-262A - Paper vs. Digital Submissions",
]
FORM_STATUS_WIDGETS = [
    "Form Status - LT-260",
    "Form Status - LT-262",
    "Form Status - LT-263",
    "Form Status - LT-261",
    "Form Status - LT-262A",
]
PAYMENT_WIDGETS = [
    "Transaction Volume by Payment Type",
    "Amount Collected by Payment Type",
]
USERS_GARAGES_WIDGET = "Count of Public Users/Garages"

ALL_WIDGETS = (
    PAPER_VS_DIGITAL_WIDGETS
    + FORM_STATUS_WIDGETS
    + [USERS_GARAGES_WIDGET]
    + PAYMENT_WIDGETS
)

# Every widget that exposes a DATE RANGE (START DATE / END DATE) pair.
DATE_RANGE_WIDGETS = PAPER_VS_DIGITAL_WIDGETS + FORM_STATUS_WIDGETS + PAYMENT_WIDGETS

# Summary counters above the charts.
SUMMARY_HEADERS = [
    "Count of LT-260s",
    "Count of LT-262s",
    "Count of LT-263s",
    "Count of LT-261s",
    "Count of LT-262As",
    "Successful Payments Collected",
    "Amount Successfully Collected",
]

MESSAGE_CENTER_COLUMNS = ["SUBJECT", "DATE", "MESSAGE"]

# ---------------------------------------------------------------------------
# Browser-side helpers. Kept as module constants so the same locate-the-card
# logic is shared by every reader/writer below.
# ---------------------------------------------------------------------------

# Find the widget card: the <h5> whose text is exactly `title`, then climb to the
# nearest ancestor that also contains the widget's canvas.
#
# The slow path scans every leaf element on a very large Angular page, and the
# re-render wait polls this many times per filter apply — so a resolved card is
# stamped with a data attribute and re-used. The stamp is re-validated on each hit
# (still attached, still owns a canvas) and falls back to the scan when Angular has
# swapped the node out.
_FIND_CARD = """
    const findCard = (title) => {
        const cached = document.querySelector('[data-e2e-kpi-widget="' + title + '"]');
        if (cached && cached.isConnected && cached.querySelector('canvas')) return cached;
        const h = Array.from(document.querySelectorAll('h5, h4, h3, h6, div, span, p'))
            .find(e => e.children.length === 0 && (e.textContent || '').trim() === title);
        if (!h) return null;
        let card = h;
        for (let i = 0; i < 15 && card.parentElement; i++) {
            card = card.parentElement;
            if (card.querySelector('canvas')) {
                card.setAttribute('data-e2e-kpi-widget', title);
                return card;
            }
        }
        return null;
    };
"""

# Resolve the Chart.js v2 instance bound to a card's canvas.
_FIND_CHART = _FIND_CARD + """
    const findChart = (title) => {
        const card = findCard(title);
        if (!card) return null;
        const cv = card.querySelector('canvas');
        if (!cv || !window.Chart || !window.Chart.instances) return null;
        return Object.values(window.Chart.instances).find(i => i.canvas === cv) || null;
    };
"""

_READ_CHART_JS = "(title) => {" + _FIND_CHART + """
    const ch = findChart(title);
    if (!ch) return null;
    const cfg = ch.config || {};
    const d = cfg.data || {};
    const ds = d.datasets || [];
    return {
        id: ch.id,
        type: cfg.type,
        labels: (d.labels || []).map(l => String(l)),
        data: ds.length ? ds[0].data.map(Number) : [],
        datasetCount: ds.length,
    };
}"""

_CARD_HANDLE_JS = "(title) => {" + _FIND_CARD + " return findCard(title); }"

_CHART_COUNT_JS = (
    "() => (window.Chart && window.Chart.instances)"
    " ? Object.keys(window.Chart.instances).length : 0"
)


class KpiDashboardPage:
    """Messages/Home — KPI Dashboard widgets and the Message Center inbox."""

    def __init__(self, page: Page):
        self.page = page
        self.kpi_tab = page.locator('[role="tab"]:has-text("KPI Dashboard")').first
        self.message_center_tab = page.locator('[role="tab"]:has-text("Message Center")').first
        self.show_filters = page.locator(
            'span:has-text("Show Filters"), button:has-text("Show Filters")'
        ).first

    # -- navigation ---------------------------------------------------------

    def goto(self):
        """Open Messages/Home and wait for the KPI charts to finish rendering."""
        self.page.goto(SP_DASHBOARD_URL, timeout=90_000)
        # networkidle is only a settle hint — the Angular bundle keeps background
        # traffic alive well past the default budget on the slower environments.
        # wait_for_charts() below is the real readiness gate.
        try:
            self.page.wait_for_load_state("networkidle", timeout=45_000)
        except Exception:
            pass
        self.wait_for_app_boot()
        self.wait_for_charts()

    def wait_for_app_boot(self, timeout_s: int = None) -> bool:
        """Ride out a cold environment that is still serving its boot page.

        A non-prod environment that has scaled to zero answers every request with a
        'Server Starting' holding page — HTTP 200, so nothing looks broken until an
        assertion reports a page title nobody expected. Reloading periodically lets a
        cold start finish; :meth:`is_booting` lets the caller skip cleanly if it does
        not, instead of every phase failing with a different confusing symptom."""
        if timeout_s is None:
            timeout_s = 300 if _is_stage() else 120
        deadline = timeout_s
        while deadline > 0:
            if not self.is_booting():
                return True
            self.page.wait_for_timeout(15_000)
            deadline -= 15
            try:
                self.page.reload(timeout=90_000)
                self.page.wait_for_load_state("networkidle", timeout=45_000)
            except Exception:
                pass
        return not self.is_booting()

    def is_booting(self) -> bool:
        """Whether the environment is serving its 'Server Starting' holding page."""
        try:
            return "server starting" in (self.page.title() or "").strip().lower()
        except Exception:
            return False

    def wait_for_charts(self, expected: int = len(ALL_WIDGETS), timeout_s: int = None) -> int:
        """Poll until every KPI chart has been constructed.

        Chart construction lags the page load badly and unevenly — runs against QA
        showed zero charts at 9 s and all twelve by 12 s. Anything reading chart data
        before this returns sees an empty dashboard and reports a bogus 'widget
        missing' failure.

        The budget is larger on STAGE, where the Angular bundle boots far slower (the
        sidebar alone takes 50-60 s there against ~2 s on QA — see
        ``dashboard_page._sidebar_timeout_ms``). Polling returns as soon as the charts
        exist, so the larger budget costs a healthy run nothing."""
        if timeout_s is None:
            timeout_s = 180 if _is_stage() else 90
        count = 0
        for _ in range(timeout_s):
            count = self.page.evaluate(_CHART_COUNT_JS)
            if count >= expected:
                return count
            self.page.wait_for_timeout(1000)
        return count

    def open_kpi_dashboard(self):
        self.kpi_tab.click()
        self.page.wait_for_timeout(1500)
        self.wait_for_charts()

    def open_message_center(self):
        """Open the Message Center tab and wait for the Inbox to settle.

        The grid's header renders before its contents, so waiting on the header alone
        returns while the body is still empty — indistinguishable from a genuinely
        empty inbox. This waits for the grid to resolve one way or the other: at least
        one row, or the explicit empty state."""
        self.message_center_tab.click()
        self.page.wait_for_timeout(1500)
        try:
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        self.page.locator('table thead th:has-text("SUBJECT")').first.wait_for(
            state="visible", timeout=60_000
        )
        budget = 120 if _is_stage() else 45
        for _ in range(budget * 2):
            if self.has_no_records() or self.message_center_rows():
                return
            self.page.wait_for_timeout(500)

    # -- widget reads -------------------------------------------------------

    def widget_exists(self, title: str) -> bool:
        return self.page.evaluate(_CARD_HANDLE_JS, title) is not None

    def chart(self, title: str) -> dict:
        """Return the widget's live Chart.js series: ``{id, type, labels, data}``.

        Raises AssertionError when the widget or its chart cannot be resolved — that
        is a real failure (missing/blank widget), not a condition to paper over."""
        snap = self.page.evaluate(_READ_CHART_JS, title)
        assert snap is not None, (
            f"KPI widget {title!r} has no resolvable Chart.js instance — the widget is "
            f"missing or its chart never rendered"
        )
        return snap

    def chart_total(self, title: str) -> float:
        return sum(self.chart(title)["data"])

    def _card(self, title: str):
        handle = self.page.evaluate_handle(_CARD_HANDLE_JS, title)
        element = handle.as_element()
        assert element is not None, f"KPI widget card {title!r} not found on the page"
        return element

    # -- widget controls ----------------------------------------------------

    def set_date_range(self, title: str, start: str, end: str) -> dict:
        """Type START DATE / END DATE (``MM/DD/YYYY``) into a widget and wait for the
        re-render. Returns the refreshed chart snapshot.

        Both inputs are ordinary mat-datepicker text inputs, so ``fill()`` replaces
        cleanly (unlike the masked year field — see :meth:`set_year`)."""
        before = self.chart(title)["id"]
        card = self._card(title)
        inputs = card.query_selector_all("input.mat-datepicker-input")
        assert len(inputs) >= 2, (
            f"Widget {title!r} should expose START DATE and END DATE inputs, "
            f"found {len(inputs)}"
        )
        inputs[0].fill(start)
        inputs[0].press("Tab")
        self.page.wait_for_timeout(400)
        inputs[1].fill(end)
        inputs[1].press("Tab")
        self._wait_for_rerender(title, before)
        return self.chart(title)

    def date_range_values(self, title: str) -> list:
        """The widget's START/END date inputs as text — empty strings when unfiltered.

        A pure DOM read with no server round trip, so it is the cheap way to ask
        "is this widget already unfiltered?" before paying for a clear."""
        card = self._card(title)
        return [
            (inp.input_value() or "").strip()
            for inp in card.query_selector_all("input.mat-datepicker-input")[:2]
        ]

    def is_date_range_clear(self, title: str) -> bool:
        return not any(self.date_range_values(title))

    def clear_date_range(self, title: str) -> dict:
        before = self.chart(title)["id"]
        card = self._card(title)
        for inp in card.query_selector_all("input.mat-datepicker-input")[:2]:
            inp.fill("")
            inp.press("Tab")
            self.page.wait_for_timeout(300)
        self._wait_for_rerender(title, before)
        return self.chart(title)

    def set_year(self, title: str, year: int) -> dict:
        """Set the YEAR control on 'Count of Public Users/Garages'.

        ``fill()`` appends on this masked numeric field, so the value is cleared with
        Ctrl+A/Delete and typed. Getting this wrong is silent: the field ends up
        holding '20262025' and the chart simply keeps its previous year's data."""
        before = self.chart(title)["id"]
        card = self._card(title)
        visible = [i for i in card.query_selector_all("input") if i.is_visible()]
        assert visible, f"Widget {title!r} exposes no visible YEAR input"
        year_input = visible[0]
        year_input.click()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.press("Delete")
        self.page.wait_for_timeout(300)
        self.page.keyboard.type(str(year), delay=80)
        self.page.keyboard.press("Tab")
        self._wait_for_rerender(title, before)
        return self.chart(title)

    def year_value(self, title: str) -> str:
        card = self._card(title)
        visible = [i for i in card.query_selector_all("input") if i.is_visible()]
        return visible[0].input_value() if visible else ""

    def select_type(self, title: str, option: str) -> dict:
        """Pick a TYPE option ('Facilities' / 'Public Portal Users') on the
        Count of Public Users/Garages widget."""
        before = self.chart(title)["id"]
        card = self._card(title)
        select = card.query_selector("mat-select")
        assert select is not None, f"Widget {title!r} exposes no TYPE dropdown"
        select.click()
        self.page.wait_for_timeout(1000)
        self.page.locator(f'mat-option:has-text("{option}")').first.click()
        self._wait_for_rerender(title, before)
        return self.chart(title)

    def selected_type(self, title: str) -> str:
        card = self._card(title)
        trigger = card.query_selector("mat-select-trigger")
        return (trigger.inner_text() if trigger else "").strip()

    def type_options(self, title: str) -> list:
        card = self._card(title)
        card.query_selector("mat-select").click()
        self.page.wait_for_timeout(1000)
        options = [
            (o.inner_text() or "").strip()
            for o in self.page.locator("mat-option").all()
        ]
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)
        return options

    def _wait_for_rerender(self, title: str, previous_id, timeout_s: int = 25):
        """Wait for the widget's Chart instance to be replaced and then settle.

        A filter apply destroys the old Chart and builds a new one, so a changed
        instance id is the signal that the *new* series is on screen. Two settle
        reads guard against sampling between the two re-renders a start+end pair
        triggers. If the id never changes (the backend returned an identical view)
        the wait falls through after the budget rather than failing — the caller's
        assertions decide whether that is correct."""
        stable = 0
        current = previous_id
        for _ in range(int(timeout_s / 0.3)):
            self.page.wait_for_timeout(300)
            snap = self.page.evaluate(_READ_CHART_JS, title)
            if snap is None:
                stable = 0
                continue
            if snap["id"] == previous_id:
                continue
            if snap["id"] == current:
                stable += 1
                if stable >= 3:
                    return
            else:
                current = snap["id"]
                stable = 1

    # -- Message Center -----------------------------------------------------

    def message_center_headers(self) -> list:
        return [
            (th or "").strip()
            for th in self.page.eval_on_selector_all(
                "table thead th", "els => els.map(e => (e.innerText || '').trim())"
            )
        ]

    def message_center_rows(self) -> list:
        """Inbox grid as a 2D list of cell texts, read in one atomic DOM pass.

        Cell-by-cell locator reads race the grid's async re-render (a row can detach
        mid-iteration and block on Playwright's auto-wait); one evaluate() snapshots
        a consistent view with no waiting."""
        return self.page.evaluate(
            """() => {
                const t = document.querySelector('table');
                if (!t) return [];
                return Array.from(t.querySelectorAll('tr'))
                    .filter(r => r.querySelector('td'))
                    .map(r => Array.from(r.querySelectorAll('td'))
                        .map(td => (td.innerText || '').trim()));
            }"""
        )

    def has_no_records(self) -> bool:
        """Whether the Inbox is showing its empty state.

        Matched case-insensitively: the grids in this app do not agree on the wording
        ('No Records Found' here, 'No records found.' on the Payments listing)."""
        return bool(
            re.search(r"no\s+records?\s+found", self.page.inner_text("body"), re.I)
        )

    def open_filters(self):
        expect(self.show_filters).to_be_visible(timeout=15_000)
        self.show_filters.click()
        self.page.wait_for_timeout(1500)

    def filter_inputs(self) -> list:
        """Filter inputs exposed inside the grid header once filters are shown."""
        return self.page.locator("table thead input").all()

    def filter_input_for(self, column: str):
        """The filter input sitting under a named column, or None.

        Filter inputs cannot be addressed by list position: the DATE column renders a
        Start/End pair, so the Nth input is not the Nth column. Each input is instead
        matched to the column it is horizontally aligned with, using the header cell's
        own bounding box — which survives extra date inputs, leading checkbox columns
        and any future column order."""
        target = self.page.locator(f'table thead th:has-text("{column}")').first
        try:
            box = target.bounding_box()
        except Exception:
            return None
        if not box:
            return None
        best, best_gap = None, None
        for candidate in self.filter_inputs():
            try:
                cbox = candidate.bounding_box()
            except Exception:
                continue
            if not cbox:
                continue
            centre = cbox["x"] + cbox["width"] / 2
            if not (box["x"] <= centre <= box["x"] + box["width"]):
                continue
            gap = abs(centre - (box["x"] + box["width"] / 2))
            if best_gap is None or gap < best_gap:
                best, best_gap = candidate, gap
        return best
