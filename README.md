# 總經多空儀表板 (Global Macro Dashboard)

回答投資人最在意的問題：**現在總經偏多還是偏空？該怎麼做？什麼會改變判斷？**
資料由排程器每日抓取並存入 SQLite，儀表板只讀本地資料庫，點擊幾乎即時回應。

## 頁面總覽

| 頁面 | 回答的問題 |
|------|------|
| **今日判讀** | 五段式多空結論、四大支柱、操作框架、成長／通膨時鐘、風險警示、多空論據、距離燈號翻轉、歷史相同燈號後的報酬、可下載簡報 |
| **趨勢雷達** | 38 項指標的方向、5 年位階、階段與轉折，可依訊號與類別篩選 |
| **需求與貿易** | 五國 PMI、美國零售、消費者信心、台灣／韓國出口、NDC 領先指標、台積電營收 |
| **成本與獲利** | OECD CLI、庫存、半導體 PPI、實質利率、CPI/PPI 剪刀差、中國 PPI、原油、銅價 |
| **流動性與風險** | VIX、殖利率曲線、M1B/M2、HY 信用利差、美元、台幣、中國信貸脈衝 |
| **股市比對** | S&P 500 vs TAIEX、Fed 利率、10Y-3M、三大法人買賣超 |
| **GMI 指數** | 19 項指標擴散歷史、明細與內部輪動 |
| **台股資金輪動** | 19 類股四象限、動能熱力圖、法人資金流、13F Smart Money |
| **燈號回測** | 各燈號後 1/3/6/12 月報酬分佈、領先落後相關矩陣 |
| **使用指南** | 判讀方法、頁面導覽與限制 |

### 多空判讀規則

`多空分數 = 燈號位階（擴張 +1／觀望 0／收縮 −1）+ 動能方向（3 個月擴散變化 ≥ +10pp 為 +1，≤ −10pp 為 −1）`

分數 +2 到 −2 對應強烈偏多、偏多、中性、偏空、強烈偏空。規則全部公開在 `analytics/market_view.py`，
本工具是規則式框架，**非投資建議**。

---

## 系統架構

```
fetchers/           → 各指標資料抓取
analytics/          → 純邏輯，不依賴 Streamlit
    ├── indicators.py     指標目錄：多空方向、頻率、領先/落後、投資意義
    ├── trend.py          單一序列的方向、位階、階段、轉折、資料是否過期
    ├── market_view.py    多空判讀、支柱、風險警示、成長/通膨時鐘、書面簡報
    └── gmi_backtest.py   條件化回測（含訊號公布時差）
ui/                 → 呈現層
    ├── theme.py          設計 token、全域 CSS、Plotly 模板
    ├── components.py     純函式 HTML 元件（一律跳脫外部資料）
    ├── charts.py         圖表與抽點（保留極值）
    └── pages.py          今日判讀、趨勢雷達、使用指南
macro_index.py      → GMI 評分引擎
scheduler.py        → APScheduler 排程
db_manager.py       → SQLite（ts_rows / blob_cache / ts_meta）與完整快照
dashboard.py        → Streamlit 入口：導覽、快取載入器、分析頁面
```

資料流：`fetchers → scheduler → db_manager(SQLite) → analytics → dashboard`

### 回應速度的設計

- **只執行目前頁面**：點擊的成本與其他頁面的圖表數量無關；子分頁同樣延遲渲染。
- **UI 不等外部網路**：13F、三大法人、指數月收都讀排程器快照；僅在從未抓取過時才連網，並寫回資料庫。
- **快取以資料版本為鍵**：`db_manager.data_version()` 改變才重算，排程寫入後立即生效；
  `cache_resource` 由所有使用者共用一份，不會每次點擊都解序列化（因此回傳物件一律視為唯讀）。
- **圖表抽點**：每條線上限 900 點，保留每區間極值與最新兩點，尖峰與最新讀值不失真。

### 測試

```bash
pip install -r requirements-dev.txt
pytest tests -q --cov=analytics --cov=ui --cov=macro_index --cov=db_manager --cov=dashboard
```

`tests/test_dashboard_app.py` 以 Streamlit AppTest 執行真實 `dashboard.py`，資料來自種子資料庫並封鎖所有網路。
沒有 API Key 也能看畫面：

```bash
python tests/seed_db.py app_data/db/demo.sqlite3
GMI_DB_PATH=app_data/db/demo.sqlite3 streamlit run dashboard.py
```

排程時間表（Asia/Taipei）：
| 排程 | 內容 |
|------|------|
| 每日 02:00 | 所有總經指標（FRED、DBnomics、台灣官方、全球爬取、Yahoo） |
| 每日 02:30 | 台股 19 類股指數 + 成交值 + 三大法人 |
| 週一 / 週四 06:00 | 美國 ETF 類股輪動 + SEC EDGAR 13F |
| 每月 1 日 03:00 | DB 維護（15 年歷史修剪 + WAL checkpoint） |

---

## 本機啟動

### 1. 環境需求

- Python 3.10+
- FRED API Key（[申請免費金鑰](https://fred.stlouisfed.org/docs/api/api_key.html)）

### 2. 安裝套件

```bash
pip install -r requirements.txt
```

### 3. 設定 API Key（選填）

建立 `.env` 檔案（容器與 `scheduler.py` 會自動載入）：

```bash
# .env（放在專案根目錄，勿 commit）
FRED_API_KEY=your_fred_key_here      # 選填，FRED 指標（VIX 歷史、M1 等）
FINMIND_TOKEN=your_finmind_token     # 選填，FinMind API（台積電月營收歷史）
```

不設定時：FRED 指標跳過（VIX 改用 Yahoo Finance）；FinMind 改用匿名模式（每小時有速率限制）。NDC、Eastmoney、TWSE 等來源均不需要 Key。

Windows PowerShell 臨時設定：
```powershell
$env:FRED_API_KEY  = "your_key_here"
$env:FINMIND_TOKEN = "your_token_here"
```

### 4. 初始化歷史資料（首次執行，約 15–20 分鐘）

```bash
python scheduler.py --run-now
```

拉取 15 年歷史資料，使用 INSERT OR IGNORE 安全冪等，可重複執行。

### 5. 啟動儀表板

```bash
streamlit run dashboard.py
```

預設使用 `http://localhost:8501`。首次若未執行 `--run-now`，儀表板會 fallback 至 live fetch（較慢）。

---

## Docker 部署（x86）

```bash
# 建置
docker build -t macro-dashboard .

# 啟動（含 DB volume + FRED Key）
docker run -d \
  --name macro-dashboard \
  -p 8501:8501 \
  -v /your/data/dir:/app/app_data \
  -e FRED_API_KEY=your_key_here \
  macro-dashboard

# 初始化歷史資料
docker exec macro-dashboard python scheduler.py --run-now
```

常用指令：
```bash
docker logs -f macro-dashboard        # 查看 log
docker stop / start macro-dashboard   # 停止 / 重啟
docker rm -f macro-dashboard          # 刪除容器
```

---

## ARM64 嵌入式部署（Yocto / 嵌入式 Linux）

### 1. 跨編譯 ARM64 映像（在 x86 Windows 執行）

```powershell
# 僅 build + 存 tar
.\build_arm64.ps1

# build + SCP + 遠端部署（自動完成）
.\build_arm64.ps1 -Deploy

# 指定目標 IP
.\build_arm64.ps1 -Deploy -YoctoIP 10.1.1.230
```

`build_arm64.ps1` 預設值：
- `YoctoIP = 10.1.1.230`
- `YoctoUser = root`
- `YoctoPath = /root`

### 2. 手動部署至 Yocto

```bash
# 上傳
scp macro-dashboard-arm64.tar root@10.1.1.230:/root/
scp embedded_deployment/deploy.sh root@10.1.1.230:/root/

# 遠端部署
ssh root@10.1.1.230 "sh /root/deploy.sh /root/macro-dashboard-arm64.tar"
```

`deploy.sh` 自動：載入映像 → 停舊容器 → 啟新容器（含 volume + env-file）→ 清除懸空映像。

### 3. 設定 FRED API Key（Yocto 端）

```bash
echo "FRED_API_KEY=your_key_here" > /root/.env
chmod 600 /root/.env
```

容器啟動時自動載入 `/root/.env`（透過 `--env-file`）。API Key 不寫入映像。

### 4. 初始化歷史資料（首次部署後執行一次）

```bash
ssh root@10.1.1.230 "docker exec -d macro-dashboard python scheduler.py --run-now"
```

執行後約 15–20 分鐘完成，之後每日排程自動更新。

### 5. DB 持久化位置

容器 volume：`/root/macro_dashboard_data:/app/app_data`

SQLite 檔案：`/root/macro_dashboard_data/db/indicator_cache.sqlite3`

重新部署容器不會遺失歷史資料。

---

## 專案結構

```
├── dashboard.py              # 主頁面（Streamlit，Tab A–F）
├── data_fetcher.py           # 向後相容入口（呼叫 fetchers/）
├── db_manager.py             # SQLite 持久化（ts_rows / blob / meta）
├── scheduler.py              # APScheduler 排程器
├── macro_index.py            # GMI 全球景氣指數計算
├── fetchers/                 # 各指標資料抓取子模組
│   ├── __init__.py
│   ├── utils.py              # 共用工具 + Eastmoney helper + Legacy TLS
│   ├── fred.py               # FRED / DBnomics / 信貸脈衝
│   ├── taiwan.py             # 台灣官方 + FinMind + TWSE OpenAPI
│   ├── global_macro.py       # Eastmoney NBS + NDC + Eurostat + 日本
│   ├── yahoo_finance.py      # Yahoo Finance + Stooq + ETF 輪動
│   ├── edgar_13f.py          # SEC EDGAR 13F-HR
│   └── taiwan_sector.py      # MI_INDEX20 + BFI82U + BFIAMU
├── tests/                    # 單元測試（204 個測試）
│   ├── test_db_manager.py
│   ├── test_taiwan_sector.py
│   ├── test_scheduler.py
│   ├── test_new_fetchers.py  # CN PMI / NDC / 信貸脈衝 / TSMC mock-HTTP 測試
│   └── ...
├── android_dashboard/        # Android App（Kotlin + Compose）
├── embedded_deployment/      # ARM64 嵌入式部署腳本
│   ├── Dockerfile            # ARM64 映像定義
│   └── deploy.sh             # Yocto 端部署腳本
├── tools/
│   └── post_deploy.py        # 部署後資料遷移（預設只回報，不修改）
├── build_arm64.ps1           # Windows 跨編譯腳本（buildx）
├── Dockerfile                # x86 Docker 映像定義
├── requirements.txt
└── README.md
```

---

## 資料來源

| 來源 | 指標 |
|------|------|
| [FRED](https://fred.stlouisfed.org/) | VIX、殖利率曲線、M1、零售銷售、CPI/PPI、HY 利差、DFF、DXY、銅、布蘭特、台幣匯率 |
| [DBnomics / OECD](https://db.nomics.world/) | OECD CLI（美中日歐韓）、ISM PMI 子項歷史資料 |
| [Yahoo Finance](https://finance.yahoo.com/) | TAIEX / N225 / KOSPI / HSI / CSI300 YoY、ETF 量能 |
| [FRED](https://fred.stlouisfed.org/) | VIX、殖利率曲線、M1、零售銷售、CPI/PPI、HY 利差、DFF、DXY、銅、布蘭特、台幣匯率 |
| [DBnomics / OECD](https://db.nomics.world/) | OECD CLI（美中日歐韓，資料截至 2023-12） |
| [Yahoo Finance + Stooq](https://finance.yahoo.com/) | TAIEX / N225 / KOSPI / HSI YoY、VKOSPI（Stooq fallback）、ETF 量能 |
| [TWSE](https://www.twse.com.tw/) | MI_INDEX20（19 類股日收盤）、BFI82U（三大法人市場整體）、BFIAMU（三大法人各類股） |
| [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar) | 13F-HR 機構持倉（20 大機構） |
| [Eastmoney datacenter](https://datacenter-web.eastmoney.com/) | 中國 NBS PMI、中國 PPI YoY |
| [MOFCOM](https://data.mofcom.gov.cn/) | 中國社融增量（信貸脈衝，Legacy TLS） |
| [中華民國財政部](https://web02.mof.gov.tw/) | 台灣出口金額 YoY |
| [中央銀行](https://www.cbc.gov.tw/) | M1B / M2 YoY |
| [中華經濟研究院](https://www.cier.edu.tw/) | 台灣製造業 PMI |
| [FinMind + TWSE OpenAPI](https://finmindtrade.com/) | 台積電月營收歷史（FinMind）+ 最新月 YoY（TWSE t187ap05_L） |
| [國發會](https://index.ndc.gov.tw/) | 景氣領先指標 + 景氣對策信號分數（CSRF+POST） |
| [韓國關稅廳](https://unipass.customs.go.kr/) | 韓國出口 YoY |
| [Eurostat](https://ec.europa.eu/eurostat) | 工業信心指標（ICI） |
| [日本内閣府](https://www5.cao.go.jp/) | 景氣觀測 DI |

---

## Android App

Android 端採原生 Kotlin + Jetpack Compose，四個看板（A/B/C/D）與 PC Web UI 對齊。

```bash
# 建置 APK
cd android_dashboard
gradlew.bat assembleDebug

# 安裝至裝置
adb install -r app\build\outputs\apk\debug\app-debug.apk
```
