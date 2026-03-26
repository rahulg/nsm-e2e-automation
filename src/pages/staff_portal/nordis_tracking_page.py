import re
import time
from playwright.sync_api import Page, expect


class NordisTrackingPage:
    def __init__(self, page: Page):
        self.page = page
        self.tracking_table = page.locator(
            "table.mat-table, mat-table, table, [class*='tracking' i], "
            "[class*='nordis' i], [class*='delivery' i]"
        ).first
        self.tracking_rows = page.locator(
            "table.mat-table tr.mat-row, mat-row, table tbody tr, "
            "[class*='tracking-row'], [class*='delivery-row']"
        )

    def expect_tracking_visible(self):
        """Verify the tracking section/table is visible.

        The TRACK LT-264 tab may display tracking info as a table or as a card/list.
        """
        try:
            expect(self.tracking_table).to_be_visible(timeout=15_000)
        except Exception:
            # Fallback: look for any tracking-related text content
            tracking_text = self.page.get_by_text(
                re.compile(r"Track|Nordis|Delivery|Mail|Status|Recipient", re.I)
            ).first
            expect(tracking_text).to_be_visible(timeout=10_000)

    def expect_all_delivered(self):
        count = self.tracking_rows.count()
        for i in range(count):
            row = self.tracking_rows.nth(i)
            expect(row).to_contain_text(re.compile(r"delivered", re.I))

    def get_tracking_count(self) -> int:
        return self.tracking_rows.count()

    # ===== E2E-001 ENHANCED METHODS =====

    def verify_tracking_details_visible(self):
        """Verify tracking details are visible — table with rows or tracking info section."""
        self.expect_tracking_visible()
        count = self.get_tracking_count()
        if count == 0:
            # If no table rows found, verify tracking info is shown in some format
            tracking_info = self.page.get_by_text(
                re.compile(r"Recipient|Address|Status|Delivered|In Transit|Mailed", re.I)
            ).first
            expect(tracking_info).to_be_visible(timeout=10_000)

    def wait_for_all_delivered(self, max_wait_ms: int = 300_000, poll_interval_ms: int = 10_000):
        """Poll/refresh until all tracking rows show 'Delivered'."""
        start_time = time.time()
        max_wait_s = max_wait_ms / 1000
        poll_interval_s = poll_interval_ms / 1000

        while (time.time() - start_time) < max_wait_s:
            try:
                count = self.tracking_rows.count()
                if count == 0:
                    self.page.reload()
                    self.page.wait_for_load_state("networkidle")
                    self.page.wait_for_timeout(int(poll_interval_ms))
                    continue

                all_delivered = True
                for i in range(count):
                    row_text = self.tracking_rows.nth(i).text_content() or ""
                    if not re.search(r"delivered", row_text, re.I):
                        all_delivered = False
                        break

                if all_delivered:
                    return  # Success
            except Exception:
                pass

            self.page.reload()
            self.page.wait_for_load_state("networkidle")
            self.page.wait_for_timeout(int(poll_interval_ms))

        # Final assertion — will fail with meaningful error
        self.expect_all_delivered()
