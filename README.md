# 📊 全球經濟指標儀表板 (Global Macro Dashboard)

即時追蹤全球總體經濟與台股資金輪動的 Streamlit 互動式儀表板。資料透過排程器（APScheduler）每日抓取並持久化至 SQLite，儀表板讀取本地快取，冷啟動後幾乎即時顯示。

## 功能總覽

| 看板 | 內容 |
|------|------|
| **A：終端需求感測** | 五國 PMI、美國零售銷售、密西根消費者信心、台灣出口 YoY、韓國出口 YoY、NDC 景氣領先指標 |
| **B：獲利與成本感測** | OECD CLI、美國商業庫存、半導體 PPI、10Y 實質利率、核心 CPI/PPI 剪刀差、中國 PPI、布蘭特原油、銅價 YoY、台積電營收 YoY |
| **C：流動性與風險感測** | VIX 恐慌指數、美債殖利率曲線 / 10Y-2Y 利差、貨幣供給 M1B/M2 YoY、HY 信用利差、台幣匯率 |
| **D：股市比對** | S&P 500 vs TAIEX YoY、聯準會基準利率 (DFF)、美債 10Y-3M 利差（衰退領先）、美國製造業新訂單 YoY |
| **E：全球景氣總覽** | 全球 GMI 綜合熱力圖、各指標最新值 |
| **F：台股資金輪動** | 19 類股四象限輪動快照、動能熱力圖、三大法人各類股買超、成交值佔比趨勢、13F Smart Money |

---

## 系統架構

```
fetchers/           → 各指標資料抓取（7 個子模組）
    ├── __init__.py       匯出所有 fetch_* 函式
    ├── utils.py          共用工具（Eastmoney helper、Legacy TLS adapter）
    ├── fred.py           FRED / DBnomics（VIX、利率、HY、銅、信貸脈衝）
    ├── taiwan.py         台灣官方（財政部、央行、CIER PMI、FinMind+TWSE 台積電）
    ├── global_macro.py   全球總經（ISM PMI、Eastmoney NBS、NDC、Eurostat、日本）
    ├── yahoo_finance.py  Yahoo Finance + Stooq（指數 YoY、VKOSPI、ETF 輪動）
    ├── edgar_13f.py      SEC EDGAR 13F-HR（20 大機構持倉）
    └── taiwan_sector.py  TWSE MI_INDEX20 + BFI82U + BFIAMU 台股類股

scheduler.py        → APScheduler 排程（每日 02:00 / 02:30 更新）
db_manager.py       → SQLite 持久化（三表架構：ts_rows / blob_cache / ts_meta）
dashboard.py        → Streamlit UI（DB-first 讀取，fallback live fetch）
```

資料流：`fetchers → scheduler → db_manager(SQLite) → dashboard`

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
│   ├── deploy.sh             # Yocto 端部署腳本
│   └── run_docker.sh         # 直接在 Yocto 建置並執行
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
