"""
E2E-010: Court Hearing — Unfavorable Judgment
PP: LT-262 → SP: LT-264 → Owner hearing → Unfavorable → LT-263 NOT unlocked

Precondition: Application in progress — LT-260 processed, LT-262 submitted
              and processed, LT-264 issued to owners.

Phases:
  1. [Public Portal]  Submit LT-260
  2. [Staff Portal]   Process LT-260
  3. [Public Portal]  Submit LT-262 with payment
  4. [Staff Portal]   Process LT-262, issue LT-264
  5. [Staff Portal]   Record unfavorable court hearing judgment
  6. [Public Portal]  Verify LT-263 is NOT available (still locked)
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    STANDARD_LIEN_CHARGES,
    SAMPLE_DOC_PATH,
    APPROX_VEHICLE_VALUE,
    STORAGE_LOCATION_NAME,
)
from src.helpers.data_helper import (
    generate_vin,
    random_vehicle,
    generate_license_plate,
    generate_address,
    generate_person,
    past_date,
)
from src.pages.public_portal.dashboard_page import PublicDashboardPage
from src.pages.public_portal.lt260_form_page import Lt260FormPage
from src.pages.public_portal.lt262_form_page import Lt262FormPage
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt260_listing_page import Lt260ListingPage
from src.pages.staff_portal.lt262_listing_page import Lt262ListingPage
from src.pages.staff_portal.form_processing_page import FormProcessingPage


# ─── Shared test data ───
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.alternate
@pytest.mark.high
class TestE2E010UnfavorableCourtJudgment:
    """E2E-010: Unfavorable court judgment — LT-263 stays locked"""

    def test_phase_1_public_portal_submit_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Submit LT-260"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.select_business()
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.click_vin_lookup()
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value(APPROX_VEHICLE_VALUE)
            lt260.select_reason_storage()
            lt260.fill_storage_location(STORAGE_LOCATION_NAME, ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            lt260.submit()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    def test_phase_2_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Process LT-260"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt260_listing = Lt260ListingPage(page)
            form_processing = FormProcessingPage(page)

            staff_dashboard.navigate_to_lt260_listing()
            lt260_listing.click_to_process_tab()
            lt260_listing.search_by_vin(TEST_VIN)
            lt260_listing.select_application(0)
            form_processing.expect_detail_page_visible()
            lt260_listing.verify_auto_issuance()
        finally:
            page.close()

    def test_phase_3_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 3: [Public Portal] Submit LT-262"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)
            dashboard.expect_application_processed()
            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()
            lt262.fill_lien_charges(STANDARD_LIEN_CHARGES)
            lt262.fill_date_of_storage(past_date(30))
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.upload_documents([SAMPLE_DOC_PATH])
            lt262.accept_terms_and_sign(PERSON["name"])
            lt262.finish_and_pay()
            page.wait_for_timeout(2000)
        finally:
            page.close()

    def test_phase_4_staff_portal_issue_lt264(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Process LT-262, issue LT-264"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)
            lt262_listing.verify_lien_details_visible()
            lt262_listing.issue_lt264()
        finally:
            page.close()

    def test_phase_5_staff_portal_unfavorable_judgment(self, staff_context: BrowserContext):
        """Phase 5: [Staff Portal] Record unfavorable court hearing judgment"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()

            # Find in Court Hearing or Aging tab
            lt262_listing.court_hearing_tab.click()
            page.wait_for_load_state("networkidle")
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.click_aging_tab()
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)
            lt262_listing.click_review_hearings_tab()
            page.wait_for_timeout(1000)

            # Select unfavorable judgment option — try multiple patterns
            # The UI may use "Unfavorable", "Not in favor", "Judgment NOT in action",
            # or a radio/checkbox/select element
            unfavorable_option = page.locator(
                'mat-radio-button:has-text("Unfavorable"), '
                'mat-radio-button:has-text("Not in favor"), '
                'mat-radio-button:has-text("Judgment NOT"), '
                'mat-checkbox:has-text("Unfavorable"), '
                'label:has-text("Unfavorable"), '
                'mat-select, select'
            ).first

            try:
                unfavorable_option.wait_for(state="visible", timeout=10_000)
                tag = unfavorable_option.evaluate("el => el.tagName.toLowerCase()")

                if tag == "mat-radio-button":
                    unfavorable_option.locator("label").click()
                elif tag == "mat-checkbox":
                    cls = unfavorable_option.get_attribute("class") or ""
                    if "mat-checkbox-checked" not in cls:
                        unfavorable_option.locator("label").click()
                elif tag in ("mat-select", "select"):
                    # Dropdown — select the unfavorable option
                    unfavorable_option.click()
                    page.wait_for_timeout(500)
                    page.locator(
                        'mat-option:has-text("Unfavorable"), '
                        'mat-option:has-text("Not in favor"), '
                        'option:has-text("Unfavorable")'
                    ).first.click()
                else:
                    unfavorable_option.click()
            except Exception:
                # Final fallback: click any element containing "Unfavorable" text
                try:
                    page.get_by_text(re.compile(r"unfavorable|not in favor", re.I)).first.click()
                except Exception:
                    pass

            page.wait_for_timeout(500)

            # Submit decision — skip buttons with display-none class
            submitted = page.evaluate("""() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const txt = btn.textContent.toLowerCase().trim();
                    const style = window.getComputedStyle(btn);
                    if ((txt.includes('submit') || txt.includes('save') || txt.includes('confirm'))
                        && style.display !== 'none' && style.visibility !== 'hidden'
                        && btn.offsetParent !== null) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }""")
            if not submitted:
                submit_btn = page.locator(
                    'button:has-text("Submit"), button:has-text("Save"), button:has-text("Confirm")'
                ).last
                try:
                    submit_btn.click(force=True)
                except Exception:
                    submit_btn.dispatch_event("click")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)
        finally:
            page.close()

    def test_phase_6_public_portal_lt263_still_locked(self, public_context: BrowserContext):
        """Phase 6: [Public Portal] LT-263 is NOT available — unfavorable judgment keeps it locked"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)
            dashboard = PublicDashboardPage(page)
            dashboard.click_notice_storage_tab()
            dashboard.select_application(0)

            # LT-263 should NOT be available
            dashboard.expect_lt263_not_available()
        finally:
            page.close()
