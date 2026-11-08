"""Acceptance check for the Taiwan early-warning layer and the 13F ranking, run on production.

    docker exec -i -w /app macro-dashboard python - < tests/acceptance_tw_warning.py

Read-only: prints what the production DB holds and what the page would show.
Exit code 1 when a required series is missing or the light cannot be computed.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")
sys.path.insert(0, ".")

import pandas as pd  # noqa: E402

import db_manager  # noqa: E402
from analytics.smart_money import ETF, OTHER, build_rank_table, classify_sector, looks_like_cusip  # noqa: E402
from analytics.tw_warning import evaluate  # noqa: E402
from analytics.tw_warning_backtest import run_backtest  # noqa: E402
from fetchers.twse_heat import fetch_whale_exit_share  # noqa: E402

KEYS = {
    "TAIEX_DAILY": "taiex_daily", "VIXTWN": "vixtwn", "VIX": "vix", "US_10Y_NOMINAL": "dgs10",
    "TWD_USD": "twd_usd", "DXY_ICE": "dxy_ice", "SOX_DAILY": "sox_daily", "TSMC_DAILY": "tsmc_daily",
    "TW_ADV": "tw_adv", "TW_DEC": "tw_dec", "TW_PCT_MA20": "tw_pct_ma20", "TW_PCT_MA60": "tw_pct_ma60",
    "TW_TURNOVER": "tw_turnover", "TW_FINI_NET": "tw_fini_net", "TW_FINI_FUT_OI": "tw_fini_fut_oi",
    "TW_MARGIN": "tw_margin", "TW_WHALE_EXIT": "tw_whale_exit",
}
OPTIONAL = {"TW_WHALE_EXIT"}

failures = []
data = {}
print("── series ──")
for name, key in KEYS.items():
    df = db_manager.read(key)
    data[name] = df
    if df is None or df.empty:
        tag = "WARN" if name in OPTIONAL else "FAIL"
        if tag == "FAIL":
            failures.append(name)
        print(f"[{tag}] {key:16s} empty")
        continue
    d = pd.to_datetime(df["date"])
    print(f"[PASS] {key:16s} {len(df):5d} rows  {d.min():%Y-%m-%d} → {d.max():%Y-%m-%d}  last={df['value'].iloc[-1]:.2f}")

closes = db_manager.read("tw_stock_close")
print(f"tw_stock_close: {0 if closes is None else len(closes)} rows")

print("── light ──")
w = evaluate(data)
if not w.get("available"):
    failures.append("evaluate")
    print("[FAIL] light unavailable")
else:
    print(f"as of {w['as_of']:%Y-%m-%d}: {w['info']['label']} {w['count']}/{w['n_signals']} "
          f"exposure {w['exposure']:.0%} (raw {w['raw_info']['label']})")
    for s in w["signals"]:
        state = "stale" if s["stale"] else ("ON" if s["on"] else ("recent" if s["recent"] else "off"))
        print(f"  {s['id']:4s} {state:6s} {s['name']}: {s['value']}")
    print(f"  rebuy {w['rebuy']['met']}/3  gauges {w['gauges']}")

print("── back-test ──")
bt = run_backtest(data)
if bt.get("available"):
    print(bt["strategies"].round(1).to_string(index=False))
    print(bt["hit_rates"].round(1).head(3).to_string(index=False))

print("── 8504 link ──")
whale = fetch_whale_exit_share()
print(f"alert-counts reachable: {not whale.empty} ({len(whale)} dates)")

print("── 13F ──")
smart = db_manager.read_snapshot("13f_smart_money") or {}
names = sorted({r[0] for k in ("top_buy_value", "top_sell_value", "top_buy_shares",
                               "top_sell_shares", "conviction_buy", "conviction_sell")
                for r in smart.get(k, [])})
real = [n for n in names if not looks_like_cusip(n)]
sectors = [classify_sector(n) for n in real]
non_etf = [s for s in sectors if s != ETF]
other = [n for n, s in zip(real, sectors) if s == OTHER]
print(f"quarter {smart.get('quarter')}: {len(names)} names, {len(names) - len(real)} CUSIP-only, "
      f"其他 {len(other)}/{len(non_etf)} = {len(other) / max(len(non_etf), 1):.0%}")
print("  unclassified:", other[:30])
rank = build_rank_table(smart)
print(f"  ranking rows {len(rank)}, signals {sorted(set(rank['訊號']))}")

print("RESULT:", "FAIL " + ", ".join(failures) if failures else "PASS")
sys.exit(1 if failures else 0)
