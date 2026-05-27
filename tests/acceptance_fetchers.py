"""
acceptance_fetchers.py — live HTTP test for the 5 rewritten fetchers.
Run inside the container:  docker exec macro-dashboard python tests/acceptance_fetchers.py
"""
import sys
sys.path.insert(0, "/app")

tests = {}

def run(name, fn):
    try:
        df = fn()
        if df.empty:
            tests[name] = "EMPTY"
        else:
            latest = df.iloc[-1]
            tests[name] = f"OK  rows={len(df)}  latest={latest['date'].date()}  val={latest['value']:.2f}"
    except Exception as e:
        tests[name] = f"ERROR  {e}"

from fetchers.global_macro import (
    fetch_china_nbs_pmi, fetch_china_nbs_ppi_yoy,
    fetch_ndc_leading_index, fetch_ndc_light_score,
)
from fetchers.fred import fetch_china_credit_impulse
from fetchers.taiwan import fetch_tsmc_revenue_yoy

run("cn_pmi",         fetch_china_nbs_pmi)
run("cn_ppi",         fetch_china_nbs_ppi_yoy)
run("ndc_leading",    fetch_ndc_leading_index)
run("ndc_light",      fetch_ndc_light_score)
run("credit_impulse", fetch_china_credit_impulse)
run("tsmc_yoy",       fetch_tsmc_revenue_yoy)

print("\n=== Fetcher Acceptance Test ===")
all_ok = True
for k, v in tests.items():
    status = "PASS" if v.startswith("OK") else "FAIL"
    if not v.startswith("OK"):
        all_ok = False
    print(f"  [{status}]  {k:<22} {v}")
print()
print("RESULT:", "ALL PASSED" if all_ok else "SOME FAILED")
sys.exit(0 if all_ok else 1)
