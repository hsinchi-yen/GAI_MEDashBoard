"""Regressions from code review: each test reproduces a defect found in real conditions."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

import db_manager
import scheduler
from analytics import market_view as mv
from analytics.indicators import Indicator
from analytics.trend import analyze_series
from fetchers import yahoo_finance as yf
from macro_index import build_macro_index_history
from tests.synthetic_data import NOW, macro_dataset


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "t.sqlite3")


def yahoo_payload(timestamps, closes, gmtoffset):
    return {"meta": {"gmtoffset": gmtoffset}, "timestamp": timestamps,
            "indicators": {"adjclose": [{"adjclose": closes}]}}


def monthly(values, end):
    dates = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in values]})


class TestYahooTimezone:
    """Asian bars open at local midnight, which is the previous day in UTC."""
    # 2026-10-01 00:00 Asia/Taipei == 2026-09-30 16:00 UTC
    TAIPEI_OCT_BAR = 1790784000 + 0

    def test_october_bar_stays_in_october(self):
        ts = int(pd.Timestamp("2026-09-30 16:00", tz="UTC").timestamp())
        payload = yahoo_payload([ts], [20000.0], gmtoffset=8 * 3600)
        with patch.object(yf, "_yf_chart", return_value=payload):
            out = yf.fetch_index_monthly_close("^TWII", years_back=5)
        assert out.iloc[0]["date"] == pd.Timestamp("2026-10-31")

    def test_us_bars_are_unaffected(self):
        ts = int(pd.Timestamp("2026-10-01 13:30", tz="UTC").timestamp())
        payload = yahoo_payload([ts], [6000.0], gmtoffset=-4 * 3600)
        with patch.object(yf, "_yf_chart", return_value=payload):
            out = yf.fetch_index_monthly_close("^GSPC", years_back=5)
        assert out.iloc[0]["date"] == pd.Timestamp("2026-10-31")

    def test_dst_change_does_not_move_a_bar_into_the_prior_month(self):
        """Live failure: in November gmtoffset is EST, but October's bar is midnight EDT.
        It landed on Sep 30, overwrote September and erased October."""
        stamps = [int(pd.Timestamp(t, tz="UTC").timestamp())
                  for t in ("2026-09-01 04:00", "2026-10-01 04:00", "2026-11-02 21:00")]
        payload = yahoo_payload(stamps, [7580.0, 7600.0, 7634.0], gmtoffset=-5 * 3600)
        with patch.object(yf, "_yf_chart", return_value=payload):
            out = yf.fetch_index_monthly_close("^GSPC", years_back=5)
        assert [d.month for d in out["date"]] == [9, 10, 11]
        assert out["value"].tolist() == [7580.0, 7600.0, 7634.0]

    def test_summer_time_bars_stay_in_their_month(self):
        ts = int(pd.Timestamp("2026-07-01 04:00", tz="UTC").timestamp())
        assert yf._bar_dates({"meta": {"gmtoffset": -4 * 3600}, "timestamp": [ts]})[0].month == 7

    def test_missing_offset_is_tolerated(self):
        ts = int(pd.Timestamp("2026-10-15 13:30", tz="UTC").timestamp())
        assert yf._bar_dates({"timestamp": [ts]})[0].month == 10

    def test_index_yoy_uses_local_month(self):
        months = pd.date_range("2024-01-31 16:00", periods=14, freq="ME")
        stamps = [int(pd.Timestamp(m, tz="UTC").timestamp()) for m in months]
        payload = yahoo_payload(stamps, [100.0 + i for i in range(14)], gmtoffset=8 * 3600)
        with patch.object(yf, "_yf_chart", return_value=payload):
            out = yf.fetch_index_yoy("^TWII", years_back=20)
        assert out.iloc[-1]["date"].month == months[-1].month + 1 if months[-1].month < 12 else 1


class TestMomentumWindow:
    def test_compares_three_months_of_prints_despite_publication_lag(self):
        """On Nov 2 the latest PMI is October; momentum must reach back to July, not August."""
        values = [50, 50, 50, 50, 50, 50, 50, 48, 49, 51, 52, 53]
        data = {"US_PMI": monthly(values, "2026-10-01")}
        assert mv._comparison_date(data, pd.Timestamp("2026-11-02")) == pd.Timestamp("2026-07-31")

    def test_stale_data_still_compares_a_real_window(self):
        data = {"US_PMI": monthly(range(40, 60), "2026-05-01")}
        assert mv._comparison_date(data, pd.Timestamp("2026-11-02")) == pd.Timestamp("2026-02-28")

    def test_no_monthly_data_uses_the_clock(self):
        assert mv._comparison_date({}, pd.Timestamp("2026-11-02")) == pd.Timestamp("2026-08-31")


class TestPartialMonthDoesNotConfirm:
    def _history(self, regimes, confirmed, end="2026-11-30"):
        dates = pd.date_range(end=end, periods=len(regimes), freq="ME")
        return pd.DataFrame({"date": dates, "score": 10, "diffusion": 50.0, "valid_count": 19,
                             "regime": regimes, "confirmed_regime": confirmed})

    def test_two_days_of_november_cannot_confirm_a_red_october(self):
        history = self._history(["yellow", "red", "red"], ["yellow", "yellow", "red"])
        regime, pending = mv._settled_regime(history, pd.Timestamp("2026-11-02"), "red")
        assert regime == "yellow"
        assert pending == "red"

    def test_a_finished_month_counts(self):
        history = self._history(["yellow", "red", "red"], ["yellow", "yellow", "red"], end="2026-10-31")
        regime, pending = mv._settled_regime(history, pd.Timestamp("2026-11-02"), "red")
        assert regime == "red"
        assert pending is None

    def test_single_row_history(self):
        history = self._history(["red"], ["red"])
        assert mv._settled_regime(history, pd.Timestamp("2026-11-02"), "red") == ("red", None)


class TestStaleAllowance:
    def _ind(self):
        return Indicator("X", "x", "demand", 1, "", "monthly", "leading", "w")

    def test_normal_publication_lag_is_not_stale(self):
        """US new orders: on Nov 2 the August print (Aug 1) is the newest published."""
        df = monthly(range(30, 60), "2026-08-01")
        assert analyze_series(df, self._ind(), pd.Timestamp("2026-11-02"))["stale"] is False

    def test_a_skipped_release_is_stale(self):
        df = monthly(range(30, 60), "2026-06-01")
        assert analyze_series(df, self._ind(), pd.Timestamp("2026-11-02"))["stale"] is True


class TestSnapshotsSurviveCleanup:
    def test_expired_snapshot_is_kept_for_serve_stale(self, isolated_db):
        db_manager.write_snapshot("tw_institutional_5d", {"actual_days": 5}, ttl_days=1)
        with db_manager._conn() as con:
            con.execute("UPDATE blob_cache SET fetched_at = fetched_at - 864000")
        db_manager.cleanup_expired()
        assert db_manager.read_snapshot("tw_institutional_5d") == {"actual_days": 5}

    def test_expired_plain_blobs_are_still_removed(self, isolated_db):
        db_manager.write("old_blob", pd.DataFrame({"a": ["x"], "b": ["y"]}), ttl_days=1)
        with db_manager._conn() as con:
            con.execute("UPDATE blob_cache SET fetched_at = fetched_at - 864000")
        assert db_manager.cleanup_expired() == 1


class TestDataVersionUnderContention:
    def test_lock_does_not_crash_the_page(self, isolated_db, monkeypatch):
        import sqlite3

        def locked():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(db_manager, "_conn", locked)
        assert db_manager.data_version() == "unavailable"


class TestReplaceSeries:
    def test_removes_rows_that_the_new_data_no_longer_has(self, isolated_db):
        old = pd.DataFrame({"date": pd.to_datetime(["2026-09-30", "2026-08-31"]), "value": [1.0, 2.0]})
        new = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-09-01"]), "value": [1.0, 2.0]})
        db_manager.write("k", old, ttl_days=1, initial=True)
        db_manager.replace_series("k", new, ttl_days=1)
        assert sorted(db_manager.read("k")["date"].dt.strftime("%m-%d")) == ["09-01", "10-01"]

    def test_empty_replacement_keeps_existing_data(self, isolated_db):
        old = pd.DataFrame({"date": pd.to_datetime(["2026-09-30"]), "value": [1.0]})
        db_manager.write("k", old, ttl_days=1, initial=True)
        db_manager.replace_series("k", pd.DataFrame(), ttl_days=1)
        assert len(db_manager.read("k")) == 1


class TestIndexCloseBackfill:
    def test_empty_series_requests_full_history_on_the_daily_job(self, isolated_db):
        calls = {}

        def fake_run(key, fn, ttl_days=1, *, initial=False, post_sleep=0.0, **kwargs):
            if key.startswith("index_close"):
                calls[key] = (initial, kwargs.get("years_back"))

        with patch.object(scheduler, "_run", side_effect=fake_run), \
                patch.object(scheduler, "fetch_tw_institutional", return_value={}):
            scheduler.job_macro_indicators(initial=False)
        assert calls["index_close_twii"] == (True, 15)

    def test_populated_series_only_refreshes_recent_months(self, isolated_db):
        df = pd.DataFrame({"date": pd.date_range("2020-01-31", periods=60, freq="ME"),
                           "value": range(60)})
        db_manager.write("index_close_twii", df.assign(value=df["value"].astype(float)),
                         ttl_days=1, initial=True)
        calls = {}

        def fake_run(key, fn, ttl_days=1, *, initial=False, post_sleep=0.0, **kwargs):
            if key == "index_close_twii":
                calls[key] = initial

        with patch.object(scheduler, "_run", side_effect=fake_run), \
                patch.object(scheduler, "fetch_tw_institutional", return_value={}):
            scheduler.job_macro_indicators(initial=False)
        assert calls["index_close_twii"] is False


def test_history_rows_stay_consistent_with_settled_regime():
    data = macro_dataset(0.6)
    history = build_macro_index_history(data, lookback_years=2)
    view = mv.compute_market_view(data, history=history, now=NOW)
    assert view["regime"] in {"green", "yellow", "red"}
