"""
NSM E2E Automation Runner
=========================
A thin wrapper around pytest that handles env selection, marker filtering,
auth refresh, report generation, and archiving in one command.

Usage:
  python run_tests.py [options]

Quick examples:
  python run_tests.py                            # Full regression, QA
  python run_tests.py --env stage                # Full regression, STAGE
  python run_tests.py --tags core                # Core tests only (E2E-001..006)
  python run_tests.py --tags fixed               # All stabilised tests
  python run_tests.py --tags "core or smoke"     # Combined marker expression
  python run_tests.py --tags "e2e and not nordis"
  python run_tests.py --test test_e2e_001        # Single test by ID fragment
  python run_tests.py --test tests/test_e2e_001_standard_vehicle_lifecycle.py
  python run_tests.py --headed --tags core       # Visible browser
  python run_tests.py --refresh-auth             # Force auth refresh then run
  python run_tests.py --no-auth-refresh          # Skip auth check entirely
  python run_tests.py --list-tags                # Show all markers
  python run_tests.py --dry-run --tags core      # Preview command, don't run
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
SCRIPTS_DIR = ROOT / "scripts"
AUTH_DIR = ROOT / "auth"

# Auth files are considered stale after this many hours
AUTH_MAX_AGE_HOURS = 8

AUTH_FILES = [
    "public-portal.json",
    "public-portal-user-b.json",
    "staff-portal.json",
    "lsa-portal.json",
    "fiscal-portal.json",
    "individual-portal.json",
]

AVAILABLE_TAGS = {
    "e2e":         "All E2E cross-portal tests (54 tests)",
    "core":        "Core workflow tests - E2E-001 to E2E-006",
    "alternate":   "Alternate / exception flows - E2E-007 to E2E-012",
    "multiuser":   "Multi-user and role-based - E2E-013 to E2E-016",
    "edge":        "Edge case tests - E2E-017+",
    "fixed":       "Stabilised tests (previously failing, now passing)",
    "smoke":       "Quick smoke subset",
    "critical":    "Critical priority",
    "high":        "High priority",
    "medium":      "Medium priority",
    "payment":     "Payment-related tests",
    "paper_form":  "Paper form workflow tests",
    "nordis":      "Nordis mailing integration tests",
    "report":      "Report generation tests",
    "performance": "Performance threshold tests",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NSM E2E Automation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # --- Environment ---
    parser.add_argument(
        "--env",
        choices=["qa", "stage"],
        default="qa",
        metavar="ENV",
        help="Target environment: qa | stage  (default: qa)",
    )

    # --- Test selection ---
    sel = parser.add_argument_group("Test selection")
    sel.add_argument(
        "--tags", "-m",
        metavar="EXPR",
        help='Pytest marker expression, e.g. "core", "fixed", "core or smoke"',
    )
    sel.add_argument(
        "--test", "-k",
        metavar="TEST",
        help=(
            "Run a specific test. Pass a file path "
            '(tests/test_e2e_001_*.py) or a keyword fragment ("test_e2e_001"). '
            "File paths are passed as positional args; keywords use -k."
        ),
    )

    # --- Browser ---
    br = parser.add_argument_group("Browser")
    br.add_argument(
        "--headed",
        action="store_true",
        help="Run with a visible browser window (default: headless)",
    )
    br.add_argument(
        "--browser",
        choices=["chromium", "firefox", "webkit"],
        default="chromium",
        help="Browser engine (default: chromium)",
    )
    br.add_argument(
        "--slowmo",
        type=int,
        default=0,
        metavar="MS",
        help="Slow each browser action by N ms — useful with --headed for debugging",
    )

    # --- Output ---
    out = parser.add_argument_group("Output")
    out.add_argument(
        "--output-dir",
        default=str(RESULTS_DIR),
        metavar="DIR",
        help="Directory for results.json / report.html  (default: results/)",
    )
    out.add_argument(
        "--no-archive",
        action="store_true",
        help="Skip archiving this run (overwrite latest files only)",
    )
    out.add_argument(
        "--open",
        action="store_true",
        help="Open the HTML report in the default browser after the run",
    )

    # --- Auth ---
    auth = parser.add_argument_group("Auth refresh")
    auth_excl = auth.add_mutually_exclusive_group()
    auth_excl.add_argument(
        "--refresh-auth",
        action="store_true",
        help="Force a full auth refresh before running tests, regardless of age",
    )
    auth_excl.add_argument(
        "--no-auth-refresh",
        action="store_true",
        help=(
            "Skip auth freshness check entirely "
            "(use when you manage auth separately or are iterating quickly)"
        ),
    )
    auth.add_argument(
        "--auth-max-age",
        type=int,
        default=AUTH_MAX_AGE_HOURS,
        metavar="HOURS",
        help=f"Auto-refresh threshold in hours (default: {AUTH_MAX_AGE_HOURS})",
    )

    # --- Misc ---
    parser.add_argument(
        "--list-tags",
        action="store_true",
        help="Print all available markers with descriptions and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the pytest command that would be run, then exit",
    )
    parser.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help=(
            "Extra flags forwarded verbatim to pytest. "
            'Separate with -- to avoid ambiguity, e.g.  -- --tb=long -x'
        ),
    )

    return parser.parse_args()


def list_tags() -> None:
    print("\nAvailable test markers\n" + "=" * 40)
    width = max(len(k) for k in AVAILABLE_TAGS) + 2
    for tag, desc in AVAILABLE_TAGS.items():
        print(f"  {tag:<{width}}  {desc}")
    print(
        "\nMarker expressions (passed to --tags):\n"
        "  --tags core\n"
        '  --tags "core or smoke"\n'
        '  --tags "e2e and not nordis"\n'
        '  --tags "fixed and not performance"\n'
    )


def build_pytest_cmd(args: argparse.Namespace, json_path: Path) -> list:
    cmd = [sys.executable, "-m", "pytest"]

    # Environment (conftest.py reads --env)
    cmd += ["--env", args.env]

    # Browser
    cmd += [f"--browser={args.browser}"]
    if args.headed:
        cmd.append("--headed")
    if args.slowmo:
        cmd.append(f"--slowmo={args.slowmo}")

    # Marker filter
    if args.tags:
        cmd += ["-m", args.tags]

    # Test target
    if args.test:
        val = args.test
        is_path = (os.sep in val or "/" in val or val.endswith(".py"))
        if is_path:
            p = Path(val)
            if not p.is_absolute():
                p = ROOT / p
            cmd.append(str(p))
        else:
            cmd += ["-k", val]

    # JSON report (consumed by generate_report.py)
    cmd += ["--json-report", f"--json-report-file={json_path}"]

    # Extra passthrough args
    extra = args.extra or []
    if extra and extra[0] == "--":
        extra = extra[1:]
    cmd.extend(extra)

    return cmd


def generate_html_report(json_path: Path, html_path: Path, env: str) -> None:
    gen = SCRIPTS_DIR / "generate_report.py"
    env_vars = {**os.environ, "NSM_ENV": env}
    result = subprocess.run(
        [sys.executable, str(gen), str(json_path), str(html_path)],
        env=env_vars,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr:
        print(f"[warn] Report generation: {result.stderr.strip()}", file=sys.stderr)


def _tag_slug(args: argparse.Namespace) -> str:
    if args.test:
        stem = Path(args.test).stem if args.test.endswith(".py") else args.test
        return f"single-{stem[:40]}"
    if args.tags:
        return args.tags.replace(" ", "-").replace('"', "").replace("'", "")[:40]
    return "all"


def _auth_status(env: str, max_age_hours: int) -> tuple[bool, str]:
    """Return (needs_refresh, human_readable_reason).

    Checks every expected auth JSON for the target env. Triggers refresh if:
    - any file is missing, or
    - any file is older than max_age_hours.
    """
    env_auth_dir = AUTH_DIR / env
    now = time.time()
    max_age_secs = max_age_hours * 3600

    missing = []
    oldest_age_secs = 0
    oldest_file = ""

    for fname in AUTH_FILES:
        fpath = env_auth_dir / fname
        if not fpath.exists():
            missing.append(fname)
            continue
        age = now - fpath.stat().st_mtime
        if age > oldest_age_secs:
            oldest_age_secs = age
            oldest_file = fname

    if missing:
        return True, f"missing files: {', '.join(missing)}"

    if oldest_age_secs > max_age_secs:
        h = int(oldest_age_secs // 3600)
        m = int((oldest_age_secs % 3600) // 60)
        return True, f"oldest token is {h}h {m}m old (threshold {max_age_hours}h) [{oldest_file}]"

    h = int(oldest_age_secs // 3600)
    m = int((oldest_age_secs % 3600) // 60)
    return False, f"all fresh (oldest {h}h {m}m old, threshold {max_age_hours}h)"


def _run_auth_refresh(env: str) -> bool:
    """Run scripts/refresh_auth.py for the given env. Returns True on success.

    In CI (CI=true) a non-zero exit from refresh_auth.py is fatal — we abort
    immediately rather than letting 54 tests fail with cryptic session errors.
    """
    in_ci = os.getenv("CI", "").lower() == "true"
    print(f"\n[auth] Refreshing auth states for {env.upper()} ...")
    print(f"[auth] Running: python scripts/refresh_auth.py --env {env}\n")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "refresh_auth.py"), "--env", env],
        cwd=str(ROOT),
    )
    if result.returncode == 0:
        print(f"\n[auth] Refresh complete.")
        return True

    msg = (
        f"\n[auth] Auth refresh FAILED (exit code {result.returncode}).\n"
        f"[auth] Check that CI secrets / .env.{env} are set correctly and the app is reachable."
    )
    if in_ci:
        print(msg, file=sys.stderr)
        print("[auth] Aborting — running tests with stale auth would produce misleading failures.", file=sys.stderr)
        sys.exit(2)
    else:
        print(f"{msg}\n[auth] Continuing locally — existing sessions may still be valid.", file=sys.stderr)
        return False


def main() -> int:
    args = parse_args()

    if args.list_tags:
        list_tags()
        return 0

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    json_path = output_dir / "results.json"
    html_path = output_dir / "report.html"

    # --- Auth refresh ---
    auth_label = ""
    if args.no_auth_refresh:
        auth_label = "skipped (--no-auth-refresh)"
    elif args.dry_run:
        if args.refresh_auth:
            auth_label = "would force-refresh (--refresh-auth) [dry-run]"
        else:
            needs, reason = _auth_status(args.env, args.auth_max_age)
            auth_label = f"would {'auto-refresh' if needs else 'skip'} - {reason} [dry-run]"
    else:
        if args.refresh_auth:
            _run_auth_refresh(args.env)
            auth_label = "force-refreshed (--refresh-auth)"
        else:
            needs, reason = _auth_status(args.env, args.auth_max_age)
            if needs:
                _run_auth_refresh(args.env)
                auth_label = f"auto-refreshed ({reason})"
            else:
                auth_label = f"fresh - {reason}"

    cmd = build_pytest_cmd(args, json_path)

    # Header
    print(f"\n{'=' * 62}")
    print("  NSM E2E Automation Runner")
    print(f"  Env     : {args.env.upper()}")
    print(f"  Tags    : {args.tags or '(all - no marker filter)'}")
    print(f"  Test    : {args.test or '(all matched)'}")
    browser_info = args.browser + (" [headed]" if args.headed else " [headless]")
    if args.slowmo:
        browser_info += f" slowmo={args.slowmo}ms"
    print(f"  Browser : {browser_info}")
    print(f"  Auth    : {auth_label}")
    print(f"  Output  : {output_dir}")
    print(f"{'=' * 62}")
    print()
    print("Command:", " ".join(str(c) for c in cmd))
    print()

    if args.dry_run:
        print("[dry-run] Exiting without executing.")
        return 0

    # Run
    env_vars = {**os.environ, "NSM_ENV": args.env}
    result = subprocess.run(cmd, cwd=str(ROOT), env=env_vars)
    exit_code = result.returncode

    # Report
    if json_path.exists():
        generate_html_report(json_path, html_path, args.env)

        if not args.no_archive:
            slug = _tag_slug(args)
            archive_dir = output_dir / "archive" / f"{run_ts}_{args.env}_{slug}"
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(json_path, archive_dir / "results.json")
            shutil.copy2(html_path, archive_dir / "report.html")
            print(f"[archive] {archive_dir}")

        print(f"[report]  {html_path}")

        if args.open:
            import webbrowser
            webbrowser.open(html_path.as_uri())
    else:
        print("[warn] No results.json produced — HTML report skipped.", file=sys.stderr)

    print(f"\n{'=' * 62}")
    status = "PASSED" if exit_code == 0 else f"FAILED (exit {exit_code})"
    print(f"  Run complete — {status}")
    print(f"{'=' * 62}\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
