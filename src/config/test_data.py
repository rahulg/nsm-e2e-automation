"""
Centralized test data for all E2E scenarios.

Contains:
  - STARS-specific VIN placeholders (update when real VINs are available)
  - Payment data (Drawdown, PayIt test cards, mailed payment)
  - Lien/form data (standard charges, sale data)
  - Performance thresholds
  - File paths for fixtures
"""

from pathlib import Path

# ─── Fixture file paths ───
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
SAMPLE_DOC_PATH = str(FIXTURES_DIR / "sample-document.pdf")
VIN_PLATE_IMAGE_PATH = str(FIXTURES_DIR / "vin-plate-image.jpg")  # Needed for E2E-017

# ─── STARS-specific VINs ───
# These VINs must exist in the STARS QA database. Update with real values.
VIN_WITH_OWNERS = "PLACEHOLDER_OWNERS"       # VIN with owners/lessees/lienholders present
VIN_NO_OWNERS = "PLACEHOLDER_NO_OWNERS"       # VIN with no owners (triggers LT-260C path)
VIN_STOLEN = "PLACEHOLDER_STOLEN"             # VIN with stolen indicator = Yes
VIN_MANUFACTURED_HOME = "PLACEHOLDER_MFH"     # VIN for manufactured/mobile home body type

# ─── Standard lien charges ───
STANDARD_LIEN_CHARGES = {
    "storage": "500",
    "towing": "200",
    "labor": "100",
}

MINIMAL_LIEN_CHARGES = {
    "storage": "100",
}

FULL_LIEN_CHARGES = {
    "storage": "500",
    "towing": "200",
    "labor": "100",
    "materials": "50",
    "other": "25",
}

# ─── Payment data ───
PAYIT_TEST_CARD = {
    "number": "4111111111111111",
    "expiry": "12/28",
    "cvv": "123",
    "zip": "27601",
}

DRAWDOWN_PAYMENT = {
    "method": "Drawdown",
}

MAILED_PAYMENT = {
    "method": "check",
    "check_number": "12345",
    "amount": "16.75",
}

# ─── Sale data ───
STANDARD_SALE_DATA = {
    "type": "public",
    "lien_amount": "800",
    "labor_cost": "100",
    "storage_cost": "500",
}

PRIVATE_SALE_DATA = {
    "type": "private",
    "lien_amount": "500",
    "labor_cost": "100",
    "storage_cost": "300",
}

# ─── Form field defaults ───
APPROX_VEHICLE_VALUE = "5000"
STORAGE_LOCATION_NAME = "Test Storage Facility"

# ─── Paper form data ───
PAPER_FORM_REQUESTER_TYPE = "Individual"  # or "Business"

# ─── Court hearing data ───
COURT_HEARING_FAVORABLE = "Judgment in action of Possessory Lien"
COURT_HEARING_UNFAVORABLE = "Unfavorable"

# ─── Performance thresholds (ms) ───
PAGE_LOAD_THRESHOLD = 5000
SEARCH_RESPONSE_THRESHOLD = 3000
FORM_SUBMIT_THRESHOLD = 10000
REPORT_GENERATE_THRESHOLD = 15000

# ─── Rejection reasons ───
REJECTION_REASONS = [
    "Provide complete serial number",
    "Information looks incomplete",
]

# ─── Close file remarks ───
CLOSE_FILE_REMARKS = "Vehicle reclaimed by owner. Closing file per standard procedure."
