"""
Post E2E test results to Slack via the Expertly automation chain API.

Uses Playwright headless to login and extract JWT token, then calls
the automation chain endpoint to post a Slack message.

Environment variables:
  EXPERTLY_USERNAME, EXPERTLY_PASSWORD  - Expertly login credentials
  SLACK_BOT_TOKEN                       - Slack bot token
  TEST_SUMMARY                          - One-line pytest summary
  TEST_SCOPE                            - "core", "full", or "smoke"
  REPO_NAME                             - GitHub repository (owner/repo)
"""

import os
import sys
import json
import urllib.request
import urllib.error

EXPERTLY_BASE = "https://demo.expertly.cloud"
CHAIN_ID = "46b4336ff4bd42574c3083babd9cd903"
CHAIN_URL = f"{EXPERTLY_BASE}/rest/api/automation/chain/test/execute/{CHAIN_ID}?outputMode=ALL"
SLACK_CHANNEL = "test_dashboard"
LOGIN_URL = f"{EXPERTLY_BASE}/pages/admin-ai/accounts/list"


def expertly_login_via_browser(username: str, password: str) -> str:
    """Login to Expertly via headless browser and extract JWT from localStorage."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print(f"[expertly] Navigating to login page...")
        page.goto(LOGIN_URL, timeout=60_000)
        page.wait_for_load_state("networkidle")

        # Fill login form
        print(f"[expertly] Filling login credentials...")
        email_input = page.locator('input#loginId')
        email_input.wait_for(state="visible", timeout=15_000)
        email_input.fill(username)

        password_input = page.locator('input#password-box-id')
        password_input.fill(password)

        # Click login button
        login_button = page.locator('button:has-text("Log In")').first
        login_button.click()

        # Wait for redirect after login
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.wait_for_timeout(3000)

        # Extract token from localStorage or cookies
        token = page.evaluate("""() => {
            // Try common localStorage keys for auth tokens
            const keys = ['authToken', 'access_token', 'token', 'jwt', 'auth_token'];
            for (const key of keys) {
                const val = localStorage.getItem(key);
                if (val) return val;
            }
            // Try all keys that look like tokens
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                const val = localStorage.getItem(key);
                if (val && val.startsWith('eyJ')) return val;
            }
            return null;
        }""")

        if not token:
            # Try extracting from cookies
            cookies = context.cookies()
            for cookie in cookies:
                if cookie["value"].startswith("eyJ"):
                    token = cookie["value"]
                    break

        browser.close()

        if not token:
            print("[expertly] ERROR: Could not extract auth token after login", file=sys.stderr)
            sys.exit(1)

        print(f"[expertly] Login succeeded, token extracted")
        return token


def post_slack_message(token: str, message: str):
    """Post message to Slack via Expertly automation chain."""
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")

    input_request = json.dumps({
        "methodInputs": {
            "token": slack_token,
            "channel": SLACK_CHANNEL,
            "message": message,
        },
        "assertions": [],
    })

    # Build multipart form-data body
    boundary = "----FormBoundaryNSME2E"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="inputRequest"\r\n\r\n'
        f"{input_request}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = urllib.request.Request(
        CHAIN_URL,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "expertly-auth-token": token,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            print(f"[slack] Notification sent successfully")
            print(f"[slack] Response: {json.dumps(result, indent=2)[:500]}")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[slack] ERROR: {e.code} - {err_body[:500]}", file=sys.stderr)
        sys.exit(1)


def main():
    username = os.environ.get("EXPERTLY_USERNAME", "")
    password = os.environ.get("EXPERTLY_PASSWORD", "")
    summary = os.environ.get("TEST_SUMMARY", "No summary available")
    scope = os.environ.get("TEST_SCOPE", "unknown")
    repo = os.environ.get("REPO_NAME", "RG9887/nsm-e2e-automation")

    owner = repo.split("/")[0].lower() if "/" in repo else "rg9887"
    repo_name = repo.split("/")[-1]
    report_url = f"https://{owner}.github.io/{repo_name}/report.html"

    if not username or not password:
        print("[expertly] EXPERTLY_USERNAME/PASSWORD not set, skipping Slack notification")
        return

    message = (
        f"Hello, \n"
        f"Please find the automation test run report below for QA - NSM ({scope} tests)\n"
        f"Summary: {summary}\n"
        f":- {report_url}"
    )

    print(f"[notify] Logging into Expertly via browser...")
    token = expertly_login_via_browser(username, password)

    print(f"[notify] Posting to Slack #{SLACK_CHANNEL}...")
    post_slack_message(token, message)

    print("[notify] Done.")


if __name__ == "__main__":
    main()
