from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .utils import compute_yoy, legacy_tls_session, DEFAULT_HEADERS

logger = logging.getLogger("gai_me.fetchers.fred")

FRED_BASE     = "https://api.stlouisfed.org/fred/series/observations"
DBNOMICS_BASE = "https://api.db.nomics.world/v22/series"


def fetch_dbnomics(provider: str, dataset: str, series: str, years_back: int = 12) -> pd.DataFrame:
    try:
        url = f"{DBNOMICS_BASE}/{provider}/{dataset}/{series}?observations=1"
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        docs = data.get("series", {}).get("docs", [])
        if not docs:
            return pd.DataFrame()
        doc = docs[0]
        periods = doc.get("period", doc.get("observations", {}).get("period", []))
        values  = doc.get("value",  doc.get("observations", {}).get("value",  []))
        df = pd.DataFrame({'date': periods, 'value': values}).dropna()
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df['date']  = pd.to_datetime(df['date'], format='mixed', errors='coerce')
        df = df.dropna().sort_values('date')
        cutoff = datetime.now() - relativedelta(years=years_back)
        return df[df['date'] >= pd.Timestamp(cutoff)]
    except Exception as e:
        logger.error("DBnomics fetch error (%s): %s", series, e)
        return pd.DataFrame()


def fetch_fred(series_id: str, api_key: str, years_back: int = 12) -> pd.DataFrame:
    if not api_key:
        return pd.DataFrame()
    try:
        cutoff = datetime.now() - relativedelta(years=years_back)
        params = {
            'series_id':         series_id,
            'api_key':           api_key,
            'file_type':         'json',
            'observation_start': cutoff.strftime('%Y-%m-%d'),
        }
        res = requests.get(FRED_BASE, params=params, timeout=10)
        res.raise_for_status()
        observations = res.json().get('observations', [])
        df = pd.DataFrame(observations)
        if df.empty:
            return pd.DataFrame()
        df = df[df['value'] != '.']
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df['date']  = pd.to_datetime(df['date'],  errors='coerce')
        return df.dropna().sort_values('date')[['date', 'value']]
    except Exception as e:
        logger.error("FRED fetch error (%s): %s", series_id, e)
        return pd.DataFrame()


def fetch_dxy(api_key: str, years_back: int = 12) -> pd.DataFrame:
    return fetch_fred('DTWEXBGS', api_key, years_back=years_back)


_MOFCOM_SHRZGM = "https://data.mofcom.gov.cn/datamofcom/front/gnmy/shrzgmQuery"


def fetch_china_credit_impulse(api_key: str | None = None, years_back: int = 12) -> pd.DataFrame:
    """中國信貸脈衝 — 社會融資規模增量(月)的 12 個月滾動加總同比變化。

    來源：商務部資料中心 shrzgmQuery（tiosfs=社融增量，億元，需降級 TLS）。
    信貸脈衝 = TTM(滾動12月)社融流量的同比變化(YoY)，正值代表信貸擴張加速，
    領先全球總需求約 9~12 個月，與 MacroMicro「中國信貸脈衝」走勢一致。
    api_key 參數保留僅為向後相容（不再使用 FRED）。
    """
    try:
        s = legacy_tls_session()
        r = s.post(_MOFCOM_SHRZGM, headers=DEFAULT_HEADERS, timeout=30)
        r.raise_for_status()
        rows = r.json()
    except Exception as e:
        logger.error("China credit impulse (MOFCOM) fetch error: %s", e)
        return pd.DataFrame()

    records = []
    for row in rows:
        ym = str(row.get("date", "")).strip()
        flow = row.get("tiosfs")
        if len(ym) != 6 or flow is None:
            continue
        try:
            records.append({"date": pd.Timestamp(year=int(ym[:4]), month=int(ym[4:]), day=1),
                            "flow": float(flow)})
        except (ValueError, TypeError):
            continue
    if len(records) < 25:                       # 需 12(TTM) + 12(YoY) + 1
        logger.error("China credit impulse: insufficient MOFCOM rows (%d)", len(records))
        return pd.DataFrame()

    df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    ttm = df["flow"].rolling(12).sum()          # 滾動 12 月社融流量
    df["value"] = (ttm.diff(12) / ttm.shift(12).abs() * 100)   # TTM 流量同比變化(%)
    out = df[["date", "value"]].dropna().reset_index(drop=True)
    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return out[out["date"] >= cutoff].reset_index(drop=True)


def fetch_copper_yoy(api_key: str, years_back: int = 12) -> pd.DataFrame:
    raw = fetch_fred('PCOPPUSDM', api_key, years_back=years_back + 1)
    return compute_yoy(raw)


def fetch_hy_spread(api_key: str, years_back: int = 12) -> pd.DataFrame:
    return fetch_fred('BAMLH0A0HYM2', api_key, years_back=years_back)


def fetch_twd_usd(api_key: str, years_back: int = 12) -> pd.DataFrame:
    return fetch_fred('DEXTAUS', api_key, years_back=years_back)


def fetch_korea_exports_yoy(api_key: str, years_back: int = 12) -> pd.DataFrame:
    raw = fetch_fred('XTEXVA01KRM664S', api_key, years_back=years_back + 1)
    return compute_yoy(raw)


def fetch_fed_funds_rate(api_key: str, years_back: int = 12) -> pd.DataFrame:
    raw = fetch_fred('DFF', api_key, years_back=years_back)
    if raw is None or raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    raw['ym'] = raw['date'].dt.to_period('M')
    monthly = raw.groupby('ym')['value'].mean().reset_index()
    monthly['date'] = monthly['ym'].dt.to_timestamp()
    return monthly[['date', 'value']].sort_values('date').reset_index(drop=True)


def fetch_t10y3m(api_key: str, years_back: int = 12) -> pd.DataFrame:
    return fetch_fred('T10Y3M', api_key, years_back=years_back)


def fetch_us_new_orders_yoy(api_key: str, years_back: int = 12) -> pd.DataFrame:
    raw = fetch_fred('AMTMNO', api_key, years_back=years_back + 1)
    return compute_yoy(raw) if raw is not None and not raw.empty else pd.DataFrame()


def fetch_sp500_yoy(api_key: str, years_back: int = 12) -> pd.DataFrame:
    raw = fetch_fred('SP500', api_key, years_back=years_back + 1)
    if raw is None or raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    raw['ym'] = raw['date'].dt.to_period('M')
    raw = raw.groupby('ym').last().reset_index()
    raw['date'] = raw['ym'].dt.to_timestamp('M')
    return compute_yoy(raw[['date', 'value']].sort_values('date'))
