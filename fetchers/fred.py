from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .utils import compute_yoy

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


def fetch_china_credit_impulse(api_key: str, years_back: int = 12) -> pd.DataFrame:
    raw = fetch_fred('MYAGM2CNM189N', api_key, years_back=years_back + 2)
    if raw is None or raw.empty:
        raw = fetch_dbnomics('OECD', 'MEI', 'CHN.MABMM201.STSA.M', years_back=years_back + 2)
    if raw is None or raw.empty:
        return pd.DataFrame()
    yoy = compute_yoy(raw)
    if yoy.empty or len(yoy) < 13:
        return pd.DataFrame()
    yoy = yoy.copy()
    yoy['value'] = yoy['value'].diff(12)
    return yoy.dropna().reset_index(drop=True)


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
