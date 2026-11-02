"""Unit tests for analytics.trend — per-series direction, position and staleness."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.indicators import REGISTRY, Indicator, all_indicators, by_theme, THEMES
from analytics import trend

NOW = pd.Timestamp("2026-10-15")


def monthly(values, end="2026-09-01") -> pd.DataFrame:
    dates = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in values]})


def ind(polarity=+1, freq="monthly", unit="", decimals=1) -> Indicator:
    return Indicator("X", "測試指標", "demand", polarity, unit, freq, "leading", "why", decimals)


class TestCatalogue:
    def test_keys_are_unique_and_match_registry(self):
        assert len(REGISTRY) == len(all_indicators())

    def test_every_theme_is_populated(self):
        for theme in THEMES:
            assert by_theme(theme), theme

    def test_polarity_is_never_zero(self):
        assert {i.polarity for i in all_indicators()} == {1, -1}

    def test_risk_gauges_read_inverted(self):
        for key in ("VIX", "HY_SPREAD", "DXY", "US_CORE_CPI_YOY"):
            assert REGISTRY[key].polarity == -1

    def test_every_indicator_explains_itself(self):
        assert all(i.why and i.page for i in all_indicators())


class TestAnalyzeSeries:
    def test_returns_none_without_enough_history(self):
        assert trend.analyze_series(None, ind(), NOW) is None
        assert trend.analyze_series(pd.DataFrame(), ind(), NOW) is None
        assert trend.analyze_series(monthly([1, 2, 3]), ind(), NOW) is None

    def test_rising_positive_polarity_is_bullish(self):
        r = trend.analyze_series(monthly(range(1, 40)), ind(), NOW)
        assert r["direction"] == "up"
        assert r["signal"] == "bullish"

    def test_rising_negative_polarity_is_bearish(self):
        r = trend.analyze_series(monthly(range(1, 40)), ind(polarity=-1), NOW)
        assert r["direction"] == "up"
        assert r["signal"] == "bearish"

    def test_falling_negative_polarity_is_bullish(self):
        r = trend.analyze_series(monthly(range(40, 1, -1)), ind(polarity=-1), NOW)
        assert r["direction"] == "down"
        assert r["signal"] == "bullish"

    def test_flat_series_is_neutral(self):
        r = trend.analyze_series(monthly([50.0] * 40), ind(), NOW)
        assert r["direction"] == "flat"
        assert r["signal"] == "neutral"
        assert r["zscore"] == 0.0

    def test_noise_within_normal_range_counts_as_flat(self):
        rng = np.random.default_rng(1)
        values = 50 + rng.normal(0, 2, 60)
        values[-4:] = [50.0, 50.1, 50.0, 50.1]
        r = trend.analyze_series(monthly(values), ind(), NOW)
        assert r["direction"] == "flat"

    def test_changes_are_measured_in_months(self):
        r = trend.analyze_series(monthly(range(1, 40)), ind(), NOW)
        assert r["change_1m"] == pytest.approx(1.0)
        assert r["change_3m"] == pytest.approx(3.0)
        assert r["change_6m"] == pytest.approx(6.0)

    def test_daily_series_is_monthly_normalised(self):
        dates = pd.bdate_range("2023-01-02", "2026-10-14")
        df = pd.DataFrame({"date": dates, "value": np.linspace(10, 40, len(dates))})
        r = trend.analyze_series(df, ind(freq="daily"), NOW)
        assert r["direction"] == "up"
        assert r["latest_date"] == dates[-1]
        assert len(r["spark"]) == trend.SPARK_MONTHS

    def test_percentile_at_top_of_range(self):
        r = trend.analyze_series(monthly(range(1, 70)), ind(), NOW)
        assert r["percentile"] == pytest.approx(100.0)

    def test_percentile_uses_five_year_window(self):
        old_high = [1000.0] * 12
        recent = list(np.linspace(10, 20, 60))
        r = trend.analyze_series(monthly(old_high + recent), ind(), NOW)
        assert r["percentile"] == pytest.approx(100.0)

    def test_zscore_sign_follows_level(self):
        high = trend.analyze_series(monthly(list(range(1, 40)) + [80]), ind(), NOW)
        assert high["zscore"] > 1.5


class TestStage:
    def test_high_and_rising_is_strong(self):
        assert trend.analyze_series(monthly(range(1, 40)), ind(), NOW)["stage"] == "強勢"

    def test_low_and_rising_is_recovering(self):
        values = list(range(60, 10, -1)) + [11, 13, 15, 17, 19]
        assert trend.analyze_series(monthly(values), ind(), NOW)["stage"] == "回升"

    def test_high_and_falling_is_fading(self):
        values = list(range(10, 60)) + [58, 56, 54, 52, 50]
        assert trend.analyze_series(monthly(values), ind(), NOW)["stage"] == "轉弱"

    def test_low_and_falling_is_weak(self):
        assert trend.analyze_series(monthly(range(60, 10, -1)), ind(), NOW)["stage"] == "弱勢"

    def test_stage_is_polarity_adjusted(self):
        """VIX high and rising is bad news: weak, not strong."""
        r = trend.analyze_series(monthly(range(1, 40)), ind(polarity=-1), NOW)
        assert r["stage"] == "弱勢"

    def test_flat_stage_reports_the_level_side(self):
        assert trend.analyze_series(monthly([50.0] * 40), ind(), NOW)["stage"] == "盤整"


class TestStaleness:
    def test_fresh_monthly_series(self):
        assert trend.analyze_series(monthly(range(1, 40)), ind(), NOW)["stale"] is False

    def test_old_monthly_series_is_stale(self):
        r = trend.analyze_series(monthly(range(1, 40), end="2024-01-01"), ind(), NOW)
        assert r["stale"] is True
        assert r["age_days"] > 900

    def test_daily_series_has_a_shorter_allowance(self):
        dates = pd.bdate_range("2023-01-02", "2026-09-15")
        df = pd.DataFrame({"date": dates, "value": np.arange(len(dates), dtype=float)})
        assert trend.analyze_series(df, ind(freq="daily"), NOW)["stale"] is True


class TestFormatting:
    def test_format_value_applies_unit_and_decimals(self):
        assert trend.format_value(3.456, ind(unit="%", decimals=2)) == "3.46%"
        assert trend.format_value(345.6, ind(unit=" bps", decimals=0)) == "346 bps"

    def test_format_value_handles_none(self):
        assert trend.format_value(None, ind()) == "—"

    def test_format_delta_has_explicit_sign(self):
        assert trend.format_delta(1.25, ind(decimals=1)) == "+1.2"
        assert trend.format_delta(-1.0, ind(decimals=1)) == "-1.0"
        assert trend.format_delta(None, ind()) == "—"


class TestBuildRadar:
    def _data(self):
        return {
            "US_PMI": monthly(range(30, 70)),
            "VIX": monthly(range(70, 30, -1)),
            "HY_SPREAD": monthly(range(30, 70)),
            "YIELD_CURVE": {"10Y": monthly(range(1, 40))},  # non-frame entries ignored
        }

    def test_rows_only_for_series_with_data(self):
        radar = trend.build_radar(self._data(), NOW)
        assert set(radar["key"]) == {"US_PMI", "VIX", "HY_SPREAD"}

    def test_empty_input_yields_expected_columns(self):
        radar = trend.build_radar({}, NOW)
        assert radar.empty
        assert {"key", "signal", "stage"}.issubset(radar.columns)

    def test_signals_are_polarity_aware(self):
        radar = trend.build_radar(self._data(), NOW).set_index("key")
        assert radar.loc["US_PMI", "signal"] == "bullish"
        assert radar.loc["VIX", "signal"] == "bullish"
        assert radar.loc["HY_SPREAD", "signal"] == "bearish"

    def test_breadth_counts_each_signal(self):
        radar = trend.build_radar(self._data(), NOW)
        b = trend.breadth(radar)
        assert b == {"bullish": 2, "bearish": 1, "neutral": 0, "total": 3, "net_pct": pytest.approx(33.3, abs=0.1)}

    def test_breadth_of_empty_radar(self):
        assert trend.breadth(pd.DataFrame())["total"] == 0

    def test_inflection_flags_turning_points(self):
        data = {"US_PMI": monthly(list(range(60, 20, -1)) + [24, 27, 30])}
        radar = trend.build_radar(data, NOW)
        assert radar.iloc[0]["inflection"] == "turning_up"

    def test_inflection_is_polarity_adjusted(self):
        data = {"VIX": monthly(list(range(60, 20, -1)) + [24, 27, 30])}
        radar = trend.build_radar(data, NOW)
        assert radar.iloc[0]["inflection"] == "turning_down"
