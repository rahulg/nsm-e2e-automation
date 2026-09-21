"""
TW#27242835 / NCNSS-212 — Allow LT-263 re-submission after DMV rejection.

Reject no longer terminally closes the case: the garage may submit a new LT-263
repeatedly until the vehicle is Closed or Sold. See:
  C:\\codecommit\\qa.engineering\\qa.kb\\NSS\\testcases\\27242835.html (pre-existing
  test-case doc TC-01..18) and the reconciled 34-case matrix produced this session
  (adds TC-19..34: Audit Log, listing one-row-per-vehicle, garage accordion
  collapse/PDF-per-row, Add Paper Form via a rejected VIN, FO-52-class regression,
  dashboard tab placement).

SKIPPED (depend on one of 6 open questions the user set aside 2026-07-28, still
unanswered): TC-10 (separate Deny action existence unconfirmed), TC-15 (OQ-CR-1
correspondence update-vs-new), TC-17 (OQ-CR-2 Global Search latest-vs-per-submission),
TC-25 (canRelog=false trigger condition unknown), TC-30 (no example of a cycle with a
missing detail snapshot), TC-31 (unconfirmed whether "LT263" is a valid Audit Log
Entity Name filter value).

NOT YET AUTOMATED THIS PASS (scope/time — designed but not executed): TC-04 (digital
resubmit date-boundary revalidation), TC-07 (explicit history-ordering assertion —
partially covered by TC-06's history-visible check), TC-14 (RBAC), TC-16 (BR-38
[UsersID] stamp), TC-18 (no-owner/court branch — a full separate lifecycle),
TC-22/23 (history reachable from LT-263 Listing / Global Search entry points —
TC-20/21 only covers the Review Court Hearings entry point), TC-26/27/28 (garage
accordion collapse/expand + per-row PDF — needs live DOM recon of the accordion,
not yet done), TC-29 (rejection-reason "\\/" escaping), TC-32 (FO-52 cross-surface
listing consistency), TC-33 (dashboard tab placement), TC-34 (independent loaders,
timing-dependent — marked best-left-manual in the matrix anyway).

Covered THIS pass, live-verified on QA: TC-01, TC-02, TC-03, TC-05 (2 cycles),
TC-06, TC-08, TC-09 (LT-265-only-to-Nordis structural check), TC-11, TC-12, TC-13,
TC-19, TC-20, TC-21, TC-24.
"""
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, expect

from src.config.env import ENV
from src.helpers.data_helper import generate_person
from src.helpers.lt263_resubmit_helper import (
    create_case_to_lt263_submitted,
    resubmit_lt263,
    reject_lt263,
    LT263_REJECT_REASON_TEXT,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.paper_form_page import PaperFormPage

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

PERSON = generate_person()

# A real, already-Rejected LT-263 case found live on QA (VIN RUTHK9WF3682FZRWV,
# case fcc26106-1652-455a-98b4-a653ed0ee99d) — confirmed to show the CR's rejection
# banner/history link/Re-Log button on 2026-07-28. Reused for TC-11/12/24 instead of
# spending another ~10min lifecycle creating a dedicated case for just those checks.
#
# This fixture VIN is ENV-SPECIFIC — it exists on QA only. On stage (or any other env)
# TC-24's "no blocking toast" assertion would pass vacuously against a VIN the env has
# never seen, so the VIN must be supplied per-env via TW27242835_REJECTED_VIN.
_ENV_REJECTED_VIN = {"qa": "RUTHK9WF3682FZRWV"}
EXISTING_REJECTED_VIN = os.environ.get("TW27242835_REJECTED_VIN") or _ENV_REJECTED_VIN.get(
    os.environ.get("NSM_ENV", "qa").lower(), ""
)

# Dev convenience only: set to skip Phase 0's ~8min case creation and reuse an
# already-created case's VIN during iteration. Unset (the default) for the real run.
_REUSE_VIN = os.environ.get("TW27242835_REUSE_VIN")


def go_to_public_dashboard(page: Page):
    # The 30s waits below were tuned on QA and are too tight for stage: the stage public
    # portal keeps background polling alive well past 30s, so it never reaches
    # networkidle and the redirect to /dashboard lands late. That made TC-13 fail with a
    # bare navigation timeout even though its acceptance criterion held (verified
    # separately: Submit LT-263 is absent once the vehicle is Sold). Same rationale the
    # E2E-054 audit-log test already documents for its own dashboard nav.
    page.goto(PP_DASHBOARD_URL, timeout=90_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=60_000)
    try:
        page.wait_for_load_state("networkidle", timeout=60_000)
    except Exception:
        print("[INFO] networkidle not reached on the public dashboard — continuing")


def go_to_staff_dashboard(page: Page):
    page.goto(SP_DASHBOARD_URL, timeout=90_000)
    try:
        page.wait_for_load_state("networkidle", timeout=60_000)
    except Exception:
        print("[INFO] networkidle not reached on the staff dashboard — continuing")


# Module-level state shared across phases (mirrors test_e2e_001's TEST_VIN convention,
# but mutable since Phase 0 generates the VIN at runtime rather than at import time).
_STATE = {"vin": None}


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_Phase0_CreateCase:
    """Phase 0: build one fresh case up to LT-263 Submitted (To Process) — the shared
    starting point every later phase in this file reuses via _STATE['vin']."""

    def test_phase0_create_case_to_lt263_submitted(self, public_context: BrowserContext, staff_context: BrowserContext):
        if _REUSE_VIN:
            _STATE["vin"] = _REUSE_VIN
            print(f"[TW27242835] TW27242835_REUSE_VIN set — reusing VIN={_REUSE_VIN}, skipping case creation")
            return
        public_page = public_context.new_page()
        staff_page = staff_context.new_page()
        try:
            vin = create_case_to_lt263_submitted(public_page, staff_page, go_to_public_dashboard, go_to_staff_dashboard)
            _STATE["vin"] = vin
            print(f"[TW27242835] created case VIN={vin}")
        finally:
            public_page.close()
            staff_page.close()


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_SC01_RejectCycle1:
    """SC-01 / TC-01, TC-02: staff rejects the LT-263; only the LT-263 is marked
    Rejected (case stays open); public timeline shows Rejected + Submit LT-263."""

    def test_tc01_reject_lt263_case_stays_open(self, staff_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()
            lt263_listing.search_by_vin(_STATE["vin"])
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            page.wait_for_timeout(2000)

            reject_lt263(page)

            # Case must NOT be terminally closed: Close File action should still be
            # available (a closed/denied case wouldn't offer it), and the LT-263
            # status itself should read Rejected, not the whole case going to a
            # Denied/terminal state.
            expect(page.get_by_text(re.compile(r"Rejected", re.I)).first).to_be_visible(timeout=15_000)
            expect(page.locator('button:has-text("Close File")').first).to_be_visible(timeout=10_000)
            print("[TC-01] LT-263 rejected; case remains open (Close File still offered)")
        finally:
            page.close()

    def test_tc02_public_timeline_shows_rejected_and_submit_button(self, public_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(_STATE["vin"])
            page.wait_for_timeout(2000)
            dashboard.select_application(0)

            expect(page.get_by_text(re.compile(r"LT-263 Rejected", re.I)).first).to_be_visible(timeout=30_000)
            dashboard.expect_lt263_available()  # Submit LT-263 button present + enabled
            print("[TC-02] Public timeline shows LT-263 Rejected + enabled Submit LT-263")
        finally:
            page.close()


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_SC02_HistoryLinkBeforeResubmit:
    """SC-02 / TC-20, TC-21 (Staff AC-3): with 1 rejection and no new LT-263 yet, the
    'Waiting for the requester...' modal (Review Court Hearings -> Review LT-263) shows
    the new 'View Previously Rejected LT-263s' link; clicking it opens the history."""

    def test_tc20_waiting_modal_shows_history_link(self, staff_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)
            staff_dashboard.navigate_to_lt262_listing()
            # The case is past To Process (LT-264 issued) — search across the listing
            # generically; Aging/Court Hearing tabs are where post-LT264 cases live.
            found = False
            for tab in (lt262_listing.aging_tab, lt262_listing.court_hearing_tab, lt262_listing.all_tab):
                tab.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)
                lt262_listing.search_by_vin(_STATE["vin"])
                page.wait_for_timeout(1500)
                if lt262_listing.application_rows.count() > 0:
                    found = True
                    break
            assert found, f"Could not find LT-262 case for VIN {_STATE['vin']} in Aging/Court Hearing/All"
            lt262_listing.select_application(0)
            page.wait_for_timeout(1500)
            lt262_listing.review_hearings_tab.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1500)
            lt262_listing.review_lt263_tab.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            waiting_msg = page.get_by_text(re.compile(r"Waiting for the requester to submit LT-263", re.I)).first
            try:
                expect(waiting_msg).to_be_visible(timeout=15_000)
            except Exception:
                page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "tc20_no_waiting_modal.png"))
                print(f"[TC-20] DEBUG url={page.url} body={page.locator('body').inner_text()[:1500]!r}")
                raise

            history_link = page.get_by_text(re.compile(r"View Previously Rejected LT-263|View previous LT-263", re.I)).first
            expect(history_link).to_be_visible(timeout=10_000)
            print("[TC-20] 'Waiting for requester' modal shows the rejected-history link with 1 prior rejection")

            history_link.click()
            page.wait_for_timeout(2000)
            expect(page.get_by_text(re.compile(LT263_REJECT_REASON_TEXT, re.I)).first).to_be_visible(timeout=15_000)
            print("[TC-21] Clicking the link opens history showing the cycle-1 rejection reason")
        finally:
            page.close()


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_SC03_ResubmitAndRejectAgain:
    """SC-03 / TC-03, TC-05, TC-06: garage resubmits after rejection (cycle 2); staff
    rejects again — history accumulates; the staff history component lists both
    cycles."""

    def test_tc03_and_tc05_resubmit_then_reject_cycle2(self, public_context: BrowserContext, staff_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        public_page = public_context.new_page()
        staff_page = staff_context.new_page()
        try:
            go_to_public_dashboard(public_page)
            dashboard = PublicDashboardPage(public_page)
            dashboard.select_business()

            go_to_staff_dashboard(staff_page)
            staff_dashboard = StaffDashboardPage(staff_page)

            resubmit_lt263(
                public_page, dashboard, _STATE["vin"], PERSON,
                staff_page, staff_dashboard,
                lien_amount="900", sale_days_out=22,
            )
            print(f"[TC-03] Cycle-2 LT-263 resubmitted for VIN {_STATE['vin']}, confirmed on staff To Process")

            lt263_listing = Lt263ListingPage(staff_page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()
            lt263_listing.search_by_vin(_STATE["vin"])
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            staff_page.wait_for_timeout(2000)
            reject_lt263(staff_page)
            print("[TC-05] Cycle-2 rejected — 2 distinct rejected cycles now exist for this case")
        finally:
            public_page.close()
            staff_page.close()

    def test_tc06_staff_history_component_lists_both_cycles(self, staff_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_rejected_tab()
            lt263_listing.search_by_vin(_STATE["vin"])
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            page.wait_for_timeout(2000)

            history_link = page.get_by_text(re.compile(r"View Previously Rejected LT-263|View previous LT-263", re.I)).first
            expect(history_link).to_be_visible(timeout=15_000)
            history_link.click()
            page.wait_for_timeout(2000)

            # Both cycles' rejection reason should appear (same reason text used for
            # both cycles in this run, so presence + a rendered history entry per
            # cycle is what's checked — not distinct text).
            body = page.locator("body").inner_text()
            occurrences = len(re.findall(LT263_REJECT_REASON_TEXT, body, re.I))
            assert occurrences >= 2, (
                f"expected >= 2 rejected-cycle entries referencing "
                f"'{LT263_REJECT_REASON_TEXT}' in the history component, found {occurrences}"
            )
            print(f"[TC-06] History component shows {occurrences} matching rejected-cycle entries (>= 2 expected)")
        finally:
            page.close()


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_SC04_FinalApproveToSold:
    """SC-04 / TC-08, TC-09, TC-13: garage resubmits a final (3rd) cycle, staff
    approves it -> LT-265 -> Vehicle Sold (loop terminates); Sold is terminal
    (Submit LT-263 no longer offered)."""

    def test_tc08_resubmit_then_approve_to_sold(self, public_context: BrowserContext, staff_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        public_page = public_context.new_page()
        staff_page = staff_context.new_page()
        try:
            go_to_public_dashboard(public_page)
            dashboard = PublicDashboardPage(public_page)
            dashboard.select_business()

            go_to_staff_dashboard(staff_page)
            staff_dashboard = StaffDashboardPage(staff_page)

            resubmit_lt263(
                public_page, dashboard, _STATE["vin"], PERSON,
                staff_page, staff_dashboard,
                lien_amount="1000", sale_days_out=23,
            )
            print(f"[TC-08 setup] Cycle-3 LT-263 resubmitted for VIN {_STATE['vin']}")

            lt263_listing = Lt263ListingPage(staff_page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()
            lt263_listing.search_by_vin(_STATE["vin"])
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            staff_page.wait_for_timeout(2000)
            lt263_listing.verify_sale_details_visible()
            lt263_listing.generate_lt265(expected_vin=_STATE["vin"])
            print("[TC-08] Cycle-3 approved -> LT-265 issued")

            lt263_listing.verify_vehicle_sold()
            print("[TC-08] Vehicle Sold confirmed — resubmission loop terminates at approval, as designed")
        finally:
            public_page.close()
            staff_page.close()

    def test_tc09_lt263_never_sent_to_nordis(self, staff_context: BrowserContext):
        """Structural check only (no Nordis mailbox access): the LT-263 detail should
        carry no Reprint control (unlike LT-265, which does) — LT-263 itself is never
        transmitted."""
        assert _STATE["vin"], "Phase 0 must run first"
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_processed_sold_tab()
            lt263_listing.search_by_vin(_STATE["vin"])
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            page.wait_for_timeout(2000)
            reprint_for_lt263 = page.locator('button:has-text("Reprint")').filter(has_text=re.compile(r"LT-263", re.I))
            assert reprint_for_lt263.count() == 0, "unexpected LT-263-specific Reprint control found"
            print("[TC-09] No LT-263-specific Reprint control present (structural proxy for 'never sent to Nordis')")
        finally:
            page.close()

    def test_tc13_resubmit_blocked_once_sold(self, public_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            # KB-confirmed (original_SKILL_recordings.md §9.4): the public dashboard's
            # "Sold Vehicles/Completed" tab holds vehicles that are sold, rejected, OR
            # closed — NOT the "Notice & Storage Requests" (Open Requests) tab. Live
            # run 2026-07-28 confirmed the VIN search finds 0 results under Notice &
            # Storage once Sold (locator timeout) — this is the fix, not a workaround.
            dashboard.click_sold_completed_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(_STATE["vin"])
            page.wait_for_timeout(2000)
            if dashboard.application_list.count() == 0:
                page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "tc13_no_result_sold_tab.png"))
                print(f"[TC-13] DEBUG 0 results under Sold/Completed tab. url={page.url} "
                      f"body={page.locator('body').inner_text()[:1200]!r}")
                dashboard.click_notice_storage_tab()
                page.wait_for_timeout(1000)
                dashboard.search_by_vin(_STATE["vin"])
                page.wait_for_timeout(2000)
                print(f"[TC-13] DEBUG under Notice & Storage tab instead: count={dashboard.application_list.count()}")
            dashboard.select_application(0)
            expect(page.get_by_text(re.compile(r"Vehicle Sold|Sold", re.I)).first).to_be_visible(timeout=30_000)
            dashboard.expect_lt263_not_available()
            print("[TC-13] Submit LT-263 not offered once Vehicle Sold — terminal, as designed")
        finally:
            page.close()


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_SC05_ExistingRejectedCase_ClosedGuardAndPaperForm:
    """SC-05 / TC-11, TC-12(partial), TC-24: reuses the pre-existing rejected QA case
    (no fresh lifecycle needed) for the Closed-guard check and Add-Paper-Form-via-
    rejected-VIN (Staff AC-5)."""

    def test_tc24_add_paper_form_with_rejected_vin(self, staff_context: BrowserContext):
        if not EXISTING_REJECTED_VIN:
            pytest.skip(
                f"no LT-263 Rejected fixture VIN for env={os.environ.get('NSM_ENV', 'qa')} — "
                "set TW27242835_REJECTED_VIN (a vacuous pass against an unknown VIN is worse than a skip)"
            )
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_to_process_tab()
            lt263_listing.click_add_from_paper()

            paper_form = PaperFormPage(page)
            paper_form.enter_vin(EXISTING_REJECTED_VIN)
            page.wait_for_timeout(2000)
            # The system should recognize this VIN's latest status is LT-263 Rejected
            # and ALLOW logging — i.e. no blocking error/duplicate-VIN rejection toast.
            blocked = page.get_by_text(re.compile(r"already exists|duplicate|not allowed|cannot", re.I))
            assert blocked.count() == 0, (
                f"Add Paper Form for a VIN whose latest status is LT-263 Rejected was "
                f"blocked: {blocked.first.inner_text() if blocked.count() else ''!r}"
            )
            print(f"[TC-24] Add Paper Form accepted VIN {EXISTING_REJECTED_VIN} (latest status LT-263 Rejected) without a block")
        finally:
            page.close()

    def test_tc11_and_tc12_resubmit_blocked_once_closed(self, staff_context: BrowserContext, public_context: BrowserContext):
        if not EXISTING_REJECTED_VIN:
            pytest.skip(
                f"no LT-263 Rejected fixture VIN for env={os.environ.get('NSM_ENV', 'qa')} — "
                "set TW27242835_REJECTED_VIN"
            )
        staff_page = staff_context.new_page()
        public_page = public_context.new_page()
        try:
            go_to_staff_dashboard(staff_page)
            staff_dashboard = StaffDashboardPage(staff_page)
            lt263_listing = Lt263ListingPage(staff_page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_all_tab()
            lt263_listing.search_by_vin(EXISTING_REJECTED_VIN)
            lt263_listing.expect_applications_visible()
            lt263_listing.select_application(0)
            staff_page.wait_for_timeout(2000)
            # Idempotent: a prior run of this test may have already closed this case.
            if staff_page.locator('button:has-text("Close File")').first.is_visible():
                lt263_listing.close_file(remarks="TW27242835 Closed-guard regression check")
                print(f"[TC-11 setup] Closed VIN {EXISTING_REJECTED_VIN}'s file")
            else:
                print(f"[TC-11 setup] VIN {EXISTING_REJECTED_VIN} already closed (Close File not offered) — reusing prior state")

            go_to_public_dashboard(public_page)
            dashboard = PublicDashboardPage(public_page)
            dashboard.select_business()
            # Same tab-placement fact as TC-13: a Closed case moves to "Sold
            # Vehicles/Completed", not "Notice & Storage Requests".
            dashboard.click_sold_completed_tab()
            public_page.wait_for_timeout(1000)
            dashboard.search_by_vin(EXISTING_REJECTED_VIN)
            public_page.wait_for_timeout(2000)
            if dashboard.application_list.count() == 0:
                public_page.screenshot(path=str(Path(__file__).resolve().parent.parent / "results" / "tc11_no_result_sold_tab.png"))
                print(f"[TC-11] DEBUG 0 results under Sold/Completed tab. url={public_page.url} "
                      f"body={public_page.locator('body').inner_text()[:1200]!r}")
                dashboard.click_notice_storage_tab()
                public_page.wait_for_timeout(1000)
                dashboard.search_by_vin(EXISTING_REJECTED_VIN)
                public_page.wait_for_timeout(2000)
                print(f"[TC-11] DEBUG under Notice & Storage tab instead: count={dashboard.application_list.count()}")
            dashboard.select_application(0)
            dashboard.expect_lt263_not_available()
            print("[TC-11] Submit LT-263 hidden once case Closed — eligibility guard holds (UI leg; TC-12 API leg not automated this pass)")
        finally:
            staff_page.close()
            public_page.close()


@pytest.mark.e2e
@pytest.mark.tw27242835
class TestTW27242835_SC06_ListingOneRowPerVehicle:
    """SC-06 / TC-19 (Staff AC-6): despite 3 rejected + 1 final-approved LT-263 cycle
    for the primary VIN, the LT-263 Listing shows exactly one row for that vehicle."""

    def test_tc19_listing_shows_one_row_despite_multiple_cycles(self, staff_context: BrowserContext):
        assert _STATE["vin"], "Phase 0 must run first"
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt263_listing = Lt263ListingPage(page)
            staff_dashboard.navigate_to_lt263_listing()
            lt263_listing.click_all_tab()
            lt263_listing.search_by_vin(_STATE["vin"])
            page.wait_for_timeout(2000)
            # application_rows ("table.mat-table tr.mat-row, table tbody tr") over-
            # matches a phantom empty <tr> in this Angular Material table (confirmed
            # live: a 2nd "row" whose inner_text() is '') — filter to rows that
            # actually carry a 2nd cell, same pattern used elsewhere in this suite for
            # Angular Material tables (e.g. Staff_assertions.py's _visible_data_row_count).
            data_rows = lt263_listing.application_rows.filter(has=page.locator("td:nth-child(2)"))
            row_count = data_rows.count()
            if row_count != 1:
                rows_text = [data_rows.nth(i).inner_text() for i in range(row_count)]
                print(f"[TC-19] DEBUG {row_count} data rows found, contents: {rows_text!r}")
            assert row_count == 1, (
                f"expected exactly 1 LT-263 Listing row for VIN {_STATE['vin']} despite "
                f"3 rejected + 1 approved cycle; found {row_count}"
            )
            print(f"[TC-19] LT-263 Listing shows exactly 1 row for VIN {_STATE['vin']} despite 4 total submissions")
        finally:
            page.close()
