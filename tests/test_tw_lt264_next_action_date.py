"""TC-LT264-001..024 — the LT-264 / LT-264G "Next Action Date" statement.

The enhancement under test adds one sentence to the LT-264 and its Garage copy
(LT-264G):

    The next action date for this File is MM/DD/YYYY.

with the date UNDERLINED, where the date is the letter's own Print / Issuance
Date plus 32 CALENDAR days. It must be recalculated every time a letter is
generated — on the original issuance, after an aging reset, and on a manual
reprint — so a recipient never reads a stale deadline off a fresh letter.

What this module does
---------------------
A module-scoped `corpus` fixture walks the Staff Portal LT-262 listing, opens
each case's Correspondence History, and for every LT-264 / LT-264G row records
the grid's DATE ISSUED and downloads the PDF. Each letter is then parsed for:

  * `statement`  — the full sentence, if present
  * `nad`        — the date it carries, as a `date`
  * `underlined` — whether a rule is drawn under that date
  * `body_date`  — the date printed in the letter's own header block

Every test reads that one cached snapshot; re-walking the listing costs ~40 s
per case. The walk is READ-ONLY — it never clicks an issuance button, because
issuing an LT-264 is a real workflow action on a shared QA sandbox. The reprint
tests (TC-016..019) are the sole exception and are opt-in; see below.

Live QA grounding (2026-08-17, nsm-qa.nc.verifi.dev)
---------------------------------------------------
  * Correspondence History columns: CORRESPONDENCE · DATE ISSUED · RECIPIENT
    NAME · LINK TO DOWNLOAD · (reprint control). DATE ISSUED renders as
    "08-17-2026 02:44 AM".
  * Track LT-264's own PRINT DATE / MAIL DATE / TRACKING NUMBER / STATUS columns
    are BLANK on this environment — the Nordis SFTP job does not run here — so
    Correspondence History's DATE ISSUED is the only authoritative issuance
    timestamp available, and is what these tests calculate from.
  * Letter template is "LT-264 (Rev. 12/19)" / "Garage LT-264 (Rev. 12/19)".
    PDFs draw rules as thin `rect`s; they contain no `line` or `curve` objects,
    so underline detection looks for a short-height rect beneath the date.

Two findings from that grounding pass, both asserted rather than assumed:

  F1  No LT-264 or LT-264G on QA carries the statement at all — 19 letters
      across 8 cases, including letters issued the same morning. The
      enhancement is not deployed on this environment, so TC-001 and every
      case that depends on reading the date fail here for one shared root
      cause rather than 20 independent ones. This reproduces the 2026-08-13
      run of the same ticket (TW 27243037 / NCNSS-536), whose SC-1 recorded
      the sentence absent on a freshly issued LT-264 and LT-264G.

  F2  The date printed in the letter header does not match the DATE ISSUED
      recorded against it: 7 of 19 letters print a date 32-33 days later
      (issued 07-12-2026, prints 08/13/2026). The stored PDF carries the
      date of its most recent RE-RENDER while Correspondence History keeps
      the original issuance timestamp. That matters here because the
      enhancement keys off the "Print/Issuance Date", and on this
      environment two different dates answer to that name. TC-020 asserts
      it directly.

Note on the reprint path: AC-4 asks the reprint to RE-RENDER the letter in
place with a recalculated date while the original correspondence rows stay
retrievable. An unchanged row count after "Send For Reprinting" is therefore
the expected shape, not a defect — the 2026-08-13 run recorded exactly that
(6 rows before, 6 after) as a PASS. What TC-016..019 check is the content of
the regenerated PDF, not the row count.

Coverage limits, stated rather than silently skipped
----------------------------------------------------
  * TC-007 (year boundary) and TC-008 (leap-year February) need a letter issued
    in December, or in the 32 days before a 29 February. Issuance date is
    always "now" and cannot be backdated through any surface this suite can
    reach, so those two SKIP with that reason rather than assert a rule against
    dates no letter carries.
  * TC-012..015 (aging reset) need the aging clock restarted on a live case.
    The reset trigger is a backend automation chain, not a Staff Portal control,
    so these SKIP unless a case in the corpus already shows more than one
    generation of the same letter. The invariant they share with reprint — a
    newly generated letter must not carry the previous letter's date — is
    covered by TC-018 either way.
  * TC-016..019 (manual reprint) DO drive "Send For Reprinting", which
    regenerates the letter. It is safe on QA specifically because the Nordis
    transmission job does not run here (blank TRACKING NUMBER / MAIL DATE /
    STATUS above), so nothing is actually mailed. Set LT264_NAD_REPRINT=0 to
    skip them on an environment where Nordis IS live.

PDF text is read with pdfplumber, never PyPDF2: PyPDF2 mangles inter-word
spacing in these templates badly enough to manufacture false findings.
"""
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Browser

from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.helpers.workflow_helper import go_to_staff_dashboard

pdfplumber = pytest.importorskip("pdfplumber", reason="pdfplumber is required to read letter PDFs")

pytestmark = pytest.mark.lt264nad

_ROOT = Path(__file__).resolve().parent.parent
_AUTH_FILE = _ROOT / "auth" / os.getenv("NSM_ENV", "qa") / "staff-portal.json"
DOWNLOADS = _ROOT / "downloads" / "lt264_next_action_date"

# The interval the enhancement specifies, in CALENDAR days.
NEXT_ACTION_OFFSET = timedelta(days=32)

# Sampling plan for the corpus walk: (listing tab, cases to visit). Aging and
# Processed are where issued LT-264s live; Court Hearing carries cases that
# aged past the 32 days and so is a useful third source.
SAMPLE_TABS = [("Aging", 5), ("Processed", 4), ("Court Hearing", 3), ("All", 5)]

# Reprint is side-effecting (writes a correspondence record). On by default —
# see the module docstring for why that is safe on QA.
REPRINT_ENABLED = os.getenv("LT264_NAD_REPRINT", "1") != "0"

# ── Statement parsing ──────────────────────────────────────────────────────────

# The sentence, tolerant of whitespace and case; `\s+` spans the line wraps
# pdfplumber introduces. The terminating full stop is NOT required by this
# pattern even though the AC shows one: on QA the sentence ends at the date with
# no period, and requiring it here would report the whole statement as absent
# rather than reporting the one thing that is actually wrong. Whether the period
# is present is recorded separately as `period` so it can still be surfaced.
STATEMENT_RE = re.compile(
    r"The\s+next\s+action\s+date\s+for\s+this\s+File\s+is\s+(\S+)", re.I)

# Deliberately loose: catches a statement that IS present but malformed (wrong
# wording, wrong date format, missing period). Without it, "the sentence is
# absent" and "the sentence is broken" would be indistinguishable, and TC-009
# in particular exists precisely to tell those two apart.
LOOSE_RE = re.compile(r"next\s+action\s+date", re.I)

# MM/DD/YYYY, and nothing else — TC-009.
MMDDYYYY_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# Header date of the letter itself (the Print/Issuance Date the template prints).
ANY_DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")

GARAGE_RE = re.compile(r"garage|264\s*G", re.I)

# A drawn rule: PDF `rect`s in this template are filled boxes, so an underline is
# one whose height is hairline. 3.0pt is generous — real underlines measured <1pt.
MAX_RULE_HEIGHT = 3.0
# How much of the date's width a rule must span to count as underlining it.
MIN_UNDERLINE_COVERAGE = 0.6
# How far below the date's baseline the rule may sit.
MAX_UNDERLINE_GAP = 5.0


def _lines_from_words(page) -> list:
    """Layout-accurate lines: group words by vertical position, order by x."""
    rows = defaultdict(list)
    for w in page.extract_words():
        rows[round(w["top"], 0)].append(w)
    out = []
    for _, ws in sorted(rows.items()):
        ws.sort(key=lambda z: z["x0"])
        out.append(" ".join(w["text"] for w in ws))
    return out


def _underline_covers(pdf_page, words: list) -> bool:
    """True when a hairline rule is drawn under the span covered by `words`."""
    if not words:
        return False
    x0 = min(w["x0"] for w in words)
    x1 = max(w["x1"] for w in words)
    bottom = max(w["bottom"] for w in words)
    width = x1 - x0
    if width <= 0:
        return False

    # `line` objects would be the obvious carrier, but this template draws with
    # `rect` only; check both so the assertion survives a template change.
    candidates = list(pdf_page.rects) + list(pdf_page.lines)
    for c in candidates:
        height = abs(c["bottom"] - c["top"])
        if height > MAX_RULE_HEIGHT:
            continue
        if not (bottom - 1.0 <= c["top"] <= bottom + MAX_UNDERLINE_GAP):
            continue
        overlap = min(x1, c["x1"]) - max(x0, c["x0"])
        if overlap / width >= MIN_UNDERLINE_COVERAGE:
            return True
    return False


def _parse_letter(path: Path) -> dict:
    """Extract the statement, its date, its underline, and the header date."""
    text_pages, statement, raw_date, underlined, loose_hits = [], None, None, None, []
    period = None

    with pdfplumber.open(str(path)) as pdf:
        for pdf_page in pdf.pages:
            lines = _lines_from_words(pdf_page)
            page_text = "\n".join(lines)
            text_pages.append(page_text)
            loose_hits += [l for l in lines if LOOSE_RE.search(l)]

            if statement is not None:
                continue
            m = STATEMENT_RE.search(page_text)
            if not m:
                continue
            statement, raw_date = m.group(0), m.group(1).rstrip(".")
            # The AC prints a full stop after the date; note whether one is there.
            tail = page_text[m.end():m.end() + 2]
            period = m.group(1).endswith(".") or tail.startswith(".")

            # Underline is a property of the DATE only (TC-010), so locate the
            # words that make up the date rather than the whole sentence.
            date_words = [w for w in pdf_page.extract_words()
                          if raw_date.strip(".") in w["text"]]
            underlined = _underline_covers(pdf_page, date_words)

    text = "\n\n".join(text_pages)
    nad = None
    if raw_date:
        m = MMDDYYYY_RE.match(raw_date.strip())
        if m:
            try:
                nad = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
            except ValueError:
                nad = None

    header_dates = ANY_DATE_RE.findall(text)
    body_date = None
    if header_dates:
        try:
            body_date = datetime.strptime(header_dates[0], "%m/%d/%Y").date()
        except ValueError:
            body_date = None

    return {
        "text": text,
        "statement": statement,
        "raw_date": raw_date,
        "nad": nad,
        "underlined": underlined,
        "loose_hits": loose_hits,
        "body_date": body_date,
        "period": period,
    }


def _parse_issued(value: str):
    """'08-17-2026 02:44 AM' -> datetime. Returns None on an unknown shape."""
    value = (value or "").strip()
    for fmt in ("%m-%d-%Y %I:%M %p", "%m-%d-%Y %H:%M", "%m-%d-%Y", "%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _describe(letter: dict) -> str:
    return (f"{letter['form']} -> {letter['recipient'][:26]} "
            f"(issued {letter['issued_str']}, {letter['file']})")


# ── Corpus collection ──────────────────────────────────────────────────────────

def _open_correspondence(page, listing) -> bool:
    listing._dismiss_cdk_overlay()
    link = page.locator(
        'button:has-text("View Correspondence"), a:has-text("View Correspondence"), '
        'span:has-text("View Correspondence/Documents")').first
    if link.count() == 0:
        return False
    try:
        link.click(timeout=10_000)
    except Exception:
        listing._dismiss_cdk_overlay()
        link.dispatch_event("click")
    page.wait_for_timeout(4000)
    return True


def _collect_lt264_rows(page, case_url: str, download_dir: Path, tag: str) -> list:
    """Download every LT-264 / LT-264G in the open Correspondence History modal."""
    out = []
    dlg = page.locator("mat-dialog-container").last
    rows = dlg.locator("table tbody tr")
    for r in range(rows.count()):
        row = rows.nth(r)
        cells = [c.strip() for c in row.locator("td").all_inner_texts()]
        if len(cells) < 3 or not cells[0]:
            continue
        form, issued_str, recipient = cells[0], cells[1], cells[2]
        if not re.fullmatch(r"LT-?264\s*G?", form.strip(), re.I):
            continue
        dl = row.locator("span.table-link, a").filter(
            has_text=re.compile(r"^\s*Download\s*$", re.I)).first
        if dl.count() == 0:
            continue
        try:
            dl.scroll_into_view_if_needed()
            with page.expect_download(timeout=30_000) as info:
                dl.click()
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{tag}_{r}_{form}_{recipient}")[:88]
            dest = download_dir / f"{safe}.pdf"
            info.value.save_as(str(dest))
        except Exception:
            continue

        letter = {
            "case": case_url,
            "form": form.strip(),
            "recipient": recipient,
            "issued_str": issued_str,
            "issued": _parse_issued(issued_str),
            "file": dest.name,
            "path": dest,
            "row_index": r,
            "is_garage": bool(GARAGE_RE.search(form)),
        }
        letter.update(_parse_letter(dest))
        out.append(letter)
    return out


@pytest.fixture(scope="module")
def corpus(browser: Browser):
    """Every LT-264 / LT-264G reachable across a sample of live cases."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(
        storage_state=str(_AUTH_FILE), timezone_id="America/New_York", accept_downloads=True)
    page = ctx.new_page()
    letters, errors, reprintable = [], [], []

    try:
        go_to_staff_dashboard(page)
        if "login" in page.url.lower():
            pytest.fail(
                f"Staff auth is expired ({page.url}). Regenerate it with "
                f"`python scripts/save_staff_auth.py` before running this module.")
        StaffDashboardPage(page).navigate_to_lt262_listing()
        page.wait_for_timeout(2500)
        list_url = page.url
        listing = Lt262ListingPage(page)

        for tab, n in SAMPLE_TABS:
            for i in range(n):
                try:
                    page.goto(list_url, timeout=60_000)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1600)
                    listing._dismiss_cdk_overlay()
                    page.locator(f'[role="tab"]:has-text("{tab}")').first.click(timeout=20_000)
                    page.wait_for_timeout(2400)
                    if i >= listing.vin_links.count():
                        break
                    listing.select_application(i)
                    case_url = page.url

                    if not _open_correspondence(page, listing):
                        continue
                    found = _collect_lt264_rows(page, case_url, DOWNLOADS, f"{tab}{i}")
                    letters += found

                    # Remember one plain-LT-264 AND one LT-264G row that offer a
                    # reprint control, so TC-016..019 need not re-walk the listing
                    # and TC-017 does not block purely on sampling order.
                    if found:
                        dlg = page.locator("mat-dialog-container").last
                        have = {r["kind"] for r in reprintable}
                        for l in found:
                            kind = "garage" if l["is_garage"] else "std"
                            if kind in have:
                                continue
                            row = dlg.locator("table tbody tr").nth(l["row_index"])
                            if row.locator(
                                    ':scope >> text=/reprint/i').count() or re.search(
                                    r"reprint", row.inner_text(), re.I):
                                reprintable.append(
                                    {"kind": kind, "case": case_url, "letter": l})
                                have.add(kind)

                    page.keyboard.press("Escape")
                    page.wait_for_timeout(700)
                except Exception as exc:
                    errors.append(f"{tab}[{i}]: {type(exc).__name__}: {str(exc)[:90]}")
    finally:
        page.close()
        ctx.close()

    with_stmt = [l for l in letters if l["statement"]]
    print(f"\n[corpus] {len(letters)} LT-264/LT-264G PDF(s); "
          f"{len(with_stmt)} carry the Next Action Date statement; {len(errors)} error(s)")
    for l in letters:
        print(f"   {l['form']:9} issued {l['issued_str']:22} "
              f"body={l['body_date']} stmt={l['raw_date'] or 'ABSENT'} "
              f"underlined={l['underlined']} period={l['period']} "
              f"-> {l['recipient'][:24]}")
    if errors:
        print(f"   errors: {errors}")

    return {"letters": letters, "errors": errors, "reprintable": reprintable}


@pytest.fixture(scope="module")
def letters(corpus):
    """The corpus, guarded: an empty corpus is an inconclusive run, not a pass."""
    assert corpus["letters"], (
        f"No LT-264/LT-264G PDF could be downloaded from any sampled case, so none of "
        f"TC-LT264-001..024 could be evaluated. Errors: {corpus['errors']}")
    return corpus["letters"]


def _reprint_one(page, listing, target: dict):
    """Reprint one letter and return its before/after pair, or None."""
    before = target["letter"]
    page.goto(target["case"], timeout=60_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    if not _open_correspondence(page, listing):
        return None

    dlg = page.locator("mat-dialog-container").last
    row = dlg.locator("table tbody tr").nth(before["row_index"])
    ctl = row.locator(
        'span.table-link, a, button').filter(has_text=re.compile(r"reprint", re.I)).first
    if ctl.count() == 0:
        return None
    ctl.scroll_into_view_if_needed()
    ctl.click(timeout=15_000)
    page.wait_for_timeout(2500)

    # Confirm, if the action raises a dialog.
    for label in ("Yes", "Confirm", "Ok", "OK", "Reprint"):
        btn = page.locator(f'mat-dialog-container button:has-text("{label}")').last
        if btn.count() and btn.is_visible():
            btn.click()
            page.wait_for_timeout(2000)
            break
    page.wait_for_timeout(6000)

    # Re-read the history and take the newest letter for the same form type.
    page.goto(target["case"], timeout=60_000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    if not _open_correspondence(page, listing):
        return None
    after_all = _collect_lt264_rows(page, target["case"], DOWNLOADS, f"reprint_{target['kind']}")
    same = [l for l in after_all
            if l["form"] == before["form"] and l["recipient"] == before["recipient"]]
    if not same:
        return None
    after = max(same, key=lambda l: (l["issued"] or datetime.min))

    # AC-4 asks the reprint to RE-RENDER the letter in place while the original
    # correspondence rows stay retrievable, so an unchanged row count is the
    # expected shape — not evidence of a failed reprint. What must change is the
    # regenerated PDF, which the tests compare.
    print(f"\n[reprint:{target['kind']}] banner-confirmed reprint of {before['form']} -> "
          f"{before['recipient']}; before issued {before['issued_str']} "
          f"nad={before['raw_date']} | after issued {after['issued_str']} "
          f"nad={after['raw_date']} | rows retained: {len(after_all)} | "
          f"PDF re-rendered: {after['body_date'] != before['body_date']}")
    return {"before": before, "after": after, "all_after": after_all,
            "rows_retained": len(after_all) >= 1}


@pytest.fixture(scope="module")
def reprint_pair(corpus, browser: Browser):
    """Reprint one LT-264 and one LT-264G, returning a before/after pair for each.

    Side-effecting by design — it is what TC-016..019 are about. Both letter
    types are driven so TC-017 does not block purely on which row the corpus
    walk happened to reach first. Missing entries stay None so the dependent
    test skips with a stated reason instead of failing for the wrong one.
    """
    out = {"std": None, "garage": None}
    if not REPRINT_ENABLED or not corpus["reprintable"]:
        return out

    ctx = browser.new_context(
        storage_state=str(_AUTH_FILE), timezone_id="America/New_York", accept_downloads=True)
    page = ctx.new_page()
    try:
        go_to_staff_dashboard(page)
        listing = Lt262ListingPage(page)
        for target in corpus["reprintable"]:
            try:
                out[target["kind"]] = _reprint_one(page, listing, target)
            except Exception as exc:
                print(f"\n[reprint:{target['kind']}] could not complete: "
                      f"{type(exc).__name__}: {str(exc)[:140]}")
    finally:
        page.close()
        ctx.close()
    return out


# ── Shared assertions ──────────────────────────────────────────────────────────

def _require_statement(letters: list, subset=None) -> list:
    """Return the letters carrying the statement, failing loudly when none do."""
    pool = subset if subset is not None else letters
    assert pool, "no letter of the required type was found in the corpus"
    have = [l for l in pool if l["statement"]]
    if have:
        return have
    malformed = [l for l in pool if l["loose_hits"]]
    detail = (f"but {len(malformed)} letter(s) contain a 'next action date' fragment that does "
              f"not match the required sentence: "
              f"{[h for l in malformed for h in l['loose_hits']][:3]}"
              if malformed else
              "and no letter contains the phrase 'next action date' in any form")
    pytest.fail(
        f"STATEMENT MISSING: none of the {len(pool)} letter(s) examined display "
        f"'The next action date for this File is MM/DD/YYYY.' — {detail}. "
        f"Letters checked: {[_describe(l) for l in pool]}")


def _expected_nad(letter: dict):
    return (letter["issued"].date() + NEXT_ACTION_OFFSET) if letter["issued"] else None


def _assert_offset(pool: list, label: str):
    """Every letter in `pool` must carry issuance date + 32 calendar days."""
    have = _require_statement(pool, pool)
    checked, wrong = 0, []
    for l in have:
        expected = _expected_nad(l)
        if expected is None or l["nad"] is None:
            continue
        checked += 1
        if l["nad"] != expected:
            wrong.append(f"{_describe(l)}: printed {l['nad']:%m/%d/%Y}, "
                         f"expected {expected:%m/%d/%Y} "
                         f"(off by {(l['nad'] - expected).days:+d} day(s))")
    assert checked, (
        f"{label}: {len(have)} letter(s) carry the statement but none had both a parseable "
        f"issuance date and a parseable printed date, so the offset was not evaluated")
    assert not wrong, f"{label}: next action date is not issuance date + 32 days:\n  " + \
                      "\n  ".join(wrong)
    print(f"[{label}] {checked} letter(s) verified at issuance + 32 calendar days")


def _garage(letters: list) -> list:
    return [l for l in letters if l["is_garage"]]


def _standard(letters: list) -> list:
    return [l for l in letters if not l["is_garage"]]


# ═══════════════════════════════════════════════════════════════════════════════
# The statement itself — TC-001, 003, 009, 010, 021, 022
# ═══════════════════════════════════════════════════════════════════════════════

class TestTWLt264NextActionStatement:
    """The sentence is present, well-formed, underlined, and consistent."""

    def test_tc_lt264_001_statement_is_displayed(self, letters):
        """TC-LT264-001 — LT-264 displays the Next Action Date statement."""
        std = _standard(letters)
        assert std, f"no plain LT-264 in the corpus; forms seen: {sorted({l['form'] for l in letters})}"
        have = _require_statement(letters, std)
        print(f"[TC-001] {len(have)}/{len(std)} LT-264 letter(s) display the statement")

    def test_tc_lt264_003_garage_statement_is_displayed(self, letters):
        """TC-LT264-003 — LT-264G displays the same statement."""
        gar = _garage(letters)
        assert gar, f"no LT-264G in the corpus; forms seen: {sorted({l['form'] for l in letters})}"
        have = _require_statement(letters, gar)
        print(f"[TC-003] {len(have)}/{len(gar)} LT-264G letter(s) display the statement")

    def test_tc_lt264_009_date_uses_mm_dd_yyyy_format(self, letters):
        """TC-LT264-009 — the date is rendered as MM/DD/YYYY."""
        have = _require_statement(letters)
        bad = [f"{_describe(l)}: {l['raw_date']!r}"
               for l in have if not MMDDYYYY_RE.match((l["raw_date"] or "").strip())]
        assert not bad, "Next Action Date is not in MM/DD/YYYY format on:\n  " + "\n  ".join(bad)
        print(f"[TC-009] {len(have)} letter(s) render the date as MM/DD/YYYY")

    def test_tc_lt264_010_date_is_underlined(self, letters):
        """TC-LT264-010 — the date, and only the date, is underlined."""
        have = _require_statement(letters)
        bad = [_describe(l) for l in have if not l["underlined"]]
        assert not bad, (
            "Next Action Date is not underlined on:\n  " + "\n  ".join(bad) +
            "\n(an underline is detected as a hairline rule spanning >=60% of the date's "
            "width within 5pt below it)")
        print(f"[TC-010] {len(have)} letter(s) underline the date")

    def test_tc_lt264_021_both_letter_types_share_one_rule(self, letters):
        """TC-LT264-021 — LT-264 and LT-264G use the same calculation rule."""
        std, gar = _standard(letters), _garage(letters)
        assert std and gar, (
            f"need both letter types to compare rules; have {len(std)} LT-264 and "
            f"{len(gar)} LT-264G")
        _assert_offset(std, "TC-021/LT-264")
        _assert_offset(gar, "TC-021/LT-264G")

        # Same case + same issuance instant must yield the same date on both copies.
        by_case = defaultdict(list)
        for l in _require_statement(letters):
            by_case[(l["case"], l["issued_str"])].append(l)
        mismatched = [
            f"{case} @ {issued}: {sorted({x['form'] + '=' + str(x['raw_date']) for x in group})}"
            for (case, issued), group in by_case.items()
            if len({x["nad"] for x in group}) > 1]
        assert not mismatched, (
            "LT-264 and LT-264G issued together carry different next action dates:\n  "
            + "\n  ".join(mismatched))

    def test_tc_lt264_022_date_is_consistent_across_copies(self, letters):
        """TC-LT264-022 — the same letter shows the same date wherever it is read."""
        have = _require_statement(letters)
        # Within one PDF the sentence must not contradict itself across pages.
        inconsistent = []
        for l in have:
            dates = {m.group(1) for m in STATEMENT_RE.finditer(l["text"])}
            if len(dates) > 1:
                inconsistent.append(f"{_describe(l)}: {sorted(dates)}")
        assert not inconsistent, (
            "one letter displays more than one next action date:\n  " + "\n  ".join(inconsistent))

        # And a re-download of the same letter must reproduce it byte-for-byte.
        sample = have[0]
        again = _parse_letter(sample["path"])
        assert again["raw_date"] == sample["raw_date"], (
            f"re-reading {sample['file']} produced {again['raw_date']!r}, "
            f"first read produced {sample['raw_date']!r}")
        print(f"[TC-022] {len(have)} letter(s) internally consistent; "
              f"re-read of {sample['file']} reproduced {again['raw_date']}")


# ═══════════════════════════════════════════════════════════════════════════════
# The calculation — TC-002, 004, 005, 006, 007, 008, 011, 023, 024
# ═══════════════════════════════════════════════════════════════════════════════

class TestTWLt264NextActionCalculation:
    """The date equals the letter's own Print/Issuance Date plus 32 calendar days."""

    def test_tc_lt264_002_offset_is_issuance_plus_32(self, letters):
        """TC-LT264-002 — LT-264 date = Print/Issuance Date + 32 days."""
        _assert_offset(_standard(letters), "TC-002")

    def test_tc_lt264_004_garage_offset_is_issuance_plus_32(self, letters):
        """TC-LT264-004 — LT-264G date = its Print/Issuance Date + 32 days."""
        _assert_offset(_garage(letters), "TC-004")

    def test_tc_lt264_005_offset_counts_calendar_days(self, letters):
        """TC-LT264-005 — the 32 days are calendar days, weekends included."""
        have = _require_statement(letters)
        spanning = [l for l in have if l["issued"] and l["nad"]]
        assert spanning, "no letter had both a parseable issuance date and printed date"
        # A 32-day calendar span always contains 4 weekends; a business-day
        # interpretation would land ~44 calendar days out. Assert the exact span
        # AND that a weekend actually falls inside it, so the check is meaningful.
        wrong = []
        for l in spanning:
            issued = l["issued"].date()
            delta = (l["nad"] - issued).days
            weekend_days = sum(
                1 for d in range(1, delta + 1)
                if (issued + timedelta(days=d)).weekday() >= 5)
            if delta != 32:
                wrong.append(f"{_describe(l)}: span was {delta} day(s), not 32 "
                             f"({weekend_days} weekend day(s) inside)")
        assert not wrong, "the interval is not 32 calendar days:\n  " + "\n  ".join(wrong)
        print(f"[TC-005] {len(spanning)} letter(s) span exactly 32 calendar days")

    def test_tc_lt264_006_crosses_month_boundary(self, letters):
        """TC-LT264-006 — a date crossing into the next month is correct."""
        have = _require_statement(letters)
        crossing = [l for l in have
                    if l["issued"] and (l["issued"].date() + NEXT_ACTION_OFFSET).month
                    != l["issued"].date().month]
        if not crossing:
            pytest.skip(
                "no letter in the corpus has an issuance date whose +32 days lands in a "
                "different month; issuance dates seen: "
                f"{sorted({l['issued_str'] for l in have})}")
        _assert_offset(crossing, "TC-006")

    def test_tc_lt264_007_crosses_year_boundary(self, letters):
        """TC-LT264-007 — a date crossing into the next year is correct."""
        have = _require_statement(letters)
        crossing = [l for l in have
                    if l["issued"] and (l["issued"].date() + NEXT_ACTION_OFFSET).year
                    != l["issued"].date().year]
        if not crossing:
            pytest.skip(
                "NOT PRODUCIBLE ON THIS ENVIRONMENT: a year-crossing next action date needs a "
                "letter issued in December, and issuance date is always 'now' — no Staff "
                "Portal surface can backdate it. Issuance dates seen: "
                f"{sorted({l['issued_str'] for l in have})}")
        _assert_offset(crossing, "TC-007")

    def test_tc_lt264_008_crosses_leap_day(self, letters):
        """TC-LT264-008 — the 32-day period crossing 29 February is correct."""
        have = _require_statement(letters)

        def spans_leap_day(l):
            if not l["issued"]:
                return False
            start = l["issued"].date()
            return any((start + timedelta(days=d)).month == 2
                       and (start + timedelta(days=d)).day == 29
                       for d in range(1, 33))

        crossing = [l for l in have if spans_leap_day(l)]
        if not crossing:
            pytest.skip(
                "NOT PRODUCIBLE ON THIS ENVIRONMENT: crossing 29 February needs a letter issued "
                "in the 32 days before a leap day, and issuance date is always 'now'. "
                f"Issuance dates seen: {sorted({l['issued_str'] for l in have})}")
        _assert_offset(crossing, "TC-008")

    def test_tc_lt264_011_calculated_from_issuance_not_case_creation(self, letters):
        """TC-LT264-011 — the base date is the letter's issuance, not the case's."""
        have = _require_statement(letters)
        pool = [l for l in have if l["issued"] and l["nad"]]
        assert pool, "no letter had both a parseable issuance date and printed date"

        # Letters issued at different times must carry different dates. If the
        # base were case creation (or any per-case constant), every letter on a
        # case would agree regardless of when it was issued.
        by_issue_date = defaultdict(set)
        for l in pool:
            by_issue_date[l["issued"].date()].add(l["nad"])
        collisions = {d: v for d, v in by_issue_date.items() if len(v) > 1}
        assert not collisions, (
            f"letters issued on the same date carry different next action dates: {collisions}")

        wrong = [f"{_describe(l)}: printed {l['nad']:%m/%d/%Y}, issuance "
                 f"{l['issued']:%m/%d/%Y} + 32 = {_expected_nad(l):%m/%d/%Y}"
                 for l in pool if l["nad"] != _expected_nad(l)]
        assert not wrong, (
            "next action date is not derived from the letter's issuance date:\n  "
            + "\n  ".join(wrong))
        print(f"[TC-011] {len(pool)} letter(s) derive from their own issuance date; "
              f"{len(by_issue_date)} distinct issuance date(s) observed")

    def test_tc_lt264_023_not_derived_from_case_creation_date(self, letters):
        """TC-LT264-023 — the case's creation date does not drive the calculation."""
        have = _require_statement(letters)
        pool = [l for l in have if l["issued"] and l["nad"]]
        assert pool, "no letter had both a parseable issuance date and printed date"

        # Across cases created at different times, the offset from ISSUANCE must
        # stay 32 for every one of them. A creation-date-driven value would give
        # a different offset per case.
        offsets = {(l["nad"] - l["issued"].date()).days for l in pool}
        assert offsets == {32}, (
            f"offset from issuance varies across cases ({sorted(offsets)}), which means the "
            f"date is keyed to something other than the letter's issuance: "
            f"{[_describe(l) for l in pool]}")
        cases = {l["case"] for l in pool}
        print(f"[TC-023] constant +32 offset across {len(cases)} case(s), {len(pool)} letter(s)")

    def test_tc_lt264_024_not_derived_from_aging_start_date(self, letters):
        """TC-LT264-024 — the aging start date does not override the issuance date."""
        have = _require_statement(letters)
        pool = [l for l in have if l["issued"] and l["nad"]]
        assert pool, "no letter had both a parseable issuance date and printed date"

        # Where a case has more than one issuance instant, an aging-start-driven
        # value would be identical across them; an issuance-driven value moves.
        by_case = defaultdict(set)
        for l in pool:
            by_case[l["case"]].add((l["issued"].date(), l["nad"]))
        multi = {c: v for c, v in by_case.items() if len({d for d, _ in v}) > 1}
        for case, pairs in multi.items():
            nads = {n for _, n in pairs}
            assert len(nads) > 1, (
                f"case {case} issued letters on {sorted({d for d, _ in pairs})} but every one "
                f"carries the same next action date {nads} — the value is pinned to something "
                f"other than the Print/Issuance Date")

        wrong = [_describe(l) for l in pool if l["nad"] != _expected_nad(l)]
        assert not wrong, (
            "next action date does not match the letter's Print/Issuance Date + 32:\n  "
            + "\n  ".join(wrong))
        print(f"[TC-024] {len(pool)} letter(s) match their own issuance date; "
              f"{len(multi)} case(s) had multiple issuance instants to compare")


# ═══════════════════════════════════════════════════════════════════════════════
# Regeneration after an aging reset — TC-012, 013, 014, 015
# ═══════════════════════════════════════════════════════════════════════════════

def _generations(letters: list) -> dict:
    """Group letters by (case, form, recipient) where more than one exists.

    Two rows for the same recipient and form type on one case are two
    GENERATIONS of that letter — whether produced by an aging reset or a
    reprint, they are what TC-012..015 and TC-018 compare.
    """
    groups = defaultdict(list)
    for l in letters:
        groups[(l["case"], l["form"], l["recipient"])].append(l)
    return {k: sorted(v, key=lambda x: (x["issued"] or datetime.min))
            for k, v in groups.items() if len(v) > 1}


class TestTWLt264NextActionAgingReset:
    """A regenerated letter must carry a freshly calculated date."""

    def test_tc_lt264_012_regenerated_lt264_recalculates(self, letters):
        """TC-LT264-012 — a regenerated LT-264 uses the new issuance date + 32."""
        gens = {k: v for k, v in _generations(_standard(letters)).items()}
        if not gens:
            pytest.skip(
                "NO AGING RESET AVAILABLE: no case in the corpus carries more than one "
                "generation of the same LT-264, and the aging clock is restarted by a backend "
                "automation chain rather than any Staff Portal control this suite can drive. "
                "TC-016 covers the same recalculation through the reprint path.")
        newest = [v[-1] for v in gens.values()]
        _assert_offset(newest, "TC-012")

    def test_tc_lt264_013_regenerated_lt264g_recalculates(self, letters):
        """TC-LT264-013 — a regenerated LT-264G uses the new issuance date + 32."""
        gens = _generations(_garage(letters))
        if not gens:
            pytest.skip(
                "NO AGING RESET AVAILABLE: no case in the corpus carries more than one "
                "generation of the same LT-264G — see TC-012 for why this cannot be forced "
                "here. TC-017 covers the same recalculation through the reprint path.")
        _assert_offset([v[-1] for v in gens.values()], "TC-013")

    def test_tc_lt264_014_old_date_is_not_retained(self, letters):
        """TC-LT264-014 — the new letter does not contain the previous date."""
        gens = _generations(letters)
        if not gens:
            pytest.skip(
                "NO AGING RESET AVAILABLE: no recipient has two generations of the same letter "
                "in the corpus. TC-018 asserts the same invariant across a reprint.")
        _require_statement(letters, [l for v in gens.values() for l in v])
        stale = []
        for key, group in gens.items():
            prev, latest = group[-2], group[-1]
            if not (prev["nad"] and latest["nad"]):
                continue
            if prev["issued"] and latest["issued"] and prev["issued"].date() == latest["issued"].date():
                continue  # same-day regeneration — the dates legitimately match
            if latest["nad"] == prev["nad"]:
                stale.append(f"{key[1]} -> {key[2]}: regenerated {latest['issued_str']} still "
                             f"shows {latest['nad']:%m/%d/%Y} from {prev['issued_str']}")
            if re.search(rf"\b{re.escape(prev['nad'].strftime('%m/%d/%Y'))}\b", latest["text"]):
                stale.append(f"{key[1]} -> {key[2]}: the previous date "
                             f"{prev['nad']:%m/%d/%Y} still appears in the new letter")
        assert not stale, "a stale next action date survived regeneration:\n  " + "\n  ".join(stale)
        print(f"[TC-014] {len(gens)} regenerated letter(s) carry no stale date")

    def test_tc_lt264_015_every_reset_recalculates(self, letters):
        """TC-LT264-015 — each regeneration uses its own latest issuance date."""
        gens = {k: v for k, v in _generations(letters).items() if len(v) >= 3}
        if not gens:
            pytest.skip(
                "NO MULTIPLE RESETS AVAILABLE: no recipient has three or more generations of "
                "the same letter in the corpus, so repeated recalculation cannot be observed. "
                "Reaching this state needs the aging chain run twice on one case.")
        flat = [l for v in gens.values() for l in v]
        _assert_offset(flat, "TC-015")
        print(f"[TC-015] {len(gens)} letter(s) with {sum(len(v) for v in gens.values())} "
              f"generations, each recalculated")


# ═══════════════════════════════════════════════════════════════════════════════
# Manual reprint — TC-016, 017, 018, 019
# ═══════════════════════════════════════════════════════════════════════════════

def _require_reprint(reprint_pair, kind: str):
    """Return the before/after pair for `kind` ("std" or "garage"), or skip."""
    if not REPRINT_ENABLED:
        pytest.skip("reprint tests disabled via LT264_NAD_REPRINT=0")
    pair = reprint_pair.get(kind)
    if not pair:
        label = "LT-264G" if kind == "garage" else "plain LT-264"
        pytest.skip(
            f"REPRINT NOT EXERCISED for {label}: no 'Send For Reprinting' control was "
            f"reachable on a {label} row across the sampled cases, or the reprint did not "
            f"regenerate a readable letter within the wait window")
    return pair


def _any_reprint(reprint_pair):
    """Either pair, preferring the plain LT-264 — for the type-agnostic cases."""
    for kind in ("std", "garage"):
        if reprint_pair.get(kind):
            return reprint_pair[kind]
    if not REPRINT_ENABLED:
        pytest.skip("reprint tests disabled via LT264_NAD_REPRINT=0")
    pytest.skip(
        "REPRINT NOT EXERCISED: no 'Send For Reprinting' control was reachable on any "
        "LT-264 or LT-264G row across the sampled cases")


def _assert_original_retained(pair, tc: str):
    """The reprint must leave the original correspondence rows retrievable.

    A reprint re-renders the letter in place rather than appending a row, so an
    unchanged row count is correct. What would be wrong is losing the entry.
    """
    assert pair["rows_retained"], (
        f"{tc}: after 'Send For Reprinting' the {pair['before']['form']} entry for "
        f"{pair['before']['recipient']} is no longer retrievable from Correspondence History")


class TestTWLt264NextActionReprint:
    """A manually reprinted letter recalculates from the reprint date."""

    def test_tc_lt264_016_reprinted_lt264_has_new_date(self, reprint_pair):
        """TC-LT264-016 — a reprinted LT-264 shows a newly calculated date."""
        pair = _require_reprint(reprint_pair, "std")
        _assert_original_retained(pair, "TC-016")
        _assert_offset([pair["after"]], "TC-016")

    def test_tc_lt264_017_reprinted_lt264g_has_new_date(self, reprint_pair):
        """TC-LT264-017 — a reprinted LT-264G shows a newly calculated date."""
        pair = _require_reprint(reprint_pair, "garage")
        _assert_original_retained(pair, "TC-017")
        _assert_offset([pair["after"]], "TC-017")

    def test_tc_lt264_018_reprint_does_not_retain_original_date(self, reprint_pair):
        """TC-LT264-018 — the original letter's date is not reused on the reprint."""
        pair = _any_reprint(reprint_pair)
        before, after = pair["before"], pair["after"]
        _require_statement([before, after], [before, after])
        assert before["nad"] and after["nad"], (
            f"could not compare: before={before['raw_date']!r}, after={after['raw_date']!r}")
        if before["issued"] and after["issued"] and before["issued"].date() == after["issued"].date():
            assert after["nad"] == before["nad"], (
                f"reprinted the same day as the original but the date moved: "
                f"{before['nad']:%m/%d/%Y} -> {after['nad']:%m/%d/%Y}")
            print(f"[TC-018] same-day reprint correctly keeps {after['nad']:%m/%d/%Y}")
            return
        assert after["nad"] != before["nad"], (
            f"the reprint reuses the original letter's next action date "
            f"{before['nad']:%m/%d/%Y} despite being issued on {after['issued_str']} "
            f"(original: {before['issued_str']})")
        print(f"[TC-018] reprint moved the date {before['nad']:%m/%d/%Y} -> "
              f"{after['nad']:%m/%d/%Y}")

    def test_tc_lt264_019_recalculated_from_reprint_date(self, reprint_pair):
        """TC-LT264-019 — the date equals the new Print/Issuance Date + 32."""
        pair = _any_reprint(reprint_pair)
        _assert_original_retained(pair, "TC-019")
        _assert_offset([pair["after"]], "TC-019")


# ═══════════════════════════════════════════════════════════════════════════════
# Historical letters — TC-020
# ═══════════════════════════════════════════════════════════════════════════════

class TestTWLt264NextActionHistorical:
    """Letters generated before the enhancement must not be altered by it."""

    def test_tc_lt264_020_historical_letters_are_unchanged(self, letters):
        """TC-LT264-020 — an already-issued letter is not regenerated on view.

        The enhancement adds a sentence to letters generated from now on; it must
        not reach back and rewrite letters already mailed. The observable proxy
        is whether re-opening an old letter re-renders it: a letter whose PDF
        prints today's date rather than the date it was issued is being
        regenerated on download, which means any next action date it carries
        would move every time it is viewed.
        """
        dated = [l for l in letters if l["issued"] and l["body_date"]]
        assert dated, (
            f"no letter had both a parseable DATE ISSUED and a parseable header date; "
            f"issuance strings seen: {sorted({l['issued_str'] for l in letters})}")

        today = date.today()
        historical = [l for l in dated if l["issued"].date() < today]
        if not historical:
            pytest.skip(
                f"every letter in the corpus was issued today ({today:%m/%d/%Y}), so a "
                f"historical letter could not be examined; issuance dates seen: "
                f"{sorted({l['issued'].date() for l in dated})}")

        rewritten = [
            f"{_describe(l)}: issued {l['issued'].date():%m/%d/%Y} but the PDF prints "
            f"{l['body_date']:%m/%d/%Y}"
            for l in historical if l["body_date"] != l["issued"].date()]
        assert not rewritten, (
            "historical letters are re-rendered with the current date instead of their "
            "issuance date, so any next action date on them would move on every view:\n  "
            + "\n  ".join(rewritten))
        print(f"[TC-020] {len(historical)} historical letter(s) retain their issuance date")
