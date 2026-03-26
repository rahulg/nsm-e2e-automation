from datetime import datetime
from playwright.sync_api import Page, expect


class Lt263FormPage:
    def __init__(self, page: Page):
        self.page = page
        # Sale type radio buttons — handle mat-radio-button wrapping
        self.sale_type_public = page.locator(
            'mat-radio-button:has-text("Public"), label:has-text("Public Sale"), '
            'input[value*="public" i], button:has-text("Public")'
        ).first
        self.sale_type_private = page.locator(
            'mat-radio-button:has-text("Private"), label:has-text("Private Sale"), '
            'input[value*="private" i], button:has-text("Private")'
        ).first
        self.sale_date_input = page.locator(
            'input[placeholder="MM/DD/YYYY"], input[name*="sale" i][name*="date" i], '
            'input[name*="date" i][type="date"]'
        ).first
        self.lien_amount_input = page.locator(
            'input[name*="lien" i][name*="amount" i], input[name*="total" i], '
            'input[aria-label*="Lien Amount" i]'
        ).first
        self.labor_cost_input = page.locator(
            'input[name*="labor" i], input[aria-label*="Labor" i]'
        ).first
        self.storage_cost_input = page.locator(
            'input[name*="storage" i], input[aria-label*="Storage" i]'
        ).first
        self.court_name_input = page.locator('input[name*="court" i]').first
        self.terms_checkboxes = page.locator('input[type="checkbox"]')
        self.submit_button = page.locator('button[type="submit"]:has-text("Submit"), button:has-text("Submit")').first
        self.success_message = page.locator('[class*="success" i], text="submitted successfully"').first
        self.terms_tab = page.locator('[role="tab"]:has-text("Terms and Conditions"), [role="tab"]:has-text("Terms")')

    def _select_sale_type_radio(self, sale_type: str):
        """Select a sale type radio button using JS fallback for mat-radio-button."""
        self.page.wait_for_timeout(500)
        clicked = self.page.evaluate(f"""() => {{
            const radios = document.querySelectorAll('mat-radio-button');
            for (const r of radios) {{
                if (r.textContent.toLowerCase().includes('{sale_type.lower()}')) {{
                    const inner = r.querySelector('.mat-radio-inner-circle') ||
                                  r.querySelector('input[type="radio"]') ||
                                  r.querySelector('label') || r;
                    inner.click();
                    return true;
                }}
            }}
            const inputs = document.querySelectorAll('input[type="radio"]');
            for (const inp of inputs) {{
                const label = inp.closest('label') || inp.parentElement;
                if (label && label.textContent.toLowerCase().includes('{sale_type.lower()}')) {{
                    inp.click();
                    return true;
                }}
            }}
            return false;
        }}""")
        if clicked:
            self.page.wait_for_timeout(500)
            return

        # Fallback: use Playwright locators
        radio = self.sale_type_public if "public" in sale_type.lower() else self.sale_type_private
        try:
            radio.wait_for(state="visible", timeout=5_000)
            tag = radio.evaluate("el => el.tagName.toLowerCase()")
            if tag == "mat-radio-button":
                radio.locator("label").click()
            else:
                radio.click()
        except Exception:
            radio.click(force=True)
        self.page.wait_for_timeout(500)

    def select_public_sale(self):
        """Select 'Public Sale' radio button (may be mat-radio-button)."""
        self._select_sale_type_radio("public")

    def select_private_sale(self):
        """Select 'Private Sale' radio button (may be mat-radio-button)."""
        self._select_sale_type_radio("private")

    def fill_sale_date(self, date: str):
        self.sale_date_input.fill(date)

    def fill_lien_amount(self, amount: str):
        self.lien_amount_input.fill(amount)

    def fill_cost_breakdown(self, labor: str, storage: str):
        self.labor_cost_input.fill(labor)
        self.storage_cost_input.fill(storage)

    def check_all_terms(self):
        count = self.terms_checkboxes.count()
        for i in range(count):
            checkbox = self.terms_checkboxes.nth(i)
            if not checkbox.is_checked():
                checkbox.check()

    def submit(self):
        self.submit_button.click()
        self.page.wait_for_load_state("networkidle")

    def expect_success(self):
        expect(self.success_message).to_be_visible(timeout=15_000)

    # ===== E2E-001 ENHANCED METHODS =====

    def click_terms_tab(self):
        self.terms_tab.first.dispatch_event("click")
        self.page.wait_for_timeout(1000)

    def accept_terms_and_sign(self, name: str, email: str):
        self.click_terms_tab()
        self.page.wait_for_timeout(1000)

        mat_checkboxes = self.page.locator("mat-tab-body.mat-tab-body-active mat-checkbox")
        mat_count = mat_checkboxes.count()
        if mat_count > 0:
            for i in range(mat_count):
                cb = mat_checkboxes.nth(i)
                cls = cb.get_attribute("class") or ""
                if "mat-checkbox-checked" not in cls:
                    cb.locator("label").click()
                    self.page.wait_for_timeout(200)
        else:
            self.check_all_terms()

        name_input = self.page.locator('input[aria-label="NAME *"], input[aria-label*="Name" i]').first
        email_input = self.page.locator('input[aria-label="EMAIL *"], input[aria-label*="Email" i]').first
        name_input.fill(name)
        email_input.fill(email)

        try:
            date_input = self.page.locator('input[aria-label="DATE *"], input[aria-label*="Date" i]').first
            date_value = date_input.input_value()
            if not date_value:
                today = datetime.now().strftime("%m/%d/%Y")
                date_input.fill(today)
        except Exception:
            pass
