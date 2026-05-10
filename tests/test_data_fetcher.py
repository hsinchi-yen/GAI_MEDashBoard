"""
Tests for data_fetcher.py ETF bulk utilities, sector rotation, and 13F proxy.

Focus areas (TDD):
- _etf_bulk_to_prices / _etf_bulk_to_volumes: price/volume extraction from bulk dict
- fetch_sector_rotation: rolling 3M semantics (not cumulative), signal direction
- fetch_13f_proxy: accepts etf_bulk, returns correct shape and signal direction
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from data_fetcher import (
    _etf_bulk_to_prices,
    _etf_bulk_to_volumes,
    fetch_sector_rotation,
    fetch_13f_proxy,
    SECTOR_ETFS,
    _ALL_SECTOR_ETFS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_dates(n_months: int, end_offset_months: int = 1) -> pd.DatetimeIndex:
    """Monthly MS dates ending end_offset_months complete months before now.

    Snap to day=1 first so date_range gets exactly n_months periods;
    a non-MS-aligned end silently produces periods-1 dates in pandas.
    """
    end = pd.Timestamp.now().replace(day=1) - pd.DateOffset(months=end_offset_months)
    return pd.date_range(end=end, periods=n_months, freq="MS")


def _build_bulk(
    dates: pd.DatetimeIndex,
    cyc_closes: list[float],
    def_closes: list[float],
    cyc_volumes: list[int] | None = None,
    def_volumes: list[int] | None = None,
) -> dict:
    """
    Construct a synthetic etf_bulk dict mirroring the shape returned by
    _fetch_etf_monthly(): {ticker: {dates, closes, volumes}}.
    All cyclical ETFs share the same price series; same for defensive.
    """
    n = len(dates)
    default_vol = [1_000_000] * n
    bulk: dict = {}
    for t in SECTOR_ETFS["cyclical"]:
        bulk[t] = {
            "dates":   dates,
            "closes":  cyc_closes[:],
            "volumes": (cyc_volumes or default_vol)[:],
        }
    for t in SECTOR_ETFS["defensive"]:
        bulk[t] = {
            "dates":   dates,
            "closes":  def_closes[:],
            "volumes": (def_volumes or default_vol)[:],
        }
    return bulk


def _price_series(n: int, monthly_ret: float, start: float = 100.0) -> list[float]:
    """Compound price series: prices[i+1] = prices[i] * (1 + monthly_ret)."""
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + monthly_ret))
    return prices


# ── TestEtfBulkToPrices ───────────────────────────────────────────────────────

class TestEtfBulkToPrices:
    def test_extracts_prices_to_dataframe(self):
        dates = _make_dates(6)
        closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        bulk = {"XLY": {"dates": dates, "closes": closes, "volumes": [1_000_000] * 6}}
        df = _etf_bulk_to_prices(bulk)
        assert "XLY" in df.columns
        assert len(df) == 6
        assert df["XLY"].iloc[0] == pytest.approx(100.0)

    def test_empty_ticker_skipped_gracefully(self):
        dates = _make_dates(6)
        bulk = {
            "XLY": {"dates": dates, "closes": [100.0] * 6, "volumes": [1_000_000] * 6},
            "XLI": {},
        }
        df = _etf_bulk_to_prices(bulk)
        assert "XLY" in df.columns
        assert "XLI" not in df.columns

    def test_non_numeric_closes_coerced_to_nan_and_dropped(self):
        dates = _make_dates(4)
        bulk = {
            "XLY": {"dates": dates, "closes": [100.0, "bad", 102.0, 103.0], "volumes": [1_000_000] * 4},
        }
        df = _etf_bulk_to_prices(bulk)
        assert len(df) <= 3

    def test_all_empty_returns_empty_dataframe(self):
        df = _etf_bulk_to_prices({})
        assert df.empty

    def test_index_is_datetime(self):
        dates = _make_dates(3)
        bulk = {"XLY": {"dates": dates, "closes": [100.0, 101.0, 102.0], "volumes": [1_000_000] * 3}}
        df = _etf_bulk_to_prices(bulk)
        assert pd.api.types.is_datetime64_any_dtype(df.index)

    def test_multiple_tickers_aligned_on_shared_index(self):
        dates = _make_dates(4)
        bulk = {
            "XLY": {"dates": dates, "closes": [100.0, 101.0, 102.0, 103.0], "volumes": [1_000_000] * 4},
            "XLI": {"dates": dates, "closes": [200.0, 201.0, 202.0, 203.0], "volumes": [2_000_000] * 4},
        }
        df = _etf_bulk_to_prices(bulk)
        assert "XLY" in df.columns and "XLI" in df.columns
        assert len(df) == 4
        assert df["XLI"].iloc[0] == pytest.approx(200.0)


# ── TestEtfBulkToVolumes ──────────────────────────────────────────────────────

class TestEtfBulkToVolumes:
    def test_extracts_volumes_to_dataframe(self):
        dates = _make_dates(4)
        vols = [1_000_000, 2_000_000, 3_000_000, 4_000_000]
        bulk = {"XLY": {"dates": dates, "closes": [100.0] * 4, "volumes": vols}}
        df = _etf_bulk_to_volumes(bulk)
        assert "XLY" in df.columns
        assert df["XLY"].iloc[0] == pytest.approx(1_000_000.0)
        assert df["XLY"].iloc[-1] == pytest.approx(4_000_000.0)

    def test_empty_ticker_skipped_gracefully(self):
        dates = _make_dates(4)
        bulk = {
            "XLY": {"dates": dates, "closes": [100.0] * 4, "volumes": [1_000_000] * 4},
            "XLI": {},
        }
        df = _etf_bulk_to_volumes(bulk)
        assert "XLY" in df.columns
        assert "XLI" not in df.columns

    def test_all_empty_returns_empty_dataframe(self):
        df = _etf_bulk_to_volumes({})
        assert df.empty

    def test_index_is_datetime(self):
        dates = _make_dates(3)
        bulk = {"XLY": {"dates": dates, "closes": [100.0] * 3, "volumes": [1_000_000, 2_000_000, 3_000_000]}}
        df = _etf_bulk_to_volumes(bulk)
        assert pd.api.types.is_datetime64_any_dtype(df.index)


# ── TestFetchSectorRotation ───────────────────────────────────────────────────

class TestFetchSectorRotation:
    """Uses synthetic etf_bulk — no real HTTP calls."""

    # Need ~30 months so dates survive both input cutoff (now-2y) and
    # output cutoff (now-1y) when years_back=1.
    N = 30

    def _uniform_bulk(self, cyc_ret: float, def_ret: float) -> dict:
        """All ETFs compound at constant monthly rates for N months."""
        dates = _make_dates(self.N)
        return _build_bulk(
            dates,
            cyc_closes=_price_series(self.N, cyc_ret),
            def_closes=_price_series(self.N, def_ret),
        )

    # ── signal direction ──────────────────────────────────────────────────────

    def test_positive_when_cyclicals_outperform(self):
        bulk = self._uniform_bulk(cyc_ret=0.02, def_ret=0.005)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert not result.empty
        assert result["value"].iloc[-1] > 0

    def test_negative_when_defensives_outperform(self):
        bulk = self._uniform_bulk(cyc_ret=0.005, def_ret=0.02)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert not result.empty
        assert result["value"].iloc[-1] < 0

    def test_near_zero_when_returns_equal(self):
        bulk = self._uniform_bulk(cyc_ret=0.01, def_ret=0.01)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert not result.empty
        assert result["value"].abs().max() < 1e-10

    # ── output shape ──────────────────────────────────────────────────────────

    def test_returns_dataframe_with_date_and_value_columns(self):
        bulk = self._uniform_bulk(cyc_ret=0.01, def_ret=0.01)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert list(result.columns) == ["date", "value"]

    def test_date_column_is_datetime(self):
        bulk = self._uniform_bulk(cyc_ret=0.01, def_ret=0.005)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        if not result.empty:
            assert pd.api.types.is_datetime64_any_dtype(result["date"])

    def test_value_column_is_numeric(self):
        bulk = self._uniform_bulk(cyc_ret=0.01, def_ret=0.005)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        if not result.empty:
            assert pd.api.types.is_numeric_dtype(result["value"])

    # ── guard: missing baskets ────────────────────────────────────────────────

    def test_empty_when_no_cyclical_etfs(self):
        dates = _make_dates(self.N)
        n = self.N
        bulk = {t: {"dates": dates, "closes": [100.0] * n, "volumes": [1_000_000] * n}
                for t in SECTOR_ETFS["defensive"]}
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert result.empty

    def test_empty_when_no_defensive_etfs(self):
        dates = _make_dates(self.N)
        n = self.N
        bulk = {t: {"dates": dates, "closes": [100.0] * n, "volumes": [1_000_000] * n}
                for t in SECTOR_ETFS["cyclical"]}
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert result.empty

    def test_empty_when_all_etf_data_empty(self):
        bulk = {t: {} for t in _ALL_SECTOR_ETFS}
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)
        assert result.empty

    # ── KEY TDD TEST: rolling 3M, not cumulative ──────────────────────────────

    def test_rolling_3m_not_cumulative(self):
        """
        Proves that rolling 3M semantics are used, not cumulative-from-inception.

        Setup:
          - Months 1 to (N-4): cyclicals +3%/mo, defensives +0.5%/mo
            (cumulative would show cyclicals massively ahead)
          - Last 3 months: cyclicals -3%/mo, defensives +3%/mo
            (rolling 3M should flip negative)

        With rolling 3M:   cyc_3m ≈ (0.97)^3 - 1 ≈ -8.7%  → excess < 0
        With cumulative:   cyc total >> def total             → excess > 0 (wrong)

        The assertion `last_value < 0` can only pass if implementation is rolling 3M.
        """
        n = self.N
        dates = _make_dates(n)

        # Build price series: final 3 months crash cyclicals
        cyc_prices = [100.0]
        def_prices = [100.0]
        for i in range(n - 1):
            if i < n - 4:
                cyc_prices.append(cyc_prices[-1] * 1.03)
                def_prices.append(def_prices[-1] * 1.005)
            else:
                cyc_prices.append(cyc_prices[-1] * 0.97)
                def_prices.append(def_prices[-1] * 1.03)

        bulk = _build_bulk(dates, cyc_closes=cyc_prices, def_closes=def_prices)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)

        assert not result.empty, "Expected non-empty result — check date range in test"
        last_value = result["value"].iloc[-1]
        assert last_value < 0, (
            f"Expected negative excess (defensives led last 3M), got {last_value:.6f}. "
            "If positive, the implementation uses cumulative returns instead of rolling 3M."
        )

    def test_rolling_3m_flips_positive_after_cyclical_rebound(self):
        """
        Complementary to the above: after a period where defensives led,
        3 months of strong cyclical recovery should flip the signal positive.
        Verifies the rolling window does not anchor to distant history.
        """
        n = self.N
        dates = _make_dates(n)

        cyc_prices = [100.0]
        def_prices = [100.0]
        for i in range(n - 1):
            if i < n - 4:
                # Defensives lead early
                cyc_prices.append(cyc_prices[-1] * 1.005)
                def_prices.append(def_prices[-1] * 1.03)
            else:
                # Cyclicals rebound last 3 months
                cyc_prices.append(cyc_prices[-1] * 1.04)
                def_prices.append(def_prices[-1] * 1.001)

        bulk = _build_bulk(dates, cyc_closes=cyc_prices, def_closes=def_prices)
        result = fetch_sector_rotation(etf_bulk=bulk, years_back=1)

        assert not result.empty
        last_value = result["value"].iloc[-1]
        assert last_value > 0, (
            f"Expected positive excess (cyclicals rebounded last 3M), got {last_value:.6f}."
        )


# ── TestFetch13fProxy ─────────────────────────────────────────────────────────

class TestFetch13fProxy:
    N = 30

    def _uniform_bulk(self, cyc_vol_growth: float = 0.0, def_vol_growth: float = 0.0) -> dict:
        dates = _make_dates(self.N)
        n = self.N

        def vol_series(monthly_growth: float) -> list[int]:
            vols = [1_000_000]
            for _ in range(n - 1):
                vols.append(int(vols[-1] * (1 + monthly_growth)))
            return vols

        return _build_bulk(
            dates,
            cyc_closes=[100.0] * n,
            def_closes=[100.0] * n,
            cyc_volumes=vol_series(cyc_vol_growth),
            def_volumes=vol_series(def_vol_growth),
        )

    def test_accepts_etf_bulk_and_returns_dataframe(self):
        bulk = self._uniform_bulk(cyc_vol_growth=0.02, def_vol_growth=0.005)
        result = fetch_13f_proxy(etf_bulk=bulk, years_back=1)
        assert isinstance(result, pd.DataFrame)

    def test_returns_date_and_value_columns_when_non_empty(self):
        bulk = self._uniform_bulk(cyc_vol_growth=0.02, def_vol_growth=0.005)
        result = fetch_13f_proxy(etf_bulk=bulk, years_back=1)
        if not result.empty:
            assert "date" in result.columns
            assert "value" in result.columns

    def test_positive_when_cyclical_volume_accelerating(self):
        """Cyclical volumes grow faster → positive volume-acceleration ratio."""
        bulk = self._uniform_bulk(cyc_vol_growth=0.08, def_vol_growth=0.01)
        result = fetch_13f_proxy(etf_bulk=bulk, years_back=1)
        if not result.empty:
            assert result["value"].iloc[-1] > 0

    def test_negative_when_defensive_volume_accelerating(self):
        """Defensive volumes grow faster → negative ratio (risk-off signal)."""
        bulk = self._uniform_bulk(cyc_vol_growth=0.01, def_vol_growth=0.08)
        result = fetch_13f_proxy(etf_bulk=bulk, years_back=1)
        if not result.empty:
            assert result["value"].iloc[-1] < 0

    def test_empty_when_all_etf_data_empty(self):
        bulk = {t: {} for t in _ALL_SECTOR_ETFS}
        result = fetch_13f_proxy(etf_bulk=bulk, years_back=1)
        assert result.empty

    def test_date_column_within_years_back_window(self):
        bulk = self._uniform_bulk(cyc_vol_growth=0.02, def_vol_growth=0.005)
        result = fetch_13f_proxy(etf_bulk=bulk, years_back=1)
        if not result.empty:
            cutoff = pd.Timestamp.now() - pd.DateOffset(years=1)
            assert result["date"].min() >= cutoff
