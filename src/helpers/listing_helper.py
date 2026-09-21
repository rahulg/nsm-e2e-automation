"""Shared VIN-search settling for staff listing pages (LT-260, LT-262).

Two QA timing failures were seen across the E2E-001-style suites (2026-09-14):

  1. The filtered query is slow on large tabs: a fixed sleep after pressing Enter let
     select_application(0) click the first *unfiltered* row — a different record
     (E2E-001 phase 7).
  2. A just-submitted record is not queryable on the first search: E2E-001 phase 2 found
     no row for 90s although phase 1 had saved the LT-260.

How the listing behaves while a VIN query runs (traced live on QA, LT-262 "All" tab,
180k rows): the app shows `.exp-loader-overlay-backdrop` for the whole query (13s for a
hit, ~6s for a miss) and KEEPS THE PREVIOUS ROWS on screen underneath it. A finished
query shows either the matching row(s) or the text "No Records Found".

So "settled" must mean: overlay gone AND (every visible VIN link equals the VIN, with at
least one) OR "No Records Found" — never just "all visible links match", which an
earlier version used and which is vacuously true over a previous EMPTY result. That bug
made the re-search loop restart a 13s query every 3s forever (E2E-006 phase 5 never
found a record that was sitting in the Aging tab).

Both helpers are soft — they never raise — so callers that legitimately expect zero rows
keep their existing behaviour.
"""

import time

from playwright.sync_api import Page

VIN_LINK_SELECTOR = "span.table-link, table a, table td a"

_STATE_JS = """([sel, vin]) => {
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const loading = [...document.querySelectorAll('.exp-loader-overlay-backdrop')].some(vis);
  const links = [...document.querySelectorAll(sel)].filter(vis)
                  .map(e => e.textContent.trim().toUpperCase());
  const want = vin.toUpperCase();
  const noRecords = /No Records? Found/i.test(document.body.innerText || '');
  return {
    loading,
    hit: links.length > 0 && links.every(t => t === want),
    present: links.includes(want),
    empty: links.length === 0 && noRecords,
  };
}"""


def _state(page: Page, vin: str) -> dict:
    return page.evaluate(_STATE_JS, [VIN_LINK_SELECTOR, vin])


def wait_for_vin_filter_applied(page: Page, vin: str, timeout: int = 60_000) -> str:
    """Wait until the VIN query has finished. Soft.

    Returns "hit" (only rows for `vin`), "empty" ("No Records Found") or "timeout".
    The settled state must hold on two reads ~1s apart, so a loader that appears a beat
    after Enter (over stale rows) is not mistaken for a finished query.
    """
    deadline = time.monotonic() + timeout / 1000
    streak = None
    while time.monotonic() < deadline:
        s = _state(page, vin)
        now = None if s["loading"] else ("hit" if s["hit"] else "empty" if s["empty"] else None)
        if now and now == streak:
            return now
        streak = now
        page.wait_for_timeout(1_000)
    print(f"  WARN: listing did not settle on VIN {vin} within {timeout // 1000}s")
    return "timeout"


def vin_link_present(page: Page, vin: str) -> bool:
    return bool(_state(page, vin)["present"])


def wait_for_vin_row(page: Page, search_fn, vin: str, timeout_s: int = 180, poll_ms: int = 5_000) -> bool:
    """Re-run `search_fn(vin)` until a row for `vin` is shown. Soft: returns False on timeout.

    `search_fn` is expected to wait for its own query to finish (the listing pages'
    search_by_vin calls wait_for_vin_filter_applied), so a re-search only ever follows a
    COMPLETED empty result — never interrupts a query still running.
    """
    started = time.monotonic()
    attempts = 0
    while True:
        if wait_for_vin_filter_applied(page, vin, timeout=90_000) == "hit" or vin_link_present(page, vin):
            if attempts:
                print(f"  NOTE: VIN {vin} appeared after {attempts} re-search(es), "
                      f"{time.monotonic() - started:.0f}s")
            return True
        if time.monotonic() - started >= timeout_s:
            print(f"  WARN: VIN {vin} not in listing after {attempts} re-searches / {timeout_s}s")
            return False
        page.wait_for_timeout(poll_ms)
        attempts += 1
        search_fn(vin)
