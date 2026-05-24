from __future__ import annotations

import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

from .utils import compute_yoy

logger = logging.getLogger("gai_me.fetchers.yahoo_finance")

SECTOR_ETFS = {
    "cyclical":  ["XLY", "XLI", "XLB", "XLF"],
    "defensive": ["XLP", "XLU", "XLV", "XLRE"],
}
_ALL_SECTOR_ETFS = SECTOR_ETFS["cyclical"] + SECTOR_ETFS["defensive"]

_YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
}


def _yf_chart(ticker: str, interval: str = "1mo", range_str: str = "15y") -> dict:
    """Fetch Yahoo Finance chart API for a single ticker.

    Tries query1 first; falls back to query2 on 404 or connection error.
    Returns parsed result[0] or {}.
    """
    enc = urllib.parse.quote(ticker, safe='-.')
    for host in ("query1", "query2"):
        try:
            url = (
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{enc}"
                f"?interval={interval}&range={range_str}"
            )
            res = requests.get(url, headers=_YF_HEADERS, timeout=15)
            if res.status_code == 404:
                logger.warning("Yahoo Finance 404 for %s on %s — trying next host", ticker, host)
                continue
            res.raise_for_status()
            results = res.json().get("chart", {}).get("result", [])
            if results:
                return results[0]
            # Empty result — no point trying the other host
            return {}
        except Exception as e:
            logger.warning("Yahoo Finance chart error (%s on %s): %s", ticker, host, e)
    return {}


def fetch_index_yoy(ticker: str, years_back: int = 12) -> pd.DataFrame:
    """通用股市指數月頻 YoY (%) — Yahoo Finance v8"""
    raw = _yf_chart(ticker, interval="1mo", range_str="15y")
    if not raw:
        return pd.DataFrame()
    timestamps = raw.get("timestamp", [])
    closes = raw.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    if not timestamps or not closes:
        return pd.DataFrame()
    df = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s"), "value": closes})
    df = df.dropna().sort_values("date")
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back + 1)
    return compute_yoy(df[df["date"] >= cutoff])


def fetch_taiex_yoy(years_back: int = 12) -> pd.DataFrame:
    return fetch_index_yoy("^TWII", years_back=years_back)


def fetch_vkospi(years_back: int = 6) -> pd.DataFrame:
    """韓國波動率指數 VKOSPI — Yahoo Finance ^VKOSPI（月頻原始水位）"""
    raw = _yf_chart("^VKOSPI", interval="1mo", range_str="7y")
    if not raw:
        return pd.DataFrame()
    timestamps = raw.get("timestamp", [])
    closes = raw.get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
    if not timestamps or not closes:
        return pd.DataFrame()
    df = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s"), "value": closes})
    df = df.dropna().sort_values("date")
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back)
    return df[df["date"] >= cutoff].reset_index(drop=True)


def _fetch_etf_monthly(ticker: str, years_back: int = 8) -> dict:
    range_str = f"{years_back}y"
    raw = _yf_chart(ticker, interval="1mo", range_str=range_str)
    if not raw:
        return {}
    ts      = raw.get("timestamp", [])
    inds    = raw.get("indicators", {})
    closes  = inds.get("adjclose", [{}])[0].get("adjclose", [])
    volumes = inds.get("quote",    [{}])[0].get("volume",   [])
    if not ts:
        return {}
    return {"dates": pd.to_datetime(ts, unit="s"), "closes": closes, "volumes": volumes}


def fetch_etf_bulk(years_back: int = 8) -> dict:
    result: dict = {}
    with ThreadPoolExecutor(max_workers=len(_ALL_SECTOR_ETFS)) as pool:
        futures = {pool.submit(_fetch_etf_monthly, t, years_back): t for t in _ALL_SECTOR_ETFS}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result[ticker] = future.result()
            except Exception as e:
                logger.error("ETF bulk fetch failed (%s): %s", ticker, e)
                result[ticker] = {}
    return result


def _etf_bulk_to_prices(etf_bulk: dict) -> pd.DataFrame:
    series = {}
    for ticker, raw in etf_bulk.items():
        if not raw:
            continue
        df = pd.DataFrame({
            "date":  pd.to_datetime(raw["dates"], errors="coerce"),
            ticker:  pd.to_numeric(raw["closes"], errors="coerce"),
        }).dropna(subset=[ticker]).set_index("date")
        df = df[df.index.notna()]
        series[ticker] = df[ticker]
    return pd.DataFrame(series)


def _etf_bulk_to_volumes(etf_bulk: dict) -> pd.DataFrame:
    series = {}
    for ticker, raw in etf_bulk.items():
        if not raw:
            continue
        df = pd.DataFrame({
            "date":   pd.to_datetime(raw["dates"], errors="coerce"),
            "volume": pd.to_numeric(raw["volumes"], errors="coerce"),
        }).dropna(subset=["volume"]).set_index("date")
        df = df[df.index.notna()]
        series[ticker] = df["volume"]
    return pd.DataFrame(series)


def fetch_sector_rotation(etf_bulk: dict | None = None, years_back: int = 5) -> pd.DataFrame:
    """景氣循環 vs 防禦 3M 滾動超額報酬（US ETF）"""
    CYCLICAL  = SECTOR_ETFS["cyclical"]
    DEFENSIVE = SECTOR_ETFS["defensive"]
    if etf_bulk is not None:
        prices = _etf_bulk_to_prices(etf_bulk)
    else:
        prices = _etf_bulk_to_prices(fetch_etf_bulk(years_back=years_back + 1))
    if prices.empty:
        return pd.DataFrame()
    now = pd.Timestamp.now()
    cutoff = now - pd.DateOffset(years=years_back + 1)
    prices = prices[prices.index >= cutoff].dropna(how="all")
    cyc_t = [t for t in CYCLICAL  if t in prices.columns]
    def_t = [t for t in DEFENSIVE if t in prices.columns]
    if not cyc_t or not def_t:
        return pd.DataFrame()
    rets   = prices.pct_change().dropna(how="all")
    cyc_3m = (1 + rets[cyc_t].mean(axis=1)).rolling(3).apply(lambda x: x.prod(), raw=True) - 1
    def_3m = (1 + rets[def_t].mean(axis=1)).rolling(3).apply(lambda x: x.prod(), raw=True) - 1
    excess = (cyc_3m - def_3m).dropna().reset_index()
    excess.columns = ["date", "value"]
    cutoff_out = now - pd.DateOffset(years=years_back)
    return excess[excess["date"] >= cutoff_out].reset_index(drop=True)


def fetch_13f_proxy(etf_bulk: dict | None = None, api_key=None, years_back: int = 5) -> pd.DataFrame:
    """13F 循環/防禦淨加碼比代理（ETF 成交量加速度差值）"""
    CYCLICAL  = SECTOR_ETFS["cyclical"]
    DEFENSIVE = SECTOR_ETFS["defensive"]
    if etf_bulk is not None:
        vols = _etf_bulk_to_volumes(etf_bulk)
    else:
        vols = _etf_bulk_to_volumes(fetch_etf_bulk(years_back=years_back + 1))
    if vols.empty:
        return pd.DataFrame()
    cyc_t = [t for t in CYCLICAL  if t in vols.columns]
    def_t = [t for t in DEFENSIVE if t in vols.columns]
    if not cyc_t or not def_t:
        return pd.DataFrame()
    cyc_accel = vols[cyc_t].mean(axis=1).rolling(3).mean().pct_change(3)
    def_accel = vols[def_t].mean(axis=1).rolling(3).mean().pct_change(3)
    ratio = (cyc_accel - def_accel).dropna().reset_index()
    ratio.columns = ["date", "value"]
    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back)
    return ratio[ratio["date"] >= cutoff].reset_index(drop=True)
