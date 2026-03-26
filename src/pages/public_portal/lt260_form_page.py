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

    def click_vehicle_details_tab(self):
        self.vehicle_details_tab.dispatch_event("click")
        self.page.wait_for_load_state("networkidle")

    def click_authorized_person_tab(self):
        try:
            self.authorized_person_tab.dispatch_event("click")
        except Exception:
            # Fallback: try clicking by text
            try:
                self.page.get_by_text("Authorized Person").first.click()
            except Exception:
                # Try clicking Next button to advance from Vehicle Details
                try:
                    self.page.locator('button:has-text("Next")').first.click()
                    self.page.wait_for_timeout(500)
                except Exception:
                    # JS fallback
                    self.page.evaluate("""() => {
                        const tabs = document.querySelectorAll('[role="tab"]');
                        for (const tab of tabs) {
                            if (tab.textContent.toLowerCase().includes('authorized')) {
                                tab.click();
                                return;
                            }
                        }
                    }""")
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

    def click_terms_tab(self):
        self.terms_tab.dispatch_event("click")
        self.page.wait_for_load_state("networkidle")

    def enter_vin(self, vin: str):
        self.vin_input.fill(vin)

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

        # Handle "The VIN Entered MAY have an error" modal
        vin_error_modal = self.page.locator('text="THE VIN ENTERED MAY HAVE AN ERROR"')
        vin_error_modal.wait_for(state="visible", timeout=10000)

        # Upload VIN image: click the VIN Image button and handle file chooser
        if vin_image_path is None:
            vin_image_path = str(Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "sample-vin-image.png")

        vin_image_button = self.page.locator('button:has-text("VIN Image"), button:has-text("vin image"), label:has-text("VIN Image")').first
        # Scroll the modal content so the button is visible
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

    def fill_vehicle_details(self, details: dict):
        if details.get("make"):
            self.make_input.click()
            self.make_input.fill("")
            self.make_input.type(details["make"], delay=100)
            # Wait for autocomplete dropdown and select the first matching option
            autocomplete_option = self.page.locator('mat-option, .mat-autocomplete-panel .mat-option, [role="option"]').first
            autocomplete_option.wait_for(state="visible", timeout=5000)
            autocomplete_option.click()
            self.page.wait_for_timeout(500)
        if details.get("body"):
            self.body_select.click()
            self.page.wait_for_timeout(500)
            option = self.page.locator(f'mat-option:has-text("{details["body"]}")').first
            option.wait_for(state="visible", timeout=5000)
            option.click()
            self.page.wait_for_timeout(500)
        if details.get("year"):
            self.year_input.fill(details["year"])
        if details.get("model"):
            self.model_input.fill(details["model"])
        if details.get("color"):
            self.color_input.fill(details["color"])

    def fill_date_vehicle_left(self, date: str):
        self.date_vehicle_left_input.fill(date)

    def fill_license_plate(self, plate: str, year: str = None):
        self.license_plate_input.fill(plate)
        if year:
            self.plate_year_input.fill(year)

    def fill_approx_value(self, value: str):
        self.approx_value_input.fill(value)

    def select_reason_storage(self):
        self.storage_checkbox.dispatch_event("click")
        self.page.wait_for_timeout(500)

    def fill_storage_location(self, location: str, address: str, zip_code: str, phone: str = "9195551234"):
        self.location_input.fill(location)
        self.address_input.fill(address)
        self.zip_input.fill(zip_code)
        try:
            self.page.locator(".cdk-overlay-backdrop").wait_for(state="hidden", timeout=15_000)
        except Exception:
            pass
        self.page.wait_for_timeout(1000)

        # Fill telephone number
        try:
            self.phone_input.scroll_into_view_if_needed(timeout=5_000)
            self.phone_input.fill(phone)
            self.page.wait_for_timeout(300)
        except Exception:
            pass

        # Select county — click dropdown then pick first available option
        county_dropdown = self.page.locator('//span[contains(text(),"Enter County")]')
        county_dropdown.scroll_into_view_if_needed(timeout=5_000)
        county_dropdown.click()
        self.page.wait_for_timeout(1000)
        # Use mat-option inside the overlay panel (not mat-chip which also has role="option")
        first_option = self.page.locator('.mat-autocomplete-panel mat-option, .cdk-overlay-pane mat-option').first
        first_option.wait_for(state="visible", timeout=5000)
        first_option.click(force=True)
        self.page.wait_for_timeout(500)

    def fill_authorized_person(self, name: str, address: str, zip_code: str):
        self.click_authorized_person_tab()
        self.page.wait_for_timeout(500)
        self.auth_person_name_input.fill(name)
        self.auth_person_address_input.fill(address)
        self.auth_person_zip_input.fill(zip_code)
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
        self.terms_name_input.fill(name)
        self.terms_email_input.fill(email)
        try:
            date_value = self.terms_date_input.input_value()
            if not date_value:
                today = datetime.now().strftime("%m/%d/%Y")
                self.terms_date_input.fill(today)
        except Exception:
            pass

    def submit(self):
        self.submit_button.click()
        self.page.wait_for_load_state("networkidle")

    def expect_success(self):
        expect(self.success_message).to_be_visible(timeout=15_000)
