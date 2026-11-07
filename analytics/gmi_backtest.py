"""GMI conditional backtest engine.

Given a historical GMI series with regime labels and one or more equity price
series, compute forward returns conditional on the regime at each month, then
aggregate to regime × horizon × market statistics. Also provides a
cross-correlation matrix to find which GMI sub-indicators lead/lag equity YoY.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REGIME_ORDER = ["green", "yellow", "red"]
DEFAULT_HORIZONS = (1, 3, 6, 12)

DEFAULT_CORR_INDICATORS = [
    "US_PMI", "TW_PMI", "CN_PMI", "EU_PMI", "JP_PMI",
    "US_NEW_ORDERS_YOY", "TW_EXP_YOY", "KR_EXP_YOY", "US_RETAIL_YOY",
    "NDC_LEADING", "US_CORE_CPI_YOY", "US_CORE_PPI_YOY", "CN_PPI_YOY",
    "HY_SPREAD", "T10Y3M", "TW_M1B_YOY", "TW_M2_YOY",
    "VIX", "VIXTWN", "TWD_USD", "COPPER_YOY",
]


def _normalize_month_end(series: pd.Series) -> pd.Series:
    """Snap a datetime Series to month-end timestamps."""
    return pd.to_datetime(series, errors="coerce").dt.to_period("M").dt.to_timestamp("M")


def compute_forward_returns(
    gmi_history: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    regime_col: str = "confirmed_regime",
    signal_lag: int = 0,
) -> pd.DataFrame:
    """For each (month t, market, horizon h), compute log(P[t+l+h] / P[t+l]).

    `signal_lag` (l) delays entry to when the signal was actually knowable:
    macro prints for month t are published during t+1, so an investor could not
    have traded month t's regime at month t's close. Use 1 for realistic stats.

    Args:
        gmi_history: DataFrame with at least 'date' and `regime_col`.
        prices:      Mapping market_name -> {date, value} DataFrame.
                     Dates are snapped to month-end internally.
        horizons:    Forward horizons in months.
        regime_col:  Which regime column to read (`regime` or `confirmed_regime`).
        signal_lag:  Months between the signal date and the entry price.

    Returns:
        Long-format DataFrame with columns:
            as_of, regime, market, horizon, fwd_log_return, fwd_pct_return
        Rows where the forward price is missing (out-of-sample) are dropped.
    """
    cols = ["as_of", "regime", "market", "horizon", "fwd_log_return", "fwd_pct_return"]
    if gmi_history is None or gmi_history.empty or regime_col not in gmi_history.columns:
        return pd.DataFrame(columns=cols)

    base = gmi_history[["date", regime_col]].rename(
        columns={"date": "as_of", regime_col: "regime"}
    ).dropna(subset=["as_of"]).copy()
    base["as_of"] = _normalize_month_end(base["as_of"])
    base = base[base["regime"].isin(REGIME_ORDER)]

    if base.empty:
        return pd.DataFrame(columns=cols)

    records = []
    for market_name, px_df in prices.items():
        if px_df is None or px_df.empty or "date" not in px_df.columns:
            continue
        px = px_df[["date", "value"]].dropna().drop_duplicates("date").copy()
        px["date"] = _normalize_month_end(px["date"])
        px = px.drop_duplicates("date", keep="last").sort_values("date")
        px_map = dict(zip(px["date"], px["value"]))

        merged = base.copy()
        merged["entry"] = _normalize_month_end(merged["as_of"] + pd.DateOffset(months=signal_lag))
        merged["px"] = merged["entry"].map(px_map)
        merged = merged.dropna(subset=["px"])
        if merged.empty:
            continue

        for h in horizons:
            forward_dates = _normalize_month_end(merged["entry"] + pd.DateOffset(months=h))
            fwd_px = forward_dates.map(px_map)
            mask = fwd_px.notna()
            if not mask.any():
                continue
            sub = merged.loc[mask].copy()
            sub["horizon"] = h
            sub["market"] = market_name
            sub["fwd_log_return"] = np.log(fwd_px[mask].values / sub["px"].values)
            sub["fwd_pct_return"] = np.expm1(sub["fwd_log_return"])
            records.append(sub[cols])

    if not records:
        return pd.DataFrame(columns=cols)
    return pd.concat(records, ignore_index=True)


def _stat_row(returns: pd.Series) -> dict:
    pct = returns.dropna()
    n = len(pct)
    if n == 0:
        return {"median": np.nan, "mean": np.nan, "win_rate": np.nan,
                "p10": np.nan, "p90": np.nan, "worst": np.nan, "n": 0}
    return {
        "median":   pct.median() * 100,
        "mean":     pct.mean() * 100,
        "win_rate": (pct > 0).mean() * 100,
        "p10":      pct.quantile(0.10) * 100,
        "p90":      pct.quantile(0.90) * 100,
        "worst":    pct.min() * 100,
        "n":        n,
    }


def summarize_by_regime(
    returns_df: pd.DataFrame,
    include_unconditional: bool = True,
) -> pd.DataFrame:
    """Aggregate forward returns to (market, regime, horizon) statistics.

    Statistics (all return-based, expressed in percent except n):
        median, mean, win_rate, p10, p90, worst, n.
    When include_unconditional=True, also adds `regime='all'` rows that pool
    every observation regardless of regime, as a baseline reference.
    """
    out_cols = ["market", "regime", "horizon", "median", "mean",
                "win_rate", "p10", "p90", "worst", "n"]
    if returns_df is None or returns_df.empty:
        return pd.DataFrame(columns=out_cols)

    rows = []
    for (market, regime, horizon), g in returns_df.groupby(["market", "regime", "horizon"]):
        rows.append({"market": market, "regime": regime, "horizon": horizon,
                     **_stat_row(g["fwd_pct_return"])})

    if include_unconditional:
        for (market, horizon), g in returns_df.groupby(["market", "horizon"]):
            rows.append({"market": market, "regime": "all", "horizon": horizon,
                         **_stat_row(g["fwd_pct_return"])})

    out = pd.DataFrame(rows, columns=out_cols)
    # Stable ordering: market, regime (green→yellow→red→all), horizon
    regime_rank = {"green": 0, "yellow": 1, "red": 2, "all": 3}
    out["_r"] = out["regime"].map(regime_rank).fillna(99)
    out = out.sort_values(["market", "_r", "horizon"]).drop(columns="_r").reset_index(drop=True)
    return out


def compute_cross_correlation(
    data: dict,
    target_series: dict[str, pd.DataFrame],
    indicator_keys: list[str] | None = None,
    max_lag: int = 12,
    min_overlap: int = 24,
) -> pd.DataFrame:
    """Compute lagged Pearson correlation between GMI sub-indicators and equity YoY.

    For each (indicator, target, lag) tuple, correlate the indicator level at
    time t with the target's 12-month log-return at time t+lag.

    Positive lag means the indicator LEADS the target (early-warning value).
    Negative lag means the indicator LAGS the target.

    Args:
        data:           Macro data dict (load_data() output).
        target_series:  Mapping market_name -> price-level DataFrame ({date, value}).
        indicator_keys: GMI indicator keys to test (defaults to DEFAULT_CORR_INDICATORS).
        max_lag:        Lag range is [-max_lag, +max_lag] months.
        min_overlap:    Skip pairs with fewer than this many overlapping observations.

    Returns:
        Long-format DataFrame: indicator, target, lag, correlation, n.
    """
    if indicator_keys is None:
        indicator_keys = list(DEFAULT_CORR_INDICATORS)

    # Build month-aligned indicator series
    series_map: dict[str, pd.Series] = {}
    for key in indicator_keys:
        df = data.get(key) if data else None
        if df is None or df.empty or "date" not in df.columns:
            continue
        s = df[["date", "value"]].dropna().drop_duplicates("date").copy()
        s["date"] = _normalize_month_end(s["date"])
        s = s.drop_duplicates("date", keep="last").sort_values("date")
        if len(s) < min_overlap:
            continue
        series_map[key] = s.set_index("date")["value"].astype(float)

    if not series_map:
        return pd.DataFrame(columns=["indicator", "target", "lag", "correlation", "n"])

    records = []
    for tgt_name, tgt_df in target_series.items():
        if tgt_df is None or tgt_df.empty:
            continue
        tgt = tgt_df[["date", "value"]].dropna().drop_duplicates("date").copy()
        tgt["date"] = _normalize_month_end(tgt["date"])
        tgt = tgt.drop_duplicates("date", keep="last").sort_values("date").set_index("date")["value"]
        tgt_yoy = np.log(tgt.astype(float) / tgt.astype(float).shift(12))

        for ind_name, ind in series_map.items():
            for lag in range(-max_lag, max_lag + 1):
                # lag > 0 → indicator leads → align ind(t) with tgt_yoy(t+lag)
                paired = pd.concat([ind, tgt_yoy.shift(-lag)], axis=1, join="inner").dropna()
                if len(paired) < min_overlap:
                    continue
                c = paired.iloc[:, 0].corr(paired.iloc[:, 1])
                if pd.isna(c):
                    continue
                records.append({
                    "indicator":   ind_name,
                    "target":      tgt_name,
                    "lag":         lag,
                    "correlation": float(c),
                    "n":           int(len(paired)),
                })

    return pd.DataFrame(records, columns=["indicator", "target", "lag", "correlation", "n"])
