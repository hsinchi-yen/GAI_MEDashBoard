import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import data_fetcher as dfetch
import db_manager
from macro_index import build_macro_index_history, compute_macro_index, get_regime_color, REGIME_LABELS
from streamlit_javascript import st_javascript

# MUST BE FIRST
st.set_page_config(page_title="全球經濟指標儀表板", layout="wide", page_icon="📊")

# UI session cache for DB-backed loaders: matches nightly scheduler frequency.
# load_data() (live-fetch fallback) keeps this as its own TTL.
CACHE_TTL    = 3600       # 1 h — live-fetch fallback only
CACHE_TTL_DB = 86400      # 24 h — DB-backed loaders (data changes once per day)

# ── 13F 板塊分類對照表 ─────────────────────────────────────────────────────
_SECTOR_MAP: dict[str, str] = {
    # 科技（軟體 / 雲端 / 儲存）
    "MICROSOFT":        "科技",  "MSFT": "科技",
    "APPLE":            "科技",  "AAPL": "科技",
    "AMAZON":           "科技",  "AMZN": "科技",
    "ALPHABET":         "科技",  "GOOGL": "科技", "GOOG": "科技",
    "META":             "科技",  "META PLATFORMS": "科技",
    "NETFLIX":          "科技",  "NFLX": "科技",
    "SALESFORCE":       "科技",
    "IBM":              "科技",
    "SERVICENOW":       "科技",
    "WESTERN DIGITAL":  "科技",  "WDC": "科技",
    "SANDISK":          "科技",
    "SEAGATE":          "科技",  "STX": "科技",
    # 半導體
    "NVIDIA":           "半導體", "NVDA": "半導體",
    "TAIWAN SEMI":      "半導體", "TSM": "半導體", "TSMC": "半導體",
    "BROADCOM":         "半導體", "AVGO": "半導體",
    "LAM RESEARCH":     "半導體", "LRCX": "半導體",
    "APPLIED MATER":    "半導體", "AMAT": "半導體",
    "QUALCOMM":         "半導體", "QCOM": "半導體",
    "AMD":              "半導體", "ADVANCED MICRO": "半導體",
    "INTEL":            "半導體", "INTC": "半導體",
    "MICRON":           "半導體", "MU": "半導體",
    "TEXAS INST":       "半導體", "TXN": "半導體",
    # 金融（只保留完整公司名關鍵字；移除單字母/雙字母 ticker 避免誤判）
    "JPMORGAN":         "金融",  "JPM": "金融",
    "GOLDMAN":          "金融",
    "BERKSHIRE":        "金融",  "BRK": "金融",
    "BROOKFIELD":       "金融",
    "VISA":             "金融",
    "MASTERCARD":       "金融",
    "BANK OF AMER":     "金融",  "BAC": "金融",
    "CITIGROUP":        "金融",
    # 醫療
    "ELI LILLY":        "醫療",  "LLY": "醫療",
    "JOHNSON":          "醫療",  "JNJ": "醫療",
    "UNITEDHEALTH":     "醫療",  "UNH": "醫療",
    "ABBVIE":           "醫療",  "ABBV": "醫療",
    "MERCK":            "醫療",  "MRK": "醫療",
    # 消費
    "WALMART":          "消費",  "WMT": "消費",
    "COSTCO":           "消費",  "COST": "消費",
    "COUPANG":          "消費",  "CPNG": "消費",
    "TESLA":            "消費",  "TSLA": "消費",
    "HOME DEPOT":       "消費",
    "PROCTER":          "消費",
    "COCA-COLA":        "消費",
    "PEPSICO":          "消費",
    # 能源/工業
    "CHEVRON":          "能源",  "CVX": "能源",
    "EXXON":            "能源",  "XOM": "能源",
    "LINDE":            "工業",
    "GENERAL ELECTRIC": "工業",
    "CATERPILLAR":      "工業",
}

_SECTOR_COLOR: dict[str, str] = {
    "科技":   "rgba(55,138,221,0.85)",
    "半導體": "rgba(127,119,221,0.85)",
    "金融":   "rgba(186,117,23,0.85)",
    "醫療":   "rgba(99,153,34,0.85)",
    "消費":   "rgba(212,83,126,0.85)",
    "能源":   "rgba(186,101,29,0.85)",
    "工業":   "rgba(136,135,128,0.85)",
    "其他":   "rgba(100,100,100,0.6)",
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


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
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
    data['NDC_LEADING']   = dfetch.fetch_ndc_leading_index()

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
    data['HY_SPREAD'] = dfetch.fetch_hy_spread(fred_key)
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


@st.cache_data(ttl=CACHE_TTL_DB, show_spinner=False)
def load_all_from_db(fred_key: str) -> dict:
    """
    Load all macro indicators from SQLite (15-year history).

    Reads directly from DB — no network calls during UI interaction.
    Year-range filtering is done by filt() after this returns, so
    switching the sidebar selector costs zero fetch time.

    Falls back to load_data(fred_key) if the DB has no entries at all
    (e.g. first launch before scheduler has run).
    """
    if not db_manager.list_keys():
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
    data['HY_SPREAD'] = R('hy_spread')
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


@st.cache_data(ttl=CACHE_TTL_DB, show_spinner=False)
def load_gmi_history(fred_key: str) -> pd.DataFrame:
    """GMI 歷史時間軸（10 年月頻）— 24h session cache，配合每日排程器。"""
    data = load_all_from_db(fred_key)
    return build_macro_index_history(data, lookback_years=10)


@st.cache_data(ttl=86400, show_spinner=False)
def load_13f_data() -> dict:
    """SEC EDGAR 13F 機構持倉 — 每日快取（24h TTL）；首次載入約 20-30 秒。"""
    return dfetch.fetch_13f_smart_money(n_top=20)


@st.cache_data(ttl=3600 * 2, show_spinner=False)
def load_tw_institutional(n_days: int = 5) -> dict:
    """台灣三大法人買賣超排行 — 每 2 小時快取；首次載入約 10-30 秒。"""
    return dfetch.fetch_tw_institutional(n_days)


@st.cache_data(ttl=CACHE_TTL_DB, show_spinner=False)
def load_tw_sector_data() -> dict:
    """台股類股輪動資料 — 優先讀 DB（scheduler 02:30 更新），fallback 至 live fetch。"""
    from fetchers.taiwan_sector import (
        fetch_tw_sector_indices,
        fetch_tw_sector_turnover,
        fetch_tw_sector_institutional,
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
        # Fallback: live fetch (first run before scheduler populates DB).
        # 70 days covers the 60-day minimum for momentum calc with a small buffer.
        sector_df = fetch_tw_sector_indices(n_days=70)

    # ── turnover: blob_cache (60-day snapshot) ────────────────────────────────
    turnover_df = db_manager.read("tw_sector_turnover")
    if turnover_df is None or turnover_df.empty:
        turnover_df = fetch_tw_sector_turnover(n_days=60)

    # ── institutional net buy/sell by sector (5-day snapshot) ─────────────────
    instit_df = db_manager.read("tw_sector_institutional")
    if instit_df is None or instit_df.empty:
        instit_df = fetch_tw_sector_institutional(n_days=5)

    momentum_df = calc_sector_momentum(sector_df) if not sector_df.empty else pd.DataFrame()
    signals     = detect_rotation_signal(momentum_df) if not momentum_df.empty else {}
    return {
        "sector_df":   sector_df,
        "turnover_df": turnover_df,
        "instit_df":   instit_df,
        "momentum_df": momentum_df,
        "signals":     signals,
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
    if is_yoy:
        fig.add_hline(y=0, line_dash="dash", line_color="orange",
                      annotation_text="0% 零增長線", annotation_position="bottom right")
    fig.update_layout(
        xaxis_title="", yaxis_title=y_label, hovermode="x unified",
        margin=dict(t=50, b=20, l=40, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


def fill_chart(df, title, y_label, pos_color='rgba(38,166,91,0.3)', neg_color='rgba(234,57,67,0.3)',
               pos_line='rgb(38,166,91)', neg_line='rgb(234,57,67)', ref_y=None, hover_fmt=None):
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
        fig.add_hline(y=ref_y, line_dash='dash', line_color='orange',
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
# 側邊欄（設定區）
# ════════════════════════════════════════════════════════

# 從瀏覽器 localStorage 讀取已儲存的 FRED API Key
# st_javascript 在第一次渲染前回傳 0，需過濾掉非字串值
_ls_val = st_javascript("localStorage.getItem('FRED_API_KEY') || ''")
_stored_key = _ls_val if isinstance(_ls_val, str) else ""

with st.sidebar:
    st.header("⚙️ 設定中心")

    st.subheader("🔑 FRED API Key")
    input_key = st.text_input(
        "FRED API Key",
        value=_stored_key,
        type="password",
        placeholder="貼上您的 FRED API Key…",
    )
    col_save, col_clear = st.columns(2)
    with col_save:
        if st.button("💾 儲存", width='stretch'):
            _safe = input_key.replace("\\", "\\\\").replace("'", "\\'")
            st_javascript(f"localStorage.setItem('FRED_API_KEY', '{_safe}'); 1")
            st.success("已儲存至瀏覽器")
    with col_clear:
        if st.button("🗑️ 清除", width='stretch'):
            st_javascript("localStorage.removeItem('FRED_API_KEY'); 1")
            st.info("已清除")

    fred_api_key = input_key

    st.markdown("---")
    st.subheader("🗓️ 圖表時間區間")
    st.caption("資料庫存有最近 15 年歷史，切換年份直接從 DB 讀取，不重新抓取。")
    range_years = st.selectbox(
        "選擇呈現範圍",
        [3, 5, 7, 10, 15],
        index=1,
        format_func=lambda x: f"近 {x} 年",
    )
    st.markdown("---")

st.title("📊 全球經濟指標動態看板")
st.markdown(
    "資料來源：ISM · CIER · NBS · 內閣府 · Eurostat · FRED · DBnomics · 財政部 · 央行 · Yahoo Finance　｜　**資料庫每日自動更新，最多 15 年歷史**"
)

with st.spinner('從資料庫載入指標數據中…'):
    data = load_all_from_db(fred_api_key)

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


# ── 全局 GMI 計算（供橫幅與側欄使用）──
gmi = compute_macro_index(data)

# ════════════════════════════════════════════════════════
# 全局景氣信號橫幅（常駐，所有 Tab 均可見）
# ════════════════════════════════════════════════════════
_REGIME_STYLE = {
    "green":   "background:#071f10; border:1.5px solid #26a65b; color:#c8f5df;",
    "yellow":  "background:#1f1700; border:1.5px solid #f5c518; color:#fff3b0;",
    "red":     "background:#1f0709; border:1.5px solid #ea3943; color:#ffcccd;",
    "unknown": "background:#1a1a2e; border:1.5px solid #666; color:#ccc;",
}
_rstyle = _REGIME_STYLE.get(gmi["regime"], _REGIME_STYLE["unknown"])
_vix   = get_latest(data.get('VIX'))
_hy    = get_latest(data.get('HY_SPREAD'))
_dxy   = get_latest(data.get('DXY'))
_twd   = get_latest(data.get('TWD_USD'))
_twpmi = get_latest(data.get('TW_PMI'))
_uspmi = get_latest(data.get('US_PMI'))
_cu    = get_latest(data.get('COPPER_YOY'))

_bparts = []
if _vix:   _bparts.append(f"VIX <b>{_vix:.1f}</b>")
if _hy:    _bparts.append(f"HY <b>{_hy:.0f}bps</b>")
if _dxy:   _bparts.append(f"DXY <b>{_dxy:.1f}</b>")
if _twd:   _bparts.append(f"TWD <b>{_twd:.2f}</b>")
if _twpmi: _bparts.append(f"🇹🇼PMI <b>{_twpmi:.1f}</b>")
if _uspmi: _bparts.append(f"🇺🇸PMI <b>{_uspmi:.1f}</b>")
if _cu:    _bparts.append(f"銅YoY <b>{_cu:+.1f}%</b>")

st.markdown(
    f'<div style="{_rstyle} border-radius:10px; padding:10px 18px; margin-bottom:4px;">'
    f'<span style="font-size:1.1em; font-weight:bold;">{gmi["regime_label"]}</span>'
    f'&nbsp;&nbsp;GMI <b>{gmi["score"]}/20</b>&nbsp; 擴散 <b>{gmi["diffusion"]:.1f}%</b>'
    f'&nbsp;&nbsp;<span style="opacity:0.4">|</span>&nbsp;&nbsp;'
    f'<span style="font-size:0.85em;">{"　".join(_bparts)}</span>'
    f'&nbsp;&nbsp;<span style="font-size:0.75em; opacity:0.55; float:right;">DB · 每日更新</span>'
    f'</div>',
    unsafe_allow_html=True,
)

# ════════════════════════════════════════════════════════
# 側邊欄景氣週期定位 Widget（橫幅計算完後才能插入）
# ════════════════════════════════════════════════════════
_cycle_map = {
    "green":   ("擴張期", "多數指標正向，留意高點訊號", "#26a65b"),
    "yellow":  ("觀望期", "訊號混合，追蹤轉折方向", "#f5c518"),
    "red":     ("收縮期", "多數指標轉弱，等待觸底", "#ea3943"),
}
_cd = _cycle_map.get(gmi["regime"], ("未知", "", "#888"))
with st.sidebar:
    st.subheader("📍 景氣週期定位")
    st.markdown(
        f'<div style="border-left:4px solid {_cd[2]}; padding:6px 10px; '
        f'background:rgba(255,255,255,0.03); border-radius:4px; font-size:0.9em; line-height:1.7;">'
        f'<b>{_cd[0]}</b><br>'
        f'<span style="opacity:0.75; font-size:0.87em">{_cd[1]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"GMI {gmi['score']}/20 · 擴散 {gmi['diffusion']:.0f}% · 信心 {gmi['confidence']}")
    st.markdown("---")

# ════════════════════════════════════════════════════════
# 主分頁 Tab 導航
# ════════════════════════════════════════════════════════
tab_ov, tab_a, tab_b, tab_c, tab_d, tab_e, tab_f = st.tabs([
    "📋 Overview", "A 需求感測", "B 成本/獲利", "C 流動性/風險", "D 股市比對", "E 總經指數", "F 資金輪動"
])


# ════════════════════════════════════════════════════════
# Overview Tab
# ════════════════════════════════════════════════════════
with tab_ov:
    st.markdown("## 📋 全局概覽 — 當前宏觀快照")
    st.caption("整合五大面向即時讀值，提供一頁式決策參考。點選上方 Tab 進入各面板深度分析。")

    # Row 1：GMI 燈號 + 驅動/拖累
    ov1, ov2, ov3 = st.columns([1, 1.5, 1.5])
    _regime_bg = {
        "green":  "background:#0d3b24; border:2px solid #26a65b;",
        "yellow": "background:#3b2e00; border:2px solid #ffc800;",
        "red":    "background:#3b0d10; border:2px solid #ea3943;",
        "unknown":"background:#333; border:2px solid #888;",
    }
    with ov1:
        st.markdown(
            f'<div style="{_regime_bg.get(gmi["regime"], _regime_bg["unknown"])} '
            f'border-radius:12px; padding:16px; text-align:center;">'
            f'<div style="font-size:2.2em; margin-bottom:2px">{gmi["regime_label"].split()[0]}</div>'
            f'<div style="font-weight:bold; font-size:1em;">{" ".join(gmi["regime_label"].split()[1:])}</div>'
            f'<div style="font-size:0.9em; margin-top:10px;">GMI&nbsp;<b>{gmi["score"]}/20</b></div>'
            f'<div style="font-size:0.8em; opacity:0.75;">擴散 {gmi["diffusion"]:.1f}%</div>'
            f'<div style="font-size:0.75em; opacity:0.6;">{gmi["confidence"]} 信心</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with ov2:
        st.markdown("**🚀 正向驅動（前 3 名）**")
        if gmi["top_drivers"]:
            for d in gmi["top_drivers"]:
                st.success(f"**#{d['id']} {d['name']}** — {d['raw']}")
        else:
            st.info("目前無正向訊號")
    with ov3:
        st.markdown("**⚠️ 拖累因子（前 3 名）**")
        if gmi["top_drags"]:
            for d in gmi["top_drags"]:
                st.error(f"**#{d['id']} {d['name']}** — {d['raw']}")
        else:
            st.success("所有指標均正向")

    st.divider()

    # Row 2：需求脈動
    st.markdown("##### A｜需求脈動")
    d1, d2, d3, d4, d5 = st.columns(5)
    _ov_demand = [
        (d1, "🇺🇸 US PMI",    'US_PMI',            None,  False),
        (d2, "🇹🇼 TW PMI",    'TW_PMI',            None,  False),
        (d3, "🇨🇳 CN PMI",    'CN_PMI',            None,  False),
        (d4, "🇰🇷 韓出口 YoY", 'KR_EXP_YOY',       "%",   False),
        (d5, "🇹🇼 台積電 YoY", 'TSMC_REVENUE_YOY', "%",   False),
    ]
    for col, label, key, unit, inv in _ov_demand:
        with col:
            v = get_latest(data.get(key)); p = get_prev(data.get(key))
            suf = unit or ""
            st.metric(label,
                      f"{v:.1f}{suf}" if v is not None else "N/A",
                      delta=f"{v-p:+.1f}{suf}" if v is not None and p is not None else None,
                      delta_color="inverse" if inv else "normal")

    # Row 3：流動性與風險
    st.markdown("##### C｜流動性與風險")
    r1, r2, r3, r4, r5 = st.columns(5)
    _t10y2y_v = get_latest(data.get('T10Y2Y')); _t10y2y_p = get_prev(data.get('T10Y2Y'))
    _rr_v     = get_latest(data.get('US_REAL_RATE')); _rr_p = get_prev(data.get('US_REAL_RATE'))
    with r1:
        v = get_latest(data.get('VIX')); p = get_prev(data.get('VIX'))
        st.metric("🚨 VIX", f"{v:.1f}" if v else "N/A",
                  delta=f"{v-p:+.1f}" if v and p else None, delta_color="inverse")
    with r2:
        v = get_latest(data.get('HY_SPREAD')); p = get_prev(data.get('HY_SPREAD'))
        st.metric("💳 HY利差", f"{v:.0f}bps" if v else "N/A",
                  delta=f"{v-p:+.0f}" if v and p else None, delta_color="inverse")
    with r3:
        st.metric("📉 10Y-2Y",
                  f"{_t10y2y_v:.3f}%" if _t10y2y_v is not None else "N/A",
                  delta=f"{_t10y2y_v-_t10y2y_p:+.3f}" if _t10y2y_v is not None and _t10y2y_p is not None else None)
    with r4:
        v = get_latest(data.get('DXY')); p = get_prev(data.get('DXY'))
        st.metric("💵 DXY", f"{v:.1f}" if v else "N/A",
                  delta=f"{v-p:+.1f}" if v and p else None, delta_color="inverse")
    with r5:
        st.metric("📐 實質利率",
                  f"{_rr_v:.2f}%" if _rr_v is not None else "N/A",
                  delta=f"{_rr_v-_rr_p:+.2f}" if _rr_v is not None and _rr_p is not None else None,
                  delta_color="inverse")

    # Row 4：市場比對
    st.markdown("##### D｜市場比對")
    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        v = get_latest(data.get('SP500_YOY')); p = get_prev(data.get('SP500_YOY'))
        st.metric("🇺🇸 S&P500 YoY", f"{v:.1f}%" if v is not None else "N/A",
                  delta=f"{v-p:+.1f}%" if v is not None and p is not None else None)
    with m2:
        v = get_latest(data.get('TAIEX_YOY')); p = get_prev(data.get('TAIEX_YOY'))
        st.metric("🇹🇼 TAIEX YoY", f"{v:.1f}%" if v is not None else "N/A",
                  delta=f"{v-p:+.1f}%" if v is not None and p is not None else None)
    with m3:
        v = get_latest(data.get('FED_FUNDS')); p = get_prev(data.get('FED_FUNDS'))
        st.metric("🏦 Fed Funds", f"{v:.2f}%" if v is not None else "N/A",
                  delta=f"{v-p:+.2f}" if v is not None and p is not None else None, delta_color="inverse")
    with m4:
        v = get_latest(data.get('COPPER_YOY')); p = get_prev(data.get('COPPER_YOY'))
        st.metric("🔶 銅 YoY", f"{v:.1f}%" if v is not None else "N/A",
                  delta=f"{v-p:+.1f}%" if v is not None and p is not None else None)
    with m5:
        v = get_latest(data.get('TW_M1B_YOY')); p = get_prev(data.get('TW_M1B_YOY'))
        st.metric("🇹🇼 M1B YoY", f"{v:.1f}%" if v is not None else "N/A",
                  delta=f"{v-p:+.1f}%" if v is not None and p is not None else None)

    st.divider()
    st.caption(
        "💡 **解讀提示** — GMI 擴散率 ≥75% 確認擴張期；VIX >30 為市場壓力警戒；HY >400bps 信用緊張；"
        "10Y-2Y 倒掛後轉正是衰退臨近信號；DXY 急升壓縮新興市場資金空間；中國信貸脈衝正值領先全球需求約 9~12 個月。"
    )


# ════════════════════════════════════════════════════════
# Panel A：終端需求感測
# ════════════════════════════════════════════════════════
with tab_a:
    st.divider()
    st.markdown("## 🅰️ 終端需求感測 (Demand Dynamics)")

    # KPI 快訊列
    kc1, kc2, kc3 = st.columns(3)
    with kc1:
        tw_pmi = data.get('TW_PMI')
        v = tw_pmi.iloc[-1]['value'] if tw_pmi is not None and not tw_pmi.empty else None
        p = tw_pmi.iloc[-2]['value'] if tw_pmi is not None and len(tw_pmi) > 1 else v
        st.metric("🇹🇼 台灣製造業 PMI", f"{v:.1f}" if v else "N/A",
                  delta=f"{v-p:+.1f}" if v and p else None)
    with kc2:
        tw_exp = data.get('TW_EXP_AMOUNT')
        ev = tw_exp.iloc[-1]['value'] if tw_exp is not None and not tw_exp.empty else None
        ed = tw_exp.iloc[-1]['date'].strftime('%Y-%m') if tw_exp is not None and not tw_exp.empty else ''
        st.metric(f"🇹🇼 台灣出口 ({ed})", f"{ev:,.0f} M$" if ev else "N/A")
    with kc3:
        kr = data.get('KR_EXP_YOY')
        kv = kr.iloc[-1]['value'] if kr is not None and not kr.empty else None
        kp = kr.iloc[-2]['value'] if kr is not None and len(kr) > 1 else kv
        st.metric("🇰🇷 韓國出口 YoY", f"{kv:.1f}%" if kv else "N/A",
                  delta=f"{kv-kp:+.1f}%" if kv and kp else None)
    st.markdown("---")

    # ── PMI ────────────────────────────────────────────────────────────────────
    st.subheader("🏭 製造業 PMI 採購經理人指數")
    st.caption("美: ISM · 台: CIER · 中: NBS · 日: 內閣府 DI · 歐: Eurostat ICI(+50)")
    fig_pmi = build_figure("五大經濟體 PMI / 景氣指數", {
        "🇺🇸 美國 (ISM)":      filt('US_PMI'),
        "🇹🇼 台灣 (CIER)":     filt('TW_PMI'),
        "🇨🇳 中國 (NBS)":      filt('CN_PMI'),
        "🇯🇵 日本 (DI)":       filt('JP_PMI'),
        "🇪🇺 歐元區 (ICI+50)": filt('EU_PMI'),
    }, y_label="指數（50 榮枯線）")
    if fig_pmi:
        fig_pmi.add_hline(y=50, line_dash="dash", line_color="yellow",
                          annotation_text="50 榮枯線", annotation_position="bottom right")
        col_chart, col_info = st.columns([3, 1])
        with col_chart:
            st.plotly_chart(fig_pmi, width='stretch', key='fig_pmi')
        with col_info:
            st.markdown("**最新讀值**")
            for key, label in [('US_PMI','🇺🇸'),('TW_PMI','🇹🇼'),('CN_PMI','🇨🇳'),
                                ('JP_PMI','🇯🇵'),('EU_PMI','🇪🇺')]:
                v = get_latest(data.get(key))
                st.metric(label, f"{v:.1f}" if v else "N/A")
    else:
        st.warning("PMI 資料暫時無法載入，請確認 FRED API Key 或等待來源回應。")

    # ── 零售銷售 ───────────────────────────────────────────────────────────────
    st.subheader("🛒 美國零售銷售")
    st.caption("FRED RSAFS — Advance Retail Sales，消費端需求強弱的高頻指標")
    col_r1, col_r2 = st.columns(2)
    with col_r1:
        fig_ret = build_figure("美國零售銷售金額 (百萬美元)",
                               {"🇺🇸 US Retail Sales": filt('US_RETAIL')}, y_label="百萬美元")
        if fig_ret:
            st.plotly_chart(fig_ret, width='stretch', key='fig_ret')
    with col_r2:
        fig_ry = build_figure("美國零售 YoY (%)",
                              {"🇺🇸 US Retail YoY": filt('US_RETAIL_YOY')},
                              y_label="年增率 (%)", is_yoy=True)
        if fig_ry:
            st.plotly_chart(fig_ry, width='stretch', key='fig_ry')

    # ── 消費者信心 ─────────────────────────────────────────────────────────────
    st.subheader("😊 密西根大學消費者信心指數 (UMCSENT)")
    st.caption("FRED UMCSENT — 消費佔美國 GDP 近 70%，此指標為景氣轉折輔助訊號")
    um = filt('UMCSENT')
    if um is not None and not um.empty:
        col_um, col_um_m = st.columns([3, 1])
        with col_um:
            fig_um = go.Figure()
            fig_um.add_trace(go.Scatter(x=um['date'], y=um['value'], fill='tozeroy',
                                        fillcolor='rgba(255,165,0,0.15)',
                                        line=dict(color='rgb(255,165,0)', width=2),
                                        name='UMCSENT',
                                        hovertemplate='%{x|%Y-%m}<br>指數: %{y:.1f}<extra></extra>'))
            fig_um.update_layout(title='密西根消費者信心 (1966Q1=100)', xaxis_title='',
                                  yaxis_title='Index', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            st.plotly_chart(fig_um, width='stretch', key='fig_um')
        with col_um_m:
            lat = um.iloc[-1]; prv = um.iloc[-2] if len(um) > 1 else lat
            st.metric(f"最新（{lat['date'].strftime('%Y-%m')}）",
                      f"{lat['value']:.1f}", delta=f"{lat['value']-prv['value']:+.1f}")
    else:
        st.warning("無法載入 UMCSENT，請確認 FRED API Key。")

    # ── 台灣出口 ───────────────────────────────────────────────────────────────
    st.subheader("🚢 台灣出口表現")
    st.caption("資料來源：中華民國財政部統計處")
    exp_t1, exp_t2, exp_t3 = st.tabs(["📊 出口金額", "📈 出口 YoY", "📅 年度比較"])
    with exp_t1:
        fig_exp = build_figure("台灣出口貨物總額 (百萬美元)",
                               {"🇹🇼 出口金額": filt('TW_EXP_AMOUNT')}, y_label="百萬美元")
        if fig_exp:
            st.plotly_chart(fig_exp, width='stretch', key='fig_exp')
        else:
            st.warning("出口金額資料暫時無法取得。")
    with exp_t2:
        fig_eyoy = fill_chart(filt('TW_EXP_YOY'), '🇹🇼 台灣出口年增率 (YoY %)', '年增率 (%)', ref_y=0)
        if fig_eyoy:
            st.plotly_chart(fig_eyoy, width='stretch', key='fig_eyoy')
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
            st.plotly_chart(fig_ann, width='stretch', key='fig_ann')

    # ── 韓國出口 vs 台灣 YoY ──────────────────────────────────────────────────
    st.subheader("🇰🇷 韓國出口 YoY vs 🇹🇼 台灣出口 YoY")
    st.caption("韓國每月 1 日前後公布，比台灣財政部早 2~3 週，是半導體週期最早的官方高頻訊號")
    col_kr, col_tw_exp = st.columns(2)
    with col_kr:
        fig_kr = fill_chart(filt('KR_EXP_YOY'), '🇰🇷 韓國出口 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_kr:
            st.plotly_chart(fig_kr, width='stretch', key='fig_kr')
        else:
            st.info("韓國出口資料載入中。")
    with col_tw_exp:
        fig_tw2 = fill_chart(filt('TW_EXP_YOY'), '🇹🇼 台灣出口 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_tw2:
            st.plotly_chart(fig_tw2, width='stretch', key='fig_tw2')

    # ── NDC 領先指標 ───────────────────────────────────────────────────────────
    st.subheader("🚦 國發會景氣領先指標 (NDC CLI)")
    st.caption("台灣官方複合領先指標，領先景氣轉折約 3~6 個月")
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
            st.plotly_chart(fig_ndc, width='stretch', key='fig_ndc')
        with col_ndc_m:
            lat = ndc.iloc[-1]
            st.metric(f"最新（{lat['date'].strftime('%Y-%m')}）", f"{lat['value']:.2f}")
    else:
        st.info("NDC 領先指標資料暫時無法取得（官方網站可能維護中）。")

    # ── 半導體週期整合概覽 ────────────────────────────────────────────────────
    st.divider()
    st.subheader("💾 半導體週期概覽")
    st.caption("整合台積電月營收、韓國出口、半導體PPI三大指標，掌握半導體景氣循環節奏與拐點位置")

    semi_k1, semi_k2, semi_k3 = st.columns(3)
    with semi_k1:
        tv = get_latest(data.get('TSMC_REVENUE_YOY')); tp = get_prev(data.get('TSMC_REVENUE_YOY'))
        st.metric("🇹🇼 台積電 YoY", f"{tv:.1f}%" if tv is not None else "N/A",
                  delta=f"{tv-tp:+.1f}%" if tv is not None and tp is not None else None)
    with semi_k2:
        kv2 = get_latest(data.get('KR_EXP_YOY')); kp2 = get_prev(data.get('KR_EXP_YOY'))
        st.metric("🇰🇷 韓國出口 YoY", f"{kv2:.1f}%" if kv2 is not None else "N/A",
                  delta=f"{kv2-kp2:+.1f}%" if kv2 is not None and kp2 is not None else None)
    with semi_k3:
        sv_ppi = get_latest(data.get('SEMI_PPI')); sv_ppi_p = get_prev(data.get('SEMI_PPI'))
        st.metric("📟 半導體 PPI", f"{sv_ppi:.2f}" if sv_ppi is not None else "N/A",
                  delta=f"{sv_ppi-sv_ppi_p:+.2f}" if sv_ppi is not None and sv_ppi_p is not None else None)

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        fig_tsmc_s = fill_chart(filt('TSMC_REVENUE_YOY'), '台積電月營收 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_tsmc_s:
            st.plotly_chart(fig_tsmc_s, width='stretch', key='fig_tsmc_s')
        else:
            st.info("台積電資料暫時無法取得。")
    with sc2:
        fig_kr_s = fill_chart(filt('KR_EXP_YOY'), '韓國出口 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_kr_s:
            st.plotly_chart(fig_kr_s, width='stretch', key='fig_kr_s')
        else:
            st.info("韓國出口資料載入中。")
    with sc3:
        sppi_s = filt('SEMI_PPI')
        if sppi_s is not None and not sppi_s.empty:
            fig_sppi_s = go.Figure()
            fig_sppi_s.add_trace(go.Scatter(
                x=sppi_s['date'], y=sppi_s['value'], fill='tozeroy',
                fillcolor='rgba(0,176,240,0.2)',
                line=dict(color='rgb(0,176,240)', width=2),
                name='Semiconductor PPI',
                hovertemplate='%{x|%Y-%m}<br>PPI: %{y:.2f}<extra></extra>'
            ))
            fig_sppi_s.update_layout(
                title='半導體製造業 PPI (Dec 1984=100)', xaxis_title='',
                yaxis_title='PPI 指數', hovermode='x unified',
                margin=dict(t=50, b=20, l=40, r=20), showlegend=False
            )
            st.plotly_chart(fig_sppi_s, width='stretch', key='fig_sppi_s')
        else:
            st.info("半導體 PPI 資料載入中。")


# ════════════════════════════════════════════════════════
# Panel B：獲利與成本感測
# ════════════════════════════════════════════════════════
with tab_b:
    st.divider()
    st.markdown("## 🅱️ 獲利與成本感測 (Cost & Profitability)")

    b1, b2 = st.columns(2)
    with b1:
        tsmc = data.get('TSMC_REVENUE_YOY')
        tv = tsmc.iloc[-1]['value'] if tsmc is not None and not tsmc.empty else None
        tp = tsmc.iloc[-2]['value'] if tsmc is not None and len(tsmc) > 1 else tv
        td = tsmc.iloc[-1]['date'].strftime('%Y-%m') if tsmc is not None and not tsmc.empty else ''
        st.metric(f"🇹🇼 台積電月營收 YoY ({td})", f"{tv:.1f}%" if tv is not None else "N/A",
                  delta=f"{tv-tp:+.1f}%" if tv is not None and tp is not None else None)
    with b2:
        cu = data.get('COPPER_YOY')
        cv = cu.iloc[-1]['value'] if cu is not None and not cu.empty else None
        cp = cu.iloc[-2]['value'] if cu is not None and len(cu) > 1 else cv
        cd = cu.iloc[-1]['date'].strftime('%Y-%m') if cu is not None and not cu.empty else ''
        st.metric(f"🔶 銅價 YoY ({cd})", f"{cv:.1f}%" if cv is not None else "N/A",
                  delta=f"{cv-cp:+.1f}%" if cv is not None and cp is not None else None)
    st.markdown("---")

    # ── OECD CLI ───────────────────────────────────────────────────────────────
    st.subheader("📈 OECD 綜合領先指標 (CLI)")
    st.caption("預測經濟轉折點，基準=100；持續上升並突破 100 代表景氣復甦確認")
    fig_cli = build_figure("五大經濟體 CLI", {
        "🇺🇸 美國": filt('US_CLI'), "🇨🇳 中國": filt('CN_CLI'),
        "🇯🇵 日本": filt('JP_CLI'), "🇪🇺 歐洲G4E": filt('EU_CLI'),
        "🇰🇷 韓國": filt('KR_CLI'),
    }, y_label="指數（基準=100）")
    if fig_cli:
        fig_cli.add_hline(y=100, line_dash="dash", line_color="blue",
                          annotation_text="100 趨勢線", annotation_position="bottom right")
        col_cli, col_cli_m = st.columns([3, 1])
        with col_cli:
            st.plotly_chart(fig_cli, width='stretch', key='fig_cli')
        with col_cli_m:
            st.markdown("**最新讀值**")
            for k, lbl in [('US_CLI','🇺🇸'),('CN_CLI','🇨🇳'),('JP_CLI','🇯🇵'),
                            ('EU_CLI','🇪🇺'),('KR_CLI','🇰🇷')]:
                v = get_latest(data.get(k))
                st.metric(lbl, f"{v:.2f}" if v else "N/A")

    # ── 銅價 YoY + 台積電 YoY ─────────────────────────────────────────────────
    col_cu, col_tsmc = st.columns(2)
    with col_cu:
        st.subheader("🔶 銅價 YoY")
        st.caption("FRED PCOPPUSDM — 工業景氣先行，比 CLI 早 1~2 季觸底/觸頂")
        fig_cu = fill_chart(filt('COPPER_YOY'), '銅價年增率 (YoY %)', '年增率 (%)', ref_y=0)
        if fig_cu:
            st.plotly_chart(fig_cu, width='stretch', key='fig_cu')
        else:
            st.info("銅價資料載入中。")
    with col_tsmc:
        st.subheader("🇹🇼 台積電月營收 YoY")
        st.caption("TWSE MOPS 2330 — 每月約 10 日公布，半導體需求端最直接硬數據")
        fig_tsmc = fill_chart(filt('TSMC_REVENUE_YOY'), '台積電月營收 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_tsmc:
            st.plotly_chart(fig_tsmc, width='stretch', key='fig_tsmc')
        else:
            st.info("台積電資料暫時無法取得。")

    # ── 庫存 + 半導體 PPI ──────────────────────────────────────────────────────
    col_inv, col_ppi = st.columns(2)
    with col_inv:
        st.subheader("📦 美國商業庫存")
        st.caption("FRED BUSINV — 庫存去化末段是製造業重新評價起點")
        fig_inv = build_figure("美國商業庫存", {"🇺🇸 US Inventories": filt('US_BUSINV')}, y_label="百萬美元")
        if fig_inv:
            st.plotly_chart(fig_inv, width='stretch', key='fig_inv')
        else:
            st.warning("庫存資料無法載入。")
    with col_ppi:
        st.subheader("📟 半導體製造業 PPI")
        st.caption("FRED PCU33443344 — 反映半導體成本趨勢；觸底回升是佈局訊號")
        sppi = filt('SEMI_PPI')
        if sppi is not None and not sppi.empty:
            fig_sp = go.Figure()
            fig_sp.add_trace(go.Scatter(x=sppi['date'], y=sppi['value'], fill='tozeroy',
                                         fillcolor='rgba(0,176,240,0.2)',
                                         line=dict(color='rgb(0,176,240)', width=2),
                                         name='Semiconductor PPI',
                                         hovertemplate='%{x|%Y-%m}<br>PPI: %{y:.2f}<extra></extra>'))
            fig_sp.update_layout(title='半導體 PPI (Dec 1984=100)', xaxis_title='',
                                  yaxis_title='PPI 指數', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            st.plotly_chart(fig_sp, width='stretch', key='fig_sp')
        else:
            st.warning("半導體 PPI 無法載入。")

    # ── 10Y 實質利率 + CPI-PPI 剪刀差 ─────────────────────────────────────────
    col_rr, col_sc = st.columns(2)
    with col_rr:
        st.subheader("📐 10Y 實質利率")
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
                                             line=dict(color='rgba(255,165,0,0.5)', width=1, dash='dot'),
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
            st.plotly_chart(fig_rr, width='stretch', key='fig_rr')
            lat_rr = rr.iloc[-1]
            st.metric(f"實質利率（{lat_rr['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_rr['value']:.2f}%", delta_color="inverse")
        else:
            st.warning("實質利率資料無法載入。")
    with col_sc:
        st.subheader("✂️ 核心 CPI–PPI 剪刀差")
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
                                         fillcolor='rgba(38,166,91,0.3)', line=dict(color='rgb(38,166,91)', width=2),
                                         name='剪刀差（正=定價權）'))
            fig_sc.add_trace(go.Scatter(x=sc_n['date'], y=sc_n['value'], fill='tozeroy',
                                         fillcolor='rgba(234,57,67,0.3)', line=dict(color='rgb(234,57,67)', width=2),
                                         name='剪刀差（負=成本壓力）'))
            fig_sc.add_hline(y=0, line_dash='dash', line_color='orange',
                              annotation_text='0%', annotation_position='bottom right')
            fig_sc.update_layout(title='核心 CPI–PPI 剪刀差', xaxis_title='', yaxis_title='百分點差 (%)',
                                  hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
                                  legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
            st.plotly_chart(fig_sc, width='stretch', key='fig_sc')
            lat_sc = sc.iloc[-1]
            st.metric(f"最新剪刀差（{lat_sc['date'].strftime('%Y-%m')}）",
                      f"{lat_sc['value']:+.2f}%")
        else:
            st.warning("CPI/PPI 剪刀差資料無法載入。")

    # ── 中國 PPI YoY + 布蘭特原油 ────────────────────────────────────────────
    col_cn, col_br = st.columns(2)
    with col_cn:
        st.subheader("🇨🇳 中國 PPI YoY")
        st.caption("NBS — 全球製造業通膨/通縮的輸出源，中國 PPI 低迷壓抑全球報價")
        fig_cnp = fill_chart(filt('CN_PPI_YOY'), '中國 PPI YoY (%)', '年增率 (%)',
                              pos_color='rgba(234,57,67,0.3)', neg_color='rgba(38,166,91,0.3)',
                              pos_line='rgb(234,57,67)', neg_line='rgb(38,166,91)', ref_y=0)
        if fig_cnp:
            st.plotly_chart(fig_cnp, width='stretch', key='fig_cnp')
        else:
            st.warning("中國 PPI 資料無法載入。")
    with col_br:
        st.subheader("🛢️ 布蘭特原油")
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
            st.plotly_chart(fig_br, width='stretch', key='fig_br')
            lat_br = br.iloc[-1]; prv_br = br.iloc[-2] if len(br) > 1 else lat_br
            st.metric(f"最新油價（{lat_br['date'].strftime('%Y-%m-%d')}）",
                      f"${lat_br['value']:.2f}",
                      delta=f"{lat_br['value']-prv_br['value']:+.2f}", delta_color="inverse")
        else:
            st.warning("布蘭特原油資料無法載入。")

    # ── 中國信貸脈衝（新增）────────────────────────────────────────────────────
    st.divider()
    st.subheader("🏦 中國信貸脈衝")
    st.caption(
        "M2 YoY 增速的 12 個月差分（加速度）— 正值=信貸擴張加速，領先全球總需求約 9~12 個月；"
        "是最強的總需求領先指標之一。來源：FRED MYAGM2CNM189N"
    )
    cci_df = filt('CHINA_CREDIT_IMPULSE')
    if cci_df is not None and not cci_df.empty:
        col_cci, col_cci_m = st.columns([3, 1])
        with col_cci:
            fig_cci = fill_chart(cci_df, '中國信貸脈衝 (M2 YoY 加速度, 百分點)', '百分點', ref_y=0,
                                 hover_fmt='%{x|%Y-%m}<br>信貸脈衝: %{y:+.2f}pp<extra></extra>')
            if fig_cci:
                st.plotly_chart(fig_cci, width='stretch', key='fig_cci')
        with col_cci_m:
            cci_v = get_latest(cci_df); cci_p = get_prev(cci_df)
            st.metric("最新信貸脈衝",
                      f"{cci_v:+.2f}pp" if cci_v is not None else "N/A",
                      delta=f"{cci_v-cci_p:+.2f}" if cci_v is not None and cci_p is not None else None,
                      help="正值=信貸加速擴張，領先需求復甦 9~12 個月")
            if cci_v is not None:
                if cci_v > 1:
                    st.success("信貸明顯加速 ▲▲")
                elif cci_v > 0:
                    st.success("信貸小幅加速 ▲")
                elif cci_v > -1:
                    st.warning("信貸小幅收縮 ▼")
                else:
                    st.error("信貸明顯收縮 ▼▼")
    else:
        st.info("中國信貸脈衝資料載入中（FRED China M2，可能需要 API Key）。")


# ════════════════════════════════════════════════════════
# Panel C：流動性與風險感測
# ════════════════════════════════════════════════════════
with tab_c:
    st.divider()
    st.markdown("## 🅲 流動性與風險感測 (Liquidity & Risk)")

    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        m1b = data.get('TW_M1B_YOY')
        mv = m1b.iloc[-1]['value'] if m1b is not None and not m1b.empty else None
        mp = m1b.iloc[-2]['value'] if m1b is not None and len(m1b) > 1 else mv
        md = m1b.iloc[-1]['date'].strftime('%Y-%m') if m1b is not None and not m1b.empty else ''
        st.metric(f"🇹🇼 M1B YoY ({md})", f"{mv:.1f}%" if mv is not None else "N/A",
                  delta=f"{mv-mp:+.1f}%" if mv is not None and mp is not None else None)
    with cc2:
        hy = data.get('HY_SPREAD')
        hv = hy.iloc[-1]['value'] if hy is not None and not hy.empty else None
        hp = hy.iloc[-2]['value'] if hy is not None and len(hy) > 1 else hv
        hd = hy.iloc[-1]['date'].strftime('%Y-%m-%d') if hy is not None and not hy.empty else ''
        st.metric(f"💳 HY 利差 ({hd})", f"{hv:.0f} bps" if hv is not None else "N/A",
                  delta=f"{hv-hp:+.0f} bps" if hv is not None and hp is not None else None,
                  delta_color="inverse")
    with cc3:
        twd = data.get('TWD_USD')
        tv2 = twd.iloc[-1]['value'] if twd is not None and not twd.empty else None
        tp2 = twd.iloc[-2]['value'] if twd is not None and len(twd) > 1 else tv2
        td2 = twd.iloc[-1]['date'].strftime('%Y-%m-%d') if twd is not None and not twd.empty else ''
        st.metric(f"🇹🇼 TWD/USD ({td2})", f"{tv2:.3f}" if tv2 is not None else "N/A",
                  delta=f"{tv2-tp2:+.3f}" if tv2 is not None and tp2 is not None else None,
                  delta_color="inverse")
    st.markdown("---")

    # ── VIX ────────────────────────────────────────────────────────────────────
    st.subheader("🚨 CBOE VIX 恐慌指數")
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
                fillcolor='rgba(234,57,67,0.3)' if is_up else 'rgba(38,166,91,0.3)',
                line=dict(color='rgb(234,57,67)' if is_up else 'rgb(38,166,91)', width=2),
                name='VIX', hovertemplate='%{x|%Y-%m-%d}<br>VIX: %{y:.2f}<extra></extra>'))
            for level, label, color in [(20, '正常(<20)', 'rgba(255,255,255,0.3)'),
                                         (30, '警戒(30)', 'rgba(255,200,0,0.4)')]:
                fig_vix.add_hline(y=level, line_dash='dot', line_color=color,
                                   annotation_text=label, annotation_position='bottom right',
                                   annotation_font_color=color)
            fig_vix.update_layout(xaxis_title='', yaxis_title='VIX', hovermode='x unified',
                                   margin=dict(t=10, b=20, l=40, r=20), showlegend=False,
                                   yaxis=dict(range=[max(0, vdf['value'].min()-3), vdf['value'].max()+3]))
            st.plotly_chart(fig_vix, width='stretch', key='fig_vix')
    else:
        st.warning("VIX 資料無法載入。")

    # ── 殖利率曲線 ─────────────────────────────────────────────────────────────
    st.subheader("📉 美國公債殖利率曲線")
    st.caption("倒掛解除轉正後通常是景氣末段或衰退的強烈信號")
    yc_t1, yc_t2 = st.tabs(["📊 殖利率曲線快照", "📈 10Y-2Y & 10Y-3M 利差走勢"])
    with yc_t1:
        mats = ['1M','3M','6M','1Y','2Y','3Y','5Y','7Y','10Y','20Y','30Y']
        snaps = {'Current': 0, '1 Month Ago': 30, '1 Year Ago': 365}
        fig_yc = go.Figure()
        colors = {'Current': 'rgb(31,119,180)', '1 Month Ago': 'rgb(214,39,40)', '1 Year Ago': 'rgba(174,199,232,0.8)'}
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
        st.plotly_chart(fig_yc, width='stretch', key='fig_yc')
    with yc_t2:
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            fig_s1 = fill_chart(filt('T10Y2Y'), '10Y-2Y 利差 (%)', '利差 (%)', ref_y=0)
            if fig_s1:
                st.plotly_chart(fig_s1, width='stretch', key='fig_s1')
            else:
                st.warning("10Y-2Y 資料無法載入。")
        with col_s2:
            fig_s2 = fill_chart(filt('T10Y3M'), '10Y-3M 利差 (%)', '利差 (%)', ref_y=0)
            if fig_s2:
                st.plotly_chart(fig_s2, width='stretch', key='fig_s2')
            else:
                st.warning("10Y-3M 資料無法載入。")

    # ── HY 信用利差 + 台幣匯率 ────────────────────────────────────────────────
    col_hy, col_twd = st.columns(2)
    with col_hy:
        st.subheader("💳 HY 信用利差 (OAS)")
        st.caption("FRED BAMLH0A0HYM2 — 往往在 VIX 飆升前 2~6 週先行擴大")
        hy_df = filt('HY_SPREAD')
        if hy_df is not None and not hy_df.empty:
            fig_hy = go.Figure()
            fig_hy.add_trace(go.Scatter(x=hy_df['date'], y=hy_df['value'], fill='tozeroy',
                                         fillcolor='rgba(200,50,200,0.15)',
                                         line=dict(color='rgb(180,40,180)', width=2), name='HY OAS',
                                         hovertemplate='%{x|%Y-%m-%d}<br>HY: %{y:.0f} bps<extra></extra>'))
            for lvl, lbl, col in [(400,'400 警戒','rgba(255,200,0,0.6)'),
                                    (600,'600 恐慌','rgba(234,57,67,0.7)')]:
                fig_hy.add_hline(y=lvl, line_dash='dot', line_color=col,
                                  annotation_text=lbl, annotation_position='bottom right',
                                  annotation_font_color=col)
            fig_hy.update_layout(title='HY 信用利差 (bps)', xaxis_title='',
                                  yaxis_title='bps', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            st.plotly_chart(fig_hy, width='stretch', key='fig_hy')
            lat_hy = hy_df.iloc[-1]; prv_hy = hy_df.iloc[-2] if len(hy_df) > 1 else lat_hy
            st.metric(f"最新 HY 利差（{lat_hy['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_hy['value']:.0f} bps",
                      delta=f"{lat_hy['value']-prv_hy['value']:+.0f} bps", delta_color="inverse")
        else:
            st.info("HY 利差資料載入中。")
    with col_twd:
        st.subheader("🇹🇼 台幣匯率 TWD/USD")
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
            st.plotly_chart(fig_twd, width='stretch', key='fig_twd')
            lat_t = twd_df.iloc[-1]; prv_t = twd_df.iloc[-2] if len(twd_df) > 1 else lat_t
            st.metric(f"最新（{lat_t['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_t['value']:.3f}",
                      delta=f"{lat_t['value']-prv_t['value']:+.3f}（升值←負值）",
                      delta_color="inverse")
        else:
            st.info("台幣匯率資料載入中。")

    # ── DXY 美元指數（新增）───────────────────────────────────────────────────
    st.divider()
    st.subheader("💵 DXY 美元指數 (貿易加權廣義)")
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
            st.plotly_chart(fig_dxy, width='stretch', key='fig_dxy')
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
    st.subheader("💰 貨幣供給量")
    st.caption("台灣 M1B/M2：中央銀行金融統計月報 ｜ 美國 M1：FRED")
    col_twm, col_usm = st.columns(2)
    with col_twm:
        fig_twm = build_figure("🇹🇼 台灣 M1B / M2 YoY (%)",
                               {"M1B YoY": filt('TW_M1B_YOY'), "M2 YoY": filt('TW_M2_YOY')},
                               y_label="年增率 (%)", is_yoy=True)
        if fig_twm:
            st.plotly_chart(fig_twm, width='stretch', key='fig_twm')
            m1b_d = filt('TW_M1B_YOY'); m2_d = filt('TW_M2_YOY')
            if m1b_d is not None and not m1b_d.empty and m2_d is not None and not m2_d.empty:
                m1v = m1b_d.iloc[-1]['value']; m2v = m2_d.iloc[-1]['value']
                cross = "🟡 黃金交叉（M1B > M2）資金活化" if m1v > m2v else "⚫ 死亡交叉（M1B < M2）資金保守"
                st.caption(f"最新：{cross}（M1B {m1v:.1f}% vs M2 {m2v:.1f}%）")
        else:
            st.warning("台灣 M1B/M2 資料暫時無法取得。")
    with col_usm:
        fig_usm = build_figure("🇺🇸 美國 M1 YoY (%)",
                               {"US M1 YoY": filt('US_M1_YOY')},
                               y_label="年增率 (%)", is_yoy=True)
        if fig_usm:
            st.plotly_chart(fig_usm, width='stretch', key='fig_usm')
        else:
            st.warning("美國 M1 資料無法載入。")


# ════════════════════════════════════════════════════════
# Panel D：股市比對
# ════════════════════════════════════════════════════════
with tab_d:
    st.divider()
    st.markdown("## 📈 股市比對 (Stock Market Comparison)")
    st.markdown(
        "比對台股加權指數（TAIEX）與美股（S&P 500）的年增率走勢，"
        "同步呈現聯準會利率、10Y-3M 利差與製造業新訂單，觀察市場行情與總經的互動關係。"
    )

    dc1, dc2, dc3, dc4 = st.columns(4)
    with dc1:
        sp = data.get('SP500_YOY')
        sv = sp.iloc[-1]['value'] if sp is not None and not sp.empty else None
        sv_p = sp.iloc[-2]['value'] if sp is not None and len(sp) > 1 else sv
        st.metric("🇺🇸 S&P500 YoY", f"{sv:.1f}%" if sv is not None else "N/A",
                  delta=f"{sv-sv_p:+.1f}%" if sv is not None and sv_p is not None else None)
    with dc2:
        tai = data.get('TAIEX_YOY')
        tav = tai.iloc[-1]['value'] if tai is not None and not tai.empty else None
        tav_p = tai.iloc[-2]['value'] if tai is not None and len(tai) > 1 else tav
        st.metric("🇹🇼 TAIEX YoY", f"{tav:.1f}%" if tav is not None else "N/A",
                  delta=f"{tav-tav_p:+.1f}%" if tav is not None and tav_p is not None else None)
    with dc3:
        ff = data.get('FED_FUNDS')
        fv = ff.iloc[-1]['value'] if ff is not None and not ff.empty else None
        fv_p = ff.iloc[-2]['value'] if ff is not None and len(ff) > 1 else fv
        st.metric("🇺🇸 Fed Funds Rate", f"{fv:.2f}%" if fv is not None else "N/A",
                  delta=f"{fv-fv_p:+.2f}%" if fv is not None and fv_p is not None else None,
                  delta_color="inverse")
    with dc4:
        t3m = data.get('T10Y3M')
        t3v = t3m.iloc[-1]['value'] if t3m is not None and not t3m.empty else None
        st.metric("📉 10Y-3M 利差", f"{t3v:.3f}%" if t3v is not None else "N/A",
                  delta_color="normal")
    st.markdown("---")

    # ── S&P500 vs TAIEX YoY ───────────────────────────────────────────────────
    st.subheader("📊 S&P 500 vs TAIEX 年增率比對 (YoY %)")
    st.caption(
        "S&P 500：FRED SP500（月收）｜ TAIEX：Yahoo Finance ^TWII（月收）"
        "　台股與美股年增率的背離往往反映資金輪動或匯率效應，收斂時是重要觀察點。"
    )
    sp_yoy = filt('SP500_YOY'); tai_yoy = filt('TAIEX_YOY')
    if (sp_yoy is not None and not sp_yoy.empty) or (tai_yoy is not None and not tai_yoy.empty):
        fig_cmp = go.Figure()
        if sp_yoy is not None and not sp_yoy.empty:
            fig_cmp.add_trace(go.Scatter(x=sp_yoy['date'], y=sp_yoy['value'],
                                          line=dict(color='rgb(31,119,180)', width=2.5),
                                          name='🇺🇸 S&P500 YoY',
                                          hovertemplate='%{x|%Y-%m}<br>S&P500 YoY: %{y:.1f}%<extra></extra>'))
        if tai_yoy is not None and not tai_yoy.empty:
            fig_cmp.add_trace(go.Scatter(x=tai_yoy['date'], y=tai_yoy['value'],
                                          line=dict(color='rgb(38,166,91)', width=2.5),
                                          name='🇹🇼 TAIEX YoY',
                                          hovertemplate='%{x|%Y-%m}<br>TAIEX YoY: %{y:.1f}%<extra></extra>'))
        fig_cmp.add_hline(y=0, line_dash='dash', line_color='orange',
                           annotation_text='0%', annotation_position='bottom right')
        fig_cmp.update_layout(title='S&P 500 vs TAIEX 年增率 (%)', xaxis_title='',
                               yaxis_title='年增率 (%)', hovermode='x unified',
                               margin=dict(t=50, b=20, l=40, r=20),
                               legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1))
        col_cmp, col_cmp_m = st.columns([3, 1])
        with col_cmp:
            st.plotly_chart(fig_cmp, width='stretch', key='fig_cmp')
        with col_cmp_m:
            st.markdown("**最新讀值**")
            st.metric("🇺🇸 S&P500", f"{sv:.1f}%" if sv is not None else "N/A")
            st.metric("🇹🇼 TAIEX", f"{tav:.1f}%" if tav is not None else "N/A")
            if sv is not None and tav is not None:
                diff = sv - tav
                st.metric("差距", f"{diff:+.1f}pp", help="S&P500 - TAIEX")
    else:
        st.warning("S&P 500 及 TAIEX 資料均無法取得，請確認 FRED API Key 及網路連線。")

    # ── Fed Funds + 10Y-3M ─────────────────────────────────────────────────────
    col_ff, col_t3m = st.columns(2)
    with col_ff:
        st.subheader("🏦 聯準會基準利率 (Fed Funds Rate)")
        st.caption("FRED DFF 日頻月均 — 利率政策是股市估值的最根本驅動力，升息壓縮 P/E，降息擴張 P/E")
        ff_df = filt('FED_FUNDS')
        if ff_df is not None and not ff_df.empty:
            fig_ff = go.Figure()
            fig_ff.add_trace(go.Scatter(x=ff_df['date'], y=ff_df['value'], fill='tozeroy',
                                         fillcolor='rgba(255,100,0,0.15)',
                                         line=dict(color='rgb(255,100,0)', width=2.5),
                                         name='Fed Funds',
                                         hovertemplate='%{x|%Y-%m}<br>Rate: %{y:.2f}%<extra></extra>'))
            fig_ff.update_layout(title='聯準會有效聯邦基金利率 (DFF)', xaxis_title='',
                                  yaxis_title='利率 (%)', hovermode='x unified',
                                  margin=dict(t=50, b=20, l=40, r=20), showlegend=False)
            st.plotly_chart(fig_ff, width='stretch', key='fig_ff')
            lat_ff = ff_df.iloc[-1]
            st.metric(f"最新利率（{lat_ff['date'].strftime('%Y-%m')}）", f"{lat_ff['value']:.2f}%")
        else:
            st.warning("Fed Funds Rate 資料無法載入。")
    with col_t3m:
        st.subheader("📉 10Y-3M 利差（衰退領先指標）")
        st.caption("FRED T10Y3M — 比 10Y-2Y 更早、更敏感的衰退預測指標；倒掛後轉正是強烈衰退訊號")
        t3m_df = filt('T10Y3M')
        if t3m_df is not None and not t3m_df.empty:
            fig_t3m = fill_chart(t3m_df, '10Y-3M 利差 (%)', '利差 (%)', ref_y=0)
            if fig_t3m:
                st.plotly_chart(fig_t3m, width='stretch', key='fig_t3m')
            lat_t3 = t3m_df.iloc[-1]
            st.metric(f"最新 10Y-3M（{lat_t3['date'].strftime('%Y-%m-%d')}）",
                      f"{lat_t3['value']:.3f}%")
        else:
            st.warning("10Y-3M 資料無法載入。")

    # ── 製造業新訂單 YoY ───────────────────────────────────────────────────────
    st.subheader("🏗️ 美國製造業新訂單 YoY (AMTMNO)")
    st.caption("FRED AMTMNO — 製造業需求端前端訊號；新訂單轉正往往領先工業股上漲 1~2 季")
    no_df = filt('US_NEW_ORDERS_YOY')
    col_no, col_no_m = st.columns([3, 1])
    with col_no:
        fig_no = fill_chart(no_df, '美國製造業新訂單 YoY (%)', '年增率 (%)', ref_y=0)
        if fig_no:
            st.plotly_chart(fig_no, width='stretch', key='fig_no')
        else:
            st.warning("製造業新訂單資料無法載入。")
    with col_no_m:
        if no_df is not None and not no_df.empty:
            lat_no = no_df.iloc[-1]
            st.metric(f"最新（{lat_no['date'].strftime('%Y-%m')}）", f"{lat_no['value']:.1f}%")

    # ── 三線疊加 ───────────────────────────────────────────────────────────────
    st.subheader("📈 三線疊加：股市 YoY vs 聯準會利率")
    st.caption("利率走勢與股市 YoY 的相對位置，觀察貨幣政策寬緊對股市的滯後效應")
    sp_f = filt('SP500_YOY'); tai_f = filt('TAIEX_YOY'); ff_f = filt('FED_FUNDS')
    if sp_f is not None and not sp_f.empty:
        fig3 = make_subplots(specs=[[{"secondary_y": True}]])
        if sp_f is not None and not sp_f.empty:
            fig3.add_trace(go.Scatter(x=sp_f['date'], y=sp_f['value'],
                                       line=dict(color='rgb(31,119,180)', width=2),
                                       name='S&P500 YoY %'), secondary_y=False)
        if tai_f is not None and not tai_f.empty:
            fig3.add_trace(go.Scatter(x=tai_f['date'], y=tai_f['value'],
                                       line=dict(color='rgb(38,166,91)', width=2),
                                       name='TAIEX YoY %'), secondary_y=False)
        if ff_f is not None and not ff_f.empty:
            fig3.add_trace(go.Scatter(x=ff_f['date'], y=ff_f['value'],
                                       line=dict(color='rgb(255,100,0)', width=1.5, dash='dot'),
                                       name='Fed Funds Rate %'), secondary_y=True)
        fig3.update_layout(
            title='股市 YoY vs Fed Funds Rate',
            hovermode='x unified',
            margin=dict(t=50, b=20, l=40, r=40),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        fig3.update_yaxes(title_text="年增率 (%)", secondary_y=False)
        fig3.update_yaxes(title_text="利率 (%)", secondary_y=True)
        st.plotly_chart(fig3, width='stretch', key='fig3')
    else:
        st.info("S&P 500 YoY 資料不足，無法顯示三線疊加圖。")

    # ── 亞洲主要指數 YoY 比對 ─────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🌏 亞洲主要指數 YoY 比對")
    st.caption(
        "S&P500 / 台股TAIEX / 日經225 / 韓國KOSPI / 恒生指數 / 滬深300 — Yahoo Finance 月頻。"
        "亞洲指數相對強弱反映區域資金輪動，與 DXY、信貸脈衝呼應觀察效果最佳。"
    )

    _ASIA_SERIES = [
        ('SP500_YOY',  '🇺🇸 S&P500',   'rgb(31,119,180)'),
        ('TAIEX_YOY',  '🇹🇼 TAIEX',    'rgb(38,166,91)'),
        ('NIKKEI_YOY', '🇯🇵 日經225',  'rgb(255,127,14)'),
        ('KOSPI_YOY',  '🇰🇷 KOSPI',    'rgb(148,103,189)'),
        ('HSI_YOY',    '🇭🇰 恒生',     'rgb(214,39,40)'),
        ('CSI300_YOY', '🇨🇳 滬深300',  'rgb(23,190,207)'),
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
            st.plotly_chart(fig_asia, width='stretch', key='fig_asia')
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
    st.markdown("---")
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
        st.plotly_chart(fig_corr, width='stretch', key='fig_corr_heatmap')
    else:
        st.info("相關係數計算需至少兩個有效指數序列。")

    # ── 亞洲 VIX 風險監控 ─────────────────────────────────────────────────────
    st.markdown("---")
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
            line=dict(color='rgb(31,119,180)', width=2),
            name='🇺🇸 VIX',
            hovertemplate='%{x|%Y-%m-%d}<br>VIX: %{y:.1f}<extra></extra>',
        ))
        if _vkos_df is not None and not _vkos_df.empty:
            fig_avix.add_trace(go.Scatter(
                x=_vkos_df['date'], y=_vkos_df['value'],
                line=dict(color='rgb(148,103,189)', width=2),
                name='🇰🇷 VKOSPI',
                hovertemplate='%{x|%Y-%m-%d}<br>VKOSPI: %{y:.1f}<extra></extra>',
            ))
        fig_avix.add_hrect(y0=20, y1=300, fillcolor='rgba(234,57,67,0.05)',
                           line_width=0, annotation_text='恐慌區 >20',
                           annotation_position='top left')
        fig_avix.update_layout(
            title='VIX vs VKOSPI 波動率比對', xaxis_title='', yaxis_title='波動率指數',
            hovermode='x unified', margin=dict(t=50, b=20, l=40, r=20),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        col_avix, col_avix_m = st.columns([3, 1])
        with col_avix:
            st.plotly_chart(fig_avix, width='stretch', key='fig_asia_vix')
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
    st.markdown("---")
    st.subheader("🇹🇼 台灣三大法人買賣超排行")
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
        if st.button("🔄 更新法人資料", key="btn_tw_inst_refresh",
                     help="清除快取並重新從 TWSE 抓取（約 10-30 秒）"):
            load_tw_institutional.clear()
            st.rerun()

    _tw_n_days = 5 if "一週" in _tw_period else 20

    with st.spinner("從台灣證交所 T86 抓取三大法人買賣超資料中…"):
        _tw_data = load_tw_institutional(_tw_n_days)

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
                st.plotly_chart(
                    _tw_bar(_tw_buy, "📈 三大法人 Top 10 買超", "rgba(38,166,91,0.82)"),
                    width='stretch', key="fig_tw_buy10",
                )
        with _tw_bar_col2:
            if not _tw_sell.empty:
                st.plotly_chart(
                    _tw_bar(_tw_sell, "📉 三大法人 Top 10 賣超", "rgba(234,57,67,0.82)"),
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
                )
                return out[["code", "name", "淨買賣超（萬股）", "估算金額（億元）"]].rename(
                    columns={"code": "代號", "name": "名稱"}
                )
            return out[["code", "name", "淨買賣超（萬股）"]].rename(
                columns={"code": "代號", "name": "名稱"}
            )

        _tw_tbl_col1, _tw_tbl_col2 = st.columns(2)
        with _tw_tbl_col1:
            st.markdown("**📈 前 30 大買超明細**")
            if not _tw_buy.empty:
                st.dataframe(_tw_fmt_table(_tw_buy), width='stretch', height=520)
        with _tw_tbl_col2:
            st.markdown("**📉 前 30 大賣超明細**")
            if not _tw_sell.empty:
                st.dataframe(_tw_fmt_table(_tw_sell), width='stretch', height=520)
    else:
        st.warning("無法載入三大法人買賣超資料，請點選「更新法人資料」重試。")



# ════════════════════════════════════════════════════════
# Panel E：全球總經指數 (Global Macro Index)
# ════════════════════════════════════════════════════════
with tab_e:
    st.divider()
    st.markdown("## 🌐 全球總經指數 (Global Macro Index)")
    st.markdown(
        "透過 **20 個指標的二元擴散法** 量化全球景氣方向，"
        "每個指標每月輸出 0（非正向）或 1（正向），加總後映射為紅黃綠三色燈號。"
        "  \n計分門檻：🟢 擴張 ≥ 15　｜　🟡 觀望 10–14　｜　🔴 收縮 ≤ 9"
    )

    with st.spinner("計算景氣歷史時間軸中…"):
        gmi_history = load_gmi_history(fred_api_key)

    display_regime = gmi["regime"]
    display_label  = gmi["regime_label"]
    confirmation_note = ""
    if gmi_history is not None and not gmi_history.empty and "confirmed_regime" in gmi_history.columns:
        latest_hist = gmi_history.iloc[-1]
        display_regime = latest_hist["confirmed_regime"]
        display_label  = latest_hist["confirmed_regime_label"]
        if latest_hist["regime"] != latest_hist["confirmed_regime"]:
            confirmation_note = (
                f"最新 raw regime 為 {REGIME_LABELS[latest_hist['regime']]}，"
                f"但尚未滿足兩期確認，故維持 {display_label}。"
            )

    # ── KPI 燈號列 ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    regime_bg = {
        "green":  "background-color:#0d3b24; border:2px solid #26a65b; border-radius:12px; padding:10px;",
        "yellow": "background-color:#3b2e00; border:2px solid #ffc800; border-radius:12px; padding:10px;",
        "red":    "background-color:#3b0d10; border:2px solid #ea3943; border-radius:12px; padding:10px;",
        "unknown":"background-color:#333; border:2px solid #888; border-radius:12px; padding:10px;",
    }
    style = regime_bg.get(display_regime, regime_bg["unknown"])
    with k1:
        st.markdown(f'<div style="{style}"><h3 style="margin:0;text-align:center">{display_label}</h3><p style="margin:0;text-align:center;font-size:0.9em">景氣燈號（兩期確認）</p></div>', unsafe_allow_html=True)
    with k2:
        st.metric("📊 GMI 分數", f"{gmi['score']} / 20")
    with k3:
        st.metric("📈 擴散比例", f"{gmi['diffusion']:.1f}%")
    with k4:
        conf_label = "🔵 正常" if gmi["confidence"] == "normal" else "🟠 低信心"
        st.metric("信心等級", conf_label, help=f"有效指標數：{gmi['valid_count']}/20")
    with k5:
        st.metric("資料基準月", gmi["as_of"])

    if confirmation_note:
        st.caption(f"Anti-whipsaw：{confirmation_note}")

    # ── 歷史 Timeline（雙軌：GMI Score + S&P500 YoY）────────────────────────
    if gmi_history is not None and not gmi_history.empty:
        st.subheader("🕰️ 歷史 Regime Timeline")
        st.caption("上軌：10 年月頻 GMI（兩期確認；彩色點為確認燈號）｜ 下軌：S&P500 YoY % 對照，觀察領先/滯後關係")

        fig_hist = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.65, 0.35],
            subplot_titles=("Global Macro Index Score (0–20)", "S&P 500 YoY %"),
        )

        # 上軌：背景色帶
        fig_hist.add_hrect(y0=0,  y1=9,  fillcolor="rgba(234,57,67,0.10)",  line_width=0, row=1, col=1)
        fig_hist.add_hrect(y0=10, y1=14, fillcolor="rgba(255,200,0,0.10)",  line_width=0, row=1, col=1)
        fig_hist.add_hrect(y0=15, y1=20, fillcolor="rgba(38,166,91,0.10)",  line_width=0, row=1, col=1)

        # 上軌：GMI 折線
        fig_hist.add_trace(go.Scatter(
            x=gmi_history["date"],
            y=gmi_history["score"],
            mode="lines+markers",
            line=dict(color="rgba(210,220,230,0.9)", width=2),
            marker=dict(
                size=7,
                color=[get_regime_color(r) for r in gmi_history["confirmed_regime"]],
            ),
            customdata=gmi_history[["diffusion", "regime", "confirmed_regime", "valid_count"]],
            hovertemplate=(
                "%{x|%Y-%m}<br>Score: %{y}/20"
                "<br>Diffusion: %{customdata[0]:.1f}%"
                "<br>Raw: %{customdata[1]}"
                "<br>Confirmed: %{customdata[2]}"
                "<br>Valid signals: %{customdata[3]}<extra></extra>"
            ),
            name="GMI Score",
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
                    x=ev_date, y=20.3, text=ev_label,
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
                    fillcolor='rgba(38,166,91,0.25)',
                    line=dict(color='rgb(38,166,91)', width=1.5),
                    name='S&P500 YoY+ %',
                    hovertemplate='%{x|%Y-%m}<br>S&P500 YoY: %{y:.1f}%<extra></extra>',
                ), row=2, col=1)
                fig_hist.add_trace(go.Scatter(
                    x=sp_neg['date'], y=sp_neg['value'], fill='tozeroy',
                    fillcolor='rgba(234,57,67,0.25)',
                    line=dict(color='rgb(234,57,67)', width=1.5),
                    name='S&P500 YoY- %',
                    hovertemplate='%{x|%Y-%m}<br>S&P500 YoY: %{y:.1f}%<extra></extra>',
                ), row=2, col=1)
                fig_hist.add_hline(y=0, line_dash='dash',
                                   line_color='rgba(255,165,0,0.5)', row=2, col=1)

        fig_hist.update_layout(
            title="Global Macro Index Timeline + S&P500 YoY",
            hovermode="x unified",
            height=520,
            margin=dict(t=80, b=20, l=40, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig_hist.update_yaxes(range=[0, 20.5], tickmode="linear", dtick=2,
                               title_text="Score", row=1, col=1)
        fig_hist.update_yaxes(title_text="YoY %", row=2, col=1)
        st.plotly_chart(fig_hist, width='stretch', key='fig_hist')

    st.markdown("---")

    # ── 20 指標熱力圖 ──────────────────────────────────────────────────────────
    st.subheader("🗺️ 20 指標方向明細")
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
                color = "🟢" if sig["score"] == 1 else "🔴"
                st.markdown(
                    f"<div style='border:1px solid #444; border-radius:8px; padding:8px; text-align:center;'>"
                    f"<div style='font-size:1.5em'>{color}</div>"
                    f"<div style='font-size:0.75em; font-weight:bold'>{sig['name']}</div>"
                    f"<div style='font-size:0.7em; color:#aaa'>{sig['raw']}</div>"
                    f"<div style='font-size:0.65em; color:#888'>{sig['rule']}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.markdown("---")

    # ── 驅動/拖累因子 ──────────────────────────────────────────────────────────
    col_drv, col_drag = st.columns(2)
    with col_drv:
        st.subheader("🚀 正向驅動因子（前 3 名）")
        if gmi["top_drivers"]:
            for d in gmi["top_drivers"]:
                st.success(f"**#{d['id']} {d['name']}** — {d['raw']} | 條件：{d['rule']}")
        else:
            st.info("目前無正向訊號")
    with col_drag:
        st.subheader("⚠️ 拖累因子（前 3 名）")
        if gmi["top_drags"]:
            for d in gmi["top_drags"]:
                st.error(f"**#{d['id']} {d['name']}** — {d['raw']} | 條件：{d['rule']}")
        else:
            st.success("目前無拖累訊號，所有指標均正向")

    st.markdown("---")

    # ── 群組分數長條圖 ─────────────────────────────────────────────────────────
    st.subheader("📊 群組分數分佈")
    grp_df = pd.DataFrame([
        {"group": k, "score": v["capped"], "raw": v["raw"]}
        for k, v in gmi["group_scores"].items()
    ])
    fig_grp = go.Figure()
    fig_grp.add_trace(go.Bar(
        x=[GROUP_NAMES[g] for g in grp_df["group"]],
        y=grp_df["score"],
        marker_color=[get_regime_color("green") if s == 5 else
                      get_regime_color("yellow") if s >= 3 else
                      get_regime_color("red") for s in grp_df["score"]],
        text=[f"{s}/5" for s in grp_df["score"]],
        textposition="outside",
    ))
    fig_grp.update_layout(
        title="各群組計入分數（滿分各 5 分）",
        xaxis_title="", yaxis_title="分數", yaxis=dict(range=[0, 6]),
        margin=dict(t=50, b=20, l=40, r=20), showlegend=False,
        hovermode="x",
    )
    st.plotly_chart(fig_grp, width='stretch', key='fig_grp')

    st.markdown("---")

    # ── 美股內部輪動 ────────────────────────────────────────────────────────────
    st.subheader("🔄 內部輪動指數")
    st.caption("景氣循環 (XLY+XLI+XLB+XLF) vs 防禦 (XLP+XLU+XLV+XLRE) 等權相對強弱")
    rot_df = filt("SECTOR_ROTATION")
    if rot_df is not None and not rot_df.empty:
        fig_rot = fill_chart(
            rot_df, "循環/防禦相對強弱指數", "比率",
            ref_y=0,
            hover_fmt="%{x|%Y-%m}<br>輪動比率: %{y:.3f}<extra></extra>",
        )
        if fig_rot:
            st.plotly_chart(fig_rot, width='stretch', key='fig_rot')
        latest_rot = rot_df.iloc[-1]["value"]
        rot_status = "Risk-On 🟢 景氣循環領先" if latest_rot > 0 else "Risk-Off 🔴 防禦領先"
        st.metric("最新輪動狀態", rot_status, f"{latest_rot:+.3f}")
    else:
        st.info("輪動指數資料抓取中（Yahoo Finance ETF 月頻）")

    st.markdown("---")

    # ── 方法說明 ───────────────────────────────────────────────────────────────
    with st.expander("📖 方法說明與資料限制"):
        st.markdown("""
**計分方法**
- 20 個指標各輸出 0（負向）或 1（正向），分為 A/B/C/D 四組各 5 個。
- 每組最高計入 5 分（群組上限），避免同質指標堆疊。
- 需連續 2 期達到門檻才切換燈號（防假突破）。
- 有效指標數 < 16 時，標示「低信心」。

**燈號門檻**
| 燈號 | 條件 | 擴散比例 |
|------|------|---------|
| 🟢 擴張 | Score ≥ 15 | ≥ 75% |
| 🟡 觀望 | Score 10–14 | 50%–70% |
| 🔴 收縮 | Score ≤ 9 | ≤ 45% |

**內部輪動限制**
- 以景氣循環 ETF（XLY/XLI/XLB/XLF）vs 防禦 ETF（XLP/XLU/XLV/XLRE）等權月收相對強弱計算。
- Yahoo Finance 月頻資料可能有 1–3 個交易日延遲。
""")


# ════════════════════════════════════════════════════════
# Tab F：台股資金輪動
# ════════════════════════════════════════════════════════
with tab_f:
    st.markdown("## F 台股資金輪動")
    st.caption(
        "追蹤 19 個 TWSE 官方類股指數的動能、資金流向與退潮訊號。"
        "數據來源：台灣證交所 MI_INDEX（類股指數），每日收盤後更新。"
    )

    with st.expander("📋 TWSE 19 類股速查表", expanded=False):
        from fetchers.taiwan_sector import SECTOR_NAMES as _SN
        _ref_df = pd.DataFrame([
            {"代碼": code, "類股名稱": name, "產業大類": _SECTOR_GROUP.get(name, "其他")}
            for code, name in sorted(_SN.items())
        ])
        st.dataframe(_ref_df, hide_index=True, width='stretch')

    with st.spinner("載入台股類股資料（首次約 30–90 秒）…"):
        tw_sector = load_tw_sector_data()

    sector_df   = tw_sector.get("sector_df",  pd.DataFrame())
    turnover_df = tw_sector.get("turnover_df", pd.DataFrame())
    instit_df   = tw_sector.get("instit_df",  pd.DataFrame())
    momentum_df = tw_sector.get("momentum_df", pd.DataFrame())
    signals     = tw_sector.get("signals", {})

    if sector_df.empty:
        st.warning("台股類股資料暫時無法取得，請稍後重試。")
        st.info("確認 TWSE MI_INDEX20 API 可連線後重新整理頁面。")
    else:
        # ── 輪動訊號橫幅 ──────────────────────────────────────────────────────
        if signals:
            col_hot, col_cool, col_warm, col_cold = st.columns(4)
            _sig_style = "border-radius:8px; padding:8px 10px; margin:2px 0;"
            with col_hot:
                st.markdown(
                    f"<div style='background:#1a3a1a;{_sig_style}'>"
                    f"<b>🟢 強勢類股</b><br>" +
                    "<br>".join(signals.get("hot", ["—"])) +
                    "</div>", unsafe_allow_html=True
                )
            with col_cool:
                st.markdown(
                    f"<div style='background:#3a2a0a;{_sig_style}'>"
                    f"<b>🟡 退潮中</b><br>" +
                    "<br>".join(signals.get("cooling", ["—"])) +
                    "</div>", unsafe_allow_html=True
                )
            with col_warm:
                st.markdown(
                    f"<div style='background:#0a2a3a;{_sig_style}'>"
                    f"<b>🔵 升溫中（候選）</b><br>" +
                    "<br>".join(signals.get("warming", ["—"])) +
                    "</div>", unsafe_allow_html=True
                )
            with col_cold:
                st.markdown(
                    f"<div style='background:#2a0a0a;{_sig_style}'>"
                    f"<b>🔴 弱勢類股</b><br>" +
                    "<br>".join(signals.get("cold", ["—"])) +
                    "</div>", unsafe_allow_html=True
                )
            st.markdown("")

        # ── 三子頁 ───────────────────────────────────────────────────────────
        f_snap, f_heat, f_flow, f_13f = st.tabs([
            "📊 輪動快照（四象限）",
            "🌡️ 動能熱力圖",
            "💹 資金流向",
            "🏦 13F 法人持倉",
        ])

        # ──── F-1：輪動快照（四象限散點圖）────────────────────────────────────
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
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,15,20,1)",
                    font_color="#ddd", margin=dict(l=40, r=20, t=20, b=40),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_snap, width='stretch', key="fig_f_snap")

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
                st.plotly_chart(fig_heat, width='stretch', key="fig_f_heat")
            else:
                st.info("熱力圖需要 sector_df 包含 chg_pct 欄位，目前資料尚未就緒。")

            # ── 三大法人整體市場買賣超 ──────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 🏛️ 三大法人整體市場淨買超（NT$ 千元）")
            st.caption("TWSE BFI82U：外資、投信、自營商整體市場買賣差額。正值＝淨買，負值＝淨賣。")
            if not instit_df.empty and "institution" in instit_df.columns:
                # Most recent trading day
                _latest_instit = (
                    instit_df[instit_df["date"] == instit_df["date"].max()]
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
                st.info(
                    "法人買超資料尚未就緒。\n\n"
                    "首次啟動請執行：`docker exec macro-dashboard python scheduler.py --run-now`\n\n"
                    "每日 02:30（台北時間）自動更新。"
                )

        # ──── F-3：成交值比重趨勢 ─────────────────────────────────────────────
        with f_flow:
            st.markdown("#### 各類股成交值佔大盤比重（近 60 交易日）")
            st.caption("可識別資金從哪個類股流出、流入哪個類股。")

            if not turnover_df.empty:
                # Top 8 類股（其餘合併為「其他」）
                _top_sectors = (
                    turnover_df.groupby("sector_name")["turnover_億"]
                    .sum()
                    .nlargest(8)
                    .index.tolist()
                )
                _flow = turnover_df.copy()
                _flow["sector_name"] = _flow["sector_name"].apply(
                    lambda s: s if s in _top_sectors else "其他"
                )
                _flow_agg = (
                    _flow.groupby(["date", "sector_name"])["turnover_share_pct"]
                    .sum()
                    .reset_index()
                )

                fig_flow = px.area(
                    _flow_agg,
                    x="date",
                    y="turnover_share_pct",
                    color="sector_name",
                    labels={
                        "date": "日期",
                        "turnover_share_pct": "成交值佔比 (%)",
                        "sector_name": "類股",
                    },
                    height=420,
                )
                fig_flow.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,15,20,1)",
                    font_color="#ddd",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    margin=dict(l=40, r=20, t=30, b=40),
                    hovermode="x unified",
                )
                st.plotly_chart(fig_flow, width='stretch', key="fig_f_flow")

                # 最新一日排行
                _latest_date = turnover_df["date"].max()
                _latest = (
                    turnover_df[turnover_df["date"] == _latest_date]
                    .sort_values("turnover_share_pct", ascending=False)
                    [["sector_name", "turnover_億", "turnover_share_pct"]]
                    .rename(columns={
                        "sector_name": "類股",
                        "turnover_億": "成交額(億)",
                        "turnover_share_pct": "佔比(%)",
                    })
                    .reset_index(drop=True)
                )
                st.markdown(f"**最新交易日（{_latest_date.strftime('%Y-%m-%d')}）類股成交排行**")
                st.dataframe(_latest, width='stretch', height=360)
            else:
                st.info(
                    "成交值資料載入中，請稍後重整頁面。\n\n"
                    "首次啟動請執行：`docker exec macro-dashboard python scheduler.py --run-now`"
                )

        # ──── F-4：13F 法人持倉 ───────────────────────────────────────────────
        with f_13f:
            st.subheader("🏦 13F 機構持倉 — Smart Money 動態")
            st.caption(
                "整合 SEC EDGAR 13F-HR / 13F-HR/A：Berkshire、Citadel、Two Sigma 等 20 大機構。"
                "以 CUSIP 為主鍵去重；13F-HR/A 修訂版優先。三個維度排名：股數 / 市值 / 機構共識。"
                "首次載入約 20-30 秒，之後 24 小時快取。"
            )

            # 13F 代理指標（ETF 量能差）
            st.markdown("#### 📈 循環 vs 防禦量能差（代理指標）")
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
                    st.plotly_chart(fig_13f_proxy, width='stretch', key='fig_13f_proxy')
                latest_13f_p = tf_df.iloc[-1]["value"]
                label_13f_p = "機構偏向景氣循環 🟢" if latest_13f_p > 0 else "機構偏向防禦 🔴"
                st.metric("最新 13F 偏好", label_13f_p, f"{latest_13f_p:+.3f}")
            else:
                st.info("13F 代理指標資料抓取中（Yahoo Finance ETF 量能）")

            st.markdown("---")

            # SEC EDGAR 13F Smart Money
            _13f_hd, _13f_bt = st.columns([3, 1])
            with _13f_hd:
                st.markdown(
                    "📌 **方法**：CUSIP 主鍵去重 → 各機構當季 vs 上季持股差值 → 20 大機構加總。"
                    "僅計 SOLE / DFND 自主裁量持股，避免選擇性持股雙重計算。"
                )
            with _13f_bt:
                if st.button("🔄 更新 13F", key='btn_13f_refresh',
                             help="清除快取並重新抓取 EDGAR（約 20-30 秒）"):
                    load_13f_data.clear()
                    st.rerun()

            with st.spinner("從 SEC EDGAR 抓取 13F 持倉中（每日快取 24h）…"):
                _smart = load_13f_data()

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
                st.metric("📅 最新季度", _quarter)
            with _mc2:
                st.metric("🏛️ 機構覆蓋", f"{_fund_count} / 20")
            with _mc3:
                _tracked = len(set(n for n, *_ in _tbs) | set(n for n, *_ in _tss))
                st.metric("📋 追蹤標的", f"{_tracked} 檔")
            with _mc4:
                st.metric("🤝 共識持股", f"{len(_cvb) + len(_cvs)} 檔")

            if _tbs or _tss or _tbv or _tsv or _cvb or _cvs:
                _sub_rank, _sub_s, _sub_v, _sub_c = st.tabs([
                    "🏆 分類排名總覽", "📊 股數排名", "💵 市值排名（USD）", "🤝 機構共識"
                ])

                with _sub_rank:
                    st.markdown("### 🏆 分類排名總覽")
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

                    st.markdown("---")

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
                        st.plotly_chart(fig_rank, width='stretch', key='fig_rank_main')

                    st.markdown("#### 📊 板塊資金流向匯總")
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
                        st.plotly_chart(fig_sector, width='stretch', key='fig_rank_sector')

                    st.markdown("#### 📋 持倉明細（可排序）")
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
                                marker_color='rgba(38,166,91,0.85)',
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
                            st.plotly_chart(fig_s_buy, width='stretch', key='fig_13f_s_buy')
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
                                marker_color='rgba(234,57,67,0.85)',
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
                            st.plotly_chart(fig_s_sell, width='stretch', key='fig_13f_s_sell')
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
                                marker_color='rgba(38,166,91,0.85)',
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
                            st.plotly_chart(fig_v_buy, width='stretch', key='fig_13f_v_buy')
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
                                marker_color='rgba(234,57,67,0.85)',
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
                            st.plotly_chart(fig_v_sell, width='stretch', key='fig_13f_v_sell')
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
                            st.plotly_chart(fig_cv_buy, width='stretch', key='fig_13f_cv_buy')
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
                            st.plotly_chart(fig_cv_sell, width='stretch', key='fig_13f_cv_sell')
                        else:
                            st.info("無共識減持（需 ≥2 家機構）。")
            else:
                st.error(
                    "⚠️ **13F 資料無法取得** — 所有機構持倉均回傳空值。\n\n"
                    "常見原因：\n"
                    "1. 網路無法連線至 SEC EDGAR（`data.sec.gov` / `www.sec.gov`）\n"
                    "2. EDGAR 限流（429）— 請按「更新 13F」鈕稍後重試\n"
                    "3. 快取存有舊的空結果 — 請按右上角「更新 13F」清除快取"
                )
                _diag_col, _link_col = st.columns([1, 2])
                with _diag_col:
                    if st.button("🔍 診斷 EDGAR 連線", key='btn_edgar_diag'):
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

            with st.expander("💡 13F 方法論與進階應用"):
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

        st.markdown("---")
        with st.expander("📖 台股類股指標說明"):
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
# 頁尾
# ════════════════════════════════════════════════════════
st.markdown("---")
st.caption(
    "資料來源：ISM · CIER · NBS · 日本內閣府 · Eurostat · FRED · DBnomics · "
    "財政部 · 央行 · Yahoo Finance · 證交所 MI_INDEX20 ｜ "
    "每小時自動刷新快取，圖表可互動縮放。"
)
