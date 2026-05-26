"""
gmi_regression.py — standalone GMI regression harness.

Two modes:

  1. Synthetic assertions (always run): prove the proportional-scoring fix —
     missing indicators must NOT drag the regime toward red, and a full data set
     reproduces the legacy absolute thresholds.

  2. Real-DB diagnostic (when --db PATH given): read the live SQLite DB, rebuild
     the 20 GMI inputs exactly as dashboard.load_all_from_db does, then print a
     per-indicator status table plus an OLD-vs-NEW regime comparison.

Self-contained: depends only on pandas + macro_index.py (no Streamlit / fetchers),
so it runs unchanged on the embedded box. Read-only against the DB.

Usage:
    python tests/gmi_regression.py                 # synthetic only
    python tests/gmi_regression.py --db <path>     # + real-DB diagnostic
Exit code: 0 = all synthetic assertions pass, 1 = a regression failed.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import pandas as pd

# Allow running both as `python tests/gmi_regression.py` (root cwd) and after
# being copied next to macro_index.py on the embedded box.
for _p in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
           os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from macro_index import compute_macro_index, REGIME_GREEN_PCT, REGIME_RED_PCT


# ── helpers ─────────────────────────────────────────────────────────────────

def _mdf(vals: list[float]) -> pd.DataFrame:
    end = pd.Timestamp.now().replace(day=1)
    return pd.DataFrame({"date": pd.date_range(end=end, periods=len(vals), freq="MS"),
                         "value": vals})


def _compute_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """12-period YoY %, mirrors fetchers.utils.compute_yoy."""
    if df is None or df.empty or len(df) < 13:
        return pd.DataFrame()
    df = df.copy()
    df["value"] = df["value"].pct_change(12) * 100
    return df.dropna()


def _legacy_regime(score: int, valid_count: int) -> tuple[float, str]:
    """Reproduce the OLD scoring: diffusion = score/20, absolute thresholds."""
    diff = round(score / 20 * 100, 1)
    if valid_count < 10:
        reg = "unknown"
    elif score >= 15:
        reg = "green"
    elif score <= 9:
        reg = "red"
    else:
        reg = "yellow"
    return diff, reg


# ── 1. synthetic assertions ─────────────────────────────────────────────────

def _run_synthetic() -> int:
    failures = []

    def check(name, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    pmi_up = _mdf([49.0, 50.5, 51.5])              # >50 & slope up -> 1
    yoy_imp = _mdf([1., 1.5, 2., 2.5, 3., 3.5, 4.])  # >0 & improving (>=6 pts) -> 1
    yoy = _mdf([2.0, 3.0, 4.0])                    # >0 simple -> 1
    hy = _mdf([400.0, 380.0, 360.0])               # falling -> 1
    t10 = _mdf([0.1, 0.2, 0.3])                    # >0 & rising -> 1
    vix = _mdf([28.0, 24.0, 20.0])                 # falling -> 1
    cli = _mdf([101.0, 101.5, 102.0])              # >100
    twd = _mdf([32.0, 31.5, 31.0])                 # appreciating -> 1
    cu = _mdf([2.0, 3.0, 4.0])                     # copper YoY >0 -> 1
    rot = _mdf([0.01, 0.02, 0.03])                 # rotation >0 & up -> 1
    m1b = _mdf([3.0, 4.0, 5.0]); m2 = _mdf([2.0, 2.5, 3.0])  # golden cross -> 1

    print("\n-- Synthetic regression scenarios --")

    # Scenario A: ~12 valid indicators, all bullish, the rest missing.
    # OLD: divides by 20 -> dragged below the green cut-off (false yellow/red).
    # NEW: divides by valid_count -> green. This is the core fix.
    data_a = {
        "US_PMI": pmi_up, "TW_PMI": pmi_up, "CN_PMI": pmi_up, "EU_PMI": pmi_up,
        "US_NEW_ORDERS_YOY": yoy, "TW_EXP_YOY": yoy_imp, "KR_EXP_YOY": yoy_imp,
        "US_RETAIL_YOY": yoy, "HY_SPREAD": hy, "T10Y3M": t10, "VIX": vix,
        "COPPER_YOY": cu,
    }
    ra = compute_macro_index(data_a)
    old_diff_a, old_reg_a = _legacy_regime(ra["score"], ra["valid_count"])
    print(f"  Scenario A ({ra['valid_count']} valid all-bullish, rest missing): "
          f"score={ra['score']} | "
          f"OLD {old_diff_a}%/{old_reg_a} -> NEW {ra['diffusion']}%/{ra['regime']}")
    check("A: NEW regime is green (proportional)", ra["regime"] == "green")
    check("A: OLD regime was NOT green (missing data dragged it down = the bug)",
          old_reg_a != "green")

    # Scenario B: all 19 present & bullish → regime is green.
    # (OECD CLI indicator #9 was removed; CLI data keys are still passed but ignored by compute_gmi)
    data_b = dict(data_a)
    data_b.update({
        "US_CORE_CPI_YOY": yoy, "US_CORE_PPI_YOY": _mdf([5.0, 4.0, 3.0]),
        "CPI_PPI_SCISSORS": pd.DataFrame(), "CN_PPI_YOY": _mdf([-3.0, -2.0, -1.0]),
        "T10Y3M": t10, "TW_M1B_YOY": m1b, "TW_M2_YOY": m2,
        "NDC_LEADING": _mdf([98.0, 99.0, 100.0]), "VIX": vix, "TWD_USD": twd,
        "COPPER_YOY": cu, "SECTOR_ROTATION": rot,
        "THIRTEENF_NET_ADD": _mdf([0.5]),
    })
    rb = compute_macro_index(data_b)
    old_diff_b, old_reg_b = _legacy_regime(rb["score"], rb["valid_count"])
    print(f"  Scenario B (20 valid all-bullish): "
          f"valid={rb['valid_count']} score={rb['score']} | "
          f"OLD {old_diff_b}%/{old_reg_b} -> NEW {rb['diffusion']}%/{rb['regime']}")
    check("B: full data -> green (parity with legacy)", rb["regime"] == "green")
    check("B: full-data diffusion equals score/valid_count",
          abs(rb["diffusion"] - round(rb["score"] / rb["valid_count"] * 100, 1)) < 0.1)

    # Scenario C: too few valid (< 10) → unknown, never a false red.
    rc = compute_macro_index({"US_PMI": pmi_up, "VIX": vix, "HY_SPREAD": hy})
    print(f"  Scenario C (3 valid): valid={rc['valid_count']} regime={rc['regime']}")
    check("C: <10 valid -> unknown (not a false red)", rc["regime"] == "unknown")

    # Scenario D: genuinely bearish valid data must still go red.
    bear_pmi = _mdf([45.0, 44.0, 43.0])
    bear_yoy = _mdf([-5.0, -4.0, -3.0])
    data_d = {k: bear_pmi for k in ("US_PMI", "TW_PMI", "CN_PMI", "EU_PMI")}
    data_d.update({
        "US_NEW_ORDERS_YOY": bear_yoy, "TW_EXP_YOY": bear_yoy, "KR_EXP_YOY": bear_yoy,
        "US_RETAIL_YOY": bear_yoy, "COPPER_YOY": bear_yoy,
        "VIX": _mdf([18.0, 22.0, 28.0]), "HY_SPREAD": _mdf([350.0, 400.0, 450.0]),
        "T10Y3M": _mdf([-0.5, -0.4, -0.3]),
    })
    rd = compute_macro_index(data_d)
    print(f"  Scenario D (12 valid all-bearish): valid={rd['valid_count']} "
          f"diffusion={rd['diffusion']}% regime={rd['regime']}")
    check("D: genuinely bearish valid data -> red", rd["regime"] == "red")

    return 1 if failures else 0


# ── 2. real-DB diagnostic ────────────────────────────────────────────────────

# (GMI data key, db key, derivation): derivation in {"raw","yoy"}
_GMI_MAP = [
    ("US_PMI", "ism_pmi", "raw"), ("TW_PMI", "taiwan_pmi", "raw"),
    ("CN_PMI", "china_nbs_pmi", "raw"), ("EU_PMI", "eurostat_ici", "raw"),
    ("US_NEW_ORDERS_YOY", "us_new_orders_yoy", "raw"),
    ("TW_EXP_YOY", "taiwan_exports", "yoy"), ("KR_EXP_YOY", "korea_exports_yoy", "raw"),
    ("US_RETAIL_YOY", "us_retail", "yoy"),
    ("NDC_LEADING", "ndc_leading", "raw"),
    ("US_CORE_CPI_YOY", "us_core_cpi", "yoy"), ("US_CORE_PPI_YOY", "us_core_ppi", "yoy"),
    ("CN_PPI_YOY", "china_ppi_yoy", "raw"),
    ("HY_SPREAD", "hy_spread", "raw"), ("T10Y3M", "t10y3m", "raw"),
    ("TW_M1B_YOY", "cbc_money_supply.m1b_yoy", "raw"),
    ("TW_M2_YOY", "cbc_money_supply.m2_yoy", "raw"),
    ("COPPER_YOY", "copper_yoy", "raw"), ("TWD_USD", "twd_usd", "raw"),
    ("VIX", "vix", "raw"),
    ("SECTOR_ROTATION", "sector_rotation", "raw"),
    ("THIRTEENF_NET_ADD", "13f_proxy", "raw"),
]


def _read_ts_raw(con: sqlite3.Connection, key: str) -> pd.DataFrame:
    """Read a simple {date,value} series from ts_rows, ignoring TTL."""
    rows = con.execute(
        "SELECT day_epoch, value FROM ts_rows WHERE indicator_id=? AND series_key='' "
        "ORDER BY day_epoch", (key,)).fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["day_epoch", "value"])
    df["date"] = df["day_epoch"].map(lambda d: pd.Timestamp(d * 86400, unit="s"))
    return df[["date", "value"]]


def _run_real_db(db_path: str) -> None:
    print(f"\n-- Real-DB diagnostic ({db_path}) --")
    con = sqlite3.connect(db_path)
    data: dict = {}
    raw_seen: dict = {}
    for gmi_key, db_key, how in _GMI_MAP:
        df = _read_ts_raw(con, db_key)
        raw_seen[gmi_key] = df
        data[gmi_key] = _compute_yoy(df) if how == "yoy" else df

    # CPI-PPI scissors derived series
    cy, py = data.get("US_CORE_CPI_YOY"), data.get("US_CORE_PPI_YOY")
    if cy is not None and not cy.empty and py is not None and not py.empty:
        m = cy.rename(columns={"value": "c"}).merge(
            py.rename(columns={"value": "p"}), on="date", how="inner")
        m["value"] = m["c"] - m["p"]
        data["CPI_PPI_SCISSORS"] = m[["date", "value"]]
    else:
        data["CPI_PPI_SCISSORS"] = pd.DataFrame()

    result = compute_macro_index(data)

    # Per-indicator status table
    print(f"\n  {'#':>2} {'indicator':28s} {'has_data':8s} {'score':>5s}  raw")
    for sig in result["signals"]:
        flag = "yes" if sig["has_data"] else "NO"
        print(f"  {sig['id']:>2} {sig['name']:28s} {flag:8s} {sig['score']:>5}  {sig['raw']}")

    missing = [s["name"] for s in result["signals"] if not s["has_data"]]
    print(f"\n  valid_count = {result['valid_count']}/19   confidence = {result['confidence']}")
    if missing:
        print(f"  MISSING ({len(missing)}): " + ", ".join(missing))

    old_diff, old_reg = _legacy_regime(result["score"], result["valid_count"])
    print(f"\n  OLD scoring: score/20 = {result['score']}/20 = {old_diff}%  -> regime = {old_reg}")
    print(f"  NEW scoring: score/valid = {result['score']}/{result['valid_count']} "
          f"= {result['diffusion']}%  -> regime = {result['regime']}")
    print(f"  (thresholds: green >= {REGIME_GREEN_PCT}% | red <= {REGIME_RED_PCT}%)")
    if old_reg != result["regime"]:
        print(f"  >>> REGIME CHANGED by the fix: {old_reg} -> {result['regime']}")


# ── entry ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", help="Path to indicator_cache.sqlite3 for real-DB diagnostic")
    args = ap.parse_args()

    print("=" * 70)
    print("GMI REGRESSION HARNESS")
    print("=" * 70)
    rc = _run_synthetic()
    if args.db:
        _run_real_db(args.db)
    print("\n" + "=" * 70)
    print("SYNTHETIC RESULT:", "ALL PASS" if rc == 0 else "FAILURES")
    print("=" * 70)
    return rc


if __name__ == "__main__":
    sys.exit(main())
