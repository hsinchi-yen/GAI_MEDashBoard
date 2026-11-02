import json

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import data_fetcher as dfetch
import db_manager
from analytics.gmi_backtest import (
    DEFAULT_HORIZONS, REGIME_ORDER, compute_cross_correlation,
    compute_forward_returns, summarize_by_regime,
)
from analytics.market_view import compute_market_view, theme_brief
from macro_index import (
    TOTAL_INDICATORS, build_macro_index_history, get_regime_color, REGIME_LABELS,
)
from ui import components as ui
from ui.charts import decimate_figure
from ui.pages import render_guide, render_radar, render_verdict
from ui.theme import HIDDEN_MODEBAR, TEMPLATE_NAME, TOKENS, css, register_plotly_theme

# MUST BE FIRST
st.set_page_config(page_title="總經多空儀表板", layout="wide", page_icon=":material/monitoring:")
register_plotly_theme()
st.markdown(css(), unsafe_allow_html=True)

# Caches are keyed by db_manager.data_version(), so new scheduler data appears at
# once; the TTLs below only bound memory. cache_resource shares one object between
# reruns and sessions instead of unpickling a copy on every click, so everything
# it returns is treated as read-only.
CACHE_TTL    = 3600       # 1 h — live-fetch fallback only
CACHE_TTL_DB = 86400      # 24 h — DB-backed loaders
_MIN_REAL_DB_KEYS = 10    # below this many real keys → fall back to live fetch
_MIN_INDEX_MONTHS = 60    # shorter index history cannot support the backtest
THRESHOLD_LINE = TOKENS["muted"]

# ── 13F 板塊分類對照表 ─────────────────────────────────────────────────────
_SECTOR_MAP: dict[str, str] = {
    # 科技（軟體 / 雲端 / 平台）
    "MICROSOFT":          "科技",     "MSFT": "科技",
    "APPLE":              "科技",     "AAPL": "科技",
    "AMAZON":             "科技",     "AMZN": "科技",
    "META":               "科技",     "META PLATFORMS": "科技",
    "NETFLIX":            "科技",     "NFLX": "科技",
    "SALESFORCE":         "科技",
    "IBM":                "科技",
    "SERVICENOW":         "科技",
    "SEAGATE":            "科技",     "STX": "科技",
    # 資訊科技（半導體製造、設備、記憶體、光學元件）
    "TAIWAN SEMI":        "資訊科技", "TSM": "資訊科技", "TSMC": "資訊科技",
    "APPLIED MATER":      "資訊科技", "AMAT": "資訊科技",
    "WESTERN DIGITAL":    "資訊科技", "WDC": "資訊科技",
    "LUMENTUM":           "資訊科技", "LITE": "資訊科技",
    "ASML":               "資訊科技",
    "MICRON":             "資訊科技", "MU": "資訊科技",
    # 半導體（IC 設計 / 晶片設計）
    "NVIDIA":             "半導體",   "NVDA": "半導體",
    "BROADCOM":           "半導體",   "AVGO": "半導體",
    "LAM RESEARCH":       "半導體",   "LRCX": "半導體",
    "QUALCOMM":           "半導體",   "QCOM": "半導體",
    "AMD":                "半導體",   "ADVANCED MICRO": "半導體",
    "INTEL":              "半導體",   "INTC": "半導體",
    "TEXAS INST":         "半導體",   "TXN": "半導體",
    # 通訊服務
    "ALPHABET":           "通訊服務", "GOOGL": "通訊服務", "GOOG": "通訊服務",
    "NEW YORK TIMES":     "通訊服務", "NYT": "通訊服務",
    # 金融（只保留完整公司名關鍵字；移除單字母/雙字母 ticker 避免誤判）
    "JPMORGAN":           "金融",     "JPM": "金融",
    "GOLDMAN":            "金融",
    "BERKSHIRE":          "金融",     "BRK": "金融",
    "BROOKFIELD":         "金融",
    "VISA":               "金融",
    "MASTERCARD":         "金融",
    "BANK OF AMER":       "金融",     "BAC": "金融",
    "CITIGROUP":          "金融",
    # 醫療（US 大型製藥 / 醫療保險）
    "ELI LILLY":          "醫療",     "LLY": "醫療",
    "JOHNSON":            "醫療",     "JNJ": "醫療",
    "UNITEDHEALTH":       "醫療",     "UNH": "醫療",
    "ABBVIE":             "醫療",     "ABBV": "醫療",
    "MERCK":              "醫療",     "MRK": "醫療",
    # 醫療保健（歐洲大型製藥 / 生技）
    "ASTRAZENECA":        "醫療保健", "AZN": "醫療保健",
    # 消費（非核心 / 自由消費）
    "WALMART":            "消費",     "WMT": "消費",
    "COSTCO":             "消費",     "COST": "消費",
    "COUPANG":            "消費",     "CPNG": "消費",
    "TESLA":              "消費",     "TSLA": "消費",
    "HOME DEPOT":         "消費",
    "PROCTER":            "消費",
    "PEPSICO":            "消費",
    # 核心消費（民生必需品）
    "COCA COLA":          "核心消費", "COCA-COLA": "核心消費",
    # 能源（石油 / 天然氣）
    "CHEVRON":            "能源",     "CVX": "能源",
    "EXXON":              "能源",     "XOM": "能源",
    "SANDISK":            "能源",     "SNDK": "能源",
    "OCCIDENTAL":         "能源",     "OXY": "能源",
    # 工業 / 航空
    "LINDE":              "工業",
    "GENERAL ELECTRIC":   "工業",
    "CATERPILLAR":        "工業",
    "DELTA AIR":          "工業",     "DAL": "工業",
    # 原物料（建材 / 基礎建設）
    "CRH":                "原物料",
    # ETF — 股票型
    "SPDR SERIES":        "ETF股票",
    "SELECT SECTOR SPDR": "ETF股票",
    # ETF — 商品型
    "SPDR GOLD":          "ETF商品",
    "UNITED STS OIL":     "ETF商品",  "USO": "ETF商品",
}

_SECTOR_COLOR: dict[str, str] = {
    "科技":     "rgba(55,138,221,0.85)",
    "資訊科技": "rgba(0,188,212,0.85)",
    "半導體":   "rgba(127,119,221,0.85)",
    "通訊服務": "rgba(156,39,176,0.85)",
    "金融":     "rgba(186,117,23,0.85)",
    "醫療":     "rgba(99,153,34,0.85)",
    "醫療保健": "rgba(76,175,80,0.85)",
    "消費":     "rgba(212,83,126,0.85)",
    "核心消費": "rgba(233,30,99,0.85)",
    "能源":     "rgba(186,101,29,0.85)",
    "工業":     "rgba(136,135,128,0.85)",
    "原物料":   "rgba(121,85,72,0.85)",
    "ETF股票":  "rgba(96,125,139,0.85)",
    "ETF商品":  "rgba(255,160,0,0.85)",
    "其他":     "rgba(100,100,100,0.6)",
}

# TWSE 19 類股 → 產業大類 (for heatmap grouping & expander table)
_SECTOR_GROUP: dict[str, str] = {
    "電子":     "科技",
    "電機機械": "科技",
    "電器電纜": "科技",
    "化學生技醫療": "科技",
    "金融保險": "金融",
    "航運":     "工業",
    "鋼鐵":     "工業",
    "建材營造": "工業",
    "汽車":     "工業",
    "塑膠":     "原物料",
    "橡膠":     "原物料",
    "玻璃陶瓷": "原物料",
    "水泥":     "原物料",
    "紡織纖維": "消費",
    "食品":     "消費",
    "觀光餐旅": "消費",
    "貿易百貨": "消費",
    "油電燃氣": "能源",
    "造紙":     "其他",
}
_GROUP_ORDER: dict[str, int] = {
    "科技": 0, "金融": 1, "工業": 2, "消費": 3, "原物料": 4, "能源": 5, "其他": 6
}

def _classify_sector(display_name: str) -> str:
    """模糊比對持倉名稱 → 板塊"""
    name_upper = display_name.upper()
    for keyword, sector in _SECTOR_MAP.items():
        if keyword in name_upper:
            return sector
    return "其他"


def _hy_to_bps(df):
    """FRED BAMLH0A0HYM2 is quoted in percent; the UI and alerts work in bps."""
    if df is None or df.empty:
        return df
    return df.assign(value=df["value"] * 100)


@st.cache_resource(ttl=CACHE_TTL, show_spinner=False, max_entries=2)
def load_data(fred_key):
    """抓取並快取所有的基礎數據"""
    data = {}

    # VIX（日頻，拉 11 年）
    data['VIX'] = dfetch.fetch_fred('VIXCLS', fred_key, years_back=11)

    # ── Panel A：終端需求感測 ─────────────────────────────────────────────────
    data['US_PMI']  = dfetch.fetch_ism_pmi(fred_key=fred_key)
    data['TW_PMI']  = dfetch.fetch_taiwan_pmi()
    data['CN_PMI']  = dfetch.fetch_china_nbs_pmi()
    data['JP_PMI']  = dfetch.fetch_japan_economy_watchers()
    data['EU_PMI']  = dfetch.fetch_eurostat_ici()

    data['US_RETAIL']     = dfetch.fetch_fred('RSAFS', fred_key)
    data['US_RETAIL_YOY'] = dfetch.compute_yoy(data['US_RETAIL'])
    data['UMCSENT']       = dfetch.fetch_fred('UMCSENT', fred_key)

    data['TW_EXP_AMOUNT'] = dfetch.fetch_taiwan_exports_amount()
    data['TW_EXP_YOY']    = dfetch.compute_yoy(data['TW_EXP_AMOUNT'])
    data['KR_EXP_YOY']    = dfetch.fetch_korea_exports_yoy(fred_key)
    data['NDC_LEADING']    = dfetch.fetch_ndc_leading_index()
    data['NDC_LIGHT_SCORE'] = dfetch.fetch_ndc_light_score()

    # ── Panel B：獲利與成本感測 ───────────────────────────────────────────────
    data['US_CLI'] = dfetch.fetch_dbnomics('OECD', 'MEI', 'USA.LOLITONO.STSA.M')
    data['CN_CLI'] = dfetch.fetch_dbnomics('OECD', 'MEI', 'CHN.LOLITONO.STSA.M')
    data['JP_CLI'] = dfetch.fetch_dbnomics('OECD', 'MEI', 'JPN.LOLITONO.STSA.M')
    data['EU_CLI'] = dfetch.fetch_dbnomics('OECD', 'MEI', 'G4E.LOLITONO.STSA.M')
    data['KR_CLI'] = dfetch.fetch_dbnomics('OECD', 'MEI', 'KOR.LOLITONO.STSA.M')

    data['US_BUSINV']  = dfetch.fetch_fred('BUSINV', fred_key)
    data['SEMI_PPI']   = dfetch.fetch_fred('PCU33443344', fred_key)
    data['COPPER_YOY'] = dfetch.fetch_copper_yoy(fred_key)
    data['TSMC_REVENUE_YOY'] = dfetch.fetch_tsmc_revenue_yoy()

    _nom = dfetch.fetch_fred('DGS10', fred_key)
    _bei = dfetch.fetch_fred('T10YIE', fred_key)
    data['US_10Y_NOMINAL'] = _nom
    data['US_10Y_BEI']     = _bei
    if _nom is not None and _bei is not None and not _nom.empty and not _bei.empty:
        _m = _nom.merge(_bei, on='date', suffixes=('_nom', '_bei'))
        _m['value'] = _m['value_nom'] - _m['value_bei']
        data['US_REAL_RATE'] = _m[['date', 'value']]
    else:
        data['US_REAL_RATE'] = pd.DataFrame()

    _ccpi = dfetch.fetch_fred('CPILFESL', fred_key)
    _cppi = dfetch.fetch_fred('PPIFES', fred_key)
    data['US_CORE_CPI_YOY'] = dfetch.compute_yoy(_ccpi) if _ccpi is not None and not _ccpi.empty else pd.DataFrame()
    data['US_CORE_PPI_YOY'] = dfetch.compute_yoy(_cppi) if _cppi is not None and not _cppi.empty else pd.DataFrame()
    _cy, _py = data['US_CORE_CPI_YOY'], data['US_CORE_PPI_YOY']
    if not _cy.empty and not _py.empty:
        _sc = _cy.merge(_py, on='date', suffixes=('_cpi', '_ppi'))
        _sc['value'] = _sc['value_cpi'] - _sc['value_ppi']
        data['CPI_PPI_SCISSORS'] = _sc[['date', 'value']]
    else:
        data['CPI_PPI_SCISSORS'] = pd.DataFrame()

    data['CN_PPI_YOY'] = dfetch.fetch_china_nbs_ppi_yoy()
    data['BRENT']      = dfetch.fetch_fred('DCOILBRENTEU', fred_key)
    data['CHINA_CREDIT_IMPULSE'] = dfetch.fetch_china_credit_impulse(fred_key)

    # ── Panel C：流動性與風險感測 ─────────────────────────────────────────────
    cbc = dfetch.fetch_cbc_money_supply()
    data['TW_M1B_YOY'] = cbc['m1b_yoy']
    data['TW_M2_YOY']  = cbc['m2_yoy']
    _us_m1 = dfetch.fetch_fred('M1SL', fred_key) if fred_key else dfetch.fetch_dbnomics('OECD', 'MEI', 'USA.MANMM101.STSA.M')
    data['US_M1_YOY']  = dfetch.compute_yoy(_us_m1)

    yield_mats = {
        '1M': 'DGS1MO', '3M': 'DGS3MO', '6M': 'DGS6MO',
        '1Y': 'DGS1',   '2Y': 'DGS2',   '3Y': 'DGS3',
        '5Y': 'DGS5',   '7Y': 'DGS7',   '10Y': 'DGS10',
        '20Y': 'DGS20', '30Y': 'DGS30',
    }
    data['YIELD_CURVE'] = {lbl: dfetch.fetch_fred(sid, fred_key, years_back=2) for lbl, sid in yield_mats.items()}
    data['T10Y2Y']    = dfetch.fetch_fred('T10Y2Y', fred_key)
    data['HY_SPREAD'] = _hy_to_bps(dfetch.fetch_hy_spread(fred_key))
    data['TWD_USD']   = dfetch.fetch_twd_usd(fred_key)
    data['DXY']       = dfetch.fetch_dxy(fred_key)

    # ── Panel D：股市比對 ─────────────────────────────────────────────────────
    data['SP500_YOY']         = dfetch.fetch_sp500_yoy(fred_key)
    data['TAIEX_YOY']         = dfetch.fetch_taiex_yoy()
    data['NIKKEI_YOY']        = dfetch.fetch_index_yoy('^N225')
    data['KOSPI_YOY']         = dfetch.fetch_index_yoy('^KS11')
    data['HSI_YOY']           = dfetch.fetch_index_yoy('^HSI')
    data['CSI300_YOY']        = dfetch.fetch_index_yoy('000300.SS')
    data['VKOSPI']            = dfetch.fetch_vkospi()
    data['FED_FUNDS']         = dfetch.fetch_fed_funds_rate(fred_key)
    data['T10Y3M']            = dfetch.fetch_t10y3m(fred_key)
    data['US_NEW_ORDERS_YOY'] = dfetch.fetch_us_new_orders_yoy(fred_key)

    # ── Panel E：全球總經指數 ─────────────────────────────────────────────────
    etf_bulk = dfetch.fetch_etf_bulk(years_back=12)
    data['SECTOR_ROTATION']   = dfetch.fetch_sector_rotation(etf_bulk=etf_bulk, years_back=11)
    data['THIRTEENF_NET_ADD'] = dfetch.fetch_13f_proxy(etf_bulk=etf_bulk, api_key=fred_key, years_back=11)

    return data


@st.cache_data(ttl=60, show_spinner=False)
def current_data_version() -> str:
    """Polled at most once a minute; every heavier cache keys off this token."""
    return db_manager.data_version()


@st.cache_data(ttl=CACHE_TTL_DB, show_spinner=False)
def db_has_data(version: str) -> bool:
    real = [k for k in db_manager.list_keys()
            if not str(k.get("key", "")).startswith(("_", db_manager._SNAPSHOT_PREFIX))]
    return len(real) >= _MIN_REAL_DB_KEYS


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_all_from_db(version: str, fred_key: str = "") -> dict:
    """
    Load all macro indicators from SQLite (15-year history).

    Reads directly from DB — no network calls during UI interaction.
    Year-range filtering is done by filt() after this returns, so
    switching the sidebar selector costs zero fetch time.

    Falls back to load_data(fred_key) when the DB holds too few *real* indicator
    keys to be useful (e.g. first launch before scheduler has run, or a DB that
    only contains leftover test keys). Keys beginning with '_' are treated as
    test/auxiliary and never count toward this threshold.
    """
    if not db_has_data(version):
        return load_data(fred_key)

    R = db_manager.read  # shorthand

    data: dict = {}

    # ── VIX ───────────────────────────────────────────────────────────────────
    data['VIX'] = R('vix')

    # ── Panel A: demand ───────────────────────────────────────────────────────
    data['US_PMI']  = R('ism_pmi')
    data['TW_PMI']  = R('taiwan_pmi')
    data['CN_PMI']  = R('china_nbs_pmi')
    data['JP_PMI']  = R('japan_watchers')
    data['EU_PMI']  = R('eurostat_ici')

    _retail = R('us_retail')
    data['US_RETAIL']     = _retail
    data['US_RETAIL_YOY'] = (dfetch.compute_yoy(_retail)
                             if _retail is not None and not _retail.empty
                             else pd.DataFrame())
    data['UMCSENT']    = R('umcsent')

    _tw_exp = R('taiwan_exports')
    data['TW_EXP_AMOUNT'] = _tw_exp
    data['TW_EXP_YOY']    = (dfetch.compute_yoy(_tw_exp)
                              if _tw_exp is not None and not _tw_exp.empty
                              else pd.DataFrame())
    data['KR_EXP_YOY']    = R('korea_exports_yoy')
    data['NDC_LEADING']   = R('ndc_leading')
    data['NDC_LIGHT_SCORE'] = R('ndc_light_score')

    # ── Panel B: cost / profit ────────────────────────────────────────────────
    data['US_CLI'] = R('cli_us')
    data['CN_CLI'] = R('cli_cn')
    data['JP_CLI'] = R('cli_jp')
    data['EU_CLI'] = R('cli_eu')
    data['KR_CLI'] = R('cli_kr')

    data['US_BUSINV']        = R('us_businv')
    data['SEMI_PPI']         = R('semi_ppi')
    data['COPPER_YOY']       = R('copper_yoy')
    data['TSMC_REVENUE_YOY'] = R('tsmc_revenue_yoy')

    _nom = R('dgs10')
    _bei = R('t10y_bei')
    data['US_10Y_NOMINAL'] = _nom
    data['US_10Y_BEI']     = _bei
    if (_nom is not None and not _nom.empty and
            _bei is not None and not _bei.empty):
        _m = _nom.merge(_bei, on='date', suffixes=('_nom', '_bei'))
        _m['value'] = _m['value_nom'] - _m['value_bei']
        data['US_REAL_RATE'] = _m[['date', 'value']]
    else:
        data['US_REAL_RATE'] = pd.DataFrame()

    _ccpi = R('us_core_cpi')
    _cppi = R('us_core_ppi')
    data['US_CORE_CPI_YOY'] = (dfetch.compute_yoy(_ccpi)
                                if _ccpi is not None and not _ccpi.empty
                                else pd.DataFrame())
    data['US_CORE_PPI_YOY'] = (dfetch.compute_yoy(_cppi)
                                if _cppi is not None and not _cppi.empty
                                else pd.DataFrame())
    _cy, _py = data['US_CORE_CPI_YOY'], data['US_CORE_PPI_YOY']
    if not _cy.empty and not _py.empty:
        _sc = _cy.merge(_py, on='date', suffixes=('_cpi', '_ppi'))
        _sc['value'] = _sc['value_cpi'] - _sc['value_ppi']
        data['CPI_PPI_SCISSORS'] = _sc[['date', 'value']]
    else:
        data['CPI_PPI_SCISSORS'] = pd.DataFrame()

    data['CN_PPI_YOY']          = R('china_ppi_yoy')
    data['BRENT']               = R('brent')
    data['CHINA_CREDIT_IMPULSE'] = R('china_credit')

    # ── Panel C: liquidity / risk ─────────────────────────────────────────────
    data['TW_M1B_YOY'] = R('cbc_money_supply.m1b_yoy')
    data['TW_M2_YOY']  = R('cbc_money_supply.m2_yoy')
    _us_m1 = R('us_m1')
    data['US_M1_YOY']  = (dfetch.compute_yoy(_us_m1)
                          if _us_m1 is not None and not _us_m1.empty
                          else pd.DataFrame())

    yield_mats = {
        '1M': 'yield_1M', '3M': 'yield_3M', '6M': 'yield_6M',
        '1Y': 'yield_1Y', '2Y': 'yield_2Y', '3Y': 'yield_3Y',
        '5Y': 'yield_5Y', '7Y': 'yield_7Y', '10Y': 'yield_10Y',
        '20Y': 'yield_20Y', '30Y': 'yield_30Y',
    }
    data['YIELD_CURVE'] = {lbl: R(db_key) for lbl, db_key in yield_mats.items()}
    data['T10Y2Y']    = R('t10y2y')
    data['HY_SPREAD'] = _hy_to_bps(R('hy_spread'))
    data['TWD_USD']   = R('twd_usd')
    data['DXY']       = R('dxy')

    # ── Panel D: equities ─────────────────────────────────────────────────────
    data['SP500_YOY']         = R('sp500_yoy')
    data['TAIEX_YOY']         = R('taiex_yoy')
    data['NIKKEI_YOY']        = R('nikkei_yoy')
    data['KOSPI_YOY']         = R('kospi_yoy')
    data['HSI_YOY']           = R('hsi_yoy')
    data['CSI300_YOY']        = R('csi300_yoy')
    data['VKOSPI']            = R('vkospi')
    data['FED_FUNDS']         = R('fed_funds_rate')
    data['T10Y3M']            = R('t10y3m')
    data['US_NEW_ORDERS_YOY'] = R('us_new_orders_yoy')

    # ── Panel E: sector rotation (ETF-based) ──────────────────────────────────
    data['SECTOR_ROTATION']   = R('sector_rotation')
    data['THIRTEENF_NET_ADD'] = R('13f_proxy')

    return data


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_gmi_history(version: str, fred_key: str = "") -> pd.DataFrame:
    """GMI 歷史時間軸（10 年月頻）。"""
    return build_macro_index_history(load_all_from_db(version, fred_key), lookback_years=10)


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_market_view(version: str, fred_key: str = "") -> dict:
    """完整多空判讀（含趨勢雷達）。每個資料版本只算一次，所有使用者共用。"""
    return compute_market_view(load_all_from_db(version, fred_key),
                               history=load_gmi_history(version, fred_key))


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_index_close_levels(version: str, years_back: int = 15) -> dict:
    """月收 price level（回測用）。DB 優先；缺資料才連網並寫回，之後不再等待。"""
    out: dict = {}
    for label, ticker, key in (("TWII", "^TWII", "index_close_twii"),
                               ("SPX", "^GSPC", "index_close_spx")):
        df = db_manager.read(key)
        if df is None or len(df) < _MIN_INDEX_MONTHS:
            try:
                df = dfetch.fetch_index_monthly_close(ticker, years_back=years_back)
                db_manager.write(key, df, ttl_days=7, initial=True)
            except Exception:
                df = pd.DataFrame()  # fetcher already logs; UI degrades gracefully
        out[label] = df
    return out


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_regime_stats(version: str, fred_key: str = "") -> pd.DataFrame:
    """各燈號的未來報酬統計。訊號延遲 1 個月進場，避免用到當時尚未公布的數據。"""
    history = load_gmi_history(version, fred_key)
    prices = load_index_close_levels(version, years_back=12)
    if history.empty or not any(not df.empty for df in prices.values()):
        return pd.DataFrame()
    returns = compute_forward_returns(history, prices, signal_lag=1)
    return summarize_by_regime(returns, include_unconditional=True)


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_cross_correlation(version: str, fred_key: str = "") -> pd.DataFrame:
    return compute_cross_correlation(load_all_from_db(version, fred_key),
                                     load_index_close_levels(version, years_back=12),
                                     max_lag=12, min_overlap=36)


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_13f_data(version: str) -> dict:
    """SEC EDGAR 13F：讀排程器快照，毫秒級。僅在從未抓取過時才連網（約 20-30 秒）。"""
    return db_manager.read_snapshot("13f_smart_money") or refresh_13f_data()


def refresh_13f_data() -> dict:
    smart = dfetch.fetch_13f_smart_money(n_top=20)
    if smart.get("fund_count"):
        db_manager.write_snapshot("13f_smart_money", smart, ttl_days=7)
    return smart


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=4)
def load_tw_institutional(version: str, n_days: int = 5) -> dict:
    """三大法人買賣超排行：讀排程器快照，僅在缺資料時才連 TWSE（約 10-30 秒）。"""
    return (db_manager.read_snapshot(f"tw_institutional_{n_days}d")
            or refresh_tw_institutional(n_days))


def refresh_tw_institutional(n_days: int) -> dict:
    result = dfetch.fetch_tw_institutional(n_days)
    if result.get("actual_days"):  # a failed fetch must not replace good data
        db_manager.write_snapshot(f"tw_institutional_{n_days}d", result, ttl_days=1)
    return result


@st.cache_resource(ttl=CACHE_TTL_DB, show_spinner=False, max_entries=2)
def load_tw_sector_data(version: str) -> dict:
    """台股類股輪動資料 — 優先讀 DB（scheduler 02:30 更新），fallback 至 live fetch。"""
    from fetchers.taiwan_sector import (
        fetch_tw_sector_indices,
        fetch_tw_sector_turnover,
        fetch_tw_sector_institutional,
        fetch_tw_sector_institutional_by_sector,
        calc_sector_momentum,
        detect_rotation_signal,
    )

    # ── DB-first: read grouped ts written by scheduler ────────────────────────
    close_raw = db_manager.read("tw_sector_close")
    if close_raw is not None and not close_raw.empty:
        sector_df = close_raw.rename(columns={"series_key": "sector_name", "value": "close"})
        chg_raw = db_manager.read("tw_sector_chg_pct")
        if chg_raw is not None and not chg_raw.empty:
            chg_df = chg_raw.rename(columns={"series_key": "sector_name", "value": "chg_pct"})
            sector_df = sector_df.merge(chg_df, on=["date", "sector_name"], how="left")
    else:
        sector_df = fetch_tw_sector_indices(n_days=70)

    # ── turnover: blob_cache (60-day snapshot) ────────────────────────────────
    turnover_df = db_manager.read("tw_sector_turnover")
    if turnover_df is None or turnover_df.empty:
        turnover_df = fetch_tw_sector_turnover(n_days=60)

    # ── overall institutional (market-wide, BFI82U) ───────────────────────────
    instit_df = db_manager.read("tw_sector_institutional")
    if instit_df is None or instit_df.empty:
        instit_df = fetch_tw_sector_institutional(n_days=5)

    # ── sector-level institutional (BFIAMU) ───────────────────────────────────
    instit_sector_df = db_manager.read("tw_sector_instit_by_sector")
    if instit_sector_df is None or instit_sector_df.empty:
        instit_sector_df = fetch_tw_sector_institutional_by_sector(n_days=5)

    momentum_df = calc_sector_momentum(sector_df) if not sector_df.empty else pd.DataFrame()
    signals     = detect_rotation_signal(momentum_df) if not momentum_df.empty else {}
    return {
        "sector_df":        sector_df,
        "turnover_df":      turnover_df,
        "instit_df":        instit_df,
        "instit_sector_df": instit_sector_df,
        "momentum_df":      momentum_df,
        "signals":          signals,
    }


def build_figure(title, data_dict, y_label="Value", is_yoy=False):
    dfs = []
    for label, df in data_dict.items():
        if df is not None and not df.empty:
            t = df.copy(); t['Indicator'] = label; dfs.append(t)
    if not dfs:
        return None
    combined = pd.concat(dfs)
    fig = px.line(combined, x='date', y='value', color='Indicator', title=title)
    fig.update_layout(legend_title_text="", showlegend=len(dfs) > 1)
    if is_yoy:
        fig.add_hline(y=0, line_dash="dash", line_color=THRESHOLD_LINE,
                      annotation_text="0% 零增長線", annotation_position="bottom right")
    fig.update_layout(
        xaxis_title="", yaxis_title=y_label, hovermode="x unified",
        margin=dict(t=50, b=20, l=40, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


def show_chart(fig, **kwargs):
    """Render with the app theme (theme=None keeps Streamlit from overriding it)."""
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("config", {"displaylogo": False, "modeBarButtonsToRemove": HIDDEN_MODEBAR})
    fig.layout.template = pio.templates[TEMPLATE_NAME]
    st.plotly_chart(decimate_figure(fig), theme=None, **kwargs)
    # st.plotly_chart resets Plotly's global default to its own template, which
    # would otherwise leak into every figure built after the first chart.
    pio.templates.default = TEMPLATE_NAME


def fill_chart(df, title, y_label, pos_color='rgba(47,191,91,0.3)', neg_color='rgba(230,103,103,0.3)',
               pos_line='rgb(47,191,91)', neg_line='rgb(230,103,103)', ref_y=None, hover_fmt=None):
    """通用正負面積圖"""
    if df is None or df.empty:
        return None
    pos = df.copy(); neg = df.copy()
    pos.loc[pos['value'] < 0, 'value'] = 0
    neg.loc[neg['value'] > 0, 'value'] = 0
    hfmt = hover_fmt or '%{x|%Y-%m}<br>%{y:.1f}<extra></extra>'
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pos['date'], y=pos['value'], fill='tozeroy',
                             fillcolor=pos_color, line=dict(color=pos_line, width=1.5),
                             name='正成長', hovertemplate=hfmt))
    fig.add_trace(go.Scatter(x=neg['date'], y=neg['value'], fill='tozeroy',
                             fillcolor=neg_color, line=dict(color=neg_line, width=1.5),
                             name='負成長', hovertemplate=hfmt))
    if ref_y is not None:
        fig.add_hline(y=ref_y, line_dash='dash', line_color=THRESHOLD_LINE,
                      annotation_text=f'{ref_y}%', annotation_position='bottom right')
    fig.update_layout(title=title, xaxis_title='', yaxis_title=y_label,
                      hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
                      legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
    return fig


def get_latest(df):
    if df is not None and not df.empty:
        return df.iloc[-1]['value']
    return None


def get_prev(df):
    if df is not None and len(df) > 1:
        return df.iloc[-2]['value']
    return None


# ════════════════════════════════════════════════════════
# 導覽與資料載入
# ════════════════════════════════════════════════════════
NAV_GROUPS = (
    ("決策", (("verdict", "今日判讀"), ("radar", "趨勢雷達"))),
    ("深度分析", (("demand", "需求與貿易"), ("cost", "成本與獲利"),
                 ("liquidity", "流動性與風險"), ("equity", "股市比對"))),
    ("進階工具", (("gmi", "GMI 指數"), ("rotation", "台股資金輪動"),
                 ("backtest", "燈號回測"), ("guide", "使用指南"))),
)
PAGE_LABELS = {key: label for _, items in NAV_GROUPS for key, label in items}
DEFAULT_PAGE = "verdict"

# title, one-line purpose, theme(s) for the conclusion bar, how to read the page
PAGE_META = {
    "verdict":   ("今日判讀", "", (), ""),
    "radar":     ("趨勢雷達", "全部指標的方向、位階與轉折，一次掃描", (), ""),
    "demand":    ("需求與貿易", "終端需求與全球貿易是否在擴張", ("demand", "trade"),
                  "PMI 站上 50 且上升代表製造業擴張；韓國出口最早公布，常領先全球貿易數據。"
                  "訂單與信心先動，出口與營收隨後確認。"),
    "cost":      ("成本與獲利", "通膨、原物料與利率是否壓縮企業獲利", ("cost",),
                  "核心通膨回落讓 Fed 有降息空間，對估值有利；PPI 高於 CPI 代表企業成本上升快於售價，"
                  "利潤率承壓。實質利率上升不利成長股。"),
    "liquidity": ("流動性與風險", "資金與信用環境是否友善", ("liquidity",),
                  "HY 利差擴大常早於股市示警；VIX 高於 30 為壓力區。"
                  "殖利率曲線倒掛後轉正時，歷史上衰退風險反而最高。M1B 高於 M2 的黃金交叉偏多台股。"),
    "equity":    ("股市比對", "股市走勢與總經訊號是否一致", ("market",),
                  "股市通常領先總經 3-6 個月。總經轉差但股市仍強，要留意補跌；"
                  "總經觸底而股市不再破底，常是中期買點的訊號。"),
    "gmi":       ("GMI 指數", "19 項指標的多空擴散與歷史軌跡", (), ""),
    "rotation":  ("台股資金輪動", "資金正流向台股哪些類股", (), ""),
    "backtest":  ("燈號回測", "歷史上各燈號之後的股市表現", (), ""),
    "guide":     ("使用指南", "如何閱讀這個儀表板", (), ""),
}


def _go_to(page: str) -> None:
    st.session_state["page"] = page
    st.query_params["page"] = page


def current_page() -> str:
    if "page" not in st.session_state:
        requested = st.query_params.get("page", DEFAULT_PAGE)
        st.session_state["page"] = requested if requested in PAGE_LABELS else DEFAULT_PAGE
    return st.session_state["page"]


def render_page_intro(page: str) -> None:
    """Title, then this page's conclusion, then how to read it."""
    title, subtitle, themes, how_to = PAGE_META[page]
    st.markdown(ui.page_head(title, subtitle), unsafe_allow_html=True)
    for theme in themes:
        st.markdown(ui.theme_brief_bar(theme_brief(view, theme)), unsafe_allow_html=True)
    if how_to:
        with st.expander("如何解讀本頁"):
            st.markdown(how_to)


def _fred_key_input() -> str:
    """The key only feeds the live-fetch fallback, so a populated DB never asks for
    it. That also skips the browser round-trip and second script run it costs."""
    from streamlit_javascript import st_javascript

    with st.sidebar.expander("FRED API Key", expanded=True):
        stored = st_javascript("localStorage.getItem('FRED_API_KEY') || ''")
        key = st.text_input("FRED API Key", value=stored if isinstance(stored, str) else "",
                            type="password", placeholder="貼上您的 FRED API Key",
                            label_visibility="collapsed")
        if st.button("儲存至瀏覽器", key="btn_save_fred"):
            st_javascript(f"localStorage.setItem('FRED_API_KEY', {json.dumps(key)}); 1")
    return key


active_page = current_page()

with st.sidebar:
    st.markdown('<div class="gm-brand">總經多空儀表板</div>', unsafe_allow_html=True)
    for group, items in NAV_GROUPS:
        st.markdown(f'<div class="gm-navlabel">{group}</div>', unsafe_allow_html=True)
        for key, label in items:
            st.button(label, key=f"nav_{key}", on_click=_go_to, args=(key,),
                      type="primary" if key == active_page else "secondary", width="stretch")
    st.markdown('<div class="gm-navlabel">圖表區間</div>', unsafe_allow_html=True)
    range_years = st.selectbox("圖表時間區間", [3, 5, 7, 10, 15], index=1,
                               format_func=lambda x: f"近 {x} 年",
                               label_visibility="collapsed")

data_version = current_data_version()
fred_api_key = "" if db_has_data(data_version) else _fred_key_input()

with st.spinner("載入總經資料…"):
    data = load_all_from_db(data_version, fred_api_key)
    view = load_market_view(data_version, fred_api_key)

gmi = view["gmi"]
cutoff = pd.Timestamp(datetime.now() - relativedelta(years=range_years))


def filt(key):
    df = data.get(key)
    if not isinstance(df, pd.DataFrame) or df is None or df.empty:
        return df
    try:
        return df[df['date'] >= cutoff]
    except TypeError:
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'], utc=True).dt.tz_localize(None)
        return df[df['date'] >= cutoff]


with st.sidebar:
    st.caption(f"資料基準 {gmi['as_of']} · 排程每日更新")


def _strip_facts() -> list[tuple[str, str]]:
    """Live market gauges for the status strip, skipping series with no data."""
    specs = (("VIX", 'VIX', "{:.1f}"), ("HY", 'HY_SPREAD', "{:.0f} bps"),
             ("10Y-3M", 'T10Y3M', "{:+.2f}"), ("美元", 'DXY', "{:.1f}"),
             ("USD/TWD", 'TWD_USD', "{:.2f}"))
    facts = []
    for label, key, fmt in specs:
        value = get_latest(data.get(key))
        if value is not None:
            facts.append((label, fmt.format(value)))
    return facts


if active_page not in ("verdict", "guide"):
    st.markdown(ui.status_strip(view, _strip_facts()), unsafe_allow_html=True)


def page_verdict():
    render_page_intro("verdict")
    with st.spinner("計算歷史統計中…"):
        history = load_gmi_history(data_version, fred_api_key)
    render_verdict(view, history, show_chart,
                   lambda: load_regime_stats(data_version, fred_api_key))


def page_radar():
    render_page_intro("radar")
    render_radar(view)


def page_guide():
    render_page_intro("guide")
    render_guide()


# ════════════════════════════════════════════════════════
# Panel A：終端需求感測
# ════════════════════════════════════════════════════════
def page_demand():
    render_page_intro("demand")

    # KPI 快訊列
    kc1, kc2, kc3 = st.columns(3)
    with kc1:
        tw_pmi = data.get('TW_PMI')
        v = tw_pmi.iloc[-1]['value'] if tw_pmi is not None and not tw_pmi.empty else None
        p = tw_pmi.iloc[-2]['value'] if tw_pmi is not None and len(tw_pmi) > 1 else v
        st.metric("台灣製造業 PMI", f"{v:.1f}" if v else "N/A",
                  delta=f"{v-p:+.1f}" if v and p else None)
    with kc2:
        tw_exp = data.get('TW_EXP_AMOUNT')
        ev = tw_exp.iloc[-1]['value'] if tw_exp is not None and not tw_exp.empty else None
        ed = tw_exp.iloc[-1]['date'].strftime('%Y-%m') if tw_exp is not None and not tw_exp.empty else ''
        st.metric(f"台灣出口 ({ed})", f"{ev:,.0f} M$" if ev else "N/A")
    with kc3:
        kr = data.get('KR_EXP_YOY')
        kv = kr.iloc[-1]['value'] if kr is not None and not kr.empty else None
        kp = kr.iloc[-2]['value'] if kr is not None and len(kr) > 1 else kv
        st.metric("韓國出口 YoY", f"{kv:.1f}%" if kv else "N/A",
                  delta=f"{kv-kp:+.1f}%" if kv and kp else None)

    # ── PMI ────────────────────────────────────────────────────────────────────
    st.subheader("製造業 PMI 採購經理人指數")
    st.caption("美: ISM · 台: CIER · 中: NBS · 日: 內閣府 DI · 歐: Eurostat ICI(+50)")
    fig_pmi = build_figure("五大經濟體 PMI / 景氣指數", {
        "美國 (ISM)":      filt('US_PMI'),
        "台灣 (CIER)":     filt('TW_PMI'),
        "中國 (NBS)":      filt('CN_PMI'),
        "日本 (DI)":       filt('JP_PMI'),
        "歐元區 (ICI+50)": filt('EU_PMI'),
    }, y_label="指數（50 榮枯線）")
    if fig_pmi:
        fig_pmi.add_hline(y=50, line_dash="dash", line_color=THRESHOLD_LINE,
                          annotation_text="50 榮枯線", annotation_position="bottom right")
        col_chart, col_info = st.columns([3, 1])
        with col_chart:
            show_chart(fig_pmi, key='fig_pmi')
        with col_info:
            st.markdown("**最新讀值**")
            for key, label in [('US_PMI','美國'),('TW_PMI','台灣'),('CN_PMI','中國'),
                                ('JP_PMI','日本'),('EU_PMI','歐元區')]:
                v = get_latest(data.get(key))
                st.metric(label, f"{v:.1f}" if v else "N/A")
    else:
        st.warning("PMI 資料暫時無法載入，請確認 FRED API Key 或等待來源回應。")

    # ── 零售銷售 ───────────────────────────────────────────────────────────────
    st.subheader("美國零售銷售")
    st.caption("FRED RSAFS — Advance Retail Sales，消費端需求強弱的高頻指標")
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        fig_ret = build_figure("美國零售銷售金額 (百萬美元)",
                               {"US Retail Sales": filt('US_RETAIL')}, y_label="百萬美元")
        if fig_ret:
            show_chart(fig_ret, key='fig_ret')
    with col_r2:
        fig_ry = build_figure("美國零售 YoY (%)",
                              {"US Retail YoY": filt('US_RETAIL_YOY')},
                              y_label="年增率 (%)", is_yoy=True)
        if fig_ry:
            show_chart(fig_ry, key='fig_ry')

    # ── 消費者信心 ─────────────────────────────────────────────────────────────
    st.subheader("密西根大學消費者信心指數 (UMCSENT)")
    st.caption("FRED UMCSENT — 消費佔美國 GDP 近 70%，此指標為景氣轉折輔助訊號")
    um = filt('UMCSENT')
    if um is not None and not um.empty:
        col_um, col_um_m = st.columns([3, 1])
        with col_um:
            fig_um = go.Figure()
            fig_um.add_trace(go.Scatter(x=um['date'], y=um['value'], fill='tozeroy',
                                        fillcolor='rgba(201,133,0,0.15)',
                                        line=dict(color='rgb(201,133,0)', width=2),
                                        name='UMCSENT',
                                        hovertemplate='%{x|%Y-%m}<br>指數: %{y:.1f}<extra></extra>'))
            fig_um.update_layout(title='密西根消費者信心 (1966Q1=100)', xaxis_title='',
                                  yaxis_title='Index', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            show_chart(fig_um, key='fig_um')
        with col_um_m:
            lat = um.iloc[-1]; prv = um.iloc[-2] if len(um) > 1 else lat
            st.metric(f"最新（{lat['date'].strftime('%Y-%m')}）",
                      f"{lat['value']:.1f}", delta=f"{lat['value']-prv['value']:+.1f}")
    else:
        st.warning("無法載入 UMCSENT，請確認 FRED API Key。")

    # ── 台灣出口 ───────────────────────────────────────────────────────────────
    st.subheader("台灣出口表現")
    st.caption("資料來源：中華民國財政部統計處")
    exp_t1, exp_t2, exp_t3 = st.tabs(["出口金額", "出口 YoY", "年度比較"])
    with exp_t1:
        fig_exp = build_figure("台灣出口貨物總額 (百萬美元)",
                               {"出口金額": filt('TW_EXP_AMOUNT')}, y_label="百萬美元")
        if fig_exp:
            show_chart(fig_exp, key='fig_exp')
        else:
            st.warning("出口金額資料暫時無法取得。")
    with exp_t2:
        fig_eyoy = fill_chart(filt('TW_EXP_YOY'), '台灣出口年增率 (YoY %)', '年增率 (%)', ref_y=0)
        if fig_eyoy:
            show_chart(fig_eyoy, key='fig_eyoy')
        else:
            st.warning("出口年增率資料不足。")
    with exp_t3:
        ea = data.get('TW_EXP_AMOUNT')
        if ea is not None and not ea.empty:
            ann = ea.copy(); ann['year'] = ann['date'].dt.year
            annual = ann.groupby('year')['value'].sum().reset_index()
            fig_ann = go.Figure(go.Bar(x=annual['year'].astype(str), y=annual['value'],
                                       marker_color='rgb(0,120,212)',
                                       hovertemplate='%{x}<br>年度出口: %{y:,.0f} M$<extra></extra>'))
            fig_ann.update_layout(title='台灣出口年度合計 (百萬美元)',
                                   xaxis_title='年份', yaxis_title='百萬美元',
                                   margin=dict(t=50, b=20))
            show_chart(fig_ann, key='fig_ann')

    # ── 韓國出口 vs 台灣 YoY ──────────────────────────────────────────────────
    st.subheader("韓國出口 YoY vs 台灣出口 YoY")
    st.caption("韓國每月 1 日前後公布，比台灣財政部早 2~3 週，是半導體週期最早的官方高頻訊號")
    col_kr, col_tw_exp = st.columns(2)
    with col_kr:
        fig_kr = fill_chart(filt('KR_EXP_YOY'), '韓國出口 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_kr:
            show_chart(fig_kr, key='fig_kr')
        else:
            st.info("韓國出口資料載入中。")
    with col_tw_exp:
        fig_tw2 = fill_chart(filt('TW_EXP_YOY'), '台灣出口 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_tw2:
            show_chart(fig_tw2, key='fig_tw2')

    # ── NDC 領先指標 + 景氣對策信號 ─────────────────────────────────────────────
    st.subheader("🚦 國發會景氣領先指標 (NDC CLI)")
    st.caption("台灣官方複合領先指標，領先景氣轉折約 3~6 個月；景氣對策信號分數 9~45 對應 藍/黃藍/綠/黃紅/紅 燈")
    ndc = filt('NDC_LEADING')
    if ndc is not None and not ndc.empty:
        col_ndc, col_ndc_m = st.columns([3, 1])
        with col_ndc:
            fig_ndc = go.Figure()
            fig_ndc.add_trace(go.Scatter(x=ndc['date'], y=ndc['value'], fill='tozeroy',
                                          fillcolor='rgba(100,180,255,0.2)',
                                          line=dict(color='rgb(100,180,255)', width=2),
                                          name='NDC CLI',
                                          hovertemplate='%{x|%Y-%m}<br>指數: %{y:.2f}<extra></extra>'))
            fig_ndc.update_layout(title='NDC 景氣領先指標', xaxis_title='', yaxis_title='指數',
                                   hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
                                   showlegend=False)
            show_chart(fig_ndc, key='fig_ndc')
        with col_ndc_m:
            lat = ndc.iloc[-1]
            st.metric(f"領先指標（{lat['date'].strftime('%Y-%m')}）", f"{lat['value']:.2f}")
            light = filt('NDC_LIGHT_SCORE')
            if light is not None and not light.empty:
                ls = light.iloc[-1]
                lv = int(round(ls['value']))
                if lv <= 16:    sig, color = "藍燈 (低迷)", "🔵"
                elif lv <= 22:  sig, color = "黃藍燈 (轉弱)", "🟡"
                elif lv <= 31:  sig, color = "綠燈 (穩定)", "🟢"
                elif lv <= 37:  sig, color = "黃紅燈 (轉熱)", "🟠"
                else:           sig, color = "紅燈 (熱絡)", "🔴"
                st.metric(f"對策信號分數（{ls['date'].strftime('%Y-%m')}）", f"{lv} 分")
                st.markdown(f"{color} **{sig}**")

        # 景氣對策信號分數色帶圖（依分數落入 藍/黃藍/綠/黃紅/紅 區間著色）
        light = filt('NDC_LIGHT_SCORE')
        if light is not None and not light.empty:
            def _light_color(v):
                v = round(v)
                if v <= 16:   return '#2563eb'   # 藍燈
                if v <= 22:   return '#38bdf8'   # 黃藍燈
                if v <= 31:   return '#2fbf5b'   # 綠燈
                if v <= 37:   return '#fab219'   # 黃紅燈
                return '#e66767'                 # 紅燈
            fig_light = go.Figure()
            _zones = [(9, 16, 'rgba(37,99,235,0.10)'), (16, 22, 'rgba(56,189,248,0.10)'),
                      (22, 31, 'rgba(34,197,94,0.10)'), (31, 37, 'rgba(245,158,11,0.10)'),
                      (37, 45, 'rgba(239,68,68,0.10)')]
            for lo, hi, c in _zones:
                fig_light.add_hrect(y0=lo, y1=hi, fillcolor=c, line_width=0, layer='below')
            fig_light.add_trace(go.Bar(
                x=light['date'], y=light['value'],
                marker_color=[_light_color(v) for v in light['value']],
                hovertemplate='%{x|%Y-%m}<br>對策信號: %{y:.0f} 分<extra></extra>', name='對策信號'))
            fig_light.update_layout(title='景氣對策信號分數（燈號）', xaxis_title='', yaxis_title='分數',
                                     yaxis=dict(range=[9, 45]), hovermode='x unified',
                                     margin=dict(t=50, b=20, l=40, r=20), showlegend=False, height=260)
            show_chart(fig_light, key='fig_ndc_light')
    else:
        st.info("NDC 領先指標資料暫時無法取得（官方網站可能維護中）。")

    # ── 半導體週期整合概覽 ────────────────────────────────────────────────────
    st.subheader("💾 半導體週期概覽")
    st.caption("整合台積電月營收、韓國出口、半導體PPI三大指標，掌握半導體景氣循環節奏與拐點位置")

    semi_k1, semi_k2, semi_k3 = st.columns(3)
    with semi_k1:
        tv = get_latest(data.get('TSMC_REVENUE_YOY')); tp = get_prev(data.get('TSMC_REVENUE_YOY'))
        st.metric("台積電 YoY", f"{tv:.1f}%" if tv is not None else "N/A",
                  delta=f"{tv-tp:+.1f}%" if tv is not None and tp is not None else None)
    with semi_k2:
        kv2 = get_latest(data.get('KR_EXP_YOY')); kp2 = get_prev(data.get('KR_EXP_YOY'))
        st.metric("韓國出口 YoY", f"{kv2:.1f}%" if kv2 is not None else "N/A",
                  delta=f"{kv2-kp2:+.1f}%" if kv2 is not None and kp2 is not None else None)
    with semi_k3:
        sv_ppi = get_latest(data.get('SEMI_PPI')); sv_ppi_p = get_prev(data.get('SEMI_PPI'))
        st.metric("📟 半導體 PPI", f"{sv_ppi:.2f}" if sv_ppi is not None else "N/A",
                  delta=f"{sv_ppi-sv_ppi_p:+.2f}" if sv_ppi is not None and sv_ppi_p is not None else None)

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        fig_tsmc_s = fill_chart(filt('TSMC_REVENUE_YOY'), '台積電月營收 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_tsmc_s:
            show_chart(fig_tsmc_s, key='fig_tsmc_s')
        else:
            st.info("台積電資料暫時無法取得。")
    with sc2:
        fig_kr_s = fill_chart(filt('KR_EXP_YOY'), '韓國出口 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_kr_s:
            show_chart(fig_kr_s, key='fig_kr_s')
        else:
            st.info("韓國出口資料載入中。")
    with sc3:
        sppi_s = filt('SEMI_PPI')
        if sppi_s is not None and not sppi_s.empty:
            fig_sppi_s = go.Figure()
            fig_sppi_s.add_trace(go.Scatter(
                x=sppi_s['date'], y=sppi_s['value'], fill='tozeroy',
                fillcolor='rgba(25,158,112,0.2)',
                line=dict(color='rgb(25,158,112)', width=2),
                name='Semiconductor PPI',
                hovertemplate='%{x|%Y-%m}<br>PPI: %{y:.2f}<extra></extra>'
            ))
            fig_sppi_s.update_layout(
                title='半導體製造業 PPI (Dec 1984=100)', xaxis_title='',
                yaxis_title='PPI 指數', hovermode='x unified',
                margin=dict(t=50, b=20, l=40, r=20), showlegend=False
            )
            show_chart(fig_sppi_s, key='fig_sppi_s')
        else:
            st.info("半導體 PPI 資料載入中。")


# ════════════════════════════════════════════════════════
# Panel B：獲利與成本感測
# ════════════════════════════════════════════════════════
def page_cost():
    render_page_intro("cost")

    b1, b2 = st.columns(2)
    with b1:
        tsmc = data.get('TSMC_REVENUE_YOY')
        tv = tsmc.iloc[-1]['value'] if tsmc is not None and not tsmc.empty else None
        tp = tsmc.iloc[-2]['value'] if tsmc is not None and len(tsmc) > 1 else tv
        td = tsmc.iloc[-1]['date'].strftime('%Y-%m') if tsmc is not None and not tsmc.empty else ''
        st.metric(f"台積電月營收 YoY ({td})", f"{tv:.1f}%" if tv is not None else "N/A",
                  delta=f"{tv-tp:+.1f}%" if tv is not None and tp is not None else None)
    with b2:
        cu = data.get('COPPER_YOY')
        cv = cu.iloc[-1]['value'] if cu is not None and not cu.empty else None
        cp = cu.iloc[-2]['value'] if cu is not None and len(cu) > 1 else cv
        cd = cu.iloc[-1]['date'].strftime('%Y-%m') if cu is not None and not cu.empty else ''
        st.metric(f"銅價 YoY ({cd})", f"{cv:.1f}%" if cv is not None else "N/A",
                  delta=f"{cv-cp:+.1f}%" if cv is not None and cp is not None else None)

    # ── OECD CLI ───────────────────────────────────────────────────────────────
    st.subheader("OECD 綜合領先指標 (CLI)")
    _cli_dfs = [data.get(k) for k in ('US_CLI','CN_CLI','JP_CLI','EU_CLI','KR_CLI')
                if data.get(k) is not None and not data.get(k).empty]
    _cli_max_date = max(df['date'].max() for df in _cli_dfs) if _cli_dfs else None
    _cli_stale_note = ""
    if _cli_max_date is not None:
        _cli_months_old = (pd.Timestamp.now() - _cli_max_date).days / 30
        if _cli_months_old > 12:
            _cli_stale_note = (f"　⚠**資料截止 {_cli_max_date.strftime('%Y-%m')}"
                               f"（已約 {int(_cli_months_old)} 個月未更新，DBnomics OECD MEI 停更中）**")
    st.caption(f"預測經濟轉折點，基準=100；持續上升並突破 100 代表景氣復甦確認{_cli_stale_note}")
    fig_cli = build_figure("五大經濟體 CLI", {
        "美國": filt('US_CLI'), "中國": filt('CN_CLI'),
        "日本": filt('JP_CLI'), "歐洲G4E": filt('EU_CLI'),
        "韓國": filt('KR_CLI'),
    }, y_label="指數（基準=100）")
    if fig_cli:
        fig_cli.add_hline(y=100, line_dash="dash", line_color="blue",
                          annotation_text="100 趨勢線", annotation_position="bottom right")
        if _cli_max_date is not None and _cli_months_old > 12:
            fig_cli.add_annotation(
                text=f"⚠ 資料截止 {_cli_max_date.strftime('%Y-%m')}",
                xref="paper", yref="paper", x=0.01, y=0.99,
                showarrow=False, font=dict(color="#fab219", size=12),
                bgcolor="rgba(0,0,0,0.5)",
            )
        col_cli, col_cli_m = st.columns([3, 1])
        with col_cli:
            show_chart(fig_cli, key='fig_cli')
        with col_cli_m:
            st.markdown("**最新讀值**")
            for k, lbl in [('US_CLI','美國'),('CN_CLI','中國'),('JP_CLI','日本'),
                            ('EU_CLI','歐元區'),('KR_CLI','韓國')]:
                v = get_latest(data.get(k))
                st.metric(lbl, f"{v:.2f}" if v else "N/A")

    # ── 銅價 YoY + 台積電 YoY ─────────────────────────────────────────────────
    col_cu, col_tsmc = st.columns(2)
    with col_cu:
        st.subheader("銅價 YoY")
        st.caption("FRED PCOPPUSDM — 工業景氣先行，比 CLI 早 1~2 季觸底/觸頂")
        fig_cu = fill_chart(filt('COPPER_YOY'), '銅價年增率 (YoY %)', '年增率 (%)', ref_y=0)
        if fig_cu:
            show_chart(fig_cu, key='fig_cu')
        else:
            st.info("銅價資料載入中。")
    with col_tsmc:
        st.subheader("台積電月營收 YoY")
        st.caption("台積電(2330) — 每月約 10 日公布，半導體需求端最直接硬數據（FinMind 歷史 + TWSE 官方最新）")
        fig_tsmc = fill_chart(filt('TSMC_REVENUE_YOY'), '台積電月營收 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_tsmc:
            show_chart(fig_tsmc, key='fig_tsmc')
        else:
            st.info("台積電資料暫時無法取得。")

    # ── 庫存 + 半導體 PPI ──────────────────────────────────────────────────────
    col_inv, col_ppi = st.columns(2)
    with col_inv:
        st.subheader("📦 美國商業庫存")
        st.caption("FRED BUSINV — 庫存去化末段是製造業重新評價起點")
        fig_inv = build_figure("美國商業庫存", {"US Inventories": filt('US_BUSINV')}, y_label="百萬美元")
        if fig_inv:
            show_chart(fig_inv, key='fig_inv')
        else:
            st.warning("庫存資料無法載入。")
    with col_ppi:
        st.subheader("📟 半導體製造業 PPI")
        st.caption("FRED PCU33443344 — 反映半導體成本趨勢；觸底回升是佈局訊號")
        sppi = filt('SEMI_PPI')
        if sppi is not None and not sppi.empty:
            fig_sp = go.Figure()
            fig_sp.add_trace(go.Scatter(x=sppi['date'], y=sppi['value'], fill='tozeroy',
                                         fillcolor='rgba(25,158,112,0.2)',
                                         line=dict(color='rgb(25,158,112)', width=2),
                                         name='Semiconductor PPI',
                                         hovertemplate='%{x|%Y-%m}<br>PPI: %{y:.2f}<extra></extra>'))
            fig_sp.update_layout(title='半導體 PPI (Dec 1984=100)', xaxis_title='',
                                  yaxis_title='PPI 指數', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            show_chart(fig_sp, key='fig_sp')
        else:
            st.warning("半導體 PPI 無法載入。")

    # ── 10Y 實質利率 + CPI-PPI 剪刀差 ─────────────────────────────────────────
    col_rr, col_sc = st.columns(2)
    with col_rr:
        st.subheader("10Y 實質利率")
        st.caption("實質利率 = DGS10 − T10YIE；實質利率見頂回落有利科技股")
        rr = filt('US_REAL_RATE')
        nom10 = filt('US_10Y_NOMINAL'); bei10 = filt('US_10Y_BEI')
        if rr is not None and not rr.empty:
            fig_rr = go.Figure()
            if nom10 is not None and not nom10.empty:
                fig_rr.add_trace(go.Scatter(x=nom10['date'], y=nom10['value'],
                                             line=dict(color='rgba(150,150,150,0.5)', width=1, dash='dot'),
                                             name='名目利率 DGS10'))
            if bei10 is not None and not bei10.empty:
                fig_rr.add_trace(go.Scatter(x=bei10['date'], y=bei10['value'],
                                             line=dict(color='rgba(201,133,0,0.5)', width=1, dash='dot'),
                                             name='預期通膨 BEI'))
            fig_rr.add_trace(go.Scatter(x=rr['date'], y=rr['value'], fill='tozeroy',
                                         fillcolor='rgba(220,50,50,0.15)',
                                         line=dict(color='rgb(220,50,50)', width=2.5),
                                         name='🔴 實質利率',
                                         hovertemplate='%{x|%Y-%m-%d}<br>Real: %{y:.2f}%<extra></extra>'))
            fig_rr.add_hline(y=0, line_dash='dash', line_color='white',
                              annotation_text='0% 分界', annotation_position='bottom right',
                              annotation_font_color='rgba(255,255,255,0.6)')
            fig_rr.update_layout(title='美國 10Y 實質利率', xaxis_title='', yaxis_title='利率 (%)',
                                  hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
                                  legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
            show_chart(fig_rr, key='fig_rr')
            lat_rr = rr.iloc[-1]
            st.metric(f"實質利率（{lat_rr['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_rr['value']:.2f}%", delta_color="inverse")
        else:
            st.warning("實質利率資料無法載入。")
    with col_sc:
        st.subheader("✂核心 CPI–PPI 剪刀差")
        st.caption("正值擴大 = 企業定價權；負值 = 成本壓力高於轉嫁能力")
        sc = filt('CPI_PPI_SCISSORS')
        if sc is not None and not sc.empty:
            fig_sc = go.Figure()
            cpi_y = filt('US_CORE_CPI_YOY'); ppi_y = filt('US_CORE_PPI_YOY')
            if cpi_y is not None and not cpi_y.empty:
                fig_sc.add_trace(go.Scatter(x=cpi_y['date'], y=cpi_y['value'],
                                             line=dict(color='rgba(255,100,100,0.6)', width=1, dash='dot'),
                                             name='Core CPI YoY'))
            if ppi_y is not None and not ppi_y.empty:
                fig_sc.add_trace(go.Scatter(x=ppi_y['date'], y=ppi_y['value'],
                                             line=dict(color='rgba(100,100,255,0.6)', width=1, dash='dot'),
                                             name='Core PPI YoY'))
            sc_p = sc.copy(); sc_n = sc.copy()
            sc_p.loc[sc_p['value'] < 0, 'value'] = 0
            sc_n.loc[sc_n['value'] > 0, 'value'] = 0
            fig_sc.add_trace(go.Scatter(x=sc_p['date'], y=sc_p['value'], fill='tozeroy',
                                         fillcolor='rgba(47,191,91,0.3)', line=dict(color='rgb(47,191,91)', width=2),
                                         name='剪刀差（正=定價權）'))
            fig_sc.add_trace(go.Scatter(x=sc_n['date'], y=sc_n['value'], fill='tozeroy',
                                         fillcolor='rgba(230,103,103,0.3)', line=dict(color='rgb(230,103,103)', width=2),
                                         name='剪刀差（負=成本壓力）'))
            fig_sc.add_hline(y=0, line_dash='dash', line_color=THRESHOLD_LINE,
                              annotation_text='0%', annotation_position='bottom right')
            fig_sc.update_layout(title='核心 CPI–PPI 剪刀差', xaxis_title='', yaxis_title='百分點差 (%)',
                                  hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
                                  legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
            show_chart(fig_sc, key='fig_sc')
            lat_sc = sc.iloc[-1]
            st.metric(f"最新剪刀差（{lat_sc['date'].strftime('%Y-%m')}）",
                      f"{lat_sc['value']:+.2f}%")
        else:
            st.warning("CPI/PPI 剪刀差資料無法載入。")

    # ── 中國 PPI YoY + 布蘭特原油 ────────────────────────────────────────────
    col_cn, col_br = st.columns(2)
    with col_cn:
        st.subheader("中國 PPI YoY")
        st.caption("NBS — 全球製造業通膨/通縮的輸出源，中國 PPI 低迷壓抑全球報價")
        fig_cnp = fill_chart(filt('CN_PPI_YOY'), '中國 PPI YoY (%)', '年增率 (%)',
                              pos_color='rgba(230,103,103,0.3)', neg_color='rgba(47,191,91,0.3)',
                              pos_line='rgb(230,103,103)', neg_line='rgb(47,191,91)', ref_y=0)
        if fig_cnp:
            show_chart(fig_cnp, key='fig_cnp')
        else:
            st.warning("中國 PPI 資料無法載入。")
    with col_br:
        st.subheader("布蘭特原油")
        st.caption("FRED DCOILBRENTEU — 能源成本指標，油價過高迫使央行維持高利率")
        br = filt('BRENT')
        if br is not None and not br.empty:
            fig_br = go.Figure()
            fig_br.add_trace(go.Scatter(x=br['date'], y=br['value'], fill='tozeroy',
                                         fillcolor='rgba(139,69,19,0.2)',
                                         line=dict(color='rgb(139,69,19)', width=2), name='Brent',
                                         hovertemplate='%{x|%Y-%m-%d}<br>$%{y:.2f}/bbl<extra></extra>'))
            fig_br.update_layout(title='布蘭特原油 (USD/barrel)', xaxis_title='',
                                  yaxis_title='USD/barrel', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            show_chart(fig_br, key='fig_br')
            lat_br = br.iloc[-1]; prv_br = br.iloc[-2] if len(br) > 1 else lat_br
            st.metric(f"最新油價（{lat_br['date'].strftime('%Y-%m-%d')}）",
                      f"${lat_br['value']:.2f}",
                      delta=f"{lat_br['value']-prv_br['value']:+.2f}", delta_color="inverse")
        else:
            st.warning("布蘭特原油資料無法載入。")

    # ── 中國信貸脈衝（新增）────────────────────────────────────────────────────
    st.subheader("中國信貸脈衝")
    st.caption(
        "社會融資規模增量（滾動 12 月）的同比變化 — 正值=信貸擴張加速，領先全球總需求約 9~12 個月；"
        "是最強的總需求領先指標之一。來源：商務部 社融增量統計（與 MacroMicro 中國信貸脈衝同步）"
    )
    cci_df = filt('CHINA_CREDIT_IMPULSE')
    if cci_df is not None and not cci_df.empty:
        col_cci, col_cci_m = st.columns([3, 1])
        with col_cci:
            fig_cci = fill_chart(cci_df, '中國信貸脈衝 (社融 TTM 同比, %)', '%', ref_y=0,
                                 hover_fmt='%{x|%Y-%m}<br>信貸脈衝: %{y:+.2f}%<extra></extra>')
            if fig_cci:
                show_chart(fig_cci, key='fig_cci')
        with col_cci_m:
            cci_v = get_latest(cci_df); cci_p = get_prev(cci_df)
            st.metric("最新信貸脈衝",
                      f"{cci_v:+.1f}%" if cci_v is not None else "N/A",
                      delta=f"{cci_v-cci_p:+.1f}" if cci_v is not None and cci_p is not None else None,
                      help="正值=信貸加速擴張，領先需求復甦 9~12 個月")
            if cci_v is not None:
                if cci_v > 5:
                    st.success("信貸明顯加速 ▲▲")
                elif cci_v > 0:
                    st.success("信貸小幅加速 ▲")
                elif cci_v > -5:
                    st.warning("信貸小幅收縮 ▼")
                else:
                    st.error("信貸明顯收縮 ▼▼")
    else:
        st.info("中國信貸脈衝資料暫時無法取得（商務部社融資料來源）。")


# ════════════════════════════════════════════════════════
# Panel C：流動性與風險感測
# ════════════════════════════════════════════════════════
def page_liquidity():
    render_page_intro("liquidity")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        m1b = data.get('TW_M1B_YOY')
        mv = m1b.iloc[-1]['value'] if m1b is not None and not m1b.empty else None
        mp = m1b.iloc[-2]['value'] if m1b is not None and len(m1b) > 1 else mv
        md = m1b.iloc[-1]['date'].strftime('%Y-%m') if m1b is not None and not m1b.empty else ''
        st.metric(f"M1B YoY ({md})", f"{mv:.1f}%" if mv is not None else "N/A",
                  delta=f"{mv-mp:+.1f}%" if mv is not None and mp is not None else None)
    with cc2:
        hy = data.get('HY_SPREAD')
        hv = hy.iloc[-1]['value'] if hy is not None and not hy.empty else None
        hp = hy.iloc[-2]['value'] if hy is not None and len(hy) > 1 else hv
        hd = hy.iloc[-1]['date'].strftime('%Y-%m-%d') if hy is not None and not hy.empty else ''
        st.metric(f"HY 利差 ({hd})", f"{hv:.0f} bps" if hv is not None else "N/A",
                  delta=f"{hv-hp:+.0f} bps" if hv is not None and hp is not None else None,
                  delta_color="inverse")
    with cc3:
        twd = data.get('TWD_USD')
        tv2 = twd.iloc[-1]['value'] if twd is not None and not twd.empty else None
        tp2 = twd.iloc[-2]['value'] if twd is not None and len(twd) > 1 else tv2
        td2 = twd.iloc[-1]['date'].strftime('%Y-%m-%d') if twd is not None and not twd.empty else ''
        st.metric(f"TWD/USD ({td2})", f"{tv2:.3f}" if tv2 is not None else "N/A",
                  delta=f"{tv2-tp2:+.3f}" if tv2 is not None and tp2 is not None else None,
                  delta_color="inverse")

    # ── VIX ────────────────────────────────────────────────────────────────────
    st.subheader("CBOE VIX 恐慌指數")
    st.caption("FRED VIXCLS — VIX > 30 急跌往往是中長期佈局機會；低位自滿時需警惕下行風險")
    VIX_P = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 365*3, f"自訂({range_years}Y)": range_years*365}
    vix_sel = st.radio("時間範圍", list(VIX_P.keys()), index=4, horizontal=True, key="vix_p")
    vix_raw = data.get('VIX')
    if vix_raw is not None and not vix_raw.empty:
        vc = pd.Timestamp(datetime.now() - timedelta(days=VIX_P[vix_sel]))
        vdf = vix_raw[vix_raw['date'] >= vc].copy()
        if not vdf.empty:
            lv = vdf.iloc[-1]['value']; fv = vdf.iloc[0]['value']
            chg = lv - fv; pct = (chg / fv * 100) if fv else 0
            vc1, vc2, vc3, vc4 = st.columns([1.5, 1, 1, 5.5])
            with vc1:
                st.metric("VIX 最新", f"{lv:.2f}",
                          delta=f"{chg:+.2f} ({pct:+.1f}%)", delta_color="inverse")
            with vc2: st.metric("最高", f"{vdf['value'].max():.2f}")
            with vc3: st.metric("最低", f"{vdf['value'].min():.2f}")
            is_up = chg >= 0
            fig_vix = go.Figure()
            fig_vix.add_trace(go.Scatter(
                x=vdf['date'], y=vdf['value'], fill='tozeroy',
                fillcolor='rgba(230,103,103,0.3)' if is_up else 'rgba(47,191,91,0.3)',
                line=dict(color='rgb(230,103,103)' if is_up else 'rgb(47,191,91)', width=2),
                name='VIX', hovertemplate='%{x|%Y-%m-%d}<br>VIX: %{y:.2f}<extra></extra>'))
            for level, label, color in [(20, '正常(<20)', 'rgba(255,255,255,0.3)'),
                                         (30, '警戒(30)', 'rgba(255,200,0,0.4)')]:
                fig_vix.add_hline(y=level, line_dash='dot', line_color=color,
                                   annotation_text=label, annotation_position='bottom right',
                                   annotation_font_color=color)
            fig_vix.update_layout(xaxis_title='', yaxis_title='VIX', hovermode='x unified',
                                   margin=dict(t=10, b=20, l=40, r=20), showlegend=False,
                                   yaxis=dict(range=[max(0, vdf['value'].min()-3), vdf['value'].max()+3]))
            show_chart(fig_vix, key='fig_vix')
    else:
        st.warning("VIX 資料無法載入。")

    # ── 殖利率曲線 ─────────────────────────────────────────────────────────────
    st.subheader("美國公債殖利率曲線")
    st.caption("倒掛解除轉正後通常是景氣末段或衰退的強烈信號")
    yc_t1, yc_t2 = st.tabs(["殖利率曲線快照", "10Y-2Y & 10Y-3M 利差走勢"])
    with yc_t1:
        mats = ['1M','3M','6M','1Y','2Y','3Y','5Y','7Y','10Y','20Y','30Y']
        snaps = {'Current': 0, '1 Month Ago': 30, '1 Year Ago': 365}
        fig_yc = go.Figure()
        colors = {'Current': 'rgb(57,135,229)', '1 Month Ago': 'rgb(230,103,103)', '1 Year Ago': 'rgba(174,199,232,0.8)'}
        widths = {'Current': 3, '1 Month Ago': 2, '1 Year Ago': 2}
        for snap, days_back in snaps.items():
            tgt = pd.Timestamp(datetime.now() - timedelta(days=days_back))
            yields = []
            for m in mats:
                ydf = data.get('YIELD_CURVE', {}).get(m)
                if ydf is not None and not ydf.empty:
                    valid = ydf[ydf['date'] <= tgt]
                    yields.append(valid.iloc[-1]['value'] if not valid.empty else None)
                else:
                    yields.append(None)
            fig_yc.add_trace(go.Scatter(x=mats, y=yields, mode='lines+markers', name=snap,
                                         line=dict(color=colors[snap], width=widths[snap]),
                                         marker=dict(size=6),
                                         hovertemplate='%{x}: %{y:.3f}%<extra>' + snap + '</extra>'))
        fig_yc.update_layout(title='US Treasury Yield Curve', xaxis_title='Maturity',
                              yaxis_title='Yield (%)', hovermode='x unified',
                              margin=dict(t=50, b=30, l=40, r=20),
                              legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        show_chart(fig_yc, key='fig_yc')
    with yc_t2:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            fig_s1 = fill_chart(filt('T10Y2Y'), '10Y-2Y 利差 (%)', '利差 (%)', ref_y=0)
            if fig_s1:
                show_chart(fig_s1, key='fig_s1')
            else:
                st.warning("10Y-2Y 資料無法載入。")
        with col_s2:
            fig_s2 = fill_chart(filt('T10Y3M'), '10Y-3M 利差 (%)', '利差 (%)', ref_y=0)
            if fig_s2:
                show_chart(fig_s2, key='fig_s2')
            else:
                st.warning("10Y-3M 資料無法載入。")

    # ── HY 信用利差 + 台幣匯率 ────────────────────────────────────────────────
    col_hy, col_twd = st.columns(2)
    with col_hy:
        st.subheader("HY 信用利差 (OAS)")
        st.caption("FRED BAMLH0A0HYM2 — 往往在 VIX 飆升前 2~6 週先行擴大")
        hy_df = filt('HY_SPREAD')
        if hy_df is not None and not hy_df.empty:
            fig_hy = go.Figure()
            fig_hy.add_trace(go.Scatter(x=hy_df['date'], y=hy_df['value'], fill='tozeroy',
                                         fillcolor='rgba(200,50,200,0.15)',
                                         line=dict(color='rgb(180,40,180)', width=2), name='HY OAS',
                                         hovertemplate='%{x|%Y-%m-%d}<br>HY: %{y:.0f} bps<extra></extra>'))
            for lvl, lbl, col in [(400,'400 警戒','rgba(255,200,0,0.6)'),
                                    (600,'600 恐慌','rgba(230,103,103,0.7)')]:
                fig_hy.add_hline(y=lvl, line_dash='dot', line_color=col,
                                  annotation_text=lbl, annotation_position='bottom right',
                                  annotation_font_color=col)
            fig_hy.update_layout(title='HY 信用利差 (bps)', xaxis_title='',
                                  yaxis_title='bps', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            show_chart(fig_hy, key='fig_hy')
            lat_hy = hy_df.iloc[-1]; prv_hy = hy_df.iloc[-2] if len(hy_df) > 1 else lat_hy
            st.metric(f"最新 HY 利差（{lat_hy['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_hy['value']:.0f} bps",
                      delta=f"{lat_hy['value']-prv_hy['value']:+.0f} bps", delta_color="inverse")
        else:
            st.info("HY 利差資料載入中。")
    with col_twd:
        st.subheader("台幣匯率 TWD/USD")
        st.caption("FRED DEXTAUS — 數值下降＝台幣升值（外資淨流入）；急升＝外資撤離")
        twd_df = filt('TWD_USD')
        if twd_df is not None and not twd_df.empty:
            fig_twd = go.Figure()
            fig_twd.add_trace(go.Scatter(x=twd_df['date'], y=twd_df['value'],
                                          line=dict(color='rgb(0,200,180)', width=2), name='TWD/USD',
                                          hovertemplate='%{x|%Y-%m-%d}<br>TWD/USD: %{y:.3f}<extra></extra>'))
            fig_twd.update_layout(title='台幣匯率 TWD/USD（↓升值）', xaxis_title='',
                                   yaxis_title='TWD/USD', hovermode='x unified',
                                   margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            show_chart(fig_twd, key='fig_twd')
            lat_t = twd_df.iloc[-1]; prv_t = twd_df.iloc[-2] if len(twd_df) > 1 else lat_t
            st.metric(f"最新（{lat_t['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_t['value']:.3f}",
                      delta=f"{lat_t['value']-prv_t['value']:+.3f}（升值←負值）",
                      delta_color="inverse")
        else:
            st.info("台幣匯率資料載入中。")

    # ── DXY 美元指數（新增）───────────────────────────────────────────────────
    st.subheader("DXY 美元指數 (貿易加權廣義)")
    st.caption(
        "FRED DTWEXBGS — 美元升值壓縮全球流動性、新興市場資金外流；"
        "降息循環下美元走弱有利商品與風險資產。與台幣匯率反向走勢可確認外資方向。"
    )
    dxy_df = filt('DXY')
    col_dxy, col_dxy_m = st.columns([3, 1])
    with col_dxy:
        if dxy_df is not None and not dxy_df.empty:
            fig_dxy = go.Figure()
            fig_dxy.add_trace(go.Scatter(
                x=dxy_df['date'], y=dxy_df['value'], fill='tozeroy',
                fillcolor='rgba(100,200,255,0.15)',
                line=dict(color='rgb(100,200,255)', width=2), name='DXY',
                hovertemplate='%{x|%Y-%m-%d}<br>DXY: %{y:.2f}<extra></extra>'
            ))
            fig_dxy.update_layout(
                title='美元指數 DXY (貿易加權廣義)', xaxis_title='',
                yaxis_title='指數', hovermode='x unified',
                margin=dict(t=50, b=20, l=40, r=20), showlegend=False
            )
            show_chart(fig_dxy, key='fig_dxy')
        else:
            st.info("DXY 資料載入中（FRED DTWEXBGS）。")
    with col_dxy_m:
        if dxy_df is not None and not dxy_df.empty:
            dxy_lat = dxy_df.iloc[-1]; dxy_prv = dxy_df.iloc[-2] if len(dxy_df) > 1 else dxy_lat
            st.metric(f"最新 DXY（{dxy_lat['date'].strftime('%Y-%m')}）",
                      f"{dxy_lat['value']:.2f}",
                      delta=f"{dxy_lat['value']-dxy_prv['value']:+.2f}",
                      delta_color="inverse",
                      help="DXY 升值對新興市場資金流動不利")
            st.caption("↑升值 = 全球流動性緊縮\n↓貶值 = 風險資產友善")

    # ── 貨幣供給 ────────────────────────────────────────────────────────────────
    st.subheader("貨幣供給量")
    st.caption("台灣 M1B/M2：中央銀行金融統計月報 ｜ 美國 M1：FRED")
    col_twm, col_usm = st.columns(2)
    with col_twm:
        fig_twm = build_figure("台灣 M1B / M2 YoY (%)",
                               {"M1B YoY": filt('TW_M1B_YOY'), "M2 YoY": filt('TW_M2_YOY')},
                               y_label="年增率 (%)", is_yoy=True)
        if fig_twm:
            show_chart(fig_twm, key='fig_twm')
            m1b_d = filt('TW_M1B_YOY'); m2_d = filt('TW_M2_YOY')
            if m1b_d is not None and not m1b_d.empty and m2_d is not None and not m2_d.empty:
                m1v = m1b_d.iloc[-1]['value']; m2v = m2_d.iloc[-1]['value']
                cross = "🟡 黃金交叉（M1B > M2）資金活化" if m1v > m2v else "⚫ 死亡交叉（M1B < M2）資金保守"
                st.caption(f"最新：{cross}（M1B {m1v:.1f}% vs M2 {m2v:.1f}%）")
        else:
            st.warning("台灣 M1B/M2 資料暫時無法取得。")
    with col_usm:
        fig_usm = build_figure("美國 M1 YoY (%)",
                               {"US M1 YoY": filt('US_M1_YOY')},
                               y_label="年增率 (%)", is_yoy=True)
        if fig_usm:
            show_chart(fig_usm, key='fig_usm')
        else:
            st.warning("美國 M1 資料無法載入。")


# ════════════════════════════════════════════════════════
# Panel D：股市比對
# ════════════════════════════════════════════════════════
def page_equity():
    render_page_intro("equity")

    dc1, dc2, dc3, dc4 = st.columns(4)
    with dc1:
        sp = data.get('SP500_YOY')
        sv = sp.iloc[-1]['value'] if sp is not None and not sp.empty else None
        sv_p = sp.iloc[-2]['value'] if sp is not None and len(sp) > 1 else sv
        st.metric("S&P500 YoY", f"{sv:.1f}%" if sv is not None else "N/A",
                  delta=f"{sv-sv_p:+.1f}%" if sv is not None and sv_p is not None else None)
    with dc2:
        tai = data.get('TAIEX_YOY')
        tav = tai.iloc[-1]['value'] if tai is not None and not tai.empty else None
        tav_p = tai.iloc[-2]['value'] if tai is not None and len(tai) > 1 else tav
        st.metric("TAIEX YoY", f"{tav:.1f}%" if tav is not None else "N/A",
                  delta=f"{tav-tav_p:+.1f}%" if tav is not None and tav_p is not None else None)
    with dc3:
        ff = data.get('FED_FUNDS')
        fv = ff.iloc[-1]['value'] if ff is not None and not ff.empty else None
        fv_p = ff.iloc[-2]['value'] if ff is not None and len(ff) > 1 else fv
        st.metric("Fed Funds Rate", f"{fv:.2f}%" if fv is not None else "N/A",
                  delta=f"{fv-fv_p:+.2f}%" if fv is not None and fv_p is not None else None,
                  delta_color="inverse")
    with dc4:
        t3m = data.get('T10Y3M')
        t3v = t3m.iloc[-1]['value'] if t3m is not None and not t3m.empty else None
        st.metric("10Y-3M 利差", f"{t3v:.3f}%" if t3v is not None else "N/A",
                  delta_color="normal")

    # ── S&P500 vs TAIEX YoY ───────────────────────────────────────────────────
    st.subheader("S&P 500 vs TAIEX 年增率比對 (YoY %)")
    st.caption(
        "S&P 500：FRED SP500（月收）｜ TAIEX：Yahoo Finance ^TWII（月收）"
        "　台股與美股年增率的背離往往反映資金輪動或匯率效應，收斂時是重要觀察點。"
    )
    sp_yoy = filt('SP500_YOY'); tai_yoy = filt('TAIEX_YOY')
    if (sp_yoy is not None and not sp_yoy.empty) or (tai_yoy is not None and not tai_yoy.empty):
        fig_cmp = go.Figure()
        if sp_yoy is not None and not sp_yoy.empty:
            fig_cmp.add_trace(go.Scatter(x=sp_yoy['date'], y=sp_yoy['value'],
                                          line=dict(color='rgb(57,135,229)', width=2.5),
                                          name='S&P500 YoY',
                                          hovertemplate='%{x|%Y-%m}<br>S&P500 YoY: %{y:.1f}%<extra></extra>'))
        if tai_yoy is not None and not tai_yoy.empty:
            fig_cmp.add_trace(go.Scatter(x=tai_yoy['date'], y=tai_yoy['value'],
                                          line=dict(color='rgb(47,191,91)', width=2.5),
                                          name='TAIEX YoY',
                                          hovertemplate='%{x|%Y-%m}<br>TAIEX YoY: %{y:.1f}%<extra></extra>'))
        fig_cmp.add_hline(y=0, line_dash='dash', line_color=THRESHOLD_LINE,
                           annotation_text='0%', annotation_position='bottom right')
        fig_cmp.update_layout(title='S&P 500 vs TAIEX 年增率 (%)', xaxis_title='',
                               yaxis_title='年增率 (%)', hovermode='x unified',
                               margin=dict(t=50, b=20, l=40, r=20),
                               legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        col_cmp, col_cmp_m = st.columns([3, 1])
        with col_cmp:
            show_chart(fig_cmp, key='fig_cmp')
        with col_cmp_m:
            st.markdown("**最新讀值**")
            st.metric("S&P500", f"{sv:.1f}%" if sv is not None else "N/A")
            st.metric("TAIEX", f"{tav:.1f}%" if tav is not None else "N/A")
            if sv is not None and tav is not None:
                diff = sv - tav
                st.metric("差距", f"{diff:+.1f}pp", help="S&P500 - TAIEX")
    else:
        st.warning("S&P 500 及 TAIEX 資料均無法取得，請確認 FRED API Key 及網路連線。")

    # ── Fed Funds + 10Y-3M ─────────────────────────────────────────────────────
    col_ff, col_t3m = st.columns(2)
    with col_ff:
        st.subheader("聯準會基準利率 (Fed Funds Rate)")
        st.caption("FRED DFF 日頻月均 — 利率政策是股市估值的最根本驅動力，升息壓縮 P/E，降息擴張 P/E")
        ff_df = filt('FED_FUNDS')
        if ff_df is not None and not ff_df.empty:
            fig_ff = go.Figure()
            fig_ff.add_trace(go.Scatter(x=ff_df['date'], y=ff_df['value'], fill='tozeroy',
                                         fillcolor='rgba(217,89,38,0.15)',
                                         line=dict(color='rgb(217,89,38)', width=2.5),
                                         name='Fed Funds',
                                         hovertemplate='%{x|%Y-%m}<br>Rate: %{y:.2f}%<extra></extra>'))
            fig_ff.update_layout(title='聯準會有效聯邦基金利率 (DFF)', xaxis_title='',
                                  yaxis_title='利率 (%)', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            show_chart(fig_ff, key='fig_ff')
            lat_ff = ff_df.iloc[-1]
            st.metric(f"最新利率（{lat_ff['date'].strftime('%Y-%m')}）", f"{lat_ff['value']:.2f}%")
        else:
            st.warning("Fed Funds Rate 資料無法載入。")
    with col_t3m:
        st.subheader("10Y-3M 利差（衰退領先指標）")
        st.caption("FRED T10Y3M — 比 10Y-2Y 更早、更敏感的衰退預測指標；倒掛後轉正是強烈衰退訊號")
        t3m_df = filt('T10Y3M')
        if t3m_df is not None and not t3m_df.empty:
            fig_t3m = fill_chart(t3m_df, '10Y-3M 利差 (%)', '利差 (%)', ref_y=0)
            if fig_t3m:
                show_chart(fig_t3m, key='fig_t3m')
            lat_t3 = t3m_df.iloc[-1]
            st.metric(f"最新 10Y-3M（{lat_t3['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_t3['value']:.3f}%")
        else:
            st.warning("10Y-3M 資料無法載入。")

    # ── 製造業新訂單 YoY ───────────────────────────────────────────────────────
    st.subheader("美國製造業新訂單 YoY (AMTMNO)")
    st.caption("FRED AMTMNO — 製造業需求端前端訊號；新訂單轉正往往領先工業股上漲 1~2 季")
    no_df = filt('US_NEW_ORDERS_YOY')
    col_no, col_no_m = st.columns([3, 1])
    with col_no:
        fig_no = fill_chart(no_df, '美國製造業新訂單 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_no:
            show_chart(fig_no, key='fig_no')
        else:
            st.warning("製造業新訂單資料無法載入。")
    with col_no_m:
        if no_df is not None and not no_df.empty:
            lat_no = no_df.iloc[-1]
            st.metric(f"最新（{lat_no['date'].strftime('%Y-%m')}）", f"{lat_no['value']:.1f}%")

    # ── 三線疊加 ───────────────────────────────────────────────────────────────
    st.subheader("三線疊加：股市 YoY vs 聯準會利率")
    st.caption("利率走勢與股市 YoY 的相對位置，觀察貨幣政策寬緊對股市的滯後效應")
    sp_f = filt('SP500_YOY'); tai_f = filt('TAIEX_YOY'); ff_f = filt('FED_FUNDS')
    if sp_f is not None and not sp_f.empty:
        fig3 = make_subplots(specs=[[{"secondary_y": True}]])
        if sp_f is not None and not sp_f.empty:
            fig3.add_trace(go.Scatter(x=sp_f['date'], y=sp_f['value'],
                                       line=dict(color='rgb(57,135,229)', width=2),
                                       name='S&P500 YoY %'), secondary_y=False)
        if tai_f is not None and not tai_f.empty:
            fig3.add_trace(go.Scatter(x=tai_f['date'], y=tai_f['value'],
                                       line=dict(color='rgb(47,191,91)', width=2),
                                       name='TAIEX YoY %'), secondary_y=False)
        if ff_f is not None and not ff_f.empty:
            fig3.add_trace(go.Scatter(x=ff_f['date'], y=ff_f['value'],
                                       line=dict(color='rgb(217,89,38)', width=1.5, dash='dot'),
                                       name='Fed Funds Rate %'), secondary_y=True)
        fig3.update_layout(
            title='股市 YoY vs Fed Funds Rate',
            hovermode='x unified',
            margin=dict(t=50, b=20, l=40, r=40),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        fig3.update_yaxes(title_text="年增率 (%)", secondary_y=False)
        fig3.update_yaxes(title_text="利率 (%)", secondary_y=True)
        show_chart(fig3, key='fig3')
    else:
        st.info("S&P 500 YoY 資料不足，無法顯示三線疊加圖。")

    # ── 亞洲主要指數 YoY 比對 ─────────────────────────────────────────────────
    st.subheader("亞洲主要指數 YoY 比對")
    st.caption(
        "S&P500 / 台股TAIEX / 日經225 / 韓國KOSPI / 恒生指數 / 滬深300 — Yahoo Finance 月頻。"
        "亞洲指數相對強弱反映區域資金輪動，與 DXY、信貸脈衝呼應觀察效果最佳。"
    )

    _ASIA_SERIES = [
        ('SP500_YOY',  'S&P500',   'rgb(57,135,229)'),
        ('TAIEX_YOY',  'TAIEX',    'rgb(47,191,91)'),
        ('NIKKEI_YOY', '日經225',  'rgb(255,127,14)'),
        ('KOSPI_YOY',  'KOSPI',    'rgb(144,133,233)'),
        ('HSI_YOY',    '恒生',     'rgb(230,103,103)'),
        ('CSI300_YOY', '滬深300',  'rgb(23,190,207)'),
    ]

    fig_asia = go.Figure()
    _has_asia = False
    for _key, _label, _color in _ASIA_SERIES:
        _df_a = filt(_key)
        if _df_a is not None and not _df_a.empty:
            fig_asia.add_trace(go.Scatter(
                x=_df_a['date'], y=_df_a['value'],
                line=dict(color=_color, width=2),
                name=_label,
                hovertemplate=f'%{{x|%Y-%m}}<br>{_label}: %{{y:.1f}}%<extra></extra>',
            ))
            _has_asia = True

    if _has_asia:
        fig_asia.add_hline(y=0, line_dash='dash', line_color='gray',
                           annotation_text='0%', annotation_position='bottom right')
        fig_asia.update_layout(
            title='亞洲主要股市 YoY (%)', xaxis_title='', yaxis_title='年增率 (%)',
            hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        col_asia, col_asia_m = st.columns([3, 1])
        with col_asia:
            show_chart(fig_asia, key='fig_asia')
        with col_asia_m:
            st.markdown("**最新讀值**")
            for _key, _label, _ in _ASIA_SERIES:
                _v = get_latest(data.get(_key))
                _p = get_prev(data.get(_key))
                st.metric(_label,
                          f"{_v:.1f}%" if _v is not None else "N/A",
                          delta=f"{_v-_p:+.1f}%" if _v is not None and _p is not None else None)
    else:
        st.warning("亞洲指數資料均無法載入，請確認網路連線。")

    # ── 跨市場相關係數矩陣 ──────────────────────────────────────────────────────
    st.subheader("🔗 跨市場相關係數矩陣")
    st.caption(
        "六大指數的全期相關係數（1 = 完全同向，-1 = 完全反向）。"
        "當兩市場相關性驟降，代表去相關化出現，是跨市場分散化的最佳時機。"
    )
    _CORR_MAP = [
        ('SP500_YOY',  'S&P500'),
        ('TAIEX_YOY',  'TAIEX'),
        ('NIKKEI_YOY', '日經225'),
        ('KOSPI_YOY',  'KOSPI'),
        ('HSI_YOY',    '恒生'),
        ('CSI300_YOY', '滬深300'),
    ]
    _corr_frames = []
    for _ck, _cl in _CORR_MAP:
        _df_c = filt(_ck)
        if _df_c is not None and not _df_c.empty:
            _t = _df_c[['date', 'value']].copy()
            _t['ym'] = _t['date'].dt.to_period('M').astype(str)
            _t = _t.groupby('ym')['value'].mean().rename(_cl)
            _corr_frames.append(_t)
    if len(_corr_frames) >= 2:
        _corr_df  = pd.concat(_corr_frames, axis=1).dropna()
        _corr_mat = _corr_df.corr().round(2)
        _labels   = _corr_mat.columns.tolist()
        _z        = _corr_mat.values.tolist()
        _text     = [[f"{v:.2f}" for v in row] for row in _z]
        fig_corr  = go.Figure(go.Heatmap(
            z=_z, x=_labels, y=_labels,
            text=_text, texttemplate='%{text}',
            colorscale='RdYlGn', zmid=0, zmin=-1, zmax=1,
            hovertemplate='%{y} × %{x}: %{z:.2f}<extra></extra>',
        ))
        fig_corr.update_layout(
            title=f'亞洲指數相關係數矩陣（近 {range_years} 年）',
            margin=dict(t=50, b=20, l=80, r=20),
            height=370,
        )
        show_chart(fig_corr, key='fig_corr_heatmap')
    else:
        st.info("相關係數計算需至少兩個有效指數序列。")

    # ── 亞洲 VIX 風險監控 ─────────────────────────────────────────────────────
    st.subheader("📡 亞洲 VIX 風險監控")
    st.caption(
        "美股 VIX（CBOE）vs 韓國 VKOSPI — 兩者共振代表亞太整體恐慌；"
        "單獨走高則為區域性事件。與 HY 利差共振時是降低權益敞口的強信號。"
    )
    _vix_df  = filt('VIX')
    _vkos_df = filt('VKOSPI')
    if _vix_df is not None and not _vix_df.empty:
        fig_avix = go.Figure()
        fig_avix.add_trace(go.Scatter(
            x=_vix_df['date'], y=_vix_df['value'],
            line=dict(color='rgb(57,135,229)', width=2),
            name='VIX',
            hovertemplate='%{x|%Y-%m-%d}<br>VIX: %{y:.1f}<extra></extra>',
        ))
        if _vkos_df is not None and not _vkos_df.empty:
            fig_avix.add_trace(go.Scatter(
                x=_vkos_df['date'], y=_vkos_df['value'],
                line=dict(color='rgb(144,133,233)', width=2),
                name='VKOSPI',
                hovertemplate='%{x|%Y-%m-%d}<br>VKOSPI: %{y:.1f}<extra></extra>',
            ))
        fig_avix.add_hrect(y0=20, y1=300, fillcolor='rgba(230,103,103,0.05)',
                           line_width=0, annotation_text='恐慌區 >20',
                           annotation_position='top left')
        fig_avix.update_layout(
            title='VIX vs VKOSPI 波動率比對', xaxis_title='', yaxis_title='波動率指數',
            hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        col_avix, col_avix_m = st.columns([3, 1])
        with col_avix:
            show_chart(fig_avix, key='fig_asia_vix')
        with col_avix_m:
            st.markdown("**最新讀值**")
            _vv = get_latest(_vix_df);  _vp = get_prev(_vix_df)
            st.metric("VIX",
                      f"{_vv:.1f}" if _vv is not None else "N/A",
                      delta=f"{_vv-_vp:+.1f}" if _vv is not None and _vp is not None else None,
                      delta_color="inverse")
            if _vkos_df is not None and not _vkos_df.empty:
                _kv = get_latest(_vkos_df); _kp = get_prev(_vkos_df)
                st.metric("VKOSPI",
                          f"{_kv:.1f}" if _kv is not None else "N/A",
                          delta=f"{_kv-_kp:+.1f}" if _kv is not None and _kp is not None else None,
                          delta_color="inverse")
    else:
        st.warning("VIX 資料無法載入。")

    # ── 台灣三大法人買賣超排行 ─────────────────────────────────────────────────
    st.subheader("台灣三大法人買賣超排行")
    st.caption(
        "資料來源：台灣證券交易所 T86 — 外資＋投信＋自營商合計淨買賣超股數。"
        "首次載入約 10-30 秒（每 2 小時快取）。"
    )

    _tw_ctrl_col, _tw_refresh_col = st.columns([4, 1])
    with _tw_ctrl_col:
        _tw_period = st.radio(
            "統計期間",
            ["近一週（5 個交易日）", "近一月（20 個交易日）"],
            horizontal=True,
            key="tw_inst_period",
            label_visibility="collapsed",
        )
    with _tw_refresh_col:
        if st.button("更新法人資料", key="btn_tw_inst_refresh",
                     help="重新從 TWSE 抓取並更新資料庫（約 10-30 秒）"):
            refresh_tw_institutional(5 if "一週" in _tw_period else 20)
            current_data_version.clear()
            st.rerun()

    _tw_n_days = 5 if "一週" in _tw_period else 20

    with st.spinner("載入三大法人買賣超…"):
        _tw_data = load_tw_institutional(data_version, _tw_n_days)

    _tw_buy         = _tw_data.get("top30_buy",    pd.DataFrame())
    _tw_sell        = _tw_data.get("top30_sell",   pd.DataFrame())
    _tw_period_lbl  = _tw_data.get("period_label", "")
    _tw_fetch_date  = _tw_data.get("fetch_date",   "")

    st.caption(f"統計期間：{_tw_period_lbl}　｜　資料擷取：{_tw_fetch_date}")

    if not _tw_buy.empty or not _tw_sell.empty:
        # ── Top 10 橫向長條圖 ──
        _tw_bar_col1, _tw_bar_col2 = st.columns(2)

        def _tw_bar(df, title, color):
            top10 = df.head(10).copy()
            top10["label"] = top10["code"] + "  " + top10["name"]
            top10["萬股"] = (top10["net_shares"] / 10000).round(1)
            fig = go.Figure(go.Bar(
                y=top10["label"].iloc[::-1],
                x=top10["萬股"].iloc[::-1],
                orientation="h",
                marker_color=color,
                text=[f"{v:,.1f}" for v in top10["萬股"].iloc[::-1]],
                textposition="outside",
                hovertemplate="%{y}<br>%{x:,.1f} 萬股<extra></extra>",
            ))
            fig.update_layout(
                title=title,
                xaxis_title="萬股",
                margin=dict(t=45, b=20, l=140, r=70),
                height=330,
                xaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.08)"),
            )
            return fig

        with _tw_bar_col1:
            if not _tw_buy.empty:
                show_chart(
                    _tw_bar(_tw_buy, "三大法人 Top 10 買超", "rgba(47,191,91,0.82)"),
                    width='stretch', key="fig_tw_buy10",
                )
        with _tw_bar_col2:
            if not _tw_sell.empty:
                show_chart(
                    _tw_bar(_tw_sell, "三大法人 Top 10 賣超", "rgba(230,103,103,0.82)"),
                    width='stretch', key="fig_tw_sell10",
                )

        # ── Top 30 明細表 ──
        def _tw_fmt_table(df: pd.DataFrame) -> pd.DataFrame:
            out = df[["code", "name", "net_shares"]].copy()
            out.index = range(1, len(out) + 1)
            out["淨買賣超（萬股）"] = (out["net_shares"] / 10000).round(1).map(
                lambda x: f"{x:,.1f}"
            )
            if "est_value_億" in df.columns:
                out["估算金額（億元）"] = df["est_value_億"].apply(
                    lambda x: f"{x:.1f}" if pd.notna(x) else "—"
                ).to_numpy()  # `out` is re-indexed from 1; assign by position, not label
                return out[["code", "name", "淨買賣超（萬股）", "估算金額（億元）"]].rename(
                    columns={"code": "代號", "name": "名稱"}
                )
            return out[["code", "name", "淨買賣超（萬股）"]].rename(
                columns={"code": "代號", "name": "名稱"}
            )

        _tw_tbl_col1, _tw_tbl_col2 = st.columns(2)
        with _tw_tbl_col1:
            st.markdown("**前 30 大買超明細**")
            if not _tw_buy.empty:
                st.dataframe(_tw_fmt_table(_tw_buy), width='stretch', height=520)
        with _tw_tbl_col2:
            st.markdown("**前 30 大賣超明細**")
            if not _tw_sell.empty:
                st.dataframe(_tw_fmt_table(_tw_sell), width='stretch', height=520)
    else:
        st.warning("無法載入三大法人買賣超資料，請點選「更新法人資料」重試。")



# ════════════════════════════════════════════════════════
# Panel E：全球總經指數 (Global Macro Index)
# ════════════════════════════════════════════════════════
def page_gmi():
    render_page_intro("gmi")
    st.caption(
        "透過 19 個指標的二元擴散法量化全球景氣方向，"
        "每個指標每月輸出 0（非正向）或 1（正向），加總後映射為紅黃綠三色燈號。"
        "計分門檻：🟢 擴張 ≥ 75%　🟡 觀望 46–74%　🔴 收縮 ≤ 45%"
    )

    with st.spinner("計算景氣歷史時間軸中…"):
        gmi_history = load_gmi_history(data_version, fred_api_key)

    display_label = REGIME_LABELS[view["regime"]]
    confirmation_note = ""
    if view["pending_regime"]:
        confirmation_note = (
            f"最新訊號為 {REGIME_LABELS[view['pending_regime']]}，"
            f"尚未滿足兩個完整月份的確認，故維持 {display_label}。"
        )

    # ── KPI 燈號列 ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1:
        st.metric("景氣燈號（兩期確認）", display_label.split(" (")[0])
    with k2:
        st.metric("GMI 分數", f"{gmi['score']} / {gmi['valid_count']}",
                  help="分子為看多指標數，分母為有效指標數（缺資料的指標不計入）")
    with k3:
        st.metric("擴散比例", f"{gmi['diffusion']:.1f}%",
                  help="看多指標 ÷ 有效指標。Green≥75% · Red≤45%")
    with k4:
        conf_label = "正常" if gmi["confidence"] == "normal" else "低信心"
        st.metric("信心等級", conf_label, help=f"有效指標數：{gmi['valid_count']}/{TOTAL_INDICATORS}（<16 為低信心）")
    with k5:
        st.metric("資料基準月", gmi["as_of"])

    if confirmation_note:
        st.caption(f"Anti-whipsaw：{confirmation_note}")

    # ── 歷史 Timeline（雙軌：GMI Score + S&P500 YoY）────────────────────────
    if gmi_history is not None and not gmi_history.empty:
        st.subheader("歷史 Regime Timeline")
        st.caption("上軌：10 年月頻 GMI（兩期確認；彩色點為確認燈號）｜ 下軌：S&P500 YoY % 對照，觀察領先/滯後關係")

        fig_hist = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.65, 0.35],
            subplot_titles=("GMI 擴散比例 (%)", "S&P 500 YoY %"),
        )

        # 上軌：背景色帶
        fig_hist.add_hrect(y0=0,  y1=45,  fillcolor="rgba(230,103,103,0.10)",  line_width=0, row=1, col=1)
        fig_hist.add_hrect(y0=45, y1=75,  fillcolor="rgba(255,200,0,0.06)",  line_width=0, row=1, col=1)
        fig_hist.add_hrect(y0=75, y1=100, fillcolor="rgba(47,191,91,0.10)",  line_width=0, row=1, col=1)

        # 上軌：GMI 折線
        fig_hist.add_trace(go.Scatter(
            x=gmi_history["date"],
            y=gmi_history["diffusion"],
            mode="lines+markers",
            line=dict(color="rgba(210,220,230,0.9)", width=2),
            marker=dict(
                size=7,
                color=[get_regime_color(r) for r in gmi_history["confirmed_regime"]],
            ),
            customdata=gmi_history[["score", "regime", "confirmed_regime", "valid_count"]],
            hovertemplate=(
                "%{x|%Y-%m}<br>擴散: %{y:.0f}%"
                "<br>得分: %{customdata[0]}/%{customdata[3]}"
                "<br>Raw: %{customdata[1]}"
                "<br>Confirmed: %{customdata[2]}<extra></extra>"
            ),
            name="GMI 擴散",
        ), row=1, col=1)

        # 上軌：事件標注
        event_dates = {
            "2008 GFC":       pd.Timestamp("2008-09-30"),
            "2015 China":     pd.Timestamp("2015-08-31"),
            "2018 Q4":        pd.Timestamp("2018-12-31"),
            "2020 COVID":     pd.Timestamp("2020-03-31"),
            "2022 Rate Hike": pd.Timestamp("2022-06-30"),
        }
        hist_min = gmi_history["date"].min()
        hist_max = gmi_history["date"].max()
        for ev_label, ev_date in event_dates.items():
            if hist_min <= ev_date <= hist_max:
                fig_hist.add_vline(x=ev_date, line_dash="dot",
                                   line_color="rgba(255,255,255,0.3)", row="all", col=1)
                fig_hist.add_annotation(
                    x=ev_date, y=101, text=ev_label,
                    showarrow=False, yanchor="bottom",
                    font=dict(size=9, color="#cfd8dc"), row=1, col=1,
                )

        # 下軌：S&P500 YoY
        sp500_all = data.get('SP500_YOY')
        if sp500_all is not None and not sp500_all.empty:
            sp_in_range = sp500_all[
                (sp500_all['date'] >= hist_min) & (sp500_all['date'] <= hist_max)
            ]
            if not sp_in_range.empty:
                sp_pos = sp_in_range.copy(); sp_neg = sp_in_range.copy()
                sp_pos.loc[sp_pos['value'] < 0, 'value'] = 0
                sp_neg.loc[sp_neg['value'] > 0, 'value'] = 0
                fig_hist.add_trace(go.Scatter(
                    x=sp_pos['date'], y=sp_pos['value'], fill='tozeroy',
                    fillcolor='rgba(47,191,91,0.25)',
                    line=dict(color='rgb(47,191,91)', width=1.5),
                    name='S&P500 YoY+ %',
                    hovertemplate='%{x|%Y-%m}<br>S&P500 YoY: %{y:.1f}%<extra></extra>',
                ), row=2, col=1)
                fig_hist.add_trace(go.Scatter(
                    x=sp_neg['date'], y=sp_neg['value'], fill='tozeroy',
                    fillcolor='rgba(230,103,103,0.25)',
                    line=dict(color='rgb(230,103,103)', width=1.5),
                    name='S&P500 YoY- %',
                    hovertemplate='%{x|%Y-%m}<br>S&P500 YoY: %{y:.1f}%<extra></extra>',
                ), row=2, col=1)
                fig_hist.add_hline(y=0, line_dash='dash',
                                   line_color='rgba(201,133,0,0.5)', row=2, col=1)

        fig_hist.update_layout(
            title="GMI 歷史軌跡 vs S&P 500",
            hovermode="x unified",
            height=520,
            margin=dict(t=80, b=20, l=40, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_hist.update_yaxes(range=[0, 108], tickvals=[0, 45, 75, 100],
                               title_text="擴散 %", row=1, col=1)
        fig_hist.update_yaxes(title_text="YoY %", row=2, col=1)
        show_chart(fig_hist, key='fig_hist')

    # ── 20 指標熱力圖 ──────────────────────────────────────────────────────────
    st.subheader("19 項指標方向明細")
    GROUP_NAMES = {
        "A": "A｜需求與領先活動",
        "B": "B｜貿易與同時流量",
        "C": "C｜成本、流動性、金融條件",
        "D": "D｜市場內部與部位",
    }
    for grp, grp_label in GROUP_NAMES.items():
        sigs = [s for s in gmi["signals"] if s["group"] == grp]
        raw_sum = gmi["group_scores"][grp]["raw"]
        capped  = gmi["group_scores"][grp]["capped"]
        cap_note = f"（原始 {raw_sum}，群組上限 5 → 計入 {capped}）" if raw_sum != capped else f"（計入 {capped}）"
        st.markdown(f"**{grp_label}** {cap_note}")
        cols = st.columns(5)
        for i, sig in enumerate(sigs):
            with cols[i]:
                tone = ("neutral" if not sig["has_data"]
                        else "bullish" if sig["score"] == 1 else "bearish")
                st.markdown(ui.indicator_tile(sig, tone), unsafe_allow_html=True)

    # ── 美股內部輪動 ────────────────────────────────────────────────────────────
    st.subheader("內部輪動指數")
    st.caption("景氣循環 (XLY+XLI+XLB+XLF) vs 防禦 (XLP+XLU+XLV+XLRE) 等權相對強弱")
    rot_df = filt("SECTOR_ROTATION")
    if rot_df is not None and not rot_df.empty:
        fig_rot = fill_chart(
            rot_df, "循環/防禦相對強弱指數", "比率",
            ref_y=0,
            hover_fmt="%{x|%Y-%m}<br>輪動比率: %{y:.3f}<extra></extra>",
        )
        if fig_rot:
            show_chart(fig_rot, key='fig_rot')
        latest_rot = rot_df.iloc[-1]["value"]
        rot_status = "Risk-On 🟢 景氣循環領先" if latest_rot > 0 else "Risk-Off 🔴 防禦領先"
        st.metric("最新輪動狀態", rot_status, f"{latest_rot:+.3f}")
    else:
        st.info("輪動指數資料抓取中（Yahoo Finance ETF 月頻）")

    # ── 方法說明 ───────────────────────────────────────────────────────────────
    with st.expander("方法說明與資料限制"):
        st.markdown("""
**計分方法**
- 19 個指標各輸出 0（負向）或 1（正向），分為 A/B/C/D 四組（A:5、B:4、C:5、D:5）。
- 每組最高計入 5 分（群組上限），避免同質指標堆疊。
- 擴散比例 = 有效指標得分 ÷ 有效指標數 × 100，按比例計算不受缺失指標影響。
- 需連續 2 期達到門檻才切換燈號（防假突破）。
- 有效指標數 < 16 時，標示「低信心」。

**燈號門檻**（擴散比例 = 得分 ÷ 有效指標數）
| 燈號 | 擴散比例 | 說明 |
|------|---------|------|
| 🟢 擴張 | ≥ 75% | 多數指標正向，景氣擴張 |
| 🟡 觀望 | 46–74% | 訊號分歧，方向未明 |
| 🔴 收縮 | ≤ 45% | 多數指標轉弱，景氣收縮 |

**內部輪動限制**
- 以景氣循環 ETF（XLY/XLI/XLB/XLF）vs 防禦 ETF（XLP/XLU/XLV/XLRE）等權月收相對強弱計算。
- Yahoo Finance 月頻資料可能有 1–3 個交易日延遲。
""")


# ════════════════════════════════════════════════════════
# Tab F：台股資金輪動
# ════════════════════════════════════════════════════════
def page_rotation():
    render_page_intro("rotation")
    st.caption(
        "追蹤 19 個 TWSE 官方類股指數的動能、資金流向與退潮訊號。"
        "數據來源：台灣證交所 MI_INDEX（類股指數），每日收盤後更新。"
    )

    with st.expander("TWSE 19 類股速查表", expanded=False):
        from fetchers.taiwan_sector import SECTOR_NAMES as _SN
        _ref_df = pd.DataFrame([
            {"代碼": code, "類股名稱": name, "產業大類": _SECTOR_GROUP.get(name, "其他")}
            for code, name in sorted(_SN.items())
        ])
        st.dataframe(_ref_df, hide_index=True, width='stretch')

    with st.spinner("載入台股類股資料…"):
        tw_sector = load_tw_sector_data(data_version)

    sector_df        = tw_sector.get("sector_df",        pd.DataFrame())
    instit_df        = tw_sector.get("instit_df",        pd.DataFrame())
    instit_sector_df = tw_sector.get("instit_sector_df", pd.DataFrame())
    momentum_df      = tw_sector.get("momentum_df",      pd.DataFrame())
    signals          = tw_sector.get("signals", {})

    if sector_df.empty:
        st.warning("台股類股資料暫時無法取得，請稍後重試。")
        st.info("確認 TWSE MI_INDEX20 API 可連線後重新整理頁面。")
    else:
        # ── 輪動訊號橫幅 ──────────────────────────────────────────────────────
        if signals:
            st.markdown(ui.rotation_cards(signals), unsafe_allow_html=True)

        # ── 三子頁 ───────────────────────────────────────────────────────────
        # Only the open sub-tab renders; the 13F tables stay idle until asked for.
        f_snap, f_heat, f_flow, f_13f = st.tabs([
            "輪動快照（四象限）", "動能熱力圖", "資金流向", "13F 法人持倉",
        ], key="rotation_tab", on_change="rerun")

        # ──── F-1：輪動快照（四象限散點圖）────────────────────────────────────
        if f_snap.open:
            with f_snap:
                st.markdown("#### 類股輪動四象限")
                st.caption(
                    "X 軸 = 近 12 週報酬率（長期動能）｜"
                    "Y 軸 = 動能加速度（近 4 週 vs 前 4 週）｜"
                    "點大小 = 最新收盤價（相對大小）"
                )

                if not momentum_df.empty:
                    _mdf = momentum_df.copy()
                    _mdf["quadrant"] = _mdf.apply(
                        lambda r: (
                            "🟢 強勢" if r["ret_short_pct"] >= 0 and r["acceleration"] >= 0 else
                            "🟡 退潮中" if r["ret_short_pct"] >= 0 and r["acceleration"] < 0 else
                            "🔵 升溫中" if r["ret_short_pct"] < 0 and r["acceleration"] >= 0 else
                            "🔴 弱勢"
                        ), axis=1
                    )
                    _color_map = {
                        "🟢 強勢":   "#4caf50",
                        "🟡 退潮中": "#ff9800",
                        "🔵 升溫中": "#2196f3",
                        "🔴 弱勢":   "#f44336",
                    }
                    _mdf["產業"] = _mdf["sector_name"].map(_SECTOR_GROUP).fillna("其他")
                    fig_snap = px.scatter(
                        _mdf,
                        x="ret_long_pct",
                        y="acceleration",
                        text="sector_name",
                        color="quadrant",
                        color_discrete_map=_color_map,
                        size="last_close",
                        size_max=40,
                        hover_data={"產業": True, "ret_short_pct": ":.1f",
                                    "last_close": False, "quadrant": False},
                        labels={
                            "ret_long_pct":  "近 12 週報酬率 (%)",
                            "acceleration":   "動能加速度 (%)",
                            "quadrant":       "象限",
                            "ret_short_pct":  "近 4 週報酬 (%)",
                        },
                        height=520,
                    )
                    fig_snap.update_traces(textposition="top center", textfont_size=11)
                    fig_snap.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.3)")
                    fig_snap.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.3)")

                    # 象限標籤
                    x_max = _mdf["ret_long_pct"].abs().max() * 1.1 or 10
                    y_max = _mdf["acceleration"].abs().max()  * 1.1 or 5
                    for label, xp, yp in [
                        ("強勢", x_max * 0.7,  y_max * 0.7),
                        ("退潮中", x_max * 0.7, -y_max * 0.7),
                        ("升溫中", -x_max * 0.7,  y_max * 0.7),
                        ("弱勢", -x_max * 0.7, -y_max * 0.7),
                    ]:
                        fig_snap.add_annotation(
                            x=xp, y=yp, text=label,
                            font=dict(size=13, color="rgba(255,255,255,0.25)"),
                            showarrow=False,
                        )
                    fig_snap.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font_color="#ddd", margin=dict(l=40, r=20, t=20, b=40),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    show_chart(fig_snap, key="fig_f_snap")

                    # 退潮→候選對照表
                    if signals.get("cooling") and signals.get("warming"):
                        st.markdown("**退潮 → 下一波候選對照**")
                        col_l, col_r = st.columns(2)
                        with col_l:
                            st.markdown("**退潮中（資金可能流出）**")
                            for s in signals["cooling"]:
                                st.markdown(f"- {s}")
                        with col_r:
                            st.markdown("**升溫中（下一波候選）**")
                            for s in signals["warming"]:
                                st.markdown(f"- {s}")
                else:
                    if sector_df.empty:
                        st.warning("類股價格資料載入失敗，請確認 TWSE 連線後重整頁面。")
                    else:
                        n_days_avail = sector_df.groupby("sector_name")["date"].count().min() if not sector_df.empty else 0
                        st.info(
                            f"動能計算需要每個類股至少 60 個交易日的歷史資料（目前：{n_days_avail} 天）。\n\n"
                            "若剛部署，請執行：`docker exec macro-dashboard python scheduler.py --run-now`"
                        )

            # ──── F-2：動能熱力圖 ─────────────────────────────────────────────────
        if f_heat.open:
            with f_heat:
                st.markdown("#### 類股動能熱力圖（近 12 週日報酬）")
                st.caption("顏色：紅=上漲、藍=下跌。欄位=週，列=類股，按近 4 週報酬排序。")

                if not sector_df.empty and "chg_pct" in sector_df.columns:
                    _heat = sector_df.copy()
                    _heat["week"] = _heat["date"].dt.to_period("W").dt.start_time

                    # 週度加總報酬（近 12 週）
                    _weekly = (
                        _heat.groupby(["week", "sector_name"])["chg_pct"]
                        .sum()
                        .reset_index()
                    )
                    _recent_weeks = sorted(_weekly["week"].unique())[-12:]
                    _weekly = _weekly[_weekly["week"].isin(_recent_weeks)]

                    _pivot = _weekly.pivot(index="sector_name", columns="week", values="chg_pct").fillna(0)

                    # 先按產業大類分組，同組內再按近 4 週報酬排序
                    _recent4_ret = _pivot.iloc[:, -4:].sum(axis=1) if len(_pivot.columns) >= 4 else _pivot.sum(axis=1)
                    _pivot = _pivot.reindex(
                        sorted(
                            _pivot.index,
                            key=lambda s: (
                                _GROUP_ORDER.get(_SECTOR_GROUP.get(s, "其他"), 99),
                                -_recent4_ret.get(s, 0),
                            ),
                        )
                    )

                    # 欄位標籤簡化為 mm/dd
                    col_labels = [f"{c.month:02d}/{c.day:02d}" for c in _pivot.columns]

                    fig_heat = go.Figure(go.Heatmap(
                        z=_pivot.values,
                        x=col_labels,
                        y=_pivot.index.tolist(),
                        colorscale=[
                            [0.0, "#1a5276"], [0.4, "#2980b9"], [0.5, "#222"],
                            [0.6, "#e74c3c"], [1.0, "#7b241c"],
                        ],
                        zmid=0,
                        text=[[f"{v:.1f}%" for v in row] for row in _pivot.values],
                        texttemplate="%{text}",
                        textfont_size=9,
                        hovertemplate="類股: %{y}<br>週: %{x}<br>報酬: %{z:.1f}%<extra></extra>",
                    ))
                    fig_heat.update_layout(
                        height=max(400, len(_pivot) * 28),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font_color="#ddd",
                        xaxis=dict(side="top"),
                        margin=dict(l=100, r=20, t=60, b=20),
                    )
                    show_chart(fig_heat, key="fig_f_heat")
                else:
                    st.info("熱力圖需要 sector_df 包含 chg_pct 欄位，目前資料尚未就緒。")

                # ── 三大法人整體市場買賣超 ──────────────────────────────────────
                if not instit_df.empty and "institution" in instit_df.columns:
                    _data_date = instit_df["date"].max()
                    _data_date_str = pd.Timestamp(_data_date).strftime("%Y-%m-%d")
                    st.markdown(f"#### 三大法人整體市場淨買超（NT$ 千元）　<span style='font-size:0.75em;color:#888;font-weight:normal;'>資料日期：{_data_date_str}</span>", unsafe_allow_html=True)
                    st.caption("TWSE BFI82U：外資、投信、自營商整體市場買賣差額。正值＝淨買，負值＝淨賣。")
                    # Most recent trading day
                    _latest_instit = (
                        instit_df[instit_df["date"] == _data_date]
                        .sort_values("net_amt", ascending=False)
                        [["institution", "buy_amt", "sell_amt", "net_amt"]]
                        .reset_index(drop=True)
                    )
                    _latest_instit.columns = ["法人", "買進（千元）", "賣出（千元）", "淨買超（千元）"]
                    _max_abs = _latest_instit["淨買超（千元）"].abs().max() or 1
                    st.dataframe(
                        _latest_instit.style.background_gradient(
                            subset=["淨買超（千元）"], cmap="RdYlGn",
                            vmin=-_max_abs, vmax=_max_abs,
                        ).format({"買進（千元）": "{:,.0f}", "賣出（千元）": "{:,.0f}",
                                   "淨買超（千元）": "{:,.0f}"}),
                        width='stretch',
                    )
                else:
                    st.markdown("#### 三大法人整體市場淨買超（NT$ 千元）")
                    st.info(
                        "法人買超資料尚未就緒。\n\n"
                        "首次啟動請執行：`docker exec macro-dashboard python scheduler.py --run-now`\n\n"
                        "每日 02:30（台北時間）自動更新。"
                    )

            # ──── F-3：動能排行（資金流向代理指標）────────────────────────────────
        if f_flow.open:
            with f_flow:
                st.markdown("#### 類股動能排行（近 4 週報酬率）")
                st.caption(
                    "台灣證交所目前未提供 JSON 格式的類股成交值 API，以「近 4 週價格動能」作為資金流向代理指標。"
                    "動能強的類股通常伴隨資金流入；動能弱的類股反之。"
                )

                if not momentum_df.empty:
                    from fetchers.taiwan_sector import SECTOR_NAMES as _SN_F3
                    # 建立代碼反查字典：名稱 → 代碼
                    _name_to_code = {v: k for k, v in _SN_F3.items()}

                    _fdf = momentum_df.copy()
                    _fdf["產業大類"] = _fdf["sector_name"].map(_SECTOR_GROUP).fillna("其他")
                    _fdf["代碼"] = _fdf["sector_name"].map(_name_to_code).fillna("—")
                    _fdf["四象限"] = _fdf.apply(
                        lambda r: (
                            "🟢 強勢"   if r["ret_short_pct"] >= 0 and r["acceleration"] >= 0 else
                            "🟡 退潮中" if r["ret_short_pct"] >= 0 and r["acceleration"] <  0 else
                            "🔵 升溫中" if r["ret_short_pct"] <  0 and r["acceleration"] >= 0 else
                            "🔴 弱勢"
                        ), axis=1
                    )
                    _fdf_sorted = _fdf.sort_values("ret_short_pct", ascending=True)

                    # 橫向條形圖：近 4 週報酬率，按產業大類著色
                    _group_colors = {
                        "科技": "#42a5f5", "金融": "#66bb6a", "工業": "#ffa726",
                        "消費": "#ef5350", "原物料": "#ab47bc", "能源": "#26c6da", "其他": "#78909c",
                    }
                    fig_flow = px.bar(
                        _fdf_sorted,
                        x="ret_short_pct",
                        y="sector_name",
                        color="產業大類",
                        color_discrete_map=_group_colors,
                        orientation="h",
                        hover_data={
                            "代碼": True,
                            "ret_long_pct": ":.2f",
                            "acceleration": ":.2f",
                            "四象限": True,
                            "ret_short_pct": ":.2f",
                            "產業大類": False,
                        },
                        labels={
                            "ret_short_pct": "近 4 週報酬率 (%)",
                            "sector_name":   "類股",
                            "ret_long_pct":  "近 12 週報酬率 (%)",
                            "acceleration":  "加速度 (%)",
                        },
                        height=560,
                    )
                    fig_flow.add_vline(x=0, line_dash="dash", line_color="rgba(255,255,255,0.4)")
                    fig_flow.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font_color="#ddd",
                        legend=dict(title="產業大類", orientation="v", x=1.01, y=1),
                        margin=dict(l=10, r=160, t=30, b=40),
                        xaxis=dict(zeroline=False, gridcolor="rgba(255,255,255,0.08)"),
                        yaxis=dict(gridcolor="rgba(0,0,0,0)"),
                    )
                    show_chart(fig_flow, key="fig_f_flow")

                    # 整合速查表：代碼 + 名稱 + 產業 + 動能數據
                    st.markdown("#### 19 類股動能速查表")
                    st.caption("含 TWSE 官方代碼、產業大類、近期動能指標與象限判斷，可作為查詢參考。")
                    _table = (
                        _fdf[["代碼", "sector_name", "產業大類", "ret_short_pct",
                               "ret_long_pct", "acceleration", "四象限"]]
                        .sort_values(
                            by=["產業大類", "ret_short_pct"],
                            key=lambda col: col.map(_GROUP_ORDER) if col.name == "產業大類"
                                            else col,
                            ascending=[True, False],
                        )
                        .rename(columns={
                            "sector_name":   "類股名稱",
                            "ret_short_pct": "近4週報酬(%)",
                            "ret_long_pct":  "近12週報酬(%)",
                            "acceleration":  "加速度(%)",
                        })
                        .reset_index(drop=True)
                    )
                    st.dataframe(
                        _table.style.background_gradient(
                            subset=["近4週報酬(%)", "近12週報酬(%)"],
                            cmap="RdYlGn",
                        ).format({
                            "近4週報酬(%)":  "{:.2f}",
                            "近12週報酬(%)": "{:.2f}",
                            "加速度(%)":     "{:.2f}",
                        }),
                        hide_index=True,
                        width='stretch',
                        height=560,
                    )
                else:
                    st.info(
                        "類股動能資料載入中，請稍後重整頁面。\n\n"
                        "首次啟動請執行：`docker exec macro-dashboard python scheduler.py --run-now`"
                    )

                # ── 三大法人各類股買賣超（BFIAMU） ────────────────────────────────
                st.markdown("#### 三大法人各類股淨買超（BFIAMU）")
                st.caption("來源：台灣證交所 BFIAMU（三大法人各類股買賣超金額統計）｜單位：千元新台幣")
                if not instit_sector_df.empty:
                    # Use latest date available
                    _bfi_latest = instit_sector_df["date"].max()
                    _bfi_day = instit_sector_df[instit_sector_df["date"] == _bfi_latest].copy()
                    _bfi_day = _bfi_day.sort_values("total_net", ascending=False)

                    # Convert to 億元 for readability
                    for _col in ("foreign_net", "trust_net", "dealer_net", "total_net"):
                        _bfi_day[_col] = (_bfi_day[_col] / 100_000).round(2)

                    _bfi_colors = [
                        "#2fbf5b" if v >= 0 else "#e66767"
                        for v in _bfi_day["total_net"]
                    ]
                    fig_bfi = go.Figure(go.Bar(
                        x=list(_bfi_day["total_net"]),
                        y=list(_bfi_day["sector_name"]),
                        orientation="h",
                        marker_color=_bfi_colors,
                        text=[f"{v:+.2f}" for v in _bfi_day["total_net"]],
                        textposition="outside",
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            "合計淨買超：%{x:+.2f} 億<br>"
                            "<extra></extra>"
                        ),
                    ))
                    fig_bfi.update_layout(
                        title=f"三大法人各類股淨買超 — {_bfi_latest.strftime('%Y-%m-%d')}",
                        xaxis_title="淨買超（億元）", yaxis_title="",
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font_color="#ddd",
                        margin=dict(l=10, r=80, t=45, b=30),
                        height=max(380, len(_bfi_day) * 28 + 80),
                        showlegend=False,
                    )
                    fig_bfi.add_vline(x=0, line_dash="dash",
                                      line_color="rgba(255,255,255,0.3)")
                    show_chart(fig_bfi, key="fig_f_bfi")

                    # Detail table: foreign / trust / dealer breakdown
                    _bfi_tbl = _bfi_day[["sector_name", "foreign_net",
                                          "trust_net", "dealer_net", "total_net"]].rename(columns={
                        "sector_name": "類股",
                        "foreign_net": "外資（億）",
                        "trust_net":   "投信（億）",
                        "dealer_net":  "自營商（億）",
                        "total_net":   "合計（億）",
                    }).reset_index(drop=True)
                    st.dataframe(
                        _bfi_tbl.style.background_gradient(
                            subset=["合計（億）"], cmap="RdYlGn", vmin=-5, vmax=5),
                        hide_index=True, width='stretch',
                    )
                else:
                    st.info(
                        "三大法人各類股資料暫無法取得（TWSE BFIAMU 端點）。"
                        "非交易日或 API 暫時不可用時會顯示此訊息。"
                    )

            # ──── F-4：13F 法人持倉 ───────────────────────────────────────────────
        if f_13f.open:
            with f_13f:
                st.subheader("13F 機構持倉 — Smart Money 動態")
                st.caption(
                    "整合 SEC EDGAR 13F-HR / 13F-HR/A：Berkshire、Citadel、Two Sigma 等 20 大機構。"
                    "以 CUSIP 為主鍵去重；13F-HR/A 修訂版優先。三個維度排名：股數 / 市值 / 機構共識。"
                    "首次載入約 20-30 秒，之後 24 小時快取。"
                )

                # 13F 代理指標（ETF 量能差）
                st.markdown("#### 循環 vs 防禦量能差（代理指標）")
                st.caption(
                    "循環 vs 防禦 ETF 成交量加速度差值（代理版）｜"
                    "正值 = 機構資金偏向景氣循環；負值 = 偏向防禦"
                )
                tf_df = filt("THIRTEENF_NET_ADD")
                if tf_df is not None and not tf_df.empty:
                    fig_13f_proxy = fill_chart(
                        tf_df, "13F 代理指標（循環/防禦量能差）", "比率差",
                        ref_y=0,
                        hover_fmt="%{x|%Y-%m}<br>差值: %{y:.3f}<extra></extra>",
                    )
                    if fig_13f_proxy:
                        show_chart(fig_13f_proxy, key='fig_13f_proxy')
                    latest_13f_p = tf_df.iloc[-1]["value"]
                    label_13f_p = "機構偏向景氣循環 🟢" if latest_13f_p > 0 else "機構偏向防禦 🔴"
                    st.metric("最新 13F 偏好", label_13f_p, f"{latest_13f_p:+.3f}")
                else:
                    st.info("13F 代理指標資料抓取中（Yahoo Finance ETF 量能）")

                # SEC EDGAR 13F Smart Money
                _13f_hd, _13f_bt = st.columns([3, 1])
                with _13f_hd:
                    st.markdown(
                        "**方法**：CUSIP 主鍵去重 → 各機構當季 vs 上季持股差值 → 20 大機構加總。"
                        "僅計 SOLE / DFND 自主裁量持股，避免選擇性持股雙重計算。"
                    )
                with _13f_bt:
                    if st.button("更新 13F", key='btn_13f_refresh',
                                 help="重新抓取 EDGAR 並更新資料庫（約 20-30 秒）"):
                        refresh_13f_data()
                        current_data_version.clear()
                        st.rerun()

                with st.spinner("載入 13F 持倉…"):
                    _smart = load_13f_data(data_version)

                _quarter    = _smart.get("quarter", "N/A")
                _fund_count = _smart.get("fund_count", 0)
                _tbs  = _smart.get("top_buy_shares",  [])
                _tss  = _smart.get("top_sell_shares", [])
                _tbv  = _smart.get("top_buy_value",   [])
                _tsv  = _smart.get("top_sell_value",  [])
                _cvb  = _smart.get("conviction_buy",  [])
                _cvs  = _smart.get("conviction_sell", [])

                _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                with _mc1:
                    st.metric("最新季度", _quarter)
                with _mc2:
                    st.metric("機構覆蓋", f"{_fund_count} / 20")
                with _mc3:
                    _tracked = len(set(n for n, *_ in _tbs) | set(n for n, *_ in _tss))
                    st.metric("追蹤標的", f"{_tracked} 檔")
                with _mc4:
                    st.metric("🤝 共識持股", f"{len(_cvb) + len(_cvs)} 檔")

                if _tbs or _tss or _tbv or _tsv or _cvb or _cvs:
                    _sub_rank, _sub_s, _sub_v, _sub_c = st.tabs([
                        "分類排名總覽", "股數排名", "市值排名（USD）", "🤝 機構共識"
                    ])

                    with _sub_rank:
                        st.markdown("### 分類排名總覽")
                        st.caption(
                            f"資料期間：{_quarter}　｜　追蹤基金：{_fund_count} 家　｜　"
                            "依淨增持市值排名，附板塊分類標籤"
                        )

                        _rk1, _rk2, _rk3, _rk4 = st.columns(4)
                        with _rk1:
                            st.metric("追蹤基金數", f"{_fund_count} 家")
                        with _rk2:
                            st.metric("淨增持標的", f"{len(_tbs)} 檔")
                        with _rk3:
                            st.metric("淨減持標的", f"{len(_tss)} 檔")
                        with _rk4:
                            st.metric("共識持股", f"{len(_cvb) + len(_cvs)} 檔")

                        _all_sectors = list(_SECTOR_COLOR.keys())
                        _sel_sectors = st.multiselect(
                            "板塊篩選（空白 = 全部）",
                            options=_all_sectors,
                            default=[],
                            key="rank_sector_filter",
                        )

                        _rank_rows = []
                        for rank, (name, val_m, n_funds) in enumerate(_tbv, 1):
                            sector = _classify_sector(name)
                            _rank_rows.append({
                                "排名": rank,
                                "持倉名稱": name,
                                "板塊": sector,
                                "淨增持（$M）": val_m,
                                "共識基金數": n_funds,
                                "訊號": "🟢 買入" if val_m > 0 else "🔴 賣出",
                            })

                        _rank_df = pd.DataFrame(_rank_rows)
                        if _sel_sectors:
                            _rank_df = _rank_df[_rank_df["板塊"].isin(_sel_sectors)]

                        if not _rank_df.empty:
                            _colors = [_SECTOR_COLOR.get(s, _SECTOR_COLOR["其他"])
                                       for s in _rank_df["板塊"]]
                            _text_labels = [
                                f"${v:,.0f}M | {s} | {f}家"
                                for v, s, f in zip(
                                    _rank_df["淨增持（$M）"],
                                    _rank_df["板塊"],
                                    _rank_df["共識基金數"],
                                )
                            ]
                            fig_rank = go.Figure(go.Bar(
                                x=list(_rank_df["淨增持（$M）"]),
                                y=list(_rank_df["持倉名稱"]),
                                orientation='h',
                                marker_color=_colors,
                                text=_text_labels,
                                textposition='outside',
                                hovertemplate='<b>%{y}</b><br>淨增持：$%{x:,.0f}M<br><extra></extra>',
                            ))
                            fig_rank.update_layout(
                                title=f"Top {len(_rank_df)} 持倉 — 分類排名（{_quarter}）",
                                xaxis_title="淨增持市值（$M USD）",
                                yaxis_title="",
                                margin=dict(t=55, b=20, l=175, r=130),
                                height=max(400, len(_rank_df) * 28 + 80),
                                showlegend=False,
                            )
                            show_chart(fig_rank, key='fig_rank_main')

                        st.markdown("#### 板塊資金流向匯總")
                        _sector_summary = (
                            _rank_df.groupby("板塊")["淨增持（$M）"]
                            .sum()
                            .reset_index()
                            .sort_values("淨增持（$M）", ascending=False)
                        )
                        if not _sector_summary.empty:
                            _sc_colors = [_SECTOR_COLOR.get(s, _SECTOR_COLOR["其他"])
                                          for s in _sector_summary["板塊"]]
                            fig_sector = go.Figure(go.Bar(
                                x=list(_sector_summary["板塊"]),
                                y=list(_sector_summary["淨增持（$M）"]),
                                marker_color=_sc_colors,
                                text=[f"${v:,.0f}M" for v in _sector_summary["淨增持（$M）"]],
                                textposition='outside',
                                hovertemplate='%{x}<br>合計：$%{y:,.0f}M<extra></extra>',
                            ))
                            fig_sector.update_layout(
                                title="板塊資金流量（各板塊淨增持加總）",
                                xaxis_title="", yaxis_title="淨增持（$M）",
                                margin=dict(t=55, b=20, l=40, r=20),
                                height=320, showlegend=False,
                            )
                            show_chart(fig_sector, key='fig_rank_sector')

                        st.markdown("#### 持倉明細（可排序）")
                        if not _rank_df.empty:
                            max_val = float(_rank_df["淨增持（$M）"].abs().max()) if len(_rank_df) > 0 else 1000.0
                            st.dataframe(
                                _rank_df,
                                width='stretch',
                                hide_index=True,
                                column_config={
                                    "排名":        st.column_config.NumberColumn(width="small"),
                                    "持倉名稱":   st.column_config.TextColumn(width="medium"),
                                    "板塊":       st.column_config.TextColumn(width="small"),
                                    "淨增持（$M）": st.column_config.ProgressColumn(
                                        "淨增持（$M）",
                                        help="淨增持市值（百萬美元）",
                                        format="$%.1f M",
                                        min_value=0,
                                        max_value=max_val,
                                        width="medium"
                                    ),
                                    "共識基金數": st.column_config.ProgressColumn(
                                        "共識基金數",
                                        help="同向操作的機構數量",
                                        format="%d 家",
                                        min_value=0,
                                        max_value=20,
                                        width="small"
                                    ),
                                    "訊號":       st.column_config.TextColumn(width="small"),
                                },
                            )

                    with _sub_s:
                        _sb_col, _ss_col = st.columns(2)
                        with _sb_col:
                            st.markdown("### 🟢 Top 20 淨增持（股數）")
                            if _tbs:
                                _nb = [n for n, v, f in reversed(_tbs)]
                                _xb = [v // 1_000 for n, v, f in reversed(_tbs)]
                                _fb = [f for n, v, f in reversed(_tbs)]
                                fig_s_buy = go.Figure(go.Bar(
                                    x=_xb, y=_nb, orientation='h',
                                    marker_color='rgba(47,191,91,0.85)',
                                    text=[f"{x:,}K ({f}家)" for x, f in zip(_xb, _fb)],
                                    textposition='outside',
                                    hovertemplate='%{y}<br>淨增持: %{x:,}K股<extra></extra>',
                                ))
                                fig_s_buy.update_layout(
                                    title=f'Top 20 淨增持 — 股數（{_quarter}）',
                                    xaxis_title='股數（千股）', yaxis_title='',
                                    margin=dict(t=50, b=20, l=165, r=90),
                                    height=540, showlegend=False,
                                )
                                show_chart(fig_s_buy, key='fig_13f_s_buy')
                            else:
                                st.info("無買入數據。")
                        with _ss_col:
                            st.markdown("### 🔴 Top 20 淨減持（股數）")
                            if _tss:
                                _ns = [n for n, v, f in reversed(_tss)]
                                _xs = [abs(v) // 1_000 for n, v, f in reversed(_tss)]
                                _fs = [f for n, v, f in reversed(_tss)]
                                fig_s_sell = go.Figure(go.Bar(
                                    x=_xs, y=_ns, orientation='h',
                                    marker_color='rgba(230,103,103,0.85)',
                                    text=[f"{x:,}K ({f}家)" for x, f in zip(_xs, _fs)],
                                    textposition='outside',
                                    hovertemplate='%{y}<br>淨減持: %{x:,}K股<extra></extra>',
                                ))
                                fig_s_sell.update_layout(
                                    title=f'Top 20 淨減持 — 股數（{_quarter}）',
                                    xaxis_title='股數（千股）', yaxis_title='',
                                    margin=dict(t=50, b=20, l=165, r=90),
                                    height=540, showlegend=False,
                                )
                                show_chart(fig_s_sell, key='fig_13f_s_sell')
                            else:
                                st.info("無賣出數據。")

                    with _sub_v:
                        _vb_col, _vs_col = st.columns(2)
                        with _vb_col:
                            st.markdown("### 🟢 Top 20 淨增持（市值 $M）")
                            if _tbv:
                                _nvb = [n for n, v, f in reversed(_tbv)]
                                _xvb = [v for n, v, f in reversed(_tbv)]
                                _fvb = [f for n, v, f in reversed(_tbv)]
                                fig_v_buy = go.Figure(go.Bar(
                                    x=_xvb, y=_nvb, orientation='h',
                                    marker_color='rgba(47,191,91,0.85)',
                                    text=[f"${x:,.0f}M ({f}家)" for x, f in zip(_xvb, _fvb)],
                                    textposition='outside',
                                    hovertemplate='%{y}<br>淨增持: $%{x:,.0f}M<extra></extra>',
                                ))
                                fig_v_buy.update_layout(
                                    title=f'Top 20 淨增持 — 市值（{_quarter}）',
                                    xaxis_title='市值變化（$M USD）', yaxis_title='',
                                    margin=dict(t=50, b=20, l=165, r=100),
                                    height=540, showlegend=False,
                                )
                                show_chart(fig_v_buy, key='fig_13f_v_buy')
                            else:
                                st.info("無市值買入數據。")
                        with _vs_col:
                            st.markdown("### 🔴 Top 20 淨減持（市值 $M）")
                            if _tsv:
                                _nvs = [n for n, v, f in reversed(_tsv)]
                                _xvs = [abs(v) for n, v, f in reversed(_tsv)]
                                _fvs = [f for n, v, f in reversed(_tsv)]
                                fig_v_sell = go.Figure(go.Bar(
                                    x=_xvs, y=_nvs, orientation='h',
                                    marker_color='rgba(230,103,103,0.85)',
                                    text=[f"${x:,.0f}M ({f}家)" for x, f in zip(_xvs, _fvs)],
                                    textposition='outside',
                                    hovertemplate='%{y}<br>淨減持: $%{x:,.0f}M<extra></extra>',
                                ))
                                fig_v_sell.update_layout(
                                    title=f'Top 20 淨減持 — 市值（{_quarter}）',
                                    xaxis_title='市值變化（$M USD）', yaxis_title='',
                                    margin=dict(t=50, b=20, l=165, r=100),
                                    height=540, showlegend=False,
                                )
                                show_chart(fig_v_sell, key='fig_13f_v_sell')
                            else:
                                st.info("無市值賣出數據。")

                    with _sub_c:
                        st.caption(
                            "機構共識 = 至少 **2 家**機構同向操作的標的，按共識機構數排序。"
                            "多家機構同步增持代表更強的確信度（Conviction）；"
                            "同步減持則是系統性警示信號。顏色深淺對應共識機構數。"
                        )
                        _cv_col, _cs_col = st.columns(2)
                        with _cv_col:
                            st.markdown("### 🟢 共識增持")
                            if _cvb:
                                _ncvb = [n for n, f, s in reversed(_cvb)]
                                _xcvb = [f for n, f, s in reversed(_cvb)]
                                _dcvb = [s // 1_000 for n, f, s in reversed(_cvb)]
                                _cmax = max(_xcvb) if _xcvb else 5
                                fig_cv_buy = go.Figure(go.Bar(
                                    x=_xcvb, y=_ncvb, orientation='h',
                                    marker=dict(color=_xcvb, colorscale='Greens',
                                                cmin=2, cmax=_cmax, showscale=True,
                                                colorbar=dict(title='機構數', len=0.5, x=1.02)),
                                    text=[f"{f}家 / {d:,}K股" for f, d in zip(_xcvb, _dcvb)],
                                    textposition='outside',
                                    hovertemplate='%{y}<br>共識機構: %{x}家<extra></extra>',
                                ))
                                fig_cv_buy.update_layout(
                                    title=f'共識增持（≥2 機構，{_quarter}）',
                                    xaxis=dict(title='機構數', dtick=1, range=[0, _cmax + 2]),
                                    yaxis_title='',
                                    margin=dict(t=50, b=20, l=165, r=80),
                                    height=max(400, len(_cvb) * 28 + 80), showlegend=False,
                                )
                                show_chart(fig_cv_buy, key='fig_13f_cv_buy')
                            else:
                                st.info("無共識增持（需 ≥2 家機構）。")
                        with _cs_col:
                            st.markdown("### 🔴 共識減持")
                            if _cvs:
                                _ncvs = [n for n, f, s in reversed(_cvs)]
                                _xcvs = [f for n, f, s in reversed(_cvs)]
                                _dcvs = [abs(s) // 1_000 for n, f, s in reversed(_cvs)]
                                _cmax_s = max(_xcvs) if _xcvs else 5
                                fig_cv_sell = go.Figure(go.Bar(
                                    x=_xcvs, y=_ncvs, orientation='h',
                                    marker=dict(color=_xcvs, colorscale='Reds',
                                                cmin=2, cmax=_cmax_s, showscale=True,
                                                colorbar=dict(title='機構數', len=0.5, x=1.02)),
                                    text=[f"{f}家 / {d:,}K股" for f, d in zip(_xcvs, _dcvs)],
                                    textposition='outside',
                                    hovertemplate='%{y}<br>共識機構: %{x}家<extra></extra>',
                                ))
                                fig_cv_sell.update_layout(
                                    title=f'共識減持（≥2 機構，{_quarter}）',
                                    xaxis=dict(title='機構數', dtick=1, range=[0, _cmax_s + 2]),
                                    yaxis_title='',
                                    margin=dict(t=50, b=20, l=165, r=80),
                                    height=max(400, len(_cvs) * 28 + 80), showlegend=False,
                                )
                                show_chart(fig_cv_sell, key='fig_13f_cv_sell')
                            else:
                                st.info("無共識減持（需 ≥2 家機構）。")
                else:
                    st.error(
                        "⚠**13F 資料無法取得** — 所有機構持倉均回傳空值。\n\n"
                        "常見原因：\n"
                        "1. 網路無法連線至 SEC EDGAR（`data.sec.gov` / `www.sec.gov`）\n"
                        "2. EDGAR 限流（429）— 請按「更新 13F」鈕稍後重試\n"
                        "3. 快取存有舊的空結果 — 請按右上角「更新 13F」清除快取"
                    )
                    _diag_col, _link_col = st.columns([1, 2])
                    with _diag_col:
                        if st.button("診斷 EDGAR 連線", key='btn_edgar_diag'):
                            with st.spinner("測試 SEC EDGAR 連線中…"):
                                _ok, _msg = dfetch.edgar_connectivity_test()
                            if _ok:
                                st.success(f"✅ {_msg}")
                            else:
                                st.error(f"❌ {_msg}")
                    with _link_col:
                        st.markdown(
                            "直接查閱 13F：\n"
                            "- [WhaleWisdom — 13F Holdings](https://whalewisdom.com/)\n"
                            "- [SEC EDGAR 13F 搜尋](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&type=13F-HR)"
                        )

                with st.expander("13F 方法論與進階應用"):
                    st.markdown("""
**13F 核心方法**
- **13F-HR/A 修訂版處理**：同一季度若有修訂申報，以最新 filingDate 版本為準，避免採用過時原始申報。
- **CUSIP 去重**：以 9 位 CUSIP 作為主鍵合併各機構申報，解決不同機構對同一標的使用不同縮寫的問題。
- **三維排名**：股數（反映機構策略性增減持規模）、市值（反映資金流向強度）、機構共識（反映智慧資金的系統性確信）。

**13F 申報日曆**
| 季度 | 截止日 |
|------|--------|
| Q4（Oct–Dec）| 次年 2/14 |
| Q1（Jan–Mar）| 5/15 |
| Q2（Apr–Jun）| 8/14 |
| Q3（Jul–Sep）| 11/14 |

資料有 45 天滯後，建議搭配 Form 13D/13G（5% 以上大量收購即時申報）觀察。
""")
        with st.expander("台股類股指標說明"):
            st.markdown("""
**四象限分類**
| 象限 | 條件 | 意義 |
|------|------|------|
| 🟢 強勢 | 近4週報酬 > 0 且 加速度 > 0 | 資金持續流入，趨勢強健 |
| 🟡 退潮中 | 近4週報酬 > 0 且 加速度 < 0 | 漲幅收斂，資金開始分散 |
| 🔵 升溫中 | 近4週報酬 < 0 且 加速度 > 0 | 跌勢收斂，可能為下一波布局點 |
| 🔴 弱勢 | 近4週報酬 < 0 且 加速度 < 0 | 資金持續流出，避免追入 |

**動能加速度**：近 4 週報酬率 − 前 4 週報酬率，正值表示近期漲勢比之前更快。

**資料來源**：台灣證交所 MI_INDEX20（類股指數），每日收盤後更新。
""")


# ════════════════════════════════════════════════════════
# Tab G — 條件化回測
# ════════════════════════════════════════════════════════
def page_backtest():
    render_page_intro("backtest")
    st.caption(
        "用 10 年 GMI 歷史燈號（兩期確認）對應歷史 TWII / S&P 500 月收，"
        "統計各情境下未來 1 / 3 / 6 / 12 個月的報酬分佈，回答「現在這個燈號歷史上後續走勢如何」。"
    )

    with st.spinner("載入 GMI 歷史與指數月收…"):
        gmi_hist_g = load_gmi_history(data_version, fred_api_key)
        prices_g   = load_index_close_levels(data_version, years_back=12)

    _has_gmi    = gmi_hist_g is not None and not gmi_hist_g.empty and "confirmed_regime" in gmi_hist_g.columns
    _has_prices = any(df is not None and not df.empty for df in prices_g.values())

    if not _has_gmi or not _has_prices:
        st.warning("GMI 歷史或指數價格資料不足；請先確認 scheduler 已執行並可連線 Yahoo Finance。")
    else:
        horizons = DEFAULT_HORIZONS
        # Signal lag: macro prints for month t are only public during t+1.
        returns_df = compute_forward_returns(gmi_hist_g, prices_g, horizons=horizons, signal_lag=1)
        stats_df   = load_regime_stats(data_version, fred_api_key)

        # ── 即時 Callout：當下燈號歷史結果 ────────────────────────────────────
        latest_row    = gmi_hist_g.iloc[-1]
        latest_regime = view["regime"]
        latest_label  = REGIME_LABELS.get(latest_regime, latest_regime)
        st.markdown("### 當下燈號 → 歷史後續報酬")

        if latest_regime in REGIME_ORDER and not stats_df.empty:
            cols_callout = st.columns(len(horizons))
            for i, h in enumerate(horizons):
                with cols_callout[i]:
                    # 對 TWII + SPX 各算一行
                    tw = stats_df[(stats_df["regime"] == latest_regime) &
                                  (stats_df["horizon"] == h) &
                                  (stats_df["market"] == "TWII")]
                    sp = stats_df[(stats_df["regime"] == latest_regime) &
                                  (stats_df["horizon"] == h) &
                                  (stats_df["market"] == "SPX")]
                    body = []
                    if not tw.empty and tw.iloc[0]["n"] > 0:
                        r = tw.iloc[0]
                        body.append(f"TWII 中位 <b>{r['median']:+.1f}%</b> · 勝率 {r['win_rate']:.0f}% (N={int(r['n'])})")
                    if not sp.empty and sp.iloc[0]["n"] > 0:
                        r = sp.iloc[0]
                        body.append(f"SPX 中位 <b>{r['median']:+.1f}%</b> · 勝率 {r['win_rate']:.0f}% (N={int(r['n'])})")
                    st.markdown(
                        f"<div style='background:#1a1d24;border:1px solid #444;border-radius:8px;padding:10px;'>"
                        f"<div style='font-size:0.85em;color:#999'>{h}M 後</div>"
                        f"<div style='font-size:0.9em;line-height:1.5'>" + "<br>".join(body) + "</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            st.caption(f"當下燈號：{latest_label}（基準月 {pd.Timestamp(latest_row['date']).strftime('%Y-%m')}）")
        else:
            st.info("當下燈號為未知或無歷史樣本，跳過 callout。")

        # ── 統計表 ─────────────────────────────────────────────────────────────
        st.markdown("### 完整統計表")
        st.caption("columns：中位數 / 平均 / 勝率 / P10 / P90 / 最差單月 / 樣本數（單位 %，n 除外）")

        regime_label_map = {"green": "🟢 擴張", "yellow": "🟡 觀望", "red": "🔴 收縮", "all": "⚪ 全期"}
        disp = stats_df.copy()
        disp["regime"]  = disp["regime"].map(regime_label_map).fillna(disp["regime"])
        disp["horizon"] = disp["horizon"].astype(int).astype(str) + "M"
        disp = disp.rename(columns={
            "market": "市場", "regime": "燈號", "horizon": "Horizon",
            "median": "中位", "mean": "平均", "win_rate": "勝率",
            "p10": "P10", "p90": "P90", "worst": "最差", "n": "N",
        })
        for col in ("中位", "平均", "勝率", "P10", "P90", "最差"):
            disp[col] = disp[col].round(1)
        st.dataframe(disp, width='stretch', hide_index=True)

        # ── Box plot ───────────────────────────────────────────────────────────
        st.markdown("### 報酬分佈 Box Plot")
        st.caption("色帶寬度 = 歷史報酬區間；中線 = 中位數。注意樣本數 N（右側 callout）。")
        if not returns_df.empty:
            plot_df = returns_df.copy()
            plot_df["fwd_return_pct"] = plot_df["fwd_pct_return"] * 100
            plot_df["horizon_lbl"] = plot_df["horizon"].astype(int).astype(str) + "M"
            plot_df["regime_lbl"]  = plot_df["regime"].map(regime_label_map).fillna(plot_df["regime"])
            color_map = {
                "🟢 擴張": "#2fbf5b",
                "🟡 觀望": "#fab219",
                "🔴 收縮": "#e66767",
            }
            fig_box = px.box(
                plot_df,
                x="horizon_lbl",
                y="fwd_return_pct",
                color="regime_lbl",
                facet_col="market",
                category_orders={
                    "horizon_lbl": [f"{h}M" for h in horizons],
                    "regime_lbl":  ["🟢 擴張", "🟡 觀望", "🔴 收縮"],
                    "market":      ["TWII", "SPX"],
                },
                color_discrete_map=color_map,
                points="all",
                labels={"horizon_lbl": "Horizon", "fwd_return_pct": "報酬 %",
                        "regime_lbl": "燈號"},
            )
            fig_box.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.3)")
            fig_box.update_layout(height=480, boxmode="group",
                                  legend_title_text="燈號")
            show_chart(fig_box, key='fig_gmi_backtest_box')
        else:
            st.info("無對齊樣本，無法繪製 box plot。")

        # ── Cross-correlation heatmap ─────────────────────────────────────────
        st.markdown("### 領先 / 落後相關係數矩陣")
        st.caption(
            "對 GMI 子指標與 TWII / S&P 500 YoY 算 lag −12 ~ +12 月的 Pearson 相關係數。"
            "**正 lag = 指標領先股市**（早期預警價值）；負 lag = 指標反映股市。"
            "顏色越深表示相關性越強。"
        )

        with st.spinner("計算交叉相關矩陣中…"):
            corr_df = load_cross_correlation(data_version, fred_api_key)

        if corr_df.empty:
            st.info("無足夠重疊樣本（需各序列 ≥ 36 月）。")
        else:
            tgt_pick = st.radio(
                "選擇對照市場",
                options=sorted(corr_df["target"].unique()),
                horizontal=True,
                key="gmi_corr_target",
            )
            sub = corr_df[corr_df["target"] == tgt_pick]
            pivot = sub.pivot(index="indicator", columns="lag", values="correlation")
            # 依「最大 |corr| 的 lag」排序（最領先的指標排上方）
            peak_lag = sub.loc[sub.groupby("indicator")["correlation"].apply(
                lambda s: s.abs().idxmax()).values, ["indicator", "lag"]].set_index("indicator")
            order = peak_lag.sort_values("lag", ascending=False).index.tolist()
            pivot = pivot.reindex(order)

            fig_corr = px.imshow(
                pivot,
                color_continuous_scale="RdBu_r",
                zmin=-0.8, zmax=0.8,
                aspect="auto",
                labels={"x": "Lag (月)  →  +n 表示指標領先股市 n 月",
                        "y": "GMI 子指標",
                        "color": "Pearson r"},
                title=f"GMI 子指標 vs {tgt_pick} 12M YoY 相關係數（lag −12 ~ +12）",
            )
            fig_corr.update_xaxes(tickmode="linear", dtick=2)
            fig_corr.update_layout(height=600)
            show_chart(fig_corr, key='fig_gmi_corr_heatmap')

            # Top leaders summary
            st.markdown("#### 最領先的 5 個指標（peak |r| 出現在 lag > 0）")
            leaders_rows = []
            for ind, g in sub.groupby("indicator"):
                idx = g["correlation"].abs().idxmax()
                row = g.loc[idx]
                if row["lag"] > 0:
                    leaders_rows.append({
                        "指標":     ind,
                        "lead (月)": int(row["lag"]),
                        "Pearson r": round(float(row["correlation"]), 3),
                        "樣本數":   int(row["n"]),
                    })
            if leaders_rows:
                leaders = pd.DataFrame(leaders_rows).sort_values("lead (月)", ascending=False).head(5)
                st.dataframe(leaders, width='stretch', hide_index=True)
            else:
                st.info("沒有指標的 peak 落在正 lag 區間。")

        with st.expander("方法與注意事項"):
            st.markdown("""
**Forward return 計算**：訊號月的數據要到下個月才公布，因此以訊號月**下一個月**的月收為進場價（延遲 1 個月），計算 1/3/6/12 月後的報酬。少數數據（如美國製造業新訂單）公布時間更晚，統計仍略偏樂觀。
12M horizon 的最近 12 個月會因為「未來未發生」自動排除。

**燈號定義**：使用 `confirmed_regime`（已套用兩期反鋸齒確認），與 Tab E 顯示一致。

**樣本數警示**：紅燈在過去 10 年出現次數較少，部分 horizon 的 N 可能 < 20，請對應參考 P10/P90 範圍而非僅看中位數。

**Cross-correlation**：
- 對 GMI 子指標的原始值（PMI、YoY%、利差等）與目標市場的 12M 對數報酬，跑 lag = −12 ~ +12。
- 正 lag = 指標領先股市；負 lag = 反過來。要求最少 36 月重疊。
- 「lead 月數」是 |r| 最大時的 lag。peak 落在正 lag 表示該指標在歷史上對該市場有領先性。

**侷限**：
- 本回測為純歷史描述，**不是預測模型**。樣本期 10 年內只經歷一次完整景氣週期（2018-2020、2022-2023），統計推論的外延性有限。
- forward return 為單期 to-from，未計入路徑風險（中間最大回撤需另外實作）。
- Cross-correlation 為 Pearson（線性）相關，對非線性或門檻效應不敏感。
""")


# ════════════════════════════════════════════════════════
# 只執行目前頁面：點擊的成本與其他頁面的圖表數量無關
# ════════════════════════════════════════════════════════
PAGES = {
    "verdict": page_verdict, "radar": page_radar, "demand": page_demand, "cost": page_cost,
    "liquidity": page_liquidity, "equity": page_equity, "gmi": page_gmi,
    "rotation": page_rotation, "backtest": page_backtest, "guide": page_guide,
}
PAGES[active_page]()
