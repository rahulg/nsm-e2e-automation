import re
from datetime import datetime
from pathlib import Path
from playwright.sync_api import Page, expect


class Lt260FormPage:
    def __init__(self, page: Page):
        self.page = page

        # Tabs — support both div[role="tab"] and [role="tab"] patterns
        self.vehicle_details_tab = page.locator('[role="tab"]:has-text("Vehicle Details")')
        self.authorized_person_tab = page.locator('[role="tab"]:has-text("Authorized Person")')
        self.terms_tab = page.locator('[role="tab"]:has-text("Terms and Conditions")')

        # Vehicle Details fields
        self.vin_input = page.locator('input[name="sno"]')
        self.vin_lookup_button = page.locator('button:has-text("VIN Lookup"), button:has-text("Lookup"), button:has-text("Search")').first
        self.make_input = page.locator('input[placeholder="Enter Make"]')
        self.body_select = page.locator('mat-select[aria-label="Body"]')
        self.year_input = page.locator('input[name="year"]')
        self.model_input = page.locator('input[name="model"]')
        self.color_input = page.locator('input[name="color"]')
        self.date_vehicle_left_input = page.locator('input[aria-label*="Date Vehicle Left"]')
        self.license_plate_input = page.locator('input[placeholder="Enter License Plate Number"]')
        self.plate_year_input = page.locator('input[placeholder="Enter Plate Year"]')
        self.approx_value_input = page.locator('input[aria-label="Approximate Value"]')
        self.parking_checkbox = page.locator('mat-checkbox[name="parking"] label, label[for="mat-checkbox-1-input"]').first
        self.storage_checkbox = page.locator('mat-checkbox[name="storage"] label, label[for="mat-checkbox-3-input"]').first
        self.location_input = page.locator('input[aria-label*="Location of Stored Vehicle"]')
        self.address_input = page.locator('input[aria-label*="Address"]').first
        self.zip_input = page.locator('input[aria-label*="Zip"]').first
        self.phone_input = page.locator('input[type="tel"]').first
        self.reference_input = page.locator('input[aria-label="Reference #"]')

        # Authorized Person (Tab 2)
        self.auth_person_name_input = page.locator(
            'input[placeholder="Enter Name"], input[placeholder*="Name" i], '
            'input[aria-label*="Name" i]'
        ).first
        self.auth_person_address_input = page.locator(
            'input[placeholder="Enter Address"], input[placeholder*="Address" i], '
            'input[aria-label*="Address" i]'
        ).first
        self.auth_person_zip_input = page.locator(
            'input[placeholder="Enter Zip"], input[placeholder*="Zip" i], '
            'input[aria-label*="Zip" i]'
        ).first

        # Terms (Tab 3)
        self.terms_name_input = page.locator('input[aria-label="NAME *"]')
        self.terms_email_input = page.locator('input[aria-label="EMAIL *"]')
        self.terms_date_input = page.locator('input[aria-label="DATE *"]')

        # Actions
        self.file_upload_input = page.locator('input[type="file"]').first
        self.submit_button = page.locator('button:has-text("Submit")').first
        self.success_message = page.locator('[class*="success" i], [class*="toast" i], [class*="snack" i]').first

    def _angular_fill(self, locator, value: str):
        """Fill a form field with click + fill."""
        locator.click()
        locator.fill(value)
        self.page.wait_for_timeout(200)

    def click_vehicle_details_tab(self):
        self.vehicle_details_tab.dispatch_event("click")
        self.page.wait_for_load_state("networkidle")

    def click_authorized_person_tab(self):
        """Advance to Authorized Person tab using Next button to preserve form state."""
        next_btn = self.page.locator('button:has-text("Next")').first
        next_btn.scroll_into_view_if_needed(timeout=5_000)
        next_btn.click()
        self.page.wait_for_timeout(2000)

    def click_terms_tab(self):
        """Advance to Terms tab using Next button to preserve form state."""
        next_btn = self.page.locator('button:has-text("Next")').first
        next_btn.scroll_into_view_if_needed(timeout=5_000)
        next_btn.click()
        self.page.wait_for_timeout(2000)

    def enter_vin(self, vin: str):
        self._angular_fill(self.vin_input, vin)

    def _dismiss_overlays(self):
        """Dismiss any blocking overlays (loader, notifications, dialogs)."""
        # Wait for loader overlay to disappear
        try:
            self.page.locator(".cdk-overlay-backdrop.exp-loader-overlay-backdrop").wait_for(
                state="hidden", timeout=10_000
            )
        except Exception:
            pass

        # Dismiss "VIN not found" or other notification dialogs
        for dismiss_selector in [
            'button:has-text("OK")',
            'button:has-text("Close")',
            'button:has-text("Got it")',
            ".cdk-overlay-dark-backdrop",
        ]:
            try:
                el = self.page.locator(dismiss_selector).first
                el.wait_for(state="visible", timeout=2_000)
                el.click(force=True)
                self.page.wait_for_timeout(500)
            except Exception:
                continue

        # Press Escape as last resort to close any remaining dialog
        try:
            overlay = self.page.locator(".cdk-overlay-backdrop-showing")
            if overlay.count() > 0:
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(500)
        except Exception:
            pass

    def click_vin_lookup(self, vin_image_path: str = None):
        self.vin_lookup_button.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)

        # Handle "THE VIN ENTERED MAY HAVE AN ERROR" modal — only appears on first submission,
        # not on resubmission of a previously rejected VIN
        vin_error_modal = self.page.locator('text="THE VIN ENTERED MAY HAVE AN ERROR"')
        try:
            vin_error_modal.wait_for(state="visible", timeout=5000)

            # Upload VIN image
            if vin_image_path is None:
                vin_image_path = str(Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "sample-vin-image.png")

            vin_image_button = self.page.locator('button:has-text("VIN Image"), button:has-text("vin image"), label:has-text("VIN Image")').first
            vin_image_button.evaluate("el => el.scrollIntoView({ block: 'center' })")
            self.page.wait_for_timeout(1000)
            with self.page.expect_file_chooser() as fc_info:
                vin_image_button.dispatch_event("click")
            file_chooser = fc_info.value
            file_chooser.set_files(vin_image_path)
            self.page.wait_for_timeout(3000)

            # Click Submit on the modal
            self.page.locator('button:has-text("Submit")').first.click()
            self.page.wait_for_timeout(2000)
        except Exception:
            # Modal did not appear — VIN was accepted directly (e.g. resubmission)
            pass

    def fill_vehicle_details(self, details: dict):
        if details.get("make"):
            self.make_input.click()
            self.make_input.fill("")
            self.make_input.type(details["make"], delay=100)
            self.page.wait_for_timeout(1000)
            # Select exact matching option — use get_by_text(exact=True) to avoid partial matches
            # e.g. "Ford" must not match "BRADFORD BUILT TRAILER"
            exact_option = self.page.locator("mat-option").get_by_text(details["make"], exact=True)
            exact_option.wait_for(state="visible", timeout=5000)
            exact_option.click()
            self.page.wait_for_timeout(500)
        if details.get("body"):
            self.body_select.click()
            self.page.wait_for_timeout(500)
            option = self.page.locator(f'mat-option:has-text("{details["body"]}")').first
            option.wait_for(state="visible", timeout=5000)
            option.click()
            self.page.wait_for_timeout(1000)
            # Wait for CDK overlay to close after body selection
            try:
                self.page.locator(".cdk-overlay-backdrop").wait_for(state="hidden", timeout=5_000)
            except Exception:
                pass
        if details.get("year"):
            self._angular_fill(self.year_input, details["year"])
        if details.get("model"):
            self._angular_fill(self.model_input, details["model"])
        if details.get("color"):
            self._angular_fill(self.color_input, details["color"])

    def fill_date_vehicle_left(self, date: str):
        self._angular_fill(self.date_vehicle_left_input, date)

    def fill_license_plate(self, plate: str, year: str = None):
        self._angular_fill(self.license_plate_input, plate)
        if year:
            self._angular_fill(self.plate_year_input, year)

    def fill_approx_value(self, value: str):
        self._angular_fill(self.approx_value_input, value)

    def select_reason_storage(self):
        self.storage_checkbox.dispatch_event("click")
        self.page.wait_for_timeout(500)

    def fill_storage_location(self, location: str, address: str, zip_code: str, phone: str = "9195551234"):
        self._angular_fill(self.location_input, location)
        self._angular_fill(self.address_input, address)
        self._angular_fill(self.zip_input, zip_code)
        try:
            self.page.locator(".cdk-overlay-backdrop").wait_for(state="hidden", timeout=15_000)
        except Exception:
            pass
        self.page.wait_for_timeout(1000)

        # Fill telephone number
        try:
            self.phone_input.scroll_into_view_if_needed(timeout=5_000)
            self._angular_fill(self.phone_input, phone)
        except Exception:
            pass

        # Select county — click dropdown then pick first available option
        # County dropdown may not be visible for all body types (e.g. Manufactured Home)
        county_dropdown = self.page.locator('//span[contains(text(),"Enter County")]')
        try:
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self.page.wait_for_timeout(500)
            county_dropdown.scroll_into_view_if_needed(timeout=8_000)
            county_dropdown.click()
            self.page.wait_for_timeout(1000)
            # Use mat-option inside the overlay panel (not mat-chip which also has role="option")
            first_option = self.page.locator('.mat-autocomplete-panel mat-option, .cdk-overlay-pane mat-option').first
            first_option.wait_for(state="visible", timeout=5000)
            first_option.click(force=True)
            self.page.wait_for_timeout(500)
        except Exception:
            # County field not visible for this body type — continue
            pass

    def fill_authorized_person(self, name: str, address: str, zip_code: str):
        self.click_authorized_person_tab()
        self.page.wait_for_timeout(500)
        self._angular_fill(self.auth_person_name_input, name)
        self._angular_fill(self.auth_person_address_input, address)
        self._angular_fill(self.auth_person_zip_input, zip_code)
        self.page.wait_for_timeout(1000)

    def accept_terms_and_sign(self, name: str, email: str):
        self.click_terms_tab()
        self.page.wait_for_timeout(1000)

        # Check all attestation checkboxes on active tab
        checkboxes = self.page.locator("mat-tab-body.mat-tab-body-active mat-checkbox")
        count = checkboxes.count()
        for i in range(count):
            cb = checkboxes.nth(i)
            cls = cb.get_attribute("class") or ""
            if "mat-checkbox-checked" not in cls:
                cb.locator("label").click()
                self.page.wait_for_timeout(200)

        # Fill signature fields
        self._angular_fill(self.terms_name_input, name)
        self._angular_fill(self.terms_email_input, email)
        # Always fill DATE — it's required and may be empty
        today = datetime.now().strftime("%m/%d/%Y")
        self.terms_date_input.wait_for(state="visible", timeout=5_000)
        date_value = self.terms_date_input.input_value()
        if not date_value:
            self._angular_fill(self.terms_date_input, today)

    def submit(self):
        self.submit_button.click()
        self.page.wait_for_load_state("networkidle")

    def submit_with_vin_image(self, vin_image_path: str = None):
        """Click Submit on Tab 3, handle the VIN image modal if it appears, then confirm."""
        self.submit_button.click()
        self.page.wait_for_timeout(3000)

        # Check if VIN error modal appeared (random VINs trigger this)
        vin_error_modal = self.page.locator('text="THE VIN ENTERED MAY HAVE AN ERROR"')
        try:
            vin_error_modal.wait_for(state="visible", timeout=15_000)
        except Exception:
            # No VIN error modal — form may have submitted directly
            self.page.wait_for_load_state("networkidle")
            return

        # VIN error modal appeared — upload VIN image
        if vin_image_path is None:
            vin_image_path = str(Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "sample-vin-image.png")

        # Find the file upload area in the modal (input[type="file"] or upload button)
        file_input = self.page.locator('mat-dialog-container input[type="file"]')
        try:
            file_input.wait_for(state="attached", timeout=5_000)
            file_input.set_input_files(vin_image_path)
        except Exception:
            # Fallback: look for upload button and use file chooser
            upload_btn = self.page.locator(
                'mat-dialog-container button:has-text("Upload"), '
                'mat-dialog-container button:has-text("VIN Image"), '
                'mat-dialog-container label:has-text("Upload"), '
                'mat-dialog-container label:has-text("VIN")'
            ).first
            upload_btn.evaluate("el => el.scrollIntoView({ block: 'center' })")
            self.page.wait_for_timeout(500)
            with self.page.expect_file_chooser() as fc_info:
                upload_btn.dispatch_event("click")
            fc_info.value.set_files(vin_image_path)
        self.page.wait_for_timeout(2000)

        # Click Submit on the modal
        modal_submit = self.page.locator('mat-dialog-container button:has-text("Submit")')
        modal_submit.wait_for(state="visible", timeout=5_000)
        modal_submit.click()
        self.page.wait_for_timeout(2000)
        self.page.wait_for_load_state("networkidle")

    def expect_success(self):
        expect(self.success_message).to_be_visible(timeout=15_000)
