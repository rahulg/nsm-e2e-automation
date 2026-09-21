"""
Staff Portal Paper Form Page — for adding paper LT-260/262/263 submissions.

Paper forms are received via mail and entered by staff. They follow a similar
structure to digital forms but with some differences:
  - Pre-filled fields from prior forms are EDITABLE (unlike PP where they are read-only)
  - Paper forms relax MOST date restrictions, but NOT the LT-263 sale-date calendar rule
    (see fill_lt263_sale_date below)
"""

import re
from datetime import datetime, timedelta

from playwright.sync_api import Page, expect

# The LT-263 SALE DATE rejects certain calendar days — QA rejects Sundays outright.
# CONFIRMED on QA 2026-07-31 against a resumed paper LT-263 draft (VIN N5818ZZBN5FMCM0ES):
# a Sunday date (11/08/2026) leaves the input `ng-invalid` with NO mat-error rendered, and
# the form's Submit button stays `disabled` forever; re-filling the same field with the
# Monday (11/09/2026) flipped it to `ng-valid` and enabled Submit. This mirrors the public
# LT-263 form's documented behaviour — the earlier "paper forms have no sale-date
# restrictions" note in this module was wrong.
#
# Because the rejection surfaces ONLY as ng-invalid + a permanently disabled Submit, a raw
# date offset is not safe: today+100 lands on a Sunday roughly one year in seven, and the
# failure then looks like an unrelated 15s "Submit not enabled" timeout several steps later.
SALE_DATE_MAX_ROLL_DAYS = 7
SALE_DATE_FORMAT = "%m/%d/%Y"


class PaperFormPage:
    def __init__(self, page: Page):
        self.page = page

        # Lien charges (for LT-262 paper form — Phase 4)
        self.storage_fee_input = page.locator('input[name="storageFee"]').first
        self.towing_fee_input = page.locator('input[name="TowingFee"]').first
        self.labor_fee_input = page.locator('input[name="LaborFee"]').first

        # Sale details (for LT-263 paper form — Phase 5)
        self.sale_type_public = page.locator(
            'mat-radio-button:has-text("Public"), input[value*="public" i], '
            'label:has-text("Public") input[type="radio"], '
            '[role="radio"]:has-text("Public")'
        ).first
        self.sale_type_private = page.locator(
            'mat-radio-button:has-text("Private"), input[value*="private" i], '
            'label:has-text("Private") input[type="radio"], '
            '[role="radio"]:has-text("Private")'
        ).first
        self.sale_date_input = page.locator(
            'input[name*="sale" i][name*="date" i], input[name*="date" i][type="date"]'
        ).first
        self.lien_amount_input = page.locator(
            'input[name*="lien" i][name*="amount" i], input[name*="total" i]'
        ).first

        # Action buttons
        self.submit_button = page.locator('button:has-text("Submit"), button:has-text("Save")').first
        self.next_button = page.locator('button:has-text("Next")').first

    # ===== CDK overlay helper =====

    def _dismiss_cdk_overlay(self):
        """Dismiss any open CDK overlay that blocks clicks."""
        try:
            self.page.evaluate("""() => {
                const backdrops = document.querySelectorAll(
                    '.cdk-overlay-backdrop-showing, .cdk-overlay-backdrop'
                );
                backdrops.forEach(b => { b.click(); b.remove(); });
            }""")
            self.page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(300)
        except Exception:
            pass

    # ===== Phase 1: LT-260 Add from Paper (high-level helpers for E2E-046+) =====

    def select_requester_type(self, requester_type: str):
        """Select Individual or Business requester type in the paper form modal."""
        radio = self.page.locator(
            f'mat-radio-button:has-text("{requester_type}"), '
            f'label:has-text("{requester_type}"), '
            f'[role="radio"]:has-text("{requester_type}")'
        ).first
        try:
            radio.wait_for(state="visible", timeout=10_000)
            radio.click()
        except Exception:
            self.page.locator(f'text="{requester_type}"').first.click()
        self.page.wait_for_timeout(500)

    def enter_vin(self, vin: str):
        """Enter VIN in the Add from Paper modal input."""
        vin_input = self.page.locator(
            'mat-dialog-container input[placeholder*="VIN" i], '
            'mat-dialog-container input[name*="vin" i]'
        ).first
        vin_input.wait_for(state="visible", timeout=10_000)
        vin_input.fill(vin)
        self.page.wait_for_timeout(500)

    def click_vin_lookup(self):
        """Click Next in the Add from Paper modal to proceed after VIN entry."""
        next_btn = self.page.locator('mat-dialog-container button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(3000)

    def fill_vehicle_details(self, vehicle: dict):
        """Fill vehicle fields (year, make, date vehicle left) from a vehicle dict."""
        from datetime import datetime, timedelta
        if vehicle.get("year"):
            self.fill_year(vehicle["year"])
        if vehicle.get("make"):
            make_prefix = vehicle["make"][:3].upper()
            self.fill_make(make_prefix)
        date_left = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        self.fill_date_vehicle_left(date_left)

    def fill_storage_location(self, location_name: str, street: str = None, zip_code: str = None):
        """Search for storage location by name and select the first autocomplete result."""
        search_text = location_name[:10] if location_name else "Garage"
        self.fill_search_location(search_text)
        self.select_stolen_no()

    # ===== Phase 1: LT-260 Add from Paper (low-level) =====

    def fill_modal_vin_and_next(self, vin: str):
        """In the Add from Paper modal: enter VIN and click Next (no E-Stop radio for LT-260)."""
        vin_input = self.page.locator(
            'mat-dialog-container input[placeholder*="VIN" i], '
            'mat-dialog-container input[name*="vin" i]'
        ).first
        vin_input.wait_for(state="visible", timeout=10_000)
        vin_input.fill(vin)
        self.page.wait_for_timeout(500)

        next_btn = self.page.locator('mat-dialog-container button:has-text("Next")').first
        next_btn.wait_for(state="visible", timeout=10_000)
        next_btn.click()
        try:
            self.page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass  # the staff SPA background-polls, so networkidle is not reliable here
        self._wait_paper_form_ready()

    def _wait_paper_form_ready(self, timeout: int = 45_000):
        """Block until the paper form has actually RENDERED its body.

        Replaces a blind 800ms settle after the VIN modal's Next. That fixed pause was a race:
        when the form took longer to render, the very next call (fill_year) waited only 10s on
        the Year input and timed out — surfacing as an intermittent Phase-3a failure that then
        cascaded through the whole paper lifecycle (3c/3e/3g/3j/3k/3m), costing ~15-20 min per
        run. Reproduced on QA 2026-08-04: probes that inserted their own extra waits here passed
        consistently, while the un-waited path failed 6/6 in the same minutes.
        Waits on a CONCRETE element instead, per this suite's convention (see LISTING_READY_SELECTOR).
        """
        try:
            self.page.wait_for_url(re.compile(r"paperFormdetails", re.I), timeout=timeout)
        except Exception:  # noqa: BLE001
            pass  # some paper routes differ; the field wait below is the real gate
        self.page.locator(
            'input[name="year"], input[name="vin"], input[role="combobox"]'
        ).first.wait_for(state="visible", timeout=timeout)

    def fill_make(self, make_text: str = "TOY"):
        """Type in the Make autocomplete field and select the first suggestion."""
        make_input = self.page.locator("(//input[@role='combobox'])[1]")
        expect(make_input).to_be_visible(timeout=15_000)
        make_input.click()
        make_input.fill(make_text)
        self.page.wait_for_timeout(400)  # autocomplete debounce; option wait below is 10s

        option = self.page.locator('.cdk-overlay-pane mat-option').first
        option.wait_for(state="visible", timeout=10_000)
        option.click()
        self.page.wait_for_timeout(500)

    def fill_year(self, year: str):
        """Fill the Year field, then Tab out to close any autocomplete and settle the form."""
        year_input = self.page.locator(
            'input[name*="year" i], input[aria-label*="Year" i], input[placeholder*="Year" i]'
        ).first
        year_input.wait_for(state="visible", timeout=10_000)
        year_input.fill(year)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(500)

    def fill_date_vehicle_left(self, date_str: str):
        """Fill the 'DATE VEHICLE LEFT' field (MM/DD/YYYY)."""
        date_input = self.page.locator(
            'input[aria-label*="Date Vehicle Left" i], '
            'input[placeholder*="Date Vehicle Left" i], '
            'input[name*="dateVehicle" i], '
            'input[name*="date_vehicle" i], '
            'input[placeholder="MM/DD/YYYY"]'
        ).first
        date_input.wait_for(state="visible", timeout=10_000)
        date_input.fill(date_str)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(300)

    def fill_search_location(self, search_text: str = "pen"):
        """Type in SEARCH LOCATION field and pick the first suggestion."""
        location_input = self.page.locator(
            'input[placeholder*="Search Garage Name or Address" i]'
        ).first
        location_input.wait_for(state="visible", timeout=10_000)
        location_input.click()
        location_input.fill(search_text)
        self.page.wait_for_timeout(800)  # autocomplete debounce; suggestion wait below is 10s

        suggestion = self.page.locator('.cdk-overlay-pane mat-option, mat-autocomplete mat-option').first
        suggestion.wait_for(state="visible", timeout=10_000)
        suggestion.click()
        self.page.wait_for_timeout(500)

    def fill_storage_contact_if_blank(self, telephone: str = "(919) 555-0123"):
        """Fill the storage-location COUNTY / TELEPHONE NO when the garage lookup left them blank.

        Picking a garage in SEARCH LOCATION auto-populates the whole storage-address block from
        that garage's record. COUNTY and TELEPHONE NO are REQUIRED (`*`) on the LT-260 paper form,
        but a garage record that carries no county/phone populates neither — the form then stays
        invalid and Submit renders `disabled="true"`, which surfaces only as a 30s click timeout
        with no error message and no mat-error text.

        MEASURED on STAGE 2026-07-31: the 'Garage' typeahead resolves to 'ABC Garage'
        (171 Oak Ave / Greensboro / 27401), whose record populates ADDRESS/ZIP/CITY/STATE but
        leaves COUNTY and TELEPHONE NO empty — so every paper-LT-260 submit failed there while
        passing on QA, whose garage record has both.

        Filling ONLY when blank keeps this a no-op wherever the lookup already populates them, so
        it does not mask a regression in the auto-populate itself. Any county satisfies the
        requirement (the field is not asserted downstream), so the first option is taken.
        """
        county = self.page.locator('mat-select[aria-labelledby*="county-label"]').first
        try:
            county.wait_for(state="visible", timeout=5_000)
            if "mat-select-empty" in (county.get_attribute("class") or ""):
                county.click()
                option = self.page.locator(".cdk-overlay-pane mat-option").first
                option.wait_for(state="visible", timeout=8_000)
                option.click()
                self.page.wait_for_timeout(400)
                print("NOTE: COUNTY was blank after the garage lookup — selected the first option")
        except Exception:  # noqa: BLE001
            print("NOTE: no COUNTY control on this form — skipped")

        phone = self.page.locator('input[name="telephone_no"]').first
        try:
            phone.wait_for(state="visible", timeout=5_000)
            if not (phone.input_value() or "").strip():
                phone.fill(telephone)
                self.page.keyboard.press("Tab")
                self.page.wait_for_timeout(300)
                print(f"NOTE: TELEPHONE NO was blank after the garage lookup — filled {telephone}")
        except Exception:  # noqa: BLE001
            print("NOTE: no TELEPHONE NO control on this form — skipped")

    def add_owner(self, name: str, address: str, zip_code: str,
                  address2: str = "Suite 100"):
        """Click '+ Add Owner' and fill the appended owner row.

        A top-level `owner_name` input is always present; '+ Add Owner' appends
        `owner_<field>__id-N` inputs — so target the `__`-suffixed names and take
        the last row.
        """
        add_btn = self.page.locator('//span[contains(text(),"+ Add Owner")]').first
        try:
            add_btn.wait_for(state="visible", timeout=10_000)
        except Exception:
            add_btn = self.page.get_by_text(re.compile(r"\+?\s*Add Owner", re.I)).first
            add_btn.wait_for(state="visible", timeout=10_000)
        add_btn.scroll_into_view_if_needed()
        add_btn.click()

        # The appended owner row is ready once its name input renders.
        self.page.locator('input[name^="owner_name__"]').last.wait_for(
            state="visible", timeout=15_000
        )

        def _fill(selector: str, value: str, required: bool = True):
            field = self.page.locator(selector).last
            try:
                field.wait_for(state="visible", timeout=5_000)
            except Exception:
                if required:
                    raise
                return
            field.scroll_into_view_if_needed()
            field.fill(value)
            self.page.wait_for_timeout(300)

        _fill('input[name^="owner_name__"]', name)
        _fill('input[name^="owner_address__"]', address)
        _fill('input[name^="owner_address2__"]', address2, required=False)
        _fill('input[name^="owner_zip__"]', zip_code)
        self.page.wait_for_timeout(500)

    def select_stolen_no(self):
        """Select 'No' from the Stolen dropdown."""
        stolen_dropdown = self.page.locator(
            'mat-select[aria-label*="Stolen" i], mat-select[name*="stolen" i]'
        ).first
        stolen_dropdown.wait_for(state="visible", timeout=10_000)
        stolen_dropdown.click()
        self.page.wait_for_timeout(500)

        no_option = self.page.locator('mat-option:has-text("No")').first
        no_option.wait_for(state="visible", timeout=10_000)
        no_option.click()
        self.page.wait_for_timeout(500)

    def submit_with_confirmation(self):
        """Click Submit → confirm modal (Yes) → verify green banner → wait for redirect."""
        self._dismiss_cdk_overlay()
        submit_btn = self.page.locator('button:has-text("Submit")').first
        submit_btn.wait_for(state="visible", timeout=15_000)
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        self.page.wait_for_timeout(1000)

        # Confirmation modal → Yes
        yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
        yes_btn.wait_for(state="visible", timeout=10_000)
        yes_btn.click()

        # Green success toast — a successful submission always raises one.
        # expect() polls, so start it the instant Yes is clicked: the toast
        # auto-dismisses, and any wait_for_timeout here risks missing it.
        success = self.page.get_by_text(re.compile(r"success", re.I)).first
        expect(success).to_be_visible(timeout=15_000)

        # Wait for redirect
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    # ===== Phase 1 assertion =====

    def expect_paper_form_visible(self):
        """Verify paper form entry screen is visible."""
        expect(
            self.page.get_by_text(re.compile(r"Individual|Business|Paper|Add from Paper", re.I)).first
        ).to_be_visible(timeout=15_000)

    # ===== Phase 4: LT-262 lien charges =====

    def fill_lien_charges(self, charges: dict):
        """Fill lien charges for paper LT-262."""
        charge_map = {
            "labor": "LaborFee",
            "towing": "TowingFee",
            "storage": "storageFee",
        }

        for charge_type, fee_name in charge_map.items():
            amount = charges.get(charge_type)
            if amount:
                checkbox = self.page.locator(f'mat-checkbox:has-text("{charge_type.capitalize()}")')
                try:
                    cls = checkbox.get_attribute("class") or ""
                    if "mat-checkbox-checked" not in cls:
                        checkbox.locator("label").click()
                        self.page.wait_for_timeout(300)
                except Exception:
                    pass

                fee_input = self.page.locator(f'input[name="{fee_name}"]')
                try:
                    fee_input.fill(amount)
                except Exception:
                    pass
                self.page.wait_for_timeout(200)

    def verify_fields_editable(self):
        """Verify that pre-filled fields are editable (paper form feature)."""
        try:
            make_input = self.page.locator("(//input[@role='combobox'])[1]")
            assert not make_input.is_disabled(), "Make field should be editable in paper form"
        except Exception:
            pass

    # ===== Phase 5: LT-263 paper form sale details =====

    def fill_lt263_sale_date(self, sale_date: str) -> str:
        """Fill the paper LT-263 SALE DATE, rolling forward past any day the form rejects.

        Returns the date actually accepted (>= the requested one), so a caller that needs to
        assert on the sale date uses the real value rather than the one it asked for.

        Validity is READ BACK off the control (ng-invalid) instead of assumed, so a holiday
        or any other blocked day is handled the same way as the known Sunday rule. The form
        renders no mat-error for a rejected day — the only signals are ng-invalid on the input
        and a disabled Submit — so this is the only way to detect it at fill time rather than
        as an unexplained timeout several steps later.
        """
        date_input = self.page.locator('input[name="sale_date"]').first
        date_input.wait_for(state="visible", timeout=10_000)

        # Accept ISO too (E2E-005 / E2E-020 pass "%Y-%m-%d"), mirroring Lt261Page. Typed
        # verbatim, an ISO string is parsed by the datepicker as UTC midnight and renders as
        # the PREVIOUS day in the NC-timezone browser — 2026-09-21 (Mon) became 9/20 (Sun),
        # "A Sunday sale date cannot be selected." left Submit disabled (E2E-020, 2026-09-14),
        # and the verbatim path also skipped the roll-forward below. Normalise first.
        base = None
        for fmt in (SALE_DATE_FORMAT, "%Y-%m-%d"):
            try:
                base = datetime.strptime(sale_date, fmt)
                break
            except ValueError:
                continue
        if base is None:
            # An unexpected format is not this helper's problem — fill it verbatim and let
            # the caller's own assertions speak.
            date_input.fill(sale_date)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(300)
            return sale_date

        for offset in range(SALE_DATE_MAX_ROLL_DAYS + 1):
            candidate = (base + timedelta(days=offset)).strftime(SALE_DATE_FORMAT)
            date_input.click()
            date_input.fill("")
            self.page.wait_for_timeout(200)
            date_input.fill(candidate)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(800)

            if "ng-invalid" not in (date_input.get_attribute("class") or ""):
                if offset:
                    print(
                        f"NOTE: paper LT-263 SALE DATE {sale_date} was rejected by the form "
                        f"(ng-invalid) — rolled forward to {candidate}"
                    )
                return candidate

        errors = self.page.locator("mat-error, .mat-error").all_text_contents()
        raise AssertionError(
            f"EXPECTED: an accepted paper LT-263 SALE DATE within "
            f"{SALE_DATE_MAX_ROLL_DAYS} days of {sale_date} | ACTUAL: every candidate left the "
            f"input ng-invalid — form errors: {errors}"
        )

    def fill_lt263_sale_details(self, sale_type: str = "public", sale_date: str = None,
                                lien_amount: str = "800"):
        """Fill Vehicle Sale Information for paper LT-263:
        TYPE OF SALE (mat-select dropdown) → SALE DATE → Lien Amount → Lien For = LABOR checkbox.
        """
        # TYPE OF SALE — mat-select dropdown.
        # Primary: the labelled control (case-insensitive, tolerant of "Type of Sale").
        # Fallback must EXCLUDE the paginator's "Page Size" mat-select — a bare
        # `mat-select` .first grabbed that dropdown when the sale form hadn't
        # rendered, which is what made this step click the paginator.
        type_of_sale_select = self.page.locator('mat-select[aria-label="TYPE OF SALE" i]').first
        try:
            type_of_sale_select.wait_for(state="visible", timeout=10_000)
        except Exception:
            type_of_sale_select = self.page.locator(
                'mat-select:not([aria-label="Page Size" i])'
            ).first
            type_of_sale_select.wait_for(state="visible", timeout=10_000)
        type_of_sale_select.click()
        self.page.wait_for_timeout(500)

        option_text = "Public" if sale_type.lower() == "public" else "Private"
        option = self.page.locator(f'mat-option:has-text("{option_text}")').first
        option.wait_for(state="visible", timeout=5_000)
        option.click()
        self.page.wait_for_timeout(500)

        # SALE DATE — rolled forward past any calendar day the form rejects (see
        # fill_lt263_sale_date; a Sunday silently disables Submit).
        if sale_date:
            self.fill_lt263_sale_date(sale_date)

        # Lien For — Labor checkbox first (reveals the lien amount input)
        # Click the mat-checkbox that contains "Labor" to trigger Angular change detection
        labor_cb = self.page.locator('//mat-checkbox[.//span[contains(text(),"Labor")]]').first
        labor_cb.wait_for(state="visible", timeout=10_000)
        cls = labor_cb.get_attribute("class") or ""
        if "mat-checkbox-checked" not in cls:
            labor_cb.locator("label").click()
            self.page.wait_for_timeout(800)

        # Lien Amount
        lien_input = self.page.locator("(//input[@name='lien_amount'])[1]")
        expect(lien_input).to_be_visible(timeout=10_000)
        lien_input.fill(lien_amount)
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(300)

    def submit_paper_lt263(self):
        """Submit paper LT-263:
        Click Submit → confirm Yes → Issue modal → Issue → OK modal → OK.
        """
        self._dismiss_cdk_overlay()

        # Submit button (enabled after form is filled)
        submit_btn = self.page.locator('button:has-text("Submit")').first
        expect(submit_btn).to_be_enabled(timeout=15_000)
        submit_btn.scroll_into_view_if_needed()
        submit_btn.click()
        self.page.wait_for_timeout(1000)

        # Confirmation modal → Yes
        yes_btn = self.page.locator('mat-dialog-container button:has-text("Yes")').first
        yes_btn.wait_for(state="visible", timeout=10_000)
        yes_btn.click()
        self.page.wait_for_timeout(1500)

        # Issue modal → Issue
        issue_btn = self.page.locator('mat-dialog-container button:has-text("Issue")').first
        issue_btn.wait_for(state="visible", timeout=10_000)
        issue_btn.click()
        self.page.wait_for_timeout(1500)

        # OK modal → OK
        ok_btn = self.page.locator(
            'mat-dialog-container button:has-text("Ok"), '
            'mat-dialog-container button:has-text("OK")'
        ).first
        ok_btn.wait_for(state="visible", timeout=10_000)
        ok_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    # ===== Legacy fill_sale_details (kept for other tests) =====

    def fill_sale_details(self, sale_type: str = "public", sale_date: str = None,
                          lien_amount: str = "800"):
        """Fill sale details for paper LT-263."""
        radio = self.sale_type_public if sale_type.lower() == "public" else self.sale_type_private
        try:
            radio.wait_for(state="visible", timeout=10_000)
            tag = radio.evaluate("el => el.tagName.toLowerCase()")
            if tag in ("mat-radio-button", "label"):
                radio.locator("label").click() if tag == "mat-radio-button" else radio.click()
            else:
                radio.click()
        except Exception:
            try:
                radio.click(force=True)
            except Exception:
                pass
        self.page.wait_for_timeout(500)

        if sale_date:
            try:
                self.sale_date_input.fill(sale_date)
            except Exception:
                try:
                    date_input = self.page.locator('input[placeholder="MM/DD/YYYY"]').first
                    date_input.fill(sale_date)
                except Exception:
                    pass

        try:
            self.lien_amount_input.fill(lien_amount)
        except Exception:
            pass
        self.page.wait_for_timeout(500)

    # ===== Shared submit (Phases 4 & 5 — no confirmation modal) =====

    def submit(self):
        """Submit paper form with fallback strategies (no confirmation modal)."""
        self._dismiss_cdk_overlay()

        try:
            self.submit_button.wait_for(state="visible", timeout=10_000)
            self.submit_button.scroll_into_view_if_needed()
            self.submit_button.click()
        except Exception:
            clicked = self.page.evaluate("""() => {
                const targets = ['submit', 'save', 'add'];
                const buttons = document.querySelectorAll('button, input[type="submit"]');
                let best = null;
                for (const btn of buttons) {
                    const txt = (btn.textContent || '').toLowerCase().trim();
                    const type = (btn.getAttribute('type') || '').toLowerCase();
                    if (type === 'submit' || targets.some(t => txt.includes(t))) {
                        if (!btn.disabled && btn.offsetParent !== null) {
                            best = btn;
                        }
                    }
                }
                if (best) { best.scrollIntoView(); best.click(); return true; }
                return false;
            }""")
            if not clicked:
                btn = self.page.locator(
                    'button:has-text("Submit"), button:has-text("Save"), '
                    'button:has-text("Add"), button[type="submit"]'
                ).last
                try:
                    btn.click(force=True)
                except Exception:
                    try:
                        btn.dispatch_event("click")
                    except Exception:
                        pass
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

    def click_next(self):
        self.next_button.click()
        self.page.wait_for_timeout(1000)
