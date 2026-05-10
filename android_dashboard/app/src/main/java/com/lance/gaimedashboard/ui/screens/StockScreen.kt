package com.lance.gaimedashboard.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.lance.gaimedashboard.data.LoadState
import com.lance.gaimedashboard.data.withinYears
import com.lance.gaimedashboard.ui.components.*
import com.lance.gaimedashboard.ui.theme.*
import com.lance.gaimedashboard.viewmodel.DashboardViewModel

// ── Indicator descriptions ────────────────────────────────────────────────────

private val infoSp500 = IndicatorInfo(
    title = "S&P 500 年增率 (YoY %)",
    summary = "美國大盤年增率，反映美股整體多空動能",
    details = """S&P 500 月收年增率衡量當月指數相對前一年同期的漲跌幅。

• YoY > 0%：美股年線上漲，多頭動能持續
• YoY < 0%：美股年線下跌，需評估基本面支撐

S&P 500 包含美國 500 家最大上市公司，是全球最重要的股票市場基準指數。
台積電 ADR（TSM）與半導體類股同步影響，是台灣投資人觀察美股的重要基準。""",
    source = "FRED SP500（月收）",
    investmentNote = "S&P 500 年增率轉正初期通常是科技股與台積電 ADR 重新佈局的關鍵視窗。"
)

private val infoTaiex = IndicatorInfo(
    title = "台灣加權指數 TAIEX 年增率 (YoY %)",
    summary = "台股大盤年增率，反映台灣股市整體動能",
    details = """台灣加權股價指數（TAIEX）月收年增率衡量當月指數相對前一年同期的漲跌幅。

• YoY > 0%：台股年線上漲，市場信心較佳
• YoY < 0%：台股年線下跌，需搭配其他指標評估底部

台積電佔台股加權指數逾三成，使 TAIEX 高度反映全球半導體需求週期。
台幣升值（外資淨流入）通常是 TAIEX 走強的重要支撐。""",
    source = "Yahoo Finance ^TWII（月收）",
    investmentNote = "TAIEX 與 S&P 500 背離時，通常反映匯率效應或特定產業輪動，可搭配 TWD/USD 研判資金流向。"
)

private val infoFedFunds = IndicatorInfo(
    title = "聯準會有效聯邦基金利率 (DFF)",
    summary = "美國貨幣政策寬緊的核心基準，直接影響股市估值",
    details = """聯邦基金有效利率（DFF）是美國銀行間隔夜拆款的實際利率，由聯準會 FOMC 決議目標區間後由市場形成。

• 利率上升（升息）：折現率提高，壓縮成長股估值；企業借貸成本上升
• 利率下降（降息）：估值壓力緩解，有利風險資產反彈；流動性環境改善
• 利率見頂並下滑：歷史上通常伴隨股市的中長期底部

Fed Funds Rate 是所有資產定價的基礎利率，對台股 ETF 與外資配置影響深遠。""",
    source = "FRED DFF（日頻月均）",
    investmentNote = "降息週期啟動後的 6～18 個月，通常是科技股與台股的強勢擴張期。升息末段（最後一次升息）是評估長線佈局的重要時機。"
)

private val infoT10y3m = IndicatorInfo(
    title = "美債 10Y-3M 殖利率利差",
    summary = "比 10Y-2Y 更敏感的衰退領先指標",
    details = """10 年期美債殖利率減去 3 個月美債殖利率。

• 利差 > 0：正常利率結構，長債利率高於短債
• 利差 < 0（倒掛）：歷史上幾乎每次衰退前均出現；倒掛時間越長越嚴重
• 倒掛後轉正：是景氣衰退即將開始的最強訊號，通常比實際衰退早 3～6 個月

10Y-3M 利差比 10Y-2Y 更早觸及負值（因 3 個月端更快反映 Fed 升息預期），是更敏感的衰退領先指標。""",
    source = "FRED T10Y3M",
    investmentNote = "10Y-3M 倒掛持續超過 3 個月是降低股票曝險的預警訊號；倒掛解除後的首次衰退確認通常是反彈買點。"
)

private val infoNewOrders = IndicatorInfo(
    title = "美國製造業新訂單 YoY (AMTMNO)",
    summary = "製造業需求端前端訊號，領先工業股約 1～2 季",
    details = """美國人口普查局每月公布的製造業新接訂單額年增率，包含耐久財與非耐久財。

• YoY > 0%：製造業需求擴張，工業與科技補庫存週期啟動
• YoY < 0%：製造業訂單萎縮，去庫存壓力或需求疲軟

新訂單領先工業生產約 1～2 個月，是追蹤全球製造業週期位置的重要指標。
台灣以電子與半導體為出口主力，與美國製造業新訂單高度正相關。""",
    source = "FRED AMTMNO",
    investmentNote = "製造業新訂單 YoY 連續轉正是佈局工業股與半導體設備股的早期訊號。"
)

// ── Screen ────────────────────────────────────────────────────────────────────

@Composable
fun StockScreen(vm: DashboardViewModel) {
    val scroll = rememberScrollState()
    val chartH = adaptiveChartHeight()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(0.dp)
    ) {
        // ── S&P 500 vs TAIEX YoY 疊加圖 ─────────────────────────────────────
        SectionTitle("📊", "S&P 500 vs TAIEX 年增率比對")
        InfoPanel(infoSp500)
        InfoPanel(infoTaiex)
        Spacer(Modifier.height(8.dp))

        val sp500Series = when (val s = vm.sp500YoyState) {
            is LoadState.Success -> s.data.withinYears(vm.rangeYears)
            else -> emptyList()
        }
        val taiexSeries = when (val s = vm.taiexYoyState) {
            is LoadState.Success -> s.data.withinYears(vm.rangeYears)
            else -> emptyList()
        }

        // KPI 卡片：S&P500 + TAIEX 並排
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            LatestValueCard(
                label       = "🇺🇸 S&P500 YoY",
                seriesColor = ColorUS,
                data        = when (val s = vm.sp500YoyState) { is LoadState.Success -> s.data; else -> emptyList() },
                logic       = SignalLogic.SpreadInversion,
                modifier    = Modifier.weight(1f)
            )
            LatestValueCard(
                label       = "🇹🇼 TAIEX YoY",
                seriesColor = ColorTW,
                data        = when (val s = vm.taiexYoyState) { is LoadState.Success -> s.data; else -> emptyList() },
                logic       = SignalLogic.SpreadInversion,
                modifier    = Modifier.weight(1f)
            )
        }
        Spacer(Modifier.height(8.dp))

        // 雙線疊加圖
        when {
            vm.sp500YoyState is LoadState.Loading || vm.taiexYoyState is LoadState.Loading -> LoadingCard()
            sp500Series.isEmpty() && taiexSeries.isEmpty() -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard("股市資料暫時無法取得", onRetry = { vm.refreshPanelD() })
            }
            else -> {
                val seriesList = buildList {
                    if (sp500Series.isNotEmpty()) add(ChartSeries("🇺🇸 S&P500 YoY %", ColorUS, sp500Series))
                    if (taiexSeries.isNotEmpty()) add(ChartSeries("🇹🇼 TAIEX YoY %", ColorTW, taiexSeries))
                }
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList     = seriesList,
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier       = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── Fed Funds Rate ────────────────────────────────────────────────────
        SectionTitle("🏦", "聯準會基準利率 (Fed Funds Rate)")
        InfoPanel(infoFedFunds)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.fedFundsState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelD() })
            }
            is LoadState.Success -> {
                SingleValueCard("Fed Funds Rate", s.data, ColorUS, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("🇺🇸 Fed Funds Rate %", ColorUS, pts, fillArea = true)),
                        modifier   = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── 10Y-3M 利差 ───────────────────────────────────────────────────────
        SectionTitle("📉", "美債 10Y-3M 利差（衰退領先）")
        InfoPanel(infoT10y3m)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.t10y3mState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelD() })
            }
            is LoadState.Success -> {
                SingleValueCard("10Y-3M 利差", s.data, ColorUS, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList     = listOf(ChartSeries("10Y-3M Spread", ColorUS, pts, splitFill = true)),
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier       = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── 美國製造業新訂單 YoY ──────────────────────────────────────────────
        SectionTitle("🏗️", "美國製造業新訂單 YoY")
        InfoPanel(infoNewOrders)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.usNewOrdersYoyState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelD() })
            }
            is LoadState.Success -> {
                SingleValueCard("新訂單 YoY", s.data, ColorUS, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList     = listOf(ChartSeries("🇺🇸 New Orders YoY %", ColorUS, pts, splitFill = true)),
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier       = Modifier.fillMaxSize()
                    )
                }
            }
        }
    }
}
