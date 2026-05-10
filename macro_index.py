"""
macro_index.py — Global Macro Index (GMI) scoring engine

Computes a 20-indicator binary diffusion score that drives a traffic-light
regime signal (Green / Yellow / Red) for the global macro dashboard.

Architecture:
    - 20 indicators in 4 groups (5 each), enforcing group-cap of 5.
    - Each indicator outputs 0 or 1 each month.
    - Score_t  = sum of all s_i,t  (max 20)
    - Diffusion_t = Score_t / 20 * 100  (%)
    - Regime:  Green >= 15 | Yellow 10-14 | Red <= 9
    - Anti-whipsaw: regime switch requires 2 consecutive months.
    - Low-confidence flag when valid indicators < 16.

Usage:
    from macro_index import compute_macro_index
    result = compute_macro_index(data_dict)
"""

import pandas as pd
import numpy as np
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

REGIME_GREEN  = 15   # Score >= this → Green (Expansion)
REGIME_RED    = 9    # Score <= this → Red (Contraction)
MIN_VALID     = 16   # Below this → Low Confidence flag
SLOPE_MONTHS  = 3    # Window used for "3M slope" calculations
GROUP_CAP     = 5    # Max effective score per group

REGIME_LABELS = {
    "green":  "🟢 擴張 (Expansion)",
    "yellow": "🟡 觀望 (Transition)",
    "red":    "🔴 收縮 (Contraction)",
    "unknown": "⚪ 資料不足",
}


# ──────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ──────────────────────────────────────────────────────────────────────────────

def _latest(df: pd.DataFrame) -> float | None:
    """Return the most recent numeric value from a date-value DataFrame."""
    if df is None or df.empty:
        return None
    v = df.sort_values("date").iloc[-1]["value"]
    return float(v) if pd.notna(v) else None


def _slope_positive(df: pd.DataFrame, months: int = SLOPE_MONTHS) -> bool | None:
    """
    Return True if the linear slope of the last `months` observations is positive.
    Returns None if not enough data.
    """
    if df is None or df.empty:
        return None
    s = df.sort_values("date").tail(months)
    if len(s) < 2:
        return None
    slope = np.polyfit(range(len(s)), s["value"].values, 1)[0]
    return bool(slope > 0)


def _avg_improving(df: pd.DataFrame, months: int = SLOPE_MONTHS) -> bool | None:
    """
    Compare rolling average of last `months` vs previous `months`.
    True if the recent avg > prior avg.
    """
    if df is None or df.empty:
        return None
    s = df.sort_values("date")
    if len(s) < months * 2:
        return None
    recent = s.tail(months)["value"].mean()
    prior  = s.iloc[-(months * 2):-months]["value"].mean()
    return bool(recent > prior)


def _3m_down(df: pd.DataFrame) -> bool | None:
    """True if the latest value is lower than 3M ago (drop = positive signal for risk-off indicators)."""
    if df is None or df.empty:
        return None
    s = df.sort_values("date")
    if len(s) < SLOPE_MONTHS:
        return None
    return bool(s.iloc[-1]["value"] < s.iloc[-SLOPE_MONTHS]["value"])


def _score(condition) -> int:
    """Convert a bool/None condition to 1 (True) or 0 (False/None)."""
    return 1 if condition is True else 0


# ──────────────────────────────────────────────────────────────────────────────
# Individual indicator signal functions (each returns 0 or 1, plus metadata)
# ──────────────────────────────────────────────────────────────────────────────

def _sig_pmi_expansion(df: pd.DataFrame, name: str):
    """PMI > 50 AND 3M slope positive."""
    v    = _latest(df)
    slp  = _slope_positive(df)
    cond = (v is not None and v > 50) and (slp is True)
    raw  = f"{v:.1f}" if v is not None else "N/A"
    rule = ">50 且 3M 斜率向上"
    return _score(cond), raw, rule, name, v is not None


def _sig_yoy_positive_improving(df: pd.DataFrame, name: str):
    """YoY > 0 AND 3M average improving."""
    v   = _latest(df)
    imp = _avg_improving(df)
    cond = (v is not None and v > 0) and (imp is True)
    raw  = f"{v:.1f}%" if v is not None else "N/A"
    rule = ">0 且 3M 均值改善"
    return _score(cond), raw, rule, name, v is not None


def _sig_yoy_positive(df: pd.DataFrame, name: str):
    """YoY > 0 (simple)."""
    v    = _latest(df)
    cond = v is not None and v > 0
    raw  = f"{v:.1f}%" if v is not None else "N/A"
    rule = ">0"
    return _score(cond), raw, rule, name, v is not None


def _sig_slope_up(df: pd.DataFrame, name: str):
    """3M slope is positive."""
    slp  = _slope_positive(df)
    v    = _latest(df)
    cond = slp is True
    raw  = f"{v:.2f}" if v is not None else "N/A"
    rule = "3M 斜率向上"
    return _score(cond), raw, rule, name, v is not None


def _sig_oecd_breadth(cli_dict: dict):
    """
    OECD CLI breadth: number of economies with CLI > 100.
    cli_dict keys: 'US', 'CN', 'JP', 'EU', 'KR'
    Signal = 1 if >= 3 of 5 are above 100.
    """
    count = 0
    valid = 0
    details = []
    for key, df in cli_dict.items():
        v = _latest(df)
        if v is not None:
            valid += 1
            above = v > 100
            details.append(f"{key}:{v:.1f}{'✓' if above else '✗'}")
            if above:
                count += 1
    if valid == 0:
        return 0, "N/A", "≥3/5 國家 CLI>100", "OECD CLI 廣度", False
    cond = count >= 3
    raw  = f"{count}/5 ({', '.join(details)})"
    rule = "≥3/5 國家 CLI>100"
    return _score(cond), raw, rule, "OECD CLI 廣度", True


def _sig_scissors_narrowing(cpi_yoy_df, ppi_yoy_df, scissors_df=None):
    """
    CPI-PPI scissors: narrowing (CPI-PPI gap shrinking) or gap < 0.
    Uses the pre-computed scissors spread if available.
    """
    cpi = _latest(cpi_yoy_df)
    ppi = _latest(ppi_yoy_df)

    if scissors_df is not None and not scissors_df.empty:
        # Primary path: use pre-computed spread series
        gap = _latest(scissors_df)
        has_data = gap is not None
        cond = has_data and (gap <= 0 or _3m_down(scissors_df) is True)
        if cpi is not None and ppi is not None and has_data:
            raw = f"CPI {cpi:.1f}% - PPI {ppi:.1f}% = {gap:.1f}pp"
        elif has_data:
            raw = f"剪刀差 = {gap:.1f}pp"
        else:
            raw = "N/A"
    elif cpi is not None and ppi is not None:
        # Fallback: compute on-the-fly from raw YoY series
        has_data = True
        gap = cpi - ppi
        merged = cpi_yoy_df.rename(columns={"value": "cpi"}).merge(
            ppi_yoy_df.rename(columns={"value": "ppi"}), on="date", how="inner"
        )
        merged["value"] = merged["cpi"] - merged["ppi"]
        cond = gap <= 0 or (_3m_down(merged[["date", "value"]]) is True)
        raw = f"CPI {cpi:.1f}% - PPI {ppi:.1f}% = {gap:.1f}pp"
    else:
        return 0, "N/A", "收斂或<0", "核心 CPI-PPI 剪刀差", False

    rule = "差值收斂或<0"
    return _score(cond), raw, rule, "核心 CPI-PPI 剪刀差", has_data


def _truncate_frame(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return a copy of df truncated to observations on or before as_of."""
    if not isinstance(df, pd.DataFrame) or df.empty or "date" not in df.columns:
        return df
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date")
    return out[out["date"] <= as_of].reset_index(drop=True)


def _slice_data_as_of(data: dict, as_of: pd.Timestamp) -> dict:
    """Create a historical snapshot by truncating all date-value frames to as_of."""
    snapshot = {}
    for key, value in data.items():
        snapshot[key] = _truncate_frame(value, as_of) if isinstance(value, pd.DataFrame) else value
    return snapshot


def _history_dates(data: dict, lookback_years: int) -> list[pd.Timestamp]:
    """Collect monthly dates from GMI-relevant series for timeline reconstruction."""
    keys = [
        "US_PMI", "TW_PMI", "CN_PMI", "EU_PMI", "US_NEW_ORDERS_YOY",
        "TW_EXP_YOY", "KR_EXP_YOY", "US_RETAIL_YOY", "US_CLI", "CN_CLI",
        "JP_CLI", "EU_CLI", "KR_CLI", "NDC_LEADING", "CPI_PPI_SCISSORS",
        "US_CORE_CPI_YOY", "US_CORE_PPI_YOY", "CN_PPI_YOY", "HY_SPREAD",
        "T10Y3M", "TW_M1B_YOY", "TW_M2_YOY", "VIX", "TWD_USD",
        "COPPER_YOY", "SECTOR_ROTATION", "THIRTEENF_NET_ADD",
    ]
    month_ends = set()
    for key in keys:
        df = data.get(key)
        if not isinstance(df, pd.DataFrame) or df.empty or "date" not in df.columns:
            continue
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        month_ends.update(dates.dt.to_period("M").dt.to_timestamp("M").tolist())

    if not month_ends:
        return []

    max_date = max(month_ends)
    min_date = max_date - pd.DateOffset(years=lookback_years)
    return sorted(d for d in month_ends if d >= min_date)


def _apply_two_period_confirmation(history_df: pd.DataFrame) -> pd.DataFrame:
    """Apply anti-whipsaw confirmation: switch regime only after 2 consecutive new-zone months."""
    if history_df.empty:
        return history_df

    confirmed = []
    current = history_df.iloc[0]["regime"]
    pending = None
    streak = 0

    for regime in history_df["regime"]:
        if regime == "unknown":
            confirmed.append("unknown")
            current = "unknown"
            pending = None
            streak = 0
            continue

        if current == "unknown":
            current = regime
            confirmed.append(current)
            pending = None
            streak = 0
            continue

        if regime == current:
            pending = None
            streak = 0
        else:
            if pending == regime:
                streak += 1
            else:
                pending = regime
                streak = 1
            if streak >= 2:
                current = regime
                pending = None
                streak = 0
        confirmed.append(current)

    out = history_df.copy()
    out["confirmed_regime"] = confirmed
    out["confirmed_regime_label"] = out["confirmed_regime"].map(REGIME_LABELS)
    return out


def _sig_hy_spread_down(df: pd.DataFrame):
    """HY OAS spread: 3M trend is down (risk-on signal)."""
    cond = _3m_down(df) is True
    v    = _latest(df)
    raw  = f"{v:.0f} bps" if v is not None else "N/A"
    rule = "3M 下降"
    return _score(cond), raw, rule, "HY 信用利差", v is not None


def _sig_10y3m_positive_rising(df: pd.DataFrame):
    """10Y-3M spread: > 0 AND 3M slope up."""
    v    = _latest(df)
    slp  = _slope_positive(df)
    cond = (v is not None and v > 0) and (slp is True)
    raw  = f"{v:.3f}%" if v is not None else "N/A"
    rule = ">0 且 3M 斜率向上"
    return _score(cond), raw, rule, "10Y-3M 利差", v is not None


def _sig_m1b_m2_spread(m1b_df: pd.DataFrame, m2_df: pd.DataFrame):
    """
    Taiwan M1B-M2 spread: M1B YoY > M2 YoY (golden cross) OR slope is up.
    Golden cross = active money growing faster than broad money.
    """
    m1b = _latest(m1b_df)
    m2  = _latest(m2_df)
    if m1b is None or m2 is None:
        return 0, "N/A", ">0 或 3M 斜率向上", "台灣 M1B-M2 利差", False
    spread = m1b - m2
    if not m1b_df.empty and not m2_df.empty:
        merged = m1b_df.rename(columns={"value": "m1b"}).merge(
            m2_df.rename(columns={"value": "m2"}), on="date", how="inner"
        )
        merged["value"] = merged["m1b"] - merged["m2"]
        spread_df = merged[["date", "value"]]
        slp = _slope_positive(spread_df)
    else:
        slp = None
    cond = spread > 0 or (slp is True)
    raw  = f"M1B {m1b:.1f}% vs M2 {m2:.1f}% → 差 {spread:.1f}pp"
    rule = ">0 或 3M 斜率向上"
    return _score(cond), raw, rule, "台灣 M1B-M2 利差", True


def _sig_vix_down(df: pd.DataFrame):
    """VIX: 3M point-to-point decline (latest vs 3M ago) is positive (risk-on)."""
    cond = _3m_down(df) is True
    v    = _latest(df)
    raw  = f"{v:.2f}" if v is not None else "N/A"
    rule = "3M 點對點下降"
    return _score(cond), raw, rule, "VIX", v is not None


def _sig_twd_appreciating(df: pd.DataFrame):
    """
    TWD/USD: lower value = TWD appreciating = risk-on for Taiwan.
    Signal: 3M trend is DOWN (USD/TWD falling).
    """
    cond = _3m_down(df) is True
    v    = _latest(df)
    raw  = f"{v:.3f}" if v is not None else "N/A"
    rule = "台幣 3M 升值趨勢"
    return _score(cond), raw, rule, "台幣匯率 TWD/USD", v is not None


def _sig_rotation_risk_on(df: pd.DataFrame):
    """
    Internal rotation: cyclical vs defensive 3M rolling excess return.
    Signal: > 0 (cyclical outperformed) AND 3M slope up.
    """
    if df is None or df.empty:
        return 0, "N/A (資料抓取中)", "超額報酬>0 且 3M 斜率向上", "內部輪動指數", False
    v    = _latest(df)
    slp  = _slope_positive(df)
    cond = (v is not None and v > 0) and (slp is True)
    raw  = f"{v:+.3f}" if v is not None else "N/A"
    rule = "超額報酬>0 且 3M 斜率向上"
    return _score(cond), raw, rule, "內部輪動指數", v is not None


def _sig_13f_cyclical_net_add(df: pd.DataFrame):
    """
    13F cyclical-vs-defensive net add ratio: > 0 means institutions are net-adding cyclical.
    Quarterly, lagged up to 45 days. If unavailable, returns 0 with 'N/A' label.
    """
    if df is None or df.empty:
        return 0, "N/A (季頻，下季公布)", "淨加碼比>0", "13F 循環/防禦淨加碼", False
    v    = _latest(df)
    cond = v is not None and v > 0
    raw  = f"{v:+.3f}" if v is not None else "N/A"
    rule = "淨加碼比>0"
    return _score(cond), raw, rule, "13F 循環/防禦淨加碼", v is not None


# ──────────────────────────────────────────────────────────────────────────────
# Main scoring function
# ──────────────────────────────────────────────────────────────────────────────

def compute_macro_index(data: dict) -> dict:
    """
    Compute the Global Macro Index from the data dictionary produced by load_data().

    Returns a dict with keys:
        score       int        0–20
        diffusion   float      0–100 (%)
        regime      str        'green' | 'yellow' | 'red' | 'unknown'
        regime_label str       Human-readable with emoji
        confidence  str        'normal' | 'low'
        valid_count int        Number of indicators with data
        signals     list[dict] Per-indicator detail rows
        group_scores dict      Score per group (A/B/C/D)
        as_of       str        Latest data date available
    """

    signals = []   # list of {group, id, name, score, raw, rule, has_data}
    group_raw = {"A": [], "B": [], "C": [], "D": []}

    def _add(group: str, id_: int, result: tuple) -> None:
        s, r, rl, n, hd = result
        signals.append({"group": group, "id": id_, "name": n, "score": s,
                         "raw": r, "rule": rl, "has_data": hd})
        group_raw[group].append(s)

    # ── Group A: Demand and Leading Activity ──────────────────────────────────
    _add("A", 1,  _sig_pmi_expansion(data.get("US_PMI"),  "美國 PMI"))
    _add("A", 2,  _sig_pmi_expansion(data.get("TW_PMI"),  "台灣 PMI"))
    _add("A", 3,  _sig_pmi_expansion(data.get("CN_PMI"),  "中國 PMI"))
    _add("A", 4,  _sig_pmi_expansion(data.get("EU_PMI"),  "歐洲工業信心"))
    _add("A", 5,  _sig_yoy_positive(data.get("US_NEW_ORDERS_YOY"), "美國製造業新訂單 YoY"))

    # ── Group B: Trade and Coincident Flow ────────────────────────────────────
    _add("B", 6,  _sig_yoy_positive_improving(data.get("TW_EXP_YOY"), "台灣出口 YoY"))
    _add("B", 7,  _sig_yoy_positive_improving(data.get("KR_EXP_YOY"), "韓國出口 YoY"))
    _add("B", 8,  _sig_yoy_positive(data.get("US_RETAIL_YOY"), "美國零售銷售 YoY"))
    _add("B", 9,  _sig_oecd_breadth({
        "US": data.get("US_CLI"), "CN": data.get("CN_CLI"),
        "JP": data.get("JP_CLI"), "EU": data.get("EU_CLI"), "KR": data.get("KR_CLI"),
    }))
    _add("B", 10, _sig_slope_up(data.get("NDC_LEADING"), "NDC 景氣領先指標"))

    # ── Group C: Cost, Liquidity, Financial Conditions ────────────────────────
    _add("C", 11, _sig_scissors_narrowing(
        data.get("US_CORE_CPI_YOY", pd.DataFrame()),
        data.get("US_CORE_PPI_YOY", pd.DataFrame()),
        data.get("CPI_PPI_SCISSORS", pd.DataFrame()),
    ))
    _add("C", 12, _sig_slope_up(data.get("CN_PPI_YOY"), "中國 PPI YoY"))
    _add("C", 13, _sig_hy_spread_down(data.get("HY_SPREAD")))
    _add("C", 14, _sig_10y3m_positive_rising(data.get("T10Y3M")))
    _add("C", 15, _sig_m1b_m2_spread(
        data.get("TW_M1B_YOY", pd.DataFrame()),
        data.get("TW_M2_YOY",  pd.DataFrame()),
    ))

    # ── Group D: Market Internals and Positioning ─────────────────────────────
    _add("D", 16, _sig_vix_down(data.get("VIX")))
    _add("D", 17, _sig_twd_appreciating(data.get("TWD_USD")))
    _add("D", 18, _sig_yoy_positive(data.get("COPPER_YOY"), "銅價 YoY"))
    _add("D", 19, _sig_rotation_risk_on(data.get("SECTOR_ROTATION")))
    _add("D", 20, _sig_13f_cyclical_net_add(data.get("THIRTEENF_NET_ADD")))

    # ── Apply group cap (max 5 per group) ─────────────────────────────────────
    group_scores = {}
    total_score  = 0
    for grp, scores in group_raw.items():
        capped = min(sum(scores), GROUP_CAP)
        group_scores[grp] = {"raw": sum(scores), "capped": capped}
        total_score += capped

    # ── Confidence ────────────────────────────────────────────────────────────
    valid_count = sum(1 for sig in signals if sig["has_data"])
    confidence  = "normal" if valid_count >= MIN_VALID else "low"

    # ── Regime ────────────────────────────────────────────────────────────────
    if valid_count < 10:
        regime = "unknown"
    elif total_score >= REGIME_GREEN:
        regime = "green"
    elif total_score <= REGIME_RED:
        regime = "red"
    else:
        regime = "yellow"

    diffusion = round(total_score / 20 * 100, 1)

    # ── Drivers and drags ─────────────────────────────────────────────────────
    # Prioritise leading-indicator groups (A first, then B, C, D) so the most
    # forward-looking signals surface rather than the first by indicator number.
    _group_priority = {"A": 0, "B": 1, "C": 2, "D": 3}
    positive_sigs = sorted(
        [s for s in signals if s["score"] == 1],
        key=lambda x: (_group_priority[x["group"]], x["id"]),
    )
    negative_sigs = sorted(
        [s for s in signals if s["score"] == 0 and s["has_data"]],
        key=lambda x: (_group_priority[x["group"]], x["id"]),
    )
    top_drivers = positive_sigs[:3]
    top_drags   = negative_sigs[:3]

    # ── As-of date ────────────────────────────────────────────────────────────
    as_of_dates = []
    for key in ["US_PMI", "TW_PMI", "HY_SPREAD", "VIX"]:
        df = data.get(key)
        if df is not None and not df.empty:
            as_of_dates.append(df.sort_values("date").iloc[-1]["date"])
    as_of = max(as_of_dates).strftime("%Y-%m") if as_of_dates else "N/A"

    return {
        "score":        total_score,
        "diffusion":    diffusion,
        "regime":       regime,
        "regime_label": REGIME_LABELS[regime],
        "confidence":   confidence,
        "valid_count":  valid_count,
        "signals":      signals,
        "group_scores": group_scores,
        "top_drivers":  top_drivers,
        "top_drags":    top_drags,
        "as_of":        as_of,
    }


def compute_macro_index_history(historical_data_list: list[dict]) -> pd.DataFrame:
    """
    Compute GMI score across multiple periods for historical timeline display.
    historical_data_list: list of data dicts, each representing one period.
    Returns a DataFrame with columns: date, score, diffusion, regime
    """
    records = []
    for item in historical_data_list:
        result = compute_macro_index(item["data"])
        records.append({
            "date":      item["date"],
            "score":     result["score"],
            "diffusion": result["diffusion"],
            "regime":    result["regime"],
            "valid_count": result["valid_count"],
        })
    history_df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    return _apply_two_period_confirmation(history_df)


def build_macro_index_history(data: dict, lookback_years: int = 10) -> pd.DataFrame:
    """Recompute the macro index month by month from the currently loaded data series."""
    records = []
    for as_of in _history_dates(data, lookback_years):
        snapshot = _slice_data_as_of(data, as_of)
        result = compute_macro_index(snapshot)
        records.append({
            "date": as_of,
            "score": result["score"],
            "diffusion": result["diffusion"],
            "regime": result["regime"],
            "valid_count": result["valid_count"],
        })

    if not records:
        return pd.DataFrame(columns=[
            "date", "score", "diffusion", "regime", "valid_count",
            "confirmed_regime", "confirmed_regime_label",
        ])

    history_df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    history_df = history_df[history_df["valid_count"] > 0].reset_index(drop=True)
    return _apply_two_period_confirmation(history_df)


def get_regime_color(regime: str) -> str:
    """Return Plotly-compatible color string for a regime."""
    return {
        "green":   "rgba(38,166,91,0.85)",
        "yellow":  "rgba(255,200,0,0.85)",
        "red":     "rgba(234,57,67,0.85)",
        "unknown": "rgba(150,150,150,0.5)",
    }.get(regime, "rgba(150,150,150,0.5)")
