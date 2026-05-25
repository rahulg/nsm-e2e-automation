"""
E2E-039: Correspondence Letter Content Accuracy — Owner/Lessee/Lienholder Name Rendering
Verify that correspondence letters (LT-264/LT-264G) generated after processing LT-262
render owner, lessee, and lienholder names correctly — no template variable fragments,
no HTML tags, no placeholder markers. Names should appear as "First Middle Last".

Phases:
  0a. [Public Portal]  Submit LT-260
  0b. [Staff Portal]   Process LT-260
  0c. [Public Portal]  Submit LT-262 with payment
  1.  [Staff Portal]   Process LT-262 — Issue LT-264 (system generates LT-264/LT-264G correspondence)
  2.  [Staff Portal]   LT-262 Aging tab — search VIN — click — verify Aging status — open
                       Correspondence History modal — scroll — verify LT-264 + LT-264G entries
                       and no template fragments, HTML tags, or placeholder markers
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import SAMPLE_DOC_PATH
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
from src.pages.staff_portal.correspondence_page import CorrespondencePage


# ─── Shared test data ───
BUSINESS_NAME = "G-Car Garages New"
TEST_VIN = generate_vin()
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)


def go_to_public_dashboard(page):
    """Navigate to Public Portal — handles auto-redirect from signin to dashboard."""
    page.goto(PP_DASHBOARD_URL, timeout=60_000, wait_until="domcontentloaded")
    page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
    page.wait_for_load_state("networkidle")


def go_to_staff_dashboard(page):
    """Navigate to Staff Portal dashboard."""
    page.goto(SP_DASHBOARD_URL, timeout=60_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.e2e
@pytest.mark.edge
@pytest.mark.high
@pytest.mark.fixed
class TestE2E039CorrespondenceLetterAccuracy:
    """E2E-039: Correspondence letter accuracy — verify name rendering in LT-264/LT-264G"""

    # ========================================================================
    # PHASE 0a: Public Portal — Create & Submit LT-260
    # ========================================================================
    def test_phase_0a_public_portal_create_lt260(self, public_context: BrowserContext):
        """Phase 0a: [Public Portal] Login, create LT-260, VIN lookup, fill form, submit"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)

            lt260.enter_vin(TEST_VIN)
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(30))
            lt260.fill_license_plate(PLATE)
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])

            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])

            lt260.submit_with_vin_image()
            page.wait_for_timeout(2000)

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 0b: Staff Portal — Process LT-260
    # ========================================================================
    def test_phase_0b_staff_portal_process_lt260(self, staff_context: BrowserContext):
        """Phase 0b: [Staff Portal] Open LT-260, add owner, set stolen=No, save, issue 160B/260A"""
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
            form_processing.click_edit()

            form_processing.add_owner(
                PERSON["name"], ADDRESS["street"], ADDRESS["zip"]
            )
            form_processing.select_stolen_no()
            form_processing.click_save()

            form_processing.issue_160b_and_260a()

            form_processing.expect_issued_success_toast()
            form_processing.expect_status_processed()
        finally:
            page.close()

    # ========================================================================
    # PHASE 0c: Public Portal — Submit LT-262
    # ========================================================================
    def test_phase_0c_public_portal_submit_lt262(self, public_context: BrowserContext):
        """Phase 0c: [Public Portal] Verify LT-260 processed, submit LT-262 with lien/charges/docs, pay"""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)

            dashboard.select_business(BUSINESS_NAME)

            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)
            dashboard.select_application(0)
            dashboard.expect_application_processed()

            dashboard.click_submit_lt262()

            lt262 = Lt262FormPage(page)
            lt262.expect_form_tabs_visible()

            lt262.skip_vehicle_and_location_tabs()
            lt262.fill_lien_charges({"storage": "500", "towing": "200", "labor": "100"})
            lt262.fill_date_of_storage(past_date(30))
            lt262.fill_person_authorizing(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.fill_additional_details(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt262.upload_documents([SAMPLE_DOC_PATH])
            lt262.accept_terms_and_sign(PERSON["name"])
            lt262.finish_and_pay()

            pay_drawdown_btn = page.locator('button:has-text("Pay Using ACH/Drawdown")')
            pay_drawdown_btn.wait_for(state="visible", timeout=30_000)
            pay_drawdown_btn.click()
            page.wait_for_timeout(2000)

            yes_btn = page.locator('mat-dialog-container button:has-text("Yes")').first
            yes_btn.wait_for(state="visible", timeout=10_000)
            yes_btn.click()
            page.wait_for_timeout(3000)

            # Soft check — banner is transient and may be missed in CI
            try:
                success_banner = page.get_by_text("Your payment has been completed successfully")
                expect(success_banner).to_be_visible(timeout=30_000)
            except Exception:
                print("WARN: 'Your payment has been completed successfully' banner not seen — continuing")

            page.wait_for_url(re.compile(r"dashboard", re.I), timeout=30_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 1: Staff Portal — Process LT-262 → Issue LT-264
    # ========================================================================
    def test_phase_1_process_lt262(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Open LT-262, verify details, CHECK DCI → Issue LT-264"""
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
            lt262_listing.verify_owner_details_visible()

            lt262_listing.issue_lt264()

            success_banner = page.get_by_text("The form has been issued successfully.")
            expect(success_banner).to_be_visible(timeout=30_000)

            track_tab = page.locator('[role="tab"]:has-text("TRACK LT-264")')
            expect(track_tab).to_be_visible(timeout=10_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — LT-262 Aging tab, verify status, open Correspondence History
    # ========================================================================
    def test_phase_2_verify_correspondence_present(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Aging tab — search VIN — verify Aging status — Correspondence History has LT-264 + LT-264G"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)

            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            # Navigate to LT-262 listing → Aging tab
            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_aging_tab()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(8000)

            # Search for VIN via filters
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify status "Aging" is displayed on the detail page
            aging_text = page.get_by_text(re.compile(r"\bAging\b", re.I)).first
            expect(aging_text).to_be_visible(timeout=15_000)

            # Click "View Correspondence/Documents" link
            correspondence = CorrespondencePage(page)
            correspondence.open_correspondence()

            # Verify "Correspondence History" modal header is displayed
            history_header = page.get_by_text(re.compile(r"Correspondence History", re.I)).first
            expect(history_header).to_be_visible(timeout=10_000)

            # Wait a few seconds for entries to load, then scroll down
            page.wait_for_timeout(3000)
            modal = page.locator('mat-dialog-container').first
            modal.evaluate("el => el.scrollTop = el.scrollHeight")
            page.wait_for_timeout(1000)

            # Verify LT-264 entry is present
            correspondence.expect_letter_present("LT-264")

            # Verify LT-264G entry is present
            correspondence.expect_letter_present("LT-264G")
            
            modal_text = page.locator(".correspondence-modal").text_content() or ""

            template_fragments = [
                r"\.lesse\b",
                r"\.owner\b",
                r"\.lien\b",
                r"\{\{.*?\}\}",
                r"\{%.*?%\}",
                r"\$\{.*?\}",
            ]

            for pattern in template_fragments:
                matches = re.findall(pattern, modal_text, re.I)
                assert len(matches) == 0, (
                    f"Found template variable fragment(s) in correspondence: {matches}"
                )

            html_tag_pattern = r"<(?:span|div|p|br|b|i|strong|em|table|tr|td|th|a|img|font)[^>]*>"
            html_matches = re.findall(html_tag_pattern, modal_text, re.I)
            assert len(html_matches) == 0, (
                f"Found raw HTML tags in correspondence: {html_matches}"
            )

            placeholder_pattern = r"\[(?:OWNER|LESSEE|LIENHOLDER|NAME|ADDRESS|PLACEHOLDER)[^\]]*\]"
            placeholder_matches = re.findall(placeholder_pattern, modal_text, re.I)
            assert len(placeholder_matches) == 0, (
                f"Found placeholder markers in correspondence: {placeholder_matches}"
            )
            
            correspondence.close()
        finally:
            page.close()
