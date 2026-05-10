# 深度優化計畫 — 全球經濟指標儀表板

日期：2026-04-25

---

## 一、診斷摘要

### Web UI 問題
1. **PC 版垂直堆疊**：三個看板各自只有一個欄位，未善用寬螢幕空間。
2. **缺少股市比對指標**：無 S&P500 / TAIEX 的 YoY 圖表，無聯準會基準利率走勢。
3. **T10Y-3M 利差缺失**：只有 T10Y2Y，缺少 T10Y3M（對衰退更敏感的信號）。

### Android 問題
1. **文字亂碼**：`DemandScreen.kt` 的 `infoKoreaExp` / `infoNdc` 以及 `RiskScreen.kt` 的 `infoHySpread` / `infoTwdUsd` 內有嚴重亂碼中文字，為源碼字元集污染造成。
2. **系統導覽列遮擋**：`MainActivity` 未設定 `enableEdgeToEdge()`，系統導航列可能覆蓋底部 NavigationBar。
3. **CIER PMI URL 脆弱**：`fetchTaiwanPmiCier` 的正則要求完整路徑含「PMI-Historical-Data-Seasonally-Adjusted.xlsx」，若 CIER 改檔名即失效。
4. **CBC M1B/M2 解析脆弱**：純 CSV 字元集偵測不穩定，需加更多 fallback。
5. **TSMC 解析脆弱**：MOPS HTML 結構可能變化，欄位定位邏輯需強化。
6. **TopAppBar 主標題**：某些裝置或字型渲染可能導致「全球經濟雷達」顯示異常。

---

## 二、新增指標規劃

### Panel D（新增「📈 股市比對」看板）

| 指標 | 來源 | 說明 |
|---|---|---|
| S&P 500 YoY | FRED `SP500` | 美股月收，計算年增率 |
| TAIEX YoY | Yahoo Finance `^TWII` | 台股加權指數月收，計算年增率 |
| 聯準會基準利率 | FRED `DFF` | 每日有效聯邦基金利率 → 月均 |
| 10Y-3M 利差 | FRED `T10Y3M` | 比 10Y-2Y 更早預測衰退 |
| 美國製造業新訂單 YoY | FRED `AMTMNO` | 製造業需求前端訊號 |

---

## 三、任務相依圖

```
data_fetcher.py (新函式)
    └─► dashboard.py (新看板 + PC 雙欄排版)
        └─► Web UI 測試

Android ApiClient.kt (新方法 + 修復)
    └─► DashboardViewModel.kt (新狀態)
        └─► DemandScreen / CostScreen / RiskScreen / MainScreen 修復
            └─► APK 建置
```

---

## 四、逐任務規格

### T1 — data_fetcher.py 新增與修復
- `fetch_sp500_yoy(api_key)` → FRED SP500 → compute_yoy
- `fetch_taiex_yoy()` → Yahoo Finance v8 API `^TWII` interval=1mo
- `fetch_fed_funds_rate(api_key)` → FRED DFF，月均
- `fetch_t10y3m(api_key)` → FRED T10Y3M
- `fetch_us_new_orders_yoy(api_key)` → FRED AMTMNO → compute_yoy
- 修復 `fetch_taiwan_pmi()` URL regex 更彈性（只抓 `.xlsx` 含 `pmi` 不分大小寫）

### T2 — dashboard.py 優化
- `load_data()` 加入 5 個新 key
- PC 排版：A/B/C 板主圖表改用 `st.columns([1,1])` 雙欄
- 新增 Panel D tab「📈 股市比對」，包含：
  - S&P500 vs TAIEX YoY 疊加圖
  - Fed Funds Rate 走勢
  - 10Y-3M 利差 vs 10Y-2Y 利差疊加圖
  - 美國製造業新訂單 YoY

### T3 — Android 亂碼修復
- `DemandScreen.kt`：重寫 `infoKoreaExp`、`infoNdc` 全文（正確中文）
- `RiskScreen.kt`：重寫 `infoHySpread`、`infoTwdUsd` 全文

### T4 — Android NavigationBar 修復
- `MainActivity.kt`：加入 `enableEdgeToEdge()`
- `MainScreen.kt`：確認 Scaffold innerPadding 正確傳遞，加 `navigationBarsPadding()` 保障

### T5 — Android 台灣資料源修復
- `ApiClient.kt` `fetchTaiwanPmiCier`：改用 `.xlsx` + `pmi` 大小寫不敏感匹配
- `fetchCbcMoneyYoY`：增加 PDF fallback（複製 Python 邏輯）或更強的 CSV charset 偵測
- `fetchTsmcRevenueYoy`：強化欄位定位邏輯（用欄位索引而非關鍵字）

### T6 — Android 新增指標
- `ApiClient.kt`：加 `loadSp500Yoy` / `loadTaiwanStockYoy` / `loadFedFundsRate` / `loadT10y3m`
- `DashboardViewModel.kt`：加對應 LoadState
- 新增 `StockScreen.kt`（第 4 個 tab）
- `MainScreen.kt`：加第 4 個 Tab「股市比對」

### T7 — 文件對齊
- `README.md`：更新功能表格，加新指標說明，更新建置指令
- 刪除 `ANDROID_IMPLEMENTATION.md`（已過時，內容已納入 README）

### T8 — 測試與啟動
- 啟動 Streamlit
- 驗證所有面板資料載入

### T9 — APK 建置
- `gradlew.bat assembleDebug`

---

## 五、驗收標準

**Web UI：**
- [ ] PC 版 A/B/C/D 四個 tab 均能載入
- [ ] 雙欄排版在寬螢幕正確顯示
- [ ] D 板：S&P500 vs TAIEX 疊加圖正確
- [ ] D 板：Fed Funds Rate 正確

**Android：**
- [ ] 無亂碼文字
- [ ] 底部頁面不被系統導覽列遮蓋
- [ ] 台灣 PMI、M1B/M2、TSMC 均能載入
- [ ] 第 4 個「股市比對」Tab 存在且能載入
- [ ] APK 編譯成功
