"""Every threshold of the Taiwan early-warning layer, in one place.

Each parameter carries its unit and where the default came from:

    A  observed in the post-mortem of the 2026-10 sell-off (and earlier events)
    P  proposed; calibrated by analytics/tw_warning_backtest.py

Change numbers here, never in tw_warning.py. ``CONFIG`` is frozen; build a
variant with ``dataclasses.replace(CONFIG, rsi_overbought=75)`` for experiments.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields


def _p(default, unit: str, source: str, note: str = ""):
    return field(default=default, metadata={"unit": unit, "source": source, "note": note})


@dataclass(frozen=True)
class TwWarningConfig:
    # ── W1 rates ──────────────────────────────────────────────────────────────
    rate_window: int = _p(40, "交易日", "A", "8/14→10/6 共 40 日")
    rate_rise_pp: float = _p(0.40, "百分點", "P", "這次 +0.61 pp")
    # ── W2 dollar / TWD ───────────────────────────────────────────────────────
    fx_window: int = _p(40, "交易日", "P")
    dxy_rise_pct: float = _p(2.0, "%", "P", "這次 99.7→102.2（+2.5%）")
    twd_depr_pct: float = _p(3.0, "%", "P", "這次 31.69→33.11（+4.5%）")
    # ── W3 breadth divergence ─────────────────────────────────────────────────
    breadth_lookback: int = _p(10, "交易日", "P")
    breadth_div_days: int = _p(2, "天", "P", "10/5、10/1、9/23 都是指數漲、多數股跌")
    breadth_index_up_pct: float = _p(1.0, "%", "P", "10/5 指數 +2.55%、364 漲 631 跌")
    # ── W4 thin volume at highs ───────────────────────────────────────────────
    near_high_window: int = _p(60, "交易日", "P")
    near_high_pct: float = _p(3.0, "%", "P")
    vol_ma: int = _p(20, "交易日", "A")
    vol_ref_window: int = _p(120, "交易日", "P")
    vol_ratio_max: float = _p(0.70, "倍", "P", "10/6 只有 7 月初的 0.56 倍")
    # ── W5 foreign cash selling into strength ─────────────────────────────────
    fini_window: int = _p(20, "交易日", "A")
    fini_net_sell_ntd_bn: float = _p(300.0, "億元", "P", "9 月淨賣 417 億、指數 +4%")
    # ── W6 foreign futures shorts ─────────────────────────────────────────────
    fut_window: int = _p(10, "交易日", "A")
    fut_short_add_lots: float = _p(10_000.0, "口（TX 等值）", "A", "10/13 加碼超過 1 萬口")
    # ── W7 margin ─────────────────────────────────────────────────────────────
    margin_window: int = _p(60, "交易日", "P")
    margin_excess_pp: float = _p(15.0, "百分點", "P",
                                 "融資增速減指數漲幅；校準：10→15，兩段命中率都是 23%（10 時 14%／17%）")
    margin_high_window: int = _p(250, "交易日", "P", "10/15 超過 7 月前高")
    margin_use_high: bool = _p(False, "開關", "P",
                               "「超過前高」只顯示、不觸發；校準期命中率 14%，低於基本機率 17%")
    # ── W8 Taiwan VIX rising with the index ───────────────────────────────────
    vix_window: int = _p(10, "交易日", "A", "10/2→10/13")
    vix_rise_pts: float = _p(3.0, "點", "P", "這次 21.9→26.7（+4.8）")
    vix_near_high_window: int = _p(20, "交易日", "P")
    vix_near_high_pct: float = _p(3.0, "%", "P")
    # ── W9 overbought ─────────────────────────────────────────────────────────
    rsi_period: int = _p(14, "交易日", "A")
    rsi_method: str = _p("sma", "算法", "A",
                         "簡單平均（Cutler）；檢討中的 85、86 是這個算法，Wilder 只有 72、76")
    rsi_overbought: float = _p(80.0, "RSI", "A", "2022/1 為 86、2026/10 為 85")
    # ── display-only gauges ───────────────────────────────────────────────────
    breadth_ma: tuple[int, ...] = _p((20, 60), "交易日", "A")
    rs_window: int = _p(20, "交易日", "A")
    macro_short_window: int = _p(20, "交易日", "A")
    # ── W10 (8504 big-holder exits) ───────────────────────────────────────────
    whale_exit_window: int = _p(20, "交易日", "P")
    whale_exit_rise_pct: float = _p(50.0, "%", "P")
    # ── composite light ───────────────────────────────────────────────────────
    signal_memory: int = _p(10, "交易日", "P",
                            "近 N 日內成立過就計入；先行訊號在下跌開始後會消失，不能只看當天")
    lvl_watch_frac: float = _p(3 / 9, "比例", "A", "9 項中 3 項")
    lvl_reduce_frac: float = _p(5 / 9, "比例", "A", "9 項中 5 項")
    trend_fast_ma: int = _p(20, "交易日", "A")
    trend_slow_ma: int = _p(60, "交易日", "A")
    trim_high_beta: tuple[float, float] = _p((0.10, 0.20), "比例", "A")
    exposure_watch: float = _p(0.90, "持股比例", "P", "黃燈：高波動股減碼 10%～20% 的整體近似")
    exposure_reduce: float = _p(0.70, "持股比例", "A")
    exposure_defend: float = _p(0.50, "持股比例", "A")
    confirm_days: int = _p(2, "交易日", "P", "升級要連續成立")
    release_days: int = _p(5, "交易日", "P", "降級要連續成立")
    # ── re-entry ──────────────────────────────────────────────────────────────
    vix_panic: float = _p(40.0, "點", "A")
    vix_peak_window: int = _p(20, "交易日", "P")
    vix_retreat_pts: float = _p(5.0, "點", "P")
    margin_flush_window: int = _p(60, "交易日", "P")
    margin_flush_pct: float = _p(15.0, "%", "A")
    fut_cover_window: int = _p(5, "交易日", "P")
    fut_cover_lots: float = _p(5_000.0, "口（TX 等值）", "P")
    rebuy_tranches: int = _p(3, "批", "A")
    rebuy_gap_days: int = _p(5, "交易日", "P")
    # ── data freshness ────────────────────────────────────────────────────────
    stale_days: int = _p(7, "日曆日", "P", "超過就不計入燈號")
    # ── backtest definitions ──────────────────────────────────────────────────
    fwd_window: int = _p(40, "交易日", "A")
    fwd_drawdown_pct: float = _p(8.0, "%", "A")
    round_trip_cost: float = _p(0.0059, "比例", "A", "台股來回約 0.59%")
    backtest_years: int = _p(10, "年", "A")

    def level_counts(self, n_signals: int) -> tuple[int, int]:
        """Signals needed for 黃 and for 橙, scaled to how many signals exist."""
        return (math.ceil(self.lvl_watch_frac * n_signals - 1e-9),
                math.ceil(self.lvl_reduce_frac * n_signals - 1e-9))


CONFIG = TwWarningConfig()


def describe(cfg: TwWarningConfig = CONFIG) -> list[dict]:
    """Rows for the parameter table on the page and in docs."""
    return [{"參數": f.name, "值": getattr(cfg, f.name), "單位": f.metadata["unit"],
             "來源": f.metadata["source"], "說明": f.metadata["note"]}
            for f in fields(cfg)]
