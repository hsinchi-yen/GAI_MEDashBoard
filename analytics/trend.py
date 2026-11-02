"""Per-series trend analysis: direction, historical position, staleness.

Answers, for every indicator: is it rising or falling *relative to its own normal
volatility*, is that good or bad for risk assets, and can the reading be trusted
(how old is it)? Pure pandas; no Streamlit, no I/O.
"""
from __future__ import annotations

import pandas as pd

from analytics.indicators import ROLE_LABELS, STALE_DAYS, THEMES, Indicator, all_indicators
from macro_index import _to_monthly

MIN_MONTHS    = 7     # below this a 6M change is undefined → series is skipped
WINDOW_MONTHS = 60    # percentile / z-score reference window
SPARK_MONTHS  = 24
NOISE_RATIO   = 0.35  # |3M change| below this share of typical 3M move → "flat"

RADAR_COLUMNS = [
    "key", "name", "theme", "theme_label", "role", "page", "latest", "latest_text",
    "latest_date", "change_1m", "change_3m", "change_6m", "change_3m_text",
    "percentile", "zscore", "direction", "signal", "stage", "inflection",
    "stale", "age_days", "spark", "why",
]


def _direction(change: float, typical: float) -> str:
    if change == 0 or abs(change) < NOISE_RATIO * typical:
        return "flat"
    return "up" if change > 0 else "down"


def _stage(direction: str, zscore: float, polarity: int) -> str:
    """Name the position in the cycle, oriented so that good news is always 'up'."""
    if direction == "flat":
        return "盤整"
    improving = (direction == "up") == (polarity > 0)
    favourable_level = (zscore >= 0) == (polarity > 0)
    if improving:
        return "強勢" if favourable_level else "回升"
    return "轉弱" if favourable_level else "弱勢"


def _inflection(change_3m: float, change_prev_3m: float, typical: float, polarity: int) -> str:
    """Detect a 3M trend that reversed the prior 3M trend (polarity-adjusted)."""
    if abs(change_3m) < NOISE_RATIO * typical or abs(change_prev_3m) < NOISE_RATIO * typical:
        return "none"
    if change_3m > 0 > change_prev_3m:
        return "turning_up" if polarity > 0 else "turning_down"
    if change_3m < 0 < change_prev_3m:
        return "turning_down" if polarity > 0 else "turning_up"
    return "none"


def analyze_series(df: pd.DataFrame | None, ind: Indicator, now: pd.Timestamp) -> dict | None:
    """Analyse one {date, value} series. Returns None when history is too short."""
    months = _to_monthly(df)
    if len(months) < MIN_MONTHS:
        return None

    values = months["value"].astype(float).reset_index(drop=True)
    latest = float(values.iloc[-1])

    def change(n: int) -> float:
        return latest - float(values.iloc[-(n + 1)])

    change_3m = change(3)
    moves = values.diff(3).dropna().tail(WINDOW_MONTHS)
    typical = float(moves.abs().median()) if not moves.empty else 0.0

    window = values.tail(WINDOW_MONTHS)
    std = float(window.std(ddof=0))
    zscore = 0.0 if std == 0 else (latest - float(window.mean())) / std
    percentile = float((window <= latest).mean() * 100)

    direction = _direction(change_3m, typical)
    if direction == "flat":
        signal = "neutral"
    else:
        signal = "bullish" if (direction == "up") == (ind.polarity > 0) else "bearish"

    prev_3m = float(values.iloc[-4] - values.iloc[-7])
    latest_date = pd.Timestamp(df.dropna(subset=["value"])["date"].max())
    age_days = int((pd.Timestamp(now) - latest_date).days)

    return {
        "latest":      latest,
        "latest_date": latest_date,
        "change_1m":   change(1),
        "change_3m":   change_3m,
        "change_6m":   change(6),
        "percentile":  percentile,
        "zscore":      float(zscore),
        "direction":   direction,
        "signal":      signal,
        "stage":       _stage(direction, zscore, ind.polarity),
        "inflection":  _inflection(change_3m, prev_3m, typical, ind.polarity),
        "stale":       age_days > STALE_DAYS[ind.freq],
        "age_days":    age_days,
        "spark":       values.tail(SPARK_MONTHS).round(4).tolist(),
    }


def format_value(value: float | None, ind: Indicator) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.{ind.decimals}f}{ind.unit}"


def format_delta(value: float | None, ind: Indicator) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+,.{ind.decimals}f}"


def build_radar(data: dict, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per catalogue indicator that has usable data."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    rows = []
    for ind in all_indicators():
        df = data.get(ind.key)
        if not isinstance(df, pd.DataFrame):
            continue
        result = analyze_series(df, ind, now)
        if result is None:
            continue
        rows.append({
            **result,
            "key":            ind.key,
            "name":           ind.name,
            "theme":          ind.theme,
            "theme_label":    THEMES[ind.theme],
            "role":           ROLE_LABELS[ind.role],
            "page":           ind.page,
            "latest_text":    format_value(result["latest"], ind),
            "change_3m_text": format_delta(result["change_3m"], ind),
            "why":            ind.why,
        })
    return pd.DataFrame(rows, columns=RADAR_COLUMNS)


def breadth(radar: pd.DataFrame) -> dict:
    """Count bullish vs bearish trends; net_pct is (bull - bear) / total."""
    if radar is None or radar.empty:
        return {"bullish": 0, "bearish": 0, "neutral": 0, "total": 0, "net_pct": 0.0}
    counts = radar["signal"].value_counts()
    bull = int(counts.get("bullish", 0))
    bear = int(counts.get("bearish", 0))
    total = int(len(radar))
    return {
        "bullish": bull,
        "bearish": bear,
        "neutral": int(counts.get("neutral", 0)),
        "total":   total,
        "net_pct": round((bull - bear) / total * 100, 1),
    }
