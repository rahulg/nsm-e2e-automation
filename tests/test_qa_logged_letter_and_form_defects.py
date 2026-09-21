"""Regression coverage for three QA-logged defects found during exploratory
testing of the NSM/NSS Staff and Public portals (2026-08-12).

These are NOT acceptance criteria of any one ticket — they were surfaced while
exploring around TW-26162855 and were reviewed and logged by QA as genuine bugs.
They live in their own module for that reason.

Each test is a STRICT xfail: it runs on every execution, keeps the suite green
while the defect is open, and flips to a hard FAILURE the moment the product is
fixed. That failure is the signal to delete the `xfail` marker, at which point
the test becomes ordinary regression protection. Nothing here is written as a
passing assertion, because encoding a defect as "expected" is how it stops being
visible.

  D1  LT-264 / LT-264G print "$.00" as the lien amount when the LT-262 carries
      no lien charge (should be "$0.00", or the letter should not issue).
      Evidence: 9 letters across 2 of 3 cases. Cross-checked against the LT-262
      UI - cases printing "$.00" show no lien amount at all, while the case
      showing "$300.00" in the UI prints "$300.00" correctly. So this is
      currency FORMATTING of an absent/zero value, not data loss.

  D2  LT-264G inserts a stray comma between the vehicle year and make
      ("2012, toyota") where the LT-264 for the same case correctly renders
      "2012 toyota". Evidence: 3 of 3 cases.

  D3  A negative Approximate Value on the public LT-260 form is correctly
      blocked from advancing, but NO validation message is shown - the Next
      button simply goes disabled with no explanation.

  D4  The Track LT-264 grid renders a DUPLICATE row for the same recipient.
      Observed on case N26-1073737 (VIN JTDZN3EU3C3176467): the row
      'WORLD OMNI FINANCIAL CORP / Lienholder / LT-264 / PO BOX 9249 MOBILE AL
      36691' appears twice, identical in every column, while Correspondence
      History holds exactly ONE LT-264 for that lienholder - so the letter is
      not duplicated, only its Track row is. This is the behaviour originally
      reported as "duplicate Track LT-264 details". It does NOT reproduce on
      every case (the sibling case N26-1073605 for the same VIN is clean),
      which is why an earlier sample of other cases missed it.

Fixture cost: D1/D2/D4 reuse one staff pass over a sample of cases. D3 drives the
public LT-260 form and abandons the draft (never submits, never pays).

PDF text is read with pdfplumber, never PyPDF2: PyPDF2 mangles inter-word spacing
in these templates badly enough to manufacture false findings.
"""
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext

from src.config.env import ENV
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.helpers.workflow_helper import go_to_staff_dashboard

pdfplumber = pytest.importorskip("pdfplumber", reason="pdfplumber is required to read letter PDFs")

_AUTH_FILE = (
    Path(__file__).resolve().parent.parent / "auth" / os.getenv("NSM_ENV", "qa") / "staff-portal.json"
)
DOWNLOADS = Path(__file__).resolve().parent.parent / "downloads" / "logged_defects"

# Cases known to carry issued LT-264 + LT-264G letters. Sampled rather than
# hardcoded to one record so a single re-seeded case cannot silently void the run.
SAMPLE_TABS = [("Aging", 4), ("Processed", 3), ("Court Hearing", 3)]

# "$.00" - a currency value whose whole-number part is missing entirely.
MALFORMED_CURRENCY = re.compile(r"\$\s*\.\d{2}(?!\d)")
# "2012, toyota" - a comma between a 4-digit year and the make.
YEAR_COMMA_MAKE = re.compile(r"sell the:\s*\d{4}\s*,\s*[A-Za-z]")


def _pdf_text(path: Path) -> str:
    """Layout-accurate text: group words into lines by their vertical position."""
    from collections import defaultdict
    with pdfplumber.open(str(path)) as pdf:
        out = []
        for page in pdf.pages:
            rows = defaultdict(list)
            for w in page.extract_words():
                rows[round(w["top"], 0)].append(w)
            for _, ws in sorted(rows.items()):
                ws.sort(key=lambda z: z["x0"])
                out.append(" ".join(w["text"] for w in ws))
    return "\n".join(out)


@pytest.fixture(scope="module")
def issued_letters(browser: Browser):
    """Download every LT-264 / LT-264G PDF reachable across a sample of cases."""
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(
        storage_state=str(_AUTH_FILE), timezone_id="America/New_York", accept_downloads=True
    )
    page = ctx.new_page()
    letters, errors = [], []
    try:
        go_to_staff_dashboard(page)
        from src.pages.staff_portal.dashboard_page import StaffDashboardPage
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

                    listing._dismiss_cdk_overlay()
                    link = page.locator(
                        'button:has-text("View Correspondence"), a:has-text("View Correspondence"), '
                        'span:has-text("View Correspondence/Documents")').first
                    if link.count() == 0:
                        continue
                    try:
                        link.click(timeout=10_000)
                    except Exception:
                        listing._dismiss_cdk_overlay()
                        link.dispatch_event("click")
                    page.wait_for_timeout(4000)

                    dlg = page.locator("mat-dialog-container").last
                    rows = dlg.locator("table tbody tr")
                    for r in range(rows.count()):
                        row = rows.nth(r)
                        cells = [c.strip() for c in row.locator("td").all_inner_texts()]
                        if len(cells) < 3 or not cells[0]:
                            continue
                        form, recipient = cells[0], cells[2]
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
                            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{form}__{recipient}")[:90]
                            dest = DOWNLOADS / f"{safe}.pdf"
                            info.value.save_as(str(dest))
                            letters.append({
                                "case": case_url, "form": form.strip(),
                                "recipient": recipient, "file": dest.name,
                                "text": _pdf_text(dest),
                            })
                        except Exception as exc:
                            errors.append(f"{form}/{recipient}: {type(exc).__name__}")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(700)
                except Exception as exc:
                    errors.append(f"{tab}[{i}]: {type(exc).__name__}: {str(exc)[:90]}")
    finally:
        page.close()
        ctx.close()

    print(f"\n[issued_letters] {len(letters)} LT-264/LT-264G PDF(s) downloaded, "
          f"{len(errors)} error(s)")
    for l in letters:
        print(f"   {l['form']:10} -> {l['recipient'][:28]:30} ({l['file']})")
    return {"letters": letters, "errors": errors}


# ═══════════════════════════════════════════════════════════════════════════════
# D1 — malformed lien amount
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.logged_defect
@pytest.mark.xfail(strict=True, reason=(
    "LOGGED DEFECT (QA 2026-08-12): LT-264 / LT-264G render the lien amount as "
    "'$.00' when the LT-262 carries no lien charge, instead of '$0.00'. Seen on 9 "
    "letters across 2 of 3 cases. Remove this marker once the currency formatting "
    "is fixed, which converts this into ordinary regression protection."))
def test_defect_lien_amount_is_well_formed_currency(issued_letters):
    """The lien amount on an LT-264/LT-264G must be a well-formed currency value.

    This is the figure a certified legal notice tells the recipient they may
    dispute, so a malformed amount is a legal-clarity problem, not cosmetic.
    """
    letters = issued_letters["letters"]
    assert letters, (
        f"No LT-264/LT-264G PDFs could be downloaded, so the defect could not be "
        f"evaluated. Errors: {issued_letters['errors']}"
    )
    offenders = []
    for l in letters:
        hits = MALFORMED_CURRENCY.findall(l["text"])
        if hits:
            offenders.append(f"{l['form']} -> {l['recipient']}: {sorted(set(hits))} ({l['file']})")
    assert not offenders, (
        "Malformed lien amount printed on:\n  " + "\n  ".join(offenders)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# D2 — stray comma between vehicle year and make on the Garage copy
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.logged_defect
@pytest.mark.xfail(strict=True, reason=(
    "LOGGED DEFECT (QA 2026-08-12): the LT-264G vehicle description inserts a comma "
    "between year and make ('2012, toyota') where the LT-264 for the same case "
    "correctly renders '2012 toyota'. Seen on 3 of 3 cases. Remove this marker once "
    "the template is fixed."))
def test_defect_lt264g_vehicle_year_make_punctuation(issued_letters):
    """LT-264G must punctuate the vehicle description like the LT-264 does."""
    garage = [l for l in issued_letters["letters"]
              if re.search(r"garage|264\s*G", l["form"], re.I)]
    assert garage, (
        f"No LT-264G PDF was downloaded, so the defect could not be evaluated. "
        f"Forms seen: {sorted({l['form'] for l in issued_letters['letters']})}"
    )
    offenders = []
    for l in garage:
        m = YEAR_COMMA_MAKE.search(l["text"])
        if m:
            offenders.append(f"{l['recipient']}: {m.group(0)!r} ({l['file']})")
    assert not offenders, (
        "LT-264G renders a stray comma after the vehicle year on:\n  "
        + "\n  ".join(offenders)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# D4 — duplicate recipient row on the Track LT-264 grid
# ═══════════════════════════════════════════════════════════════════════════════

# Targeted at the case where the duplicate was observed, rather than a random
# sample: a sweep that happened to miss this case would XPASS and, under strict
# xfail, fail for the wrong reason. Once the fix lands, widen this to a sweep.
DUP_CASE_URL = (
    "https://nsm-qa.nc.verifi.dev/pages/ncdot-notice-and-storage/"
    "LT-262/48973ae1-12ac-48ad-944b-7a4855b8ae04/details?tab=Aging"
)

JS_TRACK_VISIBLE_ROWS = """() => {
  const t = document.querySelector('table');
  if (!t) return null;
  const head = [...t.querySelectorAll('thead th')].map(x => x.innerText.trim());
  return [...t.querySelectorAll('tbody tr')]
    .filter(r => { const b = r.getBoundingClientRect();
                   return b.width > 0 && b.height > 0 && r.offsetParent !== null; })
    .map(r => [...r.querySelectorAll('td')].map(c => c.innerText.trim()))
    .filter(cells => cells.length > 1 && cells.some(c => c))
    .map(cells => { const o = {}; head.forEach((h, i) => { if (h) o[h] = cells[i] ?? ''; }); return o; });
}"""


@pytest.mark.logged_defect
@pytest.mark.xfail(strict=True, reason=(
    "LOGGED DEFECT (QA 2026-08-12): the Track LT-264 grid renders a duplicate row for "
    "the same recipient. On case N26-1073737 (VIN JTDZN3EU3C3176467) the row "
    "'WORLD OMNI FINANCIAL CORP / Lienholder / LT-264 / PO BOX 9249 MOBILE AL 36691' "
    "appears twice while Correspondence History holds only one LT-264 for it. Remove "
    "this marker once the grid de-duplicates."))
def test_defect_track_lt264_has_no_duplicate_recipient_rows(browser: Browser):
    """No recipient should appear twice on one case's Track LT-264 grid.

    A duplicated row misrepresents how many certified letters a case produced and
    makes the aging/decision picture ambiguous for staff, even though the
    underlying letter is generated only once.
    """
    ctx = browser.new_context(storage_state=str(_AUTH_FILE), timezone_id="America/New_York")
    page = ctx.new_page()
    try:
        go_to_staff_dashboard(page)
        page.goto(DUP_CASE_URL, timeout=60_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2800)

        listing = Lt262ListingPage(page)
        rows = None
        for _ in range(3):
            try:
                listing.click_track_lt264_tab()
                page.wait_for_timeout(3500)
                if page.locator("table").count():
                    rows = page.evaluate(JS_TRACK_VISIBLE_ROWS)
                    break
            except Exception:
                page.wait_for_timeout(2000)

        assert rows, (
            f"Could not read the Track LT-264 grid for {DUP_CASE_URL} — the case may have "
            f"been re-seeded or removed; re-point DUP_CASE_URL before trusting this result"
        )

        from collections import Counter
        counts = Counter(
            (r.get("RECIPIENT"), r.get("RECIPIENT TYPE"),
             r.get("FORM TYPE"), r.get("RECIPIENT ADDRESS"))
            for r in rows
        )
        dupes = {k: v for k, v in counts.items() if v > 1}
        print(f"\n[D4] {len(rows)} visible Track LT-264 row(s); "
              f"{len(counts)} distinct; duplicates: {dupes or 'none'}")
        assert not dupes, (
            "Track LT-264 renders duplicate recipient row(s): "
            + "; ".join(f"{k} x{v}" for k, v in dupes.items())
        )
    finally:
        page.close()
        ctx.close()


# ═══════════════════════════════════════════════════════════════════════════════
# D3 — silent block on a negative Approximate Value (public LT-260)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.logged_defect
@pytest.mark.xfail(strict=True, reason=(
    "LOGGED DEFECT (QA 2026-08-12): a negative Approximate Value on the public LT-260 "
    "form is correctly blocked from advancing, but no validation message is shown - "
    "the Next button just goes disabled with no explanation. Remove this marker once "
    "an inline error is displayed."))
def test_defect_negative_approximate_value_shows_validation_message(public_context: BrowserContext):
    """A negative Approximate Value must explain itself, not fail silently.

    Blocking is correct and already works; what is missing is the message telling
    the user WHY they cannot continue. The draft is abandoned, never submitted.
    """
    from src.pages.public_portal.dashboard_page import PublicDashboardPage
    from src.pages.public_portal.lt260_form_page import Lt260FormPage
    from src.helpers.data_helper import (
        generate_vin, generate_address, generate_license_plate, past_date, random_vehicle,
    )

    page = public_context.new_page()
    try:
        page.goto(ENV.PUBLIC_PORTAL_URL, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        dash = PublicDashboardPage(page)
        dash.select_business()
        dash.click_start_here()
        page.wait_for_timeout(2000)

        lt260 = Lt260FormPage(page)
        lt260.enter_vin(generate_vin())
        lt260.click_vin_lookup()
        page.wait_for_timeout(1500)
        lt260.fill_vehicle_details(random_vehicle())
        lt260.fill_date_vehicle_left(past_date(30))
        lt260.fill_license_plate(generate_license_plate())

        lt260._angular_fill(lt260.approx_value_input, "-500")
        page.wait_for_timeout(1200)

        address = generate_address()
        lt260.select_reason_storage()
        lt260.fill_storage_location("QA Regression Garage", address["street"], address["zip"])
        page.wait_for_timeout(1200)

        field_value = lt260.approx_value_input.input_value()
        body = page.locator("body").inner_text()
        next_btn = page.locator('button:has-text("Next")').first
        next_disabled = next_btn.is_disabled() if next_btn.count() else None
        message_shown = bool(re.search(
            r"must be (greater|positive|a positive)|cannot be negative|invalid (value|amount)|"
            r"enter a valid", body, re.I))

        print(f"\n[D3] Approximate Value field = {field_value!r}; "
              f"Next disabled = {next_disabled}; validation message shown = {message_shown}")

        # Blocking is the part that already works - assert it so a regression that
        # silently ACCEPTS a negative value fails loudly rather than xpassing.
        assert next_disabled is not False, (
            f"Negative Approximate Value {field_value!r} did NOT block progression - "
            f"this is worse than the logged defect and must be raised separately"
        )
        assert message_shown, (
            f"Approximate Value accepted {field_value!r} and disabled Next, but showed no "
            f"validation message explaining why the form cannot proceed"
        )
    finally:
        page.close()
