# 📊 全球經濟指標儀表板 (Global Macro Dashboard)

即時追蹤全球總體經濟指標的 Streamlit 互動式儀表板，涵蓋 PMI、消費者信心、出口、庫存、殖利率曲線、VIX、貨幣供給、股市比對等關鍵數據。

## 功能總覽

| 看板 | 內容 |
|------|------|
| **A：終端需求感測** | 五國 PMI、美國零售銷售、密西根消費者信心、台灣出口 YoY、韓國出口 YoY、NDC 景氣領先指標 |
| **B：獲利與成本感測** | OECD CLI、美國商業庫存、半導體 PPI、10Y 實質利率、核心 CPI/PPI 剪刀差、中國 PPI、布蘭特原油、銅價 YoY、台積電營收 YoY |
| **C：流動性與風險感測** | VIX 恐慌指數、美債殖利率曲線 / 10Y-2Y 利差、貨幣供給 M1B/M2 YoY、HY 信用利差、台幣匯率 |
| **D：股市比對** | S&P 500 vs TAIEX YoY 疊加、聯準會基準利率 (DFF)、美債 10Y-3M 利差（衰退領先）、美國製造業新訂單 YoY |

---

## 本機啟動

### 1. 環境需求

- Python 3.10 以上
- FRED API Key（已內建預設金鑰，也可自行申請：https://fred.stlouisfed.org/docs/api/api_key.html）

### 2. 安裝相依套件

```bash
pip install -r requirements.txt
```

### 3. 啟動服務

```bash
streamlit run dashboard.py
```

或在 Windows 直接執行：

```cmd
run.cmd
```

啟動後預設使用 `http://localhost:8501`。

若 8501 已被其他程式佔用，Streamlit 才會自動往下一個可用 port 遞增。

停止服務可使用：

```cmd
stop.cmd
```

### 4. 常用啟動選項

```bash
# 指定 port
streamlit run dashboard.py --server.port 8501

# 允許外網存取（預設只允許 localhost）
streamlit run dashboard.py --server.address 0.0.0.0

# 關閉自動開啟瀏覽器
streamlit run dashboard.py --server.headless true
```

---

## Docker 部署

### 1. 建立 Docker Image

專案根目錄已附 `Dockerfile`，直接執行：

```bash
docker build -t macro-dashboard .
```

### 2. 啟動容器

```bash
docker run -d -p 8501:8501 --name macro-dashboard macro-dashboard
```

開啟瀏覽器前往 `http://localhost:8501` 即可使用。

### 3. 常用操作

```bash
# 查看 log
docker logs -f macro-dashboard

# 停止
docker stop macro-dashboard

# 重新啟動
docker start macro-dashboard

# 刪除容器
docker rm -f macro-dashboard

# 重新建置（程式碼更新後）
docker build -t macro-dashboard . && docker rm -f macro-dashboard && docker run -d -p 8501:8501 --name macro-dashboard macro-dashboard
```

### 4. Docker Compose（可選）

如需更方便的管理，可使用 `docker-compose.yml`：

```bash
docker compose up -d        # 啟動
docker compose down          # 停止並移除
docker compose up -d --build # 重新建置後啟動
```

---

## 專案結構

```
├── dashboard.py              # 主頁面（Streamlit UI，A/B/C/D 四看板）
├── data_fetcher.py           # 資料抓取模組（FRED / DBnomics / Yahoo / 各國官方）
├── android_dashboard/        # Android App（Kotlin + Compose，edge-to-edge，四底部頁籤）
│   └── app/src/main/java/com/lance/gaimedashboard/
│       ├── data/ApiClient.kt         # 原生資料抓取層
│       ├── viewmodel/DashboardViewModel.kt
│       └── ui/screens/               # A/B/C/D 四個 Compose Screen
├── app_data/                 # 本地快取 / DB / 暫存 / 匯出 / 設定資料夾
├── requirements.txt          # Python 套件相依
├── Dockerfile                # Docker 映像檔定義
├── docker-compose.yml        # Docker Compose 定義
└── README.md                 # 本文件
```

## Android App 狀態

Android 端採原生 Kotlin + Jetpack Compose 實作，四個看板（需求感測、成本獲利、風險流動、股市比對）與 PC Web UI 完全對齊。

- **四個 Compose 看板**：A（需求）、B（成本）、C（風險）、D（股市比對）
- **edge-to-edge** 設計：`enableEdgeToEdge()` + `SystemBarStyle.dark(TRANSPARENT)`，系統導覽列不遮擋內容
- **WindowInsets 正確處理**：Scaffold `contentWindowInsets`、TopAppBar/NavigationBar 各自消費 insets
- **台灣資料源**：CIER PMI 彈性 URL 解析、CBC M1B/M2 字符集自動偵測（Big5/UTF-8）、台積電營收動態欄位解析
- **新增指標**：韓國出口 YoY、NDC 景氣領先指標、銅價 YoY、HY 信用利差、台幣匯率、S&P500/TAIEX YoY、Fed Funds Rate、10Y-3M 利差、製造業新訂單 YoY
- WebView 備援模式仍保留，可載入 `android_asset/www/index.html`

### Android 建置

```bash
cd android_dashboard
gradlew.bat assembleDebug
```

輸出 APK 位置：`android_dashboard/app/build/outputs/apk/debug/app-debug.apk`

### ADB 安裝

```bash
adb install -r android_dashboard\app\build\outputs\apk\debug\app-debug.apk
```

### 啟動模式說明

1. 預設為 Compose 原生介面（四個底部導覽頁籤）。
2. 若需要 WebView 模式，可由 `MainActivity` 傳入 `use_webview=true` intent extra 啟動。

### 驗證清單

1. 實機確認底部導覽列不遮擋最後一張圖表（edge-to-edge 修正）。
2. 確認 TAIEX、S&P500 YoY、Fed Funds Rate 圖表有資料顯示（Panel D）。
3. 確認 PMI、台灣出口 YoY、中國 PPI、台灣 M1B/M2 最新月份正確顯示。
4. 視需要補 release build 與簽章流程。

## 資料來源

| 來源 | 指標 |
|------|------|
| [FRED](https://fred.stlouisfed.org/) | VIX、殖利率曲線（T10Y2Y, T10Y3M）、M1、零售銷售、PPI、UMCSENT、BUSINV、SP500、DFF、AMTMNO |
| [DBnomics](https://db.nomics.world/) | OECD CLI / ISM 子項歷史資料 |
| [Yahoo Finance](https://finance.yahoo.com/) | TAIEX（^TWII）月收盤、銅期貨（HG=F）|
| [中華經濟研究院](https://www.cier.edu.tw/) | 台灣 PMI（季調）Excel |
| [中國國家統計局](https://www.stats.gov.cn/) | 中國 PMI / PPI 官方口徑 |
| [日本内閣府](https://www5.cao.go.jp/) | 景氣觀測 DI |
| [Eurostat](https://ec.europa.eu/eurostat) | 歐洲工業信心指標 |
| [中華民國財政部](https://web02.mof.gov.tw/) | 台灣出口 YoY |
| [韓國關稅廳](https://unipass.customs.go.kr/) | 韓國出口 YoY |
| [國發會](https://index.ndc.gov.tw/) | 台灣景氣領先指標 |
| [中央銀行](https://www.cbc.gov.tw/) | 台灣 M1B / M2 |
| [台積電 MOPS](https://mops.twse.com.tw/) | 台積電月營收 YoY |
| [ICE BofA via FRED](https://fred.stlouisfed.org/) | HY OAS 信用利差 |
| [TradingEconomics](https://www.tradingeconomics.com/) | 部分最新月份補點 fallback |
