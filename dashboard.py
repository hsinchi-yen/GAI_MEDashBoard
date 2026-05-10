import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import data_fetcher as dfetch
from macro_index import build_macro_index_history, compute_macro_index, get_regime_color, REGIME_LABELS

# MUST BE FIRST
st.set_page_config(page_title="全球經濟指標儀表板", layout="wide", page_icon="📊")

CACHE_TTL = 3600  # 1 hour


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
    data['FED_FUNDS']         = dfetch.fetch_fed_funds_rate(fred_key)
    data['T10Y3M']            = dfetch.fetch_t10y3m(fred_key)
    data['US_NEW_ORDERS_YOY'] = dfetch.fetch_us_new_orders_yoy(fred_key)

    # ── Panel E：全球總經指數 ─────────────────────────────────────────────────
    etf_bulk = dfetch.fetch_etf_bulk(years_back=12)
    data['SECTOR_ROTATION']   = dfetch.fetch_sector_rotation(etf_bulk=etf_bulk, years_back=11)
    data['THIRTEENF_NET_ADD'] = dfetch.fetch_13f_proxy(etf_bulk=etf_bulk, api_key=fred_key, years_back=11)

    return data


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_gmi_history(fred_key: str) -> pd.DataFrame:
    """單獨快取的 GMI 歷史時間軸（10 年月頻重算）。"""
    data = load_data(fred_key)
    return build_macro_index_history(data, lookback_years=10)


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
with st.sidebar:
    st.header("⚙️ 設定中心")
    fred_api_key = st.text_input("FRED API Key", value="13bf3245b1fef176250249752ed063ef",
                                  type="password", help="已內建預設金鑰，可自行替換。")
    st.markdown("---")
    st.subheader("🗓️ 圖表時間區間")
    range_years = st.selectbox("選擇呈現範圍", list(range(1, 16)), index=2,
                                format_func=lambda x: f"近 {x} 年")
    st.markdown("---")

st.title("📊 全球經濟指標動態看板")
st.markdown(
    "資料來源：ISM · CIER · NBS · 內閣府 · Eurostat · FRED · DBnomics · 財政部 · 央行 · Yahoo Finance　｜　**自動快取 1 小時更新**"
)

with st.spinner('背景提取最新指標數據中，請稍候…'):
    data = load_data(fred_api_key)

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
    f'&nbsp;&nbsp;<span style="font-size:0.75em; opacity:0.55; float:right;">1h 快取</span>'
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
tab_ov, tab_a, tab_b, tab_c, tab_d, tab_e = st.tabs([
    "📋 Overview", "A 需求感測", "B 成本/獲利", "C 流動性/風險", "D 股市比對", "E 總經指數"
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

    # ── 內部輪動 + 13F ─────────────────────────────────────────────────────────
    col_rot, col_13f = st.columns(2)
    with col_rot:
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

    with col_13f:
        st.subheader("🏦 13F 持股偏好指數")
        st.caption(
            "循環 vs 防禦 ETF 成交量加速度差值（代理版）\n"
            "正值 = 機構資金偏向景氣循環；負值 = 偏向防禦\n"
            "⚠️ 此為代理指標，完整 SEC EDGAR 13F 版本列為 Phase 2"
        )
        tf_df = filt("THIRTEENF_NET_ADD")
        if tf_df is not None and not tf_df.empty:
            fig_13f = fill_chart(
                tf_df, "13F 代理指標（循環/防禦量能差）", "比率差",
                ref_y=0,
                hover_fmt="%{x|%Y-%m}<br>差值: %{y:.3f}<extra></extra>",
            )
            if fig_13f:
                st.plotly_chart(fig_13f, width='stretch', key='fig_13f')
            latest_13f = tf_df.iloc[-1]["value"]
            label_13f = "機構偏向景氣循環 🟢" if latest_13f > 0 else "機構偏向防禦 🔴"
            st.metric("最新 13F 偏好", label_13f, f"{latest_13f:+.3f}")
        else:
            st.info("13F 代理指標資料抓取中（Yahoo Finance ETF 量能）")

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

**13F 限制**
- SEC 13F 揭露時間：季末後 45 天，有時滯。
- 本版本使用 ETF 量能加速度作為代理，方向性約 0.6–0.8 相關。
- Phase 2 計劃接入 SEC EDGAR FULL-INDEX，提升準確性。

**內部輪動限制**
- 以景氣循環 ETF（XLY/XLI/XLB/XLF）vs 防禦 ETF（XLP/XLU/XLV/XLRE）等權月收相對強弱計算。
- Yahoo Finance 月頻資料可能有 1–3 個交易日延遲。
""")


# ════════════════════════════════════════════════════════
# 頁尾
# ════════════════════════════════════════════════════════
st.markdown("---")
st.caption(
    "資料來源：ISM · CIER · NBS · 日本內閣府 · Eurostat · FRED · DBnomics · "
    "財政部 · 央行 · Yahoo Finance ｜ "
    "每小時自動刷新快取，圖表可互動縮放。"
)
