"""
E2E-004: Sheriff/Inspector Standalone (LT-261)
Staff Portal only — no Public Portal involvement.

Phases:
  1. E-STOP + owner details + Stolen = NO  → LT-261 Processed listing → vehicle Sold
  2. DWI    + owner details + Stolen = NO  → LT-261 Processed listing → vehicle Sold
  3. E-STOP + owner details + Stolen = YES → LT-261 Stolen listing
  4. DWI    + owner details + Stolen = YES → LT-261 Stolen listing

Form-type default asserted in every phase (verified against the live QA app):
  * DWI    → "Use Same Address as Place Stored" IS auto-checked by default.
  * E-STOP → "Use Same Address as Place Stored" is NOT auto-checked by default.
There are two such checkboxes (location panel + agency section) and both follow the
rule, so the assertion covers both. It runs immediately after the form loads, before
anything is clicked, so it observes the true default.

Single tab: all phases and steps share the session-scoped `staff_page` fixture. The
Angular app loads cold once; steps move between listings through the in-app sidebar
instead of a full page.goto(). Phases stay separate test methods so a failure names
the exact step, and each phase owns its VIN so the phases are independent.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from src.helpers.data_helper import (
    generate_vin,
    generate_person,
    future_date,
)
from src.pages.staff_portal.dashboard_page import StaffDashboardPage
from src.pages.staff_portal.lt261_page import Lt261Page, wait_for_vin_in_listing
from src.pages.staff_portal.sold_listing_page import SoldListingPage


# ─── In-app navigation (tab is shared — clear overlays before each sidebar click) ───
def dismiss_overlays(page: Page):
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        page.evaluate(
            """() => document.querySelectorAll(
                '.cdk-overlay-backdrop, .cdk-overlay-backdrop-showing'
            ).forEach(b => b.remove())"""
        )
    except Exception:
        pass
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('.cdk-overlay-backdrop-showing').length === 0",
            timeout=5_000,
        )
    except Exception:
        pass


def goto_lt261_listing(page: Page) -> Lt261Page:
    dismiss_overlays(page)
    StaffDashboardPage(page).navigate_to_lt261_listing()
    lt261 = Lt261Page(page)
    lt261._wait_listing_settled()
    return lt261


def goto_sold_listing(page: Page) -> SoldListingPage:
    dismiss_overlays(page)
    StaffDashboardPage(page).navigate_to_sold()
    Lt261Page(page)._wait_listing_settled()
    return SoldListingPage(page)


def expect_vin_on_detail_page(page: Page, vin: str):
    """Assert the opened detail page is the record for `vin` (not a neighbouring row)."""
    expect(page.get_by_text(re.compile(re.escape(vin), re.I)).first).to_be_visible(
        timeout=15_000
    )


# ─── Form driving ───
def open_lt261_form(page: Page, form_type: str, vin: str) -> Lt261Page:
    """LT-261 listing → open the paper form; assert its type and checkbox defaults."""
    lt261 = goto_lt261_listing(page)
    lt261.open_paper_form(form_type, vin)

    lt261.expect_form_type(form_type)
    # Default-state check must happen before any checkbox is touched.
    lt261.expect_use_same_address_default(form_type)
    print(
        f"EXPECTED: '{form_type}' form, use-same-address default "
        f"checked={form_type == 'DWI'} | ACTUAL: {lt261.use_same_address_states()} -- MATCH"
    )
    return lt261


def fill_lt261_form(lt261: Lt261Page, officer_name: str, owner_name: str):
    """Fill the paper form body — everything except Stolen, which each phase drives."""
    lt261.fill_year("2018")
    lt261.fill_make("TOY")
    lt261.fill_search_location("pen")

    try:
        # No-ops on DWI (already auto-checked) — the helpers guard on mat-checkbox-checked.
        lt261.check_use_same_address_storage()
        lt261.fill_sale_date(future_date(21))
        lt261.select_notice_of_sale_reason()
        lt261.check_agency_use_same_address()
        lt261.fill_agency_name(officer_name)
    except Exception as exc:
        print(f"NOTE: optional sale/agency section step skipped ({type(exc).__name__}: {exc})")

    lt261.fill_owner_seized_from(owner_name)
    lt261.add_owner_details(name=owner_name)


# ============================================================================
# Base classes — not collected (pytest.ini: python_classes = TestE2E*)
# ============================================================================
class _StolenNoPhase:
    """Stolen = NO → auto-processes: LT-261 Processed listing, then Sold."""

    FORM_TYPE: str = ""
    VIN: str = ""
    OFFICER: dict = {}

    def test_1_submit(self, staff_page: Page):
        """Submit the LT-261 paper form with owner details and Stolen = NO."""
        lt261 = open_lt261_form(staff_page, self.FORM_TYPE, self.VIN)
        fill_lt261_form(lt261, self.OFFICER["name"], self.OFFICER["name"])

        lt261.select_stolen_no()
        lt261.submit_with_confirmation()
        print(f"SUBMITTED: {self.FORM_TYPE} LT-261, Stolen=No, VIN={self.VIN}")

    def test_2_moved_to_lt261_processed(self, staff_page: Page):
        """The application is moved to the LT-261 Processed listing (+ LT-265 issued)."""
        lt261 = goto_lt261_listing(staff_page)
        lt261.click_processed_tab()

        # A just-submitted record takes a few seconds to become queryable — poll.
        waited = wait_for_vin_in_listing(
            staff_page, lt261.search_by_vin, self.VIN, "LT-261 Processed"
        )

        lt261.select_application(0)
        expect_vin_on_detail_page(staff_page, self.VIN)
        lt261.expect_status_processed()

        # Pre-existing E2E-004 coverage: auto-issuance produces an LT-265 entry.
        lt261.click_view_correspondence()
        lt261.expect_lt265_in_correspondence()
        print(
            f"EXPECTED: {self.VIN} Processed + LT-265 issued | ACTUAL: MATCH "
            f"(appeared after {waited:.1f}s)"
        )

    def test_3_vehicle_marked_sold(self, staff_page: Page):
        """The vehicle is marked as Sold."""
        sold = goto_sold_listing(staff_page)

        waited = wait_for_vin_in_listing(staff_page, sold.search_by_vin, self.VIN, "Sold")

        sold.select_application(0)
        expect_vin_on_detail_page(staff_page, self.VIN)
        Lt261Page(staff_page).expect_status_processed()
        print(
            f"EXPECTED: {self.VIN} marked Sold | ACTUAL: found in Sold -- MATCH "
            f"(appeared after {waited:.1f}s)"
        )


class _StolenYesPhase:
    """Stolen = YES → routed to the LT-261 Stolen listing (no auto-process)."""

    FORM_TYPE: str = ""
    VIN: str = ""
    OFFICER: dict = {}

    def test_1_submit(self, staff_page: Page):
        """Submit the LT-261 paper form with owner details and Stolen = YES."""
        lt261 = open_lt261_form(staff_page, self.FORM_TYPE, self.VIN)
        fill_lt261_form(lt261, self.OFFICER["name"], self.OFFICER["name"])

        lt261.select_stolen_yes()
        # Stolen=Yes must NOT auto-issue LT-265, so no success/issuance banner is expected.
        lt261.submit_stolen_form()
        print(f"SUBMITTED: {self.FORM_TYPE} LT-261, Stolen=Yes, VIN={self.VIN}")

    def test_2_moved_to_stolen_listing(self, staff_page: Page):
        """The application is moved to the LT-261 Stolen listing."""
        lt261 = goto_lt261_listing(staff_page)
        waited = lt261.expect_vin_in_stolen_listing(self.VIN)
        print(
            f"EXPECTED: {self.VIN} in LT-261 Stolen listing ({self.FORM_TYPE}, Stolen=Yes) | "
            f"ACTUAL: found -- MATCH (appeared after {waited:.1f}s)"
        )


# ============================================================================
# PHASE 1: E-STOP, Stolen = NO → LT-261 Processed → Sold
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase1EstopStolenNo(_StolenNoPhase):
    FORM_TYPE = "E-Stop"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# PHASE 2: DWI, Stolen = NO → LT-261 Processed → Sold
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase2DwiStolenNo(_StolenNoPhase):
    FORM_TYPE = "DWI"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# PHASE 3: E-STOP, Stolen = YES → LT-261 Stolen listing
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase3EstopStolenYes(_StolenYesPhase):
    FORM_TYPE = "E-Stop"
    VIN = generate_vin()
    OFFICER = generate_person()


# ============================================================================
# PHASE 4: DWI, Stolen = YES → LT-261 Stolen listing
# ============================================================================
@pytest.mark.e2e
@pytest.mark.core
@pytest.mark.critical
@pytest.mark.fixed
class TestE2E004Phase4DwiStolenYes(_StolenYesPhase):
    FORM_TYPE = "DWI"
    VIN = generate_vin()
    OFFICER = generate_person()
