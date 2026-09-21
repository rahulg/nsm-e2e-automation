"""Staff Portal — the shared form-listing surface (LT-260 / 261 / 262 / 262A / 263).

Every form listing renders the same frame: status tabs across the top (To Process,
Processed, Rejected, …, All), an **insta-filter** strip of day chips underneath
('Today' plus one 'MM/DD/YY' button per recent day), then the record grid with its
own "1 - 10 of 6,734 results" counter.

The existing per-form page objects (``Lt260ListingPage``, ``Lt261Page``, …) model
each form's *workflow* — issue, reject, close, mark stolen. This class deliberately
models only the parts that are identical across all five, so a check that walks every
form doesn't need five near-identical copies of the same three helpers.

Navigation goes through the sidebar link rather than ``page.goto`` on purpose: a
direct URL load re-boots the whole Angular bundle (~15 s a form), while the sidebar
routes in-app.
"""

import os
import re

from playwright.sync_api import Page

from src.config.env import ENV


BASE_PATH = "/pages/ncdot-notice-and-storage"

# Absolute base for the staff app, so a listing can be opened without first loading
# the dashboard and waiting out its sidebar.
SP_BASE = re.sub(r"/login$", BASE_PATH, ENV.STAFF_PORTAL_URL)


def _is_stage() -> bool:
    """Read at call time so this cannot race conftest's NSM_ENV setup."""
    return os.getenv("NSM_ENV", "qa").lower() == "stage"

# "1 - 10 of 6,734 results" — the grid's own record count. Whitespace is generous
# because the parts land on separate lines in innerText.
_RESULT_COUNT_RE = re.compile(
    r"(\d[\d,]*)\s*-\s*(\d[\d,]*)\s*of\s*(\d[\d,]*)\s*results", re.I
)

# The empty state is worded differently per grid — the Payments listing renders
# "No records found." while the Message Center renders "No Records Found". Matching
# case-insensitively (and tolerating the trailing period) is what stops an empty day
# from reading as "count unavailable", which would fail a run on any environment or
# date with no records rather than comparing 0 against 0.
_EMPTY_STATE_RE = re.compile(r"no\s+records?\s+found", re.I)


class FormListingPage:
    """The tabs / insta-filter / record-count frame shared by every form listing.

    ``form_code`` is the listing's own code as it appears in the route and the
    sidebar — 'LT-260', 'LT-261', 'LT-262', 'LT-262A' or 'LT-263'.
    """

    def __init__(self, page: Page, form_code: str):
        self.page = page
        self.form_code = form_code
        self.nav_link = page.locator(f'a[href*="{form_code}/list"]').first
        self.all_tab = page.locator('[role="tab"]:has-text("All")').first

    # -- navigation ---------------------------------------------------------

    def open(self):
        """Open this form's listing and wait until the route is actually this listing.

        In-app routing via the sidebar is used only when the page is already inside
        the staff app — it avoids re-booting the Angular bundle. From a blank page a
        direct URL load is *faster*, not slower: the alternative is loading the
        dashboard first and waiting out its sidebar, which on STAGE alone takes 50-60 s
        and was the direct cause of two phases timing out there.

        The URL is confirmed before returning. Without that, a slow environment can
        leave the previous form's grid on screen and the first count read belongs to
        the wrong listing — seen on STAGE as LT-262's All tab reporting 0 records."""
        self._dismiss_cdk_overlay()
        before = self._grid_signature()
        target = f"{SP_BASE}/{self.form_code}/list"
        if BASE_PATH in (self.page.url or ""):
            try:
                self.nav_link.wait_for(state="visible", timeout=15_000)
                self.nav_link.click(timeout=10_000)
            except Exception:
                self._dismiss_cdk_overlay()
                try:
                    self.nav_link.click(force=True, timeout=5_000)
                except Exception:
                    self.page.goto(target, timeout=90_000)
        else:
            self.page.goto(target, timeout=90_000)

        self.wait_for_route()
        self._settle()
        # Routing in-app swaps the route before the new form's grid arrives, so the
        # previous listing's rows can still be on screen here.
        self._await_grid_refresh(before)

    def wait_for_route(self, timeout_s: int = None):
        """Block until the browser is on this form's listing route."""
        if timeout_s is None:
            timeout_s = 120 if _is_stage() else 45
        needle = f"{self.form_code}/list".lower()
        for _ in range(int(timeout_s / 0.5)):
            if needle in (self.page.url or "").lower():
                return True
            self.page.wait_for_timeout(500)
        return False

    def click_all_tab(self):
        """Open the All tab — the only tab whose count spans every status, and so
        the only one comparable with a Form Status chart's full total."""
        self._dismiss_cdk_overlay()
        self.all_tab.wait_for(state="visible", timeout=20_000)
        before = self._grid_signature()
        try:
            self.all_tab.click(timeout=10_000)
        except Exception:
            self._dismiss_cdk_overlay()
            self.all_tab.dispatch_event("click")
        self._settle()
        self._await_grid_refresh(before)

    def _grid_signature(self):
        """Cheap fingerprint of what the grid is currently showing.

        Combines the record count with the first row's text: either changing means
        the grid has re-queried. Used to tell "this data is settled" apart from "this
        is the *previous* view's data, sitting still because the new one has not
        arrived yet" — a distinction a stability poll alone cannot make."""
        return self.page.evaluate(
            """() => {
                const row = document.querySelector('table tbody tr');
                const body = document.body.innerText || '';
                const m = body.match(/(\\d[\\d,]*)\\s*-\\s*(\\d[\\d,]*)\\s*of\\s*(\\d[\\d,]*)\\s*results/i);
                return (m ? m[0] : 'none') + '||' + (row ? (row.innerText || '').trim() : 'empty');
            }"""
        )

    def _await_grid_refresh(self, previous_signature, timeout_s: int = None):
        """Wait until the grid shows something other than `previous_signature`.

        Falls through when the budget runs out: a filter can legitimately produce the
        same view, so this is a readiness *hint*, not a precondition. What it prevents
        is the opposite error — reading the previous form's rows as if they were this
        one's, which showed up as LT-262 reporting 4 records on a day that has 32."""
        if timeout_s is None:
            timeout_s = 30 if _is_stage() else 12
        for _ in range(int(timeout_s / 0.3)):
            self.page.wait_for_timeout(300)
            if self._grid_signature() != previous_signature:
                return True
        return False

    def tab_labels(self) -> list:
        return [
            t.strip()
            for t in self.page.eval_on_selector_all(
                '[role="tab"]', "els => els.map(e => (e.innerText || '').trim())"
            )
            if t.strip()
        ]

    # -- insta filter -------------------------------------------------------

    def insta_filter_labels(self) -> list:
        """The day chips above the grid, first line only (they carry a count on the
        actionable tabs and are label-only on All)."""
        return [
            t.split("\n")[0].strip()
            for t in self.page.eval_on_selector_all(
                "button.filterBorderBtn-alt",
                "els => els.map(e => (e.innerText || '').trim())",
            )
            if t.strip()
        ]

    def _chip(self, label: str):
        return self.page.locator(
            f'button.filterBorderBtn-alt:has-text("{label}"), button:has-text("{label}")'
        ).first

    def chip_is_disabled(self, label: str) -> bool:
        """Whether a day chip is greyed out.

        The app disables a chip for a day with no records — LT-262A's 'Today' chip is
        disabled while every other form's is live. Callers must check this before
        clicking, otherwise Playwright waits out its full timeout on an element that
        will never become enabled."""
        chip = self._chip(label)
        chip.wait_for(state="visible", timeout=20_000)
        return chip.is_disabled()

    def click_insta_filter(self, label: str):
        """Click an insta-filter chip — 'Today' or a 'MM/DD/YY' day button."""
        self._dismiss_cdk_overlay()
        chip = self._chip(label)
        chip.wait_for(state="visible", timeout=20_000)
        before = self._grid_signature()
        chip.click()
        self._settle()
        self._await_grid_refresh(before)

    # -- column filters -----------------------------------------------------

    def show_filters(self):
        """Reveal the per-column filter row (the grid's 'Show Filters' toggle).

        Listings without insta-filter chips — the Payments grid, for one — expose a
        date range here instead, under the grid's own date column."""
        toggle = self.page.locator(
            'span:has-text("Show Filters"), button:has-text("Show Filters")'
        ).first
        toggle.wait_for(state="visible", timeout=20_000)
        toggle.click()
        self.page.wait_for_timeout(1000)

    def set_date_filter(self, start: str, end: str):
        """Fill the filter row's Start/End date pair (``MM/DD/YYYY``) and apply it."""
        start_input = self.page.locator('input[name="start"]').first
        end_input = self.page.locator('input[name="end"]').first
        start_input.wait_for(state="visible", timeout=20_000)
        before = self._grid_signature()
        start_input.fill(start)
        start_input.press("Tab")
        self.page.wait_for_timeout(600)
        end_input.fill(end)
        end_input.press("Tab")
        self.page.wait_for_timeout(800)
        end_input.press("Enter")
        self._settle()
        self._await_grid_refresh(before)

    # -- record count / grid ------------------------------------------------

    def result_total(self):
        """Total record count the grid reports, or None while it is still rendering.

        Returns 0 for the explicit empty state so callers can compare an empty day
        against a zero chart total instead of special-casing it. The count line is
        checked first: a grid that has rows always shows one, so it settles the
        answer without the empty-state wording having to be exactly right."""
        body = self.page.inner_text("body")
        match = _RESULT_COUNT_RE.search(body)
        if match:
            return int(match.group(3).replace(",", ""))
        return 0 if _EMPTY_STATE_RE.search(body) else None

    def wait_for_result_total(self, tries: int = None, delay: int = 500):
        """Poll until the grid's record count holds steady across three reads.

        The count is re-queried asynchronously after a tab or chip click, so a single
        read can catch the *previous* filter's number and look perfectly valid. The
        budget is larger on STAGE, where a 20 s window was not always enough for the
        grid to produce any count at all — which surfaced as a listing 'reporting'
        None records."""
        if tries is None:
            tries = 120 if _is_stage() else 40
        last, stable = None, 0
        for _ in range(tries):
            current = self.result_total()
            if current is not None and current == last:
                stable += 1
                if stable >= 3:
                    return current
            else:
                stable = 0
            last = current
            self.page.wait_for_timeout(delay)
        return last

    def column_values(self, header: str):
        """Values of the column with the given header, read in one atomic DOM pass.

        Returns None when the listing has no such column. The header is looked up by
        text rather than a hardcoded index — the All tab carries an extra STATUS
        column the actionable tabs do not have, and the columns differ per form."""
        return self.page.evaluate(
            """(header) => {
                const table = document.querySelector('table');
                if (!table) return [];
                const heads = Array.from(table.querySelectorAll('thead th'))
                    .map(th => (th.innerText || '').trim().toUpperCase());
                const idx = heads.indexOf(header.toUpperCase());
                if (idx < 0) return null;
                return Array.from(table.querySelectorAll('tbody tr'))
                    .map(r => Array.from(r.querySelectorAll('td')))
                    .filter(tds => tds.length > idx)
                    .map(tds => (tds[idx].innerText || '').trim())
                    .filter(v => v);
            }""",
            header,
        )

    def column_headers(self) -> list:
        return [
            h.strip()
            for h in self.page.eval_on_selector_all(
                "table thead th", "els => els.map(e => (e.innerText || '').trim())"
            )
            if h.strip()
        ]

    # -- pagination ---------------------------------------------------------

    # The grid renders 10 rows by default; 50 is the largest page size offered
    # ('Show 10' / 'Show 20' / 'Show 50').
    MAX_PAGE_SIZE = 50

    def set_page_size(self, size: int = MAX_PAGE_SIZE):
        """Switch the grid to `size` rows per page. Best-effort: a listing that does
        not offer the option keeps its current size and the caller simply pages more."""
        try:
            selector = self.page.locator('mat-select[aria-label="Page Size"]').first
            selector.click(timeout=10_000)
            self.page.wait_for_timeout(800)
            self.page.locator(f'mat-option:has-text("Show {size}")').first.click(timeout=10_000)
            self._settle()
            self.page.wait_for_timeout(800)
        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass

    def _range_start(self):
        """The 'X' in 'X - Y of N results' — used to detect that a page turn landed."""
        match = _RESULT_COUNT_RE.search(self.page.inner_text("body"))
        return int(match.group(1).replace(",", "")) if match else None

    def _first_row_signature(self):
        """Text of the grid's first data row — the signal that the body re-rendered."""
        return self.page.evaluate(
            """() => {
                const row = document.querySelector('table tbody tr');
                return row ? (row.innerText || '').trim() : null;
            }"""
        )

    def _await_page_turn(self, previous_start, previous_row, timeout_s: int = 16) -> bool:
        """Wait until BOTH the range indicator and the rendered rows have moved on.

        The "X - Y of N results" counter updates before the table body does, so a wait
        on the counter alone returns while the previous page's rows are still on
        screen — which reads that page twice (seen live as a 100-row read of an
        81-row result). Requiring the first row to change as well closes that gap."""
        for _ in range(int(timeout_s / 0.4)):
            self.page.wait_for_timeout(400)
            moved = self._range_start() not in (None, previous_start)
            rerendered = self._first_row_signature() not in (None, previous_row)
            if moved and rerendered:
                return True
        return False

    def first_page(self):
        """Jump back to page 1.

        Applying a new filter does NOT reset the page index: after reading a 2-page
        result the grid stays on page 2, and the next filter's rows are then read from
        page 2 onwards. That silently drops the first page of records — observed as a
        31-of-81 read — so every full-table walk starts here."""
        button = self.page.locator('button[aria-label="First page"]').first
        try:
            if not button.is_visible() or button.is_disabled():
                return
        except Exception:
            return
        previous_start, previous_row = self._range_start(), self._first_row_signature()
        button.click()
        self._settle()
        self._await_page_turn(previous_start, previous_row)

    def next_page(self) -> bool:
        """Advance one page. Returns False when already on the last page."""
        button = self.page.locator('button[aria-label="Next page"]').first
        try:
            if not button.is_visible() or button.is_disabled():
                return False
        except Exception:
            return False
        previous_start, previous_row = self._range_start(), self._first_row_signature()
        button.click()
        self._settle()
        return self._await_page_turn(previous_start, previous_row)

    def collect_columns(self, headers, max_pages: int = 20):
        """Walk every page of the current view and return one row-tuple per record.

        Returns ``(rows, complete)`` — ``complete`` is False when the page budget ran
        out before the grid did, so a caller can tell a short read from a small day.
        Each row is a dict of the requested headers; a header the listing does not
        have maps to None."""
        self.first_page()
        rows, seen_pages, complete = [], 0, True
        while True:
            page_rows = self.page.evaluate(
                """(headers) => {
                    const table = document.querySelector('table');
                    if (!table) return [];
                    const heads = Array.from(table.querySelectorAll('thead th'))
                        .map(th => (th.innerText || '').trim().toUpperCase());
                    const idx = headers.map(h => heads.indexOf(h.toUpperCase()));
                    return Array.from(table.querySelectorAll('tbody tr'))
                        .map(r => Array.from(r.querySelectorAll('td')))
                        .filter(tds => tds.length > 1)
                        .map(tds => {
                            const out = {};
                            headers.forEach((h, i) => {
                                out[h] = idx[i] >= 0 && idx[i] < tds.length
                                    ? (tds[idx[i]].innerText || '').trim() : null;
                            });
                            return out;
                        })
                        // Records can render a blank spacer row under the primary row.
                        .filter(o => Object.values(o).some(v => v));
                }""",
                list(headers),
            )
            rows.extend(page_rows)
            seen_pages += 1
            if seen_pages >= max_pages:
                complete = False
                break
            if not self.next_page():
                break
        return rows, complete

    # -- internals ----------------------------------------------------------

    def _settle(self):
        try:
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass

    def _dismiss_cdk_overlay(self):
        """Dismiss any CDK overlay that would swallow a tab/chip click."""
        try:
            self.page.evaluate(
                """() => {
                    document.querySelectorAll(
                        '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop'
                    ).forEach(b => { b.click(); b.remove(); });
                }"""
            )
            self.page.wait_for_timeout(300)
        except Exception:
            pass
