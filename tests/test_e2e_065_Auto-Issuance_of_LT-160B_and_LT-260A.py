"""
E2E-065: Auto-Issuance of LT-160B and LT-260A
Cross-portal test — Public Portal + Staff Portal, individual public-user context.

Purpose
-------
Verify that when an LT-260 is submitted for a **valid VIN that has owner
information available**, the system **auto-issues the LT-160B and LT-260A forms**
during Phase-2 processing (no manual "Issue 160B and 260A" step) and the request
reaches Processed on its own.

Auto-issuance is proven *implicitly and from the requester's side*: the public
"Submit LT-262" action only becomes available once the LT-260 has auto-issued
LT-160B / LT-260A and moved to Processed. Phase 2 refreshes the Notice & Storage
detail until that button appears — if it never does, auto-issuance is broken and
the phase fails. The file is then carried through the rest of the Notice &
Storage lifecycle (LT-262 -> LT-264 -> court hearings -> LT-263 -> LT-265).

Phases (run in file order — phase N depends on phase N-1's state)
------
  1. [Public Portal]  Individual user — create & submit LT-260 for the fixed VIN
                      (VIN Lookup + mandatory fields only)
  2. [Public Portal]  Refresh until "Submit LT-262" is visible (auto-issuance
                      gate) -> submit LT-262 -> pay via ACH/Drawdown
  3. [Staff Portal]   Process LT-262 — CHECK DCI (owner details) -> Issue LT-264
  4. [Staff Portal]   Track LT-264 — log receipt, request hearing, possessory-lien judgment
  5. [Public Portal]  Submit LT-263 — public sale, sale date +21d (never a Sunday), lien $800
  6. [Staff Portal]   Review LT-263 -> Generate LT-265 -> status Processed

Speed
-----
Each portal keeps ONE warm page for the whole class (pub_page / staff_pg
fixtures) — the Angular bundle boots once per portal instead of once per phase
(~15-25s on QA, up to a minute on STAGE). `to_public_dashboard` /
`to_staff_dashboard` reuse the loaded SPA when the page is already on it and only
fall back to a cold navigation when needed. Blind sleeps that merely preceded an
explicit `wait_for` / `expect` have been removed; the remaining fixed waits are
Angular re-render settles with no observable signal.

Runs headless by default: `pytest tests/test_e2e_065_*.py --env qa|stage`.
A `-k` slice (e.g. `-k "phase_5 or phase_6"`) still works — each run builds its
own fixtures.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    random_vehicle,
    generate_address,
    past_date,
    generate_person,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage


# ─── Shared test data ───

# Fixed, registered VIN whose STARS record carries owner information — this is the
# precondition that lets Phase 2's "Submit LT-262" gate open (i.e. the LT-260
# auto-issues LT-160B / LT-260A and reaches Processed without staff action).
TEST_VIN = "19UUA564XXA039576"

VEHICLE = random_vehicle()
ADDRESS = generate_address()
PERSON = generate_person()
RANDOM_PHONE = PERSON["phone"]  # Phase 2: Additional Details phone number
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


# ─── One warm page per portal for the whole class ───

@pytest.fixture(scope="class")
def pub_page(individual_public_context: BrowserContext):
    page = individual_public_context.new_page()
    yield page
    try:
        page.close()
    except Exception:
        pass


@pytest.fixture(scope="class")
def staff_pg(staff_context: BrowserContext):
    page = staff_context.new_page()
    yield page
    try:
        page.close()
    except Exception:
        pass


# ─── Navigation helpers (reuse the loaded SPA; cold-navigate only when needed) ───

def _dismiss_transient_modal(page):
    """Close a leftover informational dialog from a prior phase, if one is open."""
    try:
        for sel in (
            'mat-dialog-container button:has-text("Ok")',
            'mat-dialog-container button:has-text("OK")',
            'mat-dialog-container button:has-text("Close")',
            'mat-dialog-container button:has-text("Got it")',
            'mat-dialog-container button:has-text("Cancel")',
        ):
            btn = page.locator(sel).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(300)
                return
        if page.locator(".cdk-overlay-backdrop").count():
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
    except Exception:
        pass


def to_public_dashboard(page):
    if page.url and "about:blank" not in page.url:
        _dismiss_transient_modal(page)
    if "dashboard" in (page.url or "").lower():
        try:
            PublicDashboardPage(page).notice_storage_tab.wait_for(state="visible", timeout=8_000)
            return
        except Exception:
            pass
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=25_000)
    page.wait_for_load_state("load")


def to_staff_dashboard(page):
    if page.url and "about:blank" not in page.url:
        _dismiss_transient_modal(page)
    if "ncdot-notice-and-storage" in (page.url or ""):
        try:
            page.locator('a[href*="LT-260/list"]').first.wait_for(state="visible", timeout=8_000)
            return
        except Exception:
            pass
    page.goto(SP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_load_state("load")


def _open_ns_application(page, dashboard: PublicDashboardPage):
    """Notice & Storage tab -> search TEST_VIN -> open row 0."""
    dashboard.click_notice_storage_tab()
    dashboard.search_by_vin(TEST_VIN)
    try:
        dashboard.application_list.first.wait_for(state="visible", timeout=15_000)
    except Exception:
        pass
    dashboard.select_application(0)


def _wait_loader_gone(page, timeout: int = 60_000):
    """Wait out the app's loading-spinner overlay.

    On STAGE the `.exp-loader-overlay-backdrop` sits over the page for tens of
    seconds after a navigation/search and both intercepts clicks and delays the
    detail render — the single biggest source of slow-env flake here.
    """
    for sel in (".exp-loader-overlay-backdrop", ".cdk-overlay-backdrop.exp-loader-overlay-backdrop"):
        try:
            page.locator(sel).last.wait_for(state="hidden", timeout=timeout)
        except Exception:
            pass


def _staff_open_lt262(page, lt262_listing: Lt262ListingPage) -> bool:
    """Open the LT-262 detail for TEST_VIN, trying 'To Process' then 'All', with a
    reload retry. Confirms the detail page actually rendered (slow on STAGE).
    Returns True on success.
    """
    for _ in range(3):
        for open_tab in (lt262_listing.click_to_process_tab, lt262_listing.click_all_tab):
            try:
                open_tab()
            except Exception:
                continue
            lt262_listing.search_by_vin(TEST_VIN)
            _wait_loader_gone(page)
            try:
                lt262_listing.vin_links.first.wait_for(state="visible", timeout=10_000)
            except Exception:
                continue
            lt262_listing.select_application(0)
            _wait_loader_gone(page)
            try:
                expect(
                    page.get_by_text(re.compile(r"Description of (Lien|Vehicle)|REVIEW LT-262", re.I)).first
                ).to_be_visible(timeout=45_000)
                return True
            except Exception:
                pass
        page.wait_for_timeout(4000)
        page.reload()
        page.wait_for_load_state("load")
        _wait_loader_gone(page)
    return False


def _next_enabled(page) -> bool:
    """True when the form's 'Next' button is present and enabled."""
    try:
        btn = page.locator('button:has-text("Next")').first
        btn.wait_for(state="visible", timeout=6_000)
        return btn.is_enabled()
    except Exception:
        return False


def _vin_lookup(page) -> bool:
    """Click the LT-260 'VIN Lookup' button.

    Returns True when it was clicked: for a registered VIN the lookup fills
    Make / Year / Model / Body from STARS and locks those fields, so the caller
    must NOT then type into them (a .click() on the now read-only Make input
    hangs for the full default timeout). Returns False when the button is absent
    (older form builds) — the caller fills the vehicle section manually and the
    VIN-image modal at submit still covers the VIN path.
    """
    try:
        btn = page.locator(
            'button:has-text("VIN Lookup"), button:has-text("Decode VIN"), '
            'button:has-text("Lookup VIN")'
        ).first
        btn.wait_for(state="visible", timeout=8_000)
        btn.click()
        page.wait_for_load_state("load")
        page.wait_for_timeout(2000)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  WARN: VIN Lookup button not actioned ({exc}) — filling vehicle details manually")
        return False


@pytest.mark.e2e
@pytest.mark.high
class TestE2E065AutoIssuanceLt160bLt260a:
    """E2E-065: LT-260 for a VIN with owner info auto-issues LT-160B / LT-260A."""

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_1_public_portal_create_lt260(self, pub_page):
        """Phase 1: [Public Portal] Individual user (no business selection) —
        Start here -> LT-260 form -> enter VIN + VIN Lookup -> fill only the
        mandatory fields (date vehicle left, reason=storage, storage location,
        authorized person) -> accept terms and sign -> submit (VIN image modal)
        -> soft-check dashboard redirect.
        """
        page = pub_page
        to_public_dashboard(page)

        dashboard = PublicDashboardPage(page)
        dashboard.click_start_here()

        lt260 = Lt260FormPage(page)
        lt260.enter_vin(TEST_VIN)
        _vin_lookup(page)

        # VIN Lookup normally fills (and locks) the vehicle section for a
        # registered VIN. When it didn't — older form build, or the VIN already
        # has a case so the portal won't populate — the Vehicle Details tab stays
        # invalid and "Next" is disabled. Fill it by hand then, but bounded so a
        # locked field can't burn the default 90s.
        if not _next_enabled(page):
            print("  INFO: vehicle section invalid after VIN Lookup — filling it manually")
            page.set_default_timeout(20_000)
            try:
                lt260.fill_vehicle_details(VEHICLE)
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN: vehicle-details fill: {exc}")
            finally:
                page.set_default_timeout(90_000)

        lt260.fill_date_vehicle_left(past_date(30))
        try:
            lt260.select_reason_storage()
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN: reason-for-storage not set: {exc}")
        lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])
        lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
        lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

        lt260.submit_with_vin_image()

        try:
            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=12_000)
        except Exception:
            print("  WARN: did not redirect back to dashboard after LT-260 submit — continuing")

    # ========================================================================
    # PHASE 2: Public Portal — auto-issuance gate + Submit LT-262 + pay
    # ========================================================================
    def test_phase_2_public_portal_submit_lt262(self, pub_page):
        """Phase 2: [Public Portal] Refresh the Notice & Storage detail until
        'Submit LT-262' is visible — this only happens once the LT-260 has
        auto-issued LT-160B / LT-260A and reached Processed. Then submit LT-262
        (skip the pre-filled tabs, random phone in Additional Details) and pay
        via ACH/Drawdown.
        """
        page = pub_page
        to_public_dashboard(page)

        dashboard = PublicDashboardPage(page)
        _open_ns_application(page, dashboard)

        # ── Auto-issuance gate: wait (with reloads) for "Submit LT-262" ──
        submit_btn = page.locator(
            'button:has-text("Submit LT-262"), a:has-text("Submit LT-262")'
        ).first
        appeared = False
        for attempt in range(5):
            try:
                submit_btn.wait_for(state="visible", timeout=12_000)
                appeared = True
                break
            except Exception:
                print(f"  INFO: 'Submit LT-262' not visible yet (attempt {attempt + 1}/5) — reloading")
                page.reload()
                page.wait_for_load_state("load")
                page.wait_for_timeout(3000)
                _open_ns_application(page, dashboard)
        assert appeared, (
            f"'Submit LT-262' never became visible for VIN {TEST_VIN} — the LT-260 "
            f"did not auto-issue LT-160B / LT-260A and reach Processed"
        )

        dashboard.click_submit_lt262()

        lt262 = Lt262FormPage(page)
        lt262.expect_form_tabs_visible()

        # Inner tabs A-E are pre-filled from the processed LT-260. A/B just
        # advance; the lien tab (C) still enforces at least one charge and D/E
        # are required, so supply canonical values — harmless if pre-populated.
        lt262.skip_vehicle_and_location_tabs()                                        # A -> B -> C
        lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})  # C -> D
        lt262.fill_date_of_storage(past_date(30))                                     # D -> E
        lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])

        # Additional Details — enter a random phone number here.
        lt262.fill_additional_details(
            PERSON["name"], ADDRESS["street"], ADDRESS["zip"], phone=RANDOM_PHONE
        )
        lt262.upload_documents([SAMPLE_DOC_PATH])
        lt262.accept_terms_and_sign(PERSON["name"])
        lt262.finish_and_pay()

        # Pay via ACH/Drawdown on the cart page
        pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
        pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
        pay_drawdown_btn.click()

        yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
        yes_btn.wait_for(state="visible", timeout=15_000)
        yes_btn.click()

        expect(
            page.get_by_text("Your payment has been completed successfully")
        ).to_be_visible(timeout=30_000)

        page.wait_for_url(re.compile(r"dashboard", re.I), timeout=25_000)

    # ========================================================================
    # PHASE 3: Staff Portal — Process LT-262 -> Issue LT-264
    # ========================================================================
    def test_phase_3_staff_portal_process_lt262(self, staff_pg):
        """Phase 3: [Staff Portal] Open LT-262, verify lien + owner details (CHECK DCI), Issue LT-264."""
        page = staff_pg
        to_staff_dashboard(page)

        staff_dashboard = StaffDashboardPage(page)
        lt262_listing = Lt262ListingPage(page)

        staff_dashboard.navigate_to_lt262_listing()
        assert _staff_open_lt262(page, lt262_listing), (
            f"LT-262 detail for VIN {TEST_VIN} did not open (not in 'To Process' / 'All', "
            f"or the detail page never rendered)"
        )

        lt262_listing.verify_lien_details_visible()
        lt262_listing.verify_owner_details_visible()  # CHECK DCI AND NMVTIS tab
        _wait_loader_gone(page)
        lt262_listing.issue_lt264()

        # The issued-toast is transient and slow on STAGE — the reliable signal
        # that LT-264 issued is the TRACK LT-264 tab appearing.
        try:
            expect(
                page.get_by_text("The form has been issued successfully.")
            ).to_be_visible(timeout=20_000)
        except Exception:
            print("  WARN: issued-toast not seen — verifying via the TRACK LT-264 tab instead")
        expect(
            page.locator('[role="tab"]:has-text("TRACK LT-264")')
        ).to_be_visible(timeout=45_000)

    # ========================================================================
    # PHASE 4: Staff Portal — Track LT-264, Court Hearings
    # ========================================================================
    def test_phase_4_staff_portal_track_lt264(self, staff_pg):
        """Phase 4: [Staff Portal] Track LT-264 — log receipt, request judicial
        hearing, possessory-lien judgment, wait for the 'submit LT-263' modal.
        """
        page = staff_pg
        to_staff_dashboard(page)

        staff_dashboard = StaffDashboardPage(page)
        lt262_listing = Lt262ListingPage(page)

        staff_dashboard.navigate_to_lt262_listing()

        opened = False
        for open_tab in (lt262_listing.click_aging_tab,
                         lt262_listing.court_hearing_tab.click,
                         lt262_listing.click_to_process_tab):
            try:
                open_tab()
            except Exception:
                continue
            page.wait_for_load_state("networkidle")
            _wait_loader_gone(page)
            lt262_listing.search_by_vin(TEST_VIN)
            _wait_loader_gone(page)
            try:
                lt262_listing.vin_links.first.wait_for(state="visible", timeout=10_000)
                lt262_listing.select_application(0)
                opened = True
                break
            except Exception:
                continue
        assert opened, f"LT-262 for VIN {TEST_VIN} not found in Aging / Court Hearing / To Process"

        _wait_loader_gone(page)
        lt262_listing.click_track_lt264_tab()
        page.wait_for_timeout(1500)

        # TRACK LT-264: log receipt + request judicial hearing -> Save -> Yes.
        # A case that already had this recorded (resumed run) shows the tab
        # read-only with no Save button — skip straight to REVIEW COURT HEARINGS.
        save_btn = page.locator('button:has-text("Save")').first
        track_needs_doing = True
        try:
            save_btn.wait_for(state="visible", timeout=10_000)
        except Exception:
            track_needs_doing = False
            print("  INFO: TRACK LT-264 has no Save button — already completed, skipping to hearings")

        if track_needs_doing:
            # "Log Receipt of Signed LT-264 Letters"
            log_receipt_cb = page.locator('mat-checkbox').first
            if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
                log_receipt_cb.locator("label").click()
                page.wait_for_timeout(1000)  # Angular reveals the hearing section

            # "Select recipients requesting judicial hearing" (after the first check)
            hearing_cb = page.locator('mat-checkbox').nth(1)
            hearing_cb.wait_for(state="visible", timeout=10_000)
            if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
                hearing_cb.locator("label").click()
                page.wait_for_timeout(500)

            save_btn.scroll_into_view_if_needed()
            save_btn.click()

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=15_000)
            yes_btn.click()

        # REVIEW COURT HEARINGS — the auto-redirect after Save is slow/unreliable
        # on STAGE (LT-264B generation is async). Fall back to clicking the tab
        # explicitly, as E2E-005 does.
        _wait_loader_gone(page)
        possessory_text = page.get_by_text(
            re.compile(r"Judgment in action of Possessory Lien", re.I)
        ).first
        try:
            possessory_text.wait_for(state="visible", timeout=25_000)
        except Exception:
            try:
                lt262_listing.click_review_hearings_tab()
            except Exception:
                pass
            _wait_loader_gone(page)
            possessory_text.wait_for(state="visible", timeout=45_000)
        page.wait_for_timeout(1000)

        possessory_cb = page.locator('mat-checkbox').first
        possessory_cb.wait_for(state="visible", timeout=10_000)
        if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
            possessory_cb.locator("label").click()
            page.wait_for_timeout(1000)

        # Save the possessory-lien judgment — unless a resumed run finds it already
        # recorded (no Save button).
        save_btn2 = page.locator('button:has-text("Save")').first
        try:
            save_btn2.wait_for(state="visible", timeout=12_000)
            save_btn2.scroll_into_view_if_needed()
            save_btn2.click()
            yes_btn2 = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn2.wait_for(state="visible", timeout=15_000)
            yes_btn2.click()
            _wait_loader_gone(page)
            try:
                expect(
                    page.get_by_text(re.compile(r"success", re.I)).first
                ).to_be_visible(timeout=20_000)
            except Exception:
                print("  WARN: success banner not seen after possessory-lien save — continuing")
        except Exception:
            print("  INFO: no Save on REVIEW COURT HEARINGS — possessory judgment already recorded")

        next_btn = page.locator('button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=45_000)
        next_btn.scroll_into_view_if_needed()
        next_btn.click()
        _wait_loader_gone(page)

        expect(
            page.get_by_text("Waiting for the requester to submit LT-263.")
        ).to_be_visible(timeout=30_000)

    # ========================================================================
    # PHASE 5: Public Portal — Submit LT-263
    # ========================================================================
    def test_phase_5_public_portal_submit_lt263(self, pub_page):
        """Phase 5: [Public Portal] Submit LT-263 — public sale, sale date +21d
        (bumped off Sunday), lien $800.
        """
        page = pub_page
        to_public_dashboard(page)

        dashboard = PublicDashboardPage(page)
        _open_ns_application(page, dashboard)

        expect(page.get_by_text(re.compile(r"LT-262 Processed", re.I)).first).to_be_visible(timeout=30_000)
        dashboard.expect_lt263_available()
        dashboard.click_submit_lt263()

        expect(page.get_by_text(re.compile(r"LT-263.*Form Details", re.I)).first).to_be_visible(timeout=30_000)

        # Type of Sale -> Public
        sale_type_dropdown = page.locator('mat-select[aria-label*="Type of Sale" i]').first
        try:
            sale_type_dropdown.wait_for(state="visible", timeout=5_000)
            sale_type_dropdown.click()
            page.locator('mat-option:has-text("Public")').first.click()
        except Exception:
            Lt263FormPage(page).select_public_sale()

        # Sale Date = today + 21 days, but never a Sunday — the LT-263 form
        # rejects a Sunday sale date (Next stays disabled). Bump to Monday.
        sale_dt = datetime.now() + timedelta(days=21)
        if sale_dt.weekday() == 6:  # 6 = Sunday
            sale_dt += timedelta(days=1)
        sale_date = sale_dt.strftime("%m/%d/%Y")
        sale_date_input = page.locator(
            'input[aria-label*="Sale Date" i], input[placeholder*="MM/DD/YYYY"]'
        ).first
        sale_date_input.wait_for(state="visible", timeout=10_000)
        sale_date_input.fill(sale_date)

        lien_amount_input = page.locator(
            'input[aria-label*="Lien Amount" i], input[name*="lien" i][name*="amount" i]'
        ).first
        lien_amount_input.wait_for(state="visible", timeout=10_000)
        lien_amount_input.fill("800")
        page.wait_for_timeout(500)

        next_btn = page.locator('button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=30_000)
        next_btn.scroll_into_view_if_needed()
        next_btn.click()

        # Terms and Conditions — check every checkbox
        expect(page.get_by_text(re.compile(r"Terms and Conditions", re.I)).first).to_be_visible(timeout=30_000)
        mat_checkboxes = page.locator('mat-checkbox')
        for i in range(mat_checkboxes.count()):
            cb = mat_checkboxes.nth(i)
            if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
                cb.locator("label").click()
                page.wait_for_timeout(150)

        name_input = page.locator('input[aria-label*="Name" i], input[aria-label*="NAME" i]').first
        name_input.wait_for(state="visible", timeout=10_000)
        name_input.fill(PERSON["name"])

        date_input = page.locator('input[aria-label*="Date" i], input[aria-label*="DATE" i]').first
        try:
            date_input.wait_for(state="visible", timeout=5_000)
            if not date_input.input_value():
                date_input.fill(datetime.now().strftime("%m/%d/%Y"))
        except Exception:
            pass

        submit_btn = page.locator('button:has-text("Submit")').first
        submit_btn.wait_for(state="visible", timeout=30_000)
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        page.wait_for_timeout(1500)

        # Soft check — banner is transient
        try:
            expect(
                page.get_by_text(re.compile(r"Form is submitted successfully", re.I)).first
            ).to_be_visible(timeout=15_000)
        except Exception:
            print("  WARN: 'Form is submitted successfully' banner not seen — continuing")

        expect(page.get_by_text(re.compile(r"LT-263 Submitted", re.I)).first).to_be_visible(timeout=30_000)

    # ========================================================================
    # PHASE 6: Staff Portal — Review LT-263, Generate LT-265
    # ========================================================================
    def test_phase_6_staff_portal_generate_lt265(self, staff_pg):
        """Phase 6: [Staff Portal] LT-263 -> To Process -> verify sale details +
        lien amount -> Generate LT-265 -> status = Processed.
        """
        page = staff_pg
        to_staff_dashboard(page)

        staff_dashboard = StaffDashboardPage(page)
        lt263_listing = Lt263ListingPage(page)

        staff_dashboard.navigate_to_lt263_listing()
        lt263_listing.click_to_process_tab()
        lt263_listing.search_by_vin(TEST_VIN)
        _wait_loader_gone(page)
        lt263_listing.expect_applications_visible()
        lt263_listing.select_application(0)
        _wait_loader_gone(page)

        lt263_listing.verify_sale_details_visible()
        lt263_listing.verify_lien_amount_visible()

        lt263_listing.generate_lt265(expected_vin=TEST_VIN)

        # Status = Processed after LT-265 generation.
        try:
            expect(
                page.get_by_text(re.compile(r"Processed|Sold", re.I)).first
            ).to_be_visible(timeout=15_000)
        except Exception:
            # Re-open from the Processed (Sold) tab and assert there.
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_processed_sold_tab()
            lt263_listing.search_by_vin(TEST_VIN)
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            expect(
                page.get_by_text(re.compile(r"Processed|Sold", re.I)).first
            ).to_be_visible(timeout=15_000)
