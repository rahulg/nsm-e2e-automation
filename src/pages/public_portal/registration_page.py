"""Page objects for the public-portal Individual registration flow (E2E-060).

Three surfaces are involved, each with its own quirks:

* **NSM public portal** (`nsm-qa-public.nc.verifi.dev`) — the profile registration form.
* **MyNCID Ping login** (`login.myncidpp.nc.gov`) — username/password sign-on.
* **MyNCID self-registration SPA** (`myncidpp.nc.gov`) — the account-creation wizard.

The NCID account-creation UI was rebuilt as a 3-step wizard ("Create an Account" →
account-type cards → a formio/Angular signup form) with a single REGISTER button,
so the older Save-then-Confirm shape does not exist here. There is no confirm-email
field, but the QA/UAT form does render a required "* Confirm Password" (handled by
``NCIDRegistrationPage.fill_confirm_password``, tolerant of it being absent).
"""

import re
from playwright.sync_api import Page


# The portal's landing route redirects (/ncdot-nsm-signin → /ncshp-nss-signin) and
# renders behind a spinner. Observed ~10 s on QA, so anything that assumes the page
# is interactive right after `goto` will act on an empty DOM.
SIGNIN_READY_TIMEOUT_MS = 90_000

PROFILE_REGISTERED_TEXT = "Your profile details have been successfully registered."
# MyNCID's post-REGISTER confirmation wording has changed over time: older builds
# showed "Registration Successful"; the current QA/UAT build lands on a
# "Step 3 of 3 / Verify your email / We sent a verification link to <email>"
# screen. Any of these confirms the account was created and the link emailed.
NCID_REGISTERED_TEXT = (
    "Registration Successful",
    "Verify your email",
    "We sent a verification link",
)
NCID_ACTIVATED_TEXT = "Account Created"


def wait_for_portal_ready(page: Page, timeout_ms: int = SIGNIN_READY_TIMEOUT_MS):
    """Block until the Angular portal has painted something past its loading spinner.

    `networkidle` alone is not enough — it fires while the spinner is still up and
    the body is empty, and the sign-in route redirects afterwards.
    """
    deadline = timeout_ms
    step = 1_000
    waited = 0
    while waited < deadline:
        page.wait_for_timeout(step)
        waited += step
        # The portal chains redirects (/authentication/validate → dashboard), so an
        # evaluate can land exactly as the document is swapped. That is a race to ride
        # out, not a failure.
        if len(safe_body_text(page).strip()) > 40:
            page.wait_for_timeout(1_000)  # let the last bindings settle
            return
    raise AssertionError(
        f"Public portal did not finish rendering within {timeout_ms} ms (url={page.url})"
    )


def safe_body_text(page: Page, attempts: int = 5) -> str:
    """Read document.body.innerText, tolerating a mid-navigation context teardown.

    Playwright raises "Execution context was destroyed" when the document is replaced
    between the call and its evaluation — unavoidable on a redirect chain, and a retry
    against the new document is the correct response.
    """
    for attempt in range(attempts):
        try:
            return page.evaluate("() => document.body ? document.body.innerText : ''")
        except Exception:
            if attempt == attempts - 1:
                return ""
            page.wait_for_timeout(1_000)
    return ""


class NSMRegistrationPage:
    """The public-portal sign-in landing page and the Register As: chooser."""

    def __init__(self, page: Page):
        self.page = page
        self.register_button = page.locator('button:has-text("Register")').first
        self.signin_with_ncid_button = page.locator(
            'button:has-text("Sign In with NCID")'
        ).first
        self.individual_radio = page.locator(
            'mat-radio-button:has-text("Individual")'
        ).first
        self.business_radio = page.locator(
            'mat-radio-button:has-text("Business/Organization")'
        ).first

    def click_register_on_signin_page(self):
        wait_for_portal_ready(self.page)
        self.register_button.wait_for(state="visible", timeout=30_000)
        self.register_button.click()
        self.page.wait_for_url(re.compile(r"/register", re.I), timeout=60_000)
        self.page.wait_for_timeout(3_000)

    def _select_type(self, radio):
        radio.wait_for(state="visible", timeout=30_000)
        radio.click()
        # The form fields are rendered lazily once a type is chosen.
        self.page.locator('input[aria-label="First Name*"]').wait_for(
            state="visible", timeout=30_000
        )
        self.page.wait_for_timeout(1_000)

    def select_individual(self):
        self._select_type(self.individual_radio)

    def select_business_organization(self):
        self._select_type(self.business_radio)


class _NSMProfileForm:
    """Fields and actions shared by the Individual and Business profile forms.

    Both variants render the same address block, the same Address Suggestions
    dialog on Next, and the same Facility Participation Agreement step; only the
    identity fields above the address differ.
    """

    # The Zip input carries an empty aria-label and a randomised `name`, and its
    # "Zip*" label is a *sibling* of the field wrapper rather than an ancestor —
    # so neither `input[aria-label*=Zip]` nor `mat-form-field:has(label…)` matches.
    ZIP_INPUT = '//label[normalize-space(text())="Zip*"]/following::input[@type="text"][1]'

    def __init__(self, page: Page):
        self.page = page
        self.first_name_input = page.locator('input[aria-label="First Name*"]')
        self.last_name_input = page.locator('input[aria-label="Last Name*"]')
        self.email_input = page.locator('input[aria-label="Email Address*"]')
        self.address_input = page.locator('input[aria-label="Address*"]')
        self.zip_input = page.locator(self.ZIP_INPUT).first
        self.city_input = page.locator('input[aria-label="City*"]')
        self.state_select = page.locator('mat-select[aria-label="State*"]')
        self.phone_input = page.locator('input[type="tel"]').first

        self.next_button = page.locator('button:has-text("Next")').first
        self.save_button = page.locator('button:has-text("Save")').first
        self.agreement_checkbox = page.locator(
            'mat-checkbox:has-text("I understand and agree")'
        ).first

        self.address_dialog = page.locator("mat-dialog-container").first
        self.keep_original_button = page.locator(
            'mat-dialog-container button:has-text("Keep Original")'
        ).first

    def _fill(self, locator, value: str):
        locator.click()
        locator.fill(value)
        self.page.wait_for_timeout(300)

    def fill_first_name(self, value: str):
        self._fill(self.first_name_input, value)

    def fill_last_name(self, value: str):
        self._fill(self.last_name_input, value)

    def fill_email(self, value: str):
        self._fill(self.email_input, value)

    def fill_address(self, value: str):
        self._fill(self.address_input, value)

    def fill_zip(self, value: str):
        self._fill(self.zip_input, value)
        # ZIP lookup back-fills City and State; give it room before asserting/advancing.
        self.page.wait_for_timeout(4_000)

    def fill_phone(self, value: str):
        self._fill(self.phone_input, value)

    def city_value(self) -> str:
        return self.city_input.input_value()

    def state_value(self) -> str:
        return self.state_select.inner_text().strip()

    def click_next(self):
        self.next_button.click()
        self.page.wait_for_timeout(4_000)
        self.dismiss_address_suggestions()

    def dismiss_address_suggestions(self):
        """Clear the 'Address Suggestions' verification dialog raised by Next.

        The dialog offers a corrected-address dropdown plus Keep Original / Save.
        Keeping the entered address is the deterministic choice — the suggestion
        list varies with the address service's response.
        """
        try:
            if self.address_dialog.count() and self.address_dialog.is_visible():
                self.keep_original_button.click(timeout=10_000)
                self.page.wait_for_timeout(4_000)
        except Exception:
            # No dialog for this address — the form advanced straight to the agreement.
            pass

    def check_facility_participation_agreement(self):
        self.agreement_checkbox.wait_for(state="visible", timeout=30_000)
        self.agreement_checkbox.click()
        self.page.wait_for_timeout(1_000)

    def click_save(self):
        self.save_button.click()

    def expect_profile_registered_toast(self, timeout_ms: int = 30_000):
        """Assert the success snackbar fires after Save.

        The portal navigates away moments after the toast appears, which tears down
        the JS execution context — so poll for the text rather than leaning on a
        locator assertion that may outlive the page.
        """
        captured = _poll_for_text(self.page, PROFILE_REGISTERED_TEXT, timeout_ms)
        assert captured, (
            f"Expected toast {PROFILE_REGISTERED_TEXT!r} after Save, "
            f"but it never appeared (url={self.page.url})"
        )


class NSMIndividualRegistrationPage(_NSMProfileForm):
    """The Individual profile form — identity fields plus the shared address block."""


class NSMBusinessRegistrationPage(_NSMProfileForm):
    """The Business/Organization profile form.

    Adds company fields to the shared block. Note the phone control here is
    labelled "Company Phone Number" but, like the Individual form's, is the only
    `input[type=tel]` on the page — so the inherited locator still applies.
    """

    def __init__(self, page: Page):
        super().__init__(page)
        self.title_input = page.locator('input[aria-label="Title"]')
        self.company_name_input = page.locator('input[aria-label="Company Name*"]')
        self.location_name_input = page.locator('input[aria-label="Location Name*"]')
        self.company_email_input = page.locator(
            'input[aria-label="Company Email Address"]'
        )
        self.primary_contact_input = page.locator(
            'input[aria-label="Primary Contact Person"]'
        )

    def fill_title(self, value: str):
        self._fill(self.title_input, value)

    def fill_company_name(self, value: str):
        self._fill(self.company_name_input, value)

    def fill_location_name(self, value: str):
        self._fill(self.location_name_input, value)

    def fill_company_email(self, value: str):
        self._fill(self.company_email_input, value)

    def fill_primary_contact(self, value: str):
        self._fill(self.primary_contact_input, value)


class NCIDRegistrationPage:
    """MyNCID self-registration: Create an Account → Individual → account form."""

    def __init__(self, page: Page):
        self.page = page
        self.signin_with_ncid_button = page.locator(
            'button:has-text("Sign In with NCID")'
        ).first
        self.create_account_link = page.locator('a[title="Create an Account"]').first
        self.individual_account_radio = page.locator("#accountTypeIndividual")
        self.business_account_radio = page.locator("#accountTypeBusiness")
        self.continue_button = page.locator('button:has-text("Continue")').first
        self.register_button = page.locator("#create")

    # ── field lookup ────────────────────────────────────────────────────────
    # The signup SPA renders each field as a formio pair: a content block holding
    # `<p>* <strong>Label</strong></p>` followed by the input. The inputs themselves
    # have no aria-label, no placeholder and only volatile `mat-input-N` ids, so the
    # label text is the only stable handle.
    def _field(self, label: str):
        return self.page.locator(
            f'//strong[normalize-space(text())="{label}"]/following::input[1]'
        ).first

    def _fill_field(self, label: str, value: str):
        loc = self._field(label)
        loc.wait_for(state="visible", timeout=30_000)
        loc.click()
        loc.fill(value)
        self.page.wait_for_timeout(500)

    # ── navigation ──────────────────────────────────────────────────────────
    def click_register_now(self):
        """Reach MyNCID's account-creation wizard from the portal sign-in page.

        The portal has no direct 'Register Now' control: the route is
        Sign In with NCID → (Ping login) → Create an Account.
        """
        wait_for_portal_ready(self.page)
        self.signin_with_ncid_button.wait_for(state="visible", timeout=30_000)
        self.signin_with_ncid_button.click()
        self.page.wait_for_url(re.compile(r"myncidpp|myncid", re.I), timeout=60_000)
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(3_000)

        self.create_account_link.wait_for(state="visible", timeout=30_000)
        self.create_account_link.click()
        self.page.wait_for_url(re.compile(r"NewUserRegistration", re.I), timeout=60_000)
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(3_000)

    def _select_account_type(self, radio):
        radio.wait_for(state="visible", timeout=30_000)
        radio.click()
        self.page.wait_for_timeout(500)
        self.continue_button.click()

        # Step 2 hands off to a separate Angular SPA on myncidpp.nc.gov; wait for a
        # real field rather than a URL, since the route rewrites itself twice.
        self._field("First Name").wait_for(state="visible", timeout=90_000)
        self.page.wait_for_timeout(1_000)

    def select_individual_account_type(self):
        """Pick the Individual account-type card and advance to the account form."""
        self._select_account_type(self.individual_account_radio)

    def select_business_account_type(self):
        """Pick the Business account-type card and advance to the account form.

        The resulting form is identical to the Individual one (same six fields,
        same REGISTER button) — only `container.usertype` in the route differs.
        """
        self._select_account_type(self.business_account_radio)

    # ── form fields ─────────────────────────────────────────────────────────
    def fill_first_name(self, value: str):
        self._fill_field("First Name", value)

    def fill_last_name(self, value: str):
        self._fill_field("Last Name", value)

    def fill_username(self, value: str):
        self._fill_field("Username", value)

    def fill_email(self, value: str):
        self._fill_field("Personal Email Address", value)

    def fill_mobile_number(self, value: str):
        self._fill_field("Mobile Number", value)

    def fill_password(self, value: str):
        self._fill_field("Password", value)

    def fill_confirm_password(self, value: str):
        """Fill the 'Confirm Password' field when the form renders one.

        The signup SPA was originally documented as single-password, but the
        QA/UAT MyNCID form now shows a required '* Confirm Password'. Match it
        loosely (label casing/wording varies) and treat it as optional so the
        helper still works if an environment drops it again.
        """
        loc = self.page.locator(
            '//strong[contains(normalize-space(.), "Confirm") and '
            'contains(normalize-space(.), "assword")]/following::input[1]'
        ).first
        try:
            loc.wait_for(state="visible", timeout=8_000)
        except Exception:
            print("[NCIDRegistrationPage] no Confirm Password field — skipping")
            return
        loc.click()
        loc.fill(value)
        self.page.wait_for_timeout(500)

    def click_register(self):
        self.register_button.wait_for(state="visible", timeout=30_000)
        self.register_button.click()

    def expect_registration_successful(self, timeout_ms: int = 60_000):
        """Assert MyNCID confirms the account was created and a link was emailed."""
        captured = _poll_for_text(self.page, NCID_REGISTERED_TEXT, timeout_ms)
        assert captured, (
            f"Expected one of {NCID_REGISTERED_TEXT!r} after REGISTER, but the page showed:\n"
            f"{self.page.evaluate('() => document.body ? document.body.innerText : \"\"')[:800]}"
        )


class NCIDLoginPage:
    """MyNCID Ping sign-on — a username screen, then a password screen."""

    def __init__(self, page: Page):
        self.page = page
        self.signin_with_ncid_button = page.locator(
            '//*[text()="Sign In with NCID"]'
        ).first
        self.username_input = page.locator("#identifierInput")
        # Screen 1 submits with #signInButton (title "Sign In"); screen 2 submits with
        # #signOnButton (title "Sign On", but labelled "Sign In"). They are distinct
        # controls on distinct pages — a single title selector cannot cover both.
        self.username_submit = page.locator("#signInButton")
        self.password_input = page.locator("#password")
        self.password_submit = page.locator("#signOnButton")

    def start_from_portal(self):
        wait_for_portal_ready(self.page)
        self.signin_with_ncid_button.wait_for(state="visible", timeout=30_000)
        self.signin_with_ncid_button.click()
        self.page.wait_for_url(re.compile(r"myncidpp|myncid", re.I), timeout=60_000)
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(2_000)

    def sign_in(self, username: str, password: str):
        self.username_input.wait_for(state="visible", timeout=30_000)
        self.username_input.fill(username)
        self.page.wait_for_timeout(500)
        self.username_submit.click()

        self.password_input.wait_for(state="visible", timeout=60_000)
        self.password_input.fill(password)
        self.page.wait_for_timeout(500)
        self.password_submit.click()
        self.page.wait_for_load_state("domcontentloaded")
        self.page.wait_for_timeout(3_000)


# ── helpers ──────────────────────────────────────────────────────────────────

def _poll_for_text(page: Page, needle, timeout_ms: int) -> bool:
    """Poll body text + snackbar/dialog containers for `needle`.

    `needle` is a string or an iterable of strings; the poll succeeds as soon as
    ANY of them appears (case-insensitive substring match).

    Tolerates the execution context being destroyed mid-poll (these flows navigate
    right after showing their confirmation).
    """
    needles = [needle.lower()] if isinstance(needle, str) else [n.lower() for n in needle]
    waited = 0
    step = 500
    while waited < timeout_ms:
        try:
            found = page.evaluate(
                """(needles) => {
                    const hay = [];
                    if (document.body) hay.push(document.body.innerText);
                    document.querySelectorAll(
                        'simple-snack-bar, mat-snack-bar-container, [class*="snack"], '
                        + '[class*="toast"], mat-dialog-container'
                    ).forEach(e => hay.push(e.innerText || ''));
                    const text = hay.join('\\n').toLowerCase();
                    return needles.some(n => text.includes(n));
                }""",
                needles,
            )
            if found:
                return True
        except Exception:
            # Navigation destroyed the context — keep polling against the new document.
            pass
        page.wait_for_timeout(step)
        waited += step
    return False


def expect_ncid_account_activated(page: Page, timeout_ms: int = 60_000):
    """Assert the emailed activation link landed on MyNCID's success screen."""
    assert _poll_for_text(page, NCID_ACTIVATED_TEXT, timeout_ms), (
        f"Expected {NCID_ACTIVATED_TEXT!r} on the activation page (url={page.url})"
    )
