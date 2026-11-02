"""Regression tests: GMI "3M" rules must measure three *months*, not three rows.

VIX, HY spread, USD/TWD and T10Y3M are daily FRED series. The trend helpers used
to slice by row count, so a rule labelled "3M 下降" really compared the last few
trading days and the regime flipped on daily noise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import macro_index as mi


def _daily(start: str, end: str, values) -> pd.DataFrame:
    dates = pd.bdate_range(start, end)
    return pd.DataFrame({"date": dates, "value": np.resize(values, len(dates))})


def _monthly(values, end: str = "2026-09-01") -> pd.DataFrame:
    dates = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in values]})


class TestMonthlyNormalisation:
    def test_daily_series_collapses_to_last_obs_per_month(self):
        df = _daily("2026-01-01", "2026-03-31", np.arange(1000.0))
        out = mi._to_monthly(df)
        assert len(out) == 3
        assert out["date"].is_monotonic_increasing
        assert out.iloc[-1]["value"] == df.iloc[-1]["value"]

    def test_monthly_series_is_unchanged(self):
        df = _monthly([1, 2, 3, 4])
        out = mi._to_monthly(df)
        assert out["value"].tolist() == [1.0, 2.0, 3.0, 4.0]

    def test_nan_rows_are_ignored(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2026-01-05", "2026-01-20"]),
                           "value": [1.0, np.nan]})
        assert mi._to_monthly(df)["value"].tolist() == [1.0]

    def test_empty_and_none_are_safe(self):
        assert mi._to_monthly(None).empty
        assert mi._to_monthly(pd.DataFrame()).empty


class TestThreeMonthDown:
    def test_daily_blip_does_not_override_three_month_rise(self):
        """VIX rose 15→30 over 3M; a 3-day dip at the end must not read as 'down'."""
        dates = pd.bdate_range("2026-06-01", "2026-09-30")
        values = np.linspace(15, 31, len(dates))
        values[-3:] = [30.5, 30.0, 29.5]
        df = pd.DataFrame({"date": dates, "value": values})
        assert mi._3m_down(df) is False

    def test_daily_blip_does_not_override_three_month_fall(self):
        dates = pd.bdate_range("2026-06-01", "2026-09-30")
        values = np.linspace(31, 15, len(dates))
        values[-3:] = [15.0, 15.5, 16.0]
        df = pd.DataFrame({"date": dates, "value": values})
        assert mi._3m_down(df) is True

    def test_monthly_compares_exactly_three_months_back(self):
        # latest(10) < 3M ago(11), though it is above 2M ago(9).
        assert mi._3m_down(_monthly([5, 11, 9, 9.5, 10])) is True

    def test_needs_four_month_ends(self):
        assert mi._3m_down(_monthly([3, 2, 1])) is None


class TestSlopeUsesMonths:
    def test_daily_slope_ignores_final_day_noise(self):
        dates = pd.bdate_range("2026-06-01", "2026-09-30")
        values = np.linspace(1.0, 2.0, len(dates))
        values[-3:] = [1.99, 1.95, 1.90]
        df = pd.DataFrame({"date": dates, "value": values})
        assert mi._slope_positive(df) is True

    def test_avg_improving_on_daily_series_uses_months(self):
        dates = pd.bdate_range("2026-01-01", "2026-09-30")
        df = pd.DataFrame({"date": dates, "value": np.linspace(0, 10, len(dates))})
        assert mi._avg_improving(df) is True


class TestRegimeStability:
    def test_signal_is_stable_across_consecutive_days(self):
        """A smooth multi-month downtrend with choppy days must not flip day to day."""
        rng = np.random.default_rng(7)
        dates = pd.bdate_range("2026-03-02", "2026-09-30")
        base = np.linspace(30, 14, len(dates))
        df = pd.DataFrame({"date": dates, "value": base + rng.normal(0, 0.8, len(dates))})
        readings = {mi._sig_vix_down(df.iloc[: len(df) - k])[0] for k in range(0, 8)}
        assert readings == {1}

    @pytest.mark.parametrize("fn", [mi._sig_hy_spread_down, mi._sig_twd_appreciating])
    def test_other_daily_series_follow_the_same_window(self, fn):
        dates = pd.bdate_range("2026-05-01", "2026-09-30")
        values = np.linspace(4.5, 3.0, len(dates))
        values[-2:] = [3.2, 3.4]
        assert fn(pd.DataFrame({"date": dates, "value": values}))[0] == 1


class TestHistoryPerformanceShape:
    def test_precomputed_monthly_history_matches_live_scoring(self):
        """The month-end shortcut must give the same answer as scoring raw dailies."""
        from tests.synthetic_data import NOW, macro_dataset
        data = macro_dataset(0.6)
        hist = mi.build_macro_index_history(data, lookback_years=1)
        as_of = pd.Timestamp(hist.iloc[-3]["date"])
        direct = mi.compute_macro_index(mi._slice_data_as_of(data, as_of))
        assert hist.iloc[-3]["score"] == direct["score"]
        assert hist.iloc[-3]["valid_count"] == direct["valid_count"]
        assert hist.iloc[-1]["date"] >= NOW.replace(day=1) - pd.DateOffset(months=1)


class TestSnapshotSlicing:
    def test_clock_with_nanoseconds_works_on_coarser_date_units(self):
        """`now` carries ns; pandas 3 stores dates in us. Must not raise."""
        df = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=5, freq="MS").as_unit("us"),
                           "value": [1.0, 2.0, 3.0, 4.0, 5.0]})
        out = mi._truncate_frame(df, pd.Timestamp("2026-03-15 12:34:56.123456789"))
        assert out["value"].tolist() == [1.0, 2.0, 3.0]

    def test_unsorted_frames_still_slice_correctly(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2026-03-01", "2026-01-01", "2026-02-01"]),
                           "value": [3.0, 1.0, 2.0]})
        assert mi._truncate_frame(df, pd.Timestamp("2026-02-15"))["value"].tolist() == [1.0, 2.0]


class TestFastPathsKeepSemantics:
    def test_string_dates_and_values_still_parse(self):
        df = pd.DataFrame({"date": ["2026-01-01", "2026-02-01", "bad"], "value": ["1", "2", "3"]})
        assert mi._to_monthly(df)["value"].tolist() == [1.0, 2.0]

    def test_integer_values_are_accepted(self):
        df = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=2, freq="MS"), "value": [1, 2]})
        assert mi._latest(df) == 2.0
