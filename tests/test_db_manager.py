"""
test_db_manager.py — unit tests for db_manager.py

Covers:
  - _is_grouped_ts(): detection logic (pandas 2.x StringDtype compatible)
  - _dates_to_days(): resolution-independent day conversion
  - Simple ts: bulk write, delta write, read, TTL
  - Grouped ts: bulk write, delta write, read
  - Blob cache: write, read, TTL
  - Utility: is_fresh, list_keys, trim_to_window
"""
from __future__ import annotations

import os
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import numpy as np
import pytest

import db_manager


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirect DB to a fresh temp file for every test."""
    db_path = tmp_path / "test_indicator_cache.sqlite3"
    monkeypatch.setattr(db_manager, "_DB_PATH", db_path)
    yield db_path


def _simple_df(n: int = 5, start: str = "2024-01-01") -> pd.DataFrame:
    dates  = pd.date_range(start, periods=n, freq="D")
    values = [float(i) for i in range(n)]
    return pd.DataFrame({"date": dates, "value": values})


def _grouped_df(sectors: list[str] | None = None, n_days: int = 3,
                start: str = "2024-01-01", value_col: str = "close") -> pd.DataFrame:
    sectors = sectors or ["電子", "金融", "航運"]
    rows = []
    for i, day in enumerate(pd.date_range(start, periods=n_days)):
        for s in sectors:
            rows.append({"date": day, "sector_name": s, value_col: float(i * len(sectors))})
    return pd.DataFrame(rows)


# ── _is_grouped_ts ─────────────────────────────────────────────────────────────

class TestIsGroupedTs:
    def test_detects_grouped_df(self):
        df = _grouped_df()
        ok, gc, vc = db_manager._is_grouped_ts(df)
        assert ok
        assert gc == "sector_name"
        assert vc == "close"

    def test_rejects_simple_ts(self):
        df = _simple_df()
        ok, *_ = db_manager._is_grouped_ts(df)
        assert not ok

    def test_rejects_no_date_column(self):
        df = pd.DataFrame({"a": ["x", "y"], "b": [1.0, 2.0]})
        ok, *_ = db_manager._is_grouped_ts(df)
        assert not ok

    def test_rejects_four_column_df(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "col_a": ["x"],
            "col_b": [1.0],
            "col_c": [2.0],
        })
        ok, *_ = db_manager._is_grouped_ts(df)
        assert not ok

    def test_rejects_two_numeric_cols(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "a": [1.0],
            "b": [2.0],
        })
        ok, *_ = db_manager._is_grouped_ts(df)
        assert not ok

    def test_handles_object_dtype_string_col(self):
        """Legacy object dtype (pandas < 2.x) should also be detected."""
        df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "sector_name": pd.array(["電子", "金融"], dtype=object),
            "close": [100.0, 200.0],
        })
        ok, gc, vc = db_manager._is_grouped_ts(df)
        assert ok
        assert gc == "sector_name"
        assert vc == "close"


# ── _dates_to_days ────────────────────────────────────────────────────────────

class TestDatesToDays:
    def test_known_epoch_date(self):
        df = pd.DataFrame({"date": pd.to_datetime(["1970-01-01"])})
        assert db_manager._dates_to_days(df["date"]) == [0]

    def test_two_days_after_epoch(self):
        df = pd.DataFrame({"date": pd.to_datetime(["1970-01-03"])})
        assert db_manager._dates_to_days(df["date"]) == [2]

    def test_2024_date_correct_magnitude(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"])})
        days = db_manager._dates_to_days(df["date"])[0]
        # 2024-01-02 is ~19724 days after epoch
        assert 19700 < days < 19800, f"Unexpected day_epoch: {days}"

    def test_datetime64_us_and_ns_match(self):
        """Both resolutions must give identical day numbers."""
        d = pd.Timestamp("2025-06-15")
        ns = pd.Series([d]).astype("datetime64[ns]")
        us = pd.Series([d]).astype("datetime64[us]")
        assert db_manager._dates_to_days(ns) == db_manager._dates_to_days(us)


# ── Simple time-series write / read ──────────────────────────────────────────

class TestSimpleTs:
    def test_bulk_write_then_read_returns_correct_shape(self):
        df = _simple_df(5)
        db_manager.write("ts_test", df, ttl_days=1, initial=True)
        r = db_manager.read("ts_test")
        assert r is not None
        assert list(r.columns) == ["date", "value"]
        assert len(r) == 5

    def test_bulk_is_idempotent(self):
        df = _simple_df(5)
        db_manager.write("ts_idem", df, ttl_days=1, initial=True)
        db_manager.write("ts_idem", df, ttl_days=1, initial=True)   # re-run
        r = db_manager.read("ts_idem")
        assert len(r) == 5   # no duplicate rows

    def test_dates_roundtrip_correctly(self):
        df = _simple_df(3, start="2024-06-01")
        db_manager.write("ts_dates", df, ttl_days=1, initial=True)
        r = db_manager.read("ts_dates")
        orig_dates = pd.to_datetime(df["date"]).dt.normalize()
        read_dates = pd.to_datetime(r["date"]).dt.normalize()
        pd.testing.assert_series_equal(
            orig_dates.reset_index(drop=True),
            read_dates.reset_index(drop=True),
            check_names=False,
            check_dtype=False,   # _from_day() gives datetime64[s]; input may be datetime64[us]
        )

    def test_values_roundtrip_correctly(self):
        df = _simple_df(4)
        db_manager.write("ts_vals", df, ttl_days=1, initial=True)
        r = db_manager.read("ts_vals")
        assert list(r["value"]) == list(df["value"].values)

    def test_delta_write_keeps_recent_rows(self):
        """Delta write should store rows within DELTA_DAYS window."""
        recent = pd.DataFrame({
            "date":  pd.to_datetime(["2026-05-20", "2026-05-21"]),
            "value": [1.0, 2.0],
        })
        db_manager.write("ts_delta", recent, ttl_days=1, initial=False)
        r = db_manager.read("ts_delta")
        assert r is not None and len(r) == 2

    def test_delta_write_skips_old_rows(self):
        """Rows older than DELTA_DAYS must not be written in delta mode."""
        old = pd.DataFrame({
            "date":  pd.to_datetime(["2010-01-01", "2010-01-02"]),
            "value": [9.0, 8.0],
        })
        db_manager.write("ts_old", old, ttl_days=1, initial=False)
        r = db_manager.read("ts_old")
        # Either None (ts_meta not set because nothing was written) or empty
        assert r is None or r.empty

    def test_read_returns_none_when_key_missing(self):
        assert db_manager.read("__does_not_exist__") is None

    def test_read_returns_none_when_ttl_expired(self):
        df = _simple_df(2)
        db_manager.write("ts_exp", df, ttl_days=1, initial=True)
        # Mock time to be 2 days in the future
        future = int(time.time()) + 2 * 86400 + 10
        with patch.object(db_manager, "_today_day", return_value=future // 86400):
            with patch("time.time", return_value=float(future)):
                r = db_manager.read("ts_exp")
        assert r is None


# ── Grouped time-series write / read ─────────────────────────────────────────

class TestGroupedTs:
    def test_bulk_write_read_returns_correct_columns(self):
        df = _grouped_df(["電子", "金融"])
        db_manager.write("grp_test", df, ttl_days=1, initial=True)
        r = db_manager.read("grp_test")
        assert r is not None
        assert list(r.columns) == ["date", "series_key", "value"]

    def test_bulk_write_preserves_all_series(self):
        sectors = ["電子", "金融", "航運"]
        df = _grouped_df(sectors)
        db_manager.write("grp_series", df, ttl_days=1, initial=True)
        r = db_manager.read("grp_series")
        assert set(r["series_key"].unique()) == set(sectors)

    def test_bulk_write_is_idempotent(self):
        df = _grouped_df(["電子"], n_days=3)
        db_manager.write("grp_idem", df, ttl_days=1, initial=True)
        db_manager.write("grp_idem", df, ttl_days=1, initial=True)
        r = db_manager.read("grp_idem")
        assert len(r) == 3

    def test_dates_roundtrip_correctly(self):
        df = _grouped_df(["電子"], n_days=2, start="2025-03-10")
        db_manager.write("grp_dates", df, ttl_days=1, initial=True)
        r = db_manager.read("grp_dates")
        orig = set(pd.to_datetime(df["date"]).dt.normalize().unique())
        read = set(pd.to_datetime(r["date"]).dt.normalize().unique())
        assert orig == read

    def test_delta_write_recent_rows_stored(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-05-22", "2026-05-22"]),
            "sector_name": ["電子", "金融"],
            "close": [200.0, 150.0],
        })
        db_manager.write("grp_delta", df, ttl_days=1, initial=False)
        r = db_manager.read("grp_delta")
        assert r is not None and len(r) == 2

    def test_delta_write_skips_old_rows(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2010-01-01", "2010-01-01"]),
            "sector_name": ["電子", "金融"],
            "close": [100.0, 80.0],
        })
        db_manager.write("grp_old", df, ttl_days=1, initial=False)
        r = db_manager.read("grp_old")
        assert r is None or r.empty

    def test_grouped_and_simple_keys_are_independent(self):
        """Writing a grouped key must not corrupt a simple key with the same indicator_id."""
        simple = _simple_df(3)
        grouped = _grouped_df(["電子"], n_days=3)
        db_manager.write("ind_simple", simple,  ttl_days=1, initial=True)
        db_manager.write("ind_grp",    grouped, ttl_days=1, initial=True)
        rs = db_manager.read("ind_simple")
        rg = db_manager.read("ind_grp")
        assert list(rs.columns) == ["date", "value"]
        assert list(rg.columns) == ["date", "series_key", "value"]


# ── Blob cache ────────────────────────────────────────────────────────────────

class TestBlobCache:
    def _complex_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "date":   pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "ticker": ["AAPL", "MSFT"],
            "value":  [100.0, 200.0],
            "extra":  ["a", "b"],
        })

    def test_blob_write_read_roundtrip(self):
        df = self._complex_df()
        db_manager.write("blob_test", df, ttl_days=1)
        r = db_manager.read("blob_test")
        assert r is not None
        assert list(r.columns) == list(df.columns)
        assert len(r) == 2

    def test_blob_full_replace_on_second_write(self):
        df1 = self._complex_df()
        df2 = self._complex_df().head(1)
        db_manager.write("blob_replace", df1, ttl_days=1)
        db_manager.write("blob_replace", df2, ttl_days=1)
        r = db_manager.read("blob_replace")
        assert len(r) == 1

    def test_blob_read_returns_none_when_expired(self):
        df = self._complex_df()
        db_manager.write("blob_exp", df, ttl_days=1)
        future = int(time.time()) + 2 * 86400 + 10
        with patch("time.time", return_value=float(future)):
            r = db_manager.read("blob_exp")
        assert r is None


# ── is_fresh / list_keys ──────────────────────────────────────────────────────

class TestUtilities:
    def test_is_fresh_true_after_write(self):
        df = _simple_df(2)
        db_manager.write("fresh_test", df, ttl_days=1, initial=True)
        assert db_manager.is_fresh("fresh_test") is True

    def test_is_fresh_false_for_unknown_key(self):
        assert db_manager.is_fresh("__nope__") is False

    def test_is_fresh_false_after_expiry(self):
        df = _simple_df(2)
        db_manager.write("fresh_exp", df, ttl_days=1, initial=True)
        future = int(time.time()) + 2 * 86400 + 10
        with patch("time.time", return_value=float(future)):
            assert db_manager.is_fresh("fresh_exp") is False

    def test_list_keys_includes_written_keys(self):
        df = _simple_df(2)
        db_manager.write("lk_a", df, ttl_days=1, initial=True)
        db_manager.write("lk_b", df, ttl_days=1, initial=True)
        keys = {entry["key"] for entry in db_manager.list_keys()}
        assert "lk_a" in keys
        assert "lk_b" in keys

    def test_list_keys_shows_store_type(self):
        simple = _simple_df(2)
        complex_df = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01"]),
            "a": [1], "b": ["x"], "c": [3.0]
        })
        db_manager.write("lk_ts",   simple,     ttl_days=1, initial=True)
        db_manager.write("lk_blob", complex_df, ttl_days=1)
        entries = {e["key"]: e["store"] for e in db_manager.list_keys()}
        assert entries["lk_ts"]   == "ts_rows"
        assert entries["lk_blob"] == "blob"


# ── trim_to_window ────────────────────────────────────────────────────────────

class TestTrimToWindow:
    def test_trim_removes_old_rows(self):
        """Rows older than trim window must be deleted."""
        old_date = pd.Timestamp("2000-01-01")
        recent_date = pd.Timestamp.now() - pd.DateOffset(years=1)
        df = pd.DataFrame({
            "date":  [old_date, recent_date],
            "value": [1.0, 2.0],
        })
        db_manager.write("trim_test", df, ttl_days=1, initial=True)
        removed = db_manager.trim_to_window(years=5)
        assert removed >= 1
        r = db_manager.read("trim_test")
        # Only recent row should remain (or None if TTL also expired — check both)
        if r is not None and not r.empty:
            assert r["date"].min() > pd.Timestamp("2005-01-01")

    def test_trim_noop_when_all_within_window(self):
        df = _simple_df(5, start="2025-01-01")
        db_manager.write("trim_noop", df, ttl_days=1, initial=True)
        removed = db_manager.trim_to_window(years=5)
        assert removed == 0

    def test_trim_returns_count(self):
        assert isinstance(db_manager.trim_to_window(years=15), int)
