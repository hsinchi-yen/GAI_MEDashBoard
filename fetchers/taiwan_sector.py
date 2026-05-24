"""
fetchers/taiwan_sector.py — Taiwan stock sector rotation data.

Data sources:
  - TWSE MI_INDEX20  : 19 official sector indices (daily close)
  - TWSE sector turnover  : daily sector trading value / share of total
  - TWSE T86 by sector    : institutional net buy/sell aggregated by sector
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

logger = logging.getLogger("gai_me.fetchers.taiwan_sector")

# TWSE sector code → Chinese name mapping (MI_INDEX20 standard codes)
SECTOR_NAMES: dict[str, str] = {
    "01": "水泥",
    "02": "食品",
    "03": "塑膠",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "08": "化學生技醫療",
    "09": "玻璃陶瓷",
    "10": "造紙",
    "11": "鋼鐵",
    "12": "橡膠",
    "13": "汽車",
    "14": "電子",
    "15": "建材營造",
    "16": "航運",
    "17": "觀光餐旅",
    "18": "金融保險",
    "19": "貿易百貨",
    "20": "油電燃氣",
}

_HDR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def _last_trading_days(n: int = 60) -> list[str]:
    """Return up to n recent weekday date strings (YYYYMMDD), newest first."""
    days = []
    cursor = datetime.now() - timedelta(days=1)
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor.strftime("%Y%m%d"))
        cursor -= timedelta(days=1)
    return days


def fetch_tw_sector_indices(n_days: int = 252) -> pd.DataFrame:
    """
    Fetch daily close and change% for all TWSE sector indices.

    Source: TWSE MI_INDEX20 (類股指數)
    Returns DataFrame with columns: [date, sector_code, sector_name, close, chg_pct]
    """
    records = []
    dates_to_fetch = _last_trading_days(n_days + 30)  # buffer for holidays

    collected = 0
    for date_str in dates_to_fetch:
        if collected >= n_days:
            break
        try:
            resp = requests.get(
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20",
                params={"response": "json", "date": date_str},
                headers=_HDR,
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            j = resp.json()
            if j.get("stat") != "OK" or not j.get("data"):
                continue

            fields = j.get("fields", [])
            dt = pd.Timestamp(date_str)

            for row in j["data"]:
                # Expected fields: 類股名稱, 發行股數, 成交股數, 成交金額, 成交筆數, 最高, 最低, 收盤, 漲跌(%), ...
                if len(row) < 2:
                    continue
                sector_raw = str(row[0]).strip()
                # MI_INDEX20 returns names like "電子類"; strip trailing 類 to normalize
                sector_clean = sector_raw.rstrip("類")
                code = next((c for c, n in SECTOR_NAMES.items() if n == sector_clean), None)
                sector_name = sector_clean if code else sector_raw

                # Find close and chg_pct by column name
                try:
                    close_col  = fields.index("收盤") if "收盤" in fields else 7
                    chg_col    = next((i for i, f in enumerate(fields) if "漲跌" in f and "%" in f), 8)
                    close_val  = float(str(row[close_col]).replace(",", ""))
                    chg_val    = float(str(row[chg_col]).replace(",", "").replace("+", ""))
                except (ValueError, IndexError):
                    continue

                records.append({
                    "date":        dt,
                    "sector_code": code or sector_name,
                    "sector_name": sector_name,
                    "close":       close_val,
                    "chg_pct":     chg_val,
                })

            collected += 1
            time.sleep(0.3)  # polite rate limit

        except Exception as e:
            logger.warning("MI_INDEX20 fetch error (%s): %s", date_str, e)

    if not records:
        return pd.DataFrame(columns=["date", "sector_code", "sector_name", "close", "chg_pct"])

    df = pd.DataFrame(records).sort_values(["date", "sector_name"]).reset_index(drop=True)
    return df


def fetch_tw_sector_turnover(n_days: int = 60) -> pd.DataFrame:
    """
    Fetch daily sector trading value and its share of total market turnover.

    Source: TWSE MI_INDEX20 成交金額 field
    Returns DataFrame: [date, sector_name, turnover_億, turnover_share_pct]
    """
    records = []
    dates_to_fetch = _last_trading_days(n_days + 20)
    collected = 0

    for date_str in dates_to_fetch:
        if collected >= n_days:
            break
        try:
            resp = requests.get(
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX20",
                params={"response": "json", "date": date_str},
                headers=_HDR,
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            j = resp.json()
            if j.get("stat") != "OK" or not j.get("data"):
                continue

            fields = j.get("fields", [])
            dt = pd.Timestamp(date_str)

            try:
                amt_col = fields.index("成交金額") if "成交金額" in fields else 4
            except ValueError:
                amt_col = 4

            day_records = []
            total_turnover = 0.0
            for row in j["data"]:
                if len(row) <= amt_col:
                    continue
                try:
                    sector_raw = str(row[0]).strip()
                    sector_clean = sector_raw.rstrip("類")
                    sector_name = sector_clean if sector_clean in SECTOR_NAMES.values() else sector_raw
                    turnover = float(str(row[amt_col]).replace(",", ""))
                    total_turnover += turnover
                    day_records.append({"date": dt, "sector_name": sector_name, "turnover": turnover})
                except (ValueError, IndexError):
                    continue

            if total_turnover > 0:
                for r in day_records:
                    r["turnover_億"]        = round(r["turnover"] / 1e8, 2)
                    r["turnover_share_pct"] = round(r["turnover"] / total_turnover * 100, 2)
                records.extend(day_records)
                collected += 1

            time.sleep(0.3)

        except Exception as e:
            logger.warning("Sector turnover fetch error (%s): %s", date_str, e)

    if not records:
        return pd.DataFrame(columns=["date", "sector_name", "turnover_億", "turnover_share_pct"])

    df = (pd.DataFrame(records)
          [["date", "sector_name", "turnover_億", "turnover_share_pct"]]
          .sort_values(["date", "sector_name"])
          .reset_index(drop=True))
    return df


def calc_sector_momentum(sector_df: pd.DataFrame, weeks_short: int = 4, weeks_long: int = 12) -> pd.DataFrame:
    """
    Compute rolling return and momentum acceleration per sector.

    Args:
        sector_df: Output of fetch_tw_sector_indices() — columns [date, sector_name, close]
        weeks_short: lookback for short-term momentum (default 4 weeks ≈ 20 days)
        weeks_long: lookback for long-term momentum (default 12 weeks ≈ 60 days)

    Returns DataFrame: [sector_name, ret_short_pct, ret_long_pct, acceleration, last_close, last_date]
        acceleration > 0 → momentum strengthening (升溫)
        acceleration < 0 → momentum weakening (退潮)
    """
    if sector_df.empty or "close" not in sector_df.columns:
        return pd.DataFrame()

    # Build price pivot: index=date, columns=sector_name
    pivot = (sector_df.pivot_table(index="date", columns="sector_name", values="close", aggfunc="last")
             .sort_index())

    if pivot.empty:
        return pd.DataFrame()

    # Approximate: 1 week ≈ 5 trading days
    d_short    = weeks_short * 5
    d_long     = weeks_long  * 5
    d_prev     = d_short * 2  # period before short window (for acceleration)

    records = []
    for sector in pivot.columns:
        series = pivot[sector].dropna()
        if len(series) < d_long:
            continue

        latest_close = series.iloc[-1]
        latest_date  = series.index[-1]

        # Returns
        close_short_ago = series.iloc[-d_short] if len(series) > d_short else series.iloc[0]
        close_long_ago  = series.iloc[-d_long]  if len(series) > d_long  else series.iloc[0]
        close_prev_ago  = series.iloc[-d_prev]  if len(series) > d_prev  else series.iloc[0]

        ret_short = (latest_close / close_short_ago - 1) * 100
        ret_long  = (latest_close / close_long_ago  - 1) * 100

        # Acceleration = short-window return now vs. short-window return d_short periods ago
        # prev short return = price at (-d_short) / price at (-d_prev)
        ret_prev_short = (close_short_ago / close_prev_ago - 1) * 100 if close_prev_ago else 0
        acceleration   = ret_short - ret_prev_short

        records.append({
            "sector_name":   sector,
            "ret_short_pct": round(ret_short, 2),
            "ret_long_pct":  round(ret_long, 2),
            "acceleration":  round(acceleration, 2),
            "last_close":    latest_close,
            "last_date":     latest_date,
        })

    if not records:
        return pd.DataFrame(columns=["sector_name", "ret_short_pct", "ret_long_pct",
                                     "acceleration", "last_close", "last_date"])
    return pd.DataFrame(records).sort_values("ret_short_pct", ascending=False).reset_index(drop=True)


def fetch_tw_sector_institutional(n_days: int = 5) -> pd.DataFrame:
    """
    Fetch sector-level institutional net buy/sell from TWSE BFI82U.

    BFI82U aggregates foreign + trust fund + dealer net positions by
    industry category.  One row per (date, sector_name, institution_type).

    Returns DataFrame with columns:
      [date, sector_name, foreign_net, trust_net, dealer_net, total_net]
    All net values in thousands of shares (千股).

    Falls back to empty DataFrame if TWSE API is unavailable.
    """
    records: list[dict] = []
    dates_to_try = _last_trading_days(n_days + 10)
    collected = 0

    for date_str in dates_to_try:
        if collected >= n_days:
            break
        try:
            resp = requests.get(
                "https://www.twse.com.tw/rwd/zh/fund/BFI82U",
                params={"response": "json", "day": date_str, "selectType": "ALLBUT0999"},
                headers=_HDR,
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            j = resp.json()
            if j.get("stat") != "OK" or not j.get("data"):
                continue

            fields = j.get("fields", [])
            dt = pd.Timestamp(date_str)

            # Expected fields: 類別, 外資買進, 外資賣出, 外資淨買超, 投信買進, ... 自營商...
            def _col(names: list[str]) -> int:
                for name in names:
                    for i, f in enumerate(fields):
                        if name in f:
                            return i
                return -1

            foreign_col = _col(["外資淨"])
            trust_col   = _col(["投信淨"])
            dealer_col  = _col(["自營商淨"])
            # Fallback: sum buy-sell manually if net column absent
            foreign_buy_col  = _col(["外資買進"])
            foreign_sell_col = _col(["外資賣出"])
            trust_buy_col    = _col(["投信買進"])
            trust_sell_col   = _col(["投信賣出"])
            dealer_buy_col   = _col(["自營商買進"])
            dealer_sell_col  = _col(["自營商賣出"])

            def _parse_val(row, col, buy_col=-1, sell_col=-1) -> float:
                if col >= 0 and col < len(row):
                    try:
                        return float(str(row[col]).replace(",", "").replace("+", ""))
                    except ValueError:
                        pass
                if buy_col >= 0 and sell_col >= 0:
                    try:
                        b = float(str(row[buy_col]).replace(",", ""))
                        s = float(str(row[sell_col]).replace(",", ""))
                        return b - s
                    except ValueError:
                        pass
                return 0.0

            for row in j["data"]:
                if len(row) < 2:
                    continue
                sector_raw = str(row[0]).strip()
                if not sector_raw or sector_raw in ("合計", "總計"):
                    continue
                # BFI82U returns numeric sector codes ("01", "14"); map to Chinese names
                sector_name = SECTOR_NAMES.get(sector_raw, sector_raw)
                f_net = _parse_val(row, foreign_col, foreign_buy_col, foreign_sell_col)
                t_net = _parse_val(row, trust_col,   trust_buy_col,   trust_sell_col)
                d_net = _parse_val(row, dealer_col,  dealer_buy_col,  dealer_sell_col)
                records.append({
                    "date":        dt,
                    "sector_name": sector_name,
                    "foreign_net": f_net,
                    "trust_net":   t_net,
                    "dealer_net":  d_net,
                    "total_net":   f_net + t_net + d_net,
                })
            collected += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning("BFI82U fetch error (%s): %s", date_str, e)

    if not records:
        return pd.DataFrame(columns=["date", "sector_name",
                                     "foreign_net", "trust_net", "dealer_net", "total_net"])
    return (pd.DataFrame(records)
            .sort_values(["date", "sector_name"])
            .reset_index(drop=True))


def detect_rotation_signal(momentum_df: pd.DataFrame) -> dict[str, list[str]]:
    """
    Classify sectors into four rotation quadrants.

    Quadrants (based on ret_short_pct and acceleration):
      hot     : ret > 0 AND acceleration > 0  → 持續強勢
      cooling : ret > 0 AND acceleration < 0  → 退潮中（如：被動元件）
      warming : ret < 0 AND acceleration > 0  → 升溫中，下一波候選
      cold    : ret < 0 AND acceleration < 0  → 持續弱勢

    Returns dict with lists of sector names per quadrant.
    """
    if momentum_df.empty:
        return {"hot": [], "cooling": [], "warming": [], "cold": []}

    hot     = momentum_df[(momentum_df["ret_short_pct"] >= 0) & (momentum_df["acceleration"] >= 0)]["sector_name"].tolist()
    cooling = momentum_df[(momentum_df["ret_short_pct"] >= 0) & (momentum_df["acceleration"] <  0)]["sector_name"].tolist()
    warming = momentum_df[(momentum_df["ret_short_pct"] <  0) & (momentum_df["acceleration"] >= 0)]["sector_name"].tolist()
    cold    = momentum_df[(momentum_df["ret_short_pct"] <  0) & (momentum_df["acceleration"] <  0)]["sector_name"].tolist()

    return {"hot": hot, "cooling": cooling, "warming": warming, "cold": cold}
