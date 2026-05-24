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


# Reverse lookup: SECTOR_NAMES value → code  (e.g. "電子" → "14")
_NAME_TO_CODE: dict[str, str] = {name: code for code, name in SECTOR_NAMES.items()}

# MI_INDEX uses "電子工業類指數" for what SECTOR_NAMES calls "電子"
# Map stripped index label → SECTOR_NAMES key
_INDEX_LABEL_ALIASES: dict[str, str] = {
    "電子工業": "14",  # 電子工業類指數 = 電子類
}


def _resolve_index_label(raw: str) -> tuple[str | None, str | None]:
    """
    Convert an MI_INDEX 指數 label to (sector_code, sector_name).

    Examples:
        "水泥類指數"    → ("01", "水泥")
        "電子工業類指數" → ("14", "電子")
        "半導體類指數"  → (None, None)   # sub-index, skip
    """
    label = raw.strip()
    if label.endswith("指數"):
        label = label[:-2]
    if label.endswith("類"):
        label = label[:-1]
    # Exact match in SECTOR_NAMES values
    if label in _NAME_TO_CODE:
        code = _NAME_TO_CODE[label]
        return code, SECTOR_NAMES[code]
    # Alias (e.g. "電子工業" → "14")
    if label in _INDEX_LABEL_ALIASES:
        code = _INDEX_LABEL_ALIASES[label]
        return code, SECTOR_NAMES[code]
    return None, None


def fetch_tw_sector_indices(n_days: int = 252) -> pd.DataFrame:
    """
    Fetch daily close and change% for all 19 TWSE sector indices.

    Source: TWSE MI_INDEX (afterTrading/MI_INDEX, type=IND, table[0])
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
                "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
                params={"response": "json", "date": date_str, "type": "IND"},
                headers=_HDR,
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            j = resp.json()
            if j.get("stat") != "OK":
                continue

            # table[0]: 價格指數(臺灣證券交易所) — contains all sector indices
            tables = j.get("tables", [])
            if not tables:
                continue
            table0 = tables[0]
            rows = table0.get("data", [])
            if not rows:
                continue

            # fields: ['指數', '收盤指數', '漲跌(+/-)', '漲跌點數', '漲跌百分比(%)', ...]
            fields = table0.get("fields", [])
            try:
                close_col = fields.index("收盤指數") if "收盤指數" in fields else 1
                chg_col   = next((i for i, f in enumerate(fields) if "%" in f), 4)
            except (ValueError, StopIteration):
                close_col, chg_col = 1, 4

            dt = pd.Timestamp(date_str)
            day_added = False
            for row in rows:
                if len(row) <= chg_col:
                    continue
                code, sector_name = _resolve_index_label(str(row[0]))
                if code is None:
                    continue  # sub-index or composite — skip
                try:
                    close_val = float(str(row[close_col]).replace(",", ""))
                    chg_str   = str(row[chg_col]).replace(",", "").replace("+", "").strip()
                    chg_val   = float(chg_str) if chg_str else 0.0
                except (ValueError, IndexError):
                    continue
                records.append({
                    "date":        dt,
                    "sector_code": code,
                    "sector_name": sector_name,
                    "close":       close_val,
                    "chg_pct":     chg_val,
                })
                day_added = True

            if day_added:
                collected += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning("MI_INDEX fetch error (%s): %s", date_str, e)

    if not records:
        return pd.DataFrame(columns=["date", "sector_code", "sector_name", "close", "chg_pct"])

    df = pd.DataFrame(records).sort_values(["date", "sector_name"]).reset_index(drop=True)
    return df


def fetch_tw_sector_turnover(n_days: int = 60) -> pd.DataFrame:
    """
    TWSE does not expose a JSON API for sector-level turnover.
    Returns empty DataFrame so callers can handle the no-data case gracefully.
    """
    logger.info("fetch_tw_sector_turnover: no TWSE JSON API for sector turnover; returning empty")
    return pd.DataFrame(columns=["date", "sector_name", "turnover_億", "turnover_share_pct"])


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
    Fetch overall market institutional net buy/sell from TWSE BFI82U.

    BFI82U (selectType=ALLBUT0999) returns one row per institution type:
      外資及陸資, 外資自營商, 投信, 自營商(自行買賣), 自營商(避險), 合計
    Fields: [單位名稱, 買進金額, 賣出金額, 買賣差額]  (unit: NT$ thousand)

    Returns DataFrame with columns:
      [date, institution, buy_amt, sell_amt, net_amt]
    All amounts in NT$ thousands.

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

            dt = pd.Timestamp(date_str)

            def _parse_amt(val: str) -> float:
                try:
                    return float(str(val).replace(",", "").replace("+", ""))
                except (ValueError, TypeError):
                    return 0.0

            for row in j["data"]:
                if len(row) < 4:
                    continue
                institution = str(row[0]).strip()
                if not institution or institution in ("合計", "總計"):
                    continue
                records.append({
                    "date":        dt,
                    "institution": institution,
                    "buy_amt":     _parse_amt(row[1]),
                    "sell_amt":    _parse_amt(row[2]),
                    "net_amt":     _parse_amt(row[3]),
                })
            collected += 1
            time.sleep(0.3)

        except Exception as e:
            logger.warning("BFI82U fetch error (%s): %s", date_str, e)

    if not records:
        return pd.DataFrame(columns=["date", "institution", "buy_amt", "sell_amt", "net_amt"])
    return (pd.DataFrame(records)
            .sort_values(["date", "institution"])
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
