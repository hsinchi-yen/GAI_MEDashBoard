# 待下次實作清單 (incompleted.md)

> 暫停時點：2026-05-28。4 個 fetcher 換源修復完成（CN PMI、CN PPI、NDC 領先/燈號、信貸脈衝、台積電 YoY）、204 tests 全綠、UI 改善（概覽資料中斷展開、NDC 燈號色帶圖）均已驗證。
> 本機程式碼未 commit，部署至遠端 (10.1.1.230) 為本 session 末段任務。

---

## 🔴 Bug — 尚未修復

### 1. `fetch_vkospi` 404
- **現況**：Yahoo Finance 舊的 VKOSPI 端點回 404，函式永遠回空 DataFrame。
- **影響**：Tab D 的 VKOSPI 波動率欄位 N/A。
- **下一步**：找 Yahoo Finance v8 / v10 現行 VKOSPI ticker（`^VKOSPI`），或改用 FRED `VKOSPIX`（免費，但需 `FRED_API_KEY`）。
  - 可先測：`https://query2.finance.yahoo.com/v8/finance/chart/%5EVKOSPI`

---

## 🟡 資料源品質改善

### 2. OECD CLI 圖表顯示過期資料
- **現況**：OECD CLI (`cli_*`) 最新資料停在 2023-12（DBnomics MEI 停更），serve-stale 機制會把舊值回傳給圖表。GMI 計分已移除 OECD CLI（commit `e344a96`），但 Tab B 的 CLI 折線圖仍顯示 2.5 年舊資料。
- **影響**：可能誤導，讀者以為是最新 OECD 評估。
- **下一步**：Tab B 圖表加「資料截止 YYYY-MM」標注；或改接 `OECD.Stat` REST API（`stats.oecd.org/sdmx-json`，有 CLI 月度更新）。

---

## 🟡 功能待補

### 3. Tab F — 加入法人類股買超欄位（T86 by sector）
- **現況**：Tab F 顯示 19 類股四象限散點 / 熱力圖 / 成交值堆疊面積圖，但無法人（外資/投信/自營商）類股分項淨買超。
- **需求**：TWSE T86 (`bfiagrn2`) 按類股分 3 大法人淨買超金額，供投資人交叉比對資金輪動。
- **下一步**：
  1. `fetchers/taiwan_sector.py` `fetch_tw_sector_institutional()` 已有骨架但尚未完整實作。
  2. 確認 TWSE T86 下載格式（CSV/JSON），解析 19 類股 × 3 法人矩陣。
  3. Tab F-4 頁（現為 13F 持倉）或新增 F-5 頁呈現。

### 4. README 更新
- 缺：Tab F 功能說明、`.env` 範例（`FINMIND_TOKEN`、`FRED_API_KEY`）、嵌入式機部署步驟（`build_arm64.ps1 -Deploy`）。

---

## 環境備忘（遠端）

- `root@10.1.1.230`：Yocto aarch64 (pico-imx8mm)，Docker，無 docker-compose。
- 容器 `macro-dashboard`（pandas 3.0.3）：程式碼 `/app`，DB 持久化 `/root/macro_dashboard_data` → `/app/app_data`。
- 初始化 DB：`docker exec macro-dashboard python scheduler.py --run-now`
- 診斷唯讀 GMI：`docker exec macro-dashboard python tests/gmi_regression.py --db app_data/db/indicator_cache.sqlite3`

---

## 已完成（本次 session）

| 項目 | 狀態 |
|---|---|
| CN PMI — 改 Eastmoney `RPT_ECONOMY_PMI` | ✅ |
| CN PPI YoY — 改 Eastmoney `RPT_ECONOMY_PPI` | ✅ |
| NDC 領先指標 — CSRF+POST `/n/json/leading` | ✅ |
| NDC 景氣燈號分數 — POST `/n/json/lightscore`（新 key） | ✅ |
| 信貸脈衝 — 商務部社融增量 TTM YoY（MOFCOM shrzgmQuery） | ✅ |
| 台積電 YoY — FinMind 歷史 + TWSE OpenAPI t187ap05_L | ✅ |
| Overview 資料中斷展開器 | ✅ |
| NDC 燈號色帶圖 | ✅ |
| `tests/test_new_fetchers.py`（10 新測試，mock HTTP） | ✅ 204 passed |
| GMI 比例制計分 + stale-while-revalidate | ✅（前次 session） |
