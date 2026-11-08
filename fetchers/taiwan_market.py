"""Taiwan market-wide flows: breadth, turnover, foreign flows, futures OI, margin.

Daily values come from the official TWSE and TAIFEX endpoints. The 10-year
history ships as ``fetchers/data/tw_flows_seed.csv`` (built once by
``tools/backfill_tw_flows.py``), the same way VIXTWN ships its seed, so the
production box needs no backfill run and no FinMind token.

Units used everywhere downstream:
    tw_adv / tw_dec        listed common stocks up / down that day (count)
    tw_pct_ma20 / _ma60    % of listed common stocks closing above their MA
    tw_turnover            TWSE turnover, NT$ 億 (1e8)
    tw_fini_net            foreign investors' net buy in the cash market, NT$ 億
    tw_fini_fut_oi         foreign net open interest in TAIEX futures, TX lots
                           (TX + MTX / 4; negative = net short)
    tw_margin              margin purchase balance, NT$ 億

The seed also carries ``taiex_daily`` (official close) so a short Yahoo history
can be extended to the 10 years the back-test needs.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .taiwan import _HDR_TWSE

logger = logging.getLogger("gai_me.fetchers.taiwan_market")

TWSE = "https://www.twse.com.tw/rwd/zh"
TAIFEX_FUT_INST = ("https://openapi.taifex.com.tw/v1/"
                   "MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate")
SEED_CSV = Path(__file__).parent / "data" / "tw_flows_seed.csv"
CLOSES_SEED_CSV = Path(__file__).parent / "data" / "tw_stock_close_seed.csv.gz"

SERIES = ("tw_adv", "tw_dec", "tw_pct_ma20", "tw_pct_ma60", "tw_turnover",
          "tw_fini_net", "tw_fini_fut_oi", "tw_margin")
CLOSES_KEY = "tw_stock_close"     # per-stock closes, rolling window only
CLOSE_WINDOW_DAYS = 70            # trading days kept: MA60 plus a few missing days
CLOSE_KEEP_DAYS = 105             # the same window in calendar days
MTX_PER_TX = 4                    # mini-TAIEX is a quarter of a TX contract

_BN = 1e8
_COMMON_STOCK = re.compile(r"^[1-9]\d{3}$")   # 4 digits, not an 00xx ETF
_LEADING_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _num(text) -> float:
    m = _LEADING_NUM.search(str(text))
    return float(m.group().replace(",", "")) if m else float("nan")


def _twse_json(path: str, **params) -> dict | None:
    """TWSE rwd JSON, or None on a non-trading day / bad response."""
    try:
        res = requests.get(f"{TWSE}/{path}", params={**params, "response": "json"},
                           headers=_HDR_TWSE, timeout=30)
        res.raise_for_status()
        body = res.json()
    except Exception as e:
        logger.warning("TWSE %s %s failed: %s", path, params, e)
        return None
    return body if body.get("stat") == "OK" else None


# ── parsers (pure; tested against saved responses) ────────────────────────────

def parse_mi_index(body: dict) -> tuple[dict, pd.DataFrame]:
    """MI_INDEX type=ALLBUT0999 → ({adv, dec, unch}, closes[code, close]).

    Counts are the official 股票 column of 漲跌證券數合計 (excludes warrants and
    funds). Closes keep listed common stocks only, so ETFs do not dilute the MA
    breadth.
    """
    counts: dict = {}
    closes = pd.DataFrame(columns=["code", "close"])
    for table in body.get("tables", []):
        title = table.get("title") or ""
        fields = table.get("fields") or []
        if title == "漲跌證券數合計":
            col = fields.index("股票")
            for row in table.get("data", []):
                label = row[0]
                if label.startswith("上漲"):
                    counts["adv"] = int(_num(row[col]))
                elif label.startswith("下跌"):
                    counts["dec"] = int(_num(row[col]))
                elif label.startswith("持平"):
                    counts["unch"] = int(_num(row[col]))
        elif "收盤行情" in title and "證券代號" in fields:
            ci, pi = fields.index("證券代號"), fields.index("收盤價")
            rows = [(r[ci].strip(), r[pi]) for r in table.get("data", [])
                    if _COMMON_STOCK.match(r[ci].strip())]
            closes = pd.DataFrame(rows, columns=["code", "close"])
            closes["close"] = pd.to_numeric(closes["close"].str.replace(",", ""),
                                            errors="coerce")
            closes = closes.dropna()
    return counts, closes


def parse_margin(body: dict) -> float | None:
    """MI_MARGN selectType=MS → margin purchase balance (今日餘額), NT$ 億."""
    for table in body.get("tables", []):
        fields = table.get("fields") or []
        if "今日餘額" not in fields:
            continue
        for row in table.get("data", []):
            if row[0].startswith("融資金額"):
                return _num(row[fields.index("今日餘額")]) * 1000 / _BN   # 仟元 → 元
    return None


def parse_bfi82u(body: dict) -> float | None:
    """BFI82U → foreign investors' (excl. foreign dealers) net buy, NT$ 億."""
    fields = body.get("fields") or []
    if "買賣差額" not in fields:
        return None
    for row in body.get("data", []):
        if row[0].startswith("外資及陸資"):
            return _num(row[fields.index("買賣差額")]) / _BN
    return None


def parse_fmtqik(body: dict) -> pd.DataFrame:
    """FMTQIK (one month) → [date, turnover (億), close]."""
    fields = body.get("fields") or []
    if "成交金額" not in fields:
        return pd.DataFrame(columns=["date", "turnover", "close"])
    di, vi, ci = fields.index("日期"), fields.index("成交金額"), fields.index("發行量加權股價指數")
    rows = []
    for r in body.get("data", []):
        y, m, d = (int(x) for x in r[di].split("/"))
        rows.append((pd.Timestamp(y + 1911, m, d), _num(r[vi]) / _BN, _num(r[ci])))
    return pd.DataFrame(rows, columns=["date", "turnover", "close"])


def parse_taifex_fini_oi(rows: list[dict]) -> tuple[pd.Timestamp, float] | None:
    """TAIFEX OpenAPI → (date, foreign net OI in TX lots: TX + MTX/4)."""
    net = {}
    date = None
    for r in rows or []:
        if r.get("Item") != "外資及陸資":
            continue
        if r.get("ContractCode") in ("臺股期貨", "小型臺指期貨"):
            net[r["ContractCode"]] = _num(r.get("OpenInterest(Net)"))
            date = pd.Timestamp(str(r["Date"]))
    if "臺股期貨" not in net:
        return None
    return date, net["臺股期貨"] + net.get("小型臺指期貨", 0.0) / MTX_PER_TX


def ma_breadth(closes: pd.DataFrame, windows=(20, 60)) -> pd.DataFrame:
    """Per date, % of stocks closing above their own MA.

    ``closes`` is long format [date, code, close]. A stock counts only once it
    has a full window of closes, so new listings do not skew the ratio.
    """
    wide = closes.pivot_table(index="date", columns="code", values="close").sort_index()
    out = pd.DataFrame(index=wide.index)
    for w in windows:
        ma = wide.rolling(w, min_periods=w).mean()
        valid = ma.notna() & wide.notna()
        above = (wide > ma) & valid
        n = valid.sum(axis=1)
        out[f"pct_ma{w}"] = np.where(n > 0, above.sum(axis=1) / n.replace(0, np.nan) * 100, np.nan)
    return out.reset_index()


# ── daily fetchers (scheduler) ────────────────────────────────────────────────

def _one(date: pd.Timestamp, value) -> pd.DataFrame:
    return pd.DataFrame({"date": [pd.Timestamp(date).normalize()], "value": [float(value)]})


def fetch_tw_market_day(day: pd.Timestamp | None = None, sleep: float = 3.0) -> dict:
    """One trading day from TWSE: breadth counts, closes, margin, foreign cash flow.

    Returns {"tw_adv": df, "tw_dec": df, "tw_margin": df, "tw_fini_net": df,
    "closes": long df}; missing pieces are simply absent (non-trading day → {}).
    """
    day = pd.Timestamp(day or pd.Timestamp.now()).normalize()
    ymd = day.strftime("%Y%m%d")
    out: dict = {}
    body = _twse_json("afterTrading/MI_INDEX", date=ymd, type="ALLBUT0999")
    if body is None:
        return out
    counts, closes = parse_mi_index(body)
    if "adv" in counts:
        out["tw_adv"] = _one(day, counts["adv"])
        out["tw_dec"] = _one(day, counts["dec"])
    if not closes.empty:
        out["closes"] = closes.assign(date=day)[["date", "code", "close"]]
    time.sleep(sleep)
    margin = _twse_json("marginTrading/MI_MARGN", date=ymd, selectType="MS")
    value = parse_margin(margin) if margin else None
    if value is not None:
        out["tw_margin"] = _one(day, value)
    time.sleep(sleep)
    flows = _twse_json("fund/BFI82U", dayDate=ymd, type="day")
    value = parse_bfi82u(flows) if flows else None
    if value is not None:
        out["tw_fini_net"] = _one(day, value)
    return out


def fetch_tw_turnover(months: int = 2, now: pd.Timestamp | None = None,
                      sleep: float = 3.0) -> pd.DataFrame:
    """TWSE turnover (億) for the last ``months`` months → {date, value}."""
    now = pd.Timestamp(now or pd.Timestamp.now())
    frames = []
    for k in range(months - 1, -1, -1):
        first = (now - pd.DateOffset(months=k)).replace(day=1)
        body = _twse_json("afterTrading/FMTQIK", date=first.strftime("%Y%m%d"))
        if body:
            frames.append(parse_fmtqik(body))
        time.sleep(sleep)
    if not frames:
        return pd.DataFrame(columns=["date", "value"])
    df = pd.concat(frames).drop_duplicates("date")
    return df.rename(columns={"turnover": "value"})[["date", "value"]]


def fetch_taifex_fini_oi() -> pd.DataFrame:
    """Latest foreign net TAIEX-futures OI (TAIFEX publishes one day) → {date, value}."""
    try:
        res = requests.get(TAIFEX_FUT_INST, headers={"Accept": "application/json"}, timeout=30)
        res.raise_for_status()
        parsed = parse_taifex_fini_oi(res.json())
    except Exception as e:
        logger.warning("TAIFEX futures OI failed: %s", e)
        return pd.DataFrame(columns=["date", "value"])
    return pd.DataFrame(columns=["date", "value"]) if parsed is None else _one(*parsed)


def load_tw_flows_seed() -> dict[str, pd.DataFrame]:
    """The shipped 10-year history, one {date, value} frame per series."""
    if not SEED_CSV.exists():
        return {}
    wide = pd.read_csv(SEED_CSV, parse_dates=["date"])
    return {key: wide[["date", key]].dropna().rename(columns={key: "value"}).reset_index(drop=True)
            for key in (*SERIES, "taiex_daily") if key in wide.columns}


def load_tw_closes_seed() -> pd.DataFrame:
    """The last ~70 trading days of per-stock closes, so MA breadth works at once.

    Long format [date, code, close]; db_manager stores ``code`` as the series key.
    """
    if not CLOSES_SEED_CSV.exists():
        return pd.DataFrame(columns=["date", "code", "close"])
    return pd.read_csv(CLOSES_SEED_CSV, dtype={"code": str}, parse_dates=["date"])
