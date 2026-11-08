# 實作計畫：13F 分類排名總覽，補齊規格與實作的落差

## 概述

`13F_smart_money_feature_spec.md`（v1.0，2026-05-21）在 commit `0110e85` 已經實作，目前在
`dashboard.py` 的「13F 法人持倉」子頁（`_sub_rank`，約 L2665–2790）。不過規格的內容沒有全部做到，
實作也有幾個規格本身沒預料到的錯誤。這份計畫處理這些落差，不重做已經完成的部分。

### 規劃時確認的問題（2026-11-08，只讀檢查）

| # | 問題 | 證據 |
|---|------|------|
| G1 | `_classify_sector` 用子字串比對，短代號會誤判 | `CHARTER COMMUNICATIONS` 因為含 `MU` 被分到「資訊科技」；`MUELLER INDS` 也一樣；`BRKR BRUKER` 因為含 `BRK` 被分到「金融」 |
| G2 | 板塊分類沒有統一 | 「科技/資訊科技」「醫療/醫療保健」「消費/核心消費」同時存在；`SANDISK` 被分到「能源」；`AMAZON COM` 被分到「科技」（規格原本寫消費，但因為字典順序永遠不會生效） |
| G3 | 排名和板塊匯總只用 `top_buy_value` | 「訊號 🔴 賣出」永遠不會出現；「板塊資金流向匯總」標成淨流量，實際只加總買方；`ProgressColumn(min_value=0)` 處理不了負值 |
| G4 | 排名邏輯寫在 3200 行的 `dashboard.py` 裡，沒有測試 | `tests/` 中沒有任何 `_classify_sector` 或排名表的測試；AppTest 只檢查 13F 頁有沒有顯示季度 |
| G5 | 沒有測過真實資料的分類覆蓋率 | 本機 DB 是種子資料，只有 4 檔；真實名單只在生產機 `10.1.1.230` 上 |

## 架構決策

- **把純邏輯抽到 `analytics/smart_money.py`**：`classify_sector(name)` 和 `build_rank_table(smart) -> DataFrame`
  不依賴 Streamlit，可以直接寫單元測試。`dashboard.py` 只負責畫圖。這和 `analytics/market_view.py` 的做法一致。
- **分類改成比對完整的詞**：先把名稱切成詞，多字關鍵字（例如 `ELI LILLY`）要求依序相連，單字關鍵字要求整詞相符。
  長的關鍵字先比對，結果不再受字典順序影響。
- **板塊用 GICS 11 類的中文名**，`_SECTOR_COLOR` 一個板塊對一個顏色。「半導體」是否保留為獨立類別，見「待決問題」。
- **淨流量 = 買方 + 賣方**：把 `top_buy_value` 和 `top_sell_value` 合成一份排名，正負都保留。
  長條圖用正負方向和顏色區分買賣；表格改用 `NumberColumn`，因為 `ProgressColumn` 不支援負值。
- **不改 fetcher 和 snapshot 格式**：`fetchers/edgar_13f.py` 的輸出和 `13f_smart_money` snapshot 的格式維持不變，
  生產機上現有的資料不需要重抓。

## 相依關係

```
T1 生產機名單基準（只讀）──► 測試資料與覆蓋率基準
        │
        ▼
T2 classify_sector 改為整詞比對（+ 單元測試）
        │
        ▼
T3 統一板塊分類並補充對照表 ◄── 待決問題 Q1
        │
        ▼
T4 build_rank_table 合併買賣方 ──► T5 dashboard 改用新函數，更新圖表與表格
                                          │
                                          ▼
                                   T6 容器內測試與生產機驗證
```

## 任務清單

### 第一階段：基準與分類正確性

#### 任務 1：取得生產機的真實 13F 名單作為基準
**說明：** 在生產機容器內讀出 `13f_smart_money` snapshot，列出所有標的名稱和目前的分類結果，
存成測試資料 `tests/data/13f_names_prod.txt`，並記錄目前歸入「其他」的比例。只讀，不寫生產 DB。

**驗收條件：**
- [ ] 取得 `top_buy_value`、`top_sell_value` 和 `conviction_*` 中所有不重複的名稱
- [ ] 記錄基準數字：總檔數、歸入「其他」的檔數、人工判定為誤判的檔數

**驗證：**
- [ ] `docker exec -i -w /app macro-dashboard python - < 腳本` 執行成功，沒有寫入動作
- [ ] 名單檔已存入 repo，內容只有公司名稱，沒有持股數字

**相依：** 無　**檔案：** `tests/data/13f_names_prod.txt`（新增）　**規模：** XS

#### 任務 2：`classify_sector` 改為整詞比對，並移到 `analytics/smart_money.py`
**說明：** 新增 `analytics/smart_money.py`，實作整詞比對、長關鍵字優先的 `classify_sector`。
`dashboard.py` 的 `_classify_sector` 改成呼叫它。這個任務先不更動對照表內容，只修比對方式。

**驗收條件：**
- [ ] `CHARTER COMMUNICATIONS`、`MUELLER INDS`、`BRKR BRUKER` 不再因為短代號誤判
- [ ] `ELI LILLY & CO`、`TAIWAN SEMICONDUCTOR MFG`、`META PLATFORMS INC` 仍然分類正確（多字和前綴關鍵字可用）
- [ ] 分類結果不受字典順序影響（測試：打亂字典順序，結果相同）

**驗證：**
- [ ] `.venv\Scripts\python -m pytest tests/test_smart_money.py -q` 通過
- [ ] 以任務 1 的名單比較修改前後，只有預期的項目改變

**相依：** T1　**檔案：** `analytics/smart_money.py`、`dashboard.py`、`tests/test_smart_money.py`　**規模：** S

#### 任務 3：統一板塊分類並補充對照表
**說明：** 依照 Q1 的決定，合併重複的板塊（科技/資訊科技、醫療/醫療保健、消費/核心消費），
修正 `SANDISK`、`AMAZON` 等錯誤，並依照任務 1 的名單補上常見標的。同步清理 `_SECTOR_COLOR`。

**驗收條件：**
- [ ] `_SECTOR_MAP` 用到的每個板塊在 `_SECTOR_COLOR` 都有顏色，而且沒有同義的重複板塊
- [ ] 生產機名單歸入「其他」的比例低於 Q2 約定的門檻，ETF 除外
- [ ] 不影響台股的板塊對照（`_GROUP_ORDER` 等），這部分不在本次範圍

**驗證：**
- [ ] 測試：`set(MAP.values()) <= set(COLOR)`；對真實名單逐筆斷言預期板塊
- [ ] `pytest tests/ -q` 全部通過

**相依：** T2、Q1　**檔案：** `analytics/smart_money.py`、`dashboard.py`、`tests/test_smart_money.py`　**規模：** S

### 檢查點 A：分類正確
- [ ] `pytest tests/ -q` 全部通過
- [ ] 提出任務 1 名單在修改前後的分類對照表，交由人工確認

### 第二階段：淨流量排名（垂直切片：資料 → 圖 → 表）

#### 任務 4：`build_rank_table` 合併買方和賣方
**說明：** 在 `analytics/smart_money.py` 新增 `build_rank_table(smart: dict) -> pd.DataFrame`，
合併 `top_buy_value` 和 `top_sell_value`，加上板塊、方向和排名。另外新增 `sector_net_flow(df)`，
加總各板塊的淨流量。兩個函數都要能處理空的或缺少欄位的 snapshot。

**驗收條件：**
- [ ] 同時有買方和賣方時，表格中正負值都有，「訊號」欄兩種都會出現
- [ ] 板塊淨流量 = 該板塊所有買方和賣方的加總（用種子資料的數字驗算）
- [ ] 空 dict、缺少 key、列表為空時回傳有正確欄位的空 DataFrame，不拋出例外

**驗證：**
- [ ] `pytest tests/test_smart_money.py -q` 通過

**相依：** T2　**檔案：** `analytics/smart_money.py`、`tests/test_smart_money.py`　**規模：** S

#### 任務 5：`_sub_rank` 改用新函數
**說明：** `dashboard.py` 的排名子頁改呼叫 `build_rank_table` 和 `sector_net_flow`。
新增「買方 / 賣方 / 全部」切換。長條圖顯示正負方向。板塊匯總改為真正的淨流量。
明細表把 `ProgressColumn` 換成 `NumberColumn`。KPI 和篩選器的行為不變。

**驗收條件：**
- [ ] 種子資料下，排名圖同時顯示 NVIDIA（買）和 TESLA（賣），板塊匯總出現負值
- [ ] 板塊篩選和買賣切換可以一起使用；篩選後沒有資料時顯示提示文字，不顯示空圖
- [ ] 開啟其他頁面時不讀取 13F snapshot（`test_only_the_open_sub_tab_loads` 仍然通過）

**驗證：**
- [ ] `pytest tests/test_dashboard_app.py -q` 通過，並新增 AppTest：13F 排名子頁的表格同時有正負值
- [ ] 在本機用 `streamlit run dashboard.py` 檢查淺色和深色主題

**相依：** T3、T4　**檔案：** `dashboard.py`、`tests/test_dashboard_app.py`、`tests/seed_db.py`（必要時）　**規模：** M

### 檢查點 B：功能完成
- [ ] `pytest tests/ -q` 全部通過
- [ ] 本機畫面截圖交由人工確認

### 第三階段：上線驗證

#### 任務 6：容器內測試，並在生產機驗證
**說明：** 依照 `remote_deploy.md`，先用 amd64 建置同一份 Dockerfile，在容器內跑測試，避免本機和映像的套件版本不同。
接著用生產機的 snapshot 執行 `build_rank_table`，檢查結果。部署由人工確認後才進行。

**驗收條件：**
- [ ] amd64 容器內 `pytest` 全部通過（Streamlit / pandas / Plotly 版本與映像相同）
- [ ] 在生產機 snapshot 上執行沒有例外，「其他」比例和任務 1 的基準相比有改善
- [ ] 部署後 `macro-dashboard` 健康檢查正常，13F 頁可以開啟；其他專案的容器沒有受影響

**驗證：**
- [ ] 容器內測試的輸出
- [ ] `docker exec` 診斷腳本的輸出（只讀）

**相依：** T5　**檔案：** 無程式碼變更　**規模：** XS

### 檢查點 C：完成
- [ ] 規格第 2 節的所有功能在生產機上正常
- [ ] 更新規格書，加註 v1.1 的變更（淨流量、分類方式），避免規格和程式不一致

## 不在範圍內（規格第 5 節「可選擴充」）
OpenFIGI 自動分類、多季趨勢、13D/13G、Yahoo 連結、圓餅圖。這些要另外排程。
其中 OpenFIGI 可以根本解決 G1 和 G2，但需要外部 API 和金鑰，排程器也要調整，工作量至少是中等。

## 風險與因應

| 風險 | 影響 | 因應 |
|------|------|------|
| 生產機 snapshot 的名稱被截斷成 30 字（`_clean_issuer_name`），整詞比對可能對不到最後一個詞 | 中 | 任務 1 先確認截斷的實際情形；最後一個詞允許前綴比對 |
| 本機和映像的套件版本不同，`column_config` 行為可能有差異 | 中 | 任務 6 在 amd64 容器內測試 |
| 手工對照表本來就涵蓋不全 | 低 | 用覆蓋率門檻管控；未分類的歸入「其他」，不影響功能；長期改用 OpenFIGI |
| 改動 `_SECTOR_COLOR` 影響其他頁面 | 低 | 先 grep 確認只有 13F 頁使用；台股板塊有自己的對照 |

## 待決問題
- **Q1 板塊分類：** 用 GICS 11 類，還是保留現有的「半導體」獨立類別？（建議：GICS 11 類，再額外保留「半導體」和「ETF」，比較符合使用者看台股的習慣）
- **Q2 覆蓋率門檻：** 不含 ETF 的「其他」比例，目標訂多少？（建議 ≤ 15%，以任務 1 的基準為準）
- **Q3 預設檢視：** 排名頁預設顯示「全部（淨流量）」還是「買方」？（建議「全部」，因為規格的標題是淨增持排名）
