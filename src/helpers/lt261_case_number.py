"""LT-261 case-number census + direct-submit helpers  (TW 27366957).

WHY THIS EXISTS
---------------
The 27366957 test plan is almost entirely about a value that only Postgres can
authoritatively answer (`lt261_case_number_seq.last_value`, the
`lt261_case_number_sequence` row count, `GROUP BY case_number HAVING COUNT(*)>1`).
The NSM e2e suite has **no database access at all** — no psycopg / sqlalchemy /
pymysql anywhere, and no DB driver in requirements.txt.

Rather than fabricate SQL results, every uniqueness invariant is proven through
the product's own surfaces:

  * **Census** — the LT-261 listing is backed by chain
    ``4f0aa9e150233e299a3796e70609f4a0``, which accepts ``pageSize`` /
    ``currentPage`` / ``caseNumber`` / ``vin``. Asking it for the whole "All" tab
    in one page returns every LT-261 with its ``<caseNumber>``, so the duplicate
    census, the legacy maximum and the per-year bands are all computable
    black-box. (Live-confirmed on QA 2026-07-30: 1061 records returned in one
    call.)
  * **Mint** — the LT-261 submit chain is ``4d1fa71cce16eae7419f8a758186c109``,
    which is *literally the preventive AD method id named in the ticket*. Calling
    it directly is both the TC-15 server-authority probe and the PRE-9
    concurrency harness (a threaded fan-out is genuine parallelism; the suite has
    none otherwise).

What this CANNOT do, and is never faked:
  * read ``pg_sequences.last_value`` / ``is_called`` directly — the sequence
    position is *inferred* from the highest number the product has actually
    issued, which is a lower bound, not the sequence's internal cursor;
  * count rows in ``lt261_case_number_sequence`` — burnt-but-unused values are
    invisible from outside, so "one new sequence row per case" degrades to
    "no case shares a number with another case".
Both limits are stated in the assertions that rely on them.

The listing chain answers XML (``<HashMap><data>…</data>…``), not JSON.
"""

import json
import re
import threading
from pathlib import Path

import requests

LISTING_CHAIN = "4f0aa9e150233e299a3796e70609f4a0"
SUBMIT_CHAIN = "4d1fa71cce16eae7419f8a758186c109"   # = the ticket's preventive AD method
GLOBAL_TABS_CHAIN = "4ab435b126a995d7d8ec84cba3de0be7"

CASE_RE = re.compile(r"D(\d{2})-(\d{6})")

_LISTING_BODY = {
    "vin": None, "licensePlate": None, "requestorName": None, "year": None,
    "make": None, "model": None, "status": None, "currentPage": 1,
    "pageSize": 5000, "sortColumn": "default", "isDescending": True,
    "submittedStartDate": None, "submittedEndDate": None,
    "updatedStartDate": None, "updatedEndDate": None, "updatedBy": None,
    "type": "LT261", "submissionMethod": None, "caseNumber": None,
    "lt260SubmissionStartDate": None, "lt260SubmissionEndDate": None,
    "locationOfStoredVehicle": None,
}


# ---------------------------------------------------------------- auth / http

def auth_token(auth_state: Path) -> str:
    """Read the staff portal's localStorage authToken out of a saved storage state."""
    data = json.loads(Path(auth_state).read_text(encoding="utf-8"))
    for origin in data.get("origins", []):
        for item in origin.get("localStorage", []):
            if item.get("name") == "authToken":
                return item["value"]
    raise AssertionError(
        f"EXPECTED: an authToken in the saved storage state {auth_state} | "
        f"ACTUAL: none — re-run scripts/refresh_auth.py --env qa"
    )


def chain_url(base: str, chain: str) -> str:
    return f"{base.rstrip('/')}/rest/api/automation/chain/execute/{chain}?encrypted=true"


def post_chain(base: str, token: str, chain: str, body: dict, timeout: int = 90):
    return requests.post(
        chain_url(base, chain),
        headers={"Content-Type": "application/json", "Authorization": token},
        json=body,
        timeout=timeout,
    )


# ------------------------------------------------------------------- parsing

def parse_records(xml_text: str) -> list:
    """Parse the listing chain's <data>…</data> blocks into dicts."""
    out = []
    for m in re.finditer(r"<data>(.*?)</data>", xml_text, re.S):
        blk = m.group(1)

        def f(tag):
            mm = re.search(rf"<{tag}>(.*?)</{tag}>", blk, re.S)
            return (mm.group(1) if mm else "").strip()

        out.append({
            "id": f("id"), "vin": f("vin"), "case": f("caseNumber"),
            "submitted": f("submittedDate"), "updated": f("updatedAt"),
            "status": f("status"), "method": f("submissionMethod"),
            "submitter": f("submitterName"),
        })
    return out


def six(case: str) -> int:
    m = CASE_RE.fullmatch((case or "").strip())
    assert m, f"not a D[YY]-nnnnnn case number: {case!r}"
    return int(m.group(2))


def prefix(case: str) -> str:
    return (case or "")[:3]


# -------------------------------------------------------------------- census

def census(base: str, token: str, **overrides) -> list:
    """Every LT-261 the 'All' tab can see, as parsed records."""
    body = dict(_LISTING_BODY)
    body.update(overrides)
    r = post_chain(base, token, LISTING_CHAIN, body)
    assert r.status_code == 200, (
        f"EXPECTED: HTTP 200 from the LT-261 listing chain | ACTUAL: {r.status_code} "
        f"{r.text[:300]}"
    )
    return parse_records(r.text)


def census_via_page(page) -> list:
    """Same census, but issued from inside an authenticated browser page.

    Used by UI-channel tests so the census rides the very session that just
    created the record (no separate token, no auth-drift between the two).
    """
    text = page.evaluate(
        """async ([chain, body]) => {
             const r = await fetch(location.origin + '/rest/api/automation/chain/execute/' + chain + '?encrypted=true', {
               method: 'POST',
               headers: {'Content-Type': 'application/json',
                         'Authorization': localStorage.getItem('authToken')},
               body: JSON.stringify(body)});
             return await r.text();
           }""",
        [LISTING_CHAIN, _LISTING_BODY],
    )
    return parse_records(text)


def numbers(records) -> list:
    return [r["case"] for r in records if CASE_RE.fullmatch(r["case"] or "")]


def duplicates(records) -> dict:
    """{case_number: [records]} for every number held by more than one case."""
    by = {}
    for r in records:
        if CASE_RE.fullmatch(r["case"] or ""):
            by.setdefault(r["case"], []).append(r)
    return {k: v for k, v in by.items() if len(v) > 1}


def high_water(records, year_prefix: str) -> int:
    """Highest 6-digit value the product has actually issued inside `year_prefix`."""
    vals = [six(r["case"]) for r in records if prefix(r["case"]) == year_prefix]
    return max(vals) if vals else 0


def find_by_vin(records, vin: str):
    hits = [r for r in records if (r["vin"] or "").upper() == vin.upper()]
    return hits[0] if hits else None


def case_number_for_vin(base: str, token: str, vin: str) -> str:
    """Server-side readout of the number minted for `vin` (census filtered by VIN)."""
    recs = census(base, token, vin=vin)
    hit = find_by_vin(recs, vin)
    assert hit, (
        f"EXPECTED: the LT-261 for VIN {vin} to be queryable from the listing chain | "
        f"ACTUAL: no record returned"
    )
    return hit["case"]


def cases_holding(base: str, token: str, case_number: str) -> list:
    """Every case that holds `case_number` — the black-box GROUP BY … HAVING COUNT(*)>1."""
    recs = census(base, token, caseNumber=case_number)
    return [r for r in recs if r["case"] == case_number]


# --------------------------------------------------------------- direct mint

def submit_payload(vin: str, officer: str, paper_type: str = "E-Stop", **extra) -> dict:
    """A minimal-but-complete LT-261 submit payload, cloned from a live capture.

    Captured from a real E-Stop submit on QA 2026-07-30 — note there is NO
    caseNumber field: the client never supplies one. TC-15 injects it on purpose.
    """
    body = {
        "vin": vin, "make": "BOYTOY", "year": "2018", "body": None,
        "motorNumber": None, "plateYear": None, "plateState": None,
        "plateNumber": None,
        "locationOfVehicleStored": "953 Spencer Ford",
        "address": "88388 Franecki Circle", "city": "Farmville",
        "state": "North Carolina", "zip": "27828",
        "salePlace": "953 Spencer Ford", "saleAddress": "88388 Franecki Circle",
        "saleCity": "Farmville", "saleState": "North Carolina", "saleZip": "27828",
        "saleHour": "2026-07-30T04:30:00.000Z", "saleDate": "8/20/2026",
        "loggedBy": "8146", "saveAction": "SUBMIT", "draftApplicationID": None,
        "model": None,
        "agencyInformation": {
            "name": officer, "address": "88388 Franecki Circle",
            "city": "Farmville", "state": "North Carolina", "zip": "27828",
            "position": None,
        },
        "authorizedPersonDetails": {
            "nameOfCourt": None, "ownerName": None, "address": None,
            "city": None, "state": None, "zip": None,
        },
        "saleNoticeReason": "Bicycle Law (BIC)",
        "abandonedVehicleSaleDetails": {
            "placeStored": None, "address": None, "zip": None, "city": None,
            "state": None, "salePlace": None, "saleAddress": None,
            "saleCity": None, "saleState": None, "saleZip": None,
            "saleHour": None, "saleDate": None,
        },
        "owners": None, "lessees": None, "leinholders": None,
        "isStolen": False, "paperType": paper_type,
        "vehicleLocationMetadata": None,
    }
    body.update(extra)
    return body


def submit_direct(base: str, token: str, vin: str, officer: str,
                  paper_type: str = "E-Stop", **extra):
    """Fire ONE LT-261 submit straight at the preventive AD method."""
    r = post_chain(base, token, SUBMIT_CHAIN,
                   submit_payload(vin, officer, paper_type, **extra))
    return {"vin": vin, "status": r.status_code, "text": r.text[:1500]}


def submit_parallel(base: str, token: str, jobs: list) -> list:
    """Fire every job in `jobs` SIMULTANEOUSLY (real threads, one socket each).

    PRE-9's harness. `jobs` is a list of dicts: {vin, officer, paper_type}.
    A barrier releases every thread at the same instant so this is a genuine
    race on the sequence, not a serialized replay (the two existing 'concurrent'
    e2e tests drive two tabs strictly sequentially and prove nothing here).
    """
    results = [None] * len(jobs)
    barrier = threading.Barrier(len(jobs))

    def run(i, job):
        try:
            barrier.wait(timeout=60)
        except Exception:
            pass
        try:
            results[i] = submit_direct(
                base, token, job["vin"], job["officer"],
                job.get("paper_type", "E-Stop"))
        except Exception as e:                                # noqa: BLE001
            results[i] = {"vin": job["vin"], "status": -1, "text": f"EXC {e}"}

    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    return results
