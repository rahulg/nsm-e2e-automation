import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

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
