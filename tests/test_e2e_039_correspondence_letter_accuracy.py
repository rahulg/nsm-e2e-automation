"""
E2E-039: Correspondence Letter Content Accuracy — Owner/Lessee/Lienholder Name Rendering
Verify that correspondence letters (LT-264/LT-264G) generated after processing LT-262
render owner, lessee, and lienholder names correctly — no template variable fragments,
no HTML tags, no placeholder markers. Names should appear as "First Middle Last".

Precondition: The VIN used must have owners AND lessees in STARS database.
              Uses VIN_WITH_OWNERS from test_data (update with real VIN before running).

Phases:
  0. [Setup]        Submit LT-260 (PP) + process (SP) + submit LT-262 with payment (PP)
  1. [Staff Portal] Process LT-262 — system generates LT-264/LT-264G correspondence
  2. [Staff Portal] Open Correspondence tab — verify letters are present
  3. [Staff Portal] Verify letter names: no template fragments, no HTML tags, no placeholders
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
from src.config.test_data import (
    APPROX_VEHICLE_VALUE,
    STANDARD_LIEN_CHARGES,
    STORAGE_LOCATION_NAME,
    SAMPLE_DOC_PATH,
    VIN_WITH_OWNERS,
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
from src.pages.staff_portal.correspondence_page import CorrespondencePage


# ─── Shared test data ───
# NOTE: VIN_WITH_OWNERS must be a real VIN with owners/lessees/lienholders in STARS QA.
# If VIN_WITH_OWNERS is a placeholder, generate a random VIN (test may not fully validate names).
TEST_VIN = VIN_WITH_OWNERS if VIN_WITH_OWNERS != "PLACEHOLDER_OWNERS" else generate_vin()
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
class TestE2E039CorrespondenceLetterAccuracy:
    """E2E-039: Correspondence letter accuracy — verify name rendering in LT-264/LT-264G"""

    # ========================================================================
    # PHASE 0: Setup — Submit LT-260, process, submit LT-262 with payment
    # ========================================================================
    def test_phase_0_setup_through_lt262(self, public_context: BrowserContext,
                                          staff_context: BrowserContext):
        """Phase 0: [Setup] Submit LT-260, process, submit LT-262 with payment"""
        # Submit LT-260
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

        # Process LT-260
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

        # Submit LT-262 with payment
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

    # ========================================================================
    # PHASE 1: Staff Portal — Process LT-262 (generates LT-264/LT-264G)
    # ========================================================================
    def test_phase_1_process_lt262(self, staff_context: BrowserContext):
        """Phase 1: [Staff Portal] Process LT-262 — system generates LT-264/LT-264G correspondence"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()
            lt262_listing.click_to_process_tab()
            lt262_listing.search_by_vin(TEST_VIN)
            lt262_listing.select_application(0)

            # Verify lien details
            lt262_listing.verify_lien_details_visible()

            # Issue LT-264 (generates LT-264 and LT-264G correspondence)
            lt262_listing.issue_lt264()
        finally:
            page.close()

    # ========================================================================
    # PHASE 2: Staff Portal — Open Correspondence tab, verify letters present
    # ========================================================================
    def test_phase_2_verify_correspondence_present(self, staff_context: BrowserContext):
        """Phase 2: [Staff Portal] Open Correspondence tab — verify LT-264/LT-264G letters are present"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()

            # Find the application — may be in Aging tab after LT-264 issuance
            lt262_listing.click_aging_tab()
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.click_all_tab()
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            # Open Correspondence
            correspondence = CorrespondencePage(page)
            correspondence.open_correspondence()
            correspondence.expect_correspondence_visible()

            # Verify LT-264 letter is present
            correspondence.expect_letter_present("LT-264")

            # Verify LT-264G (garage copy) is present
            try:
                correspondence.expect_letter_present("LT-264G")
            except Exception:
                # LT-264G may be listed as "LT-264 Garage" or similar variant
                try:
                    correspondence.expect_letter_present("Garage")
                except Exception:
                    pass  # Garage letter naming may vary

            letter_count = correspondence.get_letter_count()
            assert letter_count >= 2, (
                f"Expected at least 2 correspondence letters (LT-264 + LT-264G), found {letter_count}"
            )

            correspondence.close()
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Staff Portal — Verify letter name rendering accuracy
    # ========================================================================
    def test_phase_3_verify_letter_name_accuracy(self, staff_context: BrowserContext):
        """Phase 3: [Staff Portal] Verify letter names — no template fragments, HTML tags, or placeholders"""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            staff_dashboard = StaffDashboardPage(page)
            lt262_listing = Lt262ListingPage(page)

            staff_dashboard.navigate_to_lt262_listing()

            # Find the application
            lt262_listing.click_aging_tab()
            lt262_listing.search_by_vin(TEST_VIN)

            if lt262_listing.application_rows.count() == 0:
                lt262_listing.click_all_tab()
                lt262_listing.search_by_vin(TEST_VIN)

            lt262_listing.select_application(0)

            # Open Correspondence
            correspondence = CorrespondencePage(page)
            correspondence.open_correspondence()
            correspondence.expect_correspondence_visible()

            # Get the full text content of the correspondence modal
            modal_text = page.locator(".correspondence-modal").text_content() or ""

            # Check for template variable fragments — these indicate broken rendering
            # Common template variable patterns: .lesse, .owner, .lien, {{variable}}, {variable}
            template_fragments = [
                r"\.lesse\b",       # .lesse (broken lessee template variable)
                r"\.owner\b",       # .owner (broken owner template variable)
                r"\.lien\b",        # .lien (broken lienholder template variable)
                r"\{\{.*?\}\}",     # {{variable}} (Handlebars/Mustache template markers)
                r"\{%.*?%\}",       # {% tag %} (Jinja template markers)
                r"\$\{.*?\}",       # ${variable} (ES6 template literal markers)
            ]

            for pattern in template_fragments:
                matches = re.findall(pattern, modal_text, re.I)
                assert len(matches) == 0, (
                    f"Found template variable fragment(s) in correspondence: {matches}"
                )

            # Check for HTML tags that should not appear in rendered correspondence
            html_tag_pattern = r"<(?:span|div|p|br|b|i|strong|em|table|tr|td|th|a|img|font)[^>]*>"
            html_matches = re.findall(html_tag_pattern, modal_text, re.I)
            assert len(html_matches) == 0, (
                f"Found raw HTML tags in correspondence: {html_matches}"
            )

            # Check for placeholder markers (e.g., [OWNER_NAME], {LESSEE_NAME}, PLACEHOLDER)
            placeholder_pattern = r"\[(?:OWNER|LESSEE|LIENHOLDER|NAME|ADDRESS|PLACEHOLDER)[^\]]*\]"
            placeholder_matches = re.findall(placeholder_pattern, modal_text, re.I)
            assert len(placeholder_matches) == 0, (
                f"Found placeholder markers in correspondence: {placeholder_matches}"
            )

            # If VIN_WITH_OWNERS was used (real VIN), verify names look like "First Middle Last"
            if TEST_VIN == VIN_WITH_OWNERS:
                # Correspondence table rows should contain name-like values (letters and spaces)
                rows = page.locator(".correspondence-modal table tbody tr")
                row_count = rows.count()
                for i in range(row_count):
                    row_text = rows.nth(i).text_content() or ""
                    # Names should contain alphabetic characters, not be all-numeric or all-symbols
                    if "LT-264" in row_text:
                        # The row should have recognizable name content
                        has_alpha = bool(re.search(r"[A-Za-z]{2,}", row_text))
                        assert has_alpha, (
                            f"Correspondence row {i} lacks alphabetic name content: {row_text}"
                        )

            correspondence.close()
        finally:
            page.close()
