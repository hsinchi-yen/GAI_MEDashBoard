from __future__ import annotations

import logging
import re
from datetime import datetime
from io import BytesIO, StringIO

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .fred import fetch_fred, fetch_dbnomics
from .utils import compute_yoy, fetch_eastmoney_economy

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


_NDC_HOME = "https://index.ndc.gov.tw/n/zh_TW"
_NDC_API = "https://index.ndc.gov.tw/n/json/"
_NDC_CSRF_RE = re.compile(r'csrf-token"\s+content="([^"]+)"')


def _fetch_ndc_series(endpoint: str, years_back: int) -> pd.DataFrame:
    """NDC 景氣指標皆為 Angular SPA，需先取 csrf-token 再 POST。

    回應形如 {"line":[{"x":"202603","y":39}, ...]}，x 為 AD 年月(YYYYMM)。
    endpoint 例：leading（領先指標）、coincident（同時指標）、lightscore（景氣對策信號分數）。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Referer": _NDC_HOME,
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        s = requests.Session()
        home = s.get(_NDC_HOME, headers=headers, timeout=15, verify=False)
        m = _NDC_CSRF_RE.search(home.text)
        if not m:
            logger.error("NDC %s: csrf-token not found", endpoint)
            return pd.DataFrame()
        token = m.group(1)
        post_headers = {**headers, "X-CSRF-TOKEN": token}
        r = s.post(_NDC_API + endpoint, headers=post_headers, data={"_token": token},
                   timeout=15, verify=False)
        r.raise_for_status()
        line = r.json().get("line", [])
    except Exception as e:
        logger.error("NDC %s fetch error: %s", endpoint, e)
        return pd.DataFrame()

    records = []
    for pt in line:
        ym = str(pt.get("x", "")).strip()
        if len(ym) != 6 or pt.get("y") is None:
            continue
        try:
            records.append({"date": pd.Timestamp(year=int(ym[:4]), month=int(ym[4:]), day=1),
                            "value": float(pt["y"])})
        except (ValueError, TypeError):
            continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).dropna().sort_values("date").reset_index(drop=True)
    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return df[df["date"] >= cutoff].reset_index(drop=True)


def fetch_ndc_leading_index(years_back: int = 12) -> pd.DataFrame:
    """國家發展委員會景氣領先指標綜合指數（不含趨勢，2021=100）。"""
    return _fetch_ndc_series("leading", years_back)


def fetch_ndc_light_score(years_back: int = 12) -> pd.DataFrame:
    """國發會景氣對策信號綜合分數（9~45 分，對應藍/黃藍/綠/黃紅/紅燈）。"""
    return _fetch_ndc_series("lightscore", years_back)


def fetch_china_nbs_pmi(years_back: int = 12) -> pd.DataFrame:
    """中國官方製造業 PMI — 東方財富總經資料中心（NBS 數據，境外可存取）。"""
    # NBS data.stats.gov.cn 境外 403；改取東方財富 RPT_ECONOMY_PMI 的 MAKE_INDEX
    # （製造業 PMI 指數，50 為榮枯線），月頻、與官方一致。
    df = fetch_eastmoney_economy("RPT_ECONOMY_PMI", "MAKE_INDEX", years_back)
    if df.empty:
        logger.error("China NBS PMI: Eastmoney source failed or empty")
    return df


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
    """中國 PPI YoY — 東方財富總經資料中心（BASE_SAME 已是年增率%）。"""
    # 取代失效的 IMF/IFS M.CN.PPPI_IX；RPT_ECONOMY_PPI 的 BASE_SAME 直接是 PPI 同比。
    df = fetch_eastmoney_economy("RPT_ECONOMY_PPI", "BASE_SAME", years_back)
    if df.empty:
        logger.error("China PPI: Eastmoney source failed or empty")
    return df


def fetch_eurostat_ici(years_back: int = 12) -> pd.DataFrame:
    """歐洲工業信心指標 (ICI) — Eurostat SDMX（嘗試 5 維度/4 維度 × 3 地域碼）"""
    since_year = datetime.now().year - years_back
    for geo_code in ("EA20", "EA21", "EU27_2020"):
        # 先試加 freq 前綴的 5 維度格式（Eurostat 2024+ 新格式），再試原 4 維度
        for key_prefix in ("M.", ""):
            try:
                url = (
                    "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
                    f"ei_bsin_m_r2/{key_prefix}BS-ICI.SA.BAL.{geo_code}"
                    f"?format=JSON&sinceTimePeriod={since_year}-01"
                )
                r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=30)
                if not r.ok:
                    logger.debug("Eurostat ICI (%s prefix=%r): HTTP %s", geo_code, key_prefix, r.status_code)
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
                logger.warning("Eurostat ICI (%s prefix=%r): %s", geo_code, key_prefix, e)
    return pd.DataFrame()
