"""Back-test of the Taiwan early-warning layer.

Three questions, each on the last ``cfg.backtest_years`` years of TAIEX closes:

1. Hit rate: after a signal, how often does the index fall ``fwd_drawdown_pct``
   or more within ``fwd_window`` trading days, versus any day at all?
2. Strategy: buy-and-hold vs. "sell everything below MA60" vs. the staged
   exposure of the light, with costs, trading at the signal day's close.
3. Events: for every peak-to-trough fall of 12 % or more, which signals were on
   before the peak, and when the light changed.

Hit rates count days, which overlap heavily; ``episodes`` collapses runs of
signal days less than ``fwd_window`` apart, which is the honest sample size.
Pure pandas, no I/O.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.tw_warning import SIGNALS, level_history
from analytics.tw_warning_config import CONFIG, TwWarningConfig

EVENT_FALL_PCT = 12.0
MIN_EPISODES = 10


def forward_drawdown(close: pd.Series, window: int) -> pd.Series:
    """Worst close over the next ``window`` days relative to today, in %."""
    fwd_min = close[::-1].rolling(window, min_periods=1).min()[::-1].shift(-1)
    out = (fwd_min / close - 1) * 100
    # The last `window` days do not have a full future yet.
    out.iloc[-window:] = np.nan
    return out


def _episodes(mask: pd.Series, gap: int) -> int:
    days = np.flatnonzero(mask.to_numpy())
    return 0 if len(days) == 0 else int(1 + (np.diff(days) > gap).sum())


def _window(hist: pd.DataFrame, cfg: TwWarningConfig, now: pd.Timestamp | None) -> pd.DataFrame:
    end = hist.index[-1] if now is None else pd.Timestamp(now)
    return hist[hist.index > end - pd.DateOffset(years=cfg.backtest_years)]


def hit_rates(hist: pd.DataFrame, cfg: TwWarningConfig = CONFIG) -> pd.DataFrame:
    """P(fall ≥ X% within N days) for each condition, with days and episodes."""
    dd = forward_drawdown(hist["close"], cfg.fwd_window)
    event = (dd <= -cfg.fwd_drawdown_pct).where(dd.notna())
    ids = [s.id for s in SIGNALS if hist[s.id].notna().any()]
    today = hist[ids].fillna(0)
    n_today = today.sum(axis=1)

    conditions: dict[str, pd.Series] = {"任何一天（基本機率）": pd.Series(True, index=hist.index)}
    for s in SIGNALS:
        if s.id in ids:
            conditions[f"{s.id} {s.name}"] = today[s.id] == 1
    chip = [i for i in ("W5", "W6", "W7") if i in ids]
    if chip:
        conditions["任一籌碼訊號（W5/W6/W7）"] = today[chip].max(axis=1) == 1
    if "W9" in ids:
        conditions["超買 + 另外 ≥ 2 項"] = (today["W9"] == 1) & (n_today - today["W9"] >= 2)
    conditions["當天 ≥ 3 項"] = n_today >= 3
    conditions["燈號 ≥ 黃"] = hist["level"] >= 1
    conditions["燈號 ≥ 橙"] = hist["level"] >= 2

    rows = []
    for name, mask in conditions.items():
        m = mask & event.notna()
        n = int(m.sum())
        hits = int((event[m] == 1).sum())
        rows.append({"條件": name, "天數": n, "獨立次數": _episodes(m, cfg.fwd_window),
                     "命中率": hits / n * 100 if n else np.nan})
    out = pd.DataFrame(rows)
    out["樣本不足"] = out["獨立次數"] < MIN_EPISODES
    return out


def _equity(close: pd.Series, exposure: pd.Series, cost: float) -> pd.Series:
    """Daily equity: today's exposure is set at today's close and earns tomorrow."""
    ret = close.pct_change(fill_method=None).fillna(0)
    held = exposure.shift(1).fillna(exposure.iloc[0])
    turnover = exposure.diff().abs().fillna(0)
    daily = held * ret - turnover * cost / 2
    return (1 + daily).cumprod()


def _stats(name: str, equity: pd.Series, exposure: pd.Series) -> dict:
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    mdd = (equity / equity.cummax() - 1).min()
    trades = int((exposure.diff().abs() > 1e-9).sum())
    return {"策略": name, "年化報酬": cagr * 100, "最大跌幅": mdd * 100,
            "平均持股": exposure.mean() * 100, "調整次數": trades}


def strategy_table(hist: pd.DataFrame, cfg: TwWarningConfig = CONFIG) -> pd.DataFrame:
    close = hist["close"]
    hold = pd.Series(1.0, index=hist.index)
    ma60 = close.rolling(cfg.trend_slow_ma, min_periods=cfg.trend_slow_ma).mean()
    ma_exit = (close >= ma60).astype(float).where(ma60.notna(), 1.0)
    staged = hist["exposure"]
    rows = [_stats("一直持有", _equity(close, hold, cfg.round_trip_cost), hold),
            _stats(f"跌破 MA{cfg.trend_slow_ma} 全部賣出", _equity(close, ma_exit, cfg.round_trip_cost), ma_exit),
            _stats("燈號分段減碼", _equity(close, staged, cfg.round_trip_cost), staged)]
    return pd.DataFrame(rows)


def drawdown_events(close: pd.Series, fall_pct: float = EVENT_FALL_PCT) -> list[dict]:
    """Peak-to-trough falls ≥ fall_pct, a new event starting after a full recovery."""
    events, peak_i, trough_i, in_fall = [], 0, 0, False
    values = close.to_numpy()
    for i in range(1, len(values)):
        if values[i] > values[peak_i]:          # new high: any fall before it is over
            if in_fall:
                events.append((peak_i, trough_i))
                in_fall = False
            peak_i = trough_i = i
        elif values[i] < values[trough_i]:
            trough_i = i
            in_fall = in_fall or (values[i] / values[peak_i] - 1) * 100 <= -fall_pct
    if in_fall:
        events.append((peak_i, trough_i))
    return [{"peak": close.index[p], "trough": close.index[t], "peak_close": values[p],
             "trough_close": values[t], "fall": (values[t] / values[p] - 1) * 100}
            for p, t in events]


def event_timeline(hist: pd.DataFrame, cfg: TwWarningConfig = CONFIG,
                   lookback: int = 40) -> pd.DataFrame:
    """Per event: signals seen before the peak and the light's reaction."""
    close = hist["close"]
    ids = [s.id for s in SIGNALS if hist[s.id].notna().any()]
    rows = []
    for ev in drawdown_events(close):
        p = close.index.get_loc(ev["peak"])
        before = hist.iloc[max(0, p - lookback):p + 1]
        seen = [i for i in ids if (before[i] == 1).any()]
        during = hist.loc[ev["peak"]:ev["trough"]]

        def first(level):
            hit = during.index[during["level"] >= level]
            if len(hit) == 0:
                return None, None
            day = hit[0]
            return day, (close.loc[day] / ev["peak_close"] - 1) * 100

        y_day, y_off = first(1)
        o_day, o_off = first(2)
        r_day, r_off = first(3)
        level_at_peak = int(hist.loc[ev["peak"], "level"])
        rows.append({
            "高點": ev["peak"].date(), "低點": ev["trough"].date(), "跌幅": ev["fall"],
            "高點前 40 日出現的訊號": "、".join(seen) or "—",
            "高點當天燈號": ("綠", "黃", "橙", "紅")[level_at_peak],
            "首次橙燈": None if o_day is None else o_day.date(), "橙燈時距高點": o_off,
            "首次紅燈": None if r_day is None else r_day.date(), "紅燈時距高點": r_off,
            "首次黃燈（高點後）": None if y_day is None else y_day.date(),
        })
    return pd.DataFrame(rows)


def run_backtest(data: dict, cfg: TwWarningConfig = CONFIG,
                 now: pd.Timestamp | None = None) -> dict:
    full = level_history(data, cfg)
    if full.empty:
        return {"available": False}
    hist = _window(full, cfg, now)
    return {
        "available": True,
        "start": hist.index[0], "end": hist.index[-1],
        "hit_rates": hit_rates(hist, cfg),
        "strategies": strategy_table(hist, cfg),
        "events": event_timeline(hist, cfg),
        "coverage": {s.id: (hist[s.id].first_valid_index()) for s in SIGNALS},
    }
