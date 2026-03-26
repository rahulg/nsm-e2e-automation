"""
Post E2E test results to Slack via the Expertly automation chain API.

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


def expertly_login(username: str, password: str) -> str:
    """Authenticate with Expertly (FusionAuth) and return JWT token."""
    login_urls = [
        f"{EXPERTLY_BASE}/api/login",
        f"{EXPERTLY_BASE}/rest/api/auth/login",
        f"{EXPERTLY_BASE}/rest/api/user/login",
    ]

    payload = json.dumps({
        "loginId": username,
        "password": password,
    }).encode("utf-8")

    for url in login_urls:
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                token = (
                    data.get("token")
                    or data.get("accessToken")
                    or data.get("data", {}).get("token")
                )
                if token:
                    print(f"[expertly] Login succeeded via {url}")
                    return token
        except urllib.error.HTTPError as e:
            print(f"[expertly] {url} returned {e.code}, trying next...")
        except Exception as e:
            print(f"[expertly] {url} failed: {e}, trying next...")

    print("[expertly] ERROR: All login endpoints failed", file=sys.stderr)
    sys.exit(1)


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
        body = e.read().decode("utf-8", errors="replace")
        print(f"[slack] ERROR: {e.code} - {body[:500]}", file=sys.stderr)
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

    print(f"[notify] Logging into Expertly...")
    token = expertly_login(username, password)

    print(f"[notify] Posting to Slack #{SLACK_CHANNEL}...")
    post_slack_message(token, message)

    print("[notify] Done.")


if __name__ == "__main__":
    main()
