package com.lance.gaimedashboard.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lance.gaimedashboard.data.LoadState
import com.lance.gaimedashboard.data.withinYears
import com.lance.gaimedashboard.ui.components.*
import com.lance.gaimedashboard.ui.theme.*
import com.lance.gaimedashboard.viewmodel.DashboardViewModel

// ── Indicator descriptions (zh-Hant) ─────────────────────────────────────────

private val infoPmi = IndicatorInfo(
    title = "製造業 PMI 採購經理人指數",
    summary = "50 榮枯分界線，持續 > 50 代表景氣擴張",
    details = """PMI（Purchasing Managers' Index）由採購經理人對新訂單、生產、就業、供應商交貨及庫存五項進行問卷調查後加權計算而成。

• PMI > 50：製造業擴張，景氣好轉
• PMI < 50：製造業收縮，景氣降溫
• PMI = 50：榮枯分界線

台灣 PMI 由中華經濟研究院編制，中國 PMI 為國家統計局數據，美國採 ISM 編制。本儀表板同時呈現日本與歐元區數據以提供全球景氣視角。""",
    source = "ISM / CIER / NBS / 日本內閣府 / Eurostat",
    investmentNote = "PMI 領先 GDP 約 1-2 季。連續 3 個月 > 50 可確認景氣復甦；連續下滑 → 預示需求放緩與企業獲利壓力。"
)

private val infoExport = IndicatorInfo(
    title = "台灣出口年增率 (YoY)",
    summary = "反映全球科技終端需求強弱，正值代表出口成長",
    details = """台灣出口年增率衡量當月出口金額相對前一年同期的變動百分比。

• YoY > 0%：出口擴張，全球終端需求健康
• YoY < 0%：出口萎縮，可能為全球需求放緩或庫存修正

台灣以半導體、電子零組件為主要出口品項，佔全球晶圓代工市場逾六成，是全球科技供應鏈的核心樞紐。""",
    source = "中華民國財政部（主）/ FRED XTEXVA01TWM667S（備援）",
    investmentNote = "台灣出口 YoY 通常領先台股大盤及全球科技股約 1-2 個月。轉正初期是科技股佈局的重要訊號。"
)

private val infoRetail = IndicatorInfo(
    title = "美國零售銷售 (Retail Sales)",
    summary = "反映美國消費端需求強弱，為景氣循環重要先行訊號",
    details = """零售銷售為美國消費支出的高頻觀測指標，通常與就業、薪資與信心同步變化。

• 金額走升：消費動能強勁，企業營收支撐較佳
• YoY 轉負：終端需求轉弱，景氣與獲利壓力提高

本頁同時呈現零售金額與年增率，對齊 Web 端雙視角觀測。""",
    source = "FRED RSAFS",
    investmentNote = "零售 YoY 連續走弱通常領先企業獲利下修；回升初期有利消費與科技類股評價修復。"
)

private val infoSentiment = IndicatorInfo(
    title = "密西根消費者信心指數 (UMCSENT)",
    summary = "衡量美國消費者對經濟前景的信心",
    details = """密西根大學每月調查美國家庭對當前與未來景氣、通膨與就業的看法。

• 指數上升：消費者風險偏好提高，消費意願提升
• 指數下降：消費者趨於保守，未來零售與 GDP 可能放緩

消費佔美國 GDP 近 70%，此指標可作為景氣轉折輔助判讀。""",
    source = "FRED UMCSENT",
    investmentNote = "信心指數回升常早於可選消費板塊基本面改善；連續走弱則需提高防禦配置。"
)
private val infoKoreaExp = IndicatorInfo(
    title = "韓國出口年增率 (Korea Exports YoY)",
    summary = "全球貿易動能與科技需求強弱的早期警報指標",
    details = """韓國出口年增率表示韓國當月全國出口金額相對前一年同期的變化百分比。

• YoY > 0%：全球買氣擴張，尤其半導體、記憶體與車用電子需求強勁
• YoY < 0%：全球製造景氣放緩，對台灣出口形成潛在壓力

韓國三星（記憶體）、SK Hynix（DRAM/HBM）和現代汽車均是韓國出口主力，其出口數據與台灣半導體週期高度正相關。韓國每月 1 日前後公布，比台灣財政部早 2～3 週，是全球電子週期最早的官方高頻訊號。""",
    source = "FRED XTEXVA01KRM664S",
    investmentNote = "韓國出口年增率通常領先台灣出口 1～2 個月，適合作為半導體週期佈局的早期參考指標。"
)

private val infoNdc = IndicatorInfo(
    title = "NDC 台灣景氣領先指標",
    summary = "領先整體經濟轉折約 3～6 個月的台灣官方複合指標",
    details = """國發會台灣景氣領先指標由六項分項指標合成：外銷訂單指數、貨幣總計數變動率、股價指數、工業生產指數、核發建照樓地板面積、製造業存貨量指數，平均領先景氣轉折點約 3～6 個月。

• 指標持續上升：經濟展望改善，預計未來 1～2 季 GDP 加速
• 指標趨緩或下滑：預示景氣放緩，需留意企業獲利壓力
• 指標連續三個月上升：景氣復甦確認訊號

與 OECD CLI 搭配使用可提高台灣景氣轉折的預測準確度。""",
    source = "國家發展委員會 index.ndc.gov.tw",
    investmentNote = "景氣領先指標連續三個月以上上升，可視為布局台股的正面訊號；連續下滑則建議提高防禦配置比重。"
)
// ── Screen ────────────────────────────────────────────────────────────────────

@Composable
fun DemandScreen(vm: DashboardViewModel) {
    val scroll = rememberScrollState()
    val chartH = adaptiveChartHeight()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(0.dp)
    ) {
        // ── PMI ──────────────────────────────────────────────────────────────
        SectionTitle("🏭", "製造業 PMI 採購經理人指數")
        InfoPanel(infoPmi)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.pmiState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelA() })
            is LoadState.Success -> {
                CountryCardsRow(s.data, logic = SignalLogic.ThresholdExpansion(50f))
                Spacer(Modifier.height(10.dp))
                val filteredPmi = s.data.mapValues { (_, pts) -> pts.withinYears(vm.rangeYears) }
                    .filter { (_, pts) -> pts.isNotEmpty() }
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = filteredPmi.entries.map { (code, pts) ->
                            ChartSeries(
                                label = countryLabels[code] ?: code,
                                color = countryColors[code] ?: OnSurface,
                                data  = pts
                            )
                        },
                        referenceY    = 50f,
                        referenceLabel = "50",
                        modifier = Modifier.fillMaxSize()
                    )
                }
                // Colour legend
                CountryLegend(filteredPmi.keys.toList())
            }
        }

        // ── US retail sales ───────────────────────────────────────────────────
        SectionTitle("🛒", "美國零售銷售 (Retail Sales)")
        InfoPanel(infoRetail)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.retailState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelA() })
            is LoadState.Success -> {
                val retailLevel = s.data["level"].orEmpty().withinYears(vm.rangeYears)
                val retailYoY = s.data["yoy"].orEmpty().withinYears(vm.rangeYears)

                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    LatestValueCard(
                        label = "美國零售金額",
                        seriesColor = ColorUS,
                        data = s.data["level"].orEmpty(),
                        logic = SignalLogic.Plain,
                        modifier = Modifier.weight(1f)
                    )
                    LatestValueCard(
                        label = "美國零售 YoY",
                        seriesColor = ColorTW,
                        data = s.data["yoy"].orEmpty(),
                        logic = SignalLogic.SpreadInversion,
                        modifier = Modifier.weight(1f)
                    )
                }

                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    DualAxisBarLineChart(
                        barSeries = retailLevel,
                        lineSeries = retailYoY,
                        barColor = ColorUS,
                        lineColor = ColorTW,
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("😊", "密西根消費者信心指數 (UMCSENT)")
        InfoPanel(infoSentiment)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.sentimentState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelA() })
            is LoadState.Success -> {
                SingleValueCard("消費者信心", s.data, ColorTW, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("UMCSENT", ColorTW, pts, fillArea = true)),
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── Export YoY ────────────────────────────────────────────────────────
        SectionTitle("🚢", "台灣出口年增率 (YoY %)")
        InfoPanel(infoExport)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.exportState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelA() })
            is LoadState.Success -> {
                val pts = s.data.withinYears(vm.rangeYears)
                SingleValueCard("台灣出口 YoY", s.data, ColorTW, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("台灣出口 YoY %", ColorTW, pts, splitFill = true)
                        ),
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── Korea Exports YoY ─────────────────────────────────────
        SectionTitle("🇰🇷", "韓國出口年增率 (Korea Exports YoY)")
        InfoPanel(infoKoreaExp)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.koreaExpState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelA() })
            is LoadState.Success -> {
                val pts = s.data.withinYears(vm.rangeYears)
                SingleValueCard("韓國出口 YoY", s.data, ColorUS, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("🇰🇷 韓國出口 YoY %", ColorUS, pts, splitFill = true)
                        ),
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── NDC Leading Index ────────────────────────────────────
        SectionTitle("📈", "NDC 台灣經濟領先指標")
        InfoPanel(infoNdc)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.ndcLeadingState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelA() })
            is LoadState.Success -> {
                if (s.data.isEmpty()) {
                    androidx.compose.material3.Text(
                        "NDC 領先指標程式筆載入中，請稍後再試。",
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        color = OnSurfaceVar,
                    )
                } else {
                    val pts = s.data.withinYears(vm.rangeYears)
                    SingleValueCard("NDC 領先指標", s.data, ColorTW, SignalLogic.Plain)
                    Spacer(Modifier.height(8.dp))
                    Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                        MacroLineChart(
                            seriesList = listOf(
                                ChartSeries("🇹🇼 NDC 領先指標", ColorTW, pts, fillArea = true)
                            ),
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                }
            }
        }
    }
}

// ── Shared legend row ─────────────────────────────────────────────────────────

@Composable
private fun CountryLegend(codes: List<String>, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp, androidx.compose.ui.Alignment.CenterHorizontally)
    ) {
        codes.forEach { code ->
            val color = countryColors[code] ?: OnSurface
            val label = countryLabels[code] ?: code
            Row(
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
            ) {
                androidx.compose.foundation.Canvas(Modifier.size(8.dp)) {
                    drawCircle(color)
                }
                androidx.compose.material3.Text(label, fontSize = 10.sp, color = OnSurfaceVar)
            }
        }
    }
}

