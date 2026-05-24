"""
test_scheduler.py — unit tests for scheduler.py

Covers (no live HTTP, no real DB):
  - _run(): success writes to DB, failure logs error without raising
  - _run(): post_sleep is called when > 0
  - _run(): dict-of-DataFrames result writes each sub-key
  - job_taiwan_sector(): splits idx_df into two 3-column writes (close, chg_pct)
"""
from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock, call

import pandas as pd
import pytest

import scheduler
import db_manager


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Redirect DB to a fresh temp file for every test."""
    db_path = tmp_path / "test_scheduler_cache.sqlite3"
    monkeypatch.setattr(db_manager, "_DB_PATH", db_path)
    yield db_path


def _simple_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame({
        "date":  pd.date_range("2025-01-01", periods=n),
        "value": [float(i) for i in range(n)],
    })


# ── _run() helper ─────────────────────────────────────────────────────────────

class TestRun:
    def test_success_writes_to_db(self):
        df = _simple_df(3)
        scheduler._run("sched_key", lambda: df, ttl_days=1, initial=True)
        result = db_manager.read("sched_key")
        assert result is not None
        assert len(result) == 3

    def test_failure_does_not_raise(self):
        def _boom():
            raise RuntimeError("API down")

        # Should not raise; logs an error instead
        scheduler._run("sched_fail", _boom, ttl_days=1)

    def test_failure_logs_error(self, caplog):
        def _boom():
            raise ValueError("bad data")

        with caplog.at_level(logging.ERROR, logger="gai_me.scheduler"):
            scheduler._run("sched_log_err", _boom, ttl_days=1)

        assert any("sched_log_err" in r.message for r in caplog.records)

    def test_none_return_is_skipped(self):
        scheduler._run("sched_none", lambda: None, ttl_days=1)
        assert db_manager.read("sched_none") is None

    def test_post_sleep_called_when_positive(self):
        # _run() does `import time as _time` locally; patch time.sleep at the module level
        df = _simple_df(2)
        import time as _time_mod
        with patch.object(_time_mod, "sleep") as mock_sleep:
            scheduler._run("sched_sleep", lambda: df, ttl_days=1,
                           initial=True, post_sleep=0.5)
            mock_sleep.assert_called_once_with(0.5)

    def test_post_sleep_not_called_when_zero(self):
        df = _simple_df(2)
        import time as _time_mod
        with patch.object(_time_mod, "sleep") as mock_sleep:
            scheduler._run("sched_no_sleep", lambda: df, ttl_days=1,
                           initial=True, post_sleep=0.0)
            mock_sleep.assert_not_called()

    def test_dict_of_dataframes_writes_sub_keys(self):
        result = {
            "close":   _simple_df(3),
            "chg_pct": _simple_df(3),
        }
        scheduler._run("multi", lambda: result, ttl_days=1, initial=True)
        assert db_manager.read("multi.close") is not None
        assert db_manager.read("multi.chg_pct") is not None

    def test_dict_skips_empty_sub_dfs(self):
        result = {
            "good":  _simple_df(2),
            "empty": pd.DataFrame(),
        }
        scheduler._run("multi_skip", lambda: result, ttl_days=1, initial=True)
        assert db_manager.read("multi_skip.good") is not None
        assert db_manager.read("multi_skip.empty") is None


# ── job_taiwan_sector() ───────────────────────────────────────────────────────

class TestJobTaiwanSector:
    """Verify sector job splits idx_df into two 3-column writes."""

    def _sector_idx_df(self, n: int = 65) -> pd.DataFrame:
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        return pd.DataFrame({
            "date":        dates.repeat(2),
            "sector_code": ["14", "18"] * n,
            "sector_name": ["電子", "金融"] * n,
            "close":       [float(i % 100 + 100) for i in range(n * 2)],
            "chg_pct":     [float(i % 5 - 2) for i in range(n * 2)],
        })

    def test_writes_close_and_chg_pct_keys(self):
        idx_df = self._sector_idx_df()
        with patch("scheduler.fetch_tw_sector_indices", return_value=idx_df), \
             patch("scheduler.fetch_tw_sector_turnover", return_value=pd.DataFrame()), \
             patch("scheduler.fetch_tw_sector_institutional", return_value=pd.DataFrame()):
            scheduler.job_taiwan_sector(initial=True)

        close_raw = db_manager.read("tw_sector_close")
        chg_raw   = db_manager.read("tw_sector_chg_pct")
        assert close_raw is not None, "tw_sector_close not written"
        assert chg_raw   is not None, "tw_sector_chg_pct not written"

    def test_close_df_has_three_columns(self):
        idx_df = self._sector_idx_df()
        with patch("scheduler.fetch_tw_sector_indices", return_value=idx_df), \
             patch("scheduler.fetch_tw_sector_turnover", return_value=pd.DataFrame()), \
             patch("scheduler.fetch_tw_sector_institutional", return_value=pd.DataFrame()):
            scheduler.job_taiwan_sector(initial=True)

        # Grouped TS reads back as {date, series_key, value}
        close_raw = db_manager.read("tw_sector_close")
        assert list(close_raw.columns) == ["date", "series_key", "value"]

    def test_both_sectors_written(self):
        idx_df = self._sector_idx_df()
        with patch("scheduler.fetch_tw_sector_indices", return_value=idx_df), \
             patch("scheduler.fetch_tw_sector_turnover", return_value=pd.DataFrame()), \
             patch("scheduler.fetch_tw_sector_institutional", return_value=pd.DataFrame()):
            scheduler.job_taiwan_sector(initial=True)

        close_raw = db_manager.read("tw_sector_close")
        assert set(close_raw["series_key"].unique()) == {"電子", "金融"}

    def test_empty_idx_df_does_not_crash(self):
        with patch("scheduler.fetch_tw_sector_indices", return_value=pd.DataFrame()), \
             patch("scheduler.fetch_tw_sector_turnover", return_value=pd.DataFrame()), \
             patch("scheduler.fetch_tw_sector_institutional", return_value=pd.DataFrame()):
            scheduler.job_taiwan_sector(initial=False)
        # Should complete without exception; nothing written
        assert db_manager.read("tw_sector_close") is None

    def test_fetch_exception_does_not_propagate(self):
        with patch("scheduler.fetch_tw_sector_indices",
                   side_effect=RuntimeError("TWSE down")), \
             patch("scheduler.fetch_tw_sector_turnover", return_value=pd.DataFrame()), \
             patch("scheduler.fetch_tw_sector_institutional", return_value=pd.DataFrame()):
            scheduler.job_taiwan_sector(initial=False)  # must not raise
