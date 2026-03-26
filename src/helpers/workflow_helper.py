"""
Composite cross-portal workflow helpers.

Each function encapsulates a multi-step workflow that is reused across E2E tests.
Functions accept a page (already navigated to the correct portal dashboard) and
return any data needed by subsequent steps.
"""

import re
from datetime import datetime
from playwright.sync_api import Page, expect

from src.config.env import ENV
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    generate_person,
    past_date,
    today_date,
    future_date,
)
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
    STANDARD_SALE_DATA,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
    SAMPLE_DOC_PATH,
    REJECTION_REASONS,
    CLOSE_FILE_REMARKS,
    MAILED_PAYMENT,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.public_portal.lt263_form_page import Lt263FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.lt263_listing_page import Lt263ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── URL helpers ───

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page: Page):
    """Navigate to Public Portal dashboard. Re-navigates if session redirects to sign-in."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    try:
        page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    except Exception:
        # Session may have expired — try navigating again
        page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page: Page):
    """Navigate to Staff Portal dashboard. Re-navigates if session redirects to login."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")
    # If redirected to login page, try once more
    if "login" in page.url.lower() or "signin" in page.url.lower():
        page.goto(SP_DASHBOARD_URL, timeout=60_000)
        page.wait_for_load_state("networkidle")


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC PORTAL WORKFLOWS
# ═══════════════════════════════════════════════════════════════════════════════


def pp_submit_lt260(page: Page, vin: str, vehicle: dict, address: dict, person: dict):
    """Submit LT-260 on Public Portal. Page should already be on dashboard."""
    dashboard = PublicDashboardPage(page)
    dashboard.select_business()
    dashboard.click_start_here()

    lt260 = Lt260FormPage(page)
    lt260.enter_vin(vin)
    lt260.click_vin_lookup()
    lt260.fill_vehicle_details(vehicle)
    lt260.fill_date_vehicle_left(past_date(30))
    lt260.fill_license_plate(generate_license_plate())
    lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
    lt260.select_reason_storage()
    lt260.fill_storage_location(STORAGE_LOCATION_NAME, address["street"], address["zip"])
    lt260.fill_authorized_person(person["name"], address["street"], address["zip"])
    lt260.accept_terms_and_sign(person["name"], person["email"])
    lt260.submit()
    page.wait_for_timeout(2000)


def pp_submit_lt262_drawdown(page: Page, person: dict, address: dict, doc_path: str = None):
    """Submit LT-262 with Drawdown payment on Public Portal.
    Page should already be on an application detail showing Submit LT-262 button."""
    dashboard = PublicDashboardPage(page)
    dashboard.click_submit_lt262()

    lt262 = Lt262FormPage(page)
    lt262.expect_form_tabs_visible()
    lt262.fill_lien_charges(STANDARD_LIEN_CHARGES)
    lt262.fill_date_of_storage(past_date(30))
    lt262.fill_person_authorizing(person["name"], address["street"], address["zip"])
    lt262.fill_additional_details(person["name"], address["street"], address["zip"])
    lt262.upload_documents([doc_path or SAMPLE_DOC_PATH])
    lt262.accept_terms_and_sign(person["name"])
    lt262.finish_and_pay()
    page.wait_for_timeout(2000)


def pp_submit_lt262_payit(page: Page, person: dict, address: dict, card_data: dict = None, doc_path: str = None):
    """Submit LT-262 with PayIt payment on Public Portal.
    After finish_and_pay, the PayIt iframe loads for card entry.
    card_data should have: number, expiry, cvv, zip."""
    from src.config.test_data import PAYIT_TEST_CARD
    card = card_data or PAYIT_TEST_CARD

    dashboard = PublicDashboardPage(page)
    dashboard.click_submit_lt262()

    lt262 = Lt262FormPage(page)
    lt262.expect_form_tabs_visible()
    lt262.fill_lien_charges(STANDARD_LIEN_CHARGES)
    lt262.fill_date_of_storage(past_date(30))
    lt262.fill_person_authorizing(person["name"], address["street"], address["zip"])
    lt262.fill_additional_details(person["name"], address["street"], address["zip"])
    lt262.upload_documents([doc_path or SAMPLE_DOC_PATH])
    lt262.accept_terms_and_sign(person["name"])
    lt262.finish_and_pay()
    page.wait_for_timeout(3000)

    # PayIt payment flow — handle the PayIt payment screen
    # Select PayIt if a method selector is present
    try:
        payit_option = page.locator('button:has-text("PayIt"), label:has-text("PayIt"), [class*="payit"]').first
        payit_option.wait_for(state="visible", timeout=5_000)
        payit_option.click()
        page.wait_for_timeout(1000)
    except Exception:
        pass  # PayIt may already be the default or only option

    # Fill card details (may be in iframe)
    try:
        card_input = page.locator('input[name*="card" i], input[placeholder*="card" i]').first
        card_input.wait_for(state="visible", timeout=10_000)
        card_input.fill(card["number"])
        page.locator('input[name*="expir" i], input[placeholder*="expir" i]').first.fill(card["expiry"])
        page.locator('input[name*="cvv" i], input[name*="cvc" i]').first.fill(card["cvv"])

        # Submit payment
        pay_button = page.locator('button:has-text("Pay"), button[type="submit"]').first
        pay_button.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)
    except Exception:
        pass  # PayIt flow may vary; test should verify payment confirmation


def pp_submit_lt263(page: Page, person: dict, sale_type: str = "public"):
    """Submit LT-263 on Public Portal. Page should be on application detail."""
    dashboard = PublicDashboardPage(page)
    dashboard.click_submit_lt263()

    lt263 = Lt263FormPage(page)
    if sale_type == "public":
        lt263.select_public_sale()
    else:
        lt263.select_private_sale()

    lt263.fill_sale_date(future_date(30))
    lt263.fill_lien_amount(STANDARD_SALE_DATA["lien_amount"])
    lt263.fill_cost_breakdown(
        STANDARD_SALE_DATA["labor_cost"],
        STANDARD_SALE_DATA["storage_cost"],
    )
    lt263.accept_terms_and_sign(person["name"], person["email"])
    lt263.submit()
    page.wait_for_timeout(2000)


# ═══════════════════════════════════════════════════════════════════════════════
# STAFF PORTAL WORKFLOWS
# ═══════════════════════════════════════════════════════════════════════════════


def sp_process_lt260(page: Page, vin: str):
    """Process LT-260 on Staff Portal — navigate, search, open, verify."""
    staff_dashboard = StaffDashboardPage(page)
    lt260_listing = Lt260ListingPage(page)
    form_processing = FormProcessingPage(page)

    staff_dashboard.navigate_to_lt260_listing()
    lt260_listing.click_to_process_tab()
    lt260_listing.search_by_vin(vin)
    lt260_listing.select_application(0)
    form_processing.expect_detail_page_visible()


def sp_reject_lt260(page: Page, vin: str, reasons: list = None):
    """Reject LT-260 on Staff Portal with rejection reasons."""
    reasons = reasons or REJECTION_REASONS
    sp_process_lt260(page, vin)

    lt260_listing = Lt260ListingPage(page)
    lt260_listing.reject_button.click()
    page.wait_for_timeout(1000)

    # Fill rejection reason in the modal/dialog
    reason_input = page.locator('textarea, input[placeholder*="reason" i], input[placeholder*="remark" i]').first
    try:
        reason_input.wait_for(state="visible", timeout=5_000)
        reason_input.fill("; ".join(reasons))
    except Exception:
        pass

    # Confirm rejection
    confirm_btn = page.locator('button:has-text("Confirm"), button:has-text("Reject"), button:has-text("Submit")').last
    confirm_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def sp_mark_stolen(page: Page, vin: str):
    """Mark vehicle as stolen on Staff Portal (LT-260 detail page)."""
    sp_process_lt260(page, vin)

    stolen_btn = page.locator('button:has-text("Save as Stolen"), button:has-text("Mark Stolen")').first
    expect(stolen_btn).to_be_visible(timeout=10_000)
    stolen_btn.click()
    page.wait_for_timeout(1000)

    # Confirm if dialog appears
    try:
        confirm = page.locator('button:has-text("Confirm"), button:has-text("Yes")').first
        confirm.wait_for(state="visible", timeout=3_000)
        confirm.click()
    except Exception:
        pass

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def sp_download_for_cms(page: Page):
    """Click 'Download for CMS' button on stolen vehicle detail page."""
    cms_btn = page.locator('button:has-text("Download for CMS"), button:has-text("CMS")').first
    expect(cms_btn).to_be_visible(timeout=10_000)
    cms_btn.click()
    page.wait_for_timeout(2000)


def sp_process_lt262_issue_lt264(page: Page, vin: str):
    """Process LT-262 and issue LT-264 on Staff Portal."""
    staff_dashboard = StaffDashboardPage(page)
    lt262_listing = Lt262ListingPage(page)

    staff_dashboard.navigate_to_lt262_listing()
    lt262_listing.click_to_process_tab()
    lt262_listing.search_by_vin(vin)
    lt262_listing.select_application(0)
    lt262_listing.verify_lien_details_visible()
    lt262_listing.verify_owner_details_visible()
    lt262_listing.issue_lt264()


def sp_process_lt262_no_owners(page: Page, vin: str):
    """Process LT-262 for no-owners path — issues LT-262B instead of LT-264."""
    staff_dashboard = StaffDashboardPage(page)
    lt262_listing = Lt262ListingPage(page)

    staff_dashboard.navigate_to_lt262_listing()
    lt262_listing.click_to_process_tab()
    lt262_listing.search_by_vin(vin)
    lt262_listing.select_application(0)
    lt262_listing.verify_lien_details_visible()

    # For no-owners path, issue LT-262B
    issue_btn = page.locator('button:has-text("Issue LT-262B"), button:has-text("Issue")').first
    expect(issue_btn).to_be_visible(timeout=10_000)
    issue_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def sp_process_court_hearing(page: Page, vin: str, favorable: bool = True):
    """Process court hearing on Staff Portal LT-262 detail page.
    If favorable=True, selects 'Judgment in action of Possessory Lien' to unlock LT-263.
    If favorable=False, selects unfavorable judgment — LT-263 stays locked."""
    from src.config.test_data import COURT_HEARING_FAVORABLE

    staff_dashboard = StaffDashboardPage(page)
    lt262_listing = Lt262ListingPage(page)

    staff_dashboard.navigate_to_lt262_listing()

    # Find application in Court Hearing or Aging tab
    lt262_listing.court_hearing_tab.click()
    page.wait_for_load_state("networkidle")
    lt262_listing.search_by_vin(vin)

    if lt262_listing.application_rows.count() == 0:
        lt262_listing.click_aging_tab()
        lt262_listing.search_by_vin(vin)

    lt262_listing.select_application(0)
    lt262_listing.click_review_hearings_tab()
    page.wait_for_timeout(1000)

    if favorable:
        # Select "Judgment in action of Possessory Lien" checkbox
        possessory_checkbox = page.locator(
            f'mat-checkbox:has-text("{COURT_HEARING_FAVORABLE}"), '
            f'label:has-text("{COURT_HEARING_FAVORABLE}")'
        ).first
        try:
            possessory_checkbox.wait_for(state="visible", timeout=10_000)
            cls = possessory_checkbox.get_attribute("class") or ""
            if "mat-checkbox-checked" not in cls:
                possessory_checkbox.locator("label").click()
                page.wait_for_timeout(500)
        except Exception:
            possessory_checkbox.click()

        # Submit hearing decision
        submit_btn = page.locator('button:has-text("Submit"), button:has-text("Save"), button:has-text("Confirm")').first
        submit_btn.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
    else:
        # Unfavorable judgment
        unfavorable_option = page.locator(
            'mat-checkbox:has-text("Unfavorable"), label:has-text("Unfavorable"), '
            'input[value*="unfavorable" i]'
        ).first
        try:
            unfavorable_option.wait_for(state="visible", timeout=10_000)
            unfavorable_option.click()
        except Exception:
            pass

        submit_btn = page.locator('button:has-text("Submit"), button:has-text("Save"), button:has-text("Confirm")').first
        submit_btn.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)


def sp_process_lt263_generate_lt265(page: Page, vin: str = None):
    """Process LT-263 and generate LT-265 on Staff Portal."""
    staff_dashboard = StaffDashboardPage(page)
    lt263_listing = Lt263ListingPage(page)

    staff_dashboard.navigate_to_lt263_listing()
    lt263_listing.click_to_process_tab()

    if vin:
        lt263_listing.search_by_vin(vin)
    lt263_listing.expect_applications_visible()
    lt263_listing.select_application(0)
    lt263_listing.verify_sale_details_visible()
    lt263_listing.verify_lien_amount_visible()
    lt263_listing.generate_lt265()


def sp_close_file(page: Page, vin: str, remarks: str = None):
    """Close file on Staff Portal with remarks."""
    remarks = remarks or CLOSE_FILE_REMARKS

    # Find the close file button on the current detail page
    close_btn = page.locator('button:has-text("Close File")').first
    expect(close_btn).to_be_visible(timeout=10_000)
    close_btn.click()
    page.wait_for_timeout(1000)

    # Fill remarks
    remarks_input = page.locator('textarea, input[placeholder*="remark" i], input[placeholder*="reason" i]').first
    try:
        remarks_input.wait_for(state="visible", timeout=5_000)
        remarks_input.fill(remarks)
    except Exception:
        pass

    # Confirm
    confirm_btn = page.locator('button:has-text("Confirm"), button:has-text("Close"), button:has-text("Submit")').last
    confirm_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def sp_add_paper_lt260(page: Page, vin: str, vehicle: dict, address: dict, person: dict,
                       requester_type: str = "Individual"):
    """Add paper LT-260 on Staff Portal."""
    staff_dashboard = StaffDashboardPage(page)
    lt260_listing = Lt260ListingPage(page)

    staff_dashboard.navigate_to_lt260_listing()

    # Click "Add from Paper" button
    add_paper_btn = page.locator('button:has-text("Add from Paper"), button:has-text("Paper")').first
    expect(add_paper_btn).to_be_visible(timeout=10_000)
    add_paper_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Select requester type
    type_option = page.locator(f'mat-radio-button:has-text("{requester_type}"), label:has-text("{requester_type}")').first
    try:
        type_option.wait_for(state="visible", timeout=5_000)
        type_option.click()
        page.wait_for_timeout(500)
    except Exception:
        pass

    # Enter VIN and lookup
    vin_input = page.locator('input[name="sno"], input[placeholder*="VIN" i]').first
    vin_input.fill(vin)
    lookup_btn = page.locator('button:has-text("VIN Lookup"), button:has-text("Lookup"), button:has-text("Search")').first
    lookup_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Dismiss any overlays
    try:
        for dismiss in ['button:has-text("OK")', 'button:has-text("Close")', 'button:has-text("Got it")']:
            el = page.locator(dismiss).first
            el.wait_for(state="visible", timeout=2_000)
            el.click(force=True)
            page.wait_for_timeout(500)
    except Exception:
        pass

    # Fill vehicle details if not auto-populated
    try:
        make_input = page.locator('input[placeholder="Enter Make"]').first
        if not make_input.input_value():
            make_input.click()
            make_input.fill("")
            make_input.type(vehicle["make"], delay=100)
            autocomplete_option = page.locator('mat-option, .mat-autocomplete-panel .mat-option, [role="option"]').first
            autocomplete_option.wait_for(state="visible", timeout=5000)
            autocomplete_option.click()
            page.wait_for_timeout(500)
            page.locator('input[name="year"]').first.fill(vehicle["year"])
            page.locator('input[name="model"]').first.fill(vehicle["model"])
            page.locator('input[name="color"]').first.fill(vehicle["color"])
    except Exception:
        pass

    # Fill storage location
    try:
        location_input = page.locator('input[aria-label*="Location" i]').first
        location_input.fill(STORAGE_LOCATION_NAME)
        page.locator('input[aria-label*="Address" i]').first.fill(address["street"])
        page.locator('input[aria-label*="Zip" i]').first.fill(address["zip"])
    except Exception:
        pass

    # Submit
    submit_btn = page.locator('button:has-text("Submit"), button:has-text("Save")').first
    submit_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def sp_record_mailed_payment(page: Page, payment_data: dict = None):
    """Record a mailed payment (check/money order) on Staff Portal Payments section."""
    payment = payment_data or MAILED_PAYMENT

    staff_dashboard = StaffDashboardPage(page)
    staff_dashboard._wait_for_sidebar()
    staff_dashboard.payments_nav_link.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Click "Record Mailed Payment"
    record_btn = page.locator('button:has-text("Record Mailed Payment"), button:has-text("Record Payment")').first
    expect(record_btn).to_be_visible(timeout=10_000)
    record_btn.click()
    page.wait_for_timeout(1000)

    # Fill payment details
    try:
        check_input = page.locator('input[placeholder*="check" i], input[name*="check" i]').first
        check_input.fill(payment.get("check_number", "12345"))
    except Exception:
        pass

    try:
        amount_input = page.locator('input[placeholder*="amount" i], input[name*="amount" i]').first
        amount_input.fill(payment.get("amount", "16.75"))
    except Exception:
        pass

    # Save payment
    save_btn = page.locator('button:has-text("Save"), button:has-text("Record"), button:has-text("Submit")').first
    save_btn.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)


def sp_global_search(page: Page, search_term: str):
    """Perform global search on Staff Portal."""
    search_input = page.locator('input[placeholder*="Global Search" i], input[placeholder*="Search" i]').first
    expect(search_input).to_be_visible(timeout=10_000)
    search_input.fill(search_term)
    search_input.press("Enter")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
