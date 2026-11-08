"""Market view: turn the macro data set into a clear bullish / bearish read.

The verdict is deliberately simple enough to audit by hand:

    stance score = level (GMI regime: +1 / 0 / -1)
                 + direction (3M change in diffusion: +1 / 0 / -1)

giving five stances from 強烈偏空 (-2) to 強烈偏多 (+2). Around it sit the things
an investor needs to act on the verdict: the four pillars, the evidence on each
side, what flipped recently, how far the regime is from changing, risk alerts,
and where we are on the growth/inflation clock.

Pure pandas; no Streamlit, no I/O. This is a rule-based framework, not a forecast.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from analytics.indicators import REGISTRY, STALE_DAYS, THEMES
from analytics.trend import breadth, build_radar
from analytics.tw_warning import evaluate as evaluate_tw_warning
from macro_index import (
    MIN_VALID, REGIME_GREEN_PCT, REGIME_LABELS, REGIME_RED_PCT, TOTAL_INDICATORS,
    _slice_data_as_of, _to_monthly, compute_macro_index,
)

LOOKBACK_MONTHS    = 3
MOMENTUM_PP        = 10.0   # ≈ two indicators out of 19 changing side
MIN_EFFECTIVE_N    = 8      # below this many independent windows → "thin sample"
CLOCK_TRAIL_MONTHS = 12
CLOCK_MIN_MONTHS   = 36

DISCLAIMER = "本工具為規則式總經框架，僅供研究參考，非投資建議；歷史統計不保證未來表現。"

STANCES: dict[str, dict] = {
    "strong_bull": {"label": "強烈偏多", "short": "多", "tone": "bullish",
                    "meaning": "景氣擴張且動能持續增強"},
    "bull":        {"label": "偏多",     "short": "多", "tone": "bullish",
                    "meaning": "多方佔優，但尚未全面確認"},
    "neutral":     {"label": "中性",     "short": "平", "tone": "neutral",
                    "meaning": "多空訊號互相抵銷，等待方向"},
    "bear":        {"label": "偏空",     "short": "空", "tone": "bearish",
                    "meaning": "空方佔優，宜控制風險"},
    "strong_bear": {"label": "強烈偏空", "short": "空", "tone": "bearish",
                    "meaning": "景氣收縮且動能持續惡化"},
    "unknown":     {"label": "資料不足", "short": "—", "tone": "neutral",
                    "meaning": "有效指標太少，無法形成判斷"},
}
_SCORE_TO_STANCE = {2: "strong_bull", 1: "bull", 0: "neutral", -1: "bear", -2: "strong_bear"}
_LEVEL = {"green": 1, "yellow": 0, "red": -1}
_DIRECTION = {"improving": 1, "flat": 0, "deteriorating": -1}
_PHASE = {
    ("green", "improving"): "expansion",     ("green", "flat"): "expansion",
    ("green", "deteriorating"): "slowdown",
    ("yellow", "improving"): "recovery",     ("yellow", "flat"): "transition",
    ("yellow", "deteriorating"): "slowdown",
    ("red", "improving"): "recovery",        ("red", "flat"): "contraction",
    ("red", "deteriorating"): "contraction",
}

PHASES: dict[str, str] = {
    "expansion":   "擴張期",
    "slowdown":    "放緩期",
    "contraction": "收縮期",
    "recovery":    "復甦期",
    "transition":  "過渡期",
    "unknown":     "未知",
}

DIRECTION_LABELS: dict[str, str] = {
    "improving":     "動能改善",
    "flat":          "動能持平",
    "deteriorating": "動能轉弱",
}

PLAYBOOK: dict[str, dict] = {
    "strong_bull": {
        "posture": "持股水位可高於長期基準",
        "actions": ["順勢持有景氣循環與高 beta 族群", "拉回視為加碼機會，而非轉向訊號",
                    "開始留意擴散比例見頂與信用利差回升"],
    },
    "bull": {
        "posture": "維持或略高於長期基準",
        "actions": ["核心持股不動，新增部位分批布局", "優先選擇基本面與趨勢同向的族群",
                    "確認訊號：下一期擴散比例能否站穩 75%"],
    },
    "neutral": {
        "posture": "回到長期基準，降低主動押注",
        "actions": ["減少單邊押注，保留現金彈性", "以多空支柱的差異做族群配對，而非押方向",
                    "等待「翻多／翻空還差幾項」收斂再行動"],
    },
    "bear": {
        "posture": "持股水位低於長期基準",
        "actions": ["降低高 beta 與高槓桿部位", "提高現金、優質債與防禦型配置",
                    "反彈先視為調節機會，等待擴散比例回升確認"],
    },
    "strong_bear": {
        "posture": "以資本保全為優先",
        "actions": ["明顯降低股票曝險，避免攤平", "偏重現金與長天期優質債",
                    "留意信用利差見頂、PMI 落底等築底訊號"],
    },
    "unknown": {
        "posture": "暫不依本框架做決策",
        "actions": ["先確認排程器與資料來源是否正常", "補齊指標後再參考判讀結果"],
    },
}

PILLARS: dict[str, dict] = {
    "A": {"name": "需求動能", "desc": "PMI、新訂單", "page": "demand"},
    "B": {"name": "貿易流量", "desc": "出口、零售、領先指標", "page": "demand"},
    "C": {"name": "金融條件", "desc": "通膨、信用、利率、貨幣", "page": "liquidity"},
    "D": {"name": "市場內部", "desc": "波動、匯率、銅、輪動", "page": "equity"},
}

# Monthly prints that define "the latest month of data" for momentum.
MOMENTUM_ANCHOR_KEYS = ("US_PMI", "TW_PMI", "CN_PMI", "EU_PMI", "TW_EXP_YOY", "KR_EXP_YOY",
                        "US_RETAIL_YOY", "US_NEW_ORDERS_YOY")

CLOCK_GROWTH_KEYS = ("US_PMI", "TW_PMI", "CN_PMI", "EU_PMI", "US_NEW_ORDERS_YOY", "KR_EXP_YOY")
CLOCK_INFLATION_KEYS = ("US_CORE_CPI_YOY", "US_CORE_PPI_YOY", "CN_PPI_YOY")

CLOCK_QUADRANTS: dict[str, dict] = {
    "recovery": {
        "label": "復甦", "desc": "成長回升、通膨降溫",
        "favoured": "股票，尤其循環與成長股", "avoid": "現金、原物料",
    },
    "overheat": {
        "label": "過熱", "desc": "成長回升、通膨升溫",
        "favoured": "原物料、能源、價值循環股", "avoid": "長天期債券",
    },
    "stagflation": {
        "label": "停滯性通膨", "desc": "成長放緩、通膨升溫",
        "favoured": "現金、防禦型股票、抗通膨資產", "avoid": "高 beta 股票、長債",
    },
    "reflation": {
        "label": "衰退式降溫", "desc": "成長放緩、通膨降溫",
        "favoured": "優質長債、防禦成長股", "avoid": "景氣循環股、原物料",
    },
}


# ── Stance ────────────────────────────────────────────────────────────────────

def classify_momentum(delta_pp: float | None) -> str:
    """Bucket a change in diffusion. Boundary counts as a real move."""
    if delta_pp is None:
        return "flat"
    if delta_pp >= MOMENTUM_PP:
        return "improving"
    if delta_pp <= -MOMENTUM_PP:
        return "deteriorating"
    return "flat"


def classify_stance(regime: str, direction: str) -> dict:
    """Level + direction → stance. An unknown regime never produces a view."""
    if regime not in _LEVEL:
        return {"key": "unknown", "score": None, "phase": "unknown", **STANCES["unknown"]}
    score = _LEVEL[regime] + _DIRECTION[direction]
    key = _SCORE_TO_STANCE[score]
    return {"key": key, "score": score, "phase": _PHASE[(regime, direction)], **STANCES[key]}


def flip_distance(gmi: dict) -> dict:
    """How many more indicators must change side for the raw regime to change."""
    valid, score = gmi["valid_count"], gmi["score"]
    if not valid:
        return {"to_green": None, "to_red": None}
    green_score = math.ceil(valid * REGIME_GREEN_PCT / 100)
    red_score = math.floor(valid * REGIME_RED_PCT / 100)
    return {"to_green": max(0, green_score - score), "to_red": max(0, score - red_score)}


# ── Risk alerts ───────────────────────────────────────────────────────────────

_LEVEL_RANK = {"alert": 0, "watch": 1}


def _current_months(data: dict, key: str, now: pd.Timestamp) -> pd.DataFrame | None:
    """Month-end series, or None when its newest point is too old to alert on.

    A warning reads as "this is happening now", so a dead feed must not raise one.
    """
    df = data.get(key)
    if not isinstance(df, pd.DataFrame):
        return None
    months = _to_monthly(df)
    if months.empty:
        return None
    age = (now - months.iloc[-1]["date"]).days
    return None if age > STALE_DAYS[REGISTRY[key].freq] else months


def _latest_value(data: dict, key: str, now: pd.Timestamp) -> float | None:
    months = _current_months(data, key, now)
    return None if months is None else float(months.iloc[-1]["value"])


def _current_days(data: dict, key: str, now: pd.Timestamp) -> pd.DataFrame | None:
    """Raw daily rows (date-sorted, NaN dropped), or None when the feed is stale."""
    df = data.get(key)
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    days = (df[["date", "value"]].assign(date=lambda f: pd.to_datetime(f["date"]))
            .dropna().sort_values("date").drop_duplicates("date", keep="last"))
    if days.empty or (now - days.iloc[-1]["date"]).days > STALE_DAYS[REGISTRY[key].freq]:
        return None
    return days


def _vixtwn_alerts(data: dict, now: pd.Timestamp, add) -> None:
    """Taiwan VIX: level tiers, a one-day jump, and stress beyond the US VIX."""
    tw = _current_days(data, "VIXTWN", now)
    if tw is None:
        return
    level = float(tw.iloc[-1]["value"])
    if level >= 35:
        add("VIXTWN", "alert", f"台指 VIX {level:.1f}", "台股選擇權恐慌升溫，避免追價並控制部位")
    elif level >= 25:
        add("VIXTWN", "watch", f"台指 VIX {level:.1f}", "台股波動高於常態，留意是否續升破 35")

    if len(tw) >= 2:
        prev = float(tw.iloc[-2]["value"])
        jump = (level / prev - 1) * 100 if prev else 0.0
        if jump >= 15:
            add("VIXTWN_JUMP", "watch", f"台指 VIX 單日 {jump:+.0f}%",
                "波動率急升，常伴隨突發事件，隔日開盤留意")

    # Taipei closes ~14 h before New York, so compare on the last shared date.
    us = _current_days(data, "VIX", now)
    if us is not None:
        both = tw.merge(us, on="date", suffixes=("_tw", "_us"))
        if not both.empty:
            gap = float(both.iloc[-1]["value_tw"] - both.iloc[-1]["value_us"])
            if gap >= 8:
                add("VIXTWN_GAP", "watch", f"台指 VIX 高於美 VIX {gap:.1f}",
                    "台股出現區域性恐慌（非全球同步），留意地緣或本地事件")


def _pct_change_3m(data: dict, key: str, now: pd.Timestamp) -> float | None:
    months = _current_months(data, key, now)
    if months is None or len(months) <= LOOKBACK_MONTHS:
        return None
    old = float(months.iloc[-(LOOKBACK_MONTHS + 1)]["value"])
    return None if old == 0 else (float(months.iloc[-1]["value"]) / old - 1) * 100


def risk_alerts(data: dict, now: pd.Timestamp | None = None) -> list[dict]:
    """Threshold-based warnings, most severe first. Calm markets return []."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    alerts: list[dict] = []

    def add(key: str, level: str, title: str, message: str) -> None:
        alerts.append({"key": key, "level": level, "title": title, "message": message})

    vix = _latest_value(data, "VIX", now)
    if vix is not None and vix >= 30:
        add("VIX", "alert", f"VIX {vix:.1f}", "市場進入壓力區，波動放大時避免追價")
    elif vix is not None and vix >= 20:
        add("VIX", "watch", f"VIX {vix:.1f}", "波動高於常態，留意是否續升破 30")

    _vixtwn_alerts(data, now, add)

    hy = _latest_value(data, "HY_SPREAD", now)
    if hy is not None and hy >= 500:
        add("HY_SPREAD", "alert", f"HY 利差 {hy:.0f} bps", "信用市場定價衰退風險，股市常滯後反映")
    elif hy is not None and hy >= 400:
        add("HY_SPREAD", "watch", f"HY 利差 {hy:.0f} bps", "信用條件轉緊，觀察是否續擴")

    curve = _latest_value(data, "T10Y3M", now)
    if curve is not None and curve < 0:
        add("T10Y3M", "alert", f"10Y-3M {curve:+.2f} pp", "殖利率曲線倒掛，歷史上領先美國衰退")

    pmi = _latest_value(data, "US_PMI", now)
    if pmi is not None and pmi < 48:
        add("US_PMI", "watch", f"美國 PMI {pmi:.1f}", "製造業明顯收縮")

    dollar = _pct_change_3m(data, "DXY", now)
    if dollar is not None and dollar >= 3:
        add("DXY", "watch", f"美元 3M {dollar:+.1f}%", "美元急升壓縮新興市場資金空間")

    real = _latest_value(data, "US_REAL_RATE", now)
    if real is not None and real >= 2.5:
        add("US_REAL_RATE", "watch", f"實質利率 {real:.2f}%", "高折現率壓抑成長股估值")

    return sorted(alerts, key=lambda a: _LEVEL_RANK[a["level"]])


# ── Growth / inflation clock ──────────────────────────────────────────────────

def _composite_momentum(data: dict, keys: tuple[str, ...]) -> pd.Series | None:
    """Average 3M change across the series, each scaled by its own typical move.

    Direction must come from the change itself. A rolling z-score of the level
    falls during a sustained rise (the mean catches up), which reported strong,
    steady expansions as "growth slowing".
    """
    frames = []
    for key in keys:
        df = data.get(key)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        months = _to_monthly(df)
        if len(months) < CLOCK_MIN_MONTHS:
            continue
        s = months.set_index(months["date"].dt.to_period("M"))["value"].astype(float)
        change = s.diff(LOOKBACK_MONTHS)
        scale = change.rolling(60, min_periods=CLOCK_MIN_MONTHS - LOOKBACK_MONTHS).std()
        frames.append((change / scale.replace(0, np.nan)).rename(key))
    if not frames:
        return None
    return pd.concat(frames, axis=1).mean(axis=1, skipna=True).dropna()


def investment_clock(data: dict) -> dict | None:
    """Locate the economy on the growth × inflation clock by 3M momentum."""
    growth = _composite_momentum(data, CLOCK_GROWTH_KEYS)
    inflation = _composite_momentum(data, CLOCK_INFLATION_KEYS)
    if growth is None or inflation is None:
        return None
    joined = pd.concat([growth.rename("growth"), inflation.rename("inflation")],
                       axis=1, join="inner").dropna()
    if joined.empty:
        return None

    latest = joined.iloc[-1]
    growth_up, inflation_up = bool(latest["growth"] > 0), bool(latest["inflation"] > 0)
    key = {
        (True, False): "recovery", (True, True): "overheat",
        (False, True): "stagflation", (False, False): "reflation",
    }[(growth_up, inflation_up)]

    trail = joined.tail(CLOCK_TRAIL_MONTHS).reset_index(names="period")
    trail["date"] = trail["period"].dt.to_timestamp()
    return {
        "key": key,
        **CLOCK_QUADRANTS[key],
        "growth_delta": float(latest["growth"]),
        "inflation_delta": float(latest["inflation"]),
        "trail": trail[["date", "growth", "inflation"]],
    }


# ── Pillars, evidence, changes ────────────────────────────────────────────────

def _pillar_rows(gmi: dict, gmi_prev: dict) -> list[dict]:
    def stats(result: dict, group: str) -> tuple[int, int]:
        sigs = [s for s in result["signals"] if s["group"] == group and s["has_data"]]
        return sum(s["score"] for s in sigs), len(sigs)

    rows = []
    for key, meta in PILLARS.items():
        bull, valid = stats(gmi, key)
        prev_bull, prev_valid = stats(gmi_prev, key)
        pct = round(bull / valid * 100, 1) if valid else None
        prev_pct = round(prev_bull / prev_valid * 100, 1) if prev_valid else None
        delta = None if pct is None or prev_pct is None else round(pct - prev_pct, 1)
        if pct is None:
            tone = "neutral"
        elif pct >= REGIME_GREEN_PCT:
            tone = "bullish"
        elif pct <= REGIME_RED_PCT:
            tone = "bearish"
        else:
            tone = "neutral"
        rows.append({"key": key, **meta, "bull": bull, "valid": valid, "pct": pct,
                     "delta": delta, "tone": tone})
    return rows


def _signal_changes(gmi: dict, gmi_prev: dict) -> list[dict]:
    before = {s["id"]: s for s in gmi_prev["signals"] if s["has_data"]}
    changes = []
    for sig in gmi["signals"]:
        prev = before.get(sig["id"])
        if prev is None or not sig["has_data"] or prev["score"] == sig["score"]:
            continue
        changes.append({"id": sig["id"], "name": sig["name"], "raw": sig["raw"],
                        "to": "bull" if sig["score"] else "bear"})
    return changes


def _conviction(gmi: dict, stance: dict, pillars: list[dict], stale_share: float) -> str:
    """Three independent checks: coverage, freshness, pillar agreement."""
    if stance["key"] == "unknown":
        return "low"
    points = int(gmi["valid_count"] >= MIN_VALID) + int(stale_share <= 0.2)
    if stance["score"] != 0:
        wanted = "bullish" if stance["score"] > 0 else "bearish"
        known = [p for p in pillars if p["pct"] is not None]
        agree = sum(p["tone"] == wanted for p in known)
        points += int(bool(known) and agree / len(known) >= 0.5)
    return {3: "high", 2: "medium"}.get(points, "low")


CONVICTION_LABELS = {"high": "高", "medium": "中", "low": "低"}
CONVICTION_RANK = {"low": 0, "medium": 1, "high": 2}


def _headline(stance: dict, gmi: dict, direction: str) -> str:
    if stance["key"] == "unknown":
        return f"資料不足：目前僅 {gmi['valid_count']} 項指標有資料，暫不形成多空判斷。"
    return (f"總經訊號{stance['label']}：{gmi['score']}/{gmi['valid_count']} 項指標偏多"
            f"（擴散 {gmi['diffusion']:.0f}%），{DIRECTION_LABELS[direction]}。")


def _comparison_date(data: dict, now: pd.Timestamp) -> pd.Timestamp:
    """Month-end LOOKBACK_MONTHS before the newest monthly print.

    Anchoring on the calendar would shorten the window: on Nov 2 the newest PMI is
    October, and "three months ago" by the clock reaches only August's print.
    """
    latest = [pd.Timestamp(data[key]["date"].max()) for key in MOMENTUM_ANCHOR_KEYS
              if isinstance(data.get(key), pd.DataFrame) and not data[key].empty]
    anchor = max(latest) if latest else now
    return (anchor.to_period("M") - LOOKBACK_MONTHS).end_time.normalize()


def _settled_regime(history: pd.DataFrame | None, now: pd.Timestamp,
                    raw_regime: str) -> tuple[str, str | None]:
    """Confirmed regime from finished months, plus any change still awaiting confirmation.

    The running month is a partial reading: a couple of VIX days must not supply
    the second month of a two-month confirmation.
    """
    if raw_regime == "unknown":
        return "unknown", None
    if history is None or history.empty or "confirmed_regime" not in history.columns:
        return raw_regime, None
    running = pd.Timestamp(history.iloc[-1]["date"]).to_period("M") >= now.to_period("M")
    finished = history.iloc[:-1] if running and len(history) > 1 else history
    regime = finished.iloc[-1]["confirmed_regime"]
    return regime, (raw_regime if raw_regime != regime else None)


def compute_market_view(data: dict, history: pd.DataFrame | None = None,
                        now: pd.Timestamp | None = None) -> dict:
    """Build the complete investor read from the macro data dict.

    Args:
        data:    Same dict the dashboard loads (series keyed by name).
        history: Optional build_macro_index_history() output. When given, the
                 two-period confirmed regime sets the level, so one noisy month
                 cannot flip the verdict.
        now:     Clock override for tests.
    """
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()

    gmi = compute_macro_index(data)
    gmi_prev = compute_macro_index(_slice_data_as_of(data, _comparison_date(data, now)))

    momentum_pp = (round(gmi["diffusion"] - gmi_prev["diffusion"], 1)
                   if gmi_prev["valid_count"] else None)
    direction = classify_momentum(momentum_pp)

    regime, pending_regime = _settled_regime(history, now, gmi["regime"])

    stance = classify_stance(regime, direction)
    pillars = _pillar_rows(gmi, gmi_prev)

    radar = build_radar(data, now)
    tw_warning = evaluate_tw_warning(data, now=now)
    alerts = risk_alerts(data, now)
    if tw_warning.get("available") and tw_warning["level"] != "green":
        info = tw_warning["info"]
        alerts.insert(0, {
            "key": "TW_WARNING", "level": "alert" if tw_warning["level"] in ("orange", "red") else "watch",
            "title": f"台股預警{info['label']}（{tw_warning['count']}/{tw_warning['n_signals']} 項）",
            "message": info["action"],
        })
    stale_count = int(radar["stale"].sum()) if not radar.empty else 0
    stale_share = stale_count / len(radar) if len(radar) else 0.0

    return {
        "as_of":          gmi["as_of"],
        "gmi":            gmi,
        "gmi_prev":       gmi_prev,
        "regime":         regime,
        "regime_label":   REGIME_LABELS.get(regime, REGIME_LABELS["unknown"]),
        "pending_regime": pending_regime,
        "momentum_pp":    momentum_pp,
        "direction":      direction,
        "stance":         stance,
        "phase_label":    PHASES[stance["phase"]],
        "conviction":     _conviction(gmi, stance, pillars, stale_share),
        "headline":       _headline(stance, gmi, direction),
        "pillars":        pillars,
        "bull_case":      [s for s in gmi["signals"] if s["has_data"] and s["score"] == 1],
        "bear_case":      [s for s in gmi["signals"] if s["has_data"] and s["score"] == 0],
        "missing":        [s for s in gmi["signals"] if not s["has_data"]],
        "changes":        _signal_changes(gmi, gmi_prev),
        "flip":           flip_distance(gmi),
        "alerts":         alerts,
        "tw_warning":     tw_warning,
        "clock":          investment_clock(data),
        "playbook":       PLAYBOOK[stance["key"]],
        "radar":          radar,
        "breadth":        breadth(radar),
        "stale_count":    stale_count,
    }


def theme_brief(view: dict, theme: str) -> dict:
    """One-line conclusion for a detail page, derived from the trend radar."""
    radar = view["radar"]
    rows = radar[radar["theme"] == theme] if not radar.empty else radar
    label = THEMES[theme]
    if rows.empty:
        return {"theme": theme, "label": label, "total": 0, "bull": 0, "bear": 0, "neutral": 0,
                "tone": "neutral", "summary": f"{label}面目前沒有足夠資料。"}

    bull = int((rows["signal"] == "bullish").sum())
    bear = int((rows["signal"] == "bearish").sum())
    neutral = len(rows) - bull - bear
    tone = "bullish" if bull > bear else "bearish" if bear > bull else "neutral"
    verdict = {"bullish": "偏多", "bearish": "偏空", "neutral": "分歧"}[tone]
    summary = (f"{label}面{verdict}：{len(rows)} 項指標中 {bull} 項趨勢向好、"
               f"{bear} 項轉差、{neutral} 項持平。")
    return {"theme": theme, "label": label, "total": len(rows), "bull": bull, "bear": bear,
            "neutral": neutral, "tone": tone, "summary": summary}


# ── Historical evidence ───────────────────────────────────────────────────────

def regime_evidence(stats: pd.DataFrame | None, regime: str, market: str = "TWII",
                    horizons: tuple[int, ...] = (3, 6, 12)) -> list[dict]:
    """Forward returns after this regime, against the all-period baseline.

    Monthly observations of a 12M return overlap heavily, so `n` overstates the
    evidence. `n_eff` counts roughly independent windows (n / horizon) and `thin`
    flags when that is too few to lean on.
    """
    if stats is None or stats.empty:
        return []
    rows = []
    subset = stats[stats["market"] == market]
    for horizon in horizons:
        hit = subset[(subset["regime"] == regime) & (subset["horizon"] == horizon)]
        base = subset[(subset["regime"] == "all") & (subset["horizon"] == horizon)]
        if hit.empty or base.empty or hit.iloc[0]["n"] == 0:
            continue
        row, ref = hit.iloc[0], base.iloc[0]
        n = int(row["n"])
        n_eff = max(1, n // horizon)
        rows.append({
            "market":   market,
            "horizon":  horizon,
            "median":   float(row["median"]),
            "win_rate": float(row["win_rate"]),
            "p10":      float(row["p10"]),
            "edge":     float(row["median"]) - float(ref["median"]),
            "n":        n,
            "n_eff":    n_eff,
            "thin":     n_eff < MIN_EFFECTIVE_N,
        })
    return rows


# ── Written brief ─────────────────────────────────────────────────────────────

def build_brief(view: dict) -> str:
    """Markdown briefing an investor can save or forward."""
    gmi, stance, flip = view["gmi"], view["stance"], view["flip"]
    lines = [f"# 總經多空簡報（資料基準 {view['as_of']}）", "",
             "## 結論", "",
             f"**{stance['label']}**｜{view['phase_label']}｜"
             f"信心 {CONVICTION_LABELS[view['conviction']]}", "",
             view["headline"], ""]

    if view["momentum_pp"] is not None:
        lines += [f"- 擴散比例較 {LOOKBACK_MONTHS} 個月前 {view['momentum_pp']:+.1f} 個百分點", ]
    if flip["to_green"] is not None:
        lines += [f"- 再 {flip['to_green']} 項轉多進入擴張區；"
                  f"再 {flip['to_red']} 項轉空落入收縮區"]

    lines += ["", "## 四大支柱", ""]
    for p in view["pillars"]:
        value = f"{p['bull']}/{p['valid']}（{p['pct']:.0f}%）" if p["pct"] is not None else "無資料"
        lines.append(f"- {p['name']}：{value}")

    lines += ["", "## 多方論據", ""]
    lines += [f"- {s['name']}：{s['raw']}" for s in view["bull_case"]] or ["- 無"]
    lines += ["", "## 空方論據", ""]
    lines += [f"- {s['name']}：{s['raw']}" for s in view["bear_case"]] or ["- 無"]

    lines += ["", "## 操作框架", "", f"**{view['playbook']['posture']}**", ""]
    lines += [f"- {a}" for a in view["playbook"]["actions"]]

    clock = view["clock"]
    if clock:
        lines += ["", f"成長／通膨時鐘：{clock['label']}（{clock['desc']}）。"
                      f"相對有利：{clock['favoured']}；相對不利：{clock['avoid']}。"]

    lines += ["", "## 風險提示", ""]
    lines += [f"- {a['title']}：{a['message']}" for a in view["alerts"]] or ["- 目前無觸發中的風險警示"]
    if view["stale_count"]:
        lines.append(f"- {view['stale_count']} 項指標資料過期，請留意判讀時效")

    lines += ["", "---", "", f"{DISCLAIMER}（評分涵蓋 {gmi['valid_count']}/{TOTAL_INDICATORS} 項指標）"]
    return "\n".join(lines)
