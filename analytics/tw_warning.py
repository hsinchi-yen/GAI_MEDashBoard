"""Taiwan early-warning layer: daily chip / sentiment signals and a composite light.

Separate from the GMI on purpose. GMI is monthly and macro; this layer reacts to
the leverage, breadth and flow shifts that build up within one or two months
before a Taiwan sell-off (the 2026-10 post-mortem). It never feeds the GMI, so
the GMI's 10-year back-test is unaffected.

Every signal is computed as a full daily history over Taiwan trading days, so
the page and the back-test read the same numbers. US series are aligned to the
last US session *before* each Taiwan day: New York closes after Taipei, so a
Taiwan close cannot have seen the same-date US print.

Pure pandas; thresholds come only from ``tw_warning_config``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from analytics.tw_warning_config import CONFIG, TwWarningConfig

DISCLAIMER = ("燈號是分段減碼的參考，不是買賣訊號：回測顯示單一訊號的預測力接近基本機率，"
              "多項同時成立也只是把風險提高一些。")

LEVELS = ("green", "yellow", "orange", "red")
LEVEL_INFO: dict[str, dict] = {
    "green":  {"label": "綠燈", "tone": "bullish", "action": "維持原本持股"},
    "yellow": {"label": "黃燈", "tone": "neutral", "action": "停止加碼，高波動股減碼 10%～20%"},
    "orange": {"label": "橙燈", "tone": "bearish", "action": "持股降到 7 成"},
    "red":    {"label": "紅燈", "tone": "bearish", "action": "持股降到 5 成"},
}

# Data keys (as load_all_from_db names them) → frame column.
TW_KEYS = {"close": "TAIEX_DAILY", "adv": "TW_ADV", "dec": "TW_DEC",
           "pct_ma20": "TW_PCT_MA20", "pct_ma60": "TW_PCT_MA60",
           "turnover": "TW_TURNOVER", "fini": "TW_FINI_NET", "fut_oi": "TW_FINI_FUT_OI",
           "margin": "TW_MARGIN", "vixtwn": "VIXTWN", "tsmc": "TSMC_DAILY",
           "whale": "TW_WHALE_EXIT"}
US_KEYS = {"dgs10": "US_10Y_NOMINAL", "dxy": "DXY_ICE", "twd": "TWD_USD",
           "vix_us": "VIX", "sox": "SOX_DAILY"}
FLOW_COLUMNS = ("fini",)          # daily flows: a missing day is unknown, never carried


@dataclass(frozen=True)
class Signal:
    id: str
    name: str
    group: str
    inputs: tuple[str, ...]


SIGNALS: tuple[Signal, ...] = (
    Signal("W1", "利率急升", "總經壓力", ("dgs10",)),
    Signal("W2", "美元／台幣壓力", "總經壓力", ("dxy", "twd")),
    Signal("W3", "寬度背離", "市場內部", ("close", "adv", "dec")),
    Signal("W4", "量縮創高", "市場內部", ("close", "turnover")),
    Signal("W5", "外資現貨背離", "籌碼", ("close", "fini")),
    Signal("W6", "外資期貨空單加碼", "籌碼", ("fut_oi",)),
    Signal("W7", "融資過熱", "籌碼", ("close", "margin")),
    Signal("W8", "台指 VIX 同漲", "情緒", ("close", "vixtwn")),
    Signal("W9", "超買", "情緒", ("close",)),
    Signal("W10", "千張大戶退場家數", "籌碼", ("whale",)),
)
REBUY = (("B1", "台指 VIX 恐慌後回落"), ("B2", "融資退場"), ("B3", "外資期貨回補"))


# ── alignment ─────────────────────────────────────────────────────────────────

def _series(data: dict, key: str) -> pd.Series | None:
    df = data.get(key)
    if not isinstance(df, pd.DataFrame) or df.empty or "value" not in df:
        return None
    # One datetime unit for every series, or merge_asof refuses to align them.
    s = (df[["date", "value"]]
         .assign(date=lambda f: pd.to_datetime(f["date"]).dt.normalize().astype("datetime64[ns]"))
         .dropna().drop_duplicates("date", keep="last").set_index("date")["value"].astype(float))
    return s.sort_index() if not s.empty else None


def build_frame(data: dict) -> tuple[pd.DataFrame, dict[str, pd.Timestamp]]:
    """Daily frame on Taiwan trading days, plus each input's last real date."""
    close = _series(data, TW_KEYS["close"])
    if close is None:
        return pd.DataFrame(), {}
    idx = close.index
    frame = pd.DataFrame(index=idx)
    last: dict[str, pd.Timestamp] = {}
    for col, key in TW_KEYS.items():
        s = _series(data, key)
        if s is None:
            frame[col] = np.nan
            continue
        last[col] = s.index[-1]
        aligned = s.reindex(idx)
        # Levels survive a missing print for a few days; flows do not.
        frame[col] = aligned if col in FLOW_COLUMNS else aligned.ffill(limit=3)
    left = pd.DataFrame({"date": idx})
    for col, key in US_KEYS.items():
        s = _series(data, key)
        if s is None:
            frame[col] = np.nan
            continue
        last[col] = s.index[-1]
        right = s.rename("v").rename_axis("date").reset_index()
        merged = pd.merge_asof(left, right, on="date", direction="backward",
                               allow_exact_matches=False)
        frame[col] = merged["v"].to_numpy()
    return frame, last


def rsi(close: pd.Series, period: int = 14, method: str = "sma") -> pd.Series:
    """RSI with simple-average (Cutler, ``sma``) or Wilder (``wilder``) smoothing."""
    delta = close.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    if method == "wilder":
        gain = up.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        loss = down.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    else:
        gain = up.rolling(period, min_periods=period).mean()
        loss = down.rolling(period, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def _flag(cond: pd.Series, *inputs: pd.Series) -> pd.Series:
    """1.0 / 0.0, NaN where any input needed for the test is missing."""
    known = pd.concat(inputs, axis=1).notna().all(axis=1)
    return cond.astype(float).where(known)


# ── signal history ────────────────────────────────────────────────────────────

def signal_history(frame: pd.DataFrame, cfg: TwWarningConfig = CONFIG) -> pd.DataFrame:
    """Per day: W1..W10 as 1/0/NaN, and the measured value behind each."""
    f = frame
    out = pd.DataFrame(index=f.index)
    close = f["close"]

    v1 = f["dgs10"].diff(cfg.rate_window)
    out["W1"], out["W1_v"] = _flag(v1 >= cfg.rate_rise_pp, v1), v1

    dxy = f["dxy"].pct_change(cfg.fx_window, fill_method=None) * 100
    twd = f["twd"].pct_change(cfg.fx_window, fill_method=None) * 100
    w2 = (dxy >= cfg.dxy_rise_pct) | (twd >= cfg.twd_depr_pct)
    known2 = dxy.notna() | twd.notna()
    out["W2"] = w2.astype(float).where(known2)
    out["W2_v"], out["W2_v2"] = dxy, twd

    ret1 = close.pct_change(fill_method=None) * 100
    div_day = _flag((ret1 >= cfg.breadth_index_up_pct) & (f["dec"] > f["adv"]), ret1, f["adv"], f["dec"])
    v3 = div_day.rolling(cfg.breadth_lookback, min_periods=cfg.breadth_lookback // 2).sum()
    out["W3"], out["W3_v"] = _flag(v3 >= cfg.breadth_div_days, v3), v3
    out["div_day"] = div_day

    high = close.rolling(cfg.near_high_window, min_periods=cfg.near_high_window).max()
    near_high = close >= high * (1 - cfg.near_high_pct / 100)
    vol = f["turnover"].rolling(cfg.vol_ma, min_periods=cfg.vol_ma).mean()
    ref = vol.rolling(cfg.vol_ref_window, min_periods=cfg.vol_ref_window // 2).max()
    v4 = vol / ref
    out["W4"], out["W4_v"] = _flag(near_high & (v4 < cfg.vol_ratio_max), high, v4), v4

    fini = f["fini"].rolling(cfg.fini_window, min_periods=int(cfg.fini_window * 0.8)).sum()
    ret20 = close.pct_change(cfg.fini_window, fill_method=None)
    out["W5"] = _flag((fini <= -cfg.fini_net_sell_ntd_bn) & (ret20 > 0), fini, ret20)
    out["W5_v"] = fini

    v6 = f["fut_oi"].diff(cfg.fut_window)          # more negative = shorts added
    out["W6"], out["W6_v"] = _flag(v6 <= -cfg.fut_short_add_lots, v6), v6

    m = f["margin"]
    excess = (m.pct_change(cfg.margin_window, fill_method=None)
              - close.pct_change(cfg.margin_window, fill_method=None)) * 100
    prior_high = m.shift(1).rolling(cfg.margin_high_window, min_periods=cfg.margin_high_window).max()
    above_high = m > prior_high
    w7 = (excess >= cfg.margin_excess_pp) | (above_high & cfg.margin_use_high)
    out["W7"] = w7.astype(float).where(excess.notna())
    out["W7_v"], out["W7_high"] = excess, above_high.astype(float).where(prior_high.notna())

    high20 = close.rolling(cfg.vix_near_high_window, min_periods=cfg.vix_near_high_window).max()
    v8 = f["vixtwn"].diff(cfg.vix_window)
    out["W8"] = _flag((close >= high20 * (1 - cfg.vix_near_high_pct / 100)) & (v8 >= cfg.vix_rise_pts),
                      high20, v8)
    out["W8_v"] = v8

    v9 = rsi(close, cfg.rsi_period, cfg.rsi_method)
    out["W9"], out["W9_v"] = _flag(v9 >= cfg.rsi_overbought, v9), v9

    whale = f["whale"]
    # A zero base share makes the change infinite, not informative.
    base10 = whale.shift(cfg.whale_exit_window)
    v10 = ((whale / base10 - 1) * 100).where(base10 > 0)
    out["W10"], out["W10_v"] = _flag(v10 >= cfg.whale_exit_rise_pct, v10), v10

    # Trend and re-entry.
    out["ma_fast"] = close.rolling(cfg.trend_fast_ma, min_periods=cfg.trend_fast_ma).mean()
    out["ma_slow"] = close.rolling(cfg.trend_slow_ma, min_periods=cfg.trend_slow_ma).mean()
    peak = f["vixtwn"].rolling(cfg.vix_peak_window, min_periods=1).max()
    out["B1"] = _flag((peak >= cfg.vix_panic) & (f["vixtwn"] <= peak - cfg.vix_retreat_pts),
                      f["vixtwn"])
    m_high = m.rolling(cfg.margin_flush_window, min_periods=cfg.margin_flush_window // 2).max()
    out["B2"] = _flag(m <= m_high * (1 - cfg.margin_flush_pct / 100), m_high)
    cover = f["fut_oi"].diff(cfg.fut_cover_window)
    out["B3"] = _flag(cover >= cfg.fut_cover_lots, cover)
    return out


def active_signals(frame: pd.DataFrame) -> list[Signal]:
    """W10 only counts once its feed exists at all; the others always count."""
    return [s for s in SIGNALS if s.id != "W10" or frame["whale"].notna().any()]


def raw_levels(hist: pd.DataFrame, close: pd.Series, n_signals: int,
               cfg: TwWarningConfig = CONFIG, ids: list[str] | None = None) -> pd.DataFrame:
    ids = ids or [s.id for s in SIGNALS[:n_signals]]
    # A precursor counts for `signal_memory` days after it last fired.
    count = hist[ids].fillna(0).rolling(cfg.signal_memory, min_periods=1).max().sum(axis=1)
    watch_n, reduce_n = cfg.level_counts(n_signals)
    red = (close < hist["ma_slow"]) & (hist["ma_fast"] < hist["ma_slow"])
    orange = (count >= reduce_n) & (close < hist["ma_fast"])
    yellow = count >= watch_n
    level = np.select([red, orange, yellow], [3, 2, 1], default=0)
    return pd.DataFrame({"count": count.astype(int), "raw": level}, index=hist.index)


def apply_hysteresis(raw: pd.Series, confirm: int, release: int) -> pd.Series:
    """Move up after ``confirm`` days above, down after ``release`` days below."""
    values = raw.to_numpy()
    out = np.zeros(len(values), dtype=int)
    cur = 0
    for i, r in enumerate(values):
        if r > cur and i + 1 >= confirm:
            window = values[i + 1 - confirm:i + 1]
            if (window > cur).all():
                cur = int(window.min())
        elif r < cur and i + 1 >= release:
            window = values[i + 1 - release:i + 1]
            if (window < cur).all():
                cur = int(window.max())
        out[i] = cur
    return pd.Series(out, index=raw.index)


def exposure_for(level: int, cfg: TwWarningConfig = CONFIG) -> float:
    return (1.0, cfg.exposure_watch, cfg.exposure_reduce, cfg.exposure_defend)[level]


def level_history(data: dict, cfg: TwWarningConfig = CONFIG) -> pd.DataFrame:
    """Daily count, raw and confirmed level, exposure, and every signal column."""
    frame, _ = build_frame(data)
    if frame.empty:
        return pd.DataFrame()
    hist = signal_history(frame, cfg)
    sigs = active_signals(frame)
    lv = raw_levels(hist, frame["close"], len(sigs), cfg, [s.id for s in sigs])
    lv["level"] = apply_hysteresis(lv["raw"], cfg.confirm_days, cfg.release_days)
    lv["exposure"] = lv["level"].map(lambda x: exposure_for(int(x), cfg))
    return pd.concat([frame[["close"]], hist, lv], axis=1)


# ── current reading ───────────────────────────────────────────────────────────

def _fmt(v, spec: str) -> str:
    return "—" if v is None or pd.isna(v) else format(v, spec)


def _describe(sig: Signal, row: pd.Series, cfg: TwWarningConfig) -> tuple[str, str]:
    """(measured value, trigger rule) in words."""
    if sig.id == "W1":
        return (f"10Y {cfg.rate_window} 日 {_fmt(row['W1_v'], '+.2f')} pp",
                f"≥ +{cfg.rate_rise_pp:.2f} pp")
    if sig.id == "W2":
        return (f"DXY {_fmt(row['W2_v'], '+.1f')}%、USD/TWD {_fmt(row['W2_v2'], '+.1f')}%（{cfg.fx_window} 日）",
                f"DXY ≥ +{cfg.dxy_rise_pct:.1f}% 或台幣貶 ≥ {cfg.twd_depr_pct:.1f}%")
    if sig.id == "W3":
        return (f"近 {cfg.breadth_lookback} 日 {_fmt(row['W3_v'], '.0f')} 天",
                f"指數漲 ≥ {cfg.breadth_index_up_pct:.0f}% 但下跌家數較多 ≥ {cfg.breadth_div_days} 天")
    if sig.id == "W4":
        return (f"20 日均量為波段高點的 {_fmt(row['W4_v'], '.0%')}",
                f"距 {cfg.near_high_window} 日高點 ≤ {cfg.near_high_pct:.0f}% 且 < {cfg.vol_ratio_max:.0%}")
    if sig.id == "W5":
        return (f"外資 {cfg.fini_window} 日 {_fmt(row['W5_v'], '+,.0f')} 億",
                f"淨賣 ≥ {cfg.fini_net_sell_ntd_bn:,.0f} 億且指數 {cfg.fini_window} 日上漲")
    if sig.id == "W6":
        v = row["W6_v"]
        return (f"淨部位 {cfg.fut_window} 日 {_fmt(v, '+,.0f')} 口",
                f"空單加碼 ≥ {cfg.fut_short_add_lots:,.0f} 口")
    if sig.id == "W7":
        high = "，創前高" if row.get("W7_high") == 1 else ""
        return (f"融資增速超出指數 {_fmt(row['W7_v'], '+.1f')} pp{high}",
                f"≥ {cfg.margin_excess_pp:.0f} pp" + (f" 或超過 {cfg.margin_high_window} 日前高" if cfg.margin_use_high else ""))
    if sig.id == "W8":
        return (f"台指 VIX {cfg.vix_window} 日 {_fmt(row['W8_v'], '+.1f')} 點",
                f"指數近高且 VIX 升 ≥ {cfg.vix_rise_pts:.0f} 點")
    if sig.id == "W9":
        return (f"RSI {_fmt(row['W9_v'], '.0f')}", f"≥ {cfg.rsi_overbought:.0f}")
    return (f"{cfg.whale_exit_window} 日 {_fmt(row['W10_v'], '+.0f')}%",
            f"警示家數增加 ≥ {cfg.whale_exit_rise_pct:.0f}%")


def evaluate(data: dict, cfg: TwWarningConfig = CONFIG, now: pd.Timestamp | None = None) -> dict:
    """The page's reading: light, signals, gauges and re-entry progress."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now()
    frame, last = build_frame(data)
    if frame.empty or len(frame) < cfg.trend_slow_ma:
        return {"available": False}
    hist = signal_history(frame, cfg)
    sigs = active_signals(frame)
    ids = [s.id for s in sigs]

    def stale(cols) -> bool:
        dates = [last.get(c) for c in cols]
        return any(d is None or (now - d).days > cfg.stale_days for d in dates)

    # A stale input must not raise (or keep) a warning: blank it out before counting.
    counted = hist.copy()
    stale_ids = set()
    for s in sigs:
        inputs = [c for c in s.inputs if c != "twd"] if s.id == "W2" else s.inputs
        if stale(inputs):
            stale_ids.add(s.id)
            counted.loc[counted.index[-(cfg.signal_memory + cfg.release_days):], s.id] = np.nan
    lv = raw_levels(counted, frame["close"], len(sigs), cfg, ids)
    level = apply_hysteresis(lv["raw"], cfg.confirm_days, cfg.release_days)
    cur = hist.iloc[-1]
    level_key = LEVELS[int(level.iloc[-1])]

    signals = []
    for s in sigs:
        value, rule = _describe(s, cur, cfg)
        on = None if s.id in stale_ids or pd.isna(cur[s.id]) else bool(cur[s.id])
        recent = (s.id not in stale_ids
                  and bool((hist[s.id].iloc[-cfg.signal_memory:] == 1).any()))
        signals.append({"id": s.id, "name": s.name, "group": s.group, "on": on,
                        "recent": recent, "stale": s.id in stale_ids,
                        "value": value, "rule": rule})

    watch_n, reduce_n = cfg.level_counts(len(sigs))
    rebuy = [{"id": b, "name": name, "met": bool(cur[b] == 1)} for b, name in REBUY]
    close = float(frame["close"].iloc[-1])
    recent_div = list(hist.index[(hist["div_day"] == 1)][-5:].strftime("%m/%d"))
    return {
        "available":  True,
        "as_of":      frame.index[-1],
        "level":      level_key,
        "level_raw":  LEVELS[int(lv["raw"].iloc[-1])],
        "info":       LEVEL_INFO[level_key],
        "exposure":   exposure_for(int(level.iloc[-1]), cfg),
        "count":      int(lv["count"].iloc[-1]),
        "n_signals":  len(sigs),
        "thresholds": {"watch": watch_n, "reduce": reduce_n},
        "signals":    signals,
        "trend": {"close": close, "ma_fast": float(cur["ma_fast"]), "ma_slow": float(cur["ma_slow"]),
                  "below_fast": close < cur["ma_fast"], "below_slow": close < cur["ma_slow"]},
        "rebuy":      {"conditions": rebuy, "met": sum(r["met"] for r in rebuy),
                       "active": all(r["met"] for r in rebuy)},
        "gauges":     gauges(frame, cfg),
        "recent_divergence_days": recent_div,
        "raw_info":   LEVEL_INFO[LEVELS[int(lv["raw"].iloc[-1])]],
        "history":    pd.DataFrame({"close": frame["close"], "count": lv["count"], "level": level}),
        "frame":      frame,
    }


def gauges(frame: pd.DataFrame, cfg: TwWarningConfig = CONFIG) -> dict:
    """Display-only numbers (D1–D4); none of them counts toward the light."""
    f = frame
    w = cfg.macro_short_window
    last = f.iloc[-1]

    def chg(col, n, pct=True):
        s = f[col].dropna()
        if len(s) <= n:
            return None
        return float((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100) if pct else float(s.iloc[-1] - s.iloc[-1 - n])

    def rel(col):
        a, b = chg(col, cfg.rs_window), chg("close", cfg.rs_window)
        return None if a is None or b is None else a - b

    vix_gap = (None if pd.isna(last["vixtwn"]) or pd.isna(last["vix_us"])
               else float(last["vixtwn"] - last["vix_us"]))
    return {
        "pct_ma20": None if pd.isna(last["pct_ma20"]) else float(last["pct_ma20"]),
        "pct_ma60": None if pd.isna(last["pct_ma60"]) else float(last["pct_ma60"]),
        "vix_gap": vix_gap,
        "sox_rel": rel("sox"), "tsmc_rel": rel("tsmc"),
        "dgs10_chg": chg("dgs10", w, pct=False), "dxy_chg": chg("dxy", w), "twd_chg": chg("twd", w),
        "window": w,
    }
