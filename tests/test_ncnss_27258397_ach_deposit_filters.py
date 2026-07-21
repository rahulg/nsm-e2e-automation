"""
NCNSS 27258397: BUG — Filters are not working in ACH Deposit Report on Staff Portal.

Fix under test (dev: reportById.run step 2): the shared report engine injected
businessIds scoping into EVERY report, so the ACH Deposit Report ignored its filter
criteria and returned unfiltered/incorrect data. Post-fix, businessIds is included
ONLY for the Audit Report. Impacted reports (per dev comment): ACH Deposit Report
AND Audit Report. Fix migrated to QA 2026-07-08.

Scenarios (from ExpertlyTestBuddy plan.json for ticket 27258397):
  PRE  [Critical] staff access + seeded ACH data (read-only checks)
  SC-1 [Critical] filter correctness — the literal defect (TC-01..08)
  SC-2 [High]     filter lifecycle & result surfaces (TC-09..12)
  SC-3 [High]     Audit Report regression — filters + BR-99/100 validations (TC-14, 15)
  TC-16 [High]    RBAC — report visibility per role (OQ-ACH-1: matrix unconfirmed;
                  hard assertion only on Audit staying admin-scoped)

Live-confirmed on QA 2026-07-09 (read-only exploration):
  - Report list (staff/N&S-Admin view) DOES include "ACH Deposit Report".
  - Fiscal view does NOT list it (nor Audit Log) — recorded as OQ-ACH-1 evidence.
  - Filters are per-column (Show Filters toggle); date columns use Start/End pairs.
  - /reports/run/<id> is session-scoped: always click through /reports/list.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext

from src.config.env import ENV
from src.pages.staff_portal.ach_deposit_report_page import AchDepositReportPage
from src.pages.staff_portal.reports_page import ReportsPage

BASE_URL = re.sub(r"/login$", "", ENV.STAFF_PORTAL_URL)
REPORTS_LIST_URL = BASE_URL + "/pages/ncdot-notice-and-storage/reports/list"

# screenshots land in the skill dir so runTestPlan's `glob:screenshots/*.png`
# snapshot strategy embeds them in result.html
SHOTS = (Path(__file__).resolve().parent.parent.parent
         / "skills" / "nsm-ach-deposit-filters" / "screenshots")
SHOTS.mkdir(parents=True, exist_ok=True)

NO_MATCH_TOKEN = "ZZZ-NO-MATCH-27258397"

# Audit Log selectors proven by test_e2e_054
XPATH_AUDIT_FROM = '//input[@aria-label="From Date"]'
XPATH_AUDIT_TO = '//input[@aria-label="To Date"]'
XPATH_AUDIT_GENERATE = '//button[contains(text()," Generate Report ")]'


def _shot(page, name):
    try:
        page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)
    except Exception:
        pass


def _open_report(ctx: BrowserContext) -> tuple:
    page = ctx.new_page()
    rep = AchDepositReportPage(page, BASE_URL)
    rep.open_report()
    rep.show_filters()
    return page, rep


def _poll(read, ok, seconds=12, step=1.5):
    """Poll `read()` until `ok(value)` or timeout; returns the last value."""
    import time
    val = read()
    deadline = time.time() + seconds
    while not ok(val) and time.time() < deadline:
        time.sleep(step)
        val = read()
    return val


def _dates_from(values):
    """Parse MM-DD-YYYY / MM/DD/YYYY prefixes out of cell text."""
    out = []
    for v in values:
        m = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", v)
        if m:
            out.append(datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))))
    return out


@pytest.mark.ncnss27258397
@pytest.mark.report
class TestE2E_NCNSS27258397_PRE_AccessAndData:
    """PRE-1/PRE-2: staff can open the ACH Deposit Report; QA data is rich enough."""

    def test_pre1_staff_opens_ach_deposit_report(self, staff_context):
        page, rep = _open_report(staff_context)
        total = rep.results_total()
        _shot(page, "pre1_report_opened")
        print(f"EXPECTED: ACH Deposit Report opens from Reports list with data | "
              f"ACTUAL: opened, {total} results -> {'MATCH' if total > 0 else 'MISMATCH'}")
        assert total > 0, "ACH Deposit Report opened but has no rows on QA"
        page.close()

    def test_pre2_seeded_data_richness(self, staff_context):
        page, rep = _open_report(staff_context)
        names = set(rep.column_values("Garage/Individual Name"))
        dates = set(d.date() for d in _dates_from(rep.column_values("ACH File Transmission Date")))
        _shot(page, "pre2_data_richness")
        print(f"EXPECTED: >=2 distinct businesses and >=2 distinct dates | "
              f"ACTUAL: {len(names)} names {sorted(names)[:5]}, {len(dates)} dates")
        assert len(names) >= 2, f"need >=2 distinct payer names to discriminate filters, got {names}"
        assert len(dates) >= 2, f"need >=2 distinct transmission dates, got {dates}"
        page.close()


@pytest.mark.ncnss27258397
@pytest.mark.report
class TestE2E_NCNSS27258397_SC1_FilterCorrectness:
    """SC-1: the literal defect — every filter constrains the result set."""

    def test_tc05_business_name_filter(self, staff_context):
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        names = rep.column_values("Garage/Individual Name")
        token = names[0].split()[0]  # e.g. 'ABC' from 'ABC Garage'
        rep.fill_column_filter("Garage/Individual Name", token)
        filtered = rep.results_total()
        vals = rep.column_values("Garage/Individual Name")
        _shot(page, "tc05_name_filter")
        ok = filtered <= baseline and vals and all(token.lower() in v.lower() for v in vals)
        print(f"EXPECTED: only rows whose name contains '{token}', count<=baseline({baseline}) | "
              f"ACTUAL: {filtered} results, names={sorted(set(vals))[:5]} -> {'MATCH' if ok else 'MISMATCH'}")
        assert vals, f"name filter '{token}' returned no rows though baseline had them"
        assert all(token.lower() in v.lower() for v in vals), \
            f"UNFILTERED LEAK (the reported bug): rows not matching '{token}': {set(vals)}"
        assert filtered < baseline or len(set(names)) == 1, \
            f"filter did not narrow results ({filtered} == baseline {baseline})"
        page.close()

    def test_tc06_partial_and_case_insensitive(self, staff_context):
        page, rep = _open_report(staff_context)
        names = rep.column_values("Garage/Individual Name")
        token = names[0].split()[0]
        rep.fill_column_filter("Garage/Individual Name", token.lower())
        vals_lower = rep.column_values("Garage/Individual Name")
        _shot(page, "tc06_case_insensitive")
        ok = bool(vals_lower) and all(token.lower() in v.lower() for v in vals_lower)
        print(f"EXPECTED: lowercase partial '{token.lower()}' still matches (robust match) | "
              f"ACTUAL: {len(vals_lower)} rows -> {'MATCH' if ok else 'MISMATCH (case-sensitive or partial-blind filter)'}")
        assert vals_lower, f"lowercase partial '{token.lower()}' returned nothing — filter is case-sensitive"
        assert all(token.lower() in v.lower() for v in vals_lower)
        page.close()

    def test_tc07_account_type_filter(self, staff_context):
        page, rep = _open_report(staff_context)
        types = set(rep.column_values("Account Type"))
        target = "Individual" if "Individual" in types else sorted(types)[0]
        rep.fill_column_filter("Account Type", target)
        vals = rep.column_values("Account Type")
        _shot(page, "tc07_account_type")
        ok = vals and all(v == target for v in vals)
        print(f"EXPECTED: only Account Type == {target} | ACTUAL: {sorted(set(vals))} "
              f"({len(vals)} rows) -> {'MATCH' if ok else 'MISMATCH'}")
        assert vals, f"Account Type filter '{target}' returned no rows"
        assert all(v == target for v in vals), f"leak: other account types present: {set(vals)}"
        page.close()

    def test_tc08_combined_filters_are_ANDed(self, staff_context):
        page, rep = _open_report(staff_context)
        names = rep.column_values("Garage/Individual Name")
        types = rep.column_values("Account Type")
        # pick a (name-token, type) pair from an actual row so intersection is non-empty
        token, target = names[0].split()[0], types[0]
        rep.fill_column_filter("Garage/Individual Name", token)
        rep.fill_column_filter("Account Type", target)
        vals_n = rep.column_values("Garage/Individual Name")
        vals_t = rep.column_values("Account Type")
        _shot(page, "tc08_combined_and")
        ok = (vals_n and all(token.lower() in v.lower() for v in vals_n)
              and all(v == target for v in vals_t))
        print(f"EXPECTED: rows match BOTH name~'{token}' AND type=={target} (AND semantics) | "
              f"ACTUAL: {len(vals_n)} rows -> {'MATCH' if ok else 'MISMATCH'}")
        assert vals_n, "combined filter returned nothing though a matching row seeded the values"
        assert all(token.lower() in v.lower() for v in vals_n), f"name criterion ignored: {set(vals_n)}"
        assert all(v == target for v in vals_t), f"type criterion ignored: {set(vals_t)}"
        page.close()

    def test_tc03_no_match_gives_empty_not_full_set(self, staff_context):
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        rep.fill_column_filter("Garage/Individual Name", NO_MATCH_TOKEN)
        filtered_rows = rep.visible_row_count()
        total = rep.results_total()
        _shot(page, "tc03_empty_state")
        ok = filtered_rows == 0 or total == 0
        print(f"EXPECTED: 0 rows / empty state (never the full {baseline}-row set) | "
              f"ACTUAL: {filtered_rows} visible rows, counter total={total} -> "
              f"{'MATCH' if ok else 'MISMATCH — pre-fix symptom (full set returned)'}")
        assert ok, (f"PRE-FIX SYMPTOM: non-matching filter returned {filtered_rows} rows "
                    f"(total {total}) instead of an empty state")
        page.close()

    def test_tc01_date_range_returns_only_in_range(self, staff_context):
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        all_dates = _dates_from(rep.column_values("ACH File Transmission Date"))
        assert all_dates, "no parseable ACH File Transmission Dates on page 1"
        pivot = sorted(all_dates)[0]  # earliest visible date
        # bounded range [pivot-1 .. pivot+1]: known to contain pivot-day rows
        # (picked via the datepicker — the real-user path)
        start_dt, end_dt = pivot - timedelta(days=1), pivot + timedelta(days=1)
        start, end = start_dt.strftime("%m/%d/%Y"), end_dt.strftime("%m/%d/%Y")
        rep.set_date_range("ACH File Transmission Date", start=start_dt, end=end_dt)
        banner = rep.snackbar_text()
        vals = _dates_from(rep.column_values("ACH File Transmission Date"))
        total_range = rep.results_total()
        _shot(page, "tc01_date_range")
        no_match = "no records matched" in banner.lower()
        in_range = vals and all(
            pivot.date() - timedelta(days=1) <= d.date() <= pivot.date() + timedelta(days=1)
            for d in vals)
        print(f"EXPECTED (TC-01): rows exist and every row within {start}..{end} | "
              f"ACTUAL: {total_range} results, banner='{banner[:60]}', in_range={bool(in_range)} -> "
              f"{'MATCH' if in_range and not no_match else 'MISMATCH'}")
        assert not no_match, (
            f"date range {start}..{end} reported 'No records matched' though rows dated "
            f"{pivot.date()} exist (baseline {baseline})")
        assert in_range, \
            f"date-range filter leaked out-of-range rows: {set(d.date() for d in vals)}"
        page.close()

    def test_tc01b_recharge_date_range_control(self, staff_context):
        """CONTROL for TC-01/02: the sibling Recharge Date filter must work — proves
        the harness drives date filters correctly and isolates any TC-01/02 failure
        to the ACH File Transmission Date column specifically."""
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        recharge_dates = _dates_from(rep.column_values("Recharge Date"))
        assert recharge_dates, "no parseable Recharge Dates on page 1"
        pivot = sorted(recharge_dates)[-1]
        rep.set_date_range("Recharge Date", start=pivot, end=pivot)
        banner = rep.snackbar_text()
        vals = _dates_from(rep.column_values("Recharge Date"))
        total = rep.results_total()
        _shot(page, "tc01b_recharge_control")
        ok = vals and all(d.date() == pivot.date() for d in vals) and "no records" not in banner.lower()
        print(f"EXPECTED (control): Recharge Date single-day {pivot:%m/%d/%Y} returns only that "
              f"day's rows | ACTUAL: {total} results, dates={sorted(set(d.date() for d in vals))}, "
              f"banner='{banner[:40]}' -> {'MATCH' if ok else 'MISMATCH'}")
        assert ok, "control failed: even Recharge Date filtering is broken (or harness issue)"
        page.close()

    def test_tc02_single_day_range_inclusive_endpoints(self, staff_context):
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        all_dates = _dates_from(rep.column_values("ACH File Transmission Date"))
        assert all_dates, "no parseable ACH File Transmission Dates on page 1"
        pivot = sorted(all_dates)[0]
        day = pivot.strftime("%m/%d/%Y")
        rep.set_date_range("ACH File Transmission Date", start=pivot, end=pivot)
        banner = rep.snackbar_text()
        vals = _dates_from(rep.column_values("ACH File Transmission Date"))
        total_single = rep.results_total()
        _shot(page, "tc02_single_day")
        no_match = "no records matched" in banner.lower()
        # stale-table anomaly: app claims no match but old rows are still rendered
        stale = no_match and rep.visible_row_count() > 0
        ok2 = (not no_match) and vals and all(d.date() == pivot.date() for d in vals)
        print(f"EXPECTED (TC-02): single-day range From=To={day} returns that day's rows "
              f"(inclusive endpoints) | ACTUAL: total={total_single}, banner='{banner[:60]}', "
              f"dates={sorted(set(d.date() for d in vals))}, stale_rows_rendered={stale} -> "
              f"{'MATCH' if ok2 else 'MISMATCH'}")
        if stale:
            print("DEFECT NOTE: on zero-match the table keeps rendering the PREVIOUS result "
                  "set (paginator shows 'of NaN') — only a transient toast signals no-match.")
        assert not no_match, (
            f"ENDPOINT INCLUSIVITY DEFECT: single-day range {day} returned 'No records matched' "
            f"though rows timestamped {pivot.date()} exist — End Date bound appears to be "
            f"midnight-EXCLUSIVE (drops same-day rows with a time component)")
        assert vals and all(d.date() == pivot.date() for d in vals), \
            f"date leak outside {day}: {set(d.date() for d in vals)}"
        page.close()

    def test_tc04_from_after_to_never_returns_full_set(self, staff_context):
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        dates = sorted(_dates_from(rep.column_values("ACH File Transmission Date")))
        hi = (dates[-1] + timedelta(days=30)).strftime("%m/%d/%Y")
        lo = (dates[0] - timedelta(days=30)).strftime("%m/%d/%Y")
        rep.set_date_range("ACH File Transmission Date", start=hi, end=lo)  # Start > End
        rows = rep.visible_row_count()
        err = rep.page_error_text()
        _shot(page, "tc04_from_after_to")
        rejected = bool(err)
        empty = rows == 0
        ok = rejected or empty  # either an explicit validation error OR zero rows
        print(f"EXPECTED (TC-04): Start>End rejected (validation) or yields 0 rows — never the "
              f"full {baseline}-row set | ACTUAL: rows={rows}, validation_error='{err[:80]}' -> "
              f"{'MATCH' if ok else 'MISMATCH — inverted range returned data'}")
        assert ok, (f"inverted range (Start>End) returned {rows} rows and no validation error — "
                    f"filter criteria are being ignored")
        page.close()


@pytest.mark.ncnss27258397
@pytest.mark.report
class TestE2E_NCNSS27258397_SC2_LifecycleAndSurfaces:
    """SC-2: reset, re-search, pagination, and PDF/XLSX export of filtered results."""

    def test_tc09_clear_filters_restores_full_set(self, staff_context):
        page, rep = _open_report(staff_context)
        baseline = rep.results_total()
        names = rep.column_values("Garage/Individual Name")
        rep.fill_column_filter("Garage/Individual Name", names[0].split()[0])
        narrowed = _poll(rep.results_total, lambda v: v < baseline)
        rep.clear_filters()
        restored = _poll(rep.results_total, lambda v: v == baseline)
        _shot(page, "tc09_clear_filters")
        ok = restored == baseline
        print(f"EXPECTED: Clear Filters restores the unfiltered set ({baseline}) | "
              f"ACTUAL: narrowed to {narrowed}, restored to {restored} -> {'MATCH' if ok else 'MISMATCH'}")
        assert ok, f"Clear Filters restored {restored}, expected baseline {baseline}"
        page.close()

    def test_tc10_research_fully_replaces_results(self, staff_context):
        page, rep = _open_report(staff_context)
        names = sorted(set(rep.column_values("Garage/Individual Name")))
        assert len(names) >= 2, "need two distinct names for the re-search check"
        a_tok, b_tok = names[0].split()[0], names[-1].split()[0]
        rep.fill_column_filter("Garage/Individual Name", a_tok)
        rows_a = set(rep.column_values("Garage/Individual Name"))
        rep.fill_column_filter("Garage/Individual Name", b_tok)
        rows_b = rep.column_values("Garage/Individual Name")
        _shot(page, "tc10_research_replace")
        stale = [v for v in rows_b if b_tok.lower() not in v.lower()]
        print(f"EXPECTED: after re-search '{a_tok}'->'{b_tok}', only '{b_tok}' rows (no stale "
              f"'{a_tok}' rows) | ACTUAL: {sorted(set(rows_b))[:5]}, stale={stale[:3]} -> "
              f"{'MATCH' if rows_b and not stale else 'MISMATCH'}")
        assert rows_b, f"re-search with '{b_tok}' returned nothing"
        assert not stale, f"stale rows from the prior filter remained: {stale}"
        page.close()

    def test_tc11_pagination_respects_filter(self, staff_context):
        page, rep = _open_report(staff_context)
        # pick the most frequent account type so the filtered set spans >1 page of 10
        types = rep.column_values("Account Type")
        target = max(set(types), key=types.count)
        rep.fill_column_filter("Account Type", target)
        total = rep.results_total()
        if total <= 10:
            pytest.skip(f"filtered set ({total}) fits one page — pagination not exercisable")
        rep.next_page()
        vals_p2 = rep.column_values("Account Type")
        _shot(page, "tc11_pagination_page2")
        ok = vals_p2 and all(v == target for v in vals_p2)
        print(f"EXPECTED: page 2 of the filtered set still only '{target}' rows | "
              f"ACTUAL: {sorted(set(vals_p2))} -> {'MATCH' if ok else 'MISMATCH'}")
        assert vals_p2, "page 2 empty though the filtered total spans multiple pages"
        assert all(v == target for v in vals_p2), \
            f"pagination dropped the filter: {set(vals_p2)}"
        # filter change must reset to page 1
        rep.fill_column_filter("Garage/Individual Name", "a")
        pg_no = _poll(rep.current_page_number, lambda v: v == 1, seconds=8)
        _shot(page, "tc11_after_filter_change")
        print(f"EXPECTED: filter change resets to page 1 | ACTUAL: page={pg_no} -> "
              f"{'MATCH' if pg_no == 1 else 'MISMATCH'}")
        assert pg_no == 1, f"after filter change the view stayed on page {pg_no}"
        page.close()

    def test_tc12_downloads_contain_filtered_rows(self, staff_context):
        page, rep = _open_report(staff_context)
        names = rep.column_values("Garage/Individual Name")
        token = names[0].split()[0]
        rep.fill_column_filter("Garage/Individual Name", token)
        results = {}
        for kind, suffix in (("PDF", ".pdf"), ("XLSX", ".xlsx")):
            try:
                dl = rep.download(kind)
                path = SHOTS / f"tc12_{dl.suggested_filename}"
                dl.save_as(str(path))
                size = path.stat().st_size
                results[kind] = (dl.suggested_filename, size)
            except Exception as e:
                results[kind] = ("DOWNLOAD FAILED: " + str(e)[:120], 0)
        _shot(page, "tc12_downloads")
        ok = all(size > 0 for _, size in results.values())
        print(f"EXPECTED: PDF + XLSX of the filtered report download non-empty | "
              f"ACTUAL: {results} -> {'MATCH' if ok else 'MISMATCH'}")
        for kind, (fname, size) in results.items():
            assert size > 0, f"{kind} download failed/empty: {fname}"
        page.close()


@pytest.mark.ncnss27258397
@pytest.mark.report
class TestE2E_NCNSS27258397_SC3_AuditRegression:
    """SC-3: the OTHER impacted report — Audit filters still work, validations intact."""

    def _open_audit(self, staff_context):
        page = staff_context.new_page()
        page.goto(REPORTS_LIST_URL, timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=30_000)
        except Exception:
            pass
        page.wait_for_timeout(5_000)
        # scope to the System Generated Reports table — the 'Recent Reports'
        # panel also has 'Audit Log' rows that navigate to a blank page
        page.locator(
            'table:has(th:has-text("REPORT NAME")) tr:has-text("Audit Log")'
        ).first.locator("a, [class*=link], td span").first.click()
        # the Audit form loads behind a long spinner — wait for the actual form
        page.locator(XPATH_AUDIT_FROM).wait_for(state="visible", timeout=90_000)
        page.wait_for_timeout(1_000)
        return page

    def _fill_date(self, page, xpath, value):
        loc = page.locator(xpath)
        loc.wait_for(state="visible", timeout=10_000)
        loc.click()
        loc.fill("")
        loc.press_sequentially(value, delay=80)
        page.wait_for_timeout(300)

    def _select_entity(self, page, entity="LT260"):
        dd = page.locator(
            'mat-select[formcontrolname*="entity" i], mat-select[aria-label*="entity" i], '
            'mat-select[placeholder*="entity" i], mat-select[id*="entity" i], mat-select'
        ).first
        dd.click()
        page.wait_for_timeout(500)
        page.locator(
            f'.cdk-overlay-pane mat-option:has-text("{entity}"), '
            f'.cdk-overlay-pane [role="option"]:has-text("{entity}")'
        ).first.click()
        page.wait_for_timeout(300)

    def _generate(self, page, wait_rows_s: int = 90):
        page.locator(XPATH_AUDIT_GENERATE).first.click(timeout=15_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        # audit queries run behind a long spinner — poll until rows land,
        # 'No Records Found' settles with no spinner, or timeout
        import time
        deadline = time.time() + wait_rows_s
        while time.time() < deadline:
            spinner = page.evaluate(
                """() => !![...document.querySelectorAll('mat-spinner, mat-progress-spinner, [class*=spinner], [class*=loading]')]
                     .find(el => el.offsetWidth || el.offsetHeight)"""
            )
            rows = self._visible_rows(page)
            if rows > 0 or not spinner:
                break
            page.wait_for_timeout(3_000)
        page.wait_for_timeout(2_000)

    def _visible_rows(self, page):
        return page.evaluate(
            """() => [...document.querySelectorAll('table tbody tr')]
                 .filter(r => (r.textContent||'').trim()).length"""
        )

    def _page_errors(self, page):
        return page.evaluate(
            """() => [...document.querySelectorAll('mat-error, [class*=error], simple-snack-bar, [class*=snack]')]
                 .filter(el => el.offsetWidth || el.offsetHeight)
                 .map(e => (e.textContent||'').trim()).filter(t => t).join(' | ')"""
        )

    def test_tc14_audit_filters_still_work(self, staff_context):
        page = self._open_audit(staff_context)
        self._fill_date(page, XPATH_AUDIT_FROM, f"01/01/{datetime.now().year}")
        self._fill_date(page, XPATH_AUDIT_TO, datetime.now().strftime("%m/%d/%Y"))
        self._select_entity(page, "LT260")
        self._generate(page)
        rows = self._visible_rows(page)
        _shot(page, "tc14_audit_filters")
        print(f"EXPECTED: Audit Log with date range + Entity=LT260 returns filtered rows "
              f"(regression: engine change kept audit scoping working) | "
              f"ACTUAL: {rows} rows -> {'MATCH' if rows > 0 else 'MISMATCH'}")
        assert rows > 0, "Audit Log filters returned nothing — regression on the OTHER impacted report"
        page.close()

    def _generate_blocked(self, page) -> bool:
        """True if Generate Report is disabled (a valid guard/rejection signal)."""
        try:
            return page.locator(XPATH_AUDIT_GENERATE).first.is_disabled()
        except Exception:
            return False

    def _fill_garage_name(self, page, value: str):
        """Type into the audit form's GARAGE/INDIVIDUAL NAME input (found under
        its label by geometry; typed with keystrokes so the reactive form
        registers it — plain fill() leaves Generate disabled)."""
        gid = page.evaluate(
            """() => {
          const labs = [...document.querySelectorAll('*')].filter(
            e => (e.textContent||'').trim().toUpperCase()==='GARAGE/INDIVIDUAL NAME'
                 && e.children.length===0);
          if (!labs.length) return null;
          const r = labs[0].getBoundingClientRect();
          const cands = [...document.querySelectorAll('input')]
            .map(i => ({i, b: i.getBoundingClientRect()}))
            .filter(o => Math.abs(o.b.x - r.x) < 80 && o.b.y > r.y && o.b.y < r.y + 90);
          return cands.length ? cands[0].i.id : null;
        }"""
        )
        assert gid, "audit form: GARAGE/INDIVIDUAL NAME input not found"
        loc = page.locator(f"#{gid}")
        loc.click()
        loc.fill("")
        loc.press_sequentially(value, delay=60)
        page.wait_for_timeout(500)

    def test_tc15_audit_validations_intact(self, staff_context):
        # (a) BR-99: range > 6 months must be rejected — with a valid non-date
        # filter present, so a disabled Generate isolates the RANGE guard
        page = self._open_audit(staff_context)
        eight_months_ago = (datetime.now() - timedelta(days=8 * 30)).strftime("%m/%d/%Y")
        self._fill_date(page, XPATH_AUDIT_FROM, eight_months_ago)
        self._fill_date(page, XPATH_AUDIT_TO, datetime.now().strftime("%m/%d/%Y"))
        self._fill_garage_name(page, "ABC")
        blocked = self._generate_blocked(page)
        err_range, rows_after_bad_range = "", 0
        if not blocked:
            try:
                self._generate(page, wait_rows_s=45)
            except Exception as e:
                err_range = f"generate click failed: {str(e)[:80]}"
            err_range = (err_range + " " + self._page_errors(page)).strip()
            rows_after_bad_range = self._visible_rows(page)
        _shot(page, "tc15_br99_six_months")
        br99_ok = blocked or bool(err_range) or rows_after_bad_range == 0
        print(f"EXPECTED (BR-99): >6-month range rejected | "
              f"ACTUAL: generate_disabled={blocked}, error='{err_range[:100]}', "
              f"rows={rows_after_bad_range} -> {'MATCH' if br99_ok else 'MISMATCH'}")
        page.close()

        # (b) BR-100: date-only search (no non-date filter) must be rejected
        page2 = self._open_audit(staff_context)
        self._fill_date(page2, XPATH_AUDIT_FROM, f"01/01/{datetime.now().year}")
        self._fill_date(page2, XPATH_AUDIT_TO, datetime.now().strftime("%m/%d/%Y"))
        blocked2 = self._generate_blocked(page2)
        err_mandatory, rows_dateonly = "", 0
        if not blocked2:
            try:
                self._generate(page2, wait_rows_s=45)
            except Exception as e:
                err_mandatory = f"generate click failed: {str(e)[:80]}"
            err_mandatory = (err_mandatory + " " + self._page_errors(page2)).strip()
            rows_dateonly = self._visible_rows(page2)
        _shot(page2, "tc15_br100_mandatory_filter")
        br100_ok = blocked2 or bool(err_mandatory) or rows_dateonly == 0
        print(f"EXPECTED (BR-100): date-only search rejected (>=1 non-date filter mandatory) | "
              f"ACTUAL: generate_disabled={blocked2}, error='{err_mandatory[:100]}', "
              f"rows={rows_dateonly} -> {'MATCH' if br100_ok else 'MISMATCH'}")
        page2.close()
        assert br99_ok, "BR-99 violated: >6-month audit range was accepted"
        assert br100_ok, "BR-100 violated: date-only audit search executed without a mandatory filter"


@pytest.mark.ncnss27258397
@pytest.mark.rbac
class TestE2E_NCNSS27258397_TC16_RBAC:
    """TC-16: report visibility per role. HARD assertion only where the matrix is
    confirmed (Audit Log = N&S-Admin-scoped, absent for Fiscal). The ACH Deposit
    Report's intended role row is UNCONFIRMED (OQ-ACH-1) — observed behavior is
    recorded, not fail-asserted."""

    def _list_reports(self, ctx):
        page = ctx.new_page()
        rep = AchDepositReportPage(page, BASE_URL)
        rep.open_reports_list()
        names = rep.report_list_names()
        return page, names

    def test_tc16_role_visibility(self, staff_context, fiscal_context):
        s_page, staff_reports = self._list_reports(staff_context)
        _shot(s_page, "tc16_staff_report_list")
        f_page, fiscal_reports = self._list_reports(fiscal_context)
        _shot(f_page, "tc16_fiscal_report_list")

        staff_sees_ach = any("ACH Deposit" in n for n in staff_reports)
        fiscal_sees_ach = any("ACH Deposit" in n for n in fiscal_reports)
        fiscal_sees_audit = any("Audit" in n for n in fiscal_reports)

        print(f"EXPECTED: staff(N&S Admin) sees ACH Deposit Report; Audit Log absent for Fiscal; "
              f"no data/privilege leak from the businessIds change | "
              f"ACTUAL: staff_sees_ach={staff_sees_ach}, fiscal_sees_ach={fiscal_sees_ach} "
              f"(OQ-ACH-1: recorded, matrix unconfirmed), fiscal_sees_audit={fiscal_sees_audit} -> "
              f"{'MATCH' if staff_sees_ach and not fiscal_sees_audit else 'MISMATCH'}")
        print(f"OBSERVED fiscal report list: {fiscal_reports}")
        assert staff_sees_ach, "N&S Admin no longer sees the ACH Deposit Report"
        assert not fiscal_sees_audit, "LEAK: Fiscal user can see the Audit Log report"
        s_page.close()
        f_page.close()
