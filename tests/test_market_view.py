"""Unit tests for analytics.market_view — the bull/bear verdict engine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics import market_view as mv
from analytics.gmi_backtest import compute_forward_returns, summarize_by_regime
from macro_index import build_macro_index_history, compute_macro_index
from tests.synthetic_data import NOW, index_levels, macro_dataset


def monthly(values, end="2026-09-01") -> pd.DataFrame:
    dates = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": [float(v) for v in values]})


FRESH = pd.Timestamp("2026-09-05")


def gmi_stub(score: int, valid: int = 19) -> dict:
    return {"score": score, "valid_count": valid,
            "diffusion": round(score / valid * 100, 1) if valid else 0.0}


# ── Stance: level + direction ─────────────────────────────────────────────────

class TestStanceMatrix:
    @pytest.mark.parametrize("regime,direction,score,key,phase", [
        ("green",  "improving",     2, "strong_bull", "expansion"),
        ("green",  "flat",          1, "bull",        "expansion"),
        ("green",  "deteriorating", 0, "neutral",     "slowdown"),
        ("yellow", "improving",     1, "bull",        "recovery"),
        ("yellow", "flat",          0, "neutral",     "transition"),
        ("yellow", "deteriorating", -1, "bear",       "slowdown"),
        ("red",    "improving",     0, "neutral",     "recovery"),
        ("red",    "flat",         -1, "bear",        "contraction"),
        ("red",    "deteriorating", -2, "strong_bear", "contraction"),
    ])
    def test_all_nine_cells(self, regime, direction, score, key, phase):
        s = mv.classify_stance(regime, direction)
        assert (s["score"], s["key"], s["phase"]) == (score, key, phase)

    def test_unknown_regime_never_claims_a_view(self):
        s = mv.classify_stance("unknown", "improving")
        assert s["key"] == "unknown"
        assert s["score"] is None
        assert s["phase"] == "unknown"

    def test_every_stance_has_a_label_and_playbook(self):
        for key, meta in mv.STANCES.items():
            assert meta["label"], key
            assert mv.PLAYBOOK[key]["posture"], key
            assert mv.PLAYBOOK[key]["actions"], key

    def test_every_phase_has_a_label(self):
        for regime in ("green", "yellow", "red", "unknown"):
            for direction in ("improving", "flat", "deteriorating"):
                assert mv.PHASES[mv.classify_stance(regime, direction)["phase"]]


class TestMomentumDirection:
    def test_improving_above_threshold(self):
        assert mv.classify_momentum(mv.MOMENTUM_PP + 1) == "improving"

    def test_deteriorating_below_threshold(self):
        assert mv.classify_momentum(-mv.MOMENTUM_PP - 1) == "deteriorating"

    def test_small_moves_are_flat(self):
        assert mv.classify_momentum(mv.MOMENTUM_PP - 1) == "flat"

    def test_boundary_counts_as_a_move(self):
        assert mv.classify_momentum(mv.MOMENTUM_PP) == "improving"

    def test_none_is_flat(self):
        assert mv.classify_momentum(None) == "flat"


# ── Flip distance ─────────────────────────────────────────────────────────────

class TestFlipDistance:
    def test_yellow_needs_counts_both_ways(self):
        f = mv.flip_distance(gmi_stub(12))
        assert f["to_green"] == 3   # 15/19 = 78.9 %
        assert f["to_red"] == 4     # 8/19 = 42.1 %

    def test_already_green(self):
        f = mv.flip_distance(gmi_stub(16))
        assert f["to_green"] == 0
        assert f["to_red"] == 8

    def test_already_red(self):
        f = mv.flip_distance(gmi_stub(5))
        assert f["to_red"] == 0
        assert f["to_green"] == 10

    def test_scales_with_valid_count(self):
        f = mv.flip_distance(gmi_stub(8, valid=12))
        assert f["to_green"] == 1   # 9/12 = 75 %

    def test_no_valid_indicators(self):
        assert mv.flip_distance(gmi_stub(0, valid=0)) == {"to_green": None, "to_red": None}


# ── Risk alerts ───────────────────────────────────────────────────────────────

class TestRiskAlerts:
    # Fixture series end 2026-09-01; daily gauges only count within ten days of that.
    def _levels(self, **kw):
        return {k: monthly([v] * 8) for k, v in kw.items()}

    def test_calm_market_has_no_alerts(self):
        data = self._levels(VIX=14, HY_SPREAD=300, T10Y3M=0.8, US_PMI=52)
        assert mv.risk_alerts(data, FRESH) == []

    def test_vix_tiers(self):
        assert mv.risk_alerts(self._levels(VIX=24), FRESH)[0]["level"] == "watch"
        assert mv.risk_alerts(self._levels(VIX=35), FRESH)[0]["level"] == "alert"

    def test_hy_spread_tiers_in_bps(self):
        assert mv.risk_alerts(self._levels(HY_SPREAD=450), FRESH)[0]["level"] == "watch"
        assert mv.risk_alerts(self._levels(HY_SPREAD=620), FRESH)[0]["level"] == "alert"

    def test_inverted_curve_alerts(self):
        out = mv.risk_alerts(self._levels(T10Y3M=-0.4), FRESH)
        assert out[0]["level"] == "alert"
        assert "倒掛" in out[0]["message"]

    def test_pmi_contraction_watch(self):
        out = mv.risk_alerts(self._levels(US_PMI=47), FRESH)
        assert out[0]["level"] == "watch"

    def test_dollar_surge_uses_three_month_change(self):
        data = {"DXY": monthly([100, 100, 100, 100, 100, 101, 103, 106])}
        out = mv.risk_alerts(data, FRESH)
        assert out and out[0]["key"] == "DXY"

    def test_alerts_sort_most_severe_first(self):
        out = mv.risk_alerts(self._levels(VIX=24, HY_SPREAD=620), FRESH)
        assert [a["level"] for a in out] == ["alert", "watch"]

    def test_dead_feed_raises_no_alert(self):
        """Production showed "US PMI 47.9" from a feed that stopped ten months earlier."""
        data = {"US_PMI": monthly([47.9] * 8, end="2025-12-01")}
        assert mv.risk_alerts(data, pd.Timestamp("2026-11-02")) == []

    def test_normal_publication_lag_still_alerts(self):
        data = {"US_PMI": monthly([47.9] * 8, end="2026-09-01")}
        assert mv.risk_alerts(data, pd.Timestamp("2026-11-02"))

    def test_missing_series_are_skipped(self):
        assert mv.risk_alerts({}, FRESH) == []


# ── Investment clock ──────────────────────────────────────────────────────────

class TestInvestmentClock:
    def _data(self, growth_up: bool, inflation_up: bool) -> dict:
        def s(up):
            base = list(range(0, 40)) + list(range(40, 0, -1)) + [0] * 10
            tail = [1, 3, 5, 7, 9, 11] if up else [-1, -3, -5, -7, -9, -11]
            return monthly([50 + v / 4 for v in base + tail])
        return {
            "US_PMI": s(growth_up), "TW_PMI": s(growth_up), "CN_PMI": s(growth_up),
            "US_CORE_CPI_YOY": s(inflation_up), "US_CORE_PPI_YOY": s(inflation_up),
        }

    @pytest.mark.parametrize("g,i,key", [
        (True, False, "recovery"), (True, True, "overheat"),
        (False, True, "stagflation"), (False, False, "reflation"),
    ])
    def test_four_quadrants(self, g, i, key):
        clock = mv.investment_clock(self._data(g, i))
        assert clock["key"] == key
        assert clock["label"] and clock["favoured"] and clock["avoid"]

    def test_sustained_uptrend_reads_as_rising_growth(self):
        """A rolling z-score of the level falls during a long rise; momentum must not."""
        rising = monthly(np.linspace(40, 60, 90))
        falling = monthly(np.linspace(6, 1, 90))
        clock = mv.investment_clock({"US_PMI": rising, "TW_PMI": rising, "CN_PMI": rising,
                                     "US_CORE_CPI_YOY": falling, "US_CORE_PPI_YOY": falling})
        assert clock is None or clock["key"] == "recovery"

    def test_bullish_backdrop_is_not_labelled_a_downturn(self):
        assert mv.compute_market_view(macro_dataset(0.9), now=NOW)["clock"]["key"] in {"recovery", "overheat"}

    def test_bearish_backdrop_is_not_labelled_a_recovery(self):
        assert mv.compute_market_view(macro_dataset(-0.9), now=NOW)["clock"]["key"] in {"reflation", "stagflation"}

    def test_trail_is_ordered_and_bounded(self):
        clock = mv.investment_clock(self._data(True, False))
        assert len(clock["trail"]) <= mv.CLOCK_TRAIL_MONTHS
        assert clock["trail"]["date"].is_monotonic_increasing

    def test_insufficient_data_returns_none(self):
        assert mv.investment_clock({}) is None
        assert mv.investment_clock({"US_PMI": monthly([50] * 8)}) is None


# ── Full view ─────────────────────────────────────────────────────────────────

class TestComputeMarketView:
    def test_bullish_backdrop_reads_bullish(self):
        view = mv.compute_market_view(macro_dataset(0.9), now=NOW)
        assert view["stance"]["score"] > 0

    def test_bearish_backdrop_reads_bearish(self):
        view = mv.compute_market_view(macro_dataset(-0.9), now=NOW)
        assert view["stance"]["score"] < 0

    def test_empty_data_is_honest(self):
        view = mv.compute_market_view({}, now=NOW)
        assert view["stance"]["key"] == "unknown"
        assert view["conviction"] == "low"
        assert "資料不足" in view["headline"]

    def test_pillars_cover_all_four_groups(self):
        view = mv.compute_market_view(macro_dataset(0.5), now=NOW)
        assert [p["key"] for p in view["pillars"]] == ["A", "B", "C", "D"]
        for p in view["pillars"]:
            assert 0 <= p["pct"] <= 100
            assert p["valid"] >= p["bull"]

    def test_pillar_handles_group_with_no_data(self):
        data = {"US_PMI": monthly(range(30, 60))}
        pillars = mv.compute_market_view(data, now=NOW)["pillars"]
        assert next(p for p in pillars if p["key"] == "D")["pct"] is None

    def test_evidence_lists_partition_scored_signals(self):
        view = mv.compute_market_view(macro_dataset(0.3), now=NOW)
        scored = [s for s in view["gmi"]["signals"] if s["has_data"]]
        assert len(view["bull_case"]) + len(view["bear_case"]) == len(scored)

    def test_changes_report_flips_against_three_months_ago(self):
        data = {
            # As of July (3M before NOW) US is below 50 and TW is above 50 and rising.
            "US_PMI": monthly([47, 47, 47, 47, 47, 47, 47, 47, 48, 49, 51, 53]),
            "TW_PMI": monthly([50, 50, 50, 50, 50, 50, 50, 52, 53, 54, 52, 49]),
        }
        changes = mv.compute_market_view(data, now=NOW)["changes"]
        by_name = {c["name"]: c["to"] for c in changes}
        assert by_name.get("美國 PMI") == "bull"
        assert by_name.get("台灣 PMI") == "bear"

    def test_momentum_is_difference_in_diffusion(self):
        view = mv.compute_market_view(macro_dataset(0.6), now=NOW)
        assert view["momentum_pp"] == pytest.approx(
            view["gmi"]["diffusion"] - view["gmi_prev"]["diffusion"], abs=0.11)

    def test_headline_states_stance_and_diffusion(self):
        view = mv.compute_market_view(macro_dataset(0.9), now=NOW)
        assert view["stance"]["label"] in view["headline"]
        assert "%" in view["headline"]

    def test_stale_series_lower_conviction(self):
        fresh = mv.compute_market_view(macro_dataset(0.9), now=NOW)
        stale = mv.compute_market_view(macro_dataset(0.9), now=NOW + pd.DateOffset(years=2))
        assert stale["stale_count"] > fresh["stale_count"]
        assert mv.CONVICTION_RANK[stale["conviction"]] <= mv.CONVICTION_RANK[fresh["conviction"]]

    def test_confirmed_history_overrides_raw_regime(self):
        data = macro_dataset(0.9)
        history = build_macro_index_history(data, lookback_years=3)
        history = history.copy()
        history.loc[history.index[-1], "confirmed_regime"] = "red"
        view = mv.compute_market_view(data, history=history,
                                      now=NOW + pd.DateOffset(months=1))
        assert view["regime"] == "red"
        assert view["stance"]["score"] <= 0

    def test_unconfirmed_regime_change_is_disclosed(self):
        data = macro_dataset(0.9)
        history = build_macro_index_history(data, lookback_years=3).copy()
        history.loc[history.index[-1], "confirmed_regime"] = "yellow"
        view = mv.compute_market_view(data, history=history,
                                      now=NOW + pd.DateOffset(months=1))
        assert view["pending_regime"] == "green"

    def test_view_does_not_mutate_input(self):
        data = macro_dataset(0.5)
        before = {k: v.copy() for k, v in data.items() if isinstance(v, pd.DataFrame)}
        mv.compute_market_view(data, now=NOW)
        for key, frame in before.items():
            pd.testing.assert_frame_equal(frame, data[key])


class TestPillarBrief:
    def test_reports_score_and_lists_signals(self):
        view = mv.compute_market_view(macro_dataset(0.5), now=NOW)
        brief = mv.theme_brief(view, "demand")
        assert brief["total"] > 0
        assert brief["bull"] + brief["bear"] + brief["neutral"] == brief["total"]
        assert brief["tone"] in {"bullish", "bearish", "neutral"}
        assert brief["summary"]

    def test_empty_theme(self):
        view = mv.compute_market_view({}, now=NOW)
        brief = mv.theme_brief(view, "demand")
        assert brief["total"] == 0
        assert brief["tone"] == "neutral"


# ── Historical evidence ───────────────────────────────────────────────────────

class TestRegimeEvidence:
    def _stats(self):
        hist = build_macro_index_history(macro_dataset(0.5), lookback_years=8)
        rets = compute_forward_returns(hist, index_levels(), signal_lag=1)
        return hist, summarize_by_regime(rets, include_unconditional=True)

    def test_rows_compare_regime_to_baseline(self):
        hist, stats = self._stats()
        regime = hist.iloc[-1]["confirmed_regime"]
        rows = mv.regime_evidence(stats, regime, market="TWII", horizons=(3, 6))
        assert rows
        row = rows[0]
        base = stats[(stats.market == "TWII") & (stats.regime == "all") & (stats.horizon == row["horizon"])].iloc[0]
        assert row["edge"] == pytest.approx(row["median"] - base["median"])

    def test_effective_sample_discounts_overlap(self):
        _, stats = self._stats()
        any_regime = stats[stats.regime != "all"].iloc[0]["regime"]
        rows = mv.regime_evidence(stats, any_regime, market="TWII", horizons=(6, 12))
        for row in rows:
            assert row["n_eff"] == max(1, row["n"] // row["horizon"])

    def test_thin_samples_are_flagged(self):
        stats = pd.DataFrame([
            {"market": "TWII", "regime": "red", "horizon": 12, "median": 5.0, "mean": 5.0,
             "win_rate": 60.0, "p10": -5.0, "p90": 9.0, "worst": -9.0, "n": 20},
            {"market": "TWII", "regime": "all", "horizon": 12, "median": 8.0, "mean": 8.0,
             "win_rate": 70.0, "p10": -5.0, "p90": 9.0, "worst": -9.0, "n": 100},
        ])
        row = mv.regime_evidence(stats, "red", market="TWII", horizons=(12,))[0]
        assert row["thin"] is True

    def test_no_stats_returns_empty(self):
        assert mv.regime_evidence(pd.DataFrame(), "green") == []
        assert mv.regime_evidence(None, "green") == []


class TestForwardReturnLag:
    def test_signal_lag_delays_entry_by_one_month(self):
        dates = pd.date_range("2024-01-31", periods=6, freq="ME")
        history = pd.DataFrame({"date": dates[:2], "confirmed_regime": ["green", "green"]})
        prices = {"M": pd.DataFrame({"date": dates, "value": [100, 110, 121, 133.1, 146.41, 161.05]})}
        no_lag = compute_forward_returns(history, prices, horizons=(1,))
        lagged = compute_forward_returns(history, prices, horizons=(1,), signal_lag=1)
        assert len(no_lag) == len(lagged) == 2
        first = lagged.sort_values("as_of").iloc[0]
        assert first["fwd_pct_return"] == pytest.approx(0.10, abs=1e-6)
        assert pd.Timestamp(first["as_of"]) == dates[0]

    def test_default_lag_preserves_behaviour(self):
        dates = pd.date_range("2024-01-31", periods=3, freq="ME")
        history = pd.DataFrame({"date": dates[:1], "confirmed_regime": ["green"]})
        prices = {"M": pd.DataFrame({"date": dates, "value": [100, 150, 200]})}
        out = compute_forward_returns(history, prices, horizons=(1,))
        assert out.iloc[0]["fwd_pct_return"] == pytest.approx(0.5)


# ── Written brief ─────────────────────────────────────────────────────────────

class TestBrief:
    def test_contains_every_section(self):
        view = mv.compute_market_view(macro_dataset(0.6), now=NOW)
        text = mv.build_brief(view)
        for heading in ("結論", "四大支柱", "多方論據", "空方論據", "操作框架", "風險提示"):
            assert heading in text

    def test_carries_a_disclaimer(self):
        view = mv.compute_market_view(macro_dataset(0.6), now=NOW)
        assert "非投資建議" in mv.build_brief(view)

    def test_works_with_no_data(self):
        text = mv.build_brief(mv.compute_market_view({}, now=NOW))
        assert "資料不足" in text


def test_compute_macro_index_on_synthetic_data_is_complete():
    """Fixture sanity: the synthetic set feeds all 20 scored indicators."""
    assert compute_macro_index(macro_dataset(0.5))["valid_count"] == 20
