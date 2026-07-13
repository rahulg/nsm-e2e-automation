import random
import string
from datetime import datetime, timedelta


def generate_vin() -> str:
    chars = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"
    return "".join(random.choice(chars) for _ in range(17))


def generate_license_plate() -> str:
    letters = string.ascii_uppercase
    digits = string.digits
    return "".join(random.choice(letters) for _ in range(3)) + "-" + "".join(random.choice(digits) for _ in range(4))


def generate_address() -> dict:
    streets = ["123 Main Street", "456 Oak Avenue", "789 Elm Drive", "321 Pine Lane", "654 Maple Court"]
    cities = [
        {"city": "Raleigh", "zip": "27601", "county": "Wake"},
        {"city": "Charlotte", "zip": "28202", "county": "Mecklenburg"},
        {"city": "Durham", "zip": "27701", "county": "Durham"},
        {"city": "Greensboro", "zip": "27401", "county": "Guilford"},
        {"city": "Wilmington", "zip": "28401", "county": "New Hanover"},
    ]
    street = random.choice(streets)
    location = random.choice(cities)
    return {
        "street": street,
        "city": location["city"],
        "state": "NC",
        "zip": location["zip"],
        "county": location["county"],
    }


def future_date(days_from_now: int) -> str:
    return (datetime.now() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def today_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def past_date(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


FIRST_NAMES = ["John", "Jane", "Robert", "Maria", "James", "Patricia"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Davis"]


def generate_person() -> dict:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    return {
        "name": f"{first} {last}",
        "email": f"{first.lower()}.{last.lower()}@test.com",
        "phone": f"919{random.randint(1000000, 9999999)}",
    }


def generate_first_name() -> str:
    return random.choice(FIRST_NAMES)


def generate_last_name() -> str:
    return random.choice(LAST_NAMES)


def generate_full_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def generate_job_title() -> str:
    titles = ["Manager", "Owner", "Operations Lead", "Office Administrator", "Supervisor", "Coordinator"]
    return random.choice(titles)


def generate_company_name() -> str:
    prefixes = ["Carolina", "Piedmont", "Tarheel", "Blue Ridge", "Coastal", "Triangle"]
    suffixes = ["Towing", "Auto Salvage", "Recovery Services", "Garage", "Storage Yard", "Auto Body"]
    return f"{random.choice(prefixes)} {random.choice(suffixes)}"


def generate_location_name() -> str:
    names = ["Main Lot", "North Yard", "South Facility", "Downtown Branch", "Highway Storage", "East Depot"]
    return random.choice(names)


def generate_reference_hash() -> str:
    import time
    return f"REF-{int(time.time())}-{random.randint(0, 999)}"


SAMPLE_VEHICLES = [
    {"make": "Toyota", "year": "2018", "body": "Sedan", "model": "Camry", "color": "Silver"},
    {"make": "Honda", "year": "2020", "body": "SUV", "model": "CR-V", "color": "Black"},
    {"make": "Ford", "year": "2015", "body": "Pick-Up Truck", "model": "F-150", "color": "White"},
    {"make": "Chevrolet", "year": "2019", "body": "Sedan", "model": "Malibu", "color": "Blue"},
    {"make": "Nissan", "year": "2017", "body": "SUV", "model": "Rogue", "color": "Red"},
]


def random_vehicle() -> dict:
    return random.choice(SAMPLE_VEHICLES)
