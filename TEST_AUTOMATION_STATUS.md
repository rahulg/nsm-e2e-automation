# E2E Test Automation Status

Generated: 2026-02-28
Framework: Python + Playwright (pytest)
Location: `/Users/kunal/NSM/e2eautomation/tests/`

Import Check: **All 47 test files pass** — 201 test methods collected, 0 import errors.

---

## Summary

| Category                               | Count | Test IDs                                       |
|----------------------------------------|-------|-------------------------------------------------|
| Fully Automated (spec-aligned)         | 43    | E2E-001 to 034, 036 to 041, 043, 044, 046, 047 |
| Non-Functional / Performance (ignored) | 1     | E2E-035                                         |
| Non-Automatable (ignored)              | 1     | E2E-042                                         |
| Partially Automatable (ignored)        | 2     | E2E-033, 045                                    |
| **Total**                              | **47**|                                                  |

---

## 1. FULLY AUTOMATED — Spec-Aligned (43 tests)

These tests are implemented, import clean, and match their original E2E spec from `NSM_E2E_Test_Cases.txt`.

### Core Workflows (E2E-001 to 006) — Critical Priority

| Test ID  | File                                              | Phases | Description                                      |
|----------|---------------------------------------------------|--------|--------------------------------------------------|
| E2E-001  | test_e2e_001_standard_vehicle_lifecycle.py         | 8      | Standard lifecycle — LT-260 to LT-265 (Sold)    |
| E2E-002  | test_e2e_002_no_owners_court_hearing.py            | 8      | No Owners Path + Court Hearing                   |
| E2E-003  | test_e2e_003_mobile_home_lt262a.py                 | 5      | Mobile Home shortcut via LT-262A                 |
| E2E-004  | test_e2e_004_sheriff_inspector_lt261.py            | 3      | Sheriff/Inspector LT-261 (staff-only)            |
| E2E-005  | test_e2e_005_paper_form_e2e.py                     | 6      | Paper Form end-to-end (staff-only)               |
| E2E-006  | test_e2e_006_individual_user_payit.py              | 8      | Individual User + PayIt (NC ID = precondition)   |

### Alternate / Exception Flows (E2E-007 to 012)

| Test ID  | File                                              | Phases | Description                                      |
|----------|---------------------------------------------------|--------|--------------------------------------------------|
| E2E-007  | test_e2e_007_rejection_resubmission.py             | 6      | Rejection, correction, resubmission              |
| E2E-008  | test_e2e_008_stolen_vehicle_lockout.py             | 4      | Stolen Vehicle Lockout + CMS download            |
| E2E-009  | test_e2e_009_vehicle_reclaim.py                    | 7      | Vehicle Reclaim Mid-Process                      |
| E2E-010  | test_e2e_010_unfavorable_court_judgment.py          | 6      | Unfavorable Court Judgment, LT-263 blocked       |
| E2E-011  | test_e2e_011_nordis_delivery_blocked.py            | 5      | Nordis Delivery Blocked, LT-263 locked           |
| E2E-012  | test_e2e_012_drawdown_setup_usage.py               | 6      | Drawdown Setup, Fund, Auto-recharge, Pay         |

### Multi-User / Role-Based (E2E-013 to 016)

| Test ID  | File                                              | Phases | Description                                      |
|----------|---------------------------------------------------|--------|--------------------------------------------------|
| E2E-013  | test_e2e_013_multi_user_business.py                | 4      | Multi-User Business Flow (Admin + User B)        |
| E2E-014  | test_e2e_014_company_switching.py                  | 3      | Company Switching + Data Isolation                |
| E2E-015  | test_e2e_015_fiscal_user_restrictions.py           | 3      | Fiscal User Role Restrictions + Reports          |
| E2E-016  | test_e2e_016_lsa_full_workflow.py                  | 6      | LSA Full Admin Workflow (KPIs, Users, Config)    |

### Edge Cases (E2E-017 to 047)

| Test ID  | File                                              | Phases | Description                                      |
|----------|---------------------------------------------------|--------|--------------------------------------------------|
| E2E-017  | test_e2e_017_invalid_vin_draft_resume.py           | 2      | Invalid VIN, manual entry, draft, resume         |
| E2E-018  | test_e2e_018_duplicate_vin_detection.py            | 3      | Duplicate VIN detection (two users, same VIN)    |
| E2E-019  | test_e2e_019_payment_failure_retry.py              | 3      | Payment failure, switch method, retry            |
| E2E-020  | test_e2e_020_paper_form_relaxed_dates.py           | 2      | Paper form relaxed date validation               |
| E2E-021  | test_e2e_021_stolen_vehicle_reset.py               | 3      | Stolen vehicle reset + resubmit                  |
| E2E-022  | test_e2e_022_concurrent_staff_actions.py           | 2      | Concurrent staff editing same LT-262             |
| E2E-023  | test_e2e_023_payit_status_update.py                | 4      | PayIt status update + cart cleared               |
| E2E-024  | test_e2e_024_close_file_attribution.py             | 3      | Close file "Updated By" attribution              |
| E2E-025  | test_e2e_025_paper_form_submitted_date.py          | 2      | Paper form submitted date recording              |
| E2E-026  | test_e2e_026_nordis_letter_reconciliation.py       | 2      | Nordis letter reconciliation (UI report only)    |
| E2E-027  | test_e2e_027_case_status_transitions.py            | 3      | Case status transitions via Global Search        |
| E2E-028  | test_e2e_028_cart_clearance_duplicates.py          | 4      | Cart clearance after payment, duplicate block    |
| E2E-029  | test_e2e_029_edit_post_processing.py               | 3      | Edit form data post-processing                   |
| E2E-030  | test_e2e_030_lt264a_issuance.py                    | 2      | LT-264A aging period tracking + issuance         |
| E2E-031  | test_e2e_031_lt264b_hearing_notification.py        | 3      | LT-264B owner hearing request + notification     |
| E2E-032  | test_e2e_032_draft_auto_save.py                    | 3      | Draft auto-save: partial fill, navigate, return  |
| E2E-034  | test_e2e_034_concurrent_vin_processing.py          | 3      | Concurrent VIN processing (two staff, same VIN)  |
| E2E-036  | test_e2e_036_report_export_integrity.py            | 4      | Report XLSX/PDF export file integrity validation |
| E2E-037  | test_e2e_037_draft_global_search_exclusion.py      | 7      | Draft form Global Search exclusion + payment-ES resilience |
| E2E-038  | test_e2e_038_closed_cases_report_attribution.py    | 6      | Closed Cases Report "Closed By" attribution (staff + public) |
| E2E-039  | test_e2e_039_correspondence_letter_accuracy.py     | 4      | Correspondence letter content accuracy (owner/lessee/lienholder names) |
| E2E-040  | test_e2e_040_listing_global_search_consistency.py  | 5      | Listing page state completeness vs Global Search consistency |
| E2E-041  | test_e2e_041_lt262_workflow_tab_visibility.py      | 7      | LT-262 workflow tab visibility (Aging, Court Hearing, Payment Pending) |
| E2E-043  | test_e2e_043_closed_case_lt264_lockdown.py         | 8      | Closed LT-262 case Track LT-264 action lockdown |
| E2E-044  | test_e2e_044_lt264_button_idempotency.py           | 6      | LT-264 issuance button idempotency (double-click prevention) |
| E2E-046  | test_e2e_046_global_search_offline_payment.py      | 4      | Global Search navigation to offline payment details (check/money order) |
| E2E-047  | test_e2e_047_facility_name_special_chars.py        | 5      | Facility name special character validation across all entry points |

### Notes
- **E2E-006**: NC ID registration at `myncidpp.nc.gov` is a precondition (external site). Test automates from NSM login onwards.
- **E2E-026**: SFTP reconciliation out of scope. Test automates UI report verification only.

---

## 2. IGNORED — Non-Functional / Performance (1 test)

| Test ID  | File                                    | Original Spec Title                                      | Reason                                    |
|----------|-----------------------------------------|----------------------------------------------------------|-------------------------------------------|
| E2E-035  | test_e2e_035_report_date_filters.py     | Cross-Portal Listing and Detail Page Performance Baseline | Non-functional performance test. Requires page load timing thresholds, DB query monitoring, DevTools instrumentation. Not suitable for functional E2E automation. |

---

## 3. IGNORED — Non-Automatable (1 test)

| Test ID  | File                                    | Original Spec Title                                                     | Reason                                    |
|----------|-----------------------------------------|-------------------------------------------------------------------------|-------------------------------------------|
| E2E-042  | test_e2e_042_sso_domain_migration.py    | Staff SSO Identity Migration — Productivity Report Continuity           | Requires SSO domain migration at infrastructure/IdP level. Cannot be triggered via UI. Entire class marked `@pytest.mark.skip`. |

---

## 4. IGNORED — Partially Automatable (2 tests)

These tests require infrastructure access (SFTP, backend batch jobs) that cannot be simulated in UI E2E tests. Entire class marked `@pytest.mark.skip`.

| Test ID  | File                                          | Original Spec Title                                            | Reason                                    |
|----------|-----------------------------------------------|----------------------------------------------------------------|-------------------------------------------|
| E2E-033  | test_e2e_033_nordis_sftp_failure.py           | Nordis SFTP Failure Simulation                                 | Requires SFTP infrastructure access for connection failure simulation |
| E2E-045  | test_e2e_045_nordis_backend_triggers.py       | Nordis Shipment Status Derivation Accuracy — Mailed vs Delivered | Requires Nordis backend SFTP file drop / batch job trigger |

---

## File Inventory

```
tests/
├── test_e2e_001_standard_vehicle_lifecycle.py      [Automated]
├── test_e2e_002_no_owners_court_hearing.py          [Automated]
├── test_e2e_003_mobile_home_lt262a.py               [Automated]
├── test_e2e_004_sheriff_inspector_lt261.py          [Automated]
├── test_e2e_005_paper_form_e2e.py                   [Automated]
├── test_e2e_006_individual_user_payit.py            [Automated]
├── test_e2e_007_rejection_resubmission.py           [Automated]
├── test_e2e_008_stolen_vehicle_lockout.py           [Automated]
├── test_e2e_009_vehicle_reclaim.py                  [Automated]
├── test_e2e_010_unfavorable_court_judgment.py       [Automated]
├── test_e2e_011_nordis_delivery_blocked.py          [Automated]
├── test_e2e_012_drawdown_setup_usage.py             [Automated]
├── test_e2e_013_multi_user_business.py              [Automated]
├── test_e2e_014_company_switching.py                [Automated]
├── test_e2e_015_fiscal_user_restrictions.py         [Automated]
├── test_e2e_016_lsa_full_workflow.py                [Automated]
├── test_e2e_017_invalid_vin_draft_resume.py         [Automated]
├── test_e2e_018_duplicate_vin_detection.py          [Automated]
├── test_e2e_019_payment_failure_retry.py            [Automated]
├── test_e2e_020_paper_form_relaxed_dates.py         [Automated]
├── test_e2e_021_stolen_vehicle_reset.py             [Automated]
├── test_e2e_022_concurrent_staff_actions.py         [Automated]
├── test_e2e_023_payit_status_update.py              [Automated]
├── test_e2e_024_close_file_attribution.py           [Automated]
├── test_e2e_025_paper_form_submitted_date.py        [Automated]
├── test_e2e_026_nordis_letter_reconciliation.py     [Automated]
├── test_e2e_027_case_status_transitions.py          [Automated]
├── test_e2e_028_cart_clearance_duplicates.py        [Automated]
├── test_e2e_029_edit_post_processing.py             [Automated]
├── test_e2e_030_lt264a_issuance.py                  [Automated]
├── test_e2e_031_lt264b_hearing_notification.py      [Automated]
├── test_e2e_032_draft_auto_save.py                  [Automated]
├── test_e2e_033_nordis_sftp_failure.py              [Ignored — partially automatable]
├── test_e2e_034_concurrent_vin_processing.py        [Automated]
├── test_e2e_035_report_date_filters.py              [Ignored — non-functional / performance]
├── test_e2e_036_report_export_integrity.py          [Automated]
├── test_e2e_037_draft_global_search_exclusion.py    [Automated]
├── test_e2e_038_closed_cases_report_attribution.py  [Automated]
├── test_e2e_039_correspondence_letter_accuracy.py   [Automated]
├── test_e2e_040_listing_global_search_consistency.py [Automated]
├── test_e2e_041_lt262_workflow_tab_visibility.py    [Automated]
├── test_e2e_042_sso_domain_migration.py             [Ignored — non-automatable]
├── test_e2e_043_closed_case_lt264_lockdown.py       [Automated]
├── test_e2e_044_lt264_button_idempotency.py         [Automated]
├── test_e2e_045_nordis_backend_triggers.py          [Ignored — partially automatable]
├── test_e2e_046_global_search_offline_payment.py    [Automated]
└── test_e2e_047_facility_name_special_chars.py      [Automated]
```

---

## Execution Commands

```bash
# All tests (skipped tests are auto-excluded by pytest)
pytest tests/ -v

# Explicit skip of ignored tests
pytest tests/ -v -k "not e2e_033 and not e2e_035 and not e2e_042 and not e2e_045"

# Core workflows only (001-006)
pytest -m core -v

# Critical priority only
pytest -m critical -v

# Edge cases only
pytest -m edge -v

# Single test
pytest tests/test_e2e_001_standard_vehicle_lifecycle.py -v

# By category
pytest -m "core" -v          # 6 core workflow tests
pytest -m "alternate" -v     # 6 alternate/exception tests
pytest -m "multiuser" -v     # 4 multi-user tests
pytest -m "edge" -v          # 31 edge case tests
pytest -m "payment" -v       # Payment-related tests
pytest -m "report" -v        # Report-related tests
pytest -m "nordis" -v        # Nordis-related tests
```
