"""The investor-facing pages: verdict, trend radar and guide.

Each page answers one question. Detail charts stay on the analysis pages.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.indicators import THEMES
from analytics.market_view import LOOKBACK_MONTHS, build_brief, regime_evidence, theme_brief
from ui import charts, components as c

_SIGNAL_TEXT = {"bullish": "▲ 偏多", "bearish": "▼ 偏空", "neutral": "● 持平"}
_INFLECTION_TEXT = {"turning_up": "轉強", "turning_down": "轉弱", "none": ""}

RADAR_FILTERS = ["全部", "偏多", "偏空", "轉折中", "資料過期"]


def _html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def render_verdict(view: dict, history: pd.DataFrame, show_chart, load_evidence) -> None:
    """Conclusion → what to do → why → what would change it → history."""
    _html(c.verdict_hero(view))
    _html(c.pillar_cards(view["pillars"]))

    _html(c.section("怎麼做", "依目前多空判讀與成長／通膨位置的對應框架"))
    _html('<div class="gm-grid">' + c.playbook_card(view["playbook"]) + c.clock_card(view["clock"])
          + c.alerts_card(view["alerts"], view["stale_count"])
          + c.tw_warning_card(view.get("tw_warning") or {}) + "</div>")

    _html(c.section("為什麼", "每項皆為可驗證的規則，並非主觀判斷"))
    _html('<div class="gm-grid">'
          + c.signal_card("多方論據", view["bull_case"], "bullish", "目前沒有指標偏多。")
          + c.signal_card("空方論據", view["bear_case"], "bearish", "目前沒有指標偏空。")
          + "</div>")

    _html(c.section("什麼會改變判斷"))
    _html('<div class="gm-grid">' + c.flip_meter(view) + c.changes_card(view["changes"]) + "</div>")

    left, right = st.columns(2)
    with left:
        fig = charts.diffusion_chart(history)
        if fig:
            show_chart(fig, key="fig_verdict_diffusion")
    with right:
        fig = charts.clock_chart(view["clock"])
        if fig:
            show_chart(fig, key="fig_verdict_clock")

    if view["missing"]:
        names = "、".join(s["name"] for s in view["missing"])
        st.caption(f"目前無資料、已排除於計分：{names}")

    st.download_button("下載本期簡報 (Markdown)", data=build_brief(view),
                       file_name=f"macro-brief-{view['as_of']}.md", mime="text/markdown",
                       key="btn_download_brief")

    _render_evidence(view, load_evidence)
    _html(c.disclaimer())


def _render_evidence(view: dict, load_evidence) -> None:
    """Last on the page: it is the only block that may need the network."""
    _html(c.section("歷史上相同燈號之後",
                    "訊號公布後才進場（延遲 1 個月）；重疊視窗已折算為獨立樣本"))
    stats = load_evidence()
    tables = [
        c.evidence_table(regime_evidence(stats, view["regime"], market=market), label)
        for market, label in (("TWII", "台灣加權指數"), ("SPX", "S&P 500"))
    ]
    tables = [t for t in tables if t]
    if tables:
        _html('<div class="gm-grid">' + "".join(tables) + "</div>")
        st.caption("⚠ 表示獨立樣本少於 8，僅供參考。")
    else:
        st.caption("目前沒有足夠的歷史樣本，或指數資料尚未載入。")


def radar_table(radar: pd.DataFrame) -> pd.DataFrame:
    """Shape the radar for display; the sparkline column stays a list of floats."""
    return pd.DataFrame({
        "指標":   radar["name"],
        "類別":   radar["theme_label"],
        "性質":   radar["role"],
        "最新":   radar["latest_text"],
        "3M 變化": radar["change_3m_text"],
        "5Y 位階": radar["percentile"].round(0),
        "階段":   radar["stage"],
        "訊號":   radar["signal"].map(_SIGNAL_TEXT),
        "轉折":   radar["inflection"].map(_INFLECTION_TEXT),
        "近 24 月": radar["spark"],
        "更新":   pd.to_datetime(radar["latest_date"]).dt.strftime("%Y-%m-%d"),
    })


def filter_radar(radar: pd.DataFrame, choice: str, theme: str | None) -> pd.DataFrame:
    out = radar if theme is None else radar[radar["theme"] == theme]
    if choice == "偏多":
        return out[out["signal"] == "bullish"]
    if choice == "偏空":
        return out[out["signal"] == "bearish"]
    if choice == "轉折中":
        return out[out["inflection"] != "none"]
    if choice == "資料過期":
        return out[out["stale"]]
    return out


@st.fragment
def _radar_explorer(radar: pd.DataFrame) -> None:
    """A fragment: filtering reruns this block only, never the whole page."""
    left, right = st.columns([2, 3])
    with left:
        choice = st.segmented_control("篩選訊號", RADAR_FILTERS, default="全部",
                                      key="radar_filter", required=True)
    with right:
        theme_key = st.selectbox("類別", [None, *THEMES], key="radar_theme",
                                 format_func=lambda k: "全部類別" if k is None else THEMES[k])
    rows = filter_radar(radar, choice or "全部", theme_key)
    if rows.empty:
        st.info("沒有符合條件的指標。")
        return
    st.dataframe(
        radar_table(rows), hide_index=True, width="stretch",
        height=min(620, 38 * len(rows) + 40),
        column_config={
            "5Y 位階": st.column_config.ProgressColumn(
                "5Y 位階", min_value=0, max_value=100, format="%.0f%%",
                help="最新值在近 5 年的百分位"),
            "近 24 月": st.column_config.LineChartColumn("近 24 月", width="small"),
        },
    )
    st.caption(f"顯示 {len(rows)} 項。訊號已依指標特性調整方向：例如 VIX 下降記為偏多。")


def render_radar(view: dict) -> None:
    radar = view["radar"]
    if radar.empty:
        st.info("目前沒有足夠歷史的指標。請確認排程器已執行。")
        return

    b = view["breadth"]
    _html(c.theme_brief_bar({
        "tone": "bullish" if b["net_pct"] > 15 else "bearish" if b["net_pct"] < -15 else "neutral",
        "summary": (f"{b['total']} 項指標中，{b['bullish']} 項趨勢向好、{b['bearish']} 項轉差、"
                    f"{b['neutral']} 項持平；淨偏多 {b['net_pct']:+.0f}%。"),
    }))
    _html(c.breadth_cards([theme_brief(view, key) for key in THEMES]))
    _radar_explorer(radar)
    with st.expander("欄位說明"):
        st.markdown(f"""
- **階段**：結合位階與方向。強勢（有利且改善）、回升（不利但改善）、轉弱（有利但惡化）、弱勢（不利且惡化）、盤整（變動在正常波動內）。
- **訊號**：近 {LOOKBACK_MONTHS} 個月的方向，與該指標「多少才算好」比較後的結果。波動在常態範圍內記為持平。
- **轉折**：近 {LOOKBACK_MONTHS} 個月的走勢與前 {LOOKBACK_MONTHS} 個月相反，常是最早的變化訊號。
- **5Y 位階**：最新值在近 5 年的百分位。對 VIX 等指標而言，高位階代表風險偏高。
""")


GUIDE = """
### 三步驟讀懂這個儀表板

1. **看結論**：「今日判讀」頂部的多空結論，由「燈號位階」加上「動能方向」決定，五段式由強烈偏空到強烈偏多。
2. **看原因**：多方與空方論據列出每項指標與規則；四大支柱顯示多空落在哪個面向。
3. **看變化**：「距離燈號翻轉」與「近 3 個月變化」告訴你什麼會改變判斷，比單一讀值更重要。

### 多空判讀怎麼算

| 燈號＼動能 | 改善（3M ≥ +10pp） | 持平 | 轉弱（3M ≤ −10pp） |
|---|---|---|---|
| 擴張（擴散 ≥ 75%） | 強烈偏多 | 偏多 | 中性 |
| 觀望（46–74%） | 偏多 | 中性 | 偏空 |
| 收縮（≤ 45%） | 中性 | 偏空 | 強烈偏空 |

- **擴散比例**：20 項指標中，符合偏多規則的比例；缺資料的指標不計入分母。
- **兩期確認**：燈號需連續兩個月落在新區間才切換，避免單月雜訊造成誤判。
- **信心**：同時檢查指標覆蓋數、資料新鮮度與支柱一致性；三項都過為高。

### 頁面導覽

| 頁面 | 回答的問題 |
|---|---|
| 今日判讀 | 現在偏多還是偏空？該怎麼做？ |
| 趨勢雷達 | 哪些指標正在轉強或轉弱？ |
| 需求與貿易 | 終端需求是否在擴張？ |
| 成本與獲利 | 通膨與成本是否壓縮企業獲利？ |
| 流動性與風險 | 資金與信用環境是否友善？ |
| 股市比對 | 股市是否已反映總經？ |
| GMI 指數 | 20 項指標的完整歷史與明細 |
| 台股資金輪動 | 資金正流向台股哪些類股？ |
| 燈號回測 | 歷史上這個燈號之後，股市表現如何？ |

### 限制與注意事項

- 這是規則式框架，**不是預測模型**；股市常領先總經數個月，景氣最差時往往已接近底部。
- 歷史回測僅涵蓋約一個完整景氣循環，且訊號使用修正後資料，實際當時公布的數值可能不同。
- 月度數據有 2–6 週公布時差；「資料過期」的指標請降低權重。
"""


def render_guide() -> None:
    st.markdown(GUIDE)
    _html(c.disclaimer())


# ── Taiwan early warning ──────────────────────────────────────────────────────

_GROUPS = ("總經壓力", "市場內部", "籌碼", "情緒")


def _fmt(v, spec: str, suffix: str = "") -> str:
    return "—" if v is None else f"{format(v, spec)}{suffix}"


def _gauge_card(g: dict) -> str:
    w = g["window"]
    rows = [
        ("站上 MA20／MA60 的上市股", f"{_fmt(g['pct_ma20'], '.0f', '%')}／{_fmt(g['pct_ma60'], '.0f', '%')}"),
        ("台指 VIX − 美 VIX", _fmt(g["vix_gap"], "+.1f", " 點")),
        (f"費半相對加權 {w} 日", _fmt(g["sox_rel"], "+.1f", " pp")),
        (f"台積電相對加權 {w} 日", _fmt(g["tsmc_rel"], "+.1f", " pp")),
        (f"美 10Y {w} 日", _fmt(g["dgs10_chg"], "+.2f", " pp")),
        (f"美元指數 {w} 日", _fmt(g["dxy_chg"], "+.1f", "%")),
        (f"USD/TWD {w} 日", _fmt(g["twd_chg"], "+.1f", "%")),
    ]
    items = "".join(f"<li><b>{c.escape(k)}</b> {c.escape(v)}</li>" for k, v in rows)
    return ('<div class="gm-card"><h4>參考指標（不計入燈號）</h4>'
            f"<ul>{items}</ul></div>")


def _rebuy_card(w: dict) -> str:
    items = "".join(f"<li>{c.chip('符合' if r['met'] else '未符合', 'bullish' if r['met'] else 'neutral')} "
                    f"<b>{c.escape(r['id'])} {c.escape(r['name'])}</b></li>"
                    for r in w["rebuy"]["conditions"])
    note = "三項都符合後分三批買回，每批間隔至少 5 個交易日。"
    return f'<div class="gm-card"><h4>買回條件</h4><ul>{items}</ul><p class="gm-sub">{note}</p></div>'


def _raw_charts(frame: pd.DataFrame, show_chart) -> None:
    import plotly.graph_objects as go
    from ui.theme import TOKENS
    f = frame.tail(250)
    specs = [
        ("上漲／下跌家數（上市股票）", [("上漲", f["adv"], TOKENS["bull"]), ("下跌", f["dec"], TOKENS["bear"])]),
        ("外資現貨 20 日累計（億）", [("外資", f["fini"].rolling(20, min_periods=16).sum(), TOKENS["accent"])]),
        ("外資台指期淨未平倉（口，TX 等值）", [("淨部位", f["fut_oi"], TOKENS["serious"])]),
        ("融資餘額（億）", [("融資", f["margin"], TOKENS["flat"])]),
        ("成交金額 20 日均（億）", [("20 日均量", f["turnover"].rolling(20, min_periods=20).mean(), TOKENS["accent"])]),
        ("台指 VIX", [("台指 VIX", f["vixtwn"], TOKENS["serious"])]),
    ]
    cols = st.columns(2)
    for i, (title, traces) in enumerate(specs):
        if all(s.dropna().empty for _, s, _ in traces):
            continue
        fig = go.Figure()
        for name, s, color in traces:
            fig.add_trace(go.Scatter(x=s.index, y=s, name=name, mode="lines", line=dict(color=color, width=1.6)))
        fig.update_layout(title=title, height=260, showlegend=len(traces) > 1, hovermode="x unified")
        with cols[i % 2]:
            show_chart(fig, key=f"fig_twwarn_raw_{i}")


def render_tw_warning(w: dict, show_chart, load_backtest, params: list[dict]) -> None:
    from analytics.tw_warning import DISCLAIMER as TW_DISCLAIMER
    if not w.get("available"):
        _html(c.tw_warning_card(w))
        st.info("台股籌碼資料尚未載入。排程器第一次執行時會匯入內建的 10 年歷史。")
        return
    _html('<div class="gm-grid">' + c.tw_warning_card(w) + _rebuy_card(w) + _gauge_card(w["gauges"]) + "</div>")
    if w["level"] != w["level_raw"]:
        st.caption(f"今天的條件對應「{w['raw_info']['label']}」，燈號要連續成立數日才會改變，以免來回跳動。")

    _html(c.section("九項訊號", "近 10 個交易日內成立過的訊號都計入項數"))
    _html('<div class="gm-grid">' + "".join(c.tw_signal_list(w["signals"], g) for g in _GROUPS) + "</div>")
    if w["recent_divergence_days"]:
        st.caption("最近「指數漲 ≥ 1%、但下跌家數較多」的日子：" + "、".join(w["recent_divergence_days"]))

    fig = charts.warning_timeline(w["history"])
    if fig:
        show_chart(fig, key="fig_twwarn_timeline")

    with st.expander("原始數據（近一年）"):
        _raw_charts(w["frame"], show_chart)

    with st.expander("回測：訊號命中率與持股策略（近 10 年）"):
        bt = load_backtest()
        if not bt.get("available"):
            st.info("歷史資料不足，無法回測。")
        else:
            st.caption(f"期間 {bt['start']:%Y-%m-%d} ～ {bt['end']:%Y-%m-%d}。"
                       "「命中」= 之後 40 個交易日內最多下跌 8% 以上。"
                       "獨立次數把間隔不到 40 日的訊號日算成同一次；少於 10 次時標示樣本不足。")
            st.dataframe(bt["hit_rates"], hide_index=True, width="stretch",
                         column_config={"命中率": st.column_config.NumberColumn(format="%.1f%%")})
            st.caption("以當天收盤價成交、來回成本 0.59%、不含股息（對一直持有略為不利）。")
            st.dataframe(bt["strategies"], hide_index=True, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%.1f%%")
                                        for k in ("年化報酬", "最大跌幅", "平均持股")})
            st.caption("高點到低點跌超過 12% 的事件")
            st.dataframe(bt["events"], hide_index=True, width="stretch",
                         column_config={k: st.column_config.NumberColumn(format="%.1f%%")
                                        for k in ("跌幅", "橙燈時距高點", "紅燈時距高點")})

    with st.expander("參數（analytics/tw_warning_config.py）"):
        st.caption("來源 A = 檢討分析中的實際觀察值；P = 建議值，已用前 6 年校準、後 4 年驗證。")
        st.dataframe(pd.DataFrame(params).astype({"值": str}), hide_index=True, width="stretch")
    _html(f'<p class="gm-sub" style="margin-top:20px">{c.escape(TW_DISCLAIMER)}</p>')
