from __future__ import annotations

import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dateutil.relativedelta import relativedelta
import warnings
import re

warnings.filterwarnings('ignore') # 忽略些微的 pandas warnings

DBNOMICS_BASE = "https://api.db.nomics.world/v22/series"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

def fetch_dbnomics(provider, dataset, series, years_back=12):
    """從 DBnomics 抓取特定時間區段的數值"""
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
        values = doc.get("value", doc.get("observations", {}).get("value", []))
        
        df = pd.DataFrame({'date': periods, 'value': values})
        df = df.dropna()
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df['date'] = pd.to_datetime(df['date'], format='mixed', errors='coerce')
        df = df.dropna().sort_values('date')
        
        cutoff = datetime.now() - relativedelta(years=years_back)
        df = df[df['date'] >= pd.Timestamp(cutoff)]
        return df
    except Exception as e:
        print(f"DBnomics fetch error ({series}): {e}")
        return pd.DataFrame()

def fetch_fred(series_id, api_key, years_back=12):
    """從 FRED 抓取數值"""
    if not api_key:
        return pd.DataFrame()
    try:
        cutoff = datetime.now() - relativedelta(years=years_back)
        start_date = cutoff.strftime('%Y-%m-%d')
        params = {
            'series_id': series_id,
            'api_key': api_key,
            'file_type': 'json',
            'observation_start': start_date,
        }
        res = requests.get(FRED_BASE, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
        observations = data.get('observations', [])
        
        df = pd.DataFrame(observations)
        if df.empty: 
            return pd.DataFrame()
        
        df = df[df['value'] != '.']
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna().sort_values('date')
        return df[['date', 'value']]
    except Exception as e:
        print(f"FRED fetch error ({series_id}): {e}")
        return pd.DataFrame()

def compute_yoy(df):
    """計算年增率 (YoY)，假設輸入資料為月資料"""
    if df.empty or len(df) < 13:
        return pd.DataFrame()
    df = df.copy()
    # 月資料計算 YoY 為：取得 12 個月前的相對變化百分比
    df['value'] = df['value'].pct_change(12) * 100
    df = df.dropna()
    return df

def fetch_taiwan_exports_amount():
    """透過爬蟲自中華民國財政部抓取台灣出口總計(百萬美元)金額"""
    from io import StringIO
    # 直接涵蓋 2011 (100年) 到 2031 (120年) 以確保歷年與未來的資料都在爬取範圍
    url = "https://web02.mof.gov.tw/njswww/webMain.aspx?sys=220&ym=10001&ymt=12012&kind=21&type=1&funid=i9121&cycle=41&outmode=0&compmode=00&outkind=1&cod00=1"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        # verify=False 繞過公部門憑證問題
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        # 尋找網頁中的所有表格
        dfs = pd.read_html(StringIO(res.text))
        if len(dfs) < 2: return pd.DataFrame()
        df = dfs[1].copy()
        
        # 爬取表格的欄位整理 (我們只要日期和總計金額)
        df.columns = ["date", "amount"] + list(df.columns[2:])
        df = df[['date', 'amount']]
        
        # 排除整年加總的列，只保留 "月" 的資料列
        df = df[df['date'].astype(str).str.contains('月')]
        
        # 轉換民國年為西元年與 datetime 格式
        def parse_minguo(x):
            x = str(x).replace(' ', '').replace('年', '-').replace('月', '')
            parts = x.split('-')
            if len(parts) == 2:
                try:
                    y = int(parts[0]) + 1911
                    m = int(parts[1])
                    return pd.Timestamp(year=y, month=m, day=1)
                except ValueError:
                    pass
            return pd.NaT
        
        df['date'] = df['date'].apply(parse_minguo)
        df['value'] = pd.to_numeric(df['amount'], errors='coerce')
        df = df.dropna(subset=['date', 'value']).sort_values('date')
        
        return df[['date', 'value']]
    except Exception as e:
        print(f"MOF scrape error: {e}")
        return pd.DataFrame()


def _parse_minguo_ym(text):
    """將民國年月 (如 '115年02月') 轉為 pd.Timestamp"""
    text = str(text).replace(' ', '').replace(',', '')
    m = re.match(r'(\d+)年(\d+)月', text)
    if m:
        y = int(m.group(1)) + 1911
        month = int(m.group(2))
        return pd.Timestamp(year=y, month=month, day=1)
    return pd.NaT


def fetch_cbc_money_supply(years_back=12):
    """
    從中央銀行 PDF 報表爬取台灣 M1B / M2 年增率 (期底)。
    來源：https://www.cbc.gov.tw/public/data/economic/statistics/key/ms.pdf
    回傳 dict: {'m1b_yoy': DataFrame, 'm2_yoy': DataFrame}
    """
    import pdfplumber
    from io import BytesIO

    pdf_url = "https://www.cbc.gov.tw/public/data/economic/statistics/key/ms.pdf"
    result = {'m1b_yoy': pd.DataFrame(), 'm2_yoy': pd.DataFrame()}

    try:
        r = requests.get(pdf_url, timeout=25, verify=False)
        r.raise_for_status()
    except Exception as e:
        print(f"CBC PDF download error: {e}")
        return result

    try:
        rows_all = []
        with pdfplumber.open(BytesIO(r.content)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    for row in table:
                        # 只留有「年月」格式的資料列
                        if row and row[0] and re.match(r'\d+年\d+月', str(row[0]).strip()):
                            rows_all.append(row)

        if not rows_all:
            print("CBC PDF: no data rows parsed")
            return result

        # 表格結構 (13 欄):
        #  0: 年月
        #  1: M1A日平均金額, 2: M1A日平均年增率
        #  3: M1A期底金額,   4: M1A期底年增率
        #  5: M1B日平均金額, 6: M1B日平均年增率
        #  7: M1B期底金額,   8: M1B期底年增率
        #  9: M2日平均金額, 10: M2日平均年增率
        # 11: M2期底金額,   12: M2期底年增率
        records = []
        for row in rows_all:
            if len(row) < 13:
                continue
            dt = _parse_minguo_ym(row[0])
            if pd.isna(dt):
                continue
            # M1B 期底年增率 (index 8), M2 期底年增率 (index 12)
            m1b_yoy = pd.to_numeric(str(row[8]).replace(',', '').strip(), errors='coerce')
            m2_yoy = pd.to_numeric(str(row[12]).replace(',', '').strip(), errors='coerce')
            records.append({'date': dt, 'm1b_yoy': m1b_yoy, 'm2_yoy': m2_yoy})

        df = pd.DataFrame(records).dropna(subset=['date']).sort_values('date')

        cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
        df = df[df['date'] >= cutoff]

        m1b = df[['date', 'm1b_yoy']].dropna().rename(columns={'m1b_yoy': 'value'})
        m2 = df[['date', 'm2_yoy']].dropna().rename(columns={'m2_yoy': 'value'})
        result['m1b_yoy'] = m1b.reset_index(drop=True)
        result['m2_yoy'] = m2.reset_index(drop=True)

    except ImportError:
        print("CBC PDF: pdfplumber not installed. Run: pip install pdfplumber")
    except Exception as e:
        print(f"CBC PDF parse error: {e}")

    return result


def fetch_taiwan_pmi(years_back=12):
    """
    從中華經濟研究院 (CIER) 下載台灣製造業 PMI 歷史 Excel。
    來源：https://www.cier.edu.tw/en/eco_cat/pmi-en/
    Excel 連結每月更新，路徑含年月，故先爬網頁取得最新連結。
    """
    from io import BytesIO
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        # 1. 從 CIER PMI 英文頁面找到最新 Excel 下載連結
        page_url = "https://www.cier.edu.tw/en/eco_cat/pmi-en/"
        res = requests.get(page_url, headers=headers, timeout=15, verify=False)
        res.raise_for_status()

        # 優先找含 PMI 的 xlsx；退而求其次取頁面上第一個 xlsx
        xlsx_urls = re.findall(
            r'href="(https?://[^"]*\.xlsx)"',
            res.text,
            re.IGNORECASE,
        )
        pmi_urls = [u for u in xlsx_urls if "pmi" in u.lower() or "cier" in u.lower()]
        if not xlsx_urls:
            print("CIER PMI: no Excel link found on page")
            return pd.DataFrame()

        xlsx_url = pmi_urls[0] if pmi_urls else xlsx_urls[0]

        # 2. 下載 Excel
        r = requests.get(xlsx_url, headers=headers, timeout=20, verify=False)
        r.raise_for_status()

        df = pd.read_excel(BytesIO(r.content))

        # 3. 解析：第一欄是日期，第二欄是 Manufacturing PMI
        date_col = df.columns[0]
        pmi_col = df.columns[1]

        df = df[[date_col, pmi_col]].copy()
        df.columns = ['date', 'value']

        # 移除標題列 (非數值)
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna().sort_values('date')

        cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
        df = df[df['date'] >= cutoff].reset_index(drop=True)

        return df

    except Exception as e:
        print(f"CIER PMI scrape error: {e}")
        return pd.DataFrame()


def fetch_ism_pmi(years_back=12, fred_key=None):
    """
    美國 ISM 製造業 PMI — DBnomics ISM 5 項子指標平均為歷史底倉；
    FRED NAPM（ISM Manufacturing PMI）補最新月份 fallback，解決 DBnomics 落後 3~4 個月的資料缺口。
    來源：https://db.nomics.world/ISM + FRED NAPM
    """
    sub_datasets = ['neword', 'production', 'employment', 'supdel', 'inventories']
    all_dfs = {}

    for ds in sub_datasets:
        try:
            url = f"{DBNOMICS_BASE}/ISM/{ds}/in?observations=1"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()
            docs = data.get('series', {}).get('docs', [])
            if not docs:
                continue
            d = docs[0]
            df = pd.DataFrame({
                'date': d.get('period', []),
                ds: d.get('value', []),
            })
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df[ds] = pd.to_numeric(df[ds], errors='coerce')
            all_dfs[ds] = df.dropna()
        except Exception as e:
            print(f"ISM sub-index {ds} error: {e}")

    historic = pd.DataFrame()
    if len(all_dfs) >= 5:
        merged = all_dfs[sub_datasets[0]]
        for ds in sub_datasets[1:]:
            merged = merged.merge(all_dfs[ds], on='date', how='inner')

        merged['value'] = merged[sub_datasets].mean(axis=1)
        historic = merged[['date', 'value']].sort_values('date')
    elif len(all_dfs) > 0:
        print(f"ISM PMI: only {len(all_dfs)}/5 sub-indices, using available data")

    # FRED NAPM fallback — 補 DBnomics 尚未更新的最新月份
    result = historic
    if fred_key:
        napm = fetch_fred('NAPM', fred_key, years_back=years_back)
        if not napm.empty:
            if historic.empty:
                result = napm
            else:
                last_dbn = historic['date'].max()
                tail = napm[napm['date'] > last_dbn]
                if not tail.empty:
                    result = pd.concat([historic, tail], ignore_index=True).sort_values('date')

    if result.empty:
        print("ISM PMI: no data available from DBnomics or FRED")
        return pd.DataFrame()

    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return result[result['date'] >= pd.Timestamp(cutoff)].reset_index(drop=True)


def fetch_ndc_leading_index(years_back=12):
    """
    國家發展委員會景氣領先指標分數 (NDC CLI) — 爬取 NDC 官方 JSON API。
    失敗時回傳空 DataFrame（dashboard 顯示「資料暫時無法取得」）。
    來源：https://index.ndc.gov.tw/
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        api_url = "https://index.ndc.gov.tw/n/json/leading"
        r = requests.get(api_url, headers=headers, timeout=15, verify=False)
        if r.ok:
            items = r.json()
            records = []
            for item in items:
                ym = str(item.get('ym', '') or item.get('yearmonth', '')).strip().replace('-', '')
                # 支援民國年月格式 (e.g. "11410") 或西元年月 (e.g. "202410")
                try:
                    if len(ym) == 5:  # 民國年月 (RRRmm)
                        year  = int(ym[:3]) + 1911
                        month = int(ym[3:])
                    elif len(ym) == 6:  # 西元年月 (YYYYmm)
                        year  = int(ym[:4])
                        month = int(ym[4:])
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
        print(f"NDC Leading Index API error: {e}")

    # Fallback: 解析 NDC HTML 表格
    try:
        from io import StringIO
        page_url = "https://index.ndc.gov.tw/n/zh_TW"
        r = requests.get(page_url, headers=headers, timeout=15, verify=False)
        if r.ok:
            dfs = pd.read_html(StringIO(r.text))
            for df in dfs:
                if df.shape[1] < 2:
                    continue
                # 尋找包含「領先」或有民國年月格式的表格
                col0 = df.iloc[:, 0].astype(str)
                date_rows = col0[col0.str.match(r'^\d{3}/\d{2}$|^\d{5}$')]
                if date_rows.empty:
                    continue
                records = []
                for idx in date_rows.index:
                    try:
                        ym_str = col0[idx].replace('/', '')
                        if len(ym_str) == 5:
                            year  = int(ym_str[:3]) + 1911
                            month = int(ym_str[3:])
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
        print(f"NDC Leading Index HTML fallback error: {e}")

    print("NDC Leading Index: 無法從官方網站取得資料")
    return pd.DataFrame()


def fetch_tsmc_revenue_yoy(years_back=5):
    """
    台積電 (2330) 月營收年增率 (YoY %) — TWSE MOPS 公開資訊觀測站。
    失敗時回傳空 DataFrame（自動降級顯示 N/A）。
    來源：https://mops.twse.com.tw/
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    "https://mops.twse.com.tw/",
    }
    try:
        from io import StringIO
        url = "https://mops.twse.com.tw/mops/web/ajax_t05st10_ifrs"
        post_data = {
            "encodeURIComponent": "1", "step": "1", "firstin": "1",
            "off": "1", "co_id": "2330", "TYPEK": "sii",
        }
        r = requests.post(url, data=post_data, headers=headers, timeout=20)
        r.raise_for_status()
        dfs = pd.read_html(StringIO(r.text))
        if not dfs:
            return pd.DataFrame()

        for df in dfs:
            if df.shape[1] < 4 or df.shape[0] < 3:
                continue
            # 展平多層欄位
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = ['_'.join(str(c) for c in col).strip() for col in df.columns]
            col0 = df.iloc[:, 0].astype(str)
            # 尋找含民國年月或年/月格式的行
            date_mask = col0.str.match(r'^\d{3}\s*年\s*\d{1,2}\s*月|^\d{3}/\d{2}$')
            if not date_mask.any():
                continue

            records = []
            for idx in df[date_mask].index:
                row = df.iloc[idx]
                # 解析日期
                ym_str = str(row.iloc[0])
                m = re.match(r'(\d+)\s*[年/]\s*(\d+)', ym_str)
                if not m:
                    continue
                year  = int(m.group(1)) + 1911
                month = int(m.group(2))
                # 找「去年同月增減(%)」欄位
                yoy_val = None
                for col_name in df.columns:
                    col_lower = str(col_name).lower()
                    if any(kw in col_lower for kw in ('去年同月', 'yoy', '年增', '年同')):
                        try:
                            yoy_val = float(str(row[col_name]).replace(',', '').replace('%', ''))
                            break
                        except (ValueError, TypeError):
                            continue
                # 若無標記欄位，嘗試第 4 欄（通常是 YoY）
                if yoy_val is None:
                    try:
                        yoy_val = float(str(row.iloc[3]).replace(',', '').replace('%', ''))
                    except (ValueError, TypeError):
                        pass
                if yoy_val is not None:
                    records.append({'date': pd.Timestamp(year=year, month=month, day=1), 'value': yoy_val})

            if records:
                df_out = pd.DataFrame(records).dropna().sort_values('date')
                cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
                return df_out[df_out['date'] >= cutoff].reset_index(drop=True)

    except Exception as e:
        print(f"TSMC revenue YoY fetch error: {e}")
    return pd.DataFrame()


def fetch_korea_exports_yoy(api_key, years_back=12):
    """
    韓國出口 YoY — FRED XTEXVA01KRM664S
    韓國每月 1 日前後公布上月出口，比台灣財政部早 2~3 週，是全球電子需求的最早官方高頻訊號。
    """
    raw = fetch_fred('XTEXVA01KRM664S', api_key, years_back=years_back + 1)
    return compute_yoy(raw)


def fetch_copper_yoy(api_key, years_back=12):
    """
    銅價 YoY — FRED PCOPPUSDM（月頻）
    「銅博士」：工業需求的市場定價代理，歷史上比 OECD CLI 早 1~2 季觸底/觸頂。
    """
    raw = fetch_fred('PCOPPUSDM', api_key, years_back=years_back + 1)
    return compute_yoy(raw)


def fetch_hy_spread(api_key, years_back=12):
    """
    HY 信用利差 (ICE BofA High Yield OAS) — FRED BAMLH0A0HYM2
    信用市場的「壓力計」：往往在 VIX 飆升前 2~6 週先行擴大，是 C 板最直接的領先風險訊號。
    """
    return fetch_fred('BAMLH0A0HYM2', api_key, years_back=years_back)


def fetch_twd_usd(api_key, years_back=12):
    """
    台幣匯率 TWD/USD — FRED DEXTAUS（日頻）
    台幣升值（數值下降）= 外資淨流入 + 出口商拋匯；急貶 = 外資撤離或全球風險惡化。
    """
    return fetch_fred('DEXTAUS', api_key, years_back=years_back)


def fetch_china_nbs_pmi(years_back=12):
    """
    中國製造業 PMI — 國家統計局 (NBS) 官方數據。
    來源：https://data.stats.gov.cn/english/
    指標代碼 A0B0101 = 製造業採購經理指數(%)
    """
    import json as _json
    try:
        n_months = years_back * 12
        params = {
            "m": "QueryData",
            "dbcode": "hgyd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": "[]",
            "dfwds": _json.dumps([
                {"wdcode": "zb", "valuecode": "A0B0101"},
                {"wdcode": "sj", "valuecode": f"LAST{n_months}"},
            ]),
        }
        r = requests.get(
            "https://data.stats.gov.cn/english/easyquery.htm",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        nodes = data.get("returndata", {}).get("datanodes", [])
        if not nodes:
            return pd.DataFrame()

        records = []
        for n in nodes:
            period = [w["valuecode"] for w in n["wds"] if w["wdcode"] == "sj"][0]
            val = n["data"]["data"]
            has = n["data"]["hasdata"]
            if not has:
                continue
            year = int(period[:4])
            month = int(period[4:6])
            records.append({"date": pd.Timestamp(year=year, month=month, day=1), "value": val})

        df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
        return df

    except Exception as e:
        print(f"NBS PMI error: {e}")
        return pd.DataFrame()


def fetch_japan_economy_watchers(years_back=12):
    """
    日本景氣觀測 DI — 內閣府 Economy Watchers Survey (製造業部門、季調)。
    DI 以 50 為中性線，與 PMI 相同判讀方式。
    來源：https://www5.cao.go.jp/keizai3/watcher-e/
    """
    from io import BytesIO
    xls_url = "https://www5.cao.go.jp/keizai3/watcher-e/di.xls"
    headers_req = {"User-Agent": "Mozilla/5.0"}

    try:
        r = requests.get(xls_url, headers=headers_req, timeout=20)
        r.raise_for_status()

        # Sheet '3. DI by sector(SA)' 含製造業欄位
        df = pd.read_excel(BytesIO(r.content), sheet_name='3. DI by sector(SA)', header=None)

        # 欄位: 0=Year, 1=Month, 2=Total, ..., 9=Manufacturing
        MONTH_MAP = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                     'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}

        year_current = None
        records = []
        for idx in range(7, len(df)):  # 資料從 row 7 開始
            row = df.iloc[idx]
            if pd.notna(row[0]) and str(row[0]).strip().replace('.0', '').isdigit():
                year_current = int(float(row[0]))

            month_str = str(row[1]).strip() if pd.notna(row[1]) else ''
            if month_str in MONTH_MAP and year_current:
                mfg_di = pd.to_numeric(row[9], errors='coerce')  # 製造業
                if pd.notna(mfg_di):
                    records.append({
                        'date': pd.Timestamp(year=year_current, month=MONTH_MAP[month_str], day=1),
                        'value': mfg_di,
                    })

        df_out = pd.DataFrame(records).sort_values('date')
        # XLS 含多張表格 (現況/未來/回應率)，同一日期取首筆 (現況)
        df_out = df_out.drop_duplicates(subset='date', keep='first')
        cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
        return df_out[df_out['date'] >= cutoff].reset_index(drop=True)

    except Exception as e:
        print(f"Japan Economy Watchers error: {e}")
        return pd.DataFrame()


def fetch_china_nbs_ppi_yoy(years_back=12):
    """
    中國工業生產者出廠價格指數 (PPI) YoY — 國家統計局 (NBS)。
    指標 A01080101 回傳以上年同月=100 的指數，此函式轉換為 YoY%。
    來源：https://data.stats.gov.cn/english/
    """
    import json as _json
    try:
        n_months = years_back * 12
        params = {
            "m": "QueryData",
            "dbcode": "hgyd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": "[]",
            "dfwds": _json.dumps([
                {"wdcode": "zb", "valuecode": "A01080101"},
                {"wdcode": "sj", "valuecode": f"LAST{n_months}"},
            ]),
        }
        r = requests.get(
            "https://data.stats.gov.cn/english/easyquery.htm",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        nodes = data.get("returndata", {}).get("datanodes", [])
        if not nodes:
            return pd.DataFrame()

        records = []
        for n in nodes:
            period = [w["valuecode"] for w in n["wds"] if w["wdcode"] == "sj"][0]
            val = n["data"]["data"]
            has = n["data"]["hasdata"]
            if not has:
                continue
            year = int(period[:4])
            month = int(period[4:6])
            # NBS 回傳值以 100 為基準 (上年同月=100)，轉換為 YoY%
            records.append({"date": pd.Timestamp(year=year, month=month, day=1), "value": val - 100})

        df = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
        return df

    except Exception as e:
        print(f"NBS PPI error: {e}")
        return pd.DataFrame()


def fetch_sp500_yoy(api_key, years_back=12):
    """
    S&P 500 月收指數 YoY (%) — FRED SP500
    用於與 TAIEX 做跨市場比對，反映美股多空動能。
    """
    raw = fetch_fred('SP500', api_key, years_back=years_back + 1)
    if raw is None or raw.empty:
        return pd.DataFrame()
    # SP500 為日頻；取月末收盤
    raw = raw.copy()
    raw['ym'] = raw['date'].dt.to_period('M')
    raw = raw.groupby('ym').last().reset_index()
    raw['date'] = raw['ym'].dt.to_timestamp('M')
    raw = raw[['date', 'value']].sort_values('date')
    return compute_yoy(raw)


def fetch_taiex_yoy(years_back=12):
    """
    台灣加權股價指數 (TAIEX / ^TWII) 月收 YoY (%) — Yahoo Finance 非官方 API。
    失敗時回傳空 DataFrame。
    """
    try:
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII"
            "?interval=1mo&range=15y"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        body = res.json()
        result_data = body.get("chart", {}).get("result", [])
        if not result_data:
            return pd.DataFrame()
        timestamps = result_data[0].get("timestamp", [])
        closes = result_data[0].get("indicators", {}).get("adjclose", [{}])[0].get("adjclose", [])
        if not timestamps or not closes:
            return pd.DataFrame()
        df = pd.DataFrame({
            "date": pd.to_datetime(timestamps, unit="s"),
            "value": closes,
        })
        df = df.dropna().sort_values("date")
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back + 1)
        df = df[df["date"] >= cutoff]
        return compute_yoy(df)
    except Exception as e:
        print(f"TAIEX YoY fetch error: {e}")
        return pd.DataFrame()


def fetch_fed_funds_rate(api_key, years_back=12):
    """
    聯準會有效聯邦基金利率 (DFF) — FRED，日頻取月均。
    反映美國貨幣政策寬緊，對股市估值影響最直接。
    """
    raw = fetch_fred('DFF', api_key, years_back=years_back)
    if raw is None or raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    raw['ym'] = raw['date'].dt.to_period('M')
    monthly = raw.groupby('ym')['value'].mean().reset_index()
    monthly['date'] = monthly['ym'].dt.to_timestamp()
    return monthly[['date', 'value']].sort_values('date').reset_index(drop=True)


def fetch_t10y3m(api_key, years_back=12):
    """
    10年-3個月美債利差 (T10Y3M) — FRED。
    比 10Y-2Y 更早預測衰退；倒掛後解除轉正是衰退即將到來的強烈信號。
    """
    return fetch_fred('T10Y3M', api_key, years_back=years_back)


def fetch_us_new_orders_yoy(api_key, years_back=12):
    """
    美國製造業新訂單 YoY (%) — FRED AMTMNO。
    製造業需求端前端訊號，領先工業生産約 1~2 季。
    """
    raw = fetch_fred('AMTMNO', api_key, years_back=years_back + 1)
    return compute_yoy(raw) if raw is not None and not raw.empty else pd.DataFrame()


def fetch_eurostat_ici(years_back=12):
    """
    歐洲工業信心指標 (ICI) — Eurostat ei_bsin_m_r2 BS-ICI SA BAL EA20
    改用 SDMX 2.1 path-filter URL 鎖定單一序列，解決 flat-index 偏移導致資料停在 2025-12 的問題。
    原始值以 0 為中性 (balance)；此函式加 50 使其對齊 PMI 50 榮枯線。
    """
    since_year = datetime.now().year - years_back
    for geo_code in ("EA20", "EA21", "EU27_2020"):
        try:
            # Path-based filter 鎖定 BS-ICI / SA / BAL / {geo}，讓 value key 直接等於 time position
            url = (
                "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/"
                f"ei_bsin_m_r2/BS-ICI.SA.BAL.{geo_code}"
                f"?format=JSON&sinceTimePeriod={since_year}-01"
            )
            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                timeout=30,
            )
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
                    # flat % nt 取出 time position（不論序列數量均正確）
                    t_pos  = int(pos_str) % nt
                    period = inv_time.get(t_pos, "")
                    if len(period) != 7:
                        continue
                    records.append({
                        "date":  pd.Timestamp(period + "-01"),
                        "value": float(raw_val) + 50.0,
                    })
                except (ValueError, TypeError):
                    continue

            if not records:
                continue

            df = (
                pd.DataFrame(records)
                .drop_duplicates(subset="date", keep="first")
                .sort_values("date")
            )
            cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
            result = df[df["date"] >= cutoff].reset_index(drop=True)
            if not result.empty:
                return result
        except Exception as e:
            print(f"Eurostat ICI ({geo_code}): {e}")

    return pd.DataFrame()


# ──────────────────────────────────────────────────────────────────────────────
# Panel E 新增：ETF 批次抓取 (共享快取，避免 sector_rotation 和 13f_proxy 重複 API 呼叫)
# ──────────────────────────────────────────────────────────────────────────────

SECTOR_ETFS = {
    "cyclical":  ["XLY", "XLI", "XLB", "XLF"],
    "defensive": ["XLP", "XLU", "XLV", "XLRE"],
}
_ALL_SECTOR_ETFS = SECTOR_ETFS["cyclical"] + SECTOR_ETFS["defensive"]

_ETF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":     "application/json",
}


def _fetch_etf_monthly(ticker: str, years_back: int = 8) -> dict:
    """Single-ticker Yahoo Finance monthly fetch; returns raw prices + volumes."""
    range_str = f"{years_back}y"
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?interval=1mo&range={range_str}"
    )
    try:
        res = requests.get(url, headers=_ETF_HEADERS, timeout=15)
        res.raise_for_status()
        body = res.json()
        result_data = body.get("chart", {}).get("result", [])
        if not result_data:
            print(f"ETF fetch: no result for {ticker}")
            return {}
        ts = result_data[0].get("timestamp", [])
        inds = result_data[0].get("indicators", {})
        closes  = inds.get("adjclose", [{}])[0].get("adjclose", [])
        volumes = inds.get("quote",    [{}])[0].get("volume",   [])
        if not ts:
            return {}
        dates = pd.to_datetime(ts, unit="s")
        return {"dates": dates, "closes": closes, "volumes": volumes}
    except Exception as e:
        print(f"ETF fetch error ({ticker}): {e}")
        return {}


def fetch_etf_bulk(years_back: int = 8) -> dict:
    """
    批次抓取所有板塊 ETF 的月頻收盤價與成交量（並行 8 個 API 呼叫）。
    回傳 dict：{ticker → {'dates', 'closes', 'volumes'}}
    供 fetch_sector_rotation() 與 fetch_13f_proxy() 共用，避免重複抓取。
    """
    result: dict = {}
    with ThreadPoolExecutor(max_workers=len(_ALL_SECTOR_ETFS)) as pool:
        futures = {pool.submit(_fetch_etf_monthly, t, years_back): t for t in _ALL_SECTOR_ETFS}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                result[ticker] = future.result()
            except Exception as e:
                print(f"ETF bulk fetch failed ({ticker}): {e}")
                result[ticker] = {}
    return result


def _etf_bulk_to_prices(etf_bulk: dict) -> pd.DataFrame:
    """將 etf_bulk 轉為 DataFrame(index=date, columns=tickers)，只保留收盤價。"""
    series = {}
    for ticker, raw in etf_bulk.items():
        if not raw:
            continue
        df = pd.DataFrame({
            "date":  pd.to_datetime(raw["dates"], errors="coerce"),
            ticker:  pd.to_numeric(raw["closes"], errors="coerce"),
        }).dropna(subset=[ticker]).set_index("date")
        df = df[df.index.notna()]  # drop NaT index rows
        series[ticker] = df[ticker]
    return pd.DataFrame(series)


def _etf_bulk_to_volumes(etf_bulk: dict) -> pd.DataFrame:
    """將 etf_bulk 轉為 DataFrame(index=date, columns=tickers)，只保留成交量。"""
    series = {}
    for ticker, raw in etf_bulk.items():
        if not raw:
            continue
        df = pd.DataFrame({
            "date":   pd.to_datetime(raw["dates"], errors="coerce"),
            "volume": pd.to_numeric(raw["volumes"], errors="coerce"),
        }).dropna(subset=["volume"]).set_index("date")
        df = df[df.index.notna()]  # drop NaT index rows
        series[ticker] = df["volume"]
    return pd.DataFrame(series)


# ──────────────────────────────────────────────────────────────────────────────
# Panel E 新增：內部輪動指數 (Sector Rotation)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_sector_rotation(etf_bulk: dict | None = None, years_back: int = 5) -> pd.DataFrame:
    """
    內部輪動指數 — 景氣循環籃子 vs 防禦籃子 3M 滾動超額報酬。

    景氣循環籃子 ETF：XLY, XLI, XLB, XLF
    防禦籃子 ETF  ：XLP, XLU, XLV, XLRE
    計算方式（依計畫書 §6 規格）：
        cyc_3m = 循環籃子 3 個月等權複合報酬
        def_3m = 防禦籃子 3 個月等權複合報酬
        value  = cyc_3m − def_3m  （超額報酬，%）
        → 正值 = 景氣循環月近 3M 領先（Risk-On）
        → 負值 = 防禦月近 3M 領先（Risk-Off）

    etf_bulk: 若提供則直接使用（避免重複 API 呼叫），否則自行抓取。
    回傳 DataFrame(date, value)，value 為超額報酬（小數）。
    """
    CYCLICAL  = SECTOR_ETFS["cyclical"]
    DEFENSIVE = SECTOR_ETFS["defensive"]

    if etf_bulk is not None:
        prices = _etf_bulk_to_prices(etf_bulk)
    else:
        bulk = fetch_etf_bulk(years_back=years_back + 1)
        prices = _etf_bulk_to_prices(bulk)

    if prices.empty:
        print("Sector rotation: no ETF price data available")
        return pd.DataFrame()

    now = pd.Timestamp.now()  # cache once to avoid dual-call race across midnight
    cutoff = now - pd.DateOffset(years=years_back + 1)
    prices = prices[prices.index >= cutoff].dropna(how="all")

    cyc_tickers = [t for t in CYCLICAL  if t in prices.columns]
    def_tickers = [t for t in DEFENSIVE if t in prices.columns]

    if not cyc_tickers or not def_tickers:
        print(f"Sector rotation: missing ETFs — cyc={cyc_tickers}, def={def_tickers}")
        return pd.DataFrame()

    # 月報酬
    rets = prices.pct_change().dropna(how="all")
    cyc_ret = rets[cyc_tickers].mean(axis=1)
    def_ret = rets[def_tickers].mean(axis=1)

    # 3M 滾動複合報酬（計畫書規格：rolling product of 1+r over 3 months）
    cyc_3m = (1 + cyc_ret).rolling(3).apply(lambda x: x.prod(), raw=True) - 1
    def_3m = (1 + def_ret).rolling(3).apply(lambda x: x.prod(), raw=True) - 1

    excess = (cyc_3m - def_3m).dropna().reset_index()
    excess.columns = ["date", "value"]

    cutoff_out = now - pd.DateOffset(years=years_back)
    return excess[excess["date"] >= cutoff_out].reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────────
# Panel E 新增：13F 持股淨加碼比 (SEC EDGAR Proxy)
# ──────────────────────────────────────────────────────────────────────────────

def fetch_13f_proxy(etf_bulk: dict | None = None, api_key=None, years_back: int = 5) -> pd.DataFrame:
    """
    13F 循環/防禦淨加碼比 — 代理版本 (Phase 1)。

    完整 SEC EDGAR 13F 解析因數據量龐大（每季數千份申報），列為 Phase 2 實作。
    本代理版本使用 ETF 成交量加速度差值估算機構資金方向：
        ratio = 循環 ETF 3M 量能加速度 − 防禦 ETF 3M 量能加速度
        正值 = 機構資金流入偏向景氣循環（與 13F 淨加碼方向正相關）

    etf_bulk: 若提供則直接使用（避免重複 API 呼叫），否則自行抓取。
    資料來源：Yahoo Finance volume data (月頻)
    注意：此代理指標的方向性與實際 13F 之相關性為估計值；
          SEC EDGAR 版本完成後（Phase 2），此函式會被取代。
    """
    CYCLICAL  = SECTOR_ETFS["cyclical"]
    DEFENSIVE = SECTOR_ETFS["defensive"]

    if etf_bulk is not None:
        vols = _etf_bulk_to_volumes(etf_bulk)
    else:
        bulk = fetch_etf_bulk(years_back=years_back + 1)
        vols = _etf_bulk_to_volumes(bulk)

    if vols.empty:
        print("13F proxy: no ETF volume data available")
        return pd.DataFrame()

    cyc_t = [t for t in CYCLICAL  if t in vols.columns]
    def_t = [t for t in DEFENSIVE if t in vols.columns]

    if not cyc_t or not def_t:
        return pd.DataFrame()

    cyc_vol   = vols[cyc_t].mean(axis=1).rolling(3).mean()
    def_vol   = vols[def_t].mean(axis=1).rolling(3).mean()
    cyc_accel = cyc_vol.pct_change(3)
    def_accel = def_vol.pct_change(3)

    ratio = (cyc_accel - def_accel).dropna().reset_index()
    ratio.columns = ["date", "value"]

    cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back)
    return ratio[ratio["date"] >= cutoff].reset_index(drop=True)


def fetch_dxy(api_key, years_back=12):
    """
    美元指數 (DXY proxy) — FRED DTWEXBGS 貿易加權廣義美元指數（月頻）。
    美元升值 = 全球流動性緊縮、新興市場資金外流壓力；
    降息循環下美元走弱通常利好風險資產與商品。
    """
    return fetch_fred('DTWEXBGS', api_key, years_back=years_back)


def fetch_china_credit_impulse(api_key, years_back=12):
    """
    中國信貸脈衝 — M2 YoY 增速的 12 個月差分（加速度）。
    正值 = 信貸擴張加速，領先全球總需求約 9~12 個月回升；
    負值 = 信貸收縮，領先需求轉弱。
    主要來源：FRED MYAGM2CNM189N（中國 M2，月頻）
    備援：DBnomics OECD MEI CHN.MABMM201.STSA.M
    """
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
