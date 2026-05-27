from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from .utils import compute_yoy, parse_minguo_ym

logger = logging.getLogger("gai_me.fetchers.taiwan")

_HDR_TWSE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.twse.com.tw/",
    "Accept": "application/json",
    "Accept-Language": "zh-TW,zh;q=0.9",
}


def fetch_taiwan_exports_amount() -> pd.DataFrame:
    """台灣出口總計(百萬美元) — 財政部"""
    url = (
        "https://web02.mof.gov.tw/njswww/webMain.aspx"
        "?sys=220&ym=10001&ymt=12012&kind=21&type=1&funid=i9121"
        "&cycle=41&outmode=0&compmode=00&outkind=1&cod00=1"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, verify=False, timeout=15)
        dfs = pd.read_html(StringIO(res.text))
        if len(dfs) < 2:
            return pd.DataFrame()
        df = dfs[1].copy()
        df.columns = ["date", "amount"] + list(df.columns[2:])
        df = df[['date', 'amount']]
        df = df[df['date'].astype(str).str.contains('月')]

        def _parse(x: str) -> pd.Timestamp:
            x = str(x).replace(' ', '').replace('年', '-').replace('月', '')
            parts = x.split('-')
            if len(parts) == 2:
                try:
                    return pd.Timestamp(year=int(parts[0]) + 1911, month=int(parts[1]), day=1)
                except ValueError:
                    pass
            return pd.NaT

        df['date']  = df['date'].apply(_parse)
        df['value'] = pd.to_numeric(df['amount'], errors='coerce')
        return df.dropna(subset=['date', 'value']).sort_values('date')[['date', 'value']]
    except Exception as e:
        logger.error("MOF scrape error: %s", e)
        return pd.DataFrame()


def fetch_cbc_money_supply(years_back: int = 12) -> dict:
    """台灣 M1B / M2 年增率 — 中央銀行 PDF"""
    import pdfplumber
    pdf_url = "https://www.cbc.gov.tw/public/data/economic/statistics/key/ms.pdf"
    result = {'m1b_yoy': pd.DataFrame(), 'm2_yoy': pd.DataFrame()}
    try:
        r = requests.get(pdf_url, timeout=25, verify=False)
        r.raise_for_status()
    except Exception as e:
        logger.error("CBC PDF download error: %s", e)
        return result
    try:
        rows_all = []
        with pdfplumber.open(BytesIO(r.content)) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    for row in table:
                        if row and row[0] and re.match(r'\d+年\d+月', str(row[0]).strip()):
                            rows_all.append(row)
        if not rows_all:
            return result
        records = []
        for row in rows_all:
            if len(row) < 13:
                continue
            dt = parse_minguo_ym(row[0])
            if pd.isna(dt):
                continue
            m1b = pd.to_numeric(str(row[8]).replace(',', '').strip(),  errors='coerce')
            m2  = pd.to_numeric(str(row[12]).replace(',', '').strip(), errors='coerce')
            records.append({'date': dt, 'm1b_yoy': m1b, 'm2_yoy': m2})
        df = pd.DataFrame(records).dropna(subset=['date']).sort_values('date')
        cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
        df = df[df['date'] >= cutoff]
        result['m1b_yoy'] = df[['date', 'm1b_yoy']].dropna().rename(columns={'m1b_yoy': 'value'}).reset_index(drop=True)
        result['m2_yoy']  = df[['date', 'm2_yoy']].dropna().rename(columns={'m2_yoy':  'value'}).reset_index(drop=True)
    except Exception as e:
        logger.error("CBC PDF parse error: %s", e)
    return result


def fetch_taiwan_pmi(years_back: int = 12) -> pd.DataFrame:
    """台灣製造業 PMI — CIER Excel"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        page_url = "https://www.cier.edu.tw/en/eco_cat/pmi-en/"
        res = requests.get(page_url, headers=headers, timeout=15, verify=False)
        res.raise_for_status()
        xlsx_urls = re.findall(r'href="(https?://[^"]*\.xlsx)"', res.text, re.IGNORECASE)
        pmi_urls  = [u for u in xlsx_urls if "pmi" in u.lower() or "cier" in u.lower()]
        if not xlsx_urls:
            return pd.DataFrame()
        xlsx_url = pmi_urls[0] if pmi_urls else xlsx_urls[0]
        r = requests.get(xlsx_url, headers=headers, timeout=20, verify=False)
        r.raise_for_status()
        df = pd.read_excel(BytesIO(r.content))
        df = df[[df.columns[0], df.columns[1]]].copy()
        df.columns = ['date', 'value']
        df['date']  = pd.to_datetime(df['date'],  errors='coerce')
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df.dropna().sort_values('date')
        cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
        return df[df['date'] >= cutoff].reset_index(drop=True)
    except Exception as e:
        logger.error("CIER PMI scrape error: %s", e)
        return pd.DataFrame()


def _tsmc_latest_yoy_twse() -> tuple[pd.Timestamp, float] | None:
    """TWSE OpenAPI t187ap05_L → 2330 最新月「去年同月增減(%)」(date, yoy)。"""
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
        for row in r.json():
            if row.get("公司代號") != "2330":
                continue
            ym = str(row.get("資料年月", "")).strip()          # ROC YYYMM 例 11504
            yoy = row.get("營業收入-去年同月增減(%)")
            if len(ym) == 5 and yoy is not None:
                date = pd.Timestamp(year=int(ym[:3]) + 1911, month=int(ym[3:]), day=1)
                return date, float(yoy)
    except Exception as e:
        logger.warning("TSMC TWSE OpenAPI latest fetch error: %s", e)
    return None


def fetch_tsmc_revenue_yoy(years_back: int = 5) -> pd.DataFrame:
    """台積電(2330)月營收 YoY — FinMind 歷史 + TWSE OpenAPI 補最新月。"""
    df = pd.DataFrame()
    try:
        start = (datetime.now() - relativedelta(years=years_back + 1)).strftime("%Y-%m-%d")
        params = {"dataset": "TaiwanStockMonthRevenue", "data_id": "2330", "start_date": start}
        token = os.environ.get("FINMIND_TOKEN")          # 免費註冊可取得，提升匿名速率限制
        if token:
            params["token"] = token
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
        r.raise_for_status()
        rows = r.json().get("data", [])
        recs = [{"date": pd.Timestamp(year=int(x["revenue_year"]), month=int(x["revenue_month"]), day=1),
                 "value": float(x["revenue"])}
                for x in rows if x.get("revenue") is not None]
        if recs:
            raw = pd.DataFrame(recs).drop_duplicates("date").sort_values("date").reset_index(drop=True)
            df = compute_yoy(raw)                       # value 轉為 YoY%
    except Exception as e:
        logger.error("TSMC revenue YoY (FinMind) fetch error: %s", e)

    # 以 TWSE 官方最新月覆蓋/補上（確保最新月即時、權威）
    latest = _tsmc_latest_yoy_twse()
    if latest is not None:
        ldate, lyoy = latest
        df = df[df["date"] != ldate] if not df.empty else df
        df = pd.concat([df, pd.DataFrame([{"date": ldate, "value": lyoy}])], ignore_index=True)

    if df.empty:
        return pd.DataFrame()
    df = df.dropna().sort_values("date").reset_index(drop=True)
    cutoff = pd.Timestamp(datetime.now() - relativedelta(years=years_back))
    return df[df["date"] >= cutoff].reset_index(drop=True)


def fetch_taiex_yoy(years_back: int = 12) -> pd.DataFrame:
    """TAIEX 月收 YoY — Yahoo Finance"""
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1mo&range=15y"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
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
        df = pd.DataFrame({"date": pd.to_datetime(timestamps, unit="s"), "value": closes})
        df = df.dropna().sort_values("date")
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=years_back + 1)
        return compute_yoy(df[df["date"] >= cutoff])
    except Exception as e:
        logger.error("TAIEX YoY fetch error: %s", e)
        return pd.DataFrame()


def fetch_tw_institutional(n_days: int = 5) -> dict:
    """台灣三大法人買賣超排行 — TWSE T86"""
    _TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"

    def _parse_num(s: str) -> int:
        try:
            return int(str(s).replace(",", "").replace("+", "").strip())
        except (ValueError, AttributeError):
            return 0

    aggregated: dict[str, dict] = {}
    days_collected = 0
    cursor = datetime.now() - timedelta(days=1)

    for _ in range(n_days + 25):
        if days_collected >= n_days:
            break
        if cursor.weekday() >= 5:
            cursor -= timedelta(days=1)
            continue
        date_str = cursor.strftime("%Y%m%d")
        try:
            resp = requests.get(
                _TWSE_T86,
                params={"response": "json", "date": date_str, "selectType": "ALLBUT0999"},
                headers=_HDR_TWSE,
                timeout=15,
            )
            if resp.status_code == 200:
                j = resp.json()
                if j.get("stat") == "OK" and j.get("data"):
                    fields = j.get("fields", [])
                    try:
                        total_col = fields.index("三大法人買賣超股數")
                    except ValueError:
                        total_col = -1
                    for row in j["data"]:
                        if len(row) < 3:
                            continue
                        code = str(row[0]).strip()
                        name = str(row[1]).strip()
                        net = _parse_num(row[total_col])
                        if code not in aggregated:
                            aggregated[code] = {"name": name, "net": 0}
                        aggregated[code]["net"] += net
                    days_collected += 1
        except Exception:
            pass
        time.sleep(0.6)
        cursor -= timedelta(days=1)

    if not aggregated:
        return {
            "top30_buy": pd.DataFrame(), "top30_sell": pd.DataFrame(),
            "actual_days": 0, "period_label": "無資料",
            "fetch_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }

    rows = [{"code": c, "name": v["name"], "net_shares": v["net"]}
            for c, v in aggregated.items() if v["net"] != 0]
    df_all = pd.DataFrame(rows)
    buy_df  = df_all[df_all["net_shares"] > 0].nlargest(30, "net_shares").reset_index(drop=True)
    sell_df = df_all[df_all["net_shares"] < 0].nsmallest(30, "net_shares").reset_index(drop=True)
    sell_df = sell_df.copy()
    sell_df["net_shares"] = sell_df["net_shares"].abs()

    # 補收盤價估算市值
    price_cursor = datetime.now() - timedelta(days=1)
    for _ in range(7):
        if price_cursor.weekday() < 5:
            break
        price_cursor -= timedelta(days=1)
    prices: dict[str, float] = {}
    try:
        presp = requests.get(
            "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL",
            params={"response": "json", "date": price_cursor.strftime("%Y%m%d")},
            headers=_HDR_TWSE, timeout=15,
        )
        if presp.status_code == 200:
            pj = presp.json()
            if pj.get("stat") == "OK":
                pfields = pj.get("fields", [])
                try:
                    close_col = pfields.index("收盤價")
                except ValueError:
                    close_col = 7
                for row in pj.get("data", []):
                    try:
                        p = float(str(row[close_col]).replace(",", ""))
                        if p > 0:
                            prices[str(row[0]).strip()] = p
                    except (ValueError, IndexError):
                        pass
    except Exception:
        pass

    def _add_value(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["est_value_億"] = df.apply(
            lambda r: round(r["net_shares"] * prices[r["code"]] / 1e8, 1)
            if r["code"] in prices and prices[r["code"]] > 0 else None,
            axis=1,
        )
        return df

    period_label = (
        f"近一週（{days_collected} 個交易日）" if n_days <= 5
        else f"近一月（{days_collected} 個交易日）"
    )
    return {
        "top30_buy":    _add_value(buy_df),
        "top30_sell":   _add_value(sell_df),
        "actual_days":  days_collected,
        "period_label": period_label,
        "fetch_date":   datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
