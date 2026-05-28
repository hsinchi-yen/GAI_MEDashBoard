"""
test_gmi_backtest.py — unit tests for analytics/gmi_backtest.py

Covers:
  - compute_forward_returns: log/pct correctness, market filtering, horizon dropoff
  - summarize_by_regime: median / mean / win_rate / N over hand-built data
  - compute_cross_correlation: peak-lag recovery on synthetic data
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.gmi_backtest import (
    REGIME_ORDER,
    compute_forward_returns,
    summarize_by_regime,
    compute_cross_correlation,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _gmi_history(regimes: list[str], start: str = "2020-01-31") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(regimes), freq="ME")
    return pd.DataFrame({"date": dates, "confirmed_regime": regimes})


def _price_series(values: list[float], start: str = "2020-01-31") -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=len(values), freq="ME")
    return pd.DataFrame({"date": dates, "value": values})


# ──────────────────────────────────────────────────────────────────────────────
# compute_forward_returns
# ──────────────────────────────────────────────────────────────────────────────

def test_forward_returns_correct_pct_and_log():
    gmi = _gmi_history(["green"] * 6)
    # Price doubles over the window
    prices = {"X": _price_series([100, 110, 121, 133.1, 146.41, 161.051])}
    out = compute_forward_returns(gmi, prices, horizons=(1, 3))
    one_m = out[(out["horizon"] == 1) & (out["as_of"] == pd.Timestamp("2020-01-31"))]
    assert len(one_m) == 1
    # +10% expected
    assert one_m.iloc[0]["fwd_pct_return"] == pytest.approx(0.10, rel=1e-6)
    assert one_m.iloc[0]["fwd_log_return"] == pytest.approx(np.log(1.10), rel=1e-6)

    three_m = out[(out["horizon"] == 3) & (out["as_of"] == pd.Timestamp("2020-01-31"))]
    assert three_m.iloc[0]["fwd_pct_return"] == pytest.approx(0.331, rel=1e-3)


def test_forward_returns_drops_out_of_sample_tail():
    gmi = _gmi_history(["green"] * 5)
    prices = {"X": _price_series([100, 110, 120, 130, 140])}
    out = compute_forward_returns(gmi, prices, horizons=(3,))
    # only 2020-01..2020-02 can compute 3M forward (need t+3 to exist)
    valid_as_of = sorted(out["as_of"].dt.strftime("%Y-%m-%d").unique())
    assert valid_as_of == ["2020-01-31", "2020-02-29"]


def test_forward_returns_skips_invalid_regime_rows():
    gmi = _gmi_history(["green", "unknown", "red", "yellow"])
    prices = {"X": _price_series([100, 105, 110, 116])}
    out = compute_forward_returns(gmi, prices, horizons=(1,))
    # 'unknown' row must be filtered out (only green/yellow/red kept)
    assert "unknown" not in out["regime"].unique()


def test_forward_returns_handles_multiple_markets():
    gmi = _gmi_history(["green"] * 4)
    prices = {
        "TWII": _price_series([100, 110, 120, 130]),
        "SPX":  _price_series([200, 210, 220, 230]),
    }
    out = compute_forward_returns(gmi, prices, horizons=(1,))
    assert sorted(out["market"].unique()) == ["SPX", "TWII"]
    assert len(out) == 6  # 3 valid as_of × 2 markets


def test_forward_returns_empty_inputs():
    assert compute_forward_returns(pd.DataFrame(), {"X": _price_series([1, 2])}).empty
    assert compute_forward_returns(_gmi_history(["green"] * 3), {}).empty


# ──────────────────────────────────────────────────────────────────────────────
# summarize_by_regime
# ──────────────────────────────────────────────────────────────────────────────

def test_summarize_handcrafted_stats():
    # 3 green rows (returns +10%, +20%, -5%) at horizon=1, market=X
    rows = [
        {"as_of": pd.Timestamp("2020-01-31"), "regime": "green", "market": "X",
         "horizon": 1, "fwd_log_return": np.log(1.10), "fwd_pct_return": 0.10},
        {"as_of": pd.Timestamp("2020-02-29"), "regime": "green", "market": "X",
         "horizon": 1, "fwd_log_return": np.log(1.20), "fwd_pct_return": 0.20},
        {"as_of": pd.Timestamp("2020-03-31"), "regime": "green", "market": "X",
         "horizon": 1, "fwd_log_return": np.log(0.95), "fwd_pct_return": -0.05},
    ]
    df = pd.DataFrame(rows)
    stats = summarize_by_regime(df, include_unconditional=False)
    g = stats[(stats["regime"] == "green") & (stats["horizon"] == 1)].iloc[0]
    # Median of {10, 20, -5} = 10
    assert g["median"] == pytest.approx(10.0)
    # Mean = 25/3 ≈ 8.333
    assert g["mean"] == pytest.approx(8.333, rel=1e-3)
    # 2 of 3 positive
    assert g["win_rate"] == pytest.approx(66.667, rel=1e-3)
    assert g["worst"] == pytest.approx(-5.0)
    assert int(g["n"]) == 3


def test_summarize_includes_unconditional_baseline():
    rows = [
        {"as_of": pd.Timestamp("2020-01-31"), "regime": "green", "market": "X",
         "horizon": 1, "fwd_log_return": 0.0, "fwd_pct_return": 0.10},
        {"as_of": pd.Timestamp("2020-02-29"), "regime": "red", "market": "X",
         "horizon": 1, "fwd_log_return": 0.0, "fwd_pct_return": -0.10},
    ]
    df = pd.DataFrame(rows)
    stats = summarize_by_regime(df, include_unconditional=True)
    all_row = stats[stats["regime"] == "all"]
    assert len(all_row) == 1
    # Pooled median of {10, -10} = 0
    assert all_row.iloc[0]["median"] == pytest.approx(0.0, abs=1e-6)
    assert int(all_row.iloc[0]["n"]) == 2


def test_summarize_empty():
    assert summarize_by_regime(pd.DataFrame()).empty


# ──────────────────────────────────────────────────────────────────────────────
# compute_cross_correlation
# ──────────────────────────────────────────────────────────────────────────────

def test_cross_correlation_identifies_zero_lag_for_identical_series():
    """When indicator IS the target YoY (built-in), peak should be at lag=0."""
    n = 60
    dates = pd.date_range("2020-01-31", periods=n, freq="ME")
    # Indicator = log return of price level (will == target_yoy after shift)
    np.random.seed(42)
    px = 100 * np.exp(np.cumsum(np.random.normal(0.01, 0.02, n)))
    tgt = pd.DataFrame({"date": dates, "value": px})
    # 12M log-return of price
    price_yoy_12m = np.log(np.array(px) / np.roll(np.array(px), 12))
    price_yoy_12m[:12] = np.nan
    ind = pd.DataFrame({"date": dates, "value": price_yoy_12m})

    out = compute_cross_correlation(
        {"FOO": ind}, {"BAR": tgt},
        indicator_keys=["FOO"], max_lag=6, min_overlap=20,
    )
    assert not out.empty
    # Peak absolute correlation should be at lag=0
    peak = out.loc[out["correlation"].abs().idxmax()]
    assert int(peak["lag"]) == 0
    assert peak["correlation"] == pytest.approx(1.0, abs=1e-6)


def test_cross_correlation_min_overlap_filter():
    # Too few observations should produce empty result
    dates = pd.date_range("2024-01-31", periods=20, freq="ME")
    ind = pd.DataFrame({"date": dates, "value": np.arange(20)})
    tgt = pd.DataFrame({"date": dates, "value": np.arange(20) ** 2})
    out = compute_cross_correlation(
        {"FOO": ind}, {"BAR": tgt},
        indicator_keys=["FOO"], max_lag=3, min_overlap=30,
    )
    assert out.empty
