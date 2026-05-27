"""
acceptance_gmi.py — verify GMI regime is reachable with real DB data.
Run:  docker exec macro-dashboard python /app/tests/acceptance_gmi.py
"""
import sys
sys.path.insert(0, "/app")

import db_manager as db
from macro_index import compute_macro_index

R = db.read

keys_info = db.list_keys()
real_keys = [k for k in keys_info if not str(k.get("key", "")).startswith("_")]
print(f"DB keys: {len(real_keys)} real, {len(keys_info)-len(real_keys)} internal")

# Build the minimal data dict compute_macro_index needs
data = {
    "VIX":              R("vix"),
    "US_PMI":           R("ism_pmi"),
    "TW_PMI":           R("taiwan_pmi"),
    "CN_PMI":           R("china_nbs_pmi"),
    "JP_PMI":           R("japan_watchers"),
    "EU_PMI":           R("eurostat_ici"),
    "NDC_LEADING":      R("ndc_leading"),
    "TSMC_REVENUE_YOY": R("tsmc_revenue_yoy"),
    "US_CLI":           R("cli_us"),
    "CN_CLI":           R("cli_cn"),
    "JP_CLI":           R("cli_jp"),
    "EU_CLI":           R("cli_eu"),
    "KR_CLI":           R("cli_kr"),
    "SEMI_PPI":         R("semi_ppi"),
    "COPPER_YOY":       R("copper_yoy"),
    "CN_PPI_YOY":       R("china_ppi_yoy"),
    "HY_SPREAD":        R("hy_spread"),
    "T10Y2Y":           R("t10y2y"),
    "CREDIT_IMPULSE":   R("china_credit"),
    "TWD_USD":          R("twd_usd"),
    "TAIEX_YOY":        R("taiex_yoy"),
    "SP500_YOY":        R("sp500_yoy"),
    "FED_FUNDS":        R("fed_funds"),
    "T10Y3M":           R("t10y3m"),
    "TW_INSTITUTIONAL": R("tw_institutional"),
}

# Fill in any missing None with empty DataFrame
import pandas as pd
for k in list(data):
    if data[k] is None:
        data[k] = pd.DataFrame()

gmi = compute_macro_index(data)
signals = gmi["signals"]
valid = [s for s in signals if s["has_data"]]
missing = [s for s in signals if not s["has_data"]]

print(f"\nGMI result:")
print(f"  score      = {gmi['score']:.1f} / {len(valid)}")
print(f"  valid_count= {gmi['valid_count']}")
print(f"  diffusion  = {gmi['diffusion']:.1%}")
print(f"  regime     = {gmi['regime']}")

print(f"\nSignals with data ({len(valid)}):")
for s in valid:
    sign = "+" if s["score"] > 0 else ("-" if s["score"] < 0 else "0")
    print(f"  [{sign}] #{s['id']:2d} {s['name']}")

if missing:
    print(f"\nMissing data ({len(missing)}):")
    for s in missing:
        print(f"  [?] #{s['id']:2d} {s['name']}")
