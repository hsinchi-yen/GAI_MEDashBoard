"""VIXTWN (TAIFEX TAIWAN VIX): fetcher, history seed, risk alerts and GMI #21.

No live HTTP: TAIFEX responses are mocked from the real file layout.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from analytics import market_view as mv
from fetchers.taiwan import (
    _parse_vixtwn_text, _vixtwn_seed, fetch_vixtwn, load_vixtwn_history,
)
from fetchers.yahoo_finance import fetch_index_daily_close
from macro_index import GROUP_CAPS, TOTAL_INDICATORS, compute_macro_index

# Verbatim layout of log2data_eng/202611new.txt: tab runs, CRLF, two header lines.
OFFICIAL_TXT = (
    "Date\t\tClosing Time\t\tDaily Index\t\tLast 1 min AVG\r\n"
    "--------\t-------------------\t--------------------\t--------------\r\n"
    "20261102\t13450000\t\t\t31.30\t\t31.28\r\n"
    "20261103\t13450000\t\t\t36.83\t\t36.83\r\n"
    "20261106\t13450000\t\t\t46.52\t\t46.52\r\n"
)


def _resp(status=200, text=""):
    m = MagicMock()
    m.status_code = status
    m.text = text
    return m


# ── Fetcher ───────────────────────────────────────────────────────────────────

class TestParse:
    def test_parses_daily_index_column(self):
        df = _parse_vixtwn_text(OFFICIAL_TXT)
        assert list(df.columns) == ["date", "value"]
        assert len(df) == 3
        assert df.iloc[0]["date"] == pd.Timestamp("2026-11-02")
        assert df.iloc[-1]["value"] == pytest.approx(46.52)

    def test_skips_headers_and_garbage(self):
        assert _parse_vixtwn_text("<html>404</html>\r\n").empty
        assert _parse_vixtwn_text("").empty


class TestFetchVixtwn:
    NOW = pd.Timestamp("2026-11-07")

    def test_requests_current_and_previous_month(self):
        with patch("fetchers.taiwan.requests.get", return_value=_resp(200, OFFICIAL_TXT)) as get:
            fetch_vixtwn(months=2, now=self.NOW)
        urls = [c.args[0] for c in get.call_args_list]
        assert urls[0].endswith("/log2data_eng/202611new.txt")
        assert urls[1].endswith("/log2data_eng/202610new.txt")
        assert all(c.kwargs.get("allow_redirects") is False for c in get.call_args_list)

    def test_expired_month_redirect_is_skipped(self):
        """TAIFEX answers months it no longer keeps with a 302 to 404.htm."""
        def fake(url, **_):
            return _resp(302) if "202610" in url else _resp(200, OFFICIAL_TXT)
        with patch("fetchers.taiwan.requests.get", side_effect=fake):
            df = fetch_vixtwn(months=2, now=self.NOW)
        assert len(df) == 3

    def test_network_error_returns_empty(self):
        with patch("fetchers.taiwan.requests.get", side_effect=OSError("down")):
            assert fetch_vixtwn(months=2, now=self.NOW).empty


class TestHistory:
    def test_seed_is_long_and_clean(self):
        seed = _vixtwn_seed()
        assert seed["date"].min() <= pd.Timestamp("2018-01-31")
        assert seed["date"].is_monotonic_increasing
        assert not seed["date"].duplicated().any()
        assert seed["value"].between(5, 100).all()

    def test_official_values_override_seed(self):
        official = pd.DataFrame({"date": pd.to_datetime(["2020-06-03"]), "value": [22.40]})
        with patch("fetchers.taiwan.fetch_vixtwn", return_value=official):
            df = load_vixtwn_history()
        row = df[df["date"] == pd.Timestamp("2020-06-03")]
        assert len(row) == 1
        assert row.iloc[0]["value"] == pytest.approx(22.40)   # seed has 21.99
        assert df["date"].is_monotonic_increasing

    def test_history_survives_taifex_outage(self):
        with patch("fetchers.taiwan.fetch_vixtwn", return_value=pd.DataFrame()):
            assert len(load_vixtwn_history()) > 1000


class TestTaiexDaily:
    def test_daily_closes_dated_by_local_session(self):
        # 2026-11-05 and -06 local midnight in Taipei (UTC+8), as Yahoo stamps them.
        ts = [int(pd.Timestamp("2026-11-04 16:00").timestamp()),
              int(pd.Timestamp("2026-11-05 16:00").timestamp())]
        raw = {"meta": {"gmtoffset": 28800}, "timestamp": ts,
               "indicators": {"quote": [{"close": [27000.0, None]}],
                              "adjclose": [{"adjclose": [27000.0, 26500.0]}]}}
        with patch("fetchers.yahoo_finance._yf_chart", return_value=raw):
            df = fetch_index_daily_close("^TWII", years_back=6)
        assert list(df["date"]) == [pd.Timestamp("2026-11-05"), pd.Timestamp("2026-11-06")]
        assert list(df["value"]) == [27000.0, 26500.0]

    def test_empty_newest_close_falls_back_to_meta_quote(self):
        """Production shape: Friday's bar had close=None while meta held the close."""
        ts = [int(pd.Timestamp("2026-11-05 01:00").timestamp()),
              int(pd.Timestamp("2026-11-06 01:00").timestamp())]
        raw = {"meta": {"gmtoffset": 28800, "regularMarketPrice": 39701.64,
                        "regularMarketTime": int(pd.Timestamp("2026-11-06 05:33").timestamp())},
               "timestamp": ts,
               "indicators": {"quote": [{"close": [41574.72, None]}],
                              "adjclose": [{"adjclose": [41574.72, None]}]}}
        with patch("fetchers.yahoo_finance._yf_chart", return_value=raw):
            df = fetch_index_daily_close("^TWII")
        assert df.iloc[-1]["date"] == pd.Timestamp("2026-11-06")
        assert df.iloc[-1]["value"] == pytest.approx(39701.64)


# ── Risk alerts ───────────────────────────────────────────────────────────────

NOW = pd.Timestamp("2026-11-07")


def daily(values, end="2026-11-06") -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=len(values))
    return pd.DataFrame({"date": dates, "value": [float(v) for v in values]})


def _keys(alerts, key="VIXTWN"):
    return [(a["key"], a["level"]) for a in alerts if a["key"].startswith(key)]


class TestVixtwnAlerts:
    def test_calm(self):
        assert _keys(mv.risk_alerts({"VIXTWN": daily([16, 16.5])}, NOW)) == []

    def test_level_tiers(self):
        assert ("VIXTWN", "watch") in _keys(mv.risk_alerts({"VIXTWN": daily([26, 26])}, NOW))
        assert ("VIXTWN", "alert") in _keys(mv.risk_alerts({"VIXTWN": daily([36, 36])}, NOW))

    def test_one_day_jump(self):
        out = _keys(mv.risk_alerts({"VIXTWN": daily([18, 21])}, NOW))   # +16.7 %
        assert ("VIXTWN_JUMP", "watch") in out
        assert ("VIXTWN_JUMP", "watch") not in _keys(
            mv.risk_alerts({"VIXTWN": daily([18, 20])}, NOW))            # +11 %

    def test_spread_over_us_vix_on_common_day(self):
        # VIX has no row for the last Taiwan day; the gap uses the last shared date.
        tw = daily([24, 24, 30])
        us = daily([15, 15], end="2026-11-05")
        out = _keys(mv.risk_alerts({"VIXTWN": tw, "VIX": us}, NOW))
        assert ("VIXTWN_GAP", "watch") in out                            # 24 - 15 = 9
        assert ("VIXTWN_GAP", "watch") not in _keys(
            mv.risk_alerts({"VIXTWN": tw, "VIX": daily([18, 18], end="2026-11-05")}, NOW))

    def test_dead_feed_is_silent(self):
        assert _keys(mv.risk_alerts({"VIXTWN": daily([40, 50], end="2026-09-01")}, NOW)) == []


# ── GMI #21 ───────────────────────────────────────────────────────────────────

def _monthly(values, end="2026-10-01"):
    return pd.DataFrame({"date": pd.date_range(end=end, periods=len(values), freq="MS"),
                         "value": [float(v) for v in values]})


class TestGmiSignal:
    def test_twenty_indicators(self):
        assert TOTAL_INDICATORS == 20
        assert GROUP_CAPS == {"A": 5, "B": 5, "C": 5, "D": 6}

    def test_falling_vixtwn_scores_one(self):
        sig = next(s for s in compute_macro_index({"VIXTWN": _monthly([30, 26, 22, 18])})["signals"]
                   if s["id"] == 21)
        assert sig["group"] == "D" and sig["score"] == 1 and sig["has_data"]

    def test_rising_vixtwn_scores_zero(self):
        sig = next(s for s in compute_macro_index({"VIXTWN": _monthly([18, 22, 26, 30])})["signals"]
                   if s["id"] == 21)
        assert sig["score"] == 0 and sig["has_data"]

    def test_group_d_can_reach_six(self):
        fall = _monthly([32.0, 28.0, 24.0, 20.0])
        data = {"VIX": fall, "VIXTWN": fall, "TWD_USD": fall,
                "COPPER_YOY": _monthly([2.0, 3.0, 4.0]),
                "SECTOR_ROTATION": _monthly([0.01, 0.02, 0.03]),
                "THIRTEENF_NET_ADD": _monthly([0.5])}
        assert compute_macro_index(data)["group_scores"]["D"] == {"raw": 6, "capped": 6}


# ── Scheduler ─────────────────────────────────────────────────────────────────

class TestSchedulerJob:
    def _run_job(self, has_history: bool):
        import scheduler
        calls = []
        with patch.object(scheduler.db_manager, "max_date",
                          return_value=pd.Timestamp("2026-11-05") if has_history else None), \
             patch.object(scheduler, "_run", side_effect=lambda key, fn, **kw: calls.append((key, fn, kw))):
            scheduler.job_tw_volatility()
        return {key: (fn, kw) for key, fn, kw in calls}

    def test_empty_db_bulk_loads_seeded_history(self):
        import scheduler
        calls = self._run_job(has_history=False)
        assert calls["vixtwn"][0] is scheduler.load_vixtwn_history
        assert calls["vixtwn"][1]["initial"] is True
        assert calls["taiex_daily"][1]["initial"] is True

    def test_existing_history_uses_delta(self):
        import scheduler
        calls = self._run_job(has_history=True)
        assert calls["vixtwn"][0] is scheduler.fetch_vixtwn
        assert calls["vixtwn"][1].get("initial", False) is False
        assert calls["taiex_daily"][1]["initial"] is False
