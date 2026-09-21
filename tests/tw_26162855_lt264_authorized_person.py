"""TW-26162855 / NCNSS-160 — Generate LT-264 Letters for the Authorized Person.

The CR adds the authorized person captured on the originating LT-260 as a FOURTH
LT-264 recipient type, alongside owner / lessee / lienholder. On the Staff Portal
LT-262 "CHECK DCI AND NMVTIS" tab it introduces an **Authorized Person Details**
panel (Name + Address + a "Send LT-264 to Authorized Person?" checkbox), and the
letter it opts into is then supposed to behave like every other LT-264 —
certified to Nordis, tracked on TRACK LT-264, aged over 32 days, and eligible for
the post-32-day LT-263 / LT-264A decision.

What this module does
---------------------
It runs ONE read-only survey pass over real LT-262 cases on the target env
(module-scoped `ap_survey` fixture), classifying each case by the state of the
Authorized Person surface, and then asserts the acceptance criteria against that
survey. A single pass is used because each case costs ~40 s of navigation; every
test below reads the same cached snapshot rather than re-walking the listing.

The survey NEVER clicks an issuance button. Issuing an LT-264 mails real
certified letters through Nordis from a shared QA sandbox, so every check here is
observational: it asserts the rules the product must already satisfy on the cases
that exist, rather than manufacturing new ones.

Grounding (live QA observation, 2026-08-11)
-------------------------------------------
  * Panel markup — heading "Authorized Person Details", then the checkbox
    "Send LT-264 to Authorized Person?", then "Name" / "Address" label-value pairs.
  * Pre-issuance case (To Process, Issue button present) → checkbox ENABLED, UNTICKED.
  * Post-issuance case (Aging, Issue button gone)        → checkbox DISABLED.
  * Case whose LT-260 carried no authorized person       → panel and checkbox both absent.
  * TRACK LT-264 columns: RECIPIENT · RECIPIENT ADDRESS · FORM TYPE · RECIPIENT TYPE ·
    TRACKING NUMBER · PRINT DATE · MAIL DATE · AGE DATE · (blank) · STATUS.

Coverage notes
--------------
1. AC-2's no-owner arm (Issue LT-262B and Issue LT-264/G shown together, the latter
   gated on the checkbox) is NOT asserted here. It needs an LT-262 whose STARS lookup
   returns no owner while its LT-260 carries an authorized person; `VIN_NO_OWNERS` is
   still "PLACEHOLDER_NO_OWNERS" in src/config/test_data.py, so no such case can be
   built deterministically. `test_ac2_*` reports what the survey actually found so the
   gap is visible in the run output instead of silently absent.

2. AC-7's aging half IS covered (`test_ac7_*`): verified live by forcing a case to
   Age 32 via automation chain 485a239fd539a7654cfb94cdf8b8f59e, where the authorized
   person's row advanced 1 -> 32 in lockstep with owner and requestor. AC-7's *Nordis
   delivery-status* half is NOT covered: TRACKING NUMBER / MAIL DATE / STATUS are blank
   for every recipient on this environment because the Nordis SFTP report job does not
   run here, so there is no delivery state to assert on for any party.

3. AC-8's recipient-selection half IS covered (`test_ac8_*`). Its *auto-issuance* half
   is not: reaching Age 32 was observed to unlock the manual decision radios rather than
   auto-issue an LT-263/LT-264A, which is consistent with the blank delivery statuses in
   note 2 (neither "all Delivered" nor ">=1 Undelivered" is evaluable). Whether the gate
   should fire on Age >= 32 or on all-rows-terminal is nss.kb OQ-48, still open.

Reviewed and closed as NOT defects (QA, 2026-08-12) — deliberately not asserted here:
   * "Authorized User" vs the AC's "Authorized Person" recipient-type label.
   * The authorized person also receiving an LT-260A.
   * Recipient-selection checkboxes having no inline text / ARIA name.
"""
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext

from src.config.env import ENV
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.helpers.workflow_helper import go_to_staff_dashboard

# ── Surface constants, all confirmed against live QA ────────────────────────────
PANEL_HEADING = "Authorized Person Details"
CHECKBOX_LABEL_RE = r"Send LT-?264 to Authorized Person"
ISSUE_264_RE = r"Issue LT-?264 and LT-?264 Garage"
ISSUE_262B_RE = r"Issue LT-?262\s*B"

# BR-60 recipient vocabulary + the CR's new fourth type.
#
# "Authorized User" is the CORRECT rendered label — confirmed by QA 2026-08-12.
# The AC text says "Authorized Person"; that wording difference was reviewed and
# ruled not a defect, so both spellings are accepted here rather than asserted
# against. The check that matters is that the label is a KNOWN value: a blank or
# unmapped recipient type still fails `test_ac6_every_recipient_type_is_a_known_label`.
ALLOWED_RECIPIENT_TYPES = {
    "owner", "lessee", "lienholder", "requestor",
    "authorized person", "authorized user",
}

# The recipient-type label carried by the letter this CR adds. Both spellings
# accepted for the reason above.
AUTHORIZED_TYPES = {"authorized person", "authorized user"}

# Values that must never reach a rendered letter or panel (FO-75 / NCNSS-550).
NULLISH = re.compile(r"^\s*(null|undefined|nan|none)\s*$", re.I)

AGE_DATE_MIN, AGE_DATE_MAX = 1, 32

# How many cases to survey per listing tab. Each costs ~40 s.
SURVEY_PLAN = [("To Process", 5), ("Aging", 4), ("Processed", 3)]

SHOTS = Path(__file__).resolve().parent.parent / "screenshots"

_AUTH_FILE = (
    Path(__file__).resolve().parent.parent / "auth" / os.getenv("NSM_ENV", "qa") / "staff-portal.json"
)

# ── Page-side extractors ───────────────────────────────────────────────────────

JS_CHECKBOX = """() => {
  const cb = Array.from(document.querySelectorAll('mat-checkbox'))
      .find(c => /Send LT-?264 to Authorized Person/i.test(c.textContent || ''));
  if (!cb) return null;
  const input = cb.querySelector('input[type=checkbox]');
  return {checked: !!input?.checked, disabled: !!input?.disabled};
}"""

JS_CHECKBOX_COUNT = """() => Array.from(document.querySelectorAll('mat-checkbox'))
    .filter(c => /Send LT-?264 to Authorized Person/i.test(c.textContent || '')).length"""

# Walk up from the checkbox until the enclosing node carries real content: that
# node is the Authorized Person Details panel.
JS_PANEL_TEXT = """() => {
  const cb = Array.from(document.querySelectorAll('mat-checkbox'))
      .find(c => /Send LT-?264 to Authorized Person/i.test(c.textContent || ''));
  if (!cb) return null;
  let n = cb;
  for (let d = 0; d < 10 && n.parentElement; d++) {
    n = n.parentElement;
    const t = (n.innerText || '').trim();
    if (t.length > 60) return t.slice(0, 1500);
  }
  return null;
}"""

JS_ISSUE_BUTTONS = """() => Array.from(document.querySelectorAll('button'))
    .map(b => ({text: (b.textContent || '').trim(), disabled: b.disabled}))
    .filter(b => /issue/i.test(b.text))"""

# Parse TRACK LT-264 by HEADER NAME, never by column position — the grid has a
# blank header between AGE DATE and STATUS, so positional indexing is fragile.
JS_TRACK_TABLE = """() => {
  const t = document.querySelector('table');
  if (!t) return null;
  const head = Array.from(t.querySelectorAll('thead th')).map(x => x.innerText.trim());
  const rows = Array.from(t.querySelectorAll('tbody tr'))
      .map(r => Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim()))
      .filter(r => r.length > 1 && r.some(c => c));
  return {head, rows: rows.map(cells => {
      const o = {};
      head.forEach((h, i) => { if (h) o[h] = cells[i] ?? ''; });
      return o;
  })};
}"""


# ── Survey ─────────────────────────────────────────────────────────────────────

def _probe_case(page, listing, tab, index):
    """Open case `index` on `tab` and snapshot its Authorized Person surface."""
    rec = {"tab": tab, "index": index}

    listing._dismiss_cdk_overlay()
    page.locator(f'[role="tab"]:has-text("{tab}")').first.click(timeout=20_000)
    page.wait_for_timeout(2600)
    if index >= listing.vin_links.count():
        return None
    listing.select_application(index)
    rec["url"] = page.url

    listing._dismiss_cdk_overlay()
    listing.check_dci_tab.first.click(timeout=20_000)
    page.wait_for_timeout(3200)

    body = page.locator("body").inner_text()
    rec["has_panel_heading"] = PANEL_HEADING in body
    rec["checkbox"] = page.evaluate(JS_CHECKBOX)
    rec["checkbox_count"] = page.evaluate(JS_CHECKBOX_COUNT)
    rec["panel_text"] = page.evaluate(JS_PANEL_TEXT)
    rec["panel_name"] = _field(rec["panel_text"], "Name")
    rec["panel_address"] = _field(rec["panel_text"], "Address")
    rec["issue_buttons"] = page.evaluate(JS_ISSUE_BUTTONS)
    # "Already issued" is inferred from the absence of the issuance button — the
    # button is removed once LT-264/LT-264G exist (FO-37 forbids re-issue).
    rec["issued"] = not any(re.search(ISSUE_264_RE, b["text"], re.I) for b in rec["issue_buttons"])

    try:
        listing._dismiss_cdk_overlay()
        listing.track_lt264_tab.first.click(timeout=20_000)
        page.wait_for_timeout(3500)
        rec["track"] = page.evaluate(JS_TRACK_TABLE)
    except Exception as exc:                      # tab blocked (e.g. BR-30) or absent
        rec["track"] = None
        rec["track_error"] = f"{type(exc).__name__}: {exc}"[:200]

    return rec


@pytest.fixture(scope="module")
def ap_survey(browser: Browser):
    """One read-only pass over real LT-262 cases; every test reads this snapshot."""
    SHOTS.mkdir(exist_ok=True)
    ctx = browser.new_context(storage_state=str(_AUTH_FILE), timezone_id="America/New_York")
    page = ctx.new_page()
    cases, errors = [], []
    try:
        go_to_staff_dashboard(page)
        dash = StaffDashboardPage(page)
        listing = Lt262ListingPage(page)
        dash.navigate_to_lt262_listing()
        page.wait_for_timeout(3000)
        list_url = page.url

        for tab, n in SURVEY_PLAN:
            for i in range(n):
                try:
                    page.goto(list_url, timeout=60_000)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1800)
                    rec = _probe_case(page, listing, tab, i)
                    if rec is None:
                        break
                    cases.append(rec)
                    if rec["checkbox"] and not [c for c in cases[:-1] if c["checkbox"]]:
                        page.screenshot(path=str(SHOTS / "tw26162855_ap_panel.png"), full_page=True)
                except Exception as exc:
                    errors.append({"tab": tab, "index": i, "error": f"{type(exc).__name__}: {exc}"[:200]})
    finally:
        page.close()
        ctx.close()

    survey = {"cases": cases, "errors": errors}
    print(f"\n[ap_survey] {len(cases)} cases surveyed, {len(errors)} nav errors")
    for c in cases:
        cb = c.get("checkbox")
        print(f"  {c['tab']}[{c['index']}] panel={c['has_panel_heading']} "
              f"checkbox={'-' if not cb else f'''checked={cb['checked']} disabled={cb['disabled']}'''} "
              f"issued={c['issued']} track_rows={len((c.get('track') or {}).get('rows', []))}")
    return survey


def with_panel(survey):
    return [c for c in survey["cases"] if c.get("checkbox")]


def without_panel(survey):
    return [c for c in survey["cases"] if not c.get("checkbox")]


def track_rows(survey):
    """Every TRACK LT-264 row across every surveyed case, tagged with its case."""
    out = []
    for c in survey["cases"]:
        for row in (c.get("track") or {}).get("rows", []):
            out.append((c, row))
    return out


def authorized_rows(case):
    """Track LT-264 rows belonging to the authorized person on a single case."""
    return [
        r for r in (case.get("track") or {}).get("rows", [])
        if (r.get("RECIPIENT TYPE") or "").strip().lower() in AUTHORIZED_TYPES
    ]


def issued_with_track(survey):
    """Post-issuance cases whose Track LT-264 grid actually returned rows."""
    return [
        c for c in survey["cases"]
        if c["issued"] and c.get("checkbox") and (c.get("track") or {}).get("rows")
    ]


def _field(panel_text, label):
    """Value following a `label` line in the panel's rendered text."""
    lines = [ln.strip() for ln in (panel_text or "").splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if ln.lower() == label.lower() and i + 1 < len(lines):
            return lines[i + 1]
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# AC-1 — Authorized Person Details panel on CHECK DCI AND NMVTIS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.tw26162855
def test_ac1_panel_renders_with_name_address_and_checkbox(ap_survey):
    """AC-1: the panel shows the AP's name and address plus the send checkbox."""
    assert ap_survey["cases"], (
        f"Survey opened no LT-262 case at all — cannot evaluate any AC. "
        f"Errors: {ap_survey['errors']}"
    )
    panelled = with_panel(ap_survey)
    assert panelled, (
        f"No surveyed case exposed the '{PANEL_HEADING}' panel across "
        f"{len(ap_survey['cases'])} cases, so AC-1 is unproven on this env."
    )

    for case in panelled:
        text = case["panel_text"] or ""
        assert PANEL_HEADING in text, (
            f"{case['url']}: checkbox present but heading '{PANEL_HEADING}' missing from panel"
        )
        name = _field(text, "Name")
        address = _field(text, "Address")
        assert name, f"{case['url']}: panel has no Name value"
        assert address, f"{case['url']}: panel has no Address value"
        assert re.search(CHECKBOX_LABEL_RE, text, re.I), (
            f"{case['url']}: checkbox label missing from the panel body"
        )


@pytest.mark.tw26162855
def test_ac1_1_panel_only_when_authorized_person_exists(ap_survey):
    """AC-1.1: panel and checkbox appear together, and only when an AP exists.

    Asserted as a biconditional over every surveyed case, so a case that renders
    the heading without the control (or the reverse) fails.
    """
    assert ap_survey["cases"], "Survey opened no LT-262 case"
    for case in ap_survey["cases"]:
        has_cb = case["checkbox"] is not None
        assert has_cb == case["has_panel_heading"], (
            f"{case['url']}: panel heading present={case['has_panel_heading']} but "
            f"checkbox present={has_cb} — the section must render as a unit"
        )

    assert without_panel(ap_survey), (
        "Every surveyed case carried an authorized person, so the negative half of "
        "AC-1.1 (panel suppressed when none exists) was never exercised."
    )


@pytest.mark.tw26162855
def test_ac1_panel_renders_exactly_once(ap_survey):
    """AC-1: exactly one send checkbox per case — a duplicated panel would let
    staff opt in twice and is the shape a double-render defect takes."""
    panelled = with_panel(ap_survey)
    assert panelled, "No case with the Authorized Person panel was surveyed"
    for case in panelled:
        assert case["checkbox_count"] == 1, (
            f"{case['url']}: found {case['checkbox_count']} 'Send LT-264 to "
            f"Authorized Person?' checkboxes, expected exactly 1"
        )


@pytest.mark.tw26162855
def test_ac1_panel_never_renders_nullish_values(ap_survey):
    """FO-75 / NCNSS-550: a literal 'null' must never surface as a name or address.

    The AP section is optional on the LT-260, so its fields are the most likely
    place for an unguarded null to reach a letter that a court then rejects.
    """
    panelled = with_panel(ap_survey)
    assert panelled, "No case with the Authorized Person panel was surveyed"
    for case in panelled:
        for label in ("Name", "Address"):
            value = _field(case["panel_text"], label)
            assert value and not NULLISH.match(value), (
                f"{case['url']}: Authorized Person {label} rendered as {value!r}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-2 — issuance buttons
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.tw26162855
def test_ac2_issue_button_coexists_with_panel(ap_survey):
    """AC-2: on a case still awaiting issuance, the AP panel and the
    'Issue LT-264 and LT-264 Garage' action are present together."""
    pending = [c for c in with_panel(ap_survey) if not c["issued"]]
    assert pending, (
        "No pre-issuance case carried the Authorized Person panel, so the panel/"
        "button pairing was never exercised."
    )
    for case in pending:
        labels = [b["text"] for b in case["issue_buttons"]]
        assert any(re.search(ISSUE_264_RE, t, re.I) for t in labels), (
            f"{case['url']}: AP panel shown but no LT-264/Garage issue action among {labels}"
        )


@pytest.mark.tw26162855
def test_ac2_no_owner_arm_reported(ap_survey):
    """AC-2 (no-owner arm): report whether QA holds a case showing BOTH
    'Issue LT-262B' and 'Issue LT-264 and LT-264 Garage'.

    This does not assert the gating rule — see the module docstring: no
    deterministic no-owner fixture exists (`VIN_NO_OWNERS` is a placeholder). It
    asserts only the part that IS checkable without one: wherever both buttons
    appear together, an Authorized Person panel must be the reason.
    """
    dual = [
        c for c in ap_survey["cases"]
        if any(re.search(ISSUE_262B_RE, b["text"], re.I) for b in c["issue_buttons"])
        and any(re.search(ISSUE_264_RE, b["text"], re.I) for b in c["issue_buttons"])
    ]
    print(f"\n[AC-2] dual-button (262B + 264/G) cases in survey: {len(dual)}")
    for case in dual:
        assert case["checkbox"] is not None, (
            f"{case['url']}: both Issue LT-262B and Issue LT-264/Garage are shown but no "
            f"Authorized Person panel — AC-2 makes the AP the only reason for that pairing"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-3 / AC-4 — checkbox lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.tw26162855
def test_ac4_checkbox_defaults_unticked_before_issuance(ap_survey):
    """AC-4 (default): the checkbox is UNTICKED until staff opt in.

    A default-ticked box would silently mail certified letters to a third party
    on every case that happens to carry an authorized person.
    """
    pending = [c for c in with_panel(ap_survey) if not c["issued"]]
    assert pending, "No pre-issuance case with the Authorized Person panel was surveyed"
    for case in pending:
        assert case["checkbox"]["checked"] is False, (
            f"{case['url']}: 'Send LT-264 to Authorized Person?' is TICKED by default"
        )


@pytest.mark.tw26162855
def test_ac2_checkbox_editable_before_issuance(ap_survey):
    """AC-2: before issuance the checkbox must be enabled — it is the control the
    LT-264/Garage button's enablement is gated on."""
    pending = [c for c in with_panel(ap_survey) if not c["issued"]]
    assert pending, "No pre-issuance case with the Authorized Person panel was surveyed"
    for case in pending:
        assert case["checkbox"]["disabled"] is False, (
            f"{case['url']}: checkbox is disabled while the case is still awaiting "
            f"issuance — staff can never opt in"
        )


@pytest.mark.tw26162855
def test_ac3_checkbox_disabled_after_issuance(ap_survey):
    """AC-3: once the LT-264/G forms are generated, the checkbox is disabled."""
    issued = [c for c in with_panel(ap_survey) if c["issued"]]
    assert issued, (
        "No post-issuance case carried the Authorized Person panel, so AC-3 "
        "(checkbox disabled after generation) was never exercised."
    )
    for case in issued:
        assert case["checkbox"]["disabled"] is True, (
            f"{case['url']}: LT-264/G already issued but the checkbox is still "
            f"editable — staff could re-opt-in after the fact (FO-37)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-4 — the letter itself (asserted through Track LT-264, which is the
# observable record that an LT-264 was generated for a given recipient)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.tw26162855
def test_ac4_ticked_at_issuance_generates_authorized_person_letter(ap_survey):
    """AC-4: when the checkbox was ticked at issuance, an LT-264 exists for the
    authorized person IN ADDITION TO the owner / lessee / lienholder letters."""
    opted_in = [c for c in issued_with_track(ap_survey) if c["checkbox"]["checked"]]
    assert opted_in, (
        "No surveyed case had the checkbox ticked at issuance, so AC-4's positive "
        "path (an authorized-person LT-264 is generated) was never exercised."
    )
    for case in opted_in:
        ap_rows = authorized_rows(case)
        all_rows = case["track"]["rows"]
        assert ap_rows, (
            f"{case['url']}: checkbox was ticked at issuance but no authorized-person "
            f"row exists on Track LT-264. Rows found: "
            f"{[(r.get('RECIPIENT'), r.get('RECIPIENT TYPE')) for r in all_rows]}"
        )
        # "in addition to" — the AP letter must not have displaced the others.
        other_types = {
            (r.get("RECIPIENT TYPE") or "").strip().lower() for r in all_rows
        } - AUTHORIZED_TYPES
        assert other_types, (
            f"{case['url']}: the authorized person is the ONLY recipient; the owner/"
            f"lessee/lienholder letters appear to have been displaced rather than added to"
        )


@pytest.mark.tw26162855
def test_ac4_unticked_at_issuance_generates_no_authorized_person_letter(ap_survey):
    """AC-4 inverse (negative control): leaving the checkbox unticked must produce
    no authorized-person letter at all.

    This is the assertion that makes the positive path meaningful — without it, a
    build that mails the authorized person unconditionally would still pass
    `test_ac4_ticked_...`.
    """
    opted_out = [c for c in issued_with_track(ap_survey) if not c["checkbox"]["checked"]]
    assert opted_out, (
        "No surveyed case was issued with the checkbox unticked, so the negative "
        "control for AC-4 was never exercised."
    )
    for case in opted_out:
        ap_rows = authorized_rows(case)
        assert not ap_rows, (
            f"{case['url']}: checkbox was NOT ticked at issuance yet an authorized-person "
            f"LT-264 was still generated: {[(r.get('RECIPIENT'), r.get('RECIPIENT TYPE')) for r in ap_rows]} "
            f"— a certified letter went to a third party nobody opted in"
        )


@pytest.mark.tw26162855
def test_ac6_authorized_person_letter_is_a_certified_lt264(ap_survey):
    """AC-6: the authorized person's letter is an LT-264 — the certified form —
    and not merely a garage copy."""
    with_ap = [c for c in issued_with_track(ap_survey) if authorized_rows(c)]
    assert with_ap, "No surveyed case carried an authorized-person Track LT-264 row"
    for case in with_ap:
        for row in authorized_rows(case):
            form = (row.get("FORM TYPE") or "").strip()
            assert re.fullmatch(r"LT-?264", form, re.I), (
                f"{case['url']}: the authorized person's letter is FORM TYPE {form!r}; "
                f"AC-6 requires the certified LT-264"
            )


@pytest.mark.tw26162855
def test_ac7_authorized_person_letter_ages_with_its_peers(ap_survey):
    """AC-7: the authorized person's LT-264 is on the SAME 32-day clock as the
    other recipients on its case.

    Asserted as equality against the sibling rows rather than just range-checking,
    because a letter that ages on its own offset would drift out of step with
    AC-8's all-delivered gate even while staying inside 1–32.
    """
    with_ap = [c for c in issued_with_track(ap_survey) if authorized_rows(c)]
    assert with_ap, "No surveyed case carried an authorized-person Track LT-264 row"
    compared = 0
    for case in with_ap:
        ages = {
            (r.get("RECIPIENT TYPE") or "").strip(): (r.get("AGE DATE") or "").strip()
            for r in case["track"]["rows"]
        }
        populated = {k: v for k, v in ages.items() if v}
        if len(populated) < 2:
            continue
        assert len(set(populated.values())) == 1, (
            f"{case['url']}: Age Dates diverge across recipients on one case: {populated}"
        )
        compared += 1
    assert compared, (
        "No case had Age Dates on two or more recipients, so peer-equality was never checked"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AC-6 / AC-7 — Track LT-264
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.tw26162855
def test_ac6_track_table_exposes_recipient_type(ap_survey):
    """AC-6: the Track LT-264 grid carries the columns the AP row needs.

    RECIPIENT TYPE is the column that distinguishes the new fourth recipient from
    owner/lessee/lienholder, so its presence is a precondition for AC-6 at all.
    """
    tracked = [c for c in ap_survey["cases"] if (c.get("track") or {}).get("head")]
    assert tracked, "No surveyed case exposed a Track LT-264 grid"
    required = {"RECIPIENT", "RECIPIENT ADDRESS", "FORM TYPE", "RECIPIENT TYPE", "AGE DATE", "STATUS"}
    for case in tracked:
        head = {h.upper() for h in case["track"]["head"] if h}
        missing = required - head
        assert not missing, f"{case['url']}: Track LT-264 missing columns {sorted(missing)}"


@pytest.mark.tw26162855
def test_ac6_every_recipient_type_is_a_known_label(ap_survey):
    """AC-6: every tracked LT-264 carries a recognised recipient type.

    Guards OQ-5 from the blank side: a new fourth recipient that ships with an
    empty or unmapped type label is user-visible on this grid and on the
    LT-264A/B checklists, and would otherwise pass a looser 'row exists' check.
    """
    rows = track_rows(ap_survey)
    assert rows, "No Track LT-264 rows across the whole survey"
    seen = set()
    for case, row in rows:
        rtype = (row.get("RECIPIENT TYPE") or "").strip()
        assert rtype, f"{case['url']}: tracked row {row!r} has a blank RECIPIENT TYPE"
        assert rtype.lower() in ALLOWED_RECIPIENT_TYPES, (
            f"{case['url']}: unrecognised RECIPIENT TYPE {rtype!r}; "
            f"expected one of {sorted(ALLOWED_RECIPIENT_TYPES)}"
        )
        seen.add(rtype)
    print(f"\n[AC-6] recipient types observed on QA: {sorted(seen)}")


@pytest.mark.tw26162855
def test_ac6_recipient_name_and_address_populated(ap_survey):
    """AC-6: each tracked row names a real recipient at a real address.

    A certified letter is physically mailed to whatever this row holds, so a
    blank or 'null' value here is a mis-delivery, not a cosmetic defect (FO-75).
    """
    rows = track_rows(ap_survey)
    assert rows, "No Track LT-264 rows across the whole survey"
    for case, row in rows:
        for col in ("RECIPIENT", "RECIPIENT ADDRESS"):
            val = (row.get(col) or "").strip()
            assert val, f"{case['url']}: tracked row has empty {col}: {row!r}"
            assert not NULLISH.match(val), f"{case['url']}: {col} rendered as {val!r}"


@pytest.mark.tw26162855
def test_ac6_only_lt264_is_certified(ap_survey):
    """BR-79: only the LT-264 is certified mail, so only it can carry a tracking
    number. An LT-264 Garage row with one would mean the AP's garage copy was
    mailed certified too."""
    rows = track_rows(ap_survey)
    assert rows, "No Track LT-264 rows across the whole survey"
    for case, row in rows:
        form = (row.get("FORM TYPE") or "").strip()
        tracking = (row.get("TRACKING NUMBER") or "").strip()
        if tracking and re.search(r"garage", form, re.I):
            pytest.fail(
                f"{case['url']}: {form} row carries tracking number {tracking!r} — "
                f"BR-79 makes only the LT-264 certified"
            )


@pytest.mark.tw26162855
def test_ac7_age_date_within_32_day_window(ap_survey):
    """AC-7: every tracked LT-264 ages on the same 1–32 day clock.

    The AP's letter is subject to the same window, and AC-8's auto-issuance
    decision keys off it, so an out-of-range or non-numeric Age Date on ANY row
    corrupts the gate for the whole case.
    """
    rows = track_rows(ap_survey)
    assert rows, "No Track LT-264 rows across the whole survey"
    checked = 0
    for case, row in rows:
        raw = (row.get("AGE DATE") or "").strip()
        if not raw:
            continue                      # not yet mailed — no clock started
        assert raw.isdigit(), f"{case['url']}: AGE DATE {raw!r} is not a day count"
        age = int(raw)
        assert AGE_DATE_MIN <= age <= AGE_DATE_MAX, (
            f"{case['url']}: AGE DATE {age} outside the {AGE_DATE_MIN}–{AGE_DATE_MAX} window"
        )
        checked += 1
    assert checked, "No tracked row had an Age Date, so the 32-day window was never checked"


# ═══════════════════════════════════════════════════════════════════════════════
# AC-5 / AC-8 / AC-9 — the downstream surfaces, read from the one case that
# actually has an authorized-person letter on it
# ═══════════════════════════════════════════════════════════════════════════════

JS_CORRESPONDENCE_ROWS = """() => {
  const dlg = document.querySelector('mat-dialog-container') || document.body;
  return [...dlg.querySelectorAll('table tbody tr')]
    .filter(r => (r.textContent || '').trim())
    .map(r => {
      const cells = [...r.querySelectorAll('td')].map(c => c.innerText.trim());
      const attr = e => (e.getAttribute && (e.getAttribute('title') || e.getAttribute('aria-label'))) || '';
      const hasReprint = [...r.querySelectorAll('button,a,span,mat-icon,img,[title],[aria-label]')]
          .some(e => /reprint/i.test((e.textContent || '') + ' ' + attr(e) + ' ' + (e.className || '')));
      const hasDownload = [...r.querySelectorAll('span.table-link,a,button')]
          .some(e => /download/i.test(e.textContent || ''));
      return {cells, text: cells.join(' | '), hasReprint, hasDownload};
    });
}"""

# The LT-264A/B recipient selection list on TRACK LT-264.
#
# These options render one per non-garage LT-264 recipient, positioned in the
# grid's blank column, and carry no inline text of their own (only the
# "A hearing was requested…" checkbox is text-labelled). That was reviewed by QA
# 2026-08-12 and ruled NOT a defect: the on-screen grid makes the pairing clear
# to the user and the generated letters mark the correct recipients.
#
# The practical consequence for THIS suite is only that a recipient option can be
# identified by COUNT against the tracked recipients rather than by reading a
# label — which is what `test_ac8_authorized_person_offered_in_lt264a_recipient_selection`
# asserts. It is a test-technique constraint, not a product finding.
JS_PARTICIPANT_CHECKBOXES = """() => {
  const all = [...document.querySelectorAll('mat-checkbox')];
  const labelled = all.filter(c => (c.textContent || '').trim());
  const blank = all.filter(c => !(c.textContent || '').trim());
  const state = c => {
    const i = c.querySelector('input[type=checkbox]');
    return {checked: !!i?.checked, disabled: !!i?.disabled,
            ariaLabel: i?.getAttribute('aria-label') || null,
            ariaLabelledBy: i?.getAttribute('aria-labelledby') || null};
  };
  return {
    total: all.length,
    labelled: labelled.map(c => (c.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 120)),
    participants: blank.map(state),
  };
}"""


@pytest.fixture(scope="module")
def ap_letters(ap_survey, browser: Browser):
    """Second pass over the ONE case that carries an authorized-person LT-264.

    Collects the Correspondence History rows (AC-5), the LT-264A/B participant
    selection list (AC-8), and the owner letter's extracted PDF text (AC-9).

    Read-only in the sense that matters: it opens a modal, downloads a PDF, and
    reveals the participant list by selecting the "did not sign" radio. It never
    clicks Save / Yes, so nothing is persisted and no letter is ever issued.
    """
    candidates = [c for c in issued_with_track(ap_survey) if authorized_rows(c)]
    if not candidates:
        return {"available": False, "reason": "no surveyed case carries an authorized-person LT-264"}

    case = candidates[0]
    ap_row = authorized_rows(case)[0]
    result = {
        "available": True,
        "url": case["url"],
        "ap_recipient": ap_row.get("RECIPIENT", ""),
        "correspondence": [],
        "participants": None,
        "participant_case": None,
        "eligible_recipients": [],
        "owner_pdf_text": "",
        "notes": [],
    }

    ctx = browser.new_context(
        storage_state=str(_AUTH_FILE), timezone_id="America/New_York", accept_downloads=True
    )
    page = ctx.new_page()
    try:
        page.goto(case["url"], timeout=60_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # ── AC-5: Correspondence History ────────────────────────────────────
        try:
            page.locator(
                'button:has-text("View Correspondence"), a:has-text("View Correspondence"), '
                'span:has-text("View Correspondence/Documents")'
            ).first.click(timeout=20_000)
            page.wait_for_timeout(4000)
            result["correspondence"] = page.evaluate(JS_CORRESPONDENCE_ROWS)
            SHOTS.mkdir(exist_ok=True)
            page.screenshot(path=str(SHOTS / "tw26162855_correspondence.png"), full_page=True)

            # ── AC-9: cc block on the OWNER's LT-264 ────────────────────────
            try:
                from PyPDF2 import PdfReader
            except ImportError:                                  # maintained package name
                from pypdf import PdfReader
            dl_dir = Path(__file__).resolve().parent.parent / "downloads" / "tw26162855"
            dl_dir.mkdir(parents=True, exist_ok=True)
            dlg = page.locator("mat-dialog-container").last
            link = dlg.locator('tr:has-text("LT-264") span.table-link, tr:has-text("LT-264") a').filter(
                has_text=re.compile(r"^\s*Download\s*$", re.I)
            ).first
            if link.count():
                link.scroll_into_view_if_needed()
                with page.expect_download(timeout=25_000) as info:
                    link.click()
                dest = dl_dir / (info.value.suggested_filename or "lt264.pdf")
                info.value.save_as(str(dest))
                result["owner_pdf_text"] = "".join(
                    (p.extract_text() or "") for p in PdfReader(str(dest)).pages
                )
                result["pdf_path"] = str(dest)
            else:
                result["notes"].append("no Download control on any LT-264 correspondence row")
            page.keyboard.press("Escape")
            page.wait_for_timeout(1500)
        except Exception as exc:
            result["notes"].append(f"correspondence: {type(exc).__name__}: {exc}"[:220])

        # ── AC-8: LT-264A/B participant selection list ──────────────────────
        # The list only renders once a case has reached the post-32-day decision
        # point (Age Date 32), so walk candidates until one exposes it rather
        # than assuming the first is far enough along.
        #
        # Cases drift between listing tabs as data ages, so a survey of the first
        # N rows per tab does not reliably include one at the decision point —
        # that produced a spurious "no selection reachable" failure. Known
        # decision-point cases are therefore tried FIRST, with the surveyed
        # candidates as fallback. If a pinned case is re-seeded it simply fails
        # its goto and the loop moves on.
        pinned = [
            {"url": "https://nsm-qa.nc.verifi.dev/pages/ncdot-notice-and-storage/"
                    "LT-262/97730e89-acd2-45a7-a8b2-3e3e2848701f/details?tab=Aging",
             "track": None, "__pinned": True},
            {"url": "https://nsm-qa.nc.verifi.dev/pages/ncdot-notice-and-storage/"
                    "LT-262/d4ac53d4-241d-4817-9008-0a483f6cc99e/details",
             "track": None, "__pinned": True},
        ]
        for cand in pinned + candidates:
            try:
                page.goto(cand["url"], timeout=60_000)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2500)
                listing = Lt262ListingPage(page)
                listing._dismiss_cdk_overlay()
                listing.track_lt264_tab.first.click(timeout=20_000)
                page.wait_for_timeout(3500)

                # Reveal the list when the decision is still open. The clickable
                # node of a mat-radio-button is its inner <label>, not the host
                # element — clicking the host times out.
                radio = page.locator("mat-radio-button:has-text('did not sign') label")
                for i in range(radio.count()):
                    try:
                        radio.nth(i).click(timeout=5000, force=True)
                        page.wait_for_timeout(2500)
                        break
                    except Exception:
                        continue

                snap = page.evaluate(JS_PARTICIPANT_CHECKBOXES)
                if snap["participants"]:
                    # Non-garage LT-264 rows are the recipients eligible for LT-264A.
                    # Pinned cases carry no surveyed grid, so read it live here;
                    # surveyed candidates reuse the snapshot already captured.
                    grid = cand.get("track") or page.evaluate(JS_TRACK_TABLE) or {}
                    eligible = [
                        r for r in grid.get("rows", [])
                        if not re.search(r"garage", r.get("FORM TYPE") or "", re.I)
                    ]
                    result["participants"] = snap
                    result["participant_case"] = cand["url"]
                    result["eligible_recipients"] = [
                        (r.get("RECIPIENT"), r.get("RECIPIENT TYPE")) for r in eligible
                    ]
                    SHOTS.mkdir(exist_ok=True)
                    page.screenshot(path=str(SHOTS / "tw26162855_participants.png"), full_page=True)
                    break
            except Exception as exc:
                result["notes"].append(
                    f"participants[{cand['url'][-12:]}]: {type(exc).__name__}: {exc}"[:200]
                )
    finally:
        page.close()
        ctx.close()

    print(f"\n[ap_letters] case={result['url']}")
    print(f"  ap recipient      : {result['ap_recipient']!r}")
    print(f"  correspondence    : {len(result['correspondence'])} rows")
    for r in result["correspondence"][:12]:
        print(f"     {r['text'][:110]!r} reprint={r['hasReprint']} download={r['hasDownload']}")
    print(f"  participant case  : {result['participant_case']}")
    print(f"  eligible (LT-264) : {result['eligible_recipients']}")
    print(f"  participants      : {result['participants']}")
    print(f"  owner pdf chars   : {len(result['owner_pdf_text'])}")
    print(f"  notes             : {result['notes']}")
    return result


def _require(letters):
    if not letters.get("available"):
        pytest.fail(
            f"No case with an authorized-person LT-264 was surveyed, so this AC could not "
            f"be evaluated: {letters.get('reason')}"
        )


@pytest.mark.tw26162855
def test_ac5_correspondence_entry_exists_for_lt264(ap_letters):
    """AC-5: a Forms Correspondence entry exists for the issued LT-264 set."""
    _require(ap_letters)
    rows = ap_letters["correspondence"]
    assert rows, (
        f"Correspondence History opened no rows for {ap_letters['url']} "
        f"(notes: {ap_letters['notes']})"
    )
    lt264 = [r for r in rows if re.search(r"LT-?264", r["text"], re.I)]
    assert lt264, (
        f"No LT-264 correspondence entry on a case whose Track grid lists LT-264 letters. "
        f"Rows: {[r['text'][:70] for r in rows]}"
    )


@pytest.mark.tw26162855
def test_ac5_lt264_entries_offer_send_for_reprinting(ap_letters):
    """AC-5: the LT-264 correspondence entries expose Send for Reprinting.

    Per BR-86 the control is withdrawn once LT-263/264A/264B is issued, so this
    asserts availability on a case that has NOT yet reached that decision.
    """
    _require(ap_letters)
    lt264 = [r for r in ap_letters["correspondence"] if re.search(r"LT-?264", r["text"], re.I)]
    assert lt264, "No LT-264 correspondence entry to check the reprint control on"
    assert any(r["hasReprint"] for r in lt264), (
        f"No LT-264 correspondence row offers Send for Reprinting (§3.39). "
        f"Rows: {[(r['text'][:70], r['hasReprint']) for r in lt264]}"
    )


@pytest.mark.tw26162855
def test_ac8_authorized_person_offered_in_lt264a_recipient_selection(ap_letters):
    """AC-8: the authorized person is one of the LT-264A/B recipient checkboxes.

    Without this the AP can receive the original LT-264 but be silently dropped
    from the follow-up letter — the exact failure AC-8 exists to prevent.

    Asserted by COUNT rather than by label, because the options carry no inline
    text or ARIA name: the selection list must offer one option per DISTINCT
    non-garage LT-264 recipient. If the authorized person were excluded, this
    case would offer one fewer option than it has distinct tracked recipients.

    Counted on DISTINCT (recipient, type) pairs, not raw grid rows. The Track
    LT-264 grid can render the same recipient twice — observed live on case
    N26-1073737, where 'WORLD OMNI FINANCIAL CORP / Lienholder' appears on two
    identical rows while Correspondence History holds only one LT-264 for it.
    The selection list correctly de-duplicates, so comparing against raw rows
    produced a false failure here.
    """
    _require(ap_letters)
    snap = ap_letters["participants"]
    assert snap and snap["participants"], (
        f"No LT-264A/B participant selection was reachable on any candidate case "
        f"(notes: {ap_letters['notes']})"
    )
    eligible = ap_letters["eligible_recipients"]
    assert any(t and t.strip().lower() in AUTHORIZED_TYPES for _, t in eligible), (
        f"The case used for this check has no authorized-person LT-264: {eligible}"
    )
    # De-duplicate: the grid may repeat a recipient row (see docstring), while the
    # selection list offers one option per real recipient.
    distinct = {(str(r).strip(), str(t).strip()) for r, t in eligible}
    assert len(snap["participants"]) == len(distinct), (
        f"{ap_letters['participant_case']}: {len(snap['participants'])} recipient "
        f"checkboxes offered for {len(distinct)} DISTINCT tracked LT-264 recipients "
        f"{sorted(distinct)} — the authorized person appears to be missing from the "
        f"LT-264A/B recipient selection "
        f"(raw grid rows were {len(eligible)}: {eligible})"
    )


@pytest.mark.tw26162855
def test_ac8_recipient_selection_option_set_is_well_formed(ap_letters):
    """AC-8 companion: the recipient option set is unambiguous at issuance.

    Asserts the option set is non-empty and that no option sits in an
    indeterminate state, which would leave the LT-264A recipient set ambiguous.

    The options carry no inline text/ARIA name — reviewed by QA 2026-08-12 and
    ruled not a defect (the grid conveys the pairing on screen and the generated
    letters mark the right recipients), so nothing here asserts against labels.
    The counts are printed to keep the identification basis visible in run output.
    """
    _require(ap_letters)
    snap = ap_letters["participants"]
    assert snap and snap["participants"], "No participant selection list was reachable"
    print(
        f"\n[AC-8] {ap_letters['participant_case']}\n"
        f"  eligible LT-264 recipients : {ap_letters['eligible_recipients']}\n"
        f"  options offered            : {len(snap['participants'])}\n"
        f"  option states              : {snap['participants']}\n"
        f"  labelled controls          : {snap['labelled']}"
    )
    for p in snap["participants"]:
        assert isinstance(p["checked"], bool), (
            f"{ap_letters['participant_case']}: recipient option in an indeterminate "
            f"state {p!r} — the LT-264A recipient set would be ambiguous at issuance"
        )


@pytest.mark.tw26162855
def test_ac9_authorized_person_appears_in_cc_of_owner_letter(ap_letters):
    """AC-9: the authorized person is carried in the cc section of the LT-264.

    Asserted on the surname token from the Track grid's RECIPIENT value, because
    the letter renders a formatted full name that need not match the grid string
    character-for-character.
    """
    _require(ap_letters)
    text = ap_letters["owner_pdf_text"]
    assert text, (
        f"No LT-264 PDF text was extracted for {ap_letters['url']} "
        f"(notes: {ap_letters['notes']})"
    )
    recipient = (ap_letters["ap_recipient"] or "").strip()
    assert recipient, "Track grid gave no authorized-person recipient name to look for"
    tokens = [t for t in re.split(r"\s+", recipient) if len(t) > 2]
    flat = re.sub(r"\s+", " ", text)
    # Word-boundary, not substring: a bare `in` test would match the token "Auth"
    # against the letter's own "Authorized" heading and pass for the wrong reason.
    missing = [
        t for t in tokens
        if not re.search(rf"\b{re.escape(t)}\b", flat, re.I)
    ]
    print(f"\n[AC-9] recipient={recipient!r} tokens={tokens} "
          f"contiguous_match={bool(re.search(re.escape(recipient), flat, re.I))}")
    assert not missing, (
        f"Authorized person tokens {missing} absent from the issued LT-264 "
        f"(recipient={recipient!r}). AC-9 requires the authorized person in the cc "
        f"section of the owner/lessee/lienholder and garage forms."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Permissions
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.tw26162855
@pytest.mark.rbac
def test_rbac_fiscal_user_cannot_reach_lt264_issuance(fiscal_context: BrowserContext):
    """BR-46: the Fiscal User is scoped to Reports, so the Authorized Person panel
    and the LT-264 issuance action must be unreachable for that role.

    Cited as BR-46 (Fiscal Users → Reports module only), not BR-85, which is the
    unrelated Daily-Transmission-report download rule.
    """
    page = fiscal_context.new_page()
    try:
        go_to_staff_dashboard(page)
        # The fiscal shell is much smaller than the admin one; give it room, or a
        # slow load looks identical to a correctly-denied module.
        for _ in range(6):
            page.wait_for_timeout(2500)
            if page.locator("a").count() > 0:
                break
        assert page.locator("a").count() > 0, (
            "Fiscal portal rendered no navigation at all — 'RBAC denies LT-264' cannot "
            "be distinguished from 'the app never loaded'"
        )

        dash = StaffDashboardPage(page)
        try:
            dash.navigate_to_lt262_listing()
        except Exception:
            SHOTS.mkdir(exist_ok=True)
            page.screenshot(path=str(SHOTS / "tw26162855_fiscal_rbac.png"), full_page=True)
            return                          # module unreachable — the expected outcome
        page.wait_for_timeout(2500)
        SHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SHOTS / "tw26162855_fiscal_rbac.png"), full_page=True)

        body = page.locator("body").inner_text()
        assert page.locator('button:has-text("Issue LT-264")').count() == 0, (
            "Fiscal User can see the Issue LT-264 action — BR-46 violation"
        )
        assert PANEL_HEADING not in body, (
            "Fiscal User can see the Authorized Person Details panel — BR-46 violation"
        )
    finally:
        page.close()
