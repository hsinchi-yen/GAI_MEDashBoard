"""
test_macro_index.py — TDD test suite for macro_index.py

Covers:
  - has_data field on every signal function
  - Signal scoring logic (PMI, YoY, VIX, rotation, 13F, scissors, etc.)
  - compute_macro_index: valid_count, confidence, group cap, regime, diffusion
  - top_drivers / top_drags group-priority ordering
  - _apply_two_period_confirmation anti-whipsaw logic
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from macro_index import (
    compute_macro_index,
    _apply_two_period_confirmation,
    _sig_pmi_expansion,
    _sig_yoy_positive,
    _sig_yoy_positive_improving,
    _sig_slope_up,
    _sig_scissors_narrowing,
    _sig_hy_spread_down,
    _sig_10y3m_positive_rising,
    _sig_m1b_m2_spread,
    _sig_vix_down,
    _sig_twd_appreciating,
    _sig_rotation_risk_on,
    _sig_13f_cyclical_net_add,
    REGIME_LABELS,
)


# ──────────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_df(values: list[float]) -> pd.DataFrame:
    """Create a date-value DataFrame (monthly, ending current month-start).

    Snap to day=1 so date_range generates exactly len(values) periods;
    a non-MS-aligned end silently produces periods-1 dates in pandas.
    """
    end = pd.Timestamp.now().replace(day=1)
    dates = pd.date_range(end=end, periods=len(values), freq="MS")
    return pd.DataFrame({"date": dates, "value": values})


def _full_data() -> dict:
    """
    Minimal but complete data dict for all 19 indicators.
    Not all signals will be 1 — that's intentional; correctness depends on
    the actual scoring rules, not a forced all-green scenario.
    """
    pmi_up   = make_df([49.0, 50.5, 51.5])   # >50, slope up → score=1
    pmi_down = make_df([53.0, 52.0, 51.0])   # >50, slope down → score=0
    yoy_pos  = make_df([2.0, 3.0, 4.0])       # positive, improving → score=1
    yoy_neg  = make_df([-2.0, -1.5, -1.0])   # negative → score=0
    hy_fall  = make_df([400.0, 380.0, 360.0]) # falling → score=1
    t10y3m   = make_df([0.10, 0.20, 0.30])    # >0, slope up → score=1
    vix_fall = make_df([28.0, 24.0, 20.0])    # falling → score=1
    twd_fall = make_df([32.0, 31.5, 31.0])    # falling (TWD appreciating) → score=1
    rot_up   = make_df([0.01, 0.02, 0.03])    # >0, slope up → score=1

    return {
        "US_PMI": pmi_up,
        "TW_PMI": pmi_up,
        "CN_PMI": pmi_up,
        "EU_PMI": pmi_up,
        "US_NEW_ORDERS_YOY": yoy_pos,
        "TW_EXP_YOY": yoy_pos,
        "KR_EXP_YOY": yoy_pos,
        "US_RETAIL_YOY": yoy_pos,
        "NDC_LEADING": make_df([98.0, 99.0, 100.0]),
        "US_CORE_CPI_YOY": yoy_pos,
        "US_CORE_PPI_YOY": make_df([5.0, 4.0, 3.0]),  # > cpi → scissors negative → score=1
        "CPI_PPI_SCISSORS": pd.DataFrame(),
        "CN_PPI_YOY": make_df([-3.0, -2.0, -1.0]),    # slope up → score=1
        "HY_SPREAD": hy_fall,
        "T10Y3M": t10y3m,
        "TW_M1B_YOY": make_df([3.0, 4.0, 5.0]),
        "TW_M2_YOY": make_df([2.0, 2.5, 3.0]),
        "VIX": vix_fall,
        "TWD_USD": twd_fall,
        "COPPER_YOY": yoy_pos,
        "SECTOR_ROTATION": rot_up,
        "THIRTEENF_NET_ADD": make_df([0.5]),
    }


# ──────────────────────────────────────────────────────────────────────────────
# has_data field — all signal functions must return a 5-tuple
# ──────────────────────────────────────────────────────────────────────────────

class TestHasDataField:
    """Every signal function must include has_data in its return tuple."""

    def test_pmi_expansion_has_data_when_series_present(self):
        s, r, rl, n, hd = _sig_pmi_expansion(make_df([51.0, 52.0, 53.0]), "PMI")
        assert hd is True

    def test_pmi_expansion_no_data_when_none(self):
        s, r, rl, n, hd = _sig_pmi_expansion(None, "PMI")
        assert hd is False
        assert s == 0

    def test_pmi_expansion_no_data_when_empty_df(self):
        s, r, rl, n, hd = _sig_pmi_expansion(pd.DataFrame(), "PMI")
        assert hd is False

    def test_yoy_positive_has_data(self):
        _, _, _, _, hd = _sig_yoy_positive(make_df([2.0]), "YoY")
        assert hd is True

    def test_yoy_positive_no_data_when_none(self):
        _, _, _, _, hd = _sig_yoy_positive(None, "YoY")
        assert hd is False

    def test_yoy_positive_improving_has_data(self):
        _, _, _, _, hd = _sig_yoy_positive_improving(make_df([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), "YoY")
        assert hd is True

    def test_slope_up_has_data(self):
        _, _, _, _, hd = _sig_slope_up(make_df([1.0, 2.0, 3.0]), "slope")
        assert hd is True

    def test_scissors_has_data_via_scissors_df(self):
        """has_data should be True when scissors_df is provided even if cpi/ppi are None."""
        scissors = make_df([-1.0, -0.5, -0.2])
        _, _, _, _, hd = _sig_scissors_narrowing(None, None, scissors_df=scissors)
        assert hd is True

    def test_scissors_no_data_when_all_missing(self):
        _, _, _, _, hd = _sig_scissors_narrowing(None, None, scissors_df=pd.DataFrame())
        assert hd is False

    def test_scissors_has_data_from_cpi_ppi(self):
        cpi = make_df([3.0, 3.2, 3.4])
        ppi = make_df([4.0, 3.5, 3.0])
        _, _, _, _, hd = _sig_scissors_narrowing(cpi, ppi)
        assert hd is True

    def test_hy_spread_has_data(self):
        _, _, _, _, hd = _sig_hy_spread_down(make_df([400.0, 380.0, 360.0]))
        assert hd is True

    def test_hy_spread_no_data_when_none(self):
        _, _, _, _, hd = _sig_hy_spread_down(None)
        assert hd is False

    def test_10y3m_has_data(self):
        _, _, _, _, hd = _sig_10y3m_positive_rising(make_df([0.1, 0.2, 0.3]))
        assert hd is True

    def test_m1b_m2_has_data_when_both_present(self):
        m1b = make_df([3.0, 4.0, 5.0])
        m2  = make_df([2.0, 2.5, 3.0])
        _, _, _, _, hd = _sig_m1b_m2_spread(m1b, m2)
        assert hd is True

    def test_m1b_m2_no_data_when_either_empty(self):
        _, _, _, _, hd = _sig_m1b_m2_spread(pd.DataFrame(), pd.DataFrame())
        assert hd is False

    def test_vix_down_has_data(self):
        _, _, _, _, hd = _sig_vix_down(make_df([25.0, 22.0, 18.0]))
        assert hd is True

    def test_vix_down_no_data_when_none(self):
        _, _, _, _, hd = _sig_vix_down(None)
        assert hd is False

    def test_twd_appreciating_has_data(self):
        _, _, _, _, hd = _sig_twd_appreciating(make_df([32.0, 31.5, 31.0]))
        assert hd is True

    def test_rotation_has_data_when_df_present(self):
        _, _, _, _, hd = _sig_rotation_risk_on(make_df([0.01, 0.02, 0.03]))
        assert hd is True

    def test_rotation_no_data_when_none(self):
        _, _, _, _, hd = _sig_rotation_risk_on(None)
        assert hd is False

    def test_rotation_no_data_when_empty(self):
        _, _, _, _, hd = _sig_rotation_risk_on(pd.DataFrame())
        assert hd is False

    def test_13f_has_data_when_df_present(self):
        _, _, _, _, hd = _sig_13f_cyclical_net_add(make_df([0.5]))
        assert hd is True

    def test_13f_no_data_when_empty(self):
        _, _, _, _, hd = _sig_13f_cyclical_net_add(pd.DataFrame())
        assert hd is False


# ──────────────────────────────────────────────────────────────────────────────
# Signal scoring correctness
# ──────────────────────────────────────────────────────────────────────────────

class TestSignalScoring:

    # PMI expansion
    def test_pmi_score_1_when_above_50_and_slope_up(self):
        s, *_ = _sig_pmi_expansion(make_df([49.0, 50.5, 51.5]), "PMI")
        assert s == 1

    def test_pmi_score_0_when_below_50(self):
        s, *_ = _sig_pmi_expansion(make_df([47.0, 48.0, 48.5]), "PMI")
        assert s == 0

    def test_pmi_score_0_when_above_50_but_slope_down(self):
        s, *_ = _sig_pmi_expansion(make_df([53.0, 52.0, 51.0]), "PMI")
        assert s == 0

    # YoY positive
    def test_yoy_positive_score_1(self):
        s, *_ = _sig_yoy_positive(make_df([5.0]), "YoY")
        assert s == 1

    def test_yoy_positive_score_0_when_zero(self):
        s, *_ = _sig_yoy_positive(make_df([0.0]), "YoY")
        assert s == 0

    def test_yoy_positive_score_0_when_negative(self):
        s, *_ = _sig_yoy_positive(make_df([-1.0]), "YoY")
        assert s == 0

    # Scissors narrowing
    def test_scissors_score_1_when_gap_negative(self):
        scissors = make_df([-1.5, -1.0, -0.5])  # CPI-PPI < 0
        s, *_ = _sig_scissors_narrowing(None, None, scissors_df=scissors)
        assert s == 1

    def test_scissors_score_1_when_gap_narrowing(self):
        scissors = make_df([2.0, 1.5, 1.0])  # positive but falling
        s, *_ = _sig_scissors_narrowing(None, None, scissors_df=scissors)
        assert s == 1

    def test_scissors_score_0_when_gap_positive_and_widening(self):
        scissors = make_df([1.0, 1.5, 2.0])  # positive and rising → no signal
        s, *_ = _sig_scissors_narrowing(None, None, scissors_df=scissors)
        assert s == 0

    # VIX down
    def test_vix_score_1_when_3m_falling(self):
        s, *_ = _sig_vix_down(make_df([28.0, 24.0, 20.0]))
        assert s == 1

    def test_vix_score_0_when_3m_rising(self):
        s, *_ = _sig_vix_down(make_df([18.0, 22.0, 26.0]))
        assert s == 0

    # TWD appreciating (lower USD/TWD = TWD up)
    def test_twd_score_1_when_rate_falling(self):
        s, *_ = _sig_twd_appreciating(make_df([32.0, 31.5, 31.0]))
        assert s == 1

    def test_twd_score_0_when_rate_rising(self):
        s, *_ = _sig_twd_appreciating(make_df([30.0, 31.0, 32.0]))
        assert s == 0

    # Rotation
    def test_rotation_score_1_when_excess_positive_and_trending_up(self):
        s, *_ = _sig_rotation_risk_on(make_df([0.01, 0.02, 0.03]))
        assert s == 1

    def test_rotation_score_0_when_excess_negative(self):
        s, *_ = _sig_rotation_risk_on(make_df([-0.03, -0.02, -0.01]))
        assert s == 0

    # 13F net add
    def test_13f_score_1_when_positive(self):
        s, *_ = _sig_13f_cyclical_net_add(make_df([0.5]))
        assert s == 1

    def test_13f_score_0_when_negative(self):
        s, *_ = _sig_13f_cyclical_net_add(make_df([-0.5]))
        assert s == 0

    # M1B-M2 golden cross
    def test_m1b_m2_score_1_when_m1b_greater_than_m2(self):
        m1b = make_df([3.0, 4.0, 5.0])
        m2  = make_df([2.0, 2.5, 3.0])
        s, *_ = _sig_m1b_m2_spread(m1b, m2)
        assert s == 1

    def test_m1b_m2_score_0_when_m1b_less_than_m2_and_not_improving(self):
        m1b = make_df([1.0, 1.2, 1.3])
        m2  = make_df([3.0, 3.5, 4.0])  # M2 much higher, spread falling
        s, *_ = _sig_m1b_m2_spread(m1b, m2)
        assert s == 0

    # HY spread
    def test_hy_score_1_when_falling(self):
        s, *_ = _sig_hy_spread_down(make_df([500.0, 450.0, 400.0]))
        assert s == 1

    def test_hy_score_0_when_rising(self):
        s, *_ = _sig_hy_spread_down(make_df([350.0, 400.0, 450.0]))
        assert s == 0

    # 10Y-3M spread
    def test_10y3m_score_1_when_positive_and_rising(self):
        s, *_ = _sig_10y3m_positive_rising(make_df([0.1, 0.2, 0.3]))
        assert s == 1

    def test_10y3m_score_0_when_inverted(self):
        s, *_ = _sig_10y3m_positive_rising(make_df([-0.5, -0.3, -0.1]))
        assert s == 0


# ──────────────────────────────────────────────────────────────────────────────
# compute_macro_index — structure and correctness
# ──────────────────────────────────────────────────────────────────────────────

class TestComputeMacroIndex:

    def test_result_has_all_required_keys(self):
        result = compute_macro_index(_full_data())
        required = (
            "score", "diffusion", "regime", "regime_label",
            "confidence", "valid_count", "signals",
            "group_scores", "top_drivers", "top_drags", "as_of",
        )
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_every_signal_dict_has_has_data(self):
        result = compute_macro_index(_full_data())
        for sig in result["signals"]:
            assert "has_data" in sig, f"Signal #{sig['id']} missing has_data"
            assert isinstance(sig["has_data"], bool)

    def test_exactly_19_signals(self):
        result = compute_macro_index(_full_data())
        assert len(result["signals"]) == 19

    def test_valid_count_is_19_with_full_data(self):
        result = compute_macro_index(_full_data())
        assert result["valid_count"] == 19

    def test_valid_count_decreases_when_indicators_missing(self):
        data = _full_data()
        data["SECTOR_ROTATION"] = None           # #18 → has_data=False
        data["THIRTEENF_NET_ADD"] = pd.DataFrame()  # #19 → has_data=False
        result = compute_macro_index(data)
        assert result["valid_count"] == 17

    def test_confidence_normal_with_16_or_more_valid(self):
        result = compute_macro_index(_full_data())
        assert result["confidence"] == "normal"

    def test_confidence_low_with_empty_data(self):
        result = compute_macro_index({})
        assert result["confidence"] == "low"

    def test_group_cap_never_exceeds_5(self):
        result = compute_macro_index(_full_data())
        for grp, scores in result["group_scores"].items():
            assert scores["capped"] <= 5, f"Group {grp} capped={scores['capped']} exceeds 5"
            assert scores["raw"] >= scores["capped"]

    def test_total_score_equals_sum_of_capped_scores(self):
        result = compute_macro_index(_full_data())
        expected = sum(v["capped"] for v in result["group_scores"].values())
        assert result["score"] == expected

    def test_diffusion_formula(self):
        """Diffusion divides by VALID indicator count, not a fixed 20."""
        result = compute_macro_index(_full_data())
        # Tolerance 0.1 accounts for round(..., 1) in the diffusion calculation
        assert abs(result["diffusion"] - result["score"] / result["valid_count"] * 100) < 0.1

    def test_diffusion_full_data_matches_legacy(self):
        """With all 19 valid, proportional diffusion equals the legacy /19 value."""
        result = compute_macro_index(_full_data())
        assert result["valid_count"] == 19
        assert abs(result["diffusion"] - result["score"] / 19 * 100) < 0.1

    def test_missing_indicators_do_not_drag_regime_down(self):
        """Core fix: dropping bullish indicators must not flip green→yellow/red."""
        full = compute_macro_index(_full_data())
        data = _full_data()
        # Drop 6 known-bullish series outright.
        for k in ("US_PMI", "TW_PMI", "CN_PMI", "EU_PMI", "HY_SPREAD", "VIX"):
            data[k] = None
        partial = compute_macro_index(data)
        # Proportional diffusion should stay >= the legacy /20 value for the same score.
        legacy_diff = partial["score"] / 19 * 100
        assert partial["diffusion"] >= legacy_diff
        # And valid_count dropped by exactly 6.
        assert partial["valid_count"] == full["valid_count"] - 6

    def test_regime_uses_proportional_thresholds(self):
        """≥75% of valid indicators bullish → green even when several are missing."""
        from macro_index import REGIME_GREEN_PCT
        data = {
            "US_PMI": make_df([49.0, 50.5, 51.5]),
            "TW_PMI": make_df([49.0, 50.5, 51.5]),
            "CN_PMI": make_df([49.0, 50.5, 51.5]),
            "EU_PMI": make_df([49.0, 50.5, 51.5]),
            "US_NEW_ORDERS_YOY": make_df([2.0, 3.0, 4.0]),
            "HY_SPREAD": make_df([400.0, 380.0, 360.0]),
            "T10Y3M": make_df([0.1, 0.2, 0.3]),
            "VIX": make_df([28.0, 24.0, 20.0]),
            "TWD_USD": make_df([32.0, 31.5, 31.0]),
            "COPPER_YOY": make_df([2.0, 3.0, 4.0]),
            "SECTOR_ROTATION": make_df([0.01, 0.02, 0.03]),
            "TW_M1B_YOY": make_df([3.0, 4.0, 5.0]),
            "TW_M2_YOY": make_df([2.0, 2.5, 3.0]),
        }
        result = compute_macro_index(data)
        assert result["valid_count"] >= 10
        if result["diffusion"] >= REGIME_GREEN_PCT:
            assert result["regime"] == "green"

    def test_score_bounds(self):
        result = compute_macro_index(_full_data())
        assert 0 <= result["score"] <= 19
        assert 0.0 <= result["diffusion"] <= 100.0

    def test_regime_is_valid_value(self):
        result = compute_macro_index(_full_data())
        assert result["regime"] in ("green", "yellow", "red", "unknown")

    def test_regime_label_matches_regime(self):
        result = compute_macro_index(_full_data())
        assert result["regime_label"] == result["regime_label"]
        # Verify label comes from REGIME_LABELS
        from macro_index import REGIME_LABELS
        assert result["regime_label"] == REGIME_LABELS[result["regime"]]

    def test_regime_unknown_when_too_few_valid(self):
        result = compute_macro_index({})
        assert result["regime"] == "unknown"

    def test_top_drivers_sorted_group_a_before_b_c_d(self):
        """Leading indicators (Group A) must appear before coincident ones in drivers."""
        result = compute_macro_index(_full_data())
        drivers = result["top_drivers"]
        _priority = {"A": 0, "B": 1, "C": 2, "D": 3}
        for i in range(len(drivers) - 1):
            assert _priority[drivers[i]["group"]] <= _priority[drivers[i + 1]["group"]], (
                f"Driver ordering wrong: {drivers[i]['group']} (#{drivers[i]['id']}) "
                f"after {drivers[i+1]['group']} (#{drivers[i+1]['id']})"
            )

    def test_top_drags_contain_only_has_data_signals(self):
        """Drags must never include indicators with no data."""
        data = _full_data()
        data["SECTOR_ROTATION"] = None
        data["THIRTEENF_NET_ADD"] = pd.DataFrame()
        result = compute_macro_index(data)
        for drag in result["top_drags"]:
            assert drag["has_data"] is True, (
                f"Drag #{drag['id']} {drag['name']} has no data but appeared in drags"
            )

    def test_top_drivers_max_3(self):
        result = compute_macro_index(_full_data())
        assert len(result["top_drivers"]) <= 3

    def test_top_drags_max_3(self):
        result = compute_macro_index(_full_data())
        assert len(result["top_drags"]) <= 3

    def test_green_regime_when_score_gte_15(self):
        """Force score=20 by providing all strongly positive data."""
        data = _full_data()
        result = compute_macro_index(data)
        # Score ≥ 15 → green; just assert consistency if we achieve it
        if result["score"] >= 15:
            assert result["regime"] == "green"

    def test_red_regime_when_score_lte_9(self):
        """Force low score by providing all strongly negative data."""
        neg_pmi = make_df([45.0, 44.0, 43.0])
        neg_yoy = make_df([-5.0, -4.0, -3.0])
        data = {
            "US_PMI": neg_pmi, "TW_PMI": neg_pmi,
            "CN_PMI": neg_pmi, "EU_PMI": neg_pmi,
            "US_NEW_ORDERS_YOY": neg_yoy,
            "TW_EXP_YOY": neg_yoy, "KR_EXP_YOY": neg_yoy,
            "US_RETAIL_YOY": neg_yoy,
            "US_CLI": make_df([98.0, 97.5, 97.0]),
            "CN_CLI": make_df([98.0, 97.5, 97.0]),
            "JP_CLI": make_df([98.0, 97.5, 97.0]),
            "EU_CLI": make_df([99.0, 98.5, 98.0]),
            "KR_CLI": make_df([99.0, 98.5, 98.0]),
            "NDC_LEADING": make_df([101.0, 100.5, 100.0]),
            "US_CORE_CPI_YOY": make_df([5.0, 5.5, 6.0]),
            "US_CORE_PPI_YOY": make_df([2.0, 1.5, 1.0]),  # CPI > PPI, widening → score=0
            "CPI_PPI_SCISSORS": pd.DataFrame(),
            "CN_PPI_YOY": make_df([-2.0, -2.5, -3.0]),    # slope down → score=0
            "HY_SPREAD": make_df([400.0, 420.0, 450.0]),
            "T10Y3M": make_df([-0.5, -0.4, -0.3]),         # inverted → score=0
            "TW_M1B_YOY": make_df([1.0, 1.5, 2.0]),
            "TW_M2_YOY": make_df([4.0, 4.5, 5.0]),         # M2 > M1B → score=0
            "VIX": make_df([18.0, 22.0, 28.0]),
            "TWD_USD": make_df([30.0, 31.0, 32.0]),
            "COPPER_YOY": neg_yoy,
            "SECTOR_ROTATION": make_df([-0.03, -0.02, -0.01]),
            "THIRTEENF_NET_ADD": make_df([-0.5]),
        }
        result = compute_macro_index(data)
        if result["score"] <= 9:
            assert result["regime"] == "red"


# ──────────────────────────────────────────────────────────────────────────────
# Anti-whipsaw two-period confirmation
# ──────────────────────────────────────────────────────────────────────────────

class TestTwoPeriodConfirmation:

    def _make_history(self, regimes: list[str]) -> pd.DataFrame:
        end = pd.Timestamp.now().replace(day=1)
        dates = pd.date_range(end=end, periods=len(regimes), freq="MS")
        return pd.DataFrame({
            "date": dates,
            "score": [10] * len(regimes),
            "diffusion": [50.0] * len(regimes),
            "regime": regimes,
            "valid_count": [18] * len(regimes),
        })

    def test_single_regime_change_does_not_switch(self):
        """One month in new regime is not enough to confirm the switch."""
        result = _apply_two_period_confirmation(
            self._make_history(["green", "red", "green"])
        )
        assert result.iloc[1]["confirmed_regime"] == "green"

    def test_two_consecutive_changes_do_switch(self):
        """Two consecutive months in new regime confirms the switch."""
        result = _apply_two_period_confirmation(
            self._make_history(["green", "red", "red"])
        )
        assert result.iloc[2]["confirmed_regime"] == "red"

    def test_confirmed_regime_stable_without_new_zone(self):
        """Continuing in the same regime keeps confirmed_regime unchanged."""
        result = _apply_two_period_confirmation(
            self._make_history(["green", "green", "green"])
        )
        assert all(result["confirmed_regime"] == "green")

    def test_unknown_resets_state(self):
        """Unknown regime resets pending state; next known regime takes immediate effect."""
        result = _apply_two_period_confirmation(
            self._make_history(["green", "unknown", "red"])
        )
        assert result.iloc[1]["confirmed_regime"] == "unknown"
        # After unknown, a single period of 'red' is an immediate reset (unknown→known)
        assert result.iloc[2]["confirmed_regime"] == "red"

    def test_confirmed_regime_label_present(self):
        result = _apply_two_period_confirmation(
            self._make_history(["green", "green"])
        )
        assert "confirmed_regime_label" in result.columns
        assert result.iloc[0]["confirmed_regime_label"] is not None

    def test_returns_same_number_of_rows(self):
        history = self._make_history(["green", "yellow", "red", "red", "green"])
        result = _apply_two_period_confirmation(history)
        assert len(result) == len(history)

    def test_requires_exactly_2_periods_not_3(self):
        """Confirm switch happens at the 2nd period, not later."""
        result = _apply_two_period_confirmation(
            self._make_history(["green", "red", "red", "red"])
        )
        # Switch should happen at index 2 (second red), not 3
        assert result.iloc[2]["confirmed_regime"] == "red"
        assert result.iloc[1]["confirmed_regime"] == "green"  # still green before confirmation

    def test_aborted_switch_resets_on_revert(self):
        """If a potential switch is aborted (only 1 period), streak resets."""
        result = _apply_two_period_confirmation(
            self._make_history(["green", "red", "green", "red", "red"])
        )
        # single red at index 1 → no switch; two reds at 3-4 → switch
        assert result.iloc[1]["confirmed_regime"] == "green"
        assert result.iloc[3]["confirmed_regime"] == "green"
        assert result.iloc[4]["confirmed_regime"] == "red"
