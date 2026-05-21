# 13F 智慧資金持倉排名功能規格書

**版本：** v1.0  
**目標系統：** 全球經濟指標儀表板（`dashboard.py` + `data_fetcher.py`）  
**部署方式：** 在現有 `tab_d`（股市比對）新增獨立 Sub-Tab，不影響現有任何 Panel  
**可行性：** ✅ **完全可行** — Backend (`fetch_13f_smart_money`) 已完整實作，只需新增 UI 呈現層

---

## 1. 現況分析

### 已完成（Backend 100%）

| 模組 | 位置 | 狀態 |
|------|------|------|
| `fetch_13f_smart_money(n_top=20)` | `data_fetcher.py` L1298 | ✅ 完整實作 |
| `_13F_MAJOR_FUNDS` 20 家基金 CIK 清單 | `data_fetcher.py` L1101 | ✅ 已驗證 |
| `_fetch_fund_delta()` 季度差值計算 | `data_fetcher.py` L1266 | ✅ CUSIP 去重 |
| `_edgar_parse_infotable()` XML 解析 | `data_fetcher.py` L1202 | ✅ 含修訂版處理 |
| `load_13f_data()` Streamlit 快取 | `dashboard.py` L128 | ✅ 24h TTL |
| `edgar_connectivity_test()` 診斷 | `data_fetcher.py` L1429 | ✅ |

### 現有 Dashboard 13F 位置

`tab_d`（股市比對）內已有 Sub-Tab 結構：
- `_sub_s` — 股數排名
- `_sub_v` — 市值排名（$M）
- `_sub_c` — 機構共識

**本次需求：** 在 `tab_d` 新增第四個 Sub-Tab `_sub_rank` — **分類排名總覽**，整合今日展示的內容（類別標籤 + 橫向比較排名）

---

## 2. 新功能需求：`_sub_rank` — 持股分類排名總覽

### 2.1 UI 位置

```python
# dashboard.py — tab_d 內，修改 sub-tab 宣告
# 原本（L1465）：
_sub_s, _sub_v, _sub_c = st.tabs(["📊 股數排名", "💵 市值排名（USD）", "🤝 機構共識"])

# 改為：
_sub_rank, _sub_s, _sub_v, _sub_c = st.tabs([
    "🏆 分類排名總覽", "📊 股數排名", "💵 市值排名（USD）", "🤝 機構共識"
])
```

### 2.2 板塊分類字典（新增至 `dashboard.py` 頂部常數區）

```python
# ── 13F 板塊分類對照表 ─────────────────────────────────────────────────────
_SECTOR_MAP: dict[str, str] = {
    # 科技
    "MICROSOFT":     "科技",  "MSFT": "科技",
    "APPLE":         "科技",  "AAPL": "科技",
    "AMAZON":        "科技",  "AMZN": "科技",
    "ALPHABET":      "科技",  "GOOGL": "科技", "GOOG": "科技",
    "META":          "科技",  "META PLATFORMS": "科技",
    "NETFLIX":       "科技",  "NFLX": "科技",
    "SALESFORCE":    "科技",  "CRM": "科技",
    "IBM":           "科技",
    "SERVICENOW":    "科技",  "NOW": "科技",
    # 半導體
    "NVIDIA":        "半導體", "NVDA": "半導體",
    "TAIWAN SEMI":   "半導體", "TSM": "半導體", "TSMC": "半導體",
    "BROADCOM":      "半導體", "AVGO": "半導體",
    "LAM RESEARCH":  "半導體", "LRCX": "半導體",
    "APPLIED MATER": "半導體", "AMAT": "半導體",
    "QUALCOMM":      "半導體", "QCOM": "半導體",
    # 金融
    "JPMORGAN":      "金融",  "JPM": "金融",
    "GOLDMAN":       "金融",  "GS": "金融",
    "BERKSHIRE":     "金融",  "BRK": "金融",
    "BROOKFIELD":    "金融",  "BAM": "金融",
    "VISA":          "金融",  "V": "金融",
    "MASTERCARD":    "金融",  "MA": "金融",
    # 醫療
    "ELI LILLY":     "醫療",  "LLY": "醫療",
    "JOHNSON":       "醫療",  "JNJ": "醫療",
    "UNITEDHEALTH":  "醫療",  "UNH": "醫療",
    "ABBVIE":        "醫療",
    # 消費
    "WALMART":       "消費",  "WMT": "消費",
    "COSTCO":        "消費",  "COST": "消費",
    "AMAZON COM":    "消費",
    "COUPANG":       "消費",  "CPNG": "消費",
    # 能源/工業
    "CHEVRON":       "能源",  "CVX": "能源",
    "EXXON":         "能源",  "XOM": "能源",
    "LINDE":         "工業",  "LIN": "工業",
    "GE":            "工業",
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

def _classify_sector(display_name: str) -> str:
    """模糊比對持倉名稱 → 板塊"""
    name_upper = display_name.upper()
    for keyword, sector in _SECTOR_MAP.items():
        if keyword in name_upper:
            return sector
    return "其他"
```

### 2.3 `_sub_rank` UI 實作（新增至 `tab_d` with 區塊）

```python
with _sub_rank:
    st.markdown("### 🏆 分類排名總覽")
    st.caption(
        f"資料期間：{_quarter}　｜　追蹤基金：{_fund_count} 家　｜　"
        "依淨增持市值排名，附板塊分類標籤"
    )

    # ── KPI 列 ──────────────────────────────────────────────────────────
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

    # ── 板塊篩選器 ──────────────────────────────────────────────────────
    _all_sectors = list(_SECTOR_COLOR.keys())
    _sel_sectors = st.multiselect(
        "板塊篩選（空白 = 全部）",
        options=_all_sectors,
        default=[],
        key="rank_sector_filter",
    )

    # ── 建立排名 DataFrame（依市值排名）────────────────────────────────
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

    # 套用板塊篩選
    if _sel_sectors:
        _rank_df = _rank_df[_rank_df["板塊"].isin(_sel_sectors)]

    # ── 橫向長條圖（市值排名）──────────────────────────────────────────
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
            hovertemplate=(
                '<b>%{y}</b><br>'
                '淨增持：$%{x:,.0f}M<br>'
                '<extra></extra>'
            ),
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

    # ── 板塊匯總（依板塊加總）──────────────────────────────────────────
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

    # ── 明細表格 ───────────────────────────────────────────────────────
    st.markdown("#### 📋 持倉明細（可排序）")
    if not _rank_df.empty:
        st.dataframe(
            _rank_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "排名":        st.column_config.NumberColumn(width="small"),
                "持倉名稱":   st.column_config.TextColumn(width="medium"),
                "板塊":       st.column_config.TextColumn(width="small"),
                "淨增持（$M）": st.column_config.NumberColumn(
                    format="$%.1f M", width="medium"
                ),
                "共識基金數": st.column_config.NumberColumn(
                    width="small", help="同向操作的機構數量"
                ),
                "訊號":       st.column_config.TextColumn(width="small"),
            },
        )
```

---

## 3. 修改步驟（逐步操作）

### Step 1 — 新增常數與輔助函數

在 `dashboard.py` 的 `# MUST BE FIRST` 之後、`CACHE_TTL` 之前，加入第 2.2 節的 `_SECTOR_MAP`、`_SECTOR_COLOR`、`_classify_sector()`。

### Step 2 — 修改 Sub-Tab 宣告

找到 `dashboard.py` 中的這一行（約 L1465）：

```python
_sub_s, _sub_v, _sub_c = st.tabs(["📊 股數排名", "💵 市值排名（USD）", "🤝 機構共識"])
```

改為：

```python
_sub_rank, _sub_s, _sub_v, _sub_c = st.tabs([
    "🏆 分類排名總覽", "📊 股數排名", "💵 市值排名（USD）", "🤝 機構共識"
])
```

### Step 3 — 插入 `_sub_rank` with 區塊

在新的 `_sub_s` with 區塊之前，插入第 2.3 節的完整 `with _sub_rank:` 程式碼。

### Step 4 — 驗證

```bash
streamlit run dashboard.py
# 前往 Tab D → 分類排名總覽
# 確認板塊篩選、長條圖、匯總圖、表格均正常顯示
```

---

## 4. 資料流確認

```
SEC EDGAR API
    │
    ▼
fetch_13f_smart_money()          ← data_fetcher.py（已完成）
    │  ThreadPool 20 基金並發
    │  CUSIP 去重 + 季度差值
    ▼
load_13f_data()                  ← dashboard.py @cache_data TTL=86400
    │
    ▼  dict keys 已可用：
    │  top_buy_value   → [(name, $M, n_funds), ...]
    │  top_sell_value  → [(name, $M, n_funds), ...]
    │  conviction_buy  → [(name, n_funds, shares), ...]
    │  quarter         → "2025-Q1"
    │  fund_count      → 20
    ▼
_classify_sector(name)           ← 新增輔助函數（純字串比對，無 API 依賴）
    │
    ▼
_sub_rank UI（新增）             ← 橫向長條圖 + 板塊匯總 + 明細表格
```

---

## 5. 可選擴充（Phase 3）

| 功能 | 工作量 | 說明 |
|------|--------|------|
| OpenFIGI API 自動取得 Ticker & 板塊 | 中 | 取代手工 `_SECTOR_MAP`，精確度 100% |
| 持倉歷史時間軸（季度趨勢） | 中 | 需快取多季 EDGAR 資料 |
| 13D/13G 大量收購即時申報 | 高 | 5% 以上持倉即時訊號 |
| 個股 Ticker 超連結至 Yahoo Finance | 低 | `st.column_config.LinkColumn` |
| 板塊比重圓餅圖 | 低 | `go.Pie` 加入 `_sub_rank` |

---

## 6. 注意事項

1. **SEC EDGAR 限流**：`fetch_13f_smart_money()` 已有 `ThreadPoolExecutor(max_workers=3)` 保護，避免觸發 429。首次載入約 20–30 秒，後續 24h TTL 快取。
2. **`_SECTOR_MAP` 維護**：使用關鍵字模糊比對，新標的若未匹配會歸入「其他」，定期補充即可。
3. **Key 衝突**：新增的 `st.plotly_chart` 使用獨立 key（`fig_rank_main`、`fig_rank_sector`），不與現有 key 衝突。
4. **無資料保護**：所有 plotly 區塊已加 `if not _rank_df.empty` 防呆。

---

*本規格書對應系統版本：`dashboard.py`（1983 行）/ `data_fetcher.py`（1445 行）*  
*生成日期：2026-05-21*
