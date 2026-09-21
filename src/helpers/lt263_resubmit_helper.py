"""
Shared workflow helper for TW#27242835 / NCNSS-212 (LT-263 re-submission after DMV
rejection). Builds a fresh case up to "LT-263 Submitted (To Process)" — the same path
as test_e2e_001's phases 1-5A — so ticket-specific tests can drive the reject/resubmit
loop from a known-good starting point without duplicating the whole lifecycle inline.

Reuses the exact page-object calls test_e2e_001_standard_vehicle_lifecycle.py uses;
kept as a separate function (not an import from that test module) so this ticket's
automation has no coupling to E2E-001's test collection/fixtures.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page, expect

from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    past_date,
    generate_person,
)
from src.config.env import ENV
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage

BUSINESS_NAME = ENV.PUBLIC_BUSINESS_NAME
SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent.parent / "fixtures" / "sample-document.pdf")

# The default rejection reason for this ticket's automation — chosen because its
# checkbox needs no embedded text-field fill (unlike "REMIT CORRECT FEE OF" or
# "PROVIDE STATEMENT ... SAME PERSON", which reveal extra inputs). Confirmed live via
# the modal recon (2026-07-28) as one of 9 predefined reasons in the LT-263 "Reject
# Case" modal — a checkbox-list modal (same UI pattern as lt260_listing_page.py's
# reject_application()), NOT the free-text pattern workflow_helper.py's
# sp_reject_lt260() uses. This is the SAME reason text already observed live on an
# existing pre-CR QA case (RUTHK9WF3682FZRWV), so it's a real, in-use reason.
LT263_REJECT_REASON_TEXT = "PROVIDE COMPLETE LEVY INFORMATION"


def reject_lt263(page: Page, reason_text: str = LT263_REJECT_REASON_TEXT):
    """Reject the LT-263 currently open on its detail/Review LT-263 page. Opens the
    'Reject Case' modal, checks the named reason's checkbox, clicks Reject. Assumes
    the Reject button is already visible (caller is on a rejectable LT-263)."""
    reject_btn = page.locator('button:has-text("Reject")').first
    expect(reject_btn).to_be_visible(timeout=15_000)
    reject_btn.click()
    page.wait_for_timeout(1500)

    expect(page.get_by_text(re.compile(r"Reject Case", re.I)).first).to_be_visible(timeout=10_000)
    reason_checkbox = page.locator(
        f'//mat-checkbox[.//span[contains(text(),"{reason_text}")]]'
    ).first
    reason_checkbox.wait_for(state="visible", timeout=10_000)
    if "mat-checkbox-checked" not in (reason_checkbox.get_attribute("class") or ""):
        reason_checkbox.locator("label").click()
        page.wait_for_timeout(500)

    confirm_btn = page.locator('mat-dialog-container').get_by_role("button", name=re.compile(r"^\s*Reject\s*$", re.I)).last
    expect(confirm_btn).to_be_enabled(timeout=10_000)
    confirm_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def _submit_lt263_form(page: Page, person: dict, lien_amount: str = "800", sale_days_out: int = 21):
    """The LT-263 form-fill sequence (public portal), from the 'Submit LT-263' click
    through the success banner. Shared by first submission AND every resubmission —
    the CR's core claim is that this exact flow is repeatable after a rejection."""
    _RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "results"

    def _snap(tag: str):
        try:
            page.screenshot(path=str(_RESULTS_DIR / f"lt263_form_{tag}.png"))
        except Exception:
            pass

    expect(page.get_by_text(re.compile(r"LT-263.*Form Details", re.I)).first).to_be_visible(timeout=30_000)
    print("  [lt263-form] on LT-263 Form Details")

    sale_type_dropdown = page.locator('mat-select[aria-label*="Type of Sale" i]').first
    try:
        sale_type_dropdown.wait_for(state="visible", timeout=5_000)
        sale_type_dropdown.click()
        page.wait_for_timeout(500)
        page.locator('mat-option:has-text("Public")').first.click()
        page.wait_for_timeout(500)
        print("  [lt263-form] Type of Sale set via dropdown")
    except Exception as e:
        print(f"  [lt263-form] dropdown path failed ({e}); trying Lt263FormPage.select_public_sale()")
        Lt263FormPage(page).select_public_sale()

    sale_date = (datetime.now() + timedelta(days=sale_days_out)).strftime("%m/%d/%Y")
    sale_date_input = page.locator('input[aria-label*="Sale Date" i], input[placeholder*="MM/DD/YYYY"]').first
    sale_date_input.wait_for(state="visible", timeout=10_000)
    sale_date_input.fill(sale_date)
    page.wait_for_timeout(500)
    print(f"  [lt263-form] Sale Date filled: {sale_date!r} (actual value={sale_date_input.input_value()!r})")

    lien_amount_input = page.locator(
        'input[aria-label*="Lien Amount" i], input[name*="lien" i][name*="amount" i]'
    ).first
    lien_amount_input.wait_for(state="visible", timeout=10_000)
    lien_amount_input.fill(lien_amount)
    page.wait_for_timeout(500)
    print(f"  [lt263-form] Lien Amount filled (actual value={lien_amount_input.input_value()!r})")
    _snap("before_next")

    next_btn = page.locator('button:has-text("Next")').first
    next_btn.wait_for(state="visible", timeout=30_000)
    print(f"  [lt263-form] Next button enabled={next_btn.is_enabled()}")
    next_btn.scroll_into_view_if_needed()
    next_btn.click()
    page.wait_for_timeout(2000)

    try:
        expect(page.get_by_text(re.compile(r"Terms and Conditions", re.I)).first).to_be_visible(timeout=15_000)
        print("  [lt263-form] advanced to Terms and Conditions")
    except Exception:
        _snap("next_did_not_advance")
        print(f"  [lt263-form] WARN: Next click didn't reach Terms and Conditions. url={page.url} "
              f"body={page.locator('body').inner_text()[:500]!r}")
        raise

    mat_checkboxes = page.locator("mat-checkbox")
    cb_count = mat_checkboxes.count()
    print(f"  [lt263-form] {cb_count} mat-checkbox controls found on T&C page")
    for i in range(cb_count):
        cb = mat_checkboxes.nth(i)
        if "mat-checkbox-checked" not in (cb.get_attribute("class") or ""):
            cb.locator("label").click()
            page.wait_for_timeout(200)

    name_input = page.locator('input[aria-label*="Name" i], input[aria-label*="NAME" i]').first
    name_input.wait_for(state="visible", timeout=10_000)
    name_input.fill(person["name"])

    date_input = page.locator('input[aria-label*="Date" i], input[aria-label*="DATE" i]').first
    try:
        date_input.wait_for(state="visible", timeout=5_000)
        if not date_input.input_value():
            date_input.fill(datetime.now().strftime("%m/%d/%Y"))
    except Exception:
        pass
    _snap("before_submit")

    submit_btn = page.locator('button:has-text("Submit")').first
    submit_btn.wait_for(state="visible", timeout=30_000)
    print(f"  [lt263-form] Submit button enabled={submit_btn.is_enabled()}")
    submit_btn.scroll_into_view_if_needed()

    # CONFIRMED LIVE (2026-07-28, screenshot lt263_form_after_submit.png): the success
    # toast appears almost immediately after the click and is transient — checking it
    # AFTER a settle delay (the original approach, copied from test_e2e_001) can miss it
    # if the toast has already auto-dismissed by the time the assertion starts polling.
    # Check immediately, no prior wait_for_timeout.
    submit_btn.click()
    try:
        expect(page.get_by_text(re.compile(r"Form is submitted successfully", re.I)).first).to_be_visible(timeout=10_000)
        print("  [lt263-form] success toast seen")
    except Exception:
        _snap("after_submit_no_toast")
        # The page body carries glyphs (the header's '▾' etc.) that a cp1252 Windows
        # console can't encode — printing it raw raised UnicodeEncodeError and killed
        # the run INSIDE the warning path, after a submission that had actually
        # succeeded. Keep diagnostics ASCII-safe so this branch can never be fatal.
        body = page.locator("body").inner_text()[:800].encode("ascii", "replace").decode("ascii")
        print(f"  WARN: 'Form is submitted successfully' toast not seen - continuing. "
              f"url={page.url} body={body!r}")
    _snap("after_submit")
    # NOTE: this page does NOT auto-redirect after submit — it stays on the LT-263 form
    # URL with the Submit button now disabled. That's normal, not a failure; the caller
    # is responsible for verifying the submission landed (staff-side, in
    # create_case_to_lt263_submitted — the public dashboard's own status search lagged
    # by more than a minute in live testing and is not a reliable signal here).


def create_case_to_lt263_submitted(public_page: Page, staff_page: Page, go_to_public_dashboard, go_to_staff_dashboard,
                                   address: dict | None = None, person: dict | None = None,
                                   lien_amount: str = "800", sale_days_out: int = 21) -> str:
    """Full lifecycle to a fresh LT-263-Submitted (To Process) case: LT-260 -> staff
    process -> LT-262 + pay -> staff DCI/LT-264 -> track/court -> submit LT-263.
    Returns the generated VIN. `go_to_public_dashboard`/`go_to_staff_dashboard` are the
    same nav helpers test_e2e_001 defines (passed in to avoid a circular import).

    `address`/`person` pin the case to specific data instead of the random defaults —
    used by scripts/submit_lt263.py to place a case in a named city (the portal derives
    city/county from the ZIP, so the ZIP is what actually pins the location)."""
    vin = generate_vin()
    # Print immediately: a failure anywhere in the ~8min lifecycle below used to lose
    # the VIN entirely (it was only returned on success), leaving a real case stranded
    # in QA with no way to find it except by timestamp.
    print(f"  [lifecycle] VIN={vin}")
    vehicle = random_vehicle()
    plate = generate_license_plate()
    address = address or generate_address()
    person = person or generate_person()

    # Phase 1 — Public: create + submit LT-260
    go_to_public_dashboard(public_page)
    dashboard = PublicDashboardPage(public_page)
    dashboard.select_business(BUSINESS_NAME)
    dashboard.click_start_here()
    lt260 = Lt260FormPage(public_page)
    lt260.enter_vin(vin)
    lt260.fill_vehicle_details(vehicle)
    lt260.fill_date_vehicle_left(past_date(30))
    lt260.fill_license_plate(plate)
    lt260.fill_approx_value("5000")
    lt260.select_reason_storage()
    lt260.fill_storage_location("Test Storage Facility", address["street"], address["zip"])
    lt260.fill_authorized_person(person["name"], address["street"], address["zip"])
    lt260.accept_terms_and_sign(person["name"], person["email"])
    lt260.submit_with_vin_image()
    public_page.wait_for_timeout(2000)
    try:
        public_page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
    except Exception:
        pass

    # Phase 2 — Staff: process LT-260
    go_to_staff_dashboard(staff_page)
    staff_dashboard = StaffDashboardPage(staff_page)
    lt260_listing = Lt260ListingPage(staff_page)
    form_processing = FormProcessingPage(staff_page)
    staff_dashboard.navigate_to_lt260_listing()
    lt260_listing.click_to_process_tab()
    lt260_listing.search_by_vin(vin)
    lt260_listing.select_application(0)
    form_processing.expect_detail_page_visible()
    form_processing.click_edit()
    form_processing.add_owner(person["name"], address["street"], address["zip"])
    form_processing.select_stolen_no()
    form_processing.click_save()
    form_processing.issue_160b_and_260a()
    form_processing.expect_issued_success_toast()
    form_processing.expect_status_processed()

    # Phase 3 — Public: submit + pay LT-262
    go_to_public_dashboard(public_page)
    dashboard.select_business(BUSINESS_NAME)
    dashboard.click_notice_storage_tab()
    public_page.wait_for_timeout(1000)
    dashboard.search_by_vin(vin)
    public_page.wait_for_timeout(2000)
    dashboard.select_application(0)
    dashboard.expect_application_processed()
    dashboard.click_submit_lt262()
    lt262 = Lt262FormPage(public_page)
    lt262.expect_form_tabs_visible()
    lt262.skip_vehicle_and_location_tabs()
    lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})
    lt262.fill_date_of_storage(past_date(30))
    lt262.fill_person_authorizing(person["name"], address["street"], address["zip"])
    lt262.fill_additional_details(person["name"], address["street"], address["zip"])
    lt262.upload_documents([SAMPLE_DOC_PATH])
    lt262.accept_terms_and_sign(person["name"])
    lt262.finish_and_pay()
    pay_drawdown_btn = public_page.locator('button:has-text("Pay Using ACH/Drawdown")')
    pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
    pay_drawdown_btn.click()
    public_page.wait_for_timeout(2000)
    yes_btn = public_page.locator('mat-dialog-container button:has-text("Yes")').first
    yes_btn.wait_for(state="visible", timeout=10_000)
    yes_btn.click()
    public_page.wait_for_timeout(3000)
    expect(public_page.get_by_text("Your payment has been completed successfully")).to_be_visible(timeout=30_000)
    public_page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)

    # Phase 4 — Staff: process LT-262 -> issue LT-264
    go_to_staff_dashboard(staff_page)
    lt262_listing = Lt262ListingPage(staff_page)
    staff_dashboard.navigate_to_lt262_listing()
    lt262_listing.click_to_process_tab()
    lt262_listing.search_by_vin(vin)
    lt262_listing.select_application(0)
    lt262_listing.verify_lien_details_visible()
    lt262_listing.verify_owner_details_visible()
    lt262_listing.issue_lt264()
    expect(staff_page.get_by_text("The form has been issued successfully.")).to_be_visible(timeout=30_000)
    expect(staff_page.locator('[role="tab"]:has-text("TRACK LT-264")')).to_be_visible(timeout=10_000)

    # Phase 5 — Staff: track LT-264, log court hearing outcome
    staff_dashboard.navigate_to_lt262_listing()
    lt262_listing.click_aging_tab()
    staff_page.wait_for_load_state("networkidle")
    staff_page.wait_for_timeout(8000)
    lt262_listing.search_by_vin(vin)
    if lt262_listing.application_rows.count() == 0:
        lt262_listing.court_hearing_tab.click()
        staff_page.wait_for_load_state("networkidle")
        lt262_listing.search_by_vin(vin)
    lt262_listing.select_application(0)
    lt262_listing.click_track_lt264_tab()
    staff_page.wait_for_timeout(2000)
    log_receipt_cb = staff_page.locator("mat-checkbox").first
    if "mat-checkbox-checked" not in (log_receipt_cb.get_attribute("class") or ""):
        log_receipt_cb.locator("label").click()
        staff_page.wait_for_timeout(1000)
    hearing_cb = staff_page.locator("mat-checkbox").nth(1)
    hearing_cb.wait_for(state="visible", timeout=10_000)
    if "mat-checkbox-checked" not in (hearing_cb.get_attribute("class") or ""):
        hearing_cb.locator("label").click()
        staff_page.wait_for_timeout(500)
    save_btn = staff_page.locator('button:has-text("Save")').first
    save_btn.wait_for(state="visible", timeout=30_000)
    save_btn.scroll_into_view_if_needed()
    save_btn.click()
    staff_page.wait_for_timeout(2000)
    yes_btn2 = staff_page.locator('mat-dialog-container button:has-text("Yes")').first
    yes_btn2.wait_for(state="visible", timeout=10_000)
    yes_btn2.click()
    staff_page.wait_for_timeout(3000)
    possessory_text = staff_page.get_by_text(re.compile(r"Judgment in action of Possessory Lien", re.I)).first
    possessory_text.wait_for(state="visible", timeout=30_000)
    staff_page.wait_for_timeout(2000)
    possessory_cb = staff_page.locator("mat-checkbox").first
    possessory_cb.wait_for(state="visible", timeout=10_000)
    if "mat-checkbox-checked" not in (possessory_cb.get_attribute("class") or ""):
        possessory_cb.locator("label").click()
        staff_page.wait_for_timeout(1000)
    save_btn3 = staff_page.locator('button:has-text("Save")').first
    save_btn3.wait_for(state="visible", timeout=30_000)
    save_btn3.scroll_into_view_if_needed()
    save_btn3.click()
    staff_page.wait_for_timeout(2000)
    yes_btn3 = staff_page.locator('mat-dialog-container button:has-text("Yes")').first
    yes_btn3.wait_for(state="visible", timeout=10_000)
    yes_btn3.click()
    staff_page.wait_for_timeout(3000)
    expect(staff_page.get_by_text(re.compile(r"success", re.I)).first).to_be_visible(timeout=30_000)
    next_btn2 = staff_page.locator('button:has-text("Next")').first
    next_btn2.wait_for(state="visible", timeout=30_000)
    next_btn2.scroll_into_view_if_needed()
    next_btn2.click()
    staff_page.wait_for_timeout(2000)
    # This is the exact "Waiting for the requester to submit LT-263." modal Staff AC-3
    # attaches its new "View Previously Rejected LT-263s" link to (absent here — zero
    # rejections yet on a fresh case).
    waiting_msg = staff_page.get_by_text("Waiting for the requester to submit LT-263.")
    expect(waiting_msg).to_be_visible(timeout=10_000)

    # Phase 5A — Public: submit LT-263 (first submission)
    go_to_public_dashboard(public_page)
    dashboard.select_business(BUSINESS_NAME)
    dashboard.click_notice_storage_tab()
    public_page.wait_for_timeout(1000)
    dashboard.search_by_vin(vin)
    public_page.wait_for_timeout(2000)
    dashboard.select_application(0)
    expect(public_page.get_by_text(re.compile(r"LT-262 Processed", re.I)).first).to_be_visible(timeout=30_000)
    dashboard.expect_lt263_available()
    dashboard.click_submit_lt263()
    public_page.wait_for_timeout(2000)
    _submit_lt263_form(public_page, person, lien_amount=lien_amount, sale_days_out=sale_days_out)

    # Verify the submission landed STAFF-side (the public dashboard's own status
    # search lagged unreliably in live testing — see the note in _submit_lt263_form).
    # This is also the more meaningful check: it's the exact state the reject-flow
    # tests need (VIN present on the LT-263 'To Process' tab).
    staff_dashboard.navigate_to_lt263_listing()
    lt263_listing = Lt263ListingPage(staff_page)
    lt263_listing.click_to_process_tab()
    for attempt in range(4):
        lt263_listing.search_by_vin(vin)
        staff_page.wait_for_timeout(2000)
        if lt263_listing.application_rows.count() > 0:
            break
        if attempt == 3:
            raise AssertionError(
                f"LT-263 submission for VIN {vin} did not appear on the staff LT-263 "
                f"'To Process' tab after 4 attempts, despite the public-portal success toast."
            )
        print(f"  WARN: VIN {vin} not yet on LT-263 To Process tab (attempt {attempt + 1}/4) — reloading")
        staff_page.reload(timeout=30_000)
        staff_page.wait_for_load_state("networkidle")
        lt263_listing.click_to_process_tab()

    return vin


def resubmit_lt263(public_page: Page, dashboard: PublicDashboardPage, vin: str, person: dict,
                    staff_page: Page, staff_dashboard: StaffDashboardPage,
                    lien_amount: str = "800", sale_days_out: int = 21):
    """Re-submit a new LT-263 for a case whose latest status is 'LT-263 Rejected'
    (Garage Dashboard AC-1/AC-2). Assumes `public_page` is already on/can reach the
    dashboard; navigates to the case and clicks the accordion's 'Submit LT-263' button.
    Verifies the resubmission landed staff-side (LT-263 'To Process' tab) before
    returning — same rationale as create_case_to_lt263_submitted."""
    dashboard.select_business(BUSINESS_NAME)
    dashboard.click_notice_storage_tab()
    public_page.wait_for_timeout(1000)
    dashboard.search_by_vin(vin)
    public_page.wait_for_timeout(2000)
    dashboard.select_application(0)
    expect(public_page.get_by_text(re.compile(r"LT-263 Rejected", re.I)).first).to_be_visible(timeout=30_000)
    dashboard.click_submit_lt263()
    public_page.wait_for_timeout(2000)
    _submit_lt263_form(public_page, person, lien_amount=lien_amount, sale_days_out=sale_days_out)

    staff_dashboard.navigate_to_lt263_listing()
    lt263_listing = Lt263ListingPage(staff_page)
    lt263_listing.click_to_process_tab()
    for attempt in range(4):
        lt263_listing.search_by_vin(vin)
        staff_page.wait_for_timeout(2000)
        if lt263_listing.application_rows.count() > 0:
            return
        if attempt == 3:
            raise AssertionError(
                f"LT-263 resubmission for VIN {vin} did not appear on the staff LT-263 "
                f"'To Process' tab after 4 attempts, despite the public-portal success toast."
            )
        print(f"  WARN: VIN {vin} not yet on LT-263 To Process tab after resubmit (attempt {attempt + 1}/4) — reloading")
        staff_page.reload(timeout=30_000)
        staff_page.wait_for_load_state("networkidle")
        lt263_listing.click_to_process_tab()
