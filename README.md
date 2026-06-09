# NSM E2E Automation

End-to-end test suite for the **NCDOT Notice & Storage Management (NSM/NSS)** system.  
Tests cover the full abandoned-vehicle lien/storage workflow across two portals — Public Portal (garage owners / towing facilities) and Staff Portal (DMV staff).

---

## Table of Contents

1. [Prerequisites & Installation](#1-prerequisites--installation)
2. [Environment Setup](#2-environment-setup)
3. [Authentication Setup](#3-authentication-setup)
4. [Running Tests](#4-running-tests)
   - [Full Regression](#full-regression)
   - [Tag-Based Runs (Core / Fixed / Smoke …)](#tag-based-runs)
   - [Single Test](#single-test)
   - [Headed Mode (Visible Browser)](#headed-mode)
5. [Viewing Results](#5-viewing-results)
6. [Runner Reference](#6-runner-reference)
7. [Marker Reference](#7-marker-reference)
8. [Project Structure](#8-project-structure)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites & Installation

### System Requirements

| Requirement | Version |
|-------------|---------|
| Python | 3.10 or later |
| pip | bundled with Python |
| Git | any recent version |
| OS | Windows 10/11, macOS 12+, Ubuntu 20.04+ |

> **Windows note:** Run all commands in PowerShell or Command Prompt. Avoid Git Bash for Playwright commands — it sometimes mishandles paths.

---

### Step-by-step setup (fresh machine)

#### 1. Get the code

```bash
git clone <repo-url> e2eautomation
cd e2eautomation
```

Or extract the project zip and `cd` into the folder.

---

#### 2. Create a virtual environment (strongly recommended)

```bash
# Create
python -m venv .venv

# Activate — Windows PowerShell
.venv\Scripts\Activate.ps1

# Activate — Windows CMD
.venv\Scripts\activate.bat

# Activate — macOS / Linux
source .venv/bin/activate
```

Your prompt will show `(.venv)` when the environment is active.  
All commands below assume the venv is active.

---

#### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---------|---------|
| `playwright` | Browser automation engine |
| `pytest` | Test runner |
| `pytest-playwright` | Playwright fixtures for pytest |
| `python-dotenv` | `.env` file loading |
| `openpyxl` | Excel file handling (test data) |
| `PyPDF2` | PDF validation in tests |
| `pytest-json-report` | JSON output consumed by the HTML reporter |

---

#### 4. Install Playwright browser binaries

```bash
playwright install chromium
```

To install all supported browsers:

```bash
playwright install
```

> The binaries are downloaded to `~/.cache/ms-playwright/` (Linux/macOS) or `%LOCALAPPDATA%\ms-playwright\` (Windows). They are **not** inside this project folder, but they only need to be installed once per machine.

---

## 2. Environment Setup

Tests target two environments. Each requires its own credential file.

### Create `.env.qa` (QA environment)

```env
# .env.qa  — QA environment credentials

# Primary public portal user
PUBLIC_PORTAL_URL=https://nsm-qa-public.nc.verifi.dev/ncshp-nss-signin
PUBLIC_PORTAL_USERNAME=<username>
PUBLIC_PORTAL_PASSWORD=<password>

# Staff portal
STAFF_PORTAL_URL=https://nsm-qa.nc.verifi.dev/login
STAFF_PORTAL_USERNAME=<username>
STAFF_PORTAL_PASSWORD=<password>

# Secondary public user (multi-user tests)
PUBLIC_USER_B_USERNAME=<username>
PUBLIC_USER_B_PASSWORD=<password>

# Secondary staff user (multi-user tests)
STAFF_USER_B_USERNAME=<username>
STAFF_USER_B_PASSWORD=<password>

# Fiscal user (restricted — Reports only)
FISCAL_USER_USERNAME=<username>
FISCAL_USER_PASSWORD=<password>

# Individual public user (E2E-006)
INDIVIDUAL_PUBLIC_USERNAME=<username>
INDIVIDUAL_PUBLIC_PASSWORD=<password>
```

### Create `.env.stage` (STAGE environment)

Same keys — substitute STAGE URLs and credentials:

```env
# .env.stage — STAGE environment credentials

PUBLIC_PORTAL_URL=https://public-nss-stage.verifi-nc.com/ncshp-nss-signin
STAFF_PORTAL_URL=https://staff-nss-stage.verifi-nc.com/login
# ... same remaining keys as .env.qa
```

> Both `.env.qa` and `.env.stage` are git-ignored. Never commit credentials.

---

## 3. Authentication Setup

Tests use **stored browser sessions** (cookies + localStorage) rather than logging in on every run.

### Automatic auth refresh (built into the runner)

The runner checks the age of every auth file before each run.  
If any file is **missing or older than 8 hours**, it automatically runs `scripts/refresh_auth.py` before starting pytest — no manual intervention needed.

```
Auth    : auto-refreshed (oldest token is 9h 12m old ...)
Auth    : fresh (oldest 2h 44m old, threshold 8h)
```

**Override flags:**

| Flag | Effect |
|------|--------|
| *(default)* | Auto-check: refresh only if stale (>8 h) |
| `--refresh-auth` | Force refresh regardless of age |
| `--no-auth-refresh` | Skip check entirely (manage auth yourself) |
| `--auth-max-age N` | Change the stale threshold to N hours |

```bash
python run_tests.py --refresh-auth            # force refresh, then run
python run_tests.py --no-auth-refresh         # trust existing sessions
python run_tests.py --auth-max-age 4          # treat anything >4h as stale
```

### Manual refresh (first-time setup or after credential changes)

```bash
# QA (default)
python scripts/refresh_auth.py

# STAGE
python scripts/refresh_auth.py --env stage
```

> This opens a headless browser for each portal user, logs in, and saves the session to `auth/qa/` or `auth/stage/`. Required before the very first run on a new machine.

### Auth files location

```
auth/
  qa/
    public-portal.json
    public-portal-user-b.json
    staff-portal.json
    lsa-portal.json
    fiscal-portal.json
    individual-portal.json
  stage/
    (same files)
```

The `auth/` directory is git-ignored — it lives only on your machine.

---

## 4. Running Tests

All test runs go through `run_tests.py` at the project root.

```
python run_tests.py [options]
```

### Full Regression

Run every test in the suite:

```bash
# QA (default)
python run_tests.py

# STAGE
python run_tests.py --env stage
```

---

### Tag-Based Runs

Use `--tags` with any pytest marker expression.

#### Core tests (E2E-001 to E2E-006 — complete vehicle lifecycle)

```bash
python run_tests.py --tags core
python run_tests.py --tags core --env stage
```

#### Fixed / stabilised tests

```bash
python run_tests.py --tags fixed
```

#### Smoke (quick sanity subset)

```bash
python run_tests.py --tags smoke
```

#### Other useful expressions

```bash
# Core or smoke
python run_tests.py --tags "core or smoke"

# All E2E except Nordis integration
python run_tests.py --tags "e2e and not nordis"

# Critical priority only
python run_tests.py --tags critical

# Fixed tests on STAGE
python run_tests.py --env stage --tags fixed

# Payment tests, headed browser for visibility
python run_tests.py --tags payment --headed
```

All available markers are listed in [Section 7](#7-marker-reference).  
Run `python run_tests.py --list-tags` for a quick in-terminal reference.

---

### Single Test

#### By test ID / keyword fragment

```bash
python run_tests.py --test test_e2e_001
python run_tests.py --test test_e2e_054
python run_tests.py --test "standard_vehicle"
```

This maps to `pytest -k <value>`, which matches any test whose node ID contains the fragment.

#### By exact file path

```bash
python run_tests.py --test tests/test_e2e_001_standard_vehicle_lifecycle.py
python run_tests.py --test tests/test_e2e_054_audit_log_report.py
```

#### Combine with env

```bash
python run_tests.py --env stage --test test_e2e_001
```

---

### Headed Mode

Watch the browser as tests execute — useful for debugging failures.

```bash
# Any run with a visible browser
python run_tests.py --headed

# Headed + slow motion (500 ms between actions)
python run_tests.py --headed --slowmo 500 --tags core

# Single test, headed, slow motion
python run_tests.py --test test_e2e_001 --headed --slowmo 300
```

---

### Preview command without running

```bash
python run_tests.py --dry-run --tags core --env stage
```

---

## 5. Viewing Results

After each run, two files are written to `results/`:

| File | Description |
|------|-------------|
| `results/report.html` | Styled HTML report — open in any browser |
| `results/results.json` | Raw pytest JSON data |

Every run is also archived to a timestamped subfolder:

```
results/
  report.html              ← latest run (overwritten each time)
  results.json             ← latest run (overwritten each time)
  archive/
    2026-06-09_143022_qa_core/
      report.html
      results.json
    2026-06-09_160001_qa_all/
      ...
```

Open the latest report:

```bash
# Windows
start results\report.html

# macOS
open results/report.html

# Linux
xdg-open results/report.html
```

Or add `--open` to the runner command to open automatically:

```bash
python run_tests.py --tags core --open
```

---

## 6. Runner Reference

```
python run_tests.py [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--env qa\|stage` | `qa` | Target environment |
| `--tags EXPR` / `-m EXPR` | *(all)* | Pytest marker expression |
| `--test VALUE` / `-k VALUE` | *(all)* | File path or keyword fragment |
| `--headed` | headless | Run with visible browser |
| `--browser chromium\|firefox\|webkit` | `chromium` | Browser engine |
| `--slowmo MS` | `0` | Milliseconds between browser actions |
| `--refresh-auth` | *(auto)* | Force auth refresh before running |
| `--no-auth-refresh` | *(auto)* | Skip auth freshness check entirely |
| `--auth-max-age HOURS` | `8` | Stale threshold in hours |
| `--output-dir DIR` | `results/` | Report output directory |
| `--no-archive` | *(archive)* | Skip per-run archive |
| `--open` | *(don't)* | Open HTML report after run |
| `--list-tags` | — | Print marker list and exit |
| `--dry-run` | — | Show pytest command (+ auth decision), don't run |
| `-- <extra>` | — | Pass extra flags directly to pytest |

### Pass-through to pytest

Anything after `--` is forwarded verbatim to pytest:

```bash
# Stop on first failure, long traceback
python run_tests.py --tags core -- -x --tb=long

# Run in parallel (requires: pip install pytest-xdist)
python run_tests.py --tags core -- -n 4
```

---

## 7. Marker Reference

| Marker | Tests | Description |
|--------|-------|-------------|
| `e2e` | All 54 | Every cross-portal E2E test |
| `core` | E2E-001…006 | Standard vehicle lifecycle, no-owners, mobile home, sheriff, paper form, individual flow |
| `alternate` | E2E-007…012 | Rejection/resubmission, stolen lockout, reclaim, no court judgment, Nordis blocked, drawdown recharge |
| `multiuser` | E2E-013…016 | Multi-user business, company switching, fiscal restrictions, LSA workflow |
| `edge` | E2E-017+ | Edge cases and integration scenarios |
| `fixed` | various | Stabilised tests (previously failing) |
| `smoke` | subset | Quick sanity check |
| `critical` | subset | Critical business paths |
| `high` | subset | High-priority tests |
| `medium` | subset | Medium-priority tests |
| `payment` | subset | PayIt, drawdown, mailed payment flows |
| `paper_form` | subset | Paper form submission and processing |
| `nordis` | subset | Nordis SFTP mailing service integration |
| `report` | E2E-035, 036 | Daily Revenue and Deposit reports |
| `performance` | subset | Page-load and response-time thresholds |

---

## 8. Project Structure

```
e2eautomation/
│
├── run_tests.py            ← Main test runner (start here)
├── pytest.ini              ← Pytest config (markers, test paths)
├── requirements.txt        ← Python dependencies
├── .env.qa                 ← QA credentials (git-ignored, create manually)
├── .env.stage              ← STAGE credentials (git-ignored, create manually)
│
├── tests/                  ← 54 E2E test files
│   ├── conftest.py         ← Fixtures: browser contexts per env & user role
│   └── test_e2e_NNN_*.py
│
├── src/
│   ├── config/
│   │   ├── env.py          ← ENV class: URL/credential resolution
│   │   └── test_data.py    ← Centralised test data (VINs, payments, thresholds)
│   ├── helpers/
│   │   ├── data_helper.py  ← VIN / address / person / date generators
│   │   ├── login_helper.py ← Context factories for each portal
│   │   ├── form_helper.py  ← Form-filling abstractions
│   │   ├── navigation_helper.py
│   │   └── workflow_helper.py  ← Cross-portal workflow composites
│   └── pages/
│       ├── public_portal/  ← Page objects for Public Portal (10 pages)
│       └── staff_portal/   ← Page objects for Staff Portal (17 pages)
│
├── scripts/
│   ├── refresh_auth.py     ← Seed / refresh all browser auth sessions
│   ├── save_*.py           ← Individual auth scripts per user role
│   ├── generate_report.py  ← JSON → styled HTML report
│   ├── notify_slack.py     ← Post results to Slack via Expertly
│   └── auth_helpers.py     ← Shared login utilities
│
├── auth/                   ← Stored browser sessions (git-ignored)
│   ├── qa/
│   └── stage/
│
├── fixtures/               ← Static test files
│   ├── sample-document.pdf
│   └── sample-vin-image.png
│
└── results/                ← Generated reports (git-ignored)
    ├── report.html
    ├── results.json
    └── archive/
```

---

## 9. Running in CI (Jenkins / GitHub Actions / GitLab CI)

### How the runner behaves in CI

| Concern | Behaviour |
|---------|-----------|
| Auth files | Always missing in a clean workspace (`auth/` is git-ignored) → runner auto-refreshes on every CI run |
| Headless mode | Auth scripts detect `CI=true` and run fully headless automatically |
| Credentials | `.env.qa` / `.env.stage` are git-ignored — CI must inject credentials as env vars (see below) |
| Auth refresh failure | **Fatal in CI** — runner exits with code 2 and a clear message rather than running 54 tests that all fail with cryptic session errors |
| Exit code | Runner returns pytest's exit code — CI marks the build pass/fail correctly |
| `--open` flag | Never pass this in CI (it tries to open a browser on the agent) |

---

### Step 1 — inject credentials as CI secrets

Since `.env.qa` and `.env.stage` are git-ignored, set these as CI environment variables (GitHub Actions secrets, Jenkins credentials binding, GitLab CI variables, etc.):

**Required:**
```
PUBLIC_PORTAL_URL
PUBLIC_PORTAL_USERNAME
PUBLIC_PORTAL_PASSWORD
STAFF_PORTAL_URL
STAFF_PORTAL_USERNAME
STAFF_PORTAL_PASSWORD
```

**Required for multi-user / role-based tests:**
```
PUBLIC_USER_B_USERNAME      PUBLIC_USER_B_PASSWORD
STAFF_USER_B_USERNAME       STAFF_USER_B_PASSWORD
FISCAL_USER_USERNAME        FISCAL_USER_PASSWORD
INDIVIDUAL_PUBLIC_USERNAME  INDIVIDUAL_PUBLIC_PASSWORD
```

`load_dotenv` is a no-op when the `.env` file is absent, so any vars already in `os.environ` (injected by CI) are used directly — no file needed.

---

### Step 2 — install dependencies in the pipeline

```yaml
# GitHub Actions example
- name: Install Python deps
  run: pip install -r requirements.txt

- name: Install Playwright browsers
  run: playwright install chromium

# Linux CI only — install OS-level browser dependencies
- name: Install Playwright system deps
  run: playwright install-deps chromium
```

> macOS and Windows CI agents usually don't need `install-deps`. Linux agents (Ubuntu, Debian) do.

---

### Step 3 — run tests

```bash
# Full regression
python run_tests.py --env qa

# Core tests only
python run_tests.py --env qa --tags core

# Force auth refresh (useful if you suspect the auto-detect isn't triggering)
python run_tests.py --env qa --refresh-auth
```

No extra flags needed — auth refresh, headless mode, and JSON/HTML reporting are all automatic.

---

### Step 4 — upload results as artifacts

The runner writes to `results/` (git-ignored). Configure your CI to upload this folder:

```yaml
# GitHub Actions
- name: Upload test report
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: nsm-e2e-report
    path: results/

# Jenkins (Declarative Pipeline)
post {
  always {
    archiveArtifacts artifacts: 'results/**', fingerprint: true
    publishHTML([
      reportDir: 'results',
      reportFiles: 'report.html',
      reportName: 'NSM E2E Report'
    ])
  }
}
```

---

### Minimal GitHub Actions workflow

```yaml
name: NSM E2E Tests

on:
  push:
    branches: [master]
  workflow_dispatch:

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          playwright install chromium
          playwright install-deps chromium

      - name: Run E2E tests
        env:
          PUBLIC_PORTAL_URL: ${{ secrets.PUBLIC_PORTAL_URL }}
          PUBLIC_PORTAL_USERNAME: ${{ secrets.PUBLIC_PORTAL_USERNAME }}
          PUBLIC_PORTAL_PASSWORD: ${{ secrets.PUBLIC_PORTAL_PASSWORD }}
          STAFF_PORTAL_URL: ${{ secrets.STAFF_PORTAL_URL }}
          STAFF_PORTAL_USERNAME: ${{ secrets.STAFF_PORTAL_USERNAME }}
          STAFF_PORTAL_PASSWORD: ${{ secrets.STAFF_PORTAL_PASSWORD }}
          PUBLIC_USER_B_USERNAME: ${{ secrets.PUBLIC_USER_B_USERNAME }}
          PUBLIC_USER_B_PASSWORD: ${{ secrets.PUBLIC_USER_B_PASSWORD }}
          STAFF_USER_B_USERNAME: ${{ secrets.STAFF_USER_B_USERNAME }}
          STAFF_USER_B_PASSWORD: ${{ secrets.STAFF_USER_B_PASSWORD }}
          FISCAL_USER_USERNAME: ${{ secrets.FISCAL_USER_USERNAME }}
          FISCAL_USER_PASSWORD: ${{ secrets.FISCAL_USER_PASSWORD }}
          INDIVIDUAL_PUBLIC_USERNAME: ${{ secrets.INDIVIDUAL_PUBLIC_USERNAME }}
          INDIVIDUAL_PUBLIC_PASSWORD: ${{ secrets.INDIVIDUAL_PUBLIC_PASSWORD }}
        run: python run_tests.py --env qa --tags core

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: nsm-e2e-report-${{ github.run_number }}
          path: results/
```

---

## 10. Troubleshooting

### Tests fail immediately with a login / session error

Auth states have expired. Refresh them:

```bash
python scripts/refresh_auth.py             # QA
python scripts/refresh_auth.py --env stage # STAGE
```

---

### `playwright install` fails or browser not found

Re-run the install:

```bash
playwright install chromium
# or for all browsers:
playwright install
```

On Linux you may also need system dependencies:

```bash
playwright install-deps chromium
```

---

### `ModuleNotFoundError` for playwright / pytest

The virtual environment is not active, or dependencies were not installed:

```bash
# Re-activate venv
.venv\Scripts\Activate.ps1          # Windows
source .venv/bin/activate            # macOS/Linux

# Re-install
pip install -r requirements.txt
```

---

### Specific test is flaky or slow

Run it headed with slow motion to observe the browser:

```bash
python run_tests.py --test test_e2e_NNN --headed --slowmo 400
```

---

### See full pytest traceback

Pass `--tb=long` via the extra args separator:

```bash
python run_tests.py --tags core -- --tb=long
```

---

### Check which tests would run without executing them

```bash
python run_tests.py --dry-run --tags core
# then run pytest --collect-only manually:
pytest --collect-only -m core --env qa
```

---

### Results directory is cluttered

Archives accumulate in `results/archive/`. Safe to delete old ones manually — they are git-ignored and not referenced by the runner.
