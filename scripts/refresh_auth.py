"""Run all portal auth scripts in sequence to regenerate saved auth states.

Usage (from e2eautomation/):
    python scripts/refresh_auth.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.save_public_auth import main as save_public
from scripts.save_public_user_b_auth import main as save_public_user_b
from scripts.save_staff_auth import main as save_staff
from scripts.save_lsa_auth import main as save_lsa
from scripts.save_fiscal_auth import main as save_fiscal
from scripts.save_individual_auth import main as save_individual

SCRIPTS = [
    ("public (daniel_scott)",       save_public),
    ("public_user_b (mora_333)",     save_public_user_b),
    ("staff (Fowler123)",            save_staff),
    ("lsa (rahulg)",                 save_lsa),
    ("fiscal (nssadmin)",            save_fiscal),
    ("individual (Automation_act)",  save_individual),
]


def main():
    passed, failed = [], []
    total_start = time.time()

    for name, fn in SCRIPTS:
        print(f"\n{'='*55}")
        print(f"  Authenticating: {name}")
        print(f"{'='*55}")
        start = time.time()
        try:
            fn()
            elapsed = time.time() - start
            print(f"  PASS  done in {elapsed:.1f}s")
            passed.append(name)
        except Exception as exc:
            elapsed = time.time() - start
            print(f"  FAIL  {elapsed:.1f}s -- {exc}")
            failed.append(name)

    print(f"\n{'='*55}")
    print(f"  Auth refresh complete -- {len(passed)} passed, {len(failed)} failed")
    print(f"  Total time: {time.time() - total_start:.1f}s")
    if failed:
        print("  Failed portals:")
        for name in failed:
            print(f"    - {name}")
        sys.exit(1)
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
