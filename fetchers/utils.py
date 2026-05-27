from __future__ import annotations

import logging
import re
import ssl
import time
from datetime import datetime

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

logger = logging.getLogger("gai_me.fetchers")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_MINGUO_PATTERN = re.compile(r'(\d+)年(\d+)月')
_YM_PATTERN = re.compile(r'(\d{4})\D+(\d{1,2})')   # "2026年04月份" → (2026, 04)

EASTMONEY_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def roc_to_ad(roc_year: int) -> int:
    return roc_year + 1911


def parse_minguo_ym(text: str) -> pd.Timestamp:
    """Convert '115年02月' or similar ROC year-month strings to pd.Timestamp."""
    text = str(text).replace(' ', '').replace(',', '')
    m = _MINGUO_PATTERN.match(text)
    if m:
        return pd.Timestamp(year=roc_to_ad(int(m.group(1))), month=int(m.group(2)), day=1)
    return pd.NaT


# Keep legacy name as alias
_parse_minguo_ym = parse_minguo_ym


def compute_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute YoY % from monthly data (12-period pct_change)."""
    if df.empty or len(df) < 13:
        return pd.DataFrame()
    df = df.copy()
    df['value'] = df['value'].pct_change(12) * 100
    return df.dropna()


def fetch_eastmoney_economy(report_name: str, value_col: str, years_back: int = 12,
                            *, page_size: int = 240) -> pd.DataFrame:
    """東方財富總經資料中心 → {date, value}。

    report_name 例：RPT_ECONOMY_PMI（製造業 PMI）、RPT_ECONOMY_PPI（PPI）、
    RPT_ECONOMY_CURRENCY_SUPPLY（貨幣供應量）。value_col 為要取的數值欄位
    （如 MAKE_INDEX、BASE_SAME、BASIC_CURRENCY_SAME）。TIME 欄位形如 "2026年04月份"。
    """
    params = {
        "columns": f"REPORT_DATE,TIME,{value_col}",
        "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": "REPORT_DATE", "sortTypes": "-1",
        "reportName": report_name,
    }
    headers = {**DEFAULT_HEADERS, "Referer": "https://data.eastmoney.com/"}
    try:
        r = requests.get(EASTMONEY_DATACENTER, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        payload = r.json()
        rows = (payload.get("result") or {}).get("data") or []
    except Exception as e:
        logger.error("Eastmoney %s fetch error: %s", report_name, e)
        return pd.DataFrame()

    records = []
    for row in rows:
        m = _YM_PATTERN.search(str(row.get("TIME", "")))
        val = row.get(value_col)
        if not m or val is None:
            continue
        try:
            records.append({"date": pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=1),
                            "value": float(val)})
        except (ValueError, TypeError):
            continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).dropna().sort_values("date").reset_index(drop=True)
    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return df[df["date"] >= cutoff].reset_index(drop=True)


class _LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    """部分政府站台僅支援舊版 TLS / 低 SECLEVEL，需降級握手。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def legacy_tls_session() -> requests.Session:
    """回傳掛載低 SECLEVEL TLS adapter 的 Session（for data.mofcom.gov.cn 等）。"""
    s = requests.Session()
    s.mount("https://", _LegacyTLSAdapter())
    return s


def fetch_with_retry(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 2.0,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """GET with exponential backoff. Raises on final failure."""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                sleep_s = backoff ** attempt
                logger.warning("fetch_with_retry: attempt %d failed for %s (%s), retrying in %.1fs",
                               attempt + 1, url, exc, sleep_s)
                time.sleep(sleep_s)
            else:
                logger.error("fetch_with_retry: all %d attempts failed for %s: %s", retries, url, exc)
    raise last_exc
