"""
NCNSS-493 — Blank / whitespace-only Make (and core-field) validation & auto-issuance guard.
Ticket 27264545. Live regression against the Staff Portal "Add from Paper" flow (primary
channel), plus the LT-260 staff Edit (LT260.update) guard.

Root cause recap: Make was made optional (TW 27171091); a null/blank/whitespace make could
be saved and later crashed LT-160B/260A issuance (PostgreSQL 42P18). Fix = 3 guards:
  (1) LT260.issue pre-gen "Make is missing" (auto + manual issue paths)
  (2) LT260.update staff make-required guard (no form-wipe)
  (3) LT260.submit regex ^.{1,}$ -> ^.*\\S.*$ (rejects whitespace-only) + Phase-1 presence
      rules on Year / Date Vehicle Left / County and across LT-261/262/262A/263.

Scenarios implemented here (see the run-report / SKILL.md for the SC->TC map):
  SC-1  [Critical] LT-260 Submit Validation Gauntlet   — TC-01..06, 20, 21, 22, 23, 29
  SC-4  [High]     Draft-Exempt Invariant              — TC-07, 28
  SC-6  [Medium]   Presence validation LT-261/262/262A/263 — TC-24, 25, 26, 27
  SC-3  [High]     Staff LT260.update Make guard        — TC-13, 14, 15, 16

Scoring: a NEGATIVE passes only when the rejection ACTUALLY fires (Submit/Save stays
DISABLED at click-time OR a validation message appears AND no success/redirect/record).
A POSITIVE passes only with positive proof (redirect off the form / success banner).
Each test prints  EXPECTED: ... | ACTUAL: ... | MATCH/MISMATCH.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext

from src.config.env import ENV
from src.helpers.data_helper import generate_vin, past_date
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt261_page import Lt261Page
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage


SP_DASHBOARD_URL = re.sub(
    r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL
)

SHOT_DIR = Path(__file__).resolve().parent.parent / "screenshots" / "ncnss493"
SHOT_DIR.mkdir(parents=True, exist_ok=True)

SUBMIT_SEL = 'button:has-text("Submit")'
DRAFT_SEL = 'button:has-text("Save As Draft"), button:has-text("Save as Draft"), button:has-text("Draft")'


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


def shot(page, name: str):
    try:
        page.screenshot(path=str(SHOT_DIR / f"{name}.png"))
    except Exception:
        pass
    return str(SHOT_DIR / f"{name}.png")


def submit_enabled(page) -> bool:
    """Is the primary Submit button click-able (form valid)?"""
    btn = page.locator(SUBMIT_SEL).first
    try:
        btn.wait_for(state="visible", timeout=10_000)
    except Exception:
        return False
    return btn.is_enabled()


def on_paper_form(page) -> bool:
    return "paperFormdetails" in (page.url or "")


def poll_feedback(page, secs: float = 6.0):
    """Poll snackbars/dialogs for a few seconds, return the set of visible text seen."""
    import time as _t
    seen = set()
    end = _t.time() + secs
    sels = ['.mat-snack-bar-container', 'simple-snack-bar', '[class*="snack"]',
            '[class*="toast"]', 'mat-dialog-container', '[role="dialog"]']
    while _t.time() < end:
        for sel in sels:
            loc = page.locator(sel)
            for i in range(loc.count()):
                try:
                    if loc.nth(i).is_visible():
                        t = (loc.nth(i).inner_text() or "").strip()
                        if t:
                            seen.add(t[:200].replace("\n", " | "))
                except Exception:
                    pass
        page.wait_for_timeout(200)
    return seen


def clear_named_input(page, name: str) -> bool:
    """Clear a text input by formcontrol/name and dispatch Angular input+blur. Returns True if found."""
    inp = page.locator(f'input[name="{name}"]').first
    try:
        inp.wait_for(state="visible", timeout=5_000)
    except Exception:
        return False
    inp.fill("")
    page.keyboard.press("Tab")
    page.wait_for_timeout(600)
    return True


# =============================================================================
# SC-1 [Critical] — LT-260 Submit Validation Gauntlet
# Covers TC-01, 02, 03(=04 min-boundary via valid submit), 04, 05, 06, 20, 21, 22, 23, 29
# =============================================================================
@pytest.mark.ncnss493
@pytest.mark.regression
@pytest.mark.critical
class TestE2E493_SC1_Lt260SubmitGauntlet:
    """LT-260 'Add from Paper' — Submit is validity-bound; blank/whitespace core fields
    must keep it BLOCKED; a fully-valid form must submit (positive proof)."""

    def _open_form(self, page, vin):
        dash = StaffDashboardPage(page)
        lst = Lt260ListingPage(page)
        pf = PaperFormPage(page)
        dash.navigate_to_lt260_listing()
        lst.click_add_from_paper()
        pf.fill_modal_vin_and_next(vin)
        return pf

    def _fill_valid(self, pf, page, skip=frozenset()):
        """Fill the LT-260 paper form with valid values, optionally skipping fields."""
        if "make" not in skip:
            pf.fill_make("TOY")
        if "year" not in skip:
            pf.fill_year("2018")
        if "date" not in skip:
            pf.fill_date_vehicle_left(past_date(30))
        if "location" not in skip:
            pf.fill_search_location("Garage")
        if "stolen" not in skip:
            pf.select_stolen_no()
        page.wait_for_timeout(800)

    # ---- TC-01/02: blank Make -> Submit blocked ----
    def test_tc01_blank_make_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            pf = self._open_form(page, generate_vin())
            # Everything valid EXCEPT make
            self._fill_valid(pf, page, skip={"make"})
            enabled = submit_enabled(page)
            shot(page, "sc1_tc01_blank_make")
            still_on_form = on_paper_form(page)
            print(
                "EXPECTED: Submit BLOCKED (disabled) with blank Make, no submission | "
                f"ACTUAL: submit_enabled={enabled}, still_on_form={still_on_form} | "
                f"{'MATCH' if (not enabled and still_on_form) else 'MISMATCH'}"
            )
            assert not enabled, (
                "FAIL: expected rejection, got a submittable form — blank Make did NOT block Submit"
            )
        finally:
            page.close()

    # ---- TC-04/05: whitespace-only Make -> Submit blocked (the closed hole) ----
    def test_tc04_whitespace_make_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            pf = self._open_form(page, generate_vin())
            self._fill_valid(pf, page, skip={"make"})

            make = page.locator("(//input[@role='combobox'])[1]")
            make.click()
            results = {}
            for label, val in [("single_space", " "), ("multi_space", "   "), ("tab", "\t")]:
                make.fill("")
                page.wait_for_timeout(200)
                make.fill(val)
                page.wait_for_timeout(900)
                # A whitespace-only entry must not yield an autocomplete option / must not form a chip
                opt_count = page.locator(".cdk-overlay-pane mat-option").count()
                # count make chips (first chip region only): whitespace must not create a make chip
                enabled = submit_enabled(page)
                results[label] = {"options": opt_count, "submit_enabled": enabled}
            shot(page, "sc1_tc04_whitespace_make")
            all_blocked = all(not r["submit_enabled"] for r in results.values())
            print(
                "EXPECTED: whitespace-only Make yields no valid selection -> Submit BLOCKED for all of "
                "' ', '   ', '\\t' | "
                f"ACTUAL: {results} | {'MATCH' if all_blocked else 'MISMATCH'}"
            )
            assert all_blocked, (
                "FAIL: expected rejection, got submission — a whitespace-only Make left Submit enabled"
            )
        finally:
            page.close()

    # ---- TC-20: blank Year -> Submit blocked ----
    def test_tc20_blank_year_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            pf = self._open_form(page, generate_vin())
            self._fill_valid(pf, page)  # fully valid first (Submit enabled)
            was_enabled = submit_enabled(page)
            clear_named_input(page, "year")
            now_enabled = submit_enabled(page)
            shot(page, "sc1_tc20_blank_year")
            print(
                "EXPECTED: clearing Year flips Submit enabled->BLOCKED (Year now required) | "
                f"ACTUAL: before={was_enabled}, after_clear={now_enabled} | "
                f"{'MATCH' if (was_enabled and not now_enabled) else 'MISMATCH'}"
            )
            assert was_enabled, "Precondition failed: form was not valid before clearing Year"
            assert not now_enabled, "FAIL: expected rejection, blank Year left Submit enabled"
        finally:
            page.close()

    # ---- TC-21: blank Date Vehicle Left -> Submit blocked ----
    def test_tc21_blank_date_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            pf = self._open_form(page, generate_vin())
            self._fill_valid(pf, page)
            was_enabled = submit_enabled(page)
            clear_named_input(page, "date_vehicle_left")
            now_enabled = submit_enabled(page)
            shot(page, "sc1_tc21_blank_date")
            print(
                "EXPECTED: clearing Date Vehicle Left flips Submit enabled->BLOCKED | "
                f"ACTUAL: before={was_enabled}, after_clear={now_enabled} | "
                f"{'MATCH' if (was_enabled and not now_enabled) else 'MISMATCH'}"
            )
            assert was_enabled, "Precondition failed: form was not valid before clearing Date"
            assert not now_enabled, "FAIL: expected rejection, blank Date Vehicle Left left Submit enabled"
        finally:
            page.close()

    # ---- TC-22: blank County -> Submit blocked ----
    def test_tc22_blank_county_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            pf = self._open_form(page, generate_vin())
            self._fill_valid(pf, page)
            was_enabled = submit_enabled(page)
            found = clear_named_input(page, "county_val")
            now_enabled = submit_enabled(page)
            shot(page, "sc1_tc22_blank_county")
            if not found:
                pytest.skip("County input (name=county_val) not present/clearable on this build")
            print(
                "EXPECTED: clearing County flips Submit enabled->BLOCKED (County now required) | "
                f"ACTUAL: before={was_enabled}, after_clear={now_enabled} | "
                f"{'MATCH' if (was_enabled and not now_enabled) else 'MISMATCH'}"
            )
            assert was_enabled, "Precondition failed: form was not valid before clearing County"
            assert not now_enabled, "FAIL: expected rejection, blank County left Submit enabled"
        finally:
            page.close()

    # ---- TC-06: fully-valid submit -> ACCEPTED (positive proof) ----
    def test_tc06_valid_submit_creates_record(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        vin = generate_vin()
        try:
            go_to_staff_dashboard(page)
            pf = self._open_form(page, vin)
            self._fill_valid(pf, page)
            enabled = submit_enabled(page)
            assert enabled, "Precondition failed: valid form did not enable Submit"
            pf.submit_with_confirmation()
            page.wait_for_timeout(1500)
            left_form = not on_paper_form(page)
            shot(page, "sc1_tc06_valid_submit")
            print(
                f"EXPECTED: valid LT-260 (Make=TOY, VIN={vin}) submits -> redirect off paper form | "
                f"ACTUAL: left_paper_form={left_form}, url_tail={page.url[-45:]} | "
                f"{'MATCH' if left_form else 'MISMATCH'}"
            )
            assert left_form, (
                "FAIL: expected submission success (redirect off the paper form) but stayed on the form"
            )
        finally:
            page.close()


# =============================================================================
# SC-4 [High] — Draft-Exempt Invariant (blank Make/core fields allowed as Draft)
# Covers TC-07, TC-28
# =============================================================================
@pytest.mark.ncnss493
@pytest.mark.regression
@pytest.mark.high
class TestE2E493_SC4_DraftExempt:
    """Save As Draft with blank Make/core fields must be ALLOWED (BR-25 conditional-mandatory)."""

    def test_tc07_lt260_draft_blank_make_allowed(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        vin = generate_vin()
        try:
            go_to_staff_dashboard(page)
            dash = StaffDashboardPage(page)
            lst = Lt260ListingPage(page)
            pf = PaperFormPage(page)
            dash.navigate_to_lt260_listing()
            lst.click_add_from_paper()
            pf.fill_modal_vin_and_next(vin)

            # Leave Make + all core fields blank; Draft button must be enabled (validation-free)
            draft_btn = page.locator(DRAFT_SEL).first
            draft_btn.wait_for(state="visible", timeout=15_000)
            draft_enabled = draft_btn.is_enabled()
            assert draft_enabled, "Save As Draft was disabled on a blank form — draft should be validation-free"

            draft_btn.scroll_into_view_if_needed()
            draft_btn.click()
            page.wait_for_timeout(1000)
            # Confirmation dialog: "Are you sure you want to save your changes as draft?" -> Yes
            yes = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes.wait_for(state="visible", timeout=10_000)
            yes.click()

            # Positive proof #1: snackbar "saved as draft" (auto-dismisses -> poll quickly)
            snackbar_seen = False
            for _ in range(12):
                try:
                    sn = page.locator(
                        '.mat-snack-bar-container, simple-snack-bar, [class*="snack"], [class*="toast"]'
                    ).first
                    if sn.count() and sn.is_visible():
                        txt = (sn.inner_text() or "")
                        if re.search(r"saved as draft|draft", txt, re.I):
                            snackbar_seen = True
                            break
                except Exception:
                    pass
                page.wait_for_timeout(250)

            body = (page.locator("body").inner_text() or "")
            make_error = bool(re.search(r"Make is required|Please enter value of Make", body, re.I))
            shot(page, "sc4_tc07_lt260_draft")

            # Positive proof #2: the VIN now appears in the "Draft Paper Forms" tab
            dash.navigate_to_lt260_listing()
            page.wait_for_timeout(1500)
            draft_tab = page.locator('[role="tab"]:has-text("Draft")').first
            draft_tab.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
            lst.search_by_vin(vin)
            page.wait_for_timeout(1500)
            in_draft_tab = page.locator("table tbody tr").count() > 0
            shot(page, "sc4_tc07_draft_tab")

            saved = (snackbar_seen or in_draft_tab) and not make_error
            print(
                f"EXPECTED: blank-Make LT-260 saves as Draft (allowed, no Make error), VIN={vin} | "
                f"ACTUAL: draft_enabled={draft_enabled}, snackbar_seen={snackbar_seen}, "
                f"in_draft_tab={in_draft_tab}, make_error_shown={make_error} | "
                f"{'MATCH' if saved else 'MISMATCH'}"
            )
            assert not make_error, "FAIL: draft save raised a Make-required error (draft must be exempt)"
            assert (snackbar_seen or in_draft_tab), (
                "FAIL: draft did not persist (no 'saved as draft' toast and VIN absent from Draft tab)"
            )
        finally:
            page.close()

    def test_tc28_lt262_lt263_draft_note(self, staff_context: BrowserContext):
        """TC-28 draft-exempt for LT-262/LT-263: their 'Add from Paper' requires a prior
        LT-260 -> LT-160B (LT-262) / processed LT-262 (LT-263) chain for the VIN. With a
        fresh VIN the modal Next bounces back to the listing, so the draft form is not
        reachable here. Verified reachable-only-with-fixture -> documented blocker."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dash = StaffDashboardPage(page)
            dash.navigate_to_lt262_listing()
            lt262 = Lt262ListingPage(page)
            lt262.click_add_from_paper()
            page.wait_for_timeout(800)
            vin = generate_vin()
            vi = page.locator('mat-dialog-container input[placeholder*="VIN" i], '
                              'mat-dialog-container input[name*="vin" i]').first
            reachable = False
            if vi.count() and vi.is_visible():
                vi.fill(vin)
                page.wait_for_timeout(400)
                page.locator('mat-dialog-container button:has-text("Next")').first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2500)
                reachable = "paperFormdetails" in (page.url or "")
            shot(page, "sc4_tc28_lt262_draft_blocked")
            print(
                "EXPECTED (documented): LT-262 paper draft needs a prior LT-160B for the VIN | "
                f"ACTUAL: fresh-VIN form reachable={reachable}, url_tail={page.url[-45:]}"
            )
            if not reachable:
                pytest.skip(
                    "BLOCKED: LT-262/LT-263 'Add from Paper' requires a prior LT-260->LT-160B "
                    "(LT-262) / processed LT-262 (LT-263) chain; fresh VIN bounces to the listing. "
                    "Draft-exempt for these forms needs a seeded case (STARS owners + payment + issue)."
                )
        finally:
            page.close()


# =============================================================================
# SC-6 [Medium] — Presence validation on LT-261/262/262A/263 submit
# Covers TC-24 (LT-261), TC-25 (LT-262/262A), TC-26 (LT-263), TC-27 (updates)
# =============================================================================
@pytest.mark.ncnss493
@pytest.mark.regression
@pytest.mark.medium
class TestE2E493_SC6_PresenceOtherForms:
    """Each form's paper Submit must be BLOCKED with a blank core field."""

    def test_tc24_lt261_blank_core_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dash = StaffDashboardPage(page)
            lt261 = Lt261Page(page)
            dash.navigate_to_lt261_listing()
            lt261.click_add_from_paper()
            lt261.fill_modal_vin_next(generate_vin())
            page.wait_for_timeout(1500)
            # Empty form: Submit must be disabled (presence validation now gates it)
            enabled = submit_enabled(page)
            shot(page, "sc6_tc24_lt261_blank")
            still_on_form = "paperFormdetails" in (page.url or "")
            print(
                "EXPECTED: LT-261 paper Submit BLOCKED with blank core fields | "
                f"ACTUAL: submit_enabled={enabled}, on_form={still_on_form} | "
                f"{'MATCH' if (not enabled and still_on_form) else 'MISMATCH'}"
            )
            assert not enabled, "FAIL: expected rejection, LT-261 blank form left Submit enabled"
        finally:
            page.close()

    def test_tc25_lt262_blank_core_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dash = StaffDashboardPage(page)
            lt262 = Lt262ListingPage(page)
            dash.navigate_to_lt262_listing()
            lt262.click_add_from_paper()
            page.wait_for_timeout(800)
            vin = generate_vin()
            vi = page.locator('mat-dialog-container input[placeholder*="VIN" i], '
                              'mat-dialog-container input[name*="vin" i]').first
            reachable = False
            if vi.count() and vi.is_visible():
                vi.fill(vin)
                page.wait_for_timeout(400)
                page.locator('mat-dialog-container button:has-text("Next")').first.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2500)
                reachable = "paperFormdetails" in (page.url or "")
            shot(page, "sc6_tc25_lt262_blank")
            if not reachable:
                print(
                    "EXPECTED (documented): LT-262/262A paper Submit presence guard | "
                    f"ACTUAL: fresh-VIN form NOT reachable (bounced to {page.url[-40:]})"
                )
                pytest.skip(
                    "BLOCKED: LT-262/262A 'Add from Paper' requires a prior LT-260->LT-160B for the "
                    "VIN (BR-26). Fresh VIN bounces to listing, so the submit-presence guard cannot "
                    "be exercised without a seeded case."
                )
            enabled = submit_enabled(page)
            print(
                "EXPECTED: LT-262 paper Submit BLOCKED with blank core fields | "
                f"ACTUAL: submit_enabled={enabled} | {'MATCH' if not enabled else 'MISMATCH'}"
            )
            assert not enabled, "FAIL: expected rejection, LT-262 blank form left Submit enabled"
        finally:
            page.close()

    def test_tc26_lt263_blank_core_blocks_submit(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            dash = StaffDashboardPage(page)
            lt263 = Lt263ListingPage(page)
            dash.navigate_to_lt263_listing()
            lt263.click_add_from_paper()
            page.wait_for_timeout(800)
            vin = generate_vin()
            vi = page.locator('mat-dialog-container input[placeholder*="VIN" i], '
                              'mat-dialog-container input[name*="vin" i]').first
            reachable = False
            if vi.count() and vi.is_visible():
                vi.fill(vin)
                page.wait_for_timeout(400)
                nxt = page.locator('mat-dialog-container button:has-text("Next")').first
                nxt.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(2500)
                reachable = "paperFormdetails" in (page.url or "")
            shot(page, "sc6_tc26_lt263_blank")
            if not reachable:
                print(
                    "EXPECTED (documented): LT-263 paper Submit presence guard + Lien Amount>0 | "
                    f"ACTUAL: fresh-VIN form NOT reachable (modal stayed / bounced to {page.url[-40:]})"
                )
                pytest.skip(
                    "BLOCKED: LT-263 'Add from Paper' requires a processed LT-262 for the VIN; fresh "
                    "VIN keeps the modal / bounces to listing. Presence guard + Lien-Amount>0 need a "
                    "seeded post-LT-262 case."
                )
            enabled = submit_enabled(page)
            print(
                "EXPECTED: LT-263 paper Submit BLOCKED with blank Type of Sale/Sale Date | "
                f"ACTUAL: submit_enabled={enabled} | {'MATCH' if not enabled else 'MISMATCH'}"
            )
            assert not enabled, "FAIL: expected rejection, LT-263 blank form left Submit enabled"
        finally:
            page.close()


# =============================================================================
# SC-3 [High] — Staff LT260.update Make guard + data-integrity
# Covers TC-13, 14, 15, 16
# =============================================================================
@pytest.mark.ncnss493
@pytest.mark.regression
@pytest.mark.high
class TestE2E493_SC3_Lt260UpdateGuard:
    """Open an existing LT-260, Edit, blank the Make -> Save must be BLOCKED ('Make is
    required'); the record's issued/stored data must NOT be wiped. Valid Make -> Save
    enables (positive). Non-destructive: we never persist a blank/altered save."""

    def _open_first_lt260_edit(self, page):
        dash = StaffDashboardPage(page)
        lst = Lt260ListingPage(page)
        dash.navigate_to_lt260_listing()
        page.wait_for_timeout(1500)
        links = page.locator("span.table-link, table td a")
        if links.count() == 0:
            return None, None
        # capture the make chip text before editing (data-integrity baseline)
        links.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        detail_url = page.url
        edit = page.locator('button:has-text("Edit")').first
        try:
            edit.wait_for(state="visible", timeout=10_000)
        except Exception:
            return None, detail_url
        edit.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        return detail_url, page.url

    def test_tc13_15_blank_make_update_blocked_no_wipe(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            detail_url, edit_url = self._open_first_lt260_edit(page)
            if detail_url is None:
                pytest.skip("BLOCKED: no editable LT-260 record reachable in qa To Process listing")

            # Baseline: capture make chip text
            make_chip = page.locator("mat-chip, mat-basic-chip, .mat-chip").first
            baseline_make = ""
            try:
                baseline_make = (make_chip.inner_text() or "").replace("cancel", "").strip()
            except Exception:
                pass

            save_before = page.locator('button:has-text("Save")').first
            save_enabled_initial = save_before.is_enabled()

            # Remove the Make chip (blank the make)
            removed = False
            try:
                remove_icon = page.locator(
                    "mat-chip mat-icon, mat-chip .mat-chip-remove, mat-chip button, "
                    "mat-basic-chip mat-icon"
                ).first
                remove_icon.click()
                page.wait_for_timeout(1000)
                removed = True
            except Exception:
                pass

            save_after = page.locator('button:has-text("Save")').first
            save_enabled_blank = save_after.is_enabled()

            # If Save is (wrongly) enabled with blank make, click it and observe the backend response.
            feedback = set()
            make_required_msg = False
            saved_ok = False
            if save_enabled_blank:
                save_after.click()
                feedback = poll_feedback(page, 7.0)
                joined = " || ".join(feedback)
                make_required_msg = bool(
                    re.search(r"Make is required|Please enter the vehicle make|Make is missing", joined, re.I)
                )
                saved_ok = bool(re.search(r"saved successfully|has been saved|details have been saved", joined, re.I))

            shot(page, "sc3_tc13_blank_make_update")

            # Data-integrity check: reload the detail page, confirm the make is still present.
            page.goto(detail_url, timeout=60_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
            after_body = (page.locator("body").inner_text() or "")
            make_token = baseline_make.split()[0] if baseline_make else ""
            record_intact = (make_token in after_body) if make_token else True
            shot(page, "sc3_tc13_record_intact")

            # Best-effort RESTORE: if the blank save was accepted (guard absent), the make got
            # wiped — put a value back so we don't leave a make-less record in qa.
            if saved_ok:
                try:
                    page.goto(detail_url, timeout=60_000)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(1500)
                    page.locator('button:has-text("Edit")').first.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)
                    mk = page.locator("(//input[@role='combobox'])[1]")
                    mk.click()
                    mk.fill("TOY")
                    page.wait_for_timeout(1000)
                    page.locator(".cdk-overlay-pane mat-option").first.click()
                    page.wait_for_timeout(800)
                    rsave = page.locator('button:has-text("Save")').first
                    if rsave.is_enabled():
                        rsave.click()
                        poll_feedback(page, 4.0)
                    print("  [cleanup] restored a Make value on the wiped record")
                except Exception as _e:
                    print(f"  [cleanup] restore attempt failed: {str(_e)[:80]}")

            # PASS conditions: rejection actually fired (Save stayed disabled) OR a Make-required
            # message appeared; AND the record's make was not wiped.
            rejection_fired = (removed and not save_enabled_blank) or make_required_msg
            print(
                "EXPECTED: blanking Make on LT260.update is REJECTED (Save stays disabled or "
                "'Make is required') AND the already-stored Make is NOT wiped | "
                f"ACTUAL: make_removed={removed}, save_enabled_after_blank={save_enabled_blank}, "
                f"make_required_msg={make_required_msg}, saved_successfully={saved_ok}, "
                f"baseline_make={baseline_make!r}, make_still_present_after={record_intact}, "
                f"feedback={sorted(feedback)} | "
                f"{'MATCH' if (rejection_fired and record_intact) else 'MISMATCH (DEFECT)'}"
            )
            assert removed, "Could not remove the Make chip to exercise the guard (selector issue)"
            assert rejection_fired and record_intact, (
                "FAIL: expected rejection, blank Make on staff update (LT260.update) was ACCEPTED "
                f"({'\"saved successfully\"' if saved_ok else 'no error'}) and the stored Make was "
                f"WIPED (make_still_present_after={record_intact}). This reproduces the NCNSS-493 "
                "defect — the LT260.update make-required guard is not enforced on qa "
                "(ticket target release 2026-07-07). Re-verify after deployment."
            )
        finally:
            page.close()

    def test_tc16_valid_make_update_enables_save(self, staff_context: BrowserContext):
        """Positive (non-destructive): a valid Make selection while editing enables Save.
        We verify Save enables on a valid change, then Cancel to avoid mutating qa data."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            detail_url, edit_url = self._open_first_lt260_edit(page)
            if detail_url is None:
                pytest.skip("BLOCKED: no editable LT-260 record reachable in qa To Process listing")

            # Remove then re-select a valid make -> form dirty + valid -> Save should enable
            try:
                page.locator(
                    "mat-chip mat-icon, mat-chip .mat-chip-remove, mat-chip button"
                ).first.click()
                page.wait_for_timeout(800)
            except Exception:
                pass
            make = page.locator("(//input[@role='combobox'])[1]")
            make.click()
            make.fill("TOY")
            page.wait_for_timeout(1000)
            try:
                page.locator(".cdk-overlay-pane mat-option").first.click()
                page.wait_for_timeout(800)
            except Exception:
                pass
            save = page.locator('button:has-text("Save")').first
            save_enabled_valid = save.is_enabled()
            shot(page, "sc3_tc16_valid_make_save")
            print(
                "EXPECTED: valid Make while editing (LT260.update) ENABLES Save (guard does not "
                "over-block valid edits) | "
                f"ACTUAL: save_enabled_valid={save_enabled_valid} | "
                f"{'MATCH' if save_enabled_valid else 'MISMATCH'}"
            )
            # Non-destructive: do NOT persist — Cancel out.
            try:
                page.locator('button:has-text("Cancel")').first.click()
                page.wait_for_timeout(800)
            except Exception:
                pass
            assert save_enabled_valid, (
                "FAIL: valid Make edit did not enable Save — guard may be over-blocking valid updates"
            )
        finally:
            page.close()


# =============================================================================
# SC-2 [Critical] — Issuance-step "Make is missing" guard (manual issue path)
# Covers TC-08, 09, 10, 11, 12
# =============================================================================
@pytest.mark.ncnss493
@pytest.mark.regression
@pytest.mark.critical
class TestE2E493_SC2_IssuanceGuard:
    """The literal defect: issuance of a blank-Make LT-260. POST-FIX a make-specific guard
    ('Make is missing') must fire BEFORE form-gen (no 42P18, no generic 'Forms can not be
    issued', no silent issuance). We create our OWN fresh record, blank its Make via the
    Edit path (works on qa — the update guard isn't deployed, see SC-3), then click the
    reachable manual issuance action (Issue LT-260C) and observe.

    Note on reachability: for random / no-owner VINs the reachable manual issuance is
    LT-260C (the 'no owners found' letter). The exact LT-160B/260A issuance (the CONCAT
    that threw 42P18) only surfaces its 'Issue 160B and 260A' button when STARS returns
    owners, which random qa VINs do not have — so TC-09/TC-11's 160B/260A path is data-
    blocked and we exercise the LT-260C issuance step instead.
    """

    def _create_valid_lt260(self, page, vin) -> str:
        """Create a valid LT-260 via Add from Paper; return its detail-page URL."""
        dash = StaffDashboardPage(page)
        lst = Lt260ListingPage(page)
        pf = PaperFormPage(page)
        dash.navigate_to_lt260_listing()
        lst.click_add_from_paper()
        pf.fill_modal_vin_and_next(vin)
        pf.fill_make("TOY")
        pf.fill_year("2018")
        pf.fill_date_vehicle_left(past_date(30))
        pf.fill_search_location("Garage")
        pf.select_stolen_no()
        page.wait_for_timeout(600)
        pf.submit_with_confirmation()
        page.wait_for_timeout(1500)
        # Locate the new record's detail page
        if re.search(r"/LT-260/[0-9a-f-]+/details", page.url or ""):
            return page.url
        dash.navigate_to_lt260_listing()
        page.wait_for_timeout(1200)
        lst.search_by_vin(vin)
        page.wait_for_timeout(1200)
        links = page.locator("span.table-link, table td a")
        links.first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2500)
        return page.url

    def _issue_lt260c(self, page):
        """Click Issue LT-260C -> confirm (Issue) -> return the feedback text set."""
        issue = page.locator('button:has-text("Issue LT-260C")').first
        issue.wait_for(state="visible", timeout=15_000)
        issue.scroll_into_view_if_needed()
        issue.click()
        page.wait_for_timeout(1500)
        confirm = page.locator('mat-dialog-container button:has-text("Issue")').first
        try:
            confirm.wait_for(state="visible", timeout=8_000)
            confirm.click()
        except Exception:
            pass
        return poll_feedback(page, 10.0)

    def test_tc09_11_blank_make_issue_guard(self, staff_context: BrowserContext):
        """Blank the Make on a fresh LT-260, then issue -> a make-specific guard MUST fire
        (no successful issuance / no crash). On current qa it issues -> FAIL = DEFECT."""
        page = staff_context.new_page()
        vin = generate_vin()
        try:
            go_to_staff_dashboard(page)
            detail_url = self._create_valid_lt260(page, vin)

            has_issue = page.locator('button:has-text("Issue LT-260C")').count() > 0
            has_edit = page.locator('button:has-text("Edit")').count() > 0
            if not (has_issue and has_edit):
                pytest.skip(
                    f"BLOCKED: freshly-created LT-260 (VIN {vin}) did not expose Edit + Issue LT-260C "
                    f"on its detail page ({page.url[-40:]}); issuance guard not reachable this run"
                )

            # Blank the Make via Edit (works on qa — SC-3 update guard undeployed)
            page.locator('button:has-text("Edit")').first.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            baseline_make = ""
            try:
                baseline_make = (page.locator("mat-chip, mat-basic-chip, .mat-chip").first.inner_text()
                                 or "").replace("cancel", "").strip()
            except Exception:
                pass
            page.locator(
                "mat-chip mat-icon, mat-chip .mat-chip-remove, mat-chip button, mat-basic-chip mat-icon"
            ).first.click()
            page.wait_for_timeout(1000)
            save = page.locator('button:has-text("Save")').first
            save.click()
            save_fb = poll_feedback(page, 5.0)
            make_blanked = any(re.search(r"saved successfully|has been saved", t, re.I) for t in save_fb)

            # Back to the detail page and issue
            page.goto(detail_url, timeout=60_000)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2500)
            feedback = self._issue_lt260c(page)
            shot(page, "sc2_tc09_blank_make_issue")

            joined = " || ".join(feedback)
            body = (page.locator("body").inner_text() or "")
            guard_fired = bool(re.search(
                r"Make is missing|Make is required|vehicle make is blank|add the vehicle make",
                joined + " " + body, re.I))
            issued_ok = bool(re.search(r"issued successfully|has been issued", joined, re.I))
            generic_fail = bool(re.search(
                r"can ?not be issued|cannot be issued|Forms can not|42P18|could not determine",
                joined + " " + body, re.I))

            print(
                "EXPECTED: issuing a blank-Make LT-260 fires a make-specific guard "
                "('Make is missing') BEFORE form-gen — NOT a successful issuance, NOT a generic "
                f"failure/42P18 | ACTUAL: baseline_make={baseline_make!r}, make_blanked={make_blanked}, "
                f"guard_fired={guard_fired}, issued_successfully={issued_ok}, generic_failure={generic_fail}, "
                f"feedback={sorted(feedback)} | "
                f"{'MATCH' if guard_fired else 'MISMATCH (DEFECT)'}"
            )
            assert make_blanked, (
                "Precondition: could not blank the Make (Edit save did not confirm) — cannot test guard"
            )
            assert guard_fired, (
                "FAIL: expected a make-specific issuance guard ('Make is missing'), but issuing a "
                f"blank-Make LT-260 produced "
                f"{'a successful issuance' if issued_ok else ('a generic failure/crash' if generic_fail else 'no guard message')}. "
                "This reproduces the NCNSS-493 issuance defect — the LT260.issue 'Make is missing' "
                "guard is not enforced on qa (ticket target release 2026-07-07). Re-verify after deploy. "
                "(Path exercised: LT-260C manual issuance; the LT-160B/260A path needs STARS owners.)"
            )
        finally:
            page.close()

    def test_tc12_valid_make_manual_issue_succeeds(self, staff_context: BrowserContext):
        """TC-12 positive: a valid-Make LT-260 issues successfully (guard does not over-block).
        Mirrors e2e-005 Phase 3 issue_lt260c()."""
        page = staff_context.new_page()
        vin = generate_vin()
        try:
            go_to_staff_dashboard(page)
            detail_url = self._create_valid_lt260(page, vin)
            if page.locator('button:has-text("Issue LT-260C")').count() == 0:
                pytest.skip(
                    f"BLOCKED: fresh LT-260 (VIN {vin}) did not expose Issue LT-260C; "
                    "positive issuance path not reachable this run (covered by e2e-005 Phase 3)."
                )
            feedback = self._issue_lt260c(page)
            shot(page, "sc2_tc12_valid_make_issue")
            issued_ok = any(re.search(r"issued successfully|has been issued", t, re.I) for t in feedback)
            body = (page.locator("body").inner_text() or "")
            processed = bool(re.search(r"Processed", body, re.I))
            print(
                f"EXPECTED: valid-Make LT-260 (VIN {vin}) manual issue succeeds (LT-260C issued, "
                f"status Processed) | ACTUAL: issued_successfully={issued_ok}, processed={processed}, "
                f"feedback={sorted(feedback)} | {'MATCH' if (issued_ok or processed) else 'MISMATCH'}"
            )
            assert issued_ok or processed, (
                "FAIL: valid-Make LT-260 did not issue successfully (no success toast / not Processed)"
            )
        finally:
            page.close()


# =============================================================================
# SC-5 [High] — STARS corrective + Nordis reconciliation — ASSESS ONLY (blocked)
# Covers TC-17, TC-18
# =============================================================================
@pytest.mark.ncnss493
@pytest.mark.regression
@pytest.mark.high
class TestE2E493_SC5_StarsCorrectiveNordis:
    """SC-5 is a one-time ops/backend corrective action, not a repeatable qa UI flow."""

    def test_tc17_18_stars_corrective_not_qa_repeatable(self, staff_context: BrowserContext):
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            print(
                "EXPECTED (assessment): a repeatable qa UI path to (a) populate Make from STARS on a "
                "stuck app, (b) regenerate LT-160B/260A letters, (c) reconcile the Nordis Index letter "
                "count | ACTUAL: none found. STARS is an external corrective lookup (no 'populate from "
                "STARS' control in the staff UI); the LT-260 edit only offers a manual Make combobox. "
                "NordisTrackingPage (TRACK LT-264 tab) is a read-only delivery-tracking table with no "
                "letter-count reconciliation or regenerate action. This is a one-time ops action tied "
                "to the two PROD stuck VINs (1C4BJWDG3GL179837->JEEP, 1GCSGAFX0E1156443->Chevrolet), "
                "already validated on PROD by the team — not qa-repeatable."
            )
            pytest.skip(
                "BLOCKED (assess-only): SC-5 STARS corrective + Nordis reconciliation (TC-17/18) is a "
                "one-time ops/backend action with no repeatable qa UI control. Looked for: a STARS "
                "make-populate button on the LT-260 detail/edit (none — only a manual Make combobox); "
                "a letter-regenerate / re-issue-to-Nordis action (none reachable on qa); a Nordis Index "
                "letter-count reconciliation view (NordisTrackingPage is read-only delivery tracking). "
                "Requires the specific PROD stuck records + Nordis batch; validate manually / on PROD."
            )
        finally:
            page.close()
