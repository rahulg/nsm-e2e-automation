import os
from pathlib import Path
from dotenv import load_dotenv

NSM_ENV = os.getenv("NSM_ENV", "qa")
_env_file = Path(__file__).resolve().parent.parent.parent / f".env.{NSM_ENV}"
load_dotenv(_env_file)

REQUIRED_VARS = [
    "PUBLIC_PORTAL_URL",
    "PUBLIC_PORTAL_USERNAME",
    "PUBLIC_PORTAL_PASSWORD",
    "STAFF_PORTAL_URL",
    "STAFF_PORTAL_USERNAME",
    "STAFF_PORTAL_PASSWORD",
]

for key in REQUIRED_VARS:
    if not os.getenv(key):
        raise EnvironmentError(f"Missing required environment variable: {key}. Check your .env file.")


class ENV:
    # Primary accounts
    PUBLIC_PORTAL_URL = os.environ["PUBLIC_PORTAL_URL"]
    PUBLIC_PORTAL_USERNAME = os.environ["PUBLIC_PORTAL_USERNAME"]
    PUBLIC_PORTAL_PASSWORD = os.environ["PUBLIC_PORTAL_PASSWORD"]
    STAFF_PORTAL_URL = os.environ["STAFF_PORTAL_URL"]
    STAFF_PORTAL_USERNAME = os.environ["STAFF_PORTAL_USERNAME"]
    STAFF_PORTAL_PASSWORD = os.environ["STAFF_PORTAL_PASSWORD"]

    # The garage/business the primary public user acts for. Env-specific: QA's
    # daniel_scott is "G-Car Garages New", stage's rahulg_biz11 is "Piedmont Auto
    # Body". Hardcoding QA's value made every public flow fail at the header business
    # selector on stage.
    PUBLIC_BUSINESS_NAME = os.getenv("PUBLIC_BUSINESS_NAME", "G-Car Garages New")

    # Secondary accounts (optional — for multi-user tests)
    STAFF_USER_B_USERNAME = os.getenv("STAFF_USER_B_USERNAME", "")
    STAFF_USER_B_PASSWORD = os.getenv("STAFF_USER_B_PASSWORD", "")
    PUBLIC_USER_B_USERNAME = os.getenv("PUBLIC_USER_B_USERNAME", "")
    PUBLIC_USER_B_PASSWORD = os.getenv("PUBLIC_USER_B_PASSWORD", "")

    # Fiscal user account (optional — restricted to Reports only)
    FISCAL_USER_USERNAME = os.getenv("FISCAL_USER_USERNAME", "")
    FISCAL_USER_PASSWORD = os.getenv("FISCAL_USER_PASSWORD", "")

    # Individual public user account (optional — for E2E-006 individual user flow)
    INDIVIDUAL_PUBLIC_USERNAME = os.getenv("INDIVIDUAL_PUBLIC_USERNAME", "")
    INDIVIDUAL_PUBLIC_PASSWORD = os.getenv("INDIVIDUAL_PUBLIC_PASSWORD", "")

    # Registered first/last name on the individual account, used in Message Center
    # "Dear <name>," greetings. Env-specific: QA's Automation_act is "Robert Davis",
    # stage's rahulg_indi31 is "Jane Smith" — hardcoding QA's value made every
    # message-greeting assertion fail on stage.
    INDIVIDUAL_ACCOUNT_NAME = os.getenv("INDIVIDUAL_ACCOUNT_NAME", "Robert Davis")

    # Registered email on the individual account — a yopmail.com disposable
    # address, used by Phase 10 of E2E-064 to verify the actual correspondence
    # emails (as opposed to the in-app Message Center).
    INDIVIDUAL_PUBLIC_EMAIL = os.getenv("INDIVIDUAL_PUBLIC_EMAIL", "autotestact000@yopmail.com")

    # Second individual public user (optional — for multi-user individual flows,
    # E2E-064). Its registered email is a mailinator.com address, not yopmail.
    INDIVIDUAL_PUBLIC_USER_B_USERNAME = os.getenv("INDIVIDUAL_PUBLIC_USER_B_USERNAME", "")
    INDIVIDUAL_PUBLIC_USER_B_PASSWORD = os.getenv("INDIVIDUAL_PUBLIC_USER_B_PASSWORD", "")
    INDIVIDUAL_PUBLIC_USER_B_EMAIL = os.getenv("INDIVIDUAL_PUBLIC_USER_B_EMAIL", "")
