"""
Generate a styled HTML test report from pytest JSON output.

Usage:
  pytest --json-report --json-report-file=results.json ...
  python scripts/generate_report.py results.json report.html
"""

import json
import sys
from datetime import datetime, timezone


def generate_report(json_path: str, html_path: str):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Extract stats
    summary = data.get("summary", {})
    total = summary.get("total", 0)
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("deselected", 0) + summary.get("xfailed", 0) + summary.get("skipped", 0)
    error = summary.get("error", 0)
    duration = summary.get("duration", 0)

    # Determine overall status
    if failed > 0 or error > 0:
        overall = "fail"
        banner_icon = "&#x274C;"
        banner_text = f"{failed + error} TEST(S) FAILED"
        banner_sub = f"{passed} passed, {skipped} skipped in {duration:.1f}s"
    else:
        overall = "pass"
        banner_icon = "&#x2705;"
        banner_text = "ALL TESTS PASSED"
        banner_sub = f"{passed} passed, {skipped} skipped in {duration:.1f}s"

    run_date = datetime.now(timezone.utc).strftime("%B %d, %Y at %I:%M %p UTC")
    duration_fmt = f"{int(duration // 60)}m {int(duration % 60)}s"

    # Build test rows
    tests = data.get("tests", [])
    rows_html = ""
    for i, test in enumerate(tests, 1):
        nodeid = test.get("nodeid", "")
        outcome = test.get("outcome", "unknown")
        test_duration = test.get("duration", 0)

        # Parse test name from nodeid
        parts = nodeid.split("::")
        test_class = parts[1] if len(parts) > 1 else ""
        test_name = parts[-1] if len(parts) > 0 else nodeid

        # Format name nicely
        display_name = test_name.replace("test_", "").replace("_", " ").title()

        # Badge class
        if outcome == "passed":
            badge_cls = "pass"
            badge_text = "PASS"
        elif outcome == "failed":
            badge_cls = "fail"
            badge_text = "FAIL"
        elif outcome == "skipped":
            badge_cls = "warn"
            badge_text = "SKIP"
        else:
            badge_cls = "warn"
            badge_text = outcome.upper()

        row_cls = ' class="red-row"' if outcome == "failed" else ""

        # Error message
        error_html = ""
        call_info = test.get("call", {})
        if call_info.get("longrepr"):
            error_msg = call_info["longrepr"]
            # Truncate very long errors
            if len(error_msg) > 500:
                error_msg = error_msg[:500] + "..."
            error_html = f'<details class="error-toggle"><summary class="toggle-btn has-issues">View Error</summary><div class="error-box"><pre>{_escape(error_msg)}</pre></div></details>'

        rows_html += f"""
        <tr{row_cls}>
          <td class="num">{i}</td>
          <td><strong>{_escape(display_name)}</strong>{error_html}</td>
          <td><code>{_escape(test_class)}</code></td>
          <td class="num">{test_duration:.1f}s</td>
          <td><span class="badge {badge_cls}">{badge_text}</span></td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSM E2E Test Report — QA</title>
<style>
  :root {{
    --green: #16a34a; --green-bg: #f0fdf4; --green-border: #bbf7d0;
    --red: #dc2626; --red-bg: #fef2f2; --red-border: #fecaca;
    --orange: #d97706; --orange-bg: #fffbeb;
    --blue: #2563eb; --blue-bg: #eff6ff;
    --gray-50: #f9fafb; --gray-100: #f3f4f6; --gray-200: #e5e7eb;
    --gray-300: #d1d5db; --gray-500: #6b7280; --gray-700: #374151; --gray-900: #111827;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: var(--gray-900); background: var(--gray-50); line-height: 1.6; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px; }}

  .header {{ background: linear-gradient(135deg, #1e293b 0%, #334155 100%); color: white; padding: 40px 32px; border-radius: 16px; margin-bottom: 32px; }}
  .header h1 {{ font-size: 28px; font-weight: 700; margin-bottom: 4px; }}
  .header .subtitle {{ font-size: 15px; color: #94a3b8; margin-bottom: 24px; }}
  .header-meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }}
  .meta-item {{ font-size: 13px; }}
  .meta-item .label {{ color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; font-size: 11px; font-weight: 600; }}
  .meta-item .value {{ color: white; font-weight: 500; margin-top: 2px; }}

  .summary-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }}
  .summary-card {{ background: white; border-radius: 12px; padding: 20px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid var(--gray-200); }}
  .summary-card .number {{ font-size: 36px; font-weight: 700; line-height: 1; }}
  .summary-card .label {{ font-size: 13px; color: var(--gray-500); margin-top: 4px; font-weight: 500; }}
  .summary-card.pass {{ border-top: 4px solid var(--green); }} .summary-card.pass .number {{ color: var(--green); }}
  .summary-card.fail {{ border-top: 4px solid var(--red); }} .summary-card.fail .number {{ color: var(--red); }}
  .summary-card.warn {{ border-top: 4px solid var(--orange); }} .summary-card.warn .number {{ color: var(--orange); }}
  .summary-card.total {{ border-top: 4px solid var(--gray-700); }} .summary-card.total .number {{ color: var(--gray-700); }}

  .result-banner {{ border-radius: 12px; padding: 16px 24px; margin-bottom: 32px; display: flex; align-items: center; gap: 12px; }}
  .result-banner.pass {{ background: var(--green-bg); border: 1px solid var(--green-border); }}
  .result-banner.pass .text {{ color: var(--green); }}
  .result-banner.fail {{ background: var(--red-bg); border: 1px solid var(--red-border); }}
  .result-banner.fail .text {{ color: var(--red); }}
  .result-banner .icon {{ font-size: 28px; }}
  .result-banner .text {{ font-size: 16px; font-weight: 600; }}
  .result-banner .subtext {{ font-size: 13px; color: var(--gray-500); font-weight: 400; }}

  .section {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border: 1px solid var(--gray-200); overflow: hidden; margin-bottom: 32px; }}
  .section-title {{ padding: 20px 24px 16px; font-size: 18px; font-weight: 600; border-bottom: 1px solid var(--gray-200); }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead {{ background: var(--gray-50); }}
  th {{ text-align: left; padding: 10px 16px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--gray-500); font-weight: 600; }}
  td {{ padding: 12px 16px; font-size: 14px; border-top: 1px solid var(--gray-100); }}
  tr:hover td {{ background: var(--gray-50); }}
  .red-row td {{ background: var(--red-bg); }}
  td.num {{ text-align: center; color: var(--gray-500); font-size: 13px; }}
  code {{ font-size: 12px; background: var(--gray-100); padding: 2px 6px; border-radius: 4px; word-break: break-all; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600; }}
  .badge.pass {{ background: var(--green-bg); color: var(--green); }}
  .badge.fail {{ background: var(--red-bg); color: var(--red); }}
  .badge.warn {{ background: var(--orange-bg); color: var(--orange); }}

  .error-box {{ background: var(--red-bg); border: 1px solid var(--red-border); border-radius: 8px; padding: 12px 16px; margin-top: 8px; font-size: 12px; color: var(--red); overflow-x: auto; }}
  .error-box pre {{ white-space: pre-wrap; word-break: break-word; font-family: monospace; margin: 0; }}
  .error-toggle {{ margin-top: 6px; }}
  .toggle-btn {{ cursor: pointer; list-style: none; display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; color: var(--gray-700); background: var(--gray-100); border: 1px solid var(--gray-200); }}
  .toggle-btn:hover {{ background: var(--gray-200); }}
  .toggle-btn.has-issues {{ background: var(--red-bg); border-color: var(--red-border); color: var(--red); }}

  .footer {{ text-align: center; padding: 24px; font-size: 12px; color: var(--gray-500); }}
  @media (max-width: 640px) {{ .summary-row {{ grid-template-columns: repeat(2, 1fr); }} .header-meta {{ grid-template-columns: 1fr; }} .container {{ padding: 16px; }} }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>NSM E2E Test Report — QA</h1>
    <div class="subtitle">Automated end-to-end test results for NCDOT Notice & Storage Management</div>
    <div class="header-meta">
      <div class="meta-item"><div class="label">Run Date</div><div class="value">{run_date}</div></div>
      <div class="meta-item"><div class="label">Environment</div><div class="value">QA</div></div>
      <div class="meta-item"><div class="label">Duration</div><div class="value">{duration_fmt}</div></div>
      <div class="meta-item"><div class="label">Tests Collected</div><div class="value">{total}</div></div>
    </div>
  </div>

  <div class="summary-row">
    <div class="summary-card pass"><div class="number">{passed}</div><div class="label">Passed</div></div>
    <div class="summary-card fail"><div class="number">{failed}</div><div class="label">Failed</div></div>
    <div class="summary-card warn"><div class="number">{skipped}</div><div class="label">Skipped</div></div>
    <div class="summary-card total"><div class="number">{total}</div><div class="label">Total</div></div>
  </div>

  <div class="result-banner {overall}">
    <div class="icon">{banner_icon}</div>
    <div>
      <div class="text">{banner_text}</div>
      <div class="subtext">{banner_sub}</div>
    </div>
  </div>

  <div class="section">
    <h2 class="section-title">Test Results</h2>
    <table>
      <thead><tr><th>#</th><th>Test</th><th>Class</th><th>Duration</th><th>Status</th></tr></thead>
      <tbody>{rows_html}
      </tbody>
    </table>
  </div>

  <div class="footer">
    Generated by NSM E2E Automation &middot; {run_date}
  </div>

</div>
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[report] Generated {html_path} — {passed} passed, {failed} failed, {skipped} skipped")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/generate_report.py <results.json> <report.html>")
        sys.exit(1)
    generate_report(sys.argv[1], sys.argv[2])
