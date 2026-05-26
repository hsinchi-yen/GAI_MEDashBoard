from __future__ import annotations

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


_NDC_JSON_CANDIDATES = [
    "https://index.ndc.gov.tw/n/api/leading",
    "https://index.ndc.gov.tw/api/leading",
    "https://index.ndc.gov.tw/api/v1/leading",
    "https://index.ndc.gov.tw/n/json/leading/data",
    "https://index.ndc.gov.tw/n/json/leading",   # 原始端點（SPA 化前仍可能有效）
]

_NDC_HTML_CANDIDATES = [
    "https://index.ndc.gov.tw/n/zh_TW",
    "https://index.ndc.gov.tw/n/zh_TW/trend",
]


def _parse_ndc_json_response(items: list, years_back: int) -> pd.DataFrame:
    records = []
    for item in items:
        ym = str(item.get('ym', '') or item.get('yearmonth', '') or item.get('date', '')).strip().replace('-', '')
        try:
            if len(ym) == 5:
                year, month = int(ym[:3]) + 1911, int(ym[3:])
            elif len(ym) == 6:
                year, month = int(ym[:4]), int(ym[4:])
            else:
                continue
            val = float(str(item.get('score', item.get('value', item.get('index', item.get('ci', '')))).replace(',', '')))
            records.append({'date': pd.Timestamp(year=year, month=month, day=1), 'value': val})
        except (ValueError, TypeError):
            continue
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records).dropna().sort_values('date')
    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return df[df['date'] >= cutoff].reset_index(drop=True)


def fetch_ndc_leading_index(years_back: int = 12) -> pd.DataFrame:
    """國家發展委員會景氣領先指標 — 依序嘗試多個 API 端點 + HTML fallback"""
    import warnings
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for url in _NDC_JSON_CANDIDATES:
        try:
            r = requests.get(url, headers=headers, timeout=15, verify=False)
            if not r.ok:
                continue
            ct = r.headers.get("content-type", "")
            # 過濾掉 Angular SPA 殼（回傳 HTML 而非 JSON）
            if "html" in ct and "json" not in ct:
                logger.debug("NDC JSON endpoint %s returned HTML, skipping", url)
                continue
            try:
                payload = r.json()
            except Exception:
                logger.debug("NDC endpoint %s: response not valid JSON", url)
                continue
            items = payload if isinstance(payload, list) else payload.get("data", payload.get("items", []))
            df = _parse_ndc_json_response(items, years_back)
            if not df.empty:
                logger.info("NDC Leading Index: fetched from %s (%d rows)", url, len(df))
                return df
        except Exception as e:
            logger.debug("NDC JSON candidate %s error: %s", url, e)

    # HTML fallback（嘗試解析表格）
    for html_url in _NDC_HTML_CANDIDATES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = requests.get(html_url, headers=headers, timeout=15, verify=False)
            if not r.ok:
                continue
            for tbl in pd.read_html(StringIO(r.text)):
                if tbl.shape[1] < 2:
                    continue
                col0 = tbl.iloc[:, 0].astype(str)
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
                        val = pd.to_numeric(tbl.iloc[idx, 1], errors='coerce')
                        if pd.notna(val):
                            records.append({'date': pd.Timestamp(year=year, month=month, day=1), 'value': float(val)})
                    except Exception:
                        continue
                if records:
                    dfr = pd.DataFrame(records).dropna().sort_values('date')
                    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
                    return dfr[dfr['date'] >= cutoff].reset_index(drop=True)
        except Exception as e:
            logger.warning("NDC HTML fallback %s error: %s", html_url, e)

    logger.error("NDC Leading Index: 所有端點均失敗")
    return pd.DataFrame()


def fetch_china_nbs_pmi(years_back: int = 12) -> pd.DataFrame:
    """中國製造業 PMI — NBS 端點境外 403，無免費替代月頻 PMI 源；永久回傳空"""
    # NBS data.stats.gov.cn 境外 IP 全面封鎖；OECD/MEI/FRED 均無中國月頻 PMI。
    # 比例制計分下，此指標視為缺值並排除分母，不影響其他 18 個指標的訊號正確性。
    logger.warning("China NBS PMI: no accessible source from outside China, returning empty")
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
    """中國 PPI YoY — IMF/IFS 月頻 PPI 指數轉 YoY (NBS 端點 403 後替代源)"""
    # IMF IFS M.CN.PPPI_IX = China Producer Price Index, monthly
    # 需多抓 2 年供 12 期 pct_change 使用
    df_idx = fetch_dbnomics("IMF", "IFS", "M.CN.PPPI_IX", years_back=years_back + 2)
    if not df_idx.empty:
        yoy = compute_yoy(df_idx)
        if not yoy.empty:
            cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
            return yoy[yoy["date"] >= cutoff].reset_index(drop=True)
    logger.error("China PPI: IMF/IFS source failed or empty")
    return pd.DataFrame()


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
