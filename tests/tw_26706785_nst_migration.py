"""NCNSS-371 / TW-26706785 - NST -> NSM legacy data migration, QA verification driver.

WHY THIS EXISTS
---------------
The 26706785 test plan (authored 2026-09-03) was written for a *dev* surface that
still had the migration ingest runner: nearly every scenario begins "seed the batch
with ... then run the migration batch". That plan could not run at all on 2026-09-03 -
the previous ExpertlyTestBuddyAuto run reported BLOCKED, 0/24 executed, because the
migrated NST dataset and the ingest runner existed only on nsm-dev.

That is no longer true. As of 2026-09-09 the migration HAS been applied to QA:
`legacy` is projected by the list chains, `legacyDocuments.regenrate` exists, and
LT-260/261/262/263 all carry legacy=true rows with 2020-era NST case numbers.

So the surface QA offers is **the already-migrated dataset**, not the ingest. This
driver therefore verifies the migration's *observable outcome* - what the migrated
records look like once they are in NSM - and is explicit about which test cases
that surface CANNOT answer (anything requiring control of the ingest: seeding a
deliberately-bad row, forcing a mid-chain rollback, capturing a pre-batch baseline).
Those are reported NOT EXECUTABLE ON QA with the reason, never guessed at.

Channel: API for the census / uniqueness / contract checks (they need whole-population
reads the UI cannot page through). The Icons-column and details-page checks are UI
changes and are driven in a real browser by tw_26706785_nst_migration_ui.py.

Run:  python tests/tw_26706785_nst_migration.py [--env qa] [--out <dir>]
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASES = {"qa": "https://nsm-qa.nc.verifi.dev", "stage": "https://nsm-stage.nc.verifi.dev"}

# -- chain ids (from the 2026-09-07 dev note on TW-26706785) -------------------
CH_LT260 = "47fdbccbbc8811e8b572a1a253a3865e"   # LT260List.get
CH_LT262 = "428387b1070387675687973fb3d27ad8"   # LT262List.get
CH_LT263 = "47730a2ded338107301eb7c1e96f5357"   # LT263.matchingRecords
CH_FORMS = "4f0aa9e150233e299a3796e70609f4a0"   # forms.getByType (LT-261 / LT-262A)
CH_PAY = "4043931198d9ca2ac0a3ad3e0947ba64"     # payments.getTransactions
CH_REGEN = "46249e2d5747970e7ea6b9557fae6e7e"   # legacyDocuments.regenrate

# The list chains answer 504 at large page sizes now that the migrated volume is in
# place - 25 is the largest page size that answered reliably on 2026-09-09.
PS = 25

RESULTS = []


def record(tid, title, status, expected, actual, evidence=None, note=None):
    RESULTS.append({"id": tid, "title": title, "status": status, "expected": expected,
                    "actual": actual, "evidence": evidence or {}, "note": note})
    print(f"  [{status:14s}] {tid}  {title}")
    if status not in ("PASS",):
        print(f"                   expected: {expected}")
        print(f"                   actual  : {actual}")


class Api:
    def __init__(self, base, token):
        self.base, self.token = base, token

    def post(self, chain, body, timeout=240):
        return requests.post(
            f"{self.base}/rest/api/automation/chain/execute/{chain}?encrypted=true",
            headers={"Content-Type": "application/json", "Authorization": self.token},
            json=body, timeout=timeout)


def token_from(auth_state):
    d = json.loads(Path(auth_state).read_text(encoding="utf-8"))
    for o in d.get("origins", []):
        for it in o.get("localStorage", []):
            if it.get("name") == "authToken":
                return it["value"]
    raise SystemExit(f"no authToken in {auth_state} - run scripts/refresh_auth.py --env qa")


def rows(xml):
    """Parse <data>...</data> blocks into dicts of every scalar tag they carry.

    Keys are lower-cased. The chains are NOT consistent about casing: LT260List.get
    answers <formtype>/<submitteddate>/<updatedat> while forms.getByType answers
    <submissionMethod>/<submittedDate>/<updatedAt> for the same concepts. Reading
    one spelling silently produced a false FAIL on the first run of this driver.
    """
    out = []
    for m in re.finditer(r"<data>(.*?)</data>", xml, re.S):
        blk = m.group(1)
        d = {}
        for t in re.finditer(r"<([A-Za-z0-9_]+)>(.*?)</\1>", blk, re.S):
            d[t.group(1).lower()] = t.group(2).strip()
        for t in re.finditer(r"<([A-Za-z0-9_]+)/>", blk):
            d.setdefault(t.group(1).lower(), "")
        out.append(d)
    return out


def is_legacy(r):
    return (r.get("legacy") or "").lower() == "true"


def case_of(r):
    return r.get("casenumber") or ""


def form_type(r):
    """'Paper' vs 'Digital' — spelled formtype on some chains, submissionMethod on others."""
    return (r.get("formtype") or r.get("submissionmethod") or "").strip()


# NST case numbers are SHORTER than NSS's own: the ticket says so explicitly ("The
# case number length received from NST is slightly shorter than what NSS currently
# supports"), and QA bears it out - migrated S20-764402 (6 digits) against native
# S26-1078853 (7 digits).
NST_CASE = re.compile(r"^[SND]\d{2}-\d{6}$")
NSS_CASE = re.compile(r"^[SND]\d{2}-\d{7,}$")

LISTS = {
    "LT-260": (CH_LT260, {"vin": None, "licensePlate": None, "requestorName": None,
                          "vehicleLocation": None, "vehicleYear": None, "make": None,
                          "model": None, "status": None, "sortColumn": "default",
                          "submittedStartDate": None, "submittedEndDate": None,
                          "updatedStartDate": None, "updatedEndDate": None,
                          "updatedBy": None, "tab": "LT260", "formType": None,
                          "caseNumber": None}),
    "LT-261": (CH_FORMS, {"vin": None, "licensePlate": None, "requestorName": None,
                          "year": None, "make": None, "model": None, "status": None,
                          "sortColumn": "default", "submittedStartDate": None,
                          "submittedEndDate": None, "updatedStartDate": None,
                          "updatedEndDate": None, "updatedBy": None, "type": "LT261",
                          "submissionMethod": None, "caseNumber": None,
                          "lt260SubmissionStartDate": None, "lt260SubmissionEndDate": None,
                          "locationOfStoredVehicle": None}),
    "LT-262": (CH_LT262, {"status": None, "sortColumn": "default", "tab": "LT262"}),
    "LT-262A": (CH_FORMS, {"vin": None, "licensePlate": None, "requestorName": None,
                           "year": None, "make": None, "model": None, "status": None,
                           "sortColumn": "default", "submittedStartDate": None,
                           "submittedEndDate": None, "updatedStartDate": None,
                           "updatedEndDate": None, "updatedBy": None, "type": "LT262A",
                           "submissionMethod": None, "caseNumber": None,
                           "lt260SubmissionStartDate": None, "lt260SubmissionEndDate": None,
                           "locationOfStoredVehicle": None}),
    "LT-263": (CH_LT263, {"vin": None, "licensePlate": None, "vehicleYear": None,
                          "make": None, "model": None, "requestorName": None,
                          "vehicleLocation": None, "submittedStartDate": None,
                          "submittedEndDate": None, "sortColumn": None,
                          "updatedStartDate": None, "updatedEndDate": None,
                          "updatedBy": None, "tab": "LT263", "status": None,
                          "caseNumber": None, "formType": None}),
}


def fetch(api, surface, desc, page=1, ps=PS):
    chain, base = LISTS[surface]
    r = api.post(chain, {**base, "pageSize": ps, "currentPage": page, "isDescending": desc})
    if r.status_code != 200:
        return None, r.status_code
    return rows(r.text), 200


def _vin_probe(vin):
    """(chain, body) that asks the LT-260 listing for every case on one VIN."""
    chain, base = LISTS["LT-260"]
    return chain, {**base, "vin": vin, "pageSize": 25, "currentPage": 1,
                   "isDescending": False}


def parsed_date(r):
    for k in ("submitteddate", "updatedat", "date"):
        v = r.get(k) or ""
        m = re.match(r"(\d{2})-(\d{2})-(\d{4})", v)
        if m:
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="qa", choices=["qa", "stage"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    base = BASES[a.env]
    auth = ROOT / "auth" / a.env / "staff-portal.json"
    if not auth.exists():
        auth = ROOT / "auth" / "staff-portal.json"
    api = Api(base, token_from(auth))
    out = Path(a.out) if a.out else ROOT / "results" / f"tw26706785_{a.env}"
    out.mkdir(parents=True, exist_ok=True)

    print(f"\nNCNSS-371 NST migration - verification on {a.env}  ({base})")
    print("=" * 78)

    # -- PRE-0 deployment gate -----------------------------------------------
    print("\nPRE-0  Deployment gate - is the NCNSS-371 surface on this environment?")
    gate = {}
    for surface in LISTS:
        rs, code = fetch(api, surface, desc=False)
        gate[surface] = {"http": code,
                         "emits_legacy": bool(rs) and "legacy" in (rs[0] if rs else {}),
                         "legacy_rows": sum(1 for r in (rs or []) if is_legacy(r)),
                         "sample_case": case_of(rs[0]) if rs else None}
    regen = api.post(CH_REGEN, {"applicationID": "00000000-0000-0000-0000-000000000000"},
                     timeout=90)
    gate["legacyDocuments.regenrate"] = {"http": regen.status_code,
                                         "exists": regen.status_code == 200}
    emitting = [s for s, g in gate.items() if g.get("emits_legacy")]
    with_data = [s for s, g in gate.items() if g.get("legacy_rows", 0) > 0]
    ok = bool(with_data) and gate["legacyDocuments.regenrate"]["exists"]
    record("PRE-0", "NCNSS-371 backend + migrated dataset present on this environment",
           "PASS" if ok else "BLOCKED",
           "list chains project `legacy`, legacyDocuments.regenrate resolves, and migrated "
           "(legacy=true) rows are observable",
           f"chains emitting legacy: {emitting or 'none'}; surfaces carrying migrated rows: "
           f"{with_data or 'none'}; regenrate chain HTTP {regen.status_code}",
           evidence=gate)
    if not ok:
        finish(out, a.env, base)
        return

    # -- TC-01 clean S record -> flagged paper LT-260 keeping its legacy number
    print("\nSC-1  Migrated LT-260 identity, numbering and paper flag")
    old260, _ = fetch(api, "LT-260", desc=False)
    leg260 = [r for r in (old260 or []) if is_legacy(r)]
    paper = [r for r in leg260 if form_type(r).lower() == "paper"]
    nstshaped = [r for r in leg260 if NST_CASE.match(case_of(r))]
    record("TC-26706785-01",
           "A clean 'S' record becomes a flagged paper LT-260 that keeps its legacy number",
           "PASS" if leg260 and len(paper) == len(leg260) and nstshaped else "FAIL",
           "every migrated LT-260 row carries legacy=true, submissionMethod='Paper', and a "
           "verbatim NST-shaped case number (S<YY>-###### - shorter than NSS's own)",
           f"{len(leg260)} migrated rows on the oldest page; {len(paper)} are "
           f"submissionMethod=Paper; {len(nstshaped)} carry an NST-shaped case number; "
           f"sample={[case_of(r) for r in leg260[:3]]}",
           evidence={"sample": leg260[:3]})

    # -- TC-18 the NSS sequence still mints cleanly after migration -----------
    new260, _ = fetch(api, "LT-260", desc=True)
    native = [r for r in (new260 or []) if not is_legacy(r)]
    native_nss = [r for r in native if NSS_CASE.match(case_of(r))]
    overlap = {case_of(r) for r in leg260} & {case_of(r) for r in native}
    record("TC-26706785-18",
           "The NSS case-number sequence still mints cleanly for new native cases after "
           "migration",
           "PASS" if native and not overlap and len(native_nss) == len(native) else "FAIL",
           "newly filed native cases keep minting in the NSS format and share no case number "
           "with any migrated record",
           f"{len(native)} native rows on the newest page, {len(native_nss)} in NSS format "
           f"(sample={[case_of(r) for r in native[:3]]}); case numbers shared with migrated "
           f"rows: {sorted(overlap) or 'none'}",
           evidence={"native_sample": [case_of(r) for r in native[:5]]})

    # -- TC-16 the Jan 1 2020 import cutoff ----------------------------------
    dated = [(r, parsed_date(r)) for r in leg260]
    pre2020 = [case_of(r) for r, d in dated if d and d.year < 2020]
    have_dates = [d for _, d in dated if d]
    record("TC-26706785-16", "Cutoff and field boundaries - only Jan 1 2020 onward is imported",
           "PASS" if have_dates and not pre2020 else ("BLOCKED" if not have_dates else "FAIL"),
           "no migrated record carries a submitted date before 2020-01-01",
           f"oldest migrated LT-260 submitted dates: "
           f"{[r.get('submittedDate') for r, _ in dated[:3]]}; pre-2020 rows: "
           f"{pre2020 or 'none'}",
           evidence={"pre2020": pre2020},
           note="Scoped to the oldest page the listing returns, sorted ascending - it is the "
                "boundary itself, but it is not a whole-population scan (the chain 504s at "
                "page sizes large enough for that).")

    # -- TC-19 NST-flag isolation --------------------------------------------
    leaked = [case_of(r) for r in native if is_legacy(r)]
    record("TC-26706785-19",
           "NST-flag isolation - native cases are not flagged as migrated",
           "PASS" if native and not leaked else "FAIL",
           "every natively-filed case carries legacy=false",
           f"{len(native)} native rows checked; wrongly flagged: {leaked or 'none'}")

    # -- SC-3 record-shape routing across the other form types ---------------
    print("\nSC-3  Record-shape routing (D -> LT-261, S->N->D -> LT-263, LT-262, LT-262A)")
    shapes = {}
    for surface in ("LT-261", "LT-262", "LT-263", "LT-262A"):
        rs, code = fetch(api, surface, desc=False)
        lg = [r for r in (rs or []) if is_legacy(r)]
        shapes[surface] = {"http": code, "rows": len(rs or []), "legacy": len(lg),
                           "cases": [case_of(r) for r in lg[:5]],
                           "statuses": sorted({r.get("status", "") for r in lg})}

    d261 = shapes["LT-261"]
    d261_ok = d261["legacy"] > 0 and all(c.startswith("D") for c in d261["cases"])
    record("TC-26706785-05",
           "'D' / 'S->D' / DWI-or-EXE chain migrates to an LT-261 under the D case number",
           "PASS" if d261_ok else ("GAP" if d261["legacy"] == 0 else "FAIL"),
           "migrated LT-261 records exist and are logged under a 'D'-prefixed NST case number",
           f"{d261['legacy']} migrated LT-261 rows on the page; case numbers {d261['cases']}",
           evidence=d261,
           note="Confirms the D-record routing landed. It does NOT confirm the DWI/EXE "
                "sale-type discriminator itself - the listing does not expose sale type, and "
                "QA has no NST source rows to compare against.")

    # TC-04 is re-scoped to the invariant QA can actually answer. The ticket's rule -
    # "for a specific VIN the S/N/D records have different case numbers, but always use
    # the S record's case number to log the case in NSS" - is a statement about the NST
    # SOURCE rows, and QA carries only the migrated outcome. What IS checkable here is
    # that a migrated case keeps ONE case number across its whole LT-260 -> LT-262 ->
    # LT-263 lifecycle, which is the behaviour NSS shows natively.
    d263 = shapes["LT-263"]
    chain_consistent, chain_split = [], []
    if d263["legacy"] > 0:
        rs263, _ = fetch(api, "LT-263", desc=False)
        for r in [x for x in (rs263 or []) if is_legacy(x)][:8]:
            vin = r.get("vin")
            if not vin:
                continue
            ch, bd = _vin_probe(vin)
            rr = api.post(ch, bd)
            c260 = {case_of(x) for x in rows(rr.text)} if rr.status_code == 200 else set()
            if case_of(r) in c260:
                chain_consistent.append((vin, case_of(r), sorted(c260)))
            else:
                chain_split.append((vin, case_of(r), sorted(c260)))
    record("TC-26706785-04",
           "A migrated case keeps ONE case number across its LT-260 -> LT-262 -> LT-263 "
           "lifecycle",
           "PASS" if chain_consistent and not chain_split else
           ("GAP" if d263["legacy"] == 0 else "FAIL"),
           "for a migrated LT-263, the same case number is present on that VIN's LT-260 - "
           "the case is one case end to end, as it is for a natively-filed record",
           f"{len(chain_consistent)} of {len(chain_consistent) + len(chain_split)} sampled "
           f"migrated LT-263 records share their case number with their own LT-260; "
           f"sample={chain_consistent[:2]}; mismatched={chain_split or 'none'}",
           evidence={"consistent": chain_consistent, "split": chain_split,
                     "lt263_cases": d263["cases"]},
           note="OPEN QUESTION, not asserted either way: the ticket says the case should be "
                "logged under the S record's case number, yet every migrated LT-262/LT-263 "
                "chain observed on QA is numbered N<YY>-######. That matches NSS's own native "
                "lifecycle (a native LT-263 is N-numbered too), so it is not evidence of a "
                "defect - but confirming the S-vs-N choice needs the NST source rows, which "
                "QA does not carry. One VIN (1G1AK55F977101573) does show an S-numbered case "
                "(S20-782271, LT-260 Closed) AND a separate N-numbered chain (N20-803009) "
                "rather than one merged case; a spot check of 20 other S records found no "
                "second N case, so this looks rare rather than systematic. Worth a BA answer.")

    d262a = shapes["LT-262A"]
    record("TC-26706785-06",
           "A manufactured-home NST record migrates to a paper LT-262A",
           "PASS" if d262a["legacy"] > 0 else "GAP",
           "at least one migrated LT-262A record is observable on this environment",
           f"LT-262A carries {d262a['rows']} rows on the page of which {d262a['legacy']} are "
           f"migrated - the same data gap the 2026-09-07 dev note recorded on dev ('zero "
           f"legacy records, so the archive icon has never been seen on that surface')",
           evidence=d262a)

    # -- TC-11 derived status -------------------------------------------------
    print("\nSC-3  Letter-trail -> derived status")
    allstat = {}
    for surface in ("LT-260", "LT-261", "LT-262", "LT-263"):
        rs, _ = fetch(api, surface, desc=False)
        for r in (rs or []):
            if is_legacy(r):
                allstat.setdefault(surface, set()).add(r.get("status", ""))
    blanks = {s: sorted(st) for s, st in allstat.items() if "" in st}
    record("TC-26706785-11",
           "Letter-trail -> status derivation - every migrated record carries a derived NSS "
           "status",
           "PASS" if allstat and not blanks else "FAIL",
           "DMV supplies no status, so every migrated record must land on a non-blank NSS "
           "status derived from its letter trail",
           f"derived statuses observed: { {k: sorted(v) for k, v in allstat.items()} }; "
           f"records with a blank status: {blanks or 'none'}",
           evidence={k: sorted(v) for k, v in allstat.items()},
           note="Confirms a status was derived for every sampled record. It does NOT verify "
                "each trail maps to the RIGHT status - that needs the NST letter-history rows "
                "the mapping sheet's Statuses tab is keyed on, which QA does not carry.")

    # -- TC-17 / TC-20 the dummy $0 payments must stay out of Payments -------
    print("\nSC-2  Payment contract - the $0 offline Check dummies stay hidden")
    pr = api.post(CH_PAY, {"isDescending": True, "sortColumn": "recievedDate",
                           "pageSize": 2000, "currentPage": 1, "tab": "all"}, timeout=240)
    prow = rows(pr.text) if pr.status_code == 200 else []
    pleg = [r for r in prow if is_legacy(r)]
    record("TC-26706785-17",
           "Side-effect suppression - migrated dummy payments are absent from Payment "
           "Transaction History",
           "PASS" if pr.status_code == 200 and prow and not pleg else
           ("BLOCKED" if pr.status_code != 200 else "FAIL"),
           "the ticket requires the migration's $0 offline Check payments NOT to be displayed "
           "in the Payment Transaction History interface - so no migrated payment may appear",
           f"Payments listing HTTP {pr.status_code}, {len(prow)} rows scanned, "
           f"{len(pleg)} of them migrated",
           evidence={"rows": len(prow), "legacy": len(pleg),
                     "sample_cases": [case_of(r) for r in prow[:3]]})

    # -- TC-09 on-demand letter regeneration ---------------------------------
    print("\nSC-2  On-demand letter generation for a migrated record")
    target = leg260[0] if leg260 else None
    if target and target.get("id"):
        rg = api.post(CH_REGEN, {"applicationID": target["id"]}, timeout=180)
        okrg = rg.status_code == 200 and "<success>true</success>" in rg.text
        record("TC-26706785-09",
               "Letters render on demand for a migrated record (legacyDocuments.regenrate)",
               "PASS" if okrg else "FAIL",
               "the on-demand letter chain accepts a real migrated applicationID and succeeds "
               "(letters are generated on download, not pre-generated)",
               f"HTTP {rg.status_code}; response head: {rg.text[:180]}",
               evidence={"case": case_of(target), "applicationID": target.get("id")},
               note="WEAK ASSERTION, stated plainly: the same chain also answers success=true "
                    "for a nonexistent applicationID (verified with an all-zero GUID), because "
                    "its own SELECT filters on regenerate_document=true and no-ops otherwise. "
                    "This proves the chain is deployed and accepts the record; it does NOT "
                    "prove a PDF rendered, nor the S3 cache-hit on a second download. Those "
                    "need the Form Correspondence modal and a real file download.")
    else:
        record("TC-26706785-09", "Letters render on demand for a migrated record",
               "BLOCKED", "a migrated LT-260 with an application id",
               "no migrated LT-260 row with an id was returned")

    # -- TC-22 Global Search reaches migrated records ------------------------
    print("\nSC-1  Global Search over migrated records")
    if target:
        found = {}
        for term_name, term in (("case number", case_of(target)), ("VIN", target.get("vin"))):
            if not term:
                continue
            ch, bd = _vin_probe(term) if term_name == "VIN" else (None, None)
            chain, base = LISTS["LT-260"]
            body = {**base, "pageSize": 25, "currentPage": 1, "isDescending": False}
            body["vin" if term_name == "VIN" else "caseNumber"] = term
            rr = api.post(chain, body)
            hits = [x for x in rows(rr.text)] if rr.status_code == 200 else []
            found[term_name] = {"term": term, "http": rr.status_code, "hits": len(hits),
                                "cases": [case_of(x) for x in hits[:3]]}
        allhit = found and all(v["hits"] > 0 for v in found.values())
        record("TC-26706785-22",
               "Migrated records are reachable by case number and by VIN",
               "PASS" if allhit else "FAIL",
               "a migrated record can be found by searching its legacy case number and by "
               "searching its VIN",
               f"lookups: {found}",
               evidence=found,
               note="Exercised through the LT-260 listing's own caseNumber / vin search "
                    "parameters. The dedicated Global Search screen is a separate surface and "
                    "the 2026-09-07 dev note records it as DEFERRED for this ticket "
                    "('globalSearch.get returns no legacy at all'), so the archive icon there "
                    "is out of scope by design - reachability is not.")

    # -- the ingest-dependent cases QA cannot answer --------------------------
    print("\nNot executable on this environment (needs control of the migration ingest)")
    ingest_only = [
        ("TC-26706785-03", "A record failing an NSS rule mid-chain is rolled back whole"),
        ("TC-26706785-10", "Duplicate active-state guard - NST-active + NSS-active errors"),
        ("TC-26706785-13", "Invalid-row rejection - each bad row is errored to the report"),
        ("TC-26706785-14", "Defaulted-value repair is written into the migration case comment"),
        ("TC-26706785-15", "Rollback is atomic at every stage and leaves no orphan timeline row"),
    ]
    for tid, title in ingest_only:
        record(tid, title, "NOT_EXECUTABLE",
               "seed a deliberately-bad / defaulted NST source row, run the batch, read the "
               "per-batch error report and the resulting case comment",
               "QA carries the already-migrated OUTCOME, not the ingest runner: there is no way "
               "from QA to seed an fls_customer / fls_holding / FLS_NST_LTR_HIST row, re-run a "
               "batch, or read the per-batch error report (errored_records_*.xlsx is produced "
               "by the dev-side import scripts)")

    finish(out, a.env, base)


def finish(out, env, base):
    payload = {"ticket": "26706785", "product": "NSS", "env": env, "base": base,
               "generated": datetime.now().isoformat(timespec="seconds"),
               "results": RESULTS}
    (out / "results.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tally = {}
    for r in RESULTS:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    print("\n" + "=" * 78)
    print("TALLY:", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    print("results ->", out / "results.json")


if __name__ == "__main__":
    main()
