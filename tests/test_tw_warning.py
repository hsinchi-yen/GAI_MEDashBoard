"""Tests for the Taiwan early-warning layer: config, parsers, signals, light, back-test."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from analytics import tw_warning as tw
from analytics.tw_warning_backtest import (
    _equity, drawdown_events, forward_drawdown, run_backtest, strategy_table,
)
from analytics.tw_warning_config import CONFIG, TwWarningConfig, describe
from fetchers import taiwan_market as tm

FIX = Path(__file__).parent / "data" / "tw_market"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


# ── config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_every_parameter_has_unit_and_source(self):
        rows = describe()
        assert len(rows) == len(dataclasses.fields(TwWarningConfig))
        assert all(r["來源"] in ("A", "P") and r["單位"] for r in rows)

    def test_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            CONFIG.rsi_overbought = 1

    def test_level_counts_scale_with_signal_count(self):
        assert CONFIG.level_counts(9) == (3, 5)        # the post-mortem's 3 and 5 of 9
        assert CONFIG.level_counts(10) == (4, 6)


# ── parsers (saved official responses) ────────────────────────────────────────

class TestParsers:
    def test_mi_index_counts_are_the_stock_column(self):
        counts, closes = tm.parse_mi_index(load("mi_index_20261005.json"))
        assert counts == {"adv": 364, "dec": 631, "unch": 87}   # post-mortem: 364 漲 631 跌

    def test_mi_index_closes_drop_etfs(self):
        _, closes = tm.parse_mi_index(load("mi_index_20261005.json"))
        assert "0050" not in set(closes["code"]) and "00400A" not in set(closes["code"])
        assert {"1101", "2330"} <= set(closes["code"])
        assert closes["close"].dtype.kind == "f"

    def test_margin_balance_in_yi(self):
        assert tm.parse_margin(load("mi_margn_20261015.json")) == pytest.approx(6464.15, abs=0.01)

    def test_foreign_net_excludes_foreign_dealers(self):
        assert tm.parse_bfi82u(load("bfi82u_20261013.json")) == pytest.approx(-1652.905, abs=0.01)

    def test_fmtqik_dates_and_turnover(self):
        df = tm.parse_fmtqik(load("fmtqik_202610.json"))
        first = df.iloc[0]
        assert first["date"] == pd.Timestamp("2026-10-01")
        assert first["turnover"] == pytest.approx(8740.46, abs=0.01)
        assert first["close"] == pytest.approx(48353.49)

    def test_taifex_net_oi_adds_quarter_of_mini(self):
        date, net = tm.parse_taifex_fini_oi(load("taifex_fut_inst_20261106.json"))
        assert date == pd.Timestamp("2026-11-06")
        assert net == pytest.approx(-99930 + 913 / 4)

    def test_parsers_tolerate_empty_bodies(self):
        counts, closes = tm.parse_mi_index({})
        assert counts == {} and closes.empty
        assert tm.parse_margin({}) is None and tm.parse_bfi82u({}) is None
        assert tm.parse_fmtqik({}).empty and tm.parse_taifex_fini_oi([]) is None

    def test_ma_breadth_needs_a_full_window(self):
        dates = pd.bdate_range("2026-01-01", periods=25)
        rising = pd.DataFrame({"date": dates, "code": "1101", "close": np.arange(25.0)})
        falling = pd.DataFrame({"date": dates, "code": "1102", "close": 100 - np.arange(25.0)})
        late = pd.DataFrame({"date": dates[-3:], "code": "9999", "close": [1.0, 2, 3]})
        out = tm.ma_breadth(pd.concat([rising, falling, late]), windows=(20,)).set_index("date")
        assert np.isnan(out["pct_ma20"].iloc[10])
        assert out["pct_ma20"].iloc[-1] == pytest.approx(50.0)   # the new listing is not counted


# ── signals ───────────────────────────────────────────────────────────────────

def frame(n=300, **cols) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-01", periods=n)
    base = {c: np.nan for c in (*tw.TW_KEYS, *tw.US_KEYS)}
    base["close"] = np.linspace(100, 120, n)
    base.update(cols)
    return pd.DataFrame(base, index=idx)


class TestSignals:
    def test_w1_rate_jump(self):
        dgs = np.r_[np.full(250, 4.0), np.linspace(4.0, 4.6, 50)]
        h = tw.signal_history(frame(dgs10=dgs))
        assert h["W1"].iloc[-1] == 1 and h["W1"].iloc[200] == 0

    def test_w3_counts_up_days_with_more_decliners(self):
        n = 300
        close = 100 * np.cumprod(np.r_[1, np.where(np.arange(1, n) % 4 == 0, 1.02, 0.999)])
        adv = np.full(n, 600.0)
        dec = np.full(n, 400.0)
        dec[-8:] = 700.0                                   # breadth collapses at the end
        h = tw.signal_history(frame(close=close, adv=adv, dec=dec))
        assert h["W3"].iloc[-1] == 1 and h["W3"].iloc[-20] == 0

    def test_w6_short_build(self):
        oi = np.r_[np.full(290, -50_000.0), np.linspace(-50_000, -65_000, 10)]
        h = tw.signal_history(frame(fut_oi=oi))
        assert h["W6"].iloc[-1] == 1

    def test_w7_margin_outpaces_index(self):
        margin = np.r_[np.full(240, 4000.0), np.linspace(4000, 5200, 60)]   # +30% vs index ~+3%
        h = tw.signal_history(frame(margin=margin))
        assert h["W7"].iloc[-1] == 1

    def test_missing_input_is_unknown_not_false(self):
        h = tw.signal_history(frame())
        assert h["W6"].isna().all() and h["W7"].isna().all()

    def test_sma_rsi_matches_the_post_mortem_method(self):
        up = pd.Series(np.arange(30.0))
        assert tw.rsi(up, 14, "sma").iloc[-1] == 100
        zigzag = pd.Series(np.tile([1.0, 2.0], 20))
        assert tw.rsi(zigzag, 14, "sma").iloc[-1] == pytest.approx(50, abs=5)

    def test_us_series_use_the_previous_session(self):
        tw_days = pd.bdate_range("2026-10-01", periods=5)
        data = {"TAIEX_DAILY": pd.DataFrame({"date": tw_days, "value": 100.0}),
                "US_10Y_NOMINAL": pd.DataFrame({"date": tw_days, "value": [1.0, 2, 3, 4, 5]})}
        f, _ = tw.build_frame(data)
        # On a Taipei date the same-date New York print does not exist yet.
        assert list(f["dgs10"]) [1:] == [1.0, 2, 3, 4] and np.isnan(f["dgs10"].iloc[0])


class TestLight:
    def test_hysteresis(self):
        raw = pd.Series([0, 2, 0, 2, 2, 2, 1, 1, 1, 1, 1, 0])
        out = tw.apply_hysteresis(raw, confirm=2, release=5)
        assert list(out) == [0, 0, 0, 0, 2, 2, 2, 2, 2, 2, 1, 1]

    def test_red_needs_only_the_trend(self):
        idx = pd.bdate_range("2026-01-01", periods=100)
        close = pd.Series(np.r_[np.linspace(100, 120, 60), np.linspace(120, 90, 40)], index=idx)
        hist = pd.DataFrame({s.id: 0.0 for s in tw.SIGNALS}, index=idx)
        hist["ma_fast"] = close.rolling(20).mean()
        hist["ma_slow"] = close.rolling(60).mean()
        lv = tw.raw_levels(hist, close, 9, CONFIG, [s.id for s in tw.SIGNALS[:9]])
        assert lv["count"].iloc[-1] == 0 and lv["raw"].iloc[-1] == 3

    def test_signal_memory_keeps_precursors(self):
        idx = pd.bdate_range("2026-01-01", periods=30)
        hist = pd.DataFrame({s.id: 0.0 for s in tw.SIGNALS}, index=idx)
        hist.loc[idx[15], ["W1", "W2", "W5"]] = 1
        hist["ma_fast"] = hist["ma_slow"] = 0.0
        close = pd.Series(1.0, index=idx)
        lv = tw.raw_levels(hist, close, 9, CONFIG, [s.id for s in tw.SIGNALS[:9]])
        assert lv["count"].iloc[15 + CONFIG.signal_memory - 1] == 3
        assert lv["count"].iloc[15 + CONFIG.signal_memory] == 0

    def test_evaluate_without_index_is_unavailable(self):
        assert tw.evaluate({})["available"] is False

    def test_stale_input_does_not_count(self):
        days = pd.bdate_range(end="2026-11-06", periods=300)
        close = pd.DataFrame({"date": days, "value": np.linspace(100, 130, 300)})
        margin = pd.DataFrame({"date": days[:-40], "value": np.r_[np.full(200, 4000.0),
                                                                   np.linspace(4000, 6000, 60)]})
        data = {"TAIEX_DAILY": close, "TW_MARGIN": margin}
        w = tw.evaluate(data, now=pd.Timestamp("2026-11-07"))
        w7 = next(s for s in w["signals"] if s["id"] == "W7")
        assert w7["stale"] and not w7["recent"] and w7["on"] is None

    def test_w10_counts_only_when_its_feed_exists(self):
        days = pd.bdate_range(end="2026-11-06", periods=200)
        data = {"TAIEX_DAILY": pd.DataFrame({"date": days, "value": np.linspace(100, 130, 200)})}
        assert tw.evaluate(data, now=pd.Timestamp("2026-11-07"))["n_signals"] == 9
        data["TW_WHALE_EXIT"] = pd.DataFrame({"date": days, "value": 10.0})
        w = tw.evaluate(data, now=pd.Timestamp("2026-11-07"))
        assert w["n_signals"] == 10 and w["thresholds"] == {"watch": 4, "reduce": 6}

    def test_short_w10_history_does_not_raise_the_bar(self):
        # Production 2026-11-08: 7 days of 8504 history, too short for a 20-day change.
        days = pd.bdate_range(end="2026-11-06", periods=200)
        data = {"TAIEX_DAILY": pd.DataFrame({"date": days, "value": np.linspace(100, 130, 200)}),
                "TW_WHALE_EXIT": pd.DataFrame({"date": days[-7:], "value": 6.0})}
        w = tw.evaluate(data, now=pd.Timestamp("2026-11-07"))
        assert w["n_signals"] == 9 and w["thresholds"] == {"watch": 3, "reduce": 5}
        hist = tw.level_history(data)
        assert (hist["n"] == 9).all()


# ── back-test ─────────────────────────────────────────────────────────────────

class TestBacktest:
    def test_forward_drawdown(self):
        close = pd.Series([100.0, 95, 90, 99, 100, 101])
        dd = forward_drawdown(close, 2)
        assert dd.iloc[0] == pytest.approx(-10.0)
        assert dd.iloc[-2:].isna().all()

    def test_drawdown_events(self):
        idx = pd.bdate_range("2026-01-01", periods=7)
        close = pd.Series([100.0, 110, 95, 90, 120, 100, 125], index=idx)
        ev = drawdown_events(close, 12)
        assert len(ev) == 2
        assert ev[0]["peak"] == idx[1] and ev[0]["trough"] == idx[3]
        assert ev[0]["fall"] == pytest.approx(-18.18, abs=0.01)

    def test_hold_equity_tracks_the_index(self):
        close = pd.Series([100.0, 110, 99, 120], index=pd.bdate_range("2026-01-01", periods=4))
        eq = _equity(close, pd.Series(1.0, index=close.index), cost=0.0059)
        assert eq.iloc[-1] == pytest.approx(1.2)

    def test_costs_are_charged_on_changes(self):
        close = pd.Series(100.0, index=pd.bdate_range("2026-01-01", periods=4))
        exp = pd.Series([1.0, 0.5, 0.5, 1.0], index=close.index)
        eq = _equity(close, exp, cost=0.01)
        assert eq.iloc[-1] == pytest.approx((1 - 0.0025) ** 2)


# ── shipped history (real data) ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def seed():
    if not tm.SEED_CSV.exists():
        pytest.skip("tw_flows_seed.csv not built")
    return tm.load_tw_flows_seed()


def at(series: pd.DataFrame, day: str) -> float:
    return float(series.set_index("date")["value"].loc[day])


class TestSeedMatchesPostMortem:
    def test_margin(self, seed):
        assert at(seed["tw_margin"], "2026-07-30") == pytest.approx(4939, abs=1)
        assert at(seed["tw_margin"], "2026-10-15") == pytest.approx(6464, abs=1)

    def test_foreign_september(self, seed):
        s = seed["tw_fini_net"].set_index("date")["value"]
        assert s.loc["2026-09"].sum() == pytest.approx(-417, abs=1)

    def test_futures_short_build_before_peak(self, seed):
        oi = seed["tw_fini_fut_oi"].set_index("date")["value"]
        assert oi.diff(10).loc["2026-10-13"] <= -10_000

    def test_breadth(self, seed):
        assert at(seed["tw_adv"], "2026-10-05") == 364
        assert at(seed["tw_dec"], "2026-10-05") == 631

    def test_ten_years_of_history(self, seed):
        for key in ("taiex_daily", "tw_margin", "tw_fini_net", "tw_turnover"):
            assert seed[key]["date"].min() <= pd.Timestamp("2015-01-31"), key


class TestBacktestReplicatesPostMortem:
    """Numbers the post-mortem reported, recomputed from the shipped closes."""

    @pytest.fixture(scope="class")
    def result(self, seed):
        data = {"TAIEX_DAILY": seed["taiex_daily"]}
        return run_backtest(data, now=pd.Timestamp("2026-11-06"))

    def test_base_rate(self, result):
        base = result["hit_rates"].iloc[0]["命中率"]
        assert base == pytest.approx(16, abs=1.5)

    def test_buy_and_hold_and_ma60(self, result):
        s = result["strategies"].set_index("策略")
        assert s.loc["一直持有", "年化報酬"] == pytest.approx(15.6, abs=0.5)
        assert s.loc["一直持有", "最大跌幅"] == pytest.approx(-31.6, abs=0.5)
        ma = s.loc[[i for i in s.index if "MA60" in i][0]]
        assert ma["年化報酬"] == pytest.approx(8.2, abs=0.5)
        assert ma["最大跌幅"] == pytest.approx(-26.5, abs=0.5)

    def test_six_post_mortem_events_are_found(self, result):
        peaks = {str(d)[:7] for d in result["events"]["高點"]}
        assert {"2020-01", "2021-04", "2022-01", "2024-07", "2026-06", "2026-10"} <= peaks


# ── scheduler job ─────────────────────────────────────────────────────────────

class TestSchedulerJob:
    def test_empty_db_loads_seed_then_daily(self, tmp_path, monkeypatch):
        import db_manager
        import scheduler
        monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "t.sqlite3")
        day = pd.Timestamp("2026-11-06")
        seed = {k: pd.DataFrame({"date": pd.bdate_range(end="2026-11-04", periods=300), "value": 1.0})
                for k in (*tm.SERIES, "taiex_daily")}
        closes = pd.DataFrame({"date": [day] * 2, "code": ["1101", "2330"], "close": [25.0, 1000.0]})
        parts = {"tw_adv": pd.DataFrame({"date": [day], "value": [500.0]}), "closes": closes}
        with patch.object(scheduler, "load_tw_flows_seed", return_value=seed), \
             patch.object(scheduler, "load_tw_closes_seed", return_value=pd.DataFrame()), \
             patch.object(scheduler, "fetch_index_daily_close", return_value=pd.DataFrame()), \
             patch.object(scheduler, "fetch_tw_market_day", side_effect=lambda d: {
                 k: v.copy() for k, v in parts.items()}), \
             patch.object(scheduler, "fetch_tw_turnover", return_value=pd.DataFrame()), \
             patch.object(scheduler, "fetch_taifex_fini_oi", return_value=pd.DataFrame()),              patch.object(scheduler, "fetch_whale_exit_share", return_value=pd.DataFrame()):
            scheduler.job_tw_flows(now=day)
        assert len(db_manager.read("tw_margin")) == 300
        adv = db_manager.read("tw_adv")
        assert adv["date"].max() == day and adv["value"].iloc[-1] == 500
        stored = db_manager.read(tm.CLOSES_KEY)
        assert set(stored["series_key"]) == {"1101", "2330"}

    def test_close_table_is_trimmed(self, tmp_path, monkeypatch):
        import db_manager
        monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "t.sqlite3")
        days = pd.bdate_range(end="2026-11-06", periods=200)
        df = pd.DataFrame({"date": days, "code": "1101", "close": 1.0})
        db_manager.write(tm.CLOSES_KEY, df, ttl_days=7, initial=True)
        db_manager.trim_series(tm.CLOSES_KEY, tm.CLOSE_KEEP_DAYS)
        kept = db_manager.read(tm.CLOSES_KEY)
        assert (kept["date"].max() - kept["date"].min()).days <= tm.CLOSE_KEEP_DAYS


class TestWhaleExitFeed:
    BODY = {"date": "2026-11-06",
            "summary": [{"date": "2026-11-04", "scored": 600, "partial": False},
                        {"date": "2026-11-05", "scored": 590, "partial": True},
                        {"date": "2026-11-06", "scored": 598, "partial": False}],
            "alerts": [{"name": "千張大戶退場", "counts": [12, 20, 30], "shares": [2.0, 3.4, 5.0]}]}

    def test_shares_without_partial_runs(self):
        from fetchers.twse_heat import parse_whale_exit
        df = parse_whale_exit(self.BODY)
        assert list(df["value"]) == [2.0, 5.0]
        assert df["date"].iloc[-1] == pd.Timestamp("2026-11-06")

    def test_no_hits_is_zero_and_service_down_is_empty(self):
        from fetchers import twse_heat
        body = {**self.BODY, "alerts": []}
        assert list(twse_heat.parse_whale_exit(body)["value"]) == [0.0, 0.0]
        with patch.object(twse_heat.requests, "get", side_effect=ConnectionError("down")):
            assert twse_heat.fetch_whale_exit_share().empty

    def test_zero_base_does_not_fire(self):
        n = 300
        whale = np.r_[np.zeros(n - 5), np.full(5, 3.0)]
        h = tw.signal_history(frame(whale=whale))
        assert np.isnan(h["W10_v"].iloc[-1])
