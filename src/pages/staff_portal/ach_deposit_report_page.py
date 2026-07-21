"""ACH Deposit Report page object (Staff Portal → Reports → ACH Deposit Report).

Synthesized for NCNSS 27258397 ("Filters are not working in ACH Deposit Report").
The report is post-FSD-v1.16: a System Generated Report opened from /reports/list
(the /reports/run/<id> URL is session-scoped and blank on direct navigation — always
click through the list row).

Live-confirmed structure (QA, 2026-07-09):
  Columns: Garage/Individual Name | Garage/Individual Address | Account Type |
           Drawdown Account ID | Amount | Recharge Date | ACH File Transmission Date |
           ACH Transaction ID | ACH File Status
  "Show Filters" toggles a per-column filter row (text inputs; Start/End Date pairs
  for the two date columns; a mat-select for ACH File Status); the button becomes
  "Clear Filters" while filters are shown.
  Results counter: "1 - 10 of N results"; paginator with page-size mat-select.
"""
import re

from playwright.sync_api import Page

REPORTS_LIST_PATH = "/pages/ncdot-notice-and-storage/reports/list"
REPORT_NAME = "ACH Deposit Report"

COLUMNS = [
    "Garage/Individual Name",
    "Garage/Individual Address",
    "Account Type",
    "Drawdown Account ID",
    "Amount",
    "Recharge Date",
    "ACH File Transmission Date",
    "ACH Transaction ID",
    "ACH File Status",
]


class AchDepositReportPage:
    def __init__(self, page: Page, base_url: str):
        self.page = page
        self.base = base_url.rstrip("/")

    # ── navigation ──────────────────────────────────────────────────────────
    def open_reports_list(self):
        self.page.goto(self.base + REPORTS_LIST_PATH, timeout=60_000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        self.page.wait_for_timeout(5_000)

    def report_list_names(self) -> list:
        return self.page.evaluate(
            """() => [...document.querySelectorAll('table tbody tr td:first-child')]
                 .map(e => (e.textContent||'').trim()).filter(t => t)"""
        )

    def open_report(self):
        """reports/list → click the ACH Deposit Report row → report renders.

        Scoped to the System Generated Reports table (th 'REPORT NAME') — a
        'Recent Reports' side panel also lists report names, and clicking those
        rows navigates to a blank session-scoped /reports/run/<id> page.
        """
        self.open_reports_list()
        row = self.page.locator(
            f'table:has(th:has-text("REPORT NAME")) tr:has-text("{REPORT_NAME}")'
        ).first
        row.locator("a, [class*=link], td span").first.click()
        try:
            self.page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        self.page.wait_for_timeout(5_000)
        # the report heading must be visible
        self.page.locator(f'text="{REPORT_NAME}"').first.wait_for(
            state="visible", timeout=15_000
        )

    # ── filters ────────────────────────────────────────────────────────────
    def show_filters(self):
        btn = self.page.locator('button:has-text("Show Filters")')
        if btn.count():
            btn.first.click()
            self.page.wait_for_timeout(2_000)

    def clear_filters(self):
        btn = self.page.locator('button:has-text("Clear Filters")')
        if btn.count():
            btn.first.click()
            self.page.wait_for_timeout(3_000)

    def _column_inputs(self) -> dict:
        """Map every visible filter input/mat-select to its column by x-geometry.

        Returns {column_text: [{tag,id,ph,x,y}, ...]} ordered left-to-right.
        Geometry-based on purpose: the inputs' DOM nesting is unstable across
        builds, but they always sit directly under their column header.
        """
        return self.page.evaluate(
            """() => {
          const vis = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
          const ths = [...document.querySelectorAll('table th')].filter(vis).map(th => {
            const r = th.getBoundingClientRect();
            return {txt:(th.textContent||'').trim(), x:r.x, w:r.width, y:r.y, h:r.height};
          });
          if (!ths.length) return {};
          const headTop = Math.min(...ths.map(t => t.y));
          const headBottom = Math.max(...ths.map(t => t.y + t.h));
          const out = {};
          [...document.querySelectorAll('input, mat-select')].filter(vis).forEach(e => {
            const r = e.getBoundingClientRect();
            // only filter-row inputs: at/below the header top and within the header
            // block (the filter boxes render inside/just under the th row) — this
            // excludes the global header search box and the paginator input.
            if (r.y < headTop - 5 || r.y > headBottom + 60) return;
            const th = ths.find(t => (r.x + r.width/2) >= t.x && (r.x + r.width/2) < (t.x + t.w));
            if (!th) return;
            (out[th.txt] = out[th.txt] || []).push(
              {tag:e.tagName, id:e.id, ph:e.placeholder||'', x:Math.round(r.x), y:Math.round(r.y)});
          });
          for (const k in out) out[k].sort((a,b)=>a.x-b.x || a.y-b.y);
          return out;
        }"""
        )

    def _input_by_id(self, input_id: str):
        return self.page.locator(f"#{input_id}")

    def fill_column_filter(self, column: str, value: str):
        """Type into a text-filter under `column` (applies live / on Enter)."""
        cols = self._column_inputs()
        matches = [c for c in cols if column.lower() in c.lower()]
        assert matches, f"no filter input found under column ~'{column}' (have: {list(cols)})"
        inp = cols[matches[0]][0]
        loc = self._input_by_id(inp["id"])
        loc.click()
        loc.fill("")
        loc.press_sequentially(value, delay=60)
        self.page.wait_for_timeout(1_500)
        # some builds filter live; others need Enter — pressing Enter is harmless
        loc.press("Enter")
        self.page.wait_for_timeout(3_000)

    def _pick_from_open_calendar(self, target):
        """Navigate the open mat-calendar to target (datetime) and click the day."""
        cal = self.page.locator(".mat-calendar").last
        cal.wait_for(state="visible", timeout=10_000)
        want = (target.year, target.month)
        month_names = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                       "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        for _ in range(48):
            hdr = cal.locator(".mat-calendar-period-button").inner_text().strip().upper()
            m = re.search(r"([A-Z]{3,9})\s+(\d{4})", hdr)
            if not m:
                break
            mon = next((i + 1 for i, n in enumerate(month_names) if m.group(1).startswith(n)), None)
            cur = (int(m.group(2)), mon)
            if cur == want:
                break
            if cur < want:
                cal.locator(".mat-calendar-next-button").click()
            else:
                cal.locator(".mat-calendar-previous-button").click()
            self.page.wait_for_timeout(400)
        aria = f"{target.strftime('%B')} {target.day}, {target.year}"
        cal.locator(f'[aria-label="{aria}"]').click()
        self.page.wait_for_timeout(800)

    def set_date_range(self, column: str, start=None, end=None):
        """Set the Start/End Date pair under a date column.

        `start`/`end` are datetime objects (preferred → picked via the material
        datepicker, the way a real user does) or 'MM/DD/YYYY' strings (typed).
        """
        from datetime import datetime as _dt
        cols = self._column_inputs()
        matches = [c for c in cols if column.lower() in c.lower()]
        assert matches, f"no inputs under date column ~'{column}' (have: {list(cols)})"
        pair = cols[matches[0]]
        starts = [i for i in pair if "start" in i["ph"].lower()]
        ends = [i for i in pair if "end" in i["ph"].lower()]
        for val, group in ((start, starts), (end, ends)):
            if val is None or not group:
                continue
            inp = self._input_by_id(group[0]["id"])
            if isinstance(val, _dt):
                # open the datepicker: the toggle button sits inside the same
                # form-field/cell as the input
                toggle = inp.locator("xpath=ancestor::mat-form-field[1]//button").first
                toggle.click()
                self._pick_from_open_calendar(val)
            else:
                inp.click()
                inp.fill("")
                inp.press_sequentially(val, delay=60)
                self.page.wait_for_timeout(400)
                inp.press("Enter")
                self.page.wait_for_timeout(1_000)
                self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(3_000)

    # ── reading results ────────────────────────────────────────────────────
    def results_total(self) -> int:
        """Parse 'x - y of N results'; returns N (0 when no counter/no rows)."""
        txt = self.page.evaluate(
            "() => (document.body.innerText.match(/\\d+\\s*-\\s*\\d+\\s*of\\s*(\\d+)\\s*results/) || [,''])[1]"
        )
        if txt:
            return int(txt)
        return self.visible_row_count()

    def visible_row_count(self) -> int:
        return self.page.evaluate(
            """() => [...document.querySelectorAll('table tbody tr')]
                 .filter(r => (r.textContent||'').trim()).length"""
        )

    def column_values(self, column: str) -> list:
        """Visible cell text for `column` on the current page."""
        return self.page.evaluate(
            """(col) => {
          const ths = [...document.querySelectorAll('table th')];
          const i = ths.findIndex(t => (t.textContent||'').toLowerCase().includes(col.toLowerCase()));
          if (i < 0) return [];
          return [...document.querySelectorAll('table tbody tr')]
            .map(r => r.querySelectorAll('td')[i])
            .filter(Boolean).map(td => (td.textContent||'').trim())
            .filter(t => t);   // drop spacer/empty rows
        }""",
            column,
        )

    def rows_text(self) -> list:
        return self.page.evaluate(
            """() => [...document.querySelectorAll('table tbody tr')]
                 .map(r => (r.textContent||'').trim()).filter(t => t)"""
        )

    def snackbar_text(self) -> str:
        """Visible toast/snackbar text (e.g. 'No records matched for this query')."""
        return self.page.evaluate(
            """() => [...document.querySelectorAll('simple-snack-bar, [class*=snack], [class*=toast], [class*=banner], [role=alert]')]
                 .filter(el => el.offsetWidth || el.offsetHeight)
                 .map(e => (e.textContent||'').trim()).filter(t => t).join(' | ')"""
        )

    def page_error_text(self) -> str:
        """Any visible red/mat-error validation text."""
        return self.page.evaluate(
            """() => [...document.querySelectorAll('mat-error, [class*=error], [class*=invalid]')]
                 .filter(el => el.offsetWidth || el.offsetHeight)
                 .map(e => (e.textContent||'').trim()).filter(t => t).join(' | ')"""
        )

    # ── pagination ─────────────────────────────────────────────────────────
    def current_page_number(self) -> int:
        v = self.page.evaluate(
            """() => {
          const i = [...document.querySelectorAll('input')].find(e => {
            const p = e.closest('[class*=pagin], [class*=pager]');
            return p && e.type !== 'checkbox';
          });
          return i ? i.value : '';
        }"""
        )
        try:
            return int(v)
        except (TypeError, ValueError):
            return 1

    def next_page(self):
        # chevrons: « ‹ [page] › » — click the single-forward one
        btn = self.page.locator(
            '[class*=pagin] button, [class*=pager] button, button[aria-label*="Next" i]'
        )
        candidates = btn.all()
        clicked = False
        for c in candidates:
            label = (c.get_attribute("aria-label") or "") + (c.text_content() or "")
            if "next" in label.lower() or label.strip() in (">", "›"):
                c.click()
                clicked = True
                break
        if not clicked and candidates:
            candidates[-2 if len(candidates) >= 2 else -1].click()
        self.page.wait_for_timeout(3_000)

    # ── downloads ──────────────────────────────────────────────────────────
    def download(self, kind: str):
        """kind: 'PDF' | 'XLSX'. Returns the playwright Download object."""
        opts = self.page.locator('button:has-text("Download Options")').first
        opts.hover()
        self.page.wait_for_timeout(800)
        with self.page.expect_download(timeout=45_000) as dl:
            target = self.page.locator(
                f'span:has-text("{kind}"), button:has-text("{kind}"), '
                f'[class*=menu] :text("{kind}"), [class*=download] :text("{kind}")'
            ).first
            try:
                target.click(timeout=5_000)
            except Exception:
                opts.click()
                self.page.wait_for_timeout(800)
                self.page.locator(f':text("{kind}")').first.click()
        return dl.value
