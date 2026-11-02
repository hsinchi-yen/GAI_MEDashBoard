"""Tests for db_manager snapshot storage, data versioning and connection reuse."""
from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

import db_manager


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "t.sqlite3")
    yield


class TestSnapshots:
    def test_round_trips_plain_values(self):
        db_manager.write_snapshot("s", {"quarter": "2026Q2", "fund_count": 18})
        assert db_manager.read_snapshot("s") == {"quarter": "2026Q2", "fund_count": 18}

    def test_tuples_come_back_iterable(self):
        db_manager.write_snapshot("s", {"top": [("NVIDIA", 100, 5)]})
        name, delta, funds = db_manager.read_snapshot("s")["top"][0]
        assert (name, delta, funds) == ("NVIDIA", 100, 5)

    def test_round_trips_dataframes(self):
        frame = pd.DataFrame({"stock": ["2330", "2317"], "net": [1000, -500]})
        db_manager.write_snapshot("s", {"top30_buy": frame, "period_label": "近 5 日"})
        out = db_manager.read_snapshot("s")
        pd.testing.assert_frame_equal(out["top30_buy"], frame)
        assert out["period_label"] == "近 5 日"

    def test_preserves_string_codes_that_look_numeric(self):
        frame = pd.DataFrame({"code": ["0050", "2330"]})
        db_manager.write_snapshot("s", {"f": frame})
        assert db_manager.read_snapshot("s")["f"]["code"].tolist() == ["0050", "2330"]

    def test_round_trips_empty_dataframe(self):
        db_manager.write_snapshot("s", {"f": pd.DataFrame(), "label": "x"})
        out = db_manager.read_snapshot("s")
        assert out["f"].empty and out["label"] == "x"

    def test_missing_key_returns_none(self):
        assert db_manager.read_snapshot("nope") is None

    def test_overwrites_previous_snapshot(self):
        db_manager.write_snapshot("s", {"v": 1})
        db_manager.write_snapshot("s", {"v": 2})
        assert db_manager.read_snapshot("s") == {"v": 2}

    def test_empty_snapshot_is_not_stored(self):
        """A failed fetch must never overwrite a good snapshot with nothing."""
        db_manager.write_snapshot("s", {"v": 1})
        db_manager.write_snapshot("s", {})
        assert db_manager.read_snapshot("s") == {"v": 1}

    def test_corrupt_payload_reads_as_missing(self):
        db_manager.write_snapshot("s", {"v": 1})
        with sqlite3.connect(str(db_manager._DB_PATH)) as con:
            con.execute("UPDATE blob_cache SET payload_json='{not json' WHERE cache_key=?",
                        (db_manager._SNAPSHOT_PREFIX + "s",))
        assert db_manager.read_snapshot("s") is None

    def test_snapshot_age_reported(self):
        assert db_manager.snapshot_age_hours("s") is None
        db_manager.write_snapshot("s", {"v": 1})
        assert db_manager.snapshot_age_hours("s") < 0.01


class TestDataVersion:
    def _series(self):
        return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "value": [1.0, 2.0, 3.0]})

    def test_stable_when_nothing_changes(self):
        db_manager.write("a", self._series(), ttl_days=1, initial=True)
        assert db_manager.data_version() == db_manager.data_version()

    def test_changes_after_a_new_indicator_is_written(self):
        db_manager.write("a", self._series(), ttl_days=1, initial=True)
        before = db_manager.data_version()
        db_manager.write("b", self._series(), ttl_days=1, initial=True)
        assert db_manager.data_version() != before

    def test_changes_when_a_snapshot_is_written(self):
        before = db_manager.data_version()
        db_manager.write_snapshot("s", {"v": 1})
        assert db_manager.data_version() != before


class TestConnectionSetup:
    def test_schema_runs_once_per_database(self, monkeypatch):
        calls = []
        real = db_manager._init_schema
        monkeypatch.setattr(db_manager, "_init_schema", lambda con: (calls.append(1), real(con)))
        monkeypatch.setattr(db_manager, "_schema_ready", set())
        for _ in range(5):
            db_manager.list_keys()
        assert len(calls) == 1

    def test_new_database_path_gets_its_own_schema(self, tmp_path, monkeypatch):
        db_manager.list_keys()
        monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "other.sqlite3")
        assert db_manager.list_keys() == []

    def test_deleted_database_is_recreated(self):
        db_manager.list_keys()
        db_manager._DB_PATH.unlink()
        assert db_manager.list_keys() == []


def test_read_returns_real_dates_for_time_series():
    df = pd.DataFrame({"date": pd.to_datetime(["2024-02-29", "2024-03-01"]), "value": [1.0, 2.0]})
    db_manager.write("dated", df, ttl_days=1, initial=True)
    out = db_manager.read("dated")
    assert out["date"].tolist() == df["date"].tolist()
    assert pd.api.types.is_datetime64_any_dtype(out["date"])


def test_grouped_read_returns_real_dates():
    df = pd.DataFrame({"date": pd.to_datetime(["2024-02-29", "2024-02-29"]),
                       "sector_name": ["A", "B"], "close": [1.0, 2.0]})
    db_manager.write("grouped", df, ttl_days=1, initial=True)
    assert db_manager.read("grouped")["date"].unique().tolist() == [pd.Timestamp("2024-02-29")]
