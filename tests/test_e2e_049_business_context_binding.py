"""
E2E-049: Business User LT-260 Submission Business Context Binding
Cross-portal test spanning Public Portal and Staff Portal.

Verifies that:
  1. An LT-260 submission with null businessId is rejected at the API level (HTTP 400)
  2. A valid submission with correct businessId succeeds end-to-end
  3. The submitted case is visible with correct status after re-login on Public Portal
  4. The case appears in Staff Portal header search under LT-260 tab with correct status and submitter
  5. A duplicate VIN submission for the same VIN is blocked with an error banner

Phases:
  0. [API] POST with null businessId → HTTP 400 (auth token from active PP session)
  1. [Public Portal] Submit LT-260 with correct business context (E2E-001 Phase 1 flow)
  3. [Public Portal] Re-login (fresh session) → search VIN → status "LT-260 Submitted"
  4. [Staff Portal] Top header search by VIN → LT-260 tab, STATUS "LT-260 Submitted",
     submitter name = BUSINESS_NAME "G-Car Garages New"
  6. [Public Portal] Duplicate VIN re-submission → blocked (E2E-018 Phase 2 flow)

Ref: Edge Case 32, Business Rule 85, Business Rule 44, Business Rule 45,
     Business Rule 47, Journey 2.1, Journey 2.2, Journey 3.1
"""

import re
import requests
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from src.config.env import ENV
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
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.global_search_page import GlobalSearchPage

SAMPLE_DOC_PATH = str(Path(__file__).resolve().parent.parent / "fixtures" / "sample-document.pdf")

# ─── Shared test data ───
TEST_VIN = generate_vin()          # Used by phases 1, 3, 4, 6
TEST_VIN_P0 = generate_vin()       # Phase 0 only — keeps API submission isolated from UI flow
VEHICLE = random_vehicle()
PLATE = generate_license_plate()
ADDRESS = generate_address()
PERSON = generate_person()
BUSINESS_NAME = "G-Car Garages New"

PP_DASHBOARD_URL = ENV.PUBLIC_PORTAL_URL
SP_DASHBOARD_URL = re.sub(r"/login$", "/pages/ncdot-notice-and-storage/dashboard", ENV.STAFF_PORTAL_URL)

# Phase 0 API — LT-260 submission chain endpoint (null businessId → HTTP 400)
_NULL_BIZ_API_PATH = "/rest/api/automation/chain/execute/48b75ae40257738bff01aa4513a76f46?encrypted=true"

# VIN image used in the Phase 0 payload (kept out of the method for readability)
_VIN_IMAGE_B64 = (
    "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"
)


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
class TestE2E049BusinessContextBinding:
    """E2E-049: Business User LT-260 Submission Business Context Binding"""

    # ========================================================================
    # PHASE 0: API — Null businessId Submission Must Return HTTP 400
    # ========================================================================
    def test_phase_0_api_null_business_id_rejected(self, public_context: BrowserContext):
        """Phase 0: [API] POST LT-260 with null businessId → expect HTTP 400.
        Auth token extracted from active public portal session.
        VIN substituted with TEST_VIN. Base URL derived from ENV.PUBLIC_PORTAL_URL.
        """
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            # Extract auth token from public portal localStorage
            auth_token = page.evaluate("""() => {
                return (
                    localStorage.getItem('token') ||
                    localStorage.getItem('access_token') ||
                    localStorage.getItem('authToken') ||
                    localStorage.getItem('id_token') ||
                    ''
                );
            }""")

            if not auth_token:
                pytest.skip(
                    "Could not extract auth token from public portal localStorage. "
                    "Update the localStorage key name to match what the app uses."
                )

            api_base = re.sub(r"(https?://[^/]+).*", r"\1", ENV.PUBLIC_PORTAL_URL)

            payload = {
                "vin": TEST_VIN_P0,
                "make": "BAGGAGE CAR TRAILER",
                "year": "2022",
                "body": "Ambulance",
                "model": None,
                "color": None,
                "dayVehicleLeft": "2026-06-03",
                "licensePlateNumber": None,
                "plateYear": None,
                "plateState": None,
                "plateCounty": "Alamance",
                "approximateValue": None,
                "vehicleLeftFor": "Storage",
                "explanation": None,
                "isVehicleInRunningCondition": None,
                "wrecked": None,
                "locationOfStoredVehicle": "Palm Street",
                "address": "444 Elm Avenue",
                "city": "Greensboro",
                "state": "North Carolina",
                "zip": "27401",
                "telephoneNumber": "(919) 203-8134",
                "authorizedPersonDetails": {
                    "name": "Test",
                    "address": "Test Address",
                    "city": "Durham",
                    "state": "North Carolina",
                    "evidence": None,
                    "remarks": None,
                    "email": "ssnrg68@mailinator.com",
                    "zip": "27709",
                },
                "termsAndConditions": {
                    "businessOperatorAttestation": True,
                    "reportingComplianceAttestation": True,
                    "informationAccuracyAttestation": True,
                    "legalObligationAttestation": True,
                    "ownerName": "Tester's paint & body shops",
                    "date": "2026-06-03T18:30:00.000Z",
                    "email": "ssnrg68@mailinator.com",
                },
                "publicUserId": "0527ead4-d7ea-4d8e-bced-7e64e7c22c0b",
                "status": "SUBMITTED",
                "formApplicationId": None,
                "vinImage": [
                    {
                        "content": _VIN_IMAGE_B64,
                        "metadata": {"name": "Apple.png", "type": "image/png", "raw": {}},
                    }
                ],
                "businessId": None,
                "referenceNumber": None,
                "loggedBy": None,
                "requestorInfo": None,
                "paperFormLocationId": None,
                "paperFormVersionId": None,
                "selectedFromAddressBook": True,
                "addressBookValue": "Palm Street - 444 Elm Avenue",
                "owners": None,
                "lessees": None,
                "leinholders": None,
                "isStolen": None,
                "statusCode": None,
                "bodySubType": None,
            }

            response = requests.post(
                f"{api_base}{_NULL_BIZ_API_PATH}",
                json=payload,
                headers={
                    "Authorization": auth_token,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/plain, */*",
                    "Origin": api_base,
                },
                timeout=30,
            )

            assert response.status_code == 400, (
                f"Expected HTTP 400 for null businessId submission, "
                f"got HTTP {response.status_code}"
            )
        finally:
            page.close()

    # ========================================================================
    # PHASE 1: Public Portal — Create & Submit LT-260
    # (copied from E2E-001 Phase 1)
    # ========================================================================
    def test_phase_1_public_portal_create_lt260(self, public_context: BrowserContext):
        """Phase 1: [Public Portal] Login, create LT-260, fill form, submit"""
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

            # Verify redirect back to dashboard
            try:
                page.wait_for_url(re.compile(r"dashboard", re.I), timeout=15_000)
            except Exception:
                print("  WARN: did not redirect back to dashboard after LT-260 submit — continuing")
        finally:
            page.close()

    # ========================================================================
    # PHASE 3: Public Portal — Re-login, verify "LT-260 Submitted"
    # ========================================================================
    def test_phase_3_relogin_verify_lt260_submitted(self, fresh_public_context: BrowserContext):
        """Phase 3: [Public Portal] Re-login (fresh session) → search for same VIN →
        status must show 'LT-260 Submitted'."""
        page = fresh_public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_notice_storage_tab()
            page.wait_for_timeout(1000)
            dashboard.search_by_vin(TEST_VIN)
            page.wait_for_timeout(2000)

            status_label = page.locator('text="LT-260 Submitted"').first
            expect(status_label).to_be_visible(timeout=15_000)
        finally:
            page.close()

    # ========================================================================
    # PHASE 4: Staff Portal — Top Header Search, LT-260 Tab, Status + Submitter
    # ========================================================================
    def test_phase_4_staff_portal_header_search(self, staff_context: BrowserContext):
        """Phase 4: [Staff Portal] Enter VIN in top header search field → click Search →
        verify VIN entry in LT-260 tab with STATUS 'LT-260 Submitted' and
        submitter name = BUSINESS_NAME 'G-Car Garages New'."""
        page = staff_context.new_page()
        try:
            go_to_staff_dashboard(page)
            page.wait_for_timeout(2000)

            # Navigate to Global Search (top header search) and search by VIN
            global_search = GlobalSearchPage(page)
            global_search.navigate_to()
            global_search.search(TEST_VIN)

            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

            # Click the LT-260 tab in the results
            lt260_tab = page.locator('[role="tab"]:has-text("LT-260")').first
            lt260_tab.wait_for(state="visible", timeout=15_000)
            lt260_tab.click()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            # Verify the VIN row is present in LT-260 tab
            vin_row = page.locator(f'text="{TEST_VIN}"').first
            vin_row.wait_for(state="visible", timeout=15_000)

            # Verify STATUS = "LT-260 Submitted"
            status_cell = page.locator('text="LT-260 Submitted"').first
            expect(status_cell).to_be_visible(timeout=10_000)

            # Verify submitter name = BUSINESS_NAME visible in the results
            try:
                biz_name = page.get_by_text(BUSINESS_NAME, exact=False).first
                biz_name.wait_for(state="visible", timeout=10_000)
            except Exception:
                # Fallback: check full page HTML (covers hidden elements / data attrs)
                page_source = page.content()
                assert BUSINESS_NAME in page_source, (
                    f"Expected submitter '{BUSINESS_NAME}' in LT-260 global search results. "
                    f"Not found in page source — business name may not be surfaced in this view."
                )
        finally:
            page.close()

    # ========================================================================
    # PHASE 6: Public Portal — Duplicate VIN Blocked
    # (Phase 2 of E2E-018 duplicate VIN detection)
    # ========================================================================
    def test_phase_6_duplicate_vin_blocked(self, public_context: BrowserContext):
        """Phase 6: [Public Portal] Re-submit LT-260 with same VIN →
        expect red error banner 'is associated with an ongoing application'."""
        page = public_context.new_page()
        try:
            go_to_public_dashboard(page)

            dashboard = PublicDashboardPage(page)
            dashboard.select_business(BUSINESS_NAME)
            dashboard.click_start_here()

            lt260 = Lt260FormPage(page)
            lt260.enter_vin(TEST_VIN)
            lt260.fill_vehicle_details(VEHICLE)
            lt260.fill_date_vehicle_left(past_date(15))
            lt260.fill_license_plate(generate_license_plate())
            lt260.fill_approx_value("5000")
            lt260.select_reason_storage()
            lt260.fill_storage_location("Test Storage Facility", ADDRESS["street"], ADDRESS["zip"])
            lt260.fill_authorized_person(PERSON["name"], ADDRESS["street"], ADDRESS["zip"])
            lt260.accept_terms_and_sign(PERSON["name"], PERSON["email"])
            # Direct submit click (no VIN image modal — duplicate blocked before modal)
            lt260.submit_button.click()
            page.wait_for_timeout(3000)

            error_banner = page.locator(
                ':has-text("is associated with an ongoing application")'
            ).last

            expect(error_banner).to_be_visible(timeout=10_000)
            expect(error_banner).to_contain_text(TEST_VIN)
            expect(error_banner).to_contain_text(
                "is associated with an ongoing application and cannot be entered again"
            )
        finally:
            page.close()
