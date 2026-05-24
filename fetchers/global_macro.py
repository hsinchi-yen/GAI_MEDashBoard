from __future__ import annotations

import json as _json
import logging
from datetime import datetime
from io import BytesIO, StringIO

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .fred import fetch_fred, fetch_dbnomics
from .utils import compute_yoy

logger = logging.getLogger("gai_me.fetchers.global_macro")


def fetch_ism_pmi(years_back: int = 12, fred_key: str | None = None) -> pd.DataFrame:
    """美國 ISM 製造業 PMI — DBnomics 5 子指標平均 + FRED fallback"""
    from .fred import DBNOMICS_BASE
    sub_datasets = ['neword', 'production', 'employment', 'supdel', 'inventories']
    all_dfs: dict = {}
    for ds in sub_datasets:
        try:
            url = f"{DBNOMICS_BASE}/ISM/{ds}/in?observations=1"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            docs = r.json().get('series', {}).get('docs', [])
            if not docs:
                continue
            d = docs[0]
            df = pd.DataFrame({'date': d.get('period', []), ds: d.get('value', [])})
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df[ds]     = pd.to_numeric(df[ds], errors='coerce')
            all_dfs[ds] = df.dropna()
        except Exception as e:
            logger.warning("ISM sub-index %s error: %s", ds, e)

    historic = pd.DataFrame()
    if len(all_dfs) >= 5:
        merged = all_dfs[sub_datasets[0]]
        for ds in sub_datasets[1:]:
            merged = merged.merge(all_dfs[ds], on='date', how='inner')
        merged['value'] = merged[sub_datasets].mean(axis=1)
        historic = merged[['date', 'value']].sort_values('date')

    result = historic
    if fred_key:
        napm = fetch_fred('NAPM', fred_key, years_back=years_back)
        if not napm.empty:
            if historic.empty:
                result = napm
            else:
                tail = napm[napm['date'] > historic['date'].max()]
                if not tail.empty:
                    result = pd.concat([historic, tail], ignore_index=True).sort_values('date')

    if result.empty:
        return pd.DataFrame()
    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return result[result['date'] >= cutoff].reset_index(drop=True)


def fetch_ndc_leading_index(years_back: int = 12) -> pd.DataFrame:
    """國家發展委員會景氣領先指標 — NDC JSON + HTML fallback"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        r = requests.get("https://index.ndc.gov.tw/n/json/leading", headers=headers, timeout=15, verify=False)
        if r.ok:
            records = []
            for item in r.json():
                ym = str(item.get('ym', '') or item.get('yearmonth', '')).strip().replace('-', '')
                try:
                    if len(ym) == 5:
                        year, month = int(ym[:3]) + 1911, int(ym[3:])
                    elif len(ym) == 6:
                        year, month = int(ym[:4]), int(ym[4:])
                    else:
                        continue
                    val = float(str(item.get('score', item.get('value', item.get('index', '')))).replace(',', ''))
                    records.append({'date': pd.Timestamp(year=year, month=month, day=1), 'value': val})
                except (ValueError, TypeError):
                    continue
            if records:
                df = pd.DataFrame(records).dropna().sort_values('date')
                cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
                return df[df['date'] >= cutoff].reset_index(drop=True)
    except Exception as e:
        logger.warning("NDC Leading Index API error: %s", e)

    # HTML fallback
    try:
        r = requests.get("https://index.ndc.gov.tw/n/zh_TW", headers=headers, timeout=15, verify=False)
        if r.ok:
            for df in pd.read_html(StringIO(r.text)):
                if df.shape[1] < 2:
                    continue
                col0 = df.iloc[:, 0].astype(str)
                date_rows = col0[col0.str.match(r'^\d{3}/\d{2}$|^\d{5}$')]
                if date_rows.empty:
                    continue
                records = []
                for idx in date_rows.index:
                    try:
                        ym_str = col0[idx].replace('/', '')
                        if len(ym_str) == 5:
                            year, month = int(ym_str[:3]) + 1911, int(ym_str[3:])
                        else:
                            continue
                        val = pd.to_numeric(df.iloc[idx, 1], errors='coerce')
                        if pd.notna(val):
                            records.append({'date': pd.Timestamp(year=year, month=month, day=1), 'value': float(val)})
                    except Exception:
                        continue
                if records:
                    dfr = pd.DataFrame(records).dropna().sort_values('date')
                    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
                    return dfr[dfr['date'] >= cutoff].reset_index(drop=True)
    except Exception as e:
        logger.warning("NDC Leading Index HTML fallback error: %s", e)

    logger.error("NDC Leading Index: 無法從官方網站取得資料")
    return pd.DataFrame()


def fetch_china_nbs_pmi(years_back: int = 12) -> pd.DataFrame:
    """中國製造業 PMI — 國家統計局"""
    try:
        n_months = years_back * 12
        params = {
            "m": "QueryData", "dbcode": "hgyd", "rowcode": "zb", "colcode": "sj",
            "wds": "[]",
            "dfwds": _json.dumps([
                {"wdcode": "zb", "valuecode": "A0B0101"},
                {"wdcode": "sj", "valuecode": f"LAST{n_months}"},
            ]),
        }
        r = requests.get("https://data.stats.gov.cn/english/easyquery.htm",
                         params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        nodes = r.json().get("returndata", {}).get("datanodes", [])
        if not nodes:
            return pd.DataFrame()
        records = []
        for n in nodes:
            if not n["data"]["hasdata"]:
                continue
            period = [w["valuecode"] for w in n["wds"] if w["wdcode"] == "sj"][0]
            records.append({"date": pd.Timestamp(year=int(period[:4]), month=int(period[4:6]), day=1),
                            "value": n["data"]["data"]})
        return pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.error("NBS PMI error: %s", e)
        return pd.DataFrame()


def fetch_japan_economy_watchers(years_back: int = 12) -> pd.DataFrame:
    """日本景氣觀測 DI — 內閣府 Economy Watchers Survey"""
    MONTH_MAP = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                 'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
    try:
        r = requests.get("https://www5.cao.go.jp/keizai3/watcher-e/di.xls",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        df = pd.read_excel(BytesIO(r.content), sheet_name='3. DI by sector(SA)', header=None)
        year_current = None
        records = []
        for idx in range(7, len(df)):
            row = df.iloc[idx]
            if pd.notna(row[0]) and str(row[0]).strip().replace('.0', '').isdigit():
                year_current = int(float(row[0]))
            month_str = str(row[1]).strip() if pd.notna(row[1]) else ''
            if month_str in MONTH_MAP and year_current:
                mfg_di = pd.to_numeric(row[9], errors='coerce')
                if pd.notna(mfg_di):
                    records.append({'date': pd.Timestamp(year=year_current, month=MONTH_MAP[month_str], day=1),
                                    'value': mfg_di})
        df_out = pd.DataFrame(records).sort_values('date')
        df_out = df_out.drop_duplicates(subset='date', keep='first')
        cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
        return df_out[df_out['date'] >= cutoff].reset_index(drop=True)
    except Exception as e:
        logger.error("Japan Economy Watchers error: %s", e)
        return pd.DataFrame()


def fetch_china_nbs_ppi_yoy(years_back: int = 12) -> pd.DataFrame:
    """中國 PPI YoY — 國家統計局 A01080101"""
    try:
        n_months = years_back * 12
        params = {
            "m": "QueryData", "dbcode": "hgyd", "rowcode": "zb", "colcode": "sj",
            "wds": "[]",
            "dfwds": _json.dumps([
                {"wdcode": "zb", "valuecode": "A01080101"},
                {"wdcode": "sj", "valuecode": f"LAST{n_months}"},
            ]),
        }
        r = requests.get("https://data.stats.gov.cn/english/easyquery.htm",
                         params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        nodes = r.json().get("returndata", {}).get("datanodes", [])
        if not nodes:
            return pd.DataFrame()
        records = []
        for n in nodes:
            if not n["data"]["hasdata"]:
                continue
            period = [w["valuecode"] for w in n["wds"] if w["wdcode"] == "sj"][0]
            records.append({"date": pd.Timestamp(year=int(period[:4]), month=int(period[4:6]), day=1),
                            "value": n["data"]["data"] - 100})
        return pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.error("NBS PPI error: %s", e)
        return pd.DataFrame()


def fetch_eurostat_ici(years_back: int = 12) -> pd.DataFrame:
    """歐洲工業信心指標 (ICI) — Eurostat SDMX"""
    since_year = datetime.now().year - years_back
    for geo_code in ("EA20", "EA21", "EU27_2020"):
        try:
            url = (
                "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
                f"ei_bsin_m_r2/BS-ICI.SA.BAL.{geo_code}"
                f"?format=JSON&sinceTimePeriod={since_year}-01"
            )
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=30)
            if not r.ok:
                continue
            data = r.json()
            dims  = data.get("dimension", {})
            sizes = data.get("size", [])
            vals  = data.get("value", {})
            time_idx = dims.get("time", {}).get("category", {}).get("index", {})
            nt = sizes[-1] if sizes else len(time_idx)
            if not nt or not vals:
                continue
            inv_time = {v: k for k, v in time_idx.items()}
            records = []
            for pos_str, raw_val in vals.items():
                try:
                    period = inv_time.get(int(pos_str) % nt, "")
                    if len(period) != 7:
                        continue
                    records.append({"date": pd.Timestamp(period + "-01"), "value": float(raw_val) + 50.0})
                except (ValueError, TypeError):
                    continue
            if not records:
                continue
            df = pd.DataFrame(records).drop_duplicates(subset="date", keep="first").sort_values("date")
            cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
            result = df[df["date"] >= cutoff].reset_index(drop=True)
            if not result.empty:
                return result
        except Exception as e:
            logger.warning("Eurostat ICI (%s): %s", geo_code, e)
    return pd.DataFrame()
