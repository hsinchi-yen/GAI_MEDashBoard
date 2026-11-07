"""Deterministic synthetic macro data for unit and integration tests.

`macro_dataset(bias)` returns the same dict shape as dashboard.load_all_from_db.
`bias` (-1 … +1) tilts every series toward a bearish or bullish macro backdrop,
so tests can assert the verdict end to end without any network access.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

NOW = pd.Timestamp("2026-10-15")
MONTHS = 96


def _months(end: pd.Timestamp = NOW, periods: int = MONTHS) -> pd.DatetimeIndex:
    return pd.date_range(end=end.normalize().replace(day=1) - pd.DateOffset(months=1),
                         periods=periods, freq="MS")


def _series(base: float, slope: float, amp: float, seed: int, end=NOW, periods=MONTHS) -> pd.DataFrame:
    """Monthly series: a level + a 3-month-resolved trend + a small seeded wobble."""
    rng = np.random.default_rng(seed)
    t = np.arange(periods, dtype=float)
    wobble = amp * np.sin(t / 7.0) + rng.normal(0, amp * 0.08, periods)
    # Trend ramps in only over the final year so history stays mean-reverting.
    ramp = np.clip(t - (periods - 13), 0, None) * slope
    return pd.DataFrame({"date": _months(end, periods), "value": base + wobble + ramp})


def _daily(base: float, slope: float, amp: float, seed: int, end=NOW, days: int = 2200) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end.normalize() - pd.Timedelta(days=1), periods=days)
    days = len(dates)
    t = np.arange(days, dtype=float)
    wobble = amp * np.sin(t / 150.0) + rng.normal(0, amp * 0.05, days)
    ramp = np.clip(t - (days - 260), 0, None) * slope / 21.0
    return pd.DataFrame({"date": dates, "value": base + wobble + ramp})


def macro_dataset(bias: float = 0.8, end: pd.Timestamp = NOW) -> dict:
    """Full `data` dict. bias > 0 → improving growth / easing stress."""
    b = float(bias)
    m = lambda base, slope, amp, seed: _series(base, slope * b, amp, seed, end)
    d = lambda base, slope, amp, seed: _daily(base, slope * b, amp, seed, end)

    data: dict = {
        "US_PMI": m(50, 0.6, 1.0, 1), "TW_PMI": m(50, 0.7, 1.0, 2),
        "CN_PMI": m(50, 0.4, 0.8, 3), "EU_PMI": m(50, 0.5, 1.0, 4),
        "JP_PMI": m(48, 0.4, 1.2, 5),
        "US_NEW_ORDERS_YOY": m(1.5 * b, 0.6, 1.5, 6), "UMCSENT": m(72, 0.8, 3.0, 7),
        "US_RETAIL_YOY": m(1.5 * b, 0.4, 1.0, 8),
        "NDC_LEADING": m(100, 0.3, 0.8, 9), "NDC_LIGHT_SCORE": m(25, 0.8, 3.0, 10),
        "TW_EXP_YOY": m(4 * b, 1.2, 3.0, 11), "KR_EXP_YOY": m(4 * b, 1.0, 3.0, 12),
        "TSMC_REVENUE_YOY": m(20, 1.5, 5.0, 13), "COPPER_YOY": m(3 * b, 1.0, 3.0, 14),
        "CHINA_CREDIT_IMPULSE": m(1, 0.3, 1.5, 15),
        "US_CORE_CPI_YOY": m(3.0, -0.05, 0.2, 16), "US_CORE_PPI_YOY": m(2.8, -0.05, 0.3, 17),
        "CN_PPI_YOY": m(-1, 0.3, 0.8, 18),
        "BRENT": d(80, -1.0, 6.0, 19), "US_REAL_RATE": d(1.8, -0.03, 0.15, 20),
        "VIX": d(18, -0.8, 2.0, 21), "HY_SPREAD": d(420, -12.0, 25.0, 22),
        "T10Y3M": d(0.4, 0.05, 0.1, 23), "T10Y2Y": d(0.3, 0.04, 0.1, 24),
        "FED_FUNDS": m(4.0, -0.05, 0.2, 25), "DXY": d(120, -0.5, 2.0, 26),
        "TWD_USD": d(31, -0.15, 0.4, 27),
        "TW_M1B_YOY": m(3, 0.4, 0.7, 28), "TW_M2_YOY": m(4, 0.05, 0.4, 29),
        "US_M1_YOY": m(1, 0.3, 1.0, 30),
        "SP500_YOY": m(9, 1.0, 4.0, 31), "TAIEX_YOY": m(12, 1.5, 6.0, 32),
        "NIKKEI_YOY": m(8, 0.8, 5.0, 33), "KOSPI_YOY": m(6, 1.2, 6.0, 34),
        "HSI_YOY": m(1, 0.8, 6.0, 35), "CSI300_YOY": m(1, 0.6, 5.0, 36),
        "VKOSPI": d(20, -0.8, 2.0, 37), "VIXTWN": d(19, -0.8, 2.0, 51),
        "TAIEX_DAILY": d(22000, 120, 1500, 52), "SECTOR_ROTATION": m(0.01 * b, 0.004, 0.01, 38),
        "THIRTEENF_NET_ADD": m(0.02 * b, 0.002, 0.01, 39),
        "US_RETAIL": m(600, 2.0, 5.0, 40), "TW_EXP_AMOUNT": m(38000, 200, 800, 41),
        "US_CLI": m(100, 0.05, 0.3, 42), "CN_CLI": m(100, 0.05, 0.3, 43),
        "JP_CLI": m(100, 0.05, 0.3, 44), "EU_CLI": m(100, 0.05, 0.3, 45),
        "KR_CLI": m(100, 0.05, 0.3, 46),
        "US_BUSINV": m(2500, 2.0, 8.0, 47), "SEMI_PPI": m(120, 0.4, 2.0, 48),
        "US_10Y_NOMINAL": d(4.2, -0.02, 0.2, 49), "US_10Y_BEI": d(2.3, 0.0, 0.1, 50),
    }
    data["CPI_PPI_SCISSORS"] = (
        data["US_CORE_CPI_YOY"].merge(data["US_CORE_PPI_YOY"], on="date", suffixes=("_c", "_p"))
        .assign(value=lambda f: f["value_c"] - f["value_p"])[["date", "value"]]
    )
    data["YIELD_CURVE"] = {
        label: d(3.8 + i * 0.1, 0.0, 0.2, 60 + i)
        for i, label in enumerate(["1M", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y"])
    }
    return data


def index_levels(end: pd.Timestamp = NOW, periods: int = 130) -> dict:
    """Month-end index price levels with a modest upward drift."""
    dates = pd.date_range(end=end.normalize().replace(day=1) - pd.DateOffset(days=1),
                          periods=periods, freq="ME")
    t = np.arange(periods, dtype=float)
    twii = 8000 * np.exp(0.009 * t + 0.05 * np.sin(t / 5))
    spx = 2000 * np.exp(0.008 * t + 0.04 * np.sin(t / 6))
    return {
        "TWII": pd.DataFrame({"date": dates, "value": twii}),
        "SPX":  pd.DataFrame({"date": dates, "value": spx}),
    }
