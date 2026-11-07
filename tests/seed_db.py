"""Populate a database with synthetic data, matching what the scheduler would write.

Used by the integration tests, and runnable for a local demo without any API keys:

    python tests/seed_db.py app_data/db/demo.sqlite3
    GMI_DB_PATH=app_data/db/demo.sqlite3 streamlit run dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db_manager  # noqa: E402
from tests.synthetic_data import NOW, index_levels, macro_dataset  # noqa: E402

# load_all_from_db key → DB key, for series stored exactly as served.
DIRECT = {
    "VIX": "vix", "US_PMI": "ism_pmi", "TW_PMI": "taiwan_pmi", "CN_PMI": "china_nbs_pmi",
    "JP_PMI": "japan_watchers", "EU_PMI": "eurostat_ici", "UMCSENT": "umcsent",
    "KR_EXP_YOY": "korea_exports_yoy", "NDC_LEADING": "ndc_leading",
    "NDC_LIGHT_SCORE": "ndc_light_score", "US_CLI": "cli_us", "CN_CLI": "cli_cn",
    "JP_CLI": "cli_jp", "EU_CLI": "cli_eu", "KR_CLI": "cli_kr", "US_BUSINV": "us_businv",
    "SEMI_PPI": "semi_ppi", "COPPER_YOY": "copper_yoy", "TSMC_REVENUE_YOY": "tsmc_revenue_yoy",
    "US_10Y_NOMINAL": "dgs10", "US_10Y_BEI": "t10y_bei", "CN_PPI_YOY": "china_ppi_yoy",
    "BRENT": "brent", "CHINA_CREDIT_IMPULSE": "china_credit",
    "TW_M1B_YOY": "cbc_money_supply.m1b_yoy", "TW_M2_YOY": "cbc_money_supply.m2_yoy",
    "T10Y2Y": "t10y2y", "TWD_USD": "twd_usd", "DXY": "dxy", "SP500_YOY": "sp500_yoy",
    "TAIEX_YOY": "taiex_yoy", "NIKKEI_YOY": "nikkei_yoy", "KOSPI_YOY": "kospi_yoy",
    "HSI_YOY": "hsi_yoy", "CSI300_YOY": "csi300_yoy", "VKOSPI": "vkospi", "VIXTWN": "vixtwn",
    "TAIEX_DAILY": "taiex_daily",
    "FED_FUNDS": "fed_funds_rate", "T10Y3M": "t10y3m", "US_NEW_ORDERS_YOY": "us_new_orders_yoy",
    "SECTOR_ROTATION": "sector_rotation", "THIRTEENF_NET_ADD": "13f_proxy",
    "US_RETAIL": "us_retail", "TW_EXP_AMOUNT": "taiwan_exports",
}
SECTORS = ["電子", "金融保險", "航運", "鋼鐵", "塑膠", "食品"]


def _level_from_yoy(yoy: pd.DataFrame, base: float = 100.0) -> pd.DataFrame:
    """Rebuild an index level whose 12M change matches a YoY series."""
    values = yoy["value"].to_numpy() / 100 + 1
    level = np.full(len(values) + 12, base, dtype=float)
    for i, growth in enumerate(values):
        level[i + 12] = level[i] * growth
    dates = pd.date_range(end=yoy["date"].iloc[-1], periods=len(level), freq="MS")
    return pd.DataFrame({"date": dates, "value": level})


def seed_macro(bias: float = 0.6, end: pd.Timestamp = NOW) -> None:
    data = macro_dataset(bias, end)
    for key, db_key in DIRECT.items():
        db_manager.write(db_key, data[key], ttl_days=30, initial=True)

    hy = data["HY_SPREAD"].assign(value=lambda f: f["value"] / 100)  # FRED quotes percent
    db_manager.write("hy_spread", hy, ttl_days=30, initial=True)
    db_manager.write("us_core_cpi", _level_from_yoy(data["US_CORE_CPI_YOY"]), ttl_days=30, initial=True)
    db_manager.write("us_core_ppi", _level_from_yoy(data["US_CORE_PPI_YOY"]), ttl_days=30, initial=True)
    db_manager.write("us_m1", _level_from_yoy(data["US_M1_YOY"]), ttl_days=30, initial=True)
    for label, frame in data["YIELD_CURVE"].items():
        db_manager.write(f"yield_{label}", frame, ttl_days=30, initial=True)


def seed_market(end: pd.Timestamp = NOW) -> None:
    """Snapshots and series the scheduler keeps for the slower pages."""
    prices = index_levels(end)
    db_manager.write("index_close_twii", prices["TWII"], ttl_days=30, initial=True)
    db_manager.write("index_close_spx", prices["SPX"], ttl_days=30, initial=True)

    top = pd.DataFrame({"code": ["2330", "0050", "2317"], "name": ["台積電", "元大台灣50", "鴻海"],
                        "net_shares": [52_000_000, 21_000_000, 9_000_000],
                        "est_value_億": [520.0, 38.5, None]})
    for n_days in (5, 20):
        db_manager.write_snapshot(f"tw_institutional_{n_days}d", {
            "top30_buy": top, "top30_sell": top.assign(net_shares=lambda f: -f["net_shares"]),
            "actual_days": n_days, "period_label": f"近 {n_days} 日", "fetch_date": "2026-10-14 16:00",
        })

    db_manager.write_snapshot("13f_smart_money", {
        "quarter": "2026Q2", "fund_count": 18, "as_of": "2026-06-30",
        "top_buy_shares":  [("NVIDIA CORP", 5_000_000, 9), ("MICROSOFT", 2_000_000, 7)],
        "top_sell_shares": [("TESLA", -3_000_000, 6), ("EXXON", -1_000_000, 4)],
        "top_buy_value":   [("NVIDIA CORP", 980.5, 9), ("MICROSOFT", 420.0, 7)],
        "top_sell_value":  [("TESLA", -610.0, 6), ("EXXON", -120.0, 4)],
        "conviction_buy":  [("NVIDIA CORP", 9, 5_000_000), ("MICROSOFT", 7, 2_000_000)],
        "conviction_sell": [("TESLA", 6, -3_000_000), ("EXXON", 4, -1_000_000)],
    })

    days = pd.bdate_range(end=end, periods=90)
    rows = []
    for i, sector in enumerate(SECTORS):
        for t, day in enumerate(days):
            rows.append({"date": day, "sector_name": sector,
                         "close": 100 + i * 10 + t * (0.3 - 0.1 * i)})
    close = pd.DataFrame(rows)
    db_manager.write("tw_sector_close", close, ttl_days=30, initial=True)

    last = days[-1]
    db_manager.write("tw_sector_institutional", pd.DataFrame({
        "date": [last] * 3, "institution": ["外資", "投信", "自營商"],
        "buy_amt": [100.0, 50.0, 30.0], "sell_amt": [80.0, 40.0, 35.0], "net_amt": [20.0, 10.0, -5.0],
    }), ttl_days=30)
    db_manager.write("tw_sector_instit_by_sector", pd.DataFrame({
        "date": [last] * len(SECTORS), "sector_name": SECTORS,
        "foreign_net": [1e6] * 6, "trust_net": [2e5] * 6, "dealer_net": [-1e5] * 6,
        "total_net": [1.1e6, 9e5, -2e5, 3e5, -4e5, 1e5],
    }), ttl_days=30)


def seed_all(bias: float = 0.6, end: pd.Timestamp = NOW) -> None:
    seed_macro(bias, end)
    seed_market(end)


if __name__ == "__main__":
    db_manager._DB_PATH = Path(sys.argv[1]).resolve()
    seed_all(end=pd.Timestamp.now())
    print(f"Seeded {db_manager._DB_PATH}")
