"""
Public Portal Vehicle Reclaim Page — for when vehicle owner reclaims vehicle mid-process.

The Vehicle Reclaim flow allows a requestor to initiate return of the vehicle
to its owner. The owner pays the pending amount, and the file is closed.
"""

import re
from playwright.sync_api import Page, expect


class VehicleReclaimPage:
    def __init__(self, page: Page):
        self.page = page

        # Reclaim button on application detail — try multiple text patterns
        self.vehicle_reclaim_button = page.locator(
            'button:has-text("Vehicle Reclaim"), button:has-text("Reclaim Vehicle"), '
            'button:has-text("Reclaim"), a:has-text("Vehicle Reclaim"), '
            'a:has-text("Reclaim"), button:has-text("Owner Reclaim"), '
            'button:has-text("Withdraw"), button:has-text("Cancel Application"), '
            'button:has-text("Cancel Request"), button:has-text("Close")'
        ).first

        # Pending amount display
        self.pending_amount = page.locator(
            '[class*="pending" i], [class*="amount" i], [class*="balance" i]'
        ).first

        # Payment / confirm buttons
        self.pay_button = page.locator(
            'button:has-text("Pay"), button:has-text("Confirm Payment")'
        ).first
        self.confirm_reclaim_button = page.locator(
            'button:has-text("Confirm"), button:has-text("Confirm Reclaim"), '
            'button:has-text("Submit")'
        ).first

    def open_vehicle_reclaimed_download(self):
        """Hover over the 3-dot menu on the application list row, then click
        'Vehicle Reclaimed' from the dropdown."""
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(1000)

        # Hover over the 3-dot menu div to reveal the dropdown options
        three_dot = self.page.locator(
            "//div[@class='_disable-hammer-styles flex flex-col items-center justify-around "
            "exp-gap-0px ng-star-inserted px2 pt2 pb1 three-dot-menu']"
        ).first
        three_dot.wait_for(state="visible", timeout=10_000)
        three_dot.hover()
        self.page.wait_for_timeout(800)

        # Click "Vehicle Reclaimed" from the revealed dropdown
        menu_item = self.page.locator(
            '[role="menuitem"]:has-text("Vehicle Reclaimed"), '
            '.mat-menu-item:has-text("Vehicle Reclaimed"), '
            'button:has-text("Vehicle Reclaimed"), '
            'span:has-text("Vehicle Reclaimed")'
        ).first
        menu_item.wait_for(state="visible", timeout=10_000)
        menu_item.click()
        self.page.wait_for_timeout(1000)

    def enter_reclaim_comments(self, comment: str):
        """Enter comments in the Vehicle Reclaim modal."""
        comment_input = self.page.locator(
            'mat-dialog-container textarea, mat-dialog-container input[type="text"], '
            'mat-dialog-container input[placeholder*="comment" i], '
            'mat-dialog-container textarea[placeholder*="comment" i]'
        ).first
        comment_input.wait_for(state="visible", timeout=10_000)
        comment_input.fill(comment)
        self.page.wait_for_timeout(500)

    def click_vehicle_reclaimed_btn(self):
        """Click the 'Vehicle Reclaimed' button in the reclaim modal."""
        reclaimed_btn = self.page.locator(
            'mat-dialog-container button:has-text("Vehicle Reclaimed")'
        ).first
        reclaimed_btn.wait_for(state="visible", timeout=10_000)
        reclaimed_btn.click()
        self.page.wait_for_load_state("networkidle")
        self.page.wait_for_timeout(2000)
