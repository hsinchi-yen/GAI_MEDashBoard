from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

logger = logging.getLogger("gai_me.fetchers.edgar_13f")

_EDGAR_BASE     = "https://data.sec.gov"
_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_EDGAR_HEADERS  = {"User-Agent": "GAI_MEDashBoard hsinchi.yen@gmail.com"}

_13F_MAJOR_FUNDS: dict[str, str] = {
    "Berkshire Hathaway":  "0001067983",
    "Citadel Advisors":    "0001423053",
    "Two Sigma":           "0001179392",
    "Millennium Mgmt":     "0001273087",
    "D.E. Shaw":           "0001009207",
    "AQR Capital":         "0001167557",
    "Point72":             "0001603466",
    "Tiger Global":        "0001167483",
    "Viking Global":       "0001101785",
    "Lone Pine Capital":   "0001061165",
    "Pershing Square":     "0001336528",
    "Third Point":         "0001040273",
    "Baupost Group":       "0001054420",
    "Appaloosa Mgmt":      "0001006438",
    "Coatue Management":   "0001135730",
    "Greenlight Capital":  "0001079114",
    "Maverick Capital":    "0000934639",
    "Eminence Capital":    "0001107310",
    "Glenview Capital":    "0001138995",
    "Starboard Value":     "0001517137",
}

_RE_WS = re.compile(r'\s+')


def _clean_issuer_name(name: str, maxlen: int = 30) -> str:
    name = _RE_WS.sub(' ', name.strip())
    return name if len(name) <= maxlen else name[:maxlen - 1] + '…'


def _edgar_get_13f_accessions(cik: str, n: int = 2) -> list[dict]:
    try:
        url = f"{_EDGAR_BASE}/submissions/CIK{cik}.json"
        res = requests.get(url, headers=_EDGAR_HEADERS, timeout=15)
        res.raise_for_status()
        data = res.json()
        recent       = data.get("filings", {}).get("recent", {})
        forms        = recent.get("form", [])
        accessions   = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])
        filing_dates = recent.get("filingDate", [])
        by_period: dict[str, dict] = {}
        for form, acc, rd, fd in zip(forms, accessions, report_dates, filing_dates):
            if form not in ("13F-HR", "13F-HR/A"):
                continue
            if rd not in by_period or fd > by_period[rd]["filingDate"]:
                by_period[rd] = {"accession": acc, "reportDate": rd, "filingDate": fd}
        return sorted(by_period.values(), key=lambda x: x["reportDate"], reverse=True)[:n]
    except Exception as e:
        logger.error("EDGAR accessions error (CIK=%s): %s", cik, e)
        return []


def _edgar_get_infotable_url(cik: str, accession: str) -> str | None:
    try:
        cik_path   = str(int(cik))
        acc_nodash = accession.replace("-", "")
        index_url  = f"{_EDGAR_ARCHIVES}/{cik_path}/{acc_nodash}/index.json"
        res   = requests.get(index_url, headers=_EDGAR_HEADERS, timeout=12)
        res.raise_for_status()
        items     = res.json().get("directory", {}).get("item", [])
        xml_items = [it for it in items if it.get("name", "").lower().endswith(".xml")]
        base      = f"{_EDGAR_ARCHIVES}/{cik_path}/{acc_nodash}"
        for it in xml_items:
            n = it["name"].lower().replace("_", "").replace("-", "")
            if "infotable" in n or "informationtable" in n:
                return f"{base}/{it['name']}"
        _SKIP = {"primary_doc.xml", "primary-doc.xml", "index.xml"}
        for it in xml_items:
            n = it["name"].lower()
            if n not in _SKIP and "index" not in n and "primary" not in n:
                return f"{base}/{it['name']}"
        return None
    except Exception as e:
        logger.error("EDGAR index error (CIK=%s, acc=%s): %s", cik, accession, e)
        return None


def _edgar_parse_infotable(xml_url: str) -> list[dict]:
    try:
        res  = requests.get(xml_url, headers=_EDGAR_HEADERS, timeout=30)
        res.raise_for_status()
        root = ET.fromstring(res.text)
        ns_m = re.match(r'\{([^}]+)\}', root.tag)
        ns   = '{' + ns_m.group(1) + '}' if ns_m else ''
        holdings: list[dict] = []
        for entry in root.iter(ns + 'infoTable'):
            name_el   = entry.find(ns + 'nameOfIssuer')
            cusip_el  = entry.find(ns + 'cusip')
            shares_el = entry.find('.//' + ns + 'sshPrnamt')
            value_el  = entry.find(ns + 'value')
            disc_el   = entry.find(ns + 'investmentDiscretion')
            if name_el is None or shares_el is None:
                continue
            disc = (disc_el.text or '').strip().upper() if disc_el is not None else 'SOLE'
            if disc not in ('SOLE', 'DFND'):
                continue
            name  = (name_el.text  or '').strip().upper()
            cusip = (cusip_el.text or '').strip() if cusip_el is not None else ''
            try:
                shares = int(shares_el.text)
            except (ValueError, TypeError):
                shares = 0
            try:
                value_k = int(value_el.text) if value_el is not None else 0
            except (ValueError, TypeError):
                value_k = 0
            if name and (shares > 0 or value_k > 0):
                holdings.append({"cusip": cusip, "name": name, "shares": shares, "value_k": value_k})
        return holdings
    except Exception as e:
        logger.error("EDGAR parse error (%s): %s", xml_url, e)
        return []


def _holdings_to_map(lst: list[dict]) -> dict[str, dict]:
    m: dict[str, dict] = {}
    for h in lst:
        key = h["cusip"] if h["cusip"] else h["name"]
        if key in m:
            m[key]["shares"]  += h["shares"]
            m[key]["value_k"] += h["value_k"]
            if len(h["name"]) > len(m[key]["name"]):
                m[key]["name"] = h["name"]
        else:
            m[key] = {"name": h["name"], "shares": h["shares"], "value_k": h["value_k"]}
    return m


def _fetch_fund_delta(fund_name: str, cik: str) -> tuple[dict, str]:
    try:
        accessions = _edgar_get_13f_accessions(cik, n=2)
        if not accessions:
            return {}, ""
        cur_url  = _edgar_get_infotable_url(cik, accessions[0]["accession"])
        cur_map  = _holdings_to_map(_edgar_parse_infotable(cur_url)  if cur_url  else [])
        prev_map = {}
        if len(accessions) >= 2:
            prev_url = _edgar_get_infotable_url(cik, accessions[1]["accession"])
            prev_map = _holdings_to_map(_edgar_parse_infotable(prev_url) if prev_url else [])
        all_keys = set(cur_map) | set(prev_map)
        delta: dict[str, dict] = {}
        for key in all_keys:
            c = cur_map.get(key,  {"name": key, "shares": 0, "value_k": 0})
            p = prev_map.get(key, {"shares": 0, "value_k": 0})
            sd = c["shares"]  - p["shares"]
            vd = c["value_k"] - p["value_k"]
            if sd != 0 or vd != 0:
                delta[key] = {"name": c["name"], "share_delta": sd, "value_delta_k": vd}
        return delta, accessions[0].get("reportDate", "")
    except Exception as e:
        logger.error("Fund delta error (%s): %s", fund_name, e)
        return {}, ""


def fetch_13f_smart_money(n_top: int = 20) -> dict:
    """Aggregate net position changes from SEC EDGAR 13F-HR across 20 major hedge funds."""
    aggregate: dict[str, dict] = {}
    max_report_date = ""
    fund_count = 0

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_fund_delta, name, cik): name
                   for name, cik in _13F_MAJOR_FUNDS.items()}
        for future in as_completed(futures):
            try:
                _, delta, rd = future.result()
                if not delta:
                    continue
                fund_count += 1
                if rd and rd > max_report_date:
                    max_report_date = rd
                for key, info in delta.items():
                    if key not in aggregate:
                        aggregate[key] = {"name": info["name"], "share_delta": 0,
                                          "value_delta_k": 0, "funds_buy": 0, "funds_sell": 0}
                    if len(info["name"]) > len(aggregate[key]["name"]):
                        aggregate[key]["name"] = info["name"]
                    aggregate[key]["share_delta"]   += info["share_delta"]
                    aggregate[key]["value_delta_k"] += info["value_delta_k"]
                    if info["share_delta"] > 0:
                        aggregate[key]["funds_buy"]  += 1
                    elif info["share_delta"] < 0:
                        aggregate[key]["funds_sell"] += 1
            except Exception as e:
                logger.error("Smart money aggregation error: %s", e)

    def _disp(name: str) -> str:
        return _clean_issuer_name(name)

    items      = list(aggregate.items())
    buy_items  = [(k, v) for k, v in items if v["share_delta"]   > 0]
    sell_items = [(k, v) for k, v in items if v["share_delta"]   < 0]
    buy_val    = [(k, v) for k, v in items if v["value_delta_k"] > 0]
    sell_val   = [(k, v) for k, v in items if v["value_delta_k"] < 0]

    top_buy_shares  = sorted(buy_items,  key=lambda x: -x[1]["share_delta"])[:n_top]
    top_sell_shares = sorted(sell_items, key=lambda x:  x[1]["share_delta"])[:n_top]
    top_buy_value   = sorted(buy_val,    key=lambda x: -x[1]["value_delta_k"])[:n_top]
    top_sell_value  = sorted(sell_val,   key=lambda x:  x[1]["value_delta_k"])[:n_top]
    conviction_buy  = sorted([(k, v) for k, v in buy_items  if v["funds_buy"]  >= 2],
                              key=lambda x: (-x[1]["funds_buy"],  -x[1]["share_delta"]))[:n_top]
    conviction_sell = sorted([(k, v) for k, v in sell_items if v["funds_sell"] >= 2],
                              key=lambda x: (-x[1]["funds_sell"],  x[1]["share_delta"]))[:n_top]

    quarter_label = "Latest"
    if max_report_date:
        try:
            dt = pd.Timestamp(max_report_date)
            quarter_label = f"{dt.year}-Q{(dt.month - 1) // 3 + 1}"
        except Exception:
            quarter_label = max_report_date

    return {
        "quarter":       quarter_label,
        "fund_count":    fund_count,
        "top_buy_shares":  [(_disp(v["name"]), v["share_delta"],   v["funds_buy"])  for _, v in top_buy_shares],
        "top_sell_shares": [(_disp(v["name"]), v["share_delta"],   v["funds_sell"]) for _, v in top_sell_shares],
        "top_buy_value":   [(_disp(v["name"]), round(v["value_delta_k"] / 1_000, 1), v["funds_buy"])  for _, v in top_buy_value],
        "top_sell_value":  [(_disp(v["name"]), round(v["value_delta_k"] / 1_000, 1), v["funds_sell"]) for _, v in top_sell_value],
        "conviction_buy":  [(_disp(v["name"]), v["funds_buy"],  v["share_delta"])  for _, v in conviction_buy],
        "conviction_sell": [(_disp(v["name"]), v["funds_sell"], v["share_delta"])  for _, v in conviction_sell],
    }


def edgar_connectivity_test() -> tuple[bool, str]:
    try:
        url = f"{_EDGAR_BASE}/submissions/CIK0001067983.json"
        res = requests.get(url, headers=_EDGAR_HEADERS, timeout=10)
        if res.status_code == 200:
            return True, f"SEC EDGAR 連線正常（已驗證：{res.json().get('name', 'Unknown')}）"
        if res.status_code == 429:
            return False, "SEC EDGAR 限流（429 Too Many Requests）— 請稍後 30 秒再試"
        return False, f"SEC EDGAR 回傳 HTTP {res.status_code}"
    except Exception as e:
        return False, f"網路連線失敗：{e}"
