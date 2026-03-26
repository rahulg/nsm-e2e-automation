from playwright.sync_api import Page


def fill_input(page: Page, selector: str, value: str):
    page.locator(selector).first.fill(value)


def select_option(page: Page, selector: str, option_label: str):
    page.locator(selector).first.select_option(label=option_label)


def check_all_checkboxes(page: Page, parent_selector: str = None):
    scope = page.locator(parent_selector) if parent_selector else page
    checkboxes = scope.locator('input[type="checkbox"]')
    count = checkboxes.count()
    for i in range(count):
        checkbox = checkboxes.nth(i)
        if not checkbox.is_checked():
            checkbox.check()


def upload_file(page: Page, file_paths: list, selector: str = None):
    file_input = page.locator(selector or 'input[type="file"]').first
    file_input.set_input_files(file_paths)


def click_submit(page: Page, button_text: str = "Submit"):
    page.locator(f'button:has-text("{button_text}"), button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")


def wait_for_success_message(page: Page):
    page.locator('[class*="success" i], [class*="toast" i]:has-text("success"), text=/success/i').first.wait_for(state="visible", timeout=15_000)


def dismiss_modal(page: Page):
    close_button = page.locator('[class*="modal" i] button:has-text("Close"), [class*="modal" i] [class*="close" i], [role="dialog"] button:has-text("Close")').first
    if close_button.is_visible():
        close_button.click()


def fill_date_input(page: Page, selector: str, date: str):
    page.locator(selector).first.fill(date)


def wait_for_table_to_load(page: Page, table_selector: str = None):
    page.locator(table_selector or "table tbody tr").first.wait_for(state="visible", timeout=15_000)
