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

private val infoVix = IndicatorInfo(
    title = "VIX 恐慌指數（CBOE 波動率指數）",
    summary = "市場恐懼程度的即時溫度計，< 20 為相對平靜",
    details = """VIX（Volatility Index）由 CBOE 根據 S&P 500 指數期權的隱含波動率計算，反映市場對未來 30 天股市波動的預期。

• VIX < 15：市場極度平靜，可能存在自滿情緒
• VIX 15–20：正常市場波動範圍
• VIX 20–30：市場出現顯著不確定性
• VIX > 30：市場恐慌，通常伴隨急跌或系統性風險
• VIX > 40：極端恐慌（如金融危機、疫情衝擊）

VIX 與股市走勢高度負相關，也稱為「恐懼指數」。""",
    source = "CBOE / FRED VIXCLS（每日資料按月末取值）",
    investmentNote = "VIX 飆升至 30 以上伴隨股市急跌時，歷史經驗顯示通常是中長期佈局機會；VIX 長期維持低位則需警惕市場自滿所帶來的下行風險。"
)

private val infoSpread = IndicatorInfo(
    title = "美債 10Y-2Y 殖利率利差",
    summary = "倒掛（< 0）是經濟衰退的前置警訊",
    details = """10 年期美債殖利率減去 2 年期美債殖利率，反映長短端利率差異。

• 利差 > 0（正常）：殖利率曲線正斜率，長債利率高於短債，反映市場對未來成長與通膨的正常預期
• 利差 = 0（平坦）：殖利率曲線趨平，市場對經濟前景不確定
• 利差 < 0（倒掛）：殖利率曲線倒掛，歷史上每次美國衰退前均出現此現象

自 1960 年代以來，每次 10Y-2Y 利差轉負後的 6-24 個月內均發生衰退（以 NBER 定義）。""",
    source = "美國財政部 / FRED T10Y2Y（每日按月末取值）",
    investmentNote = "利差轉負後通常需要 6-18 個月才發生衰退，但倒掛訊號出現後應逐步降低高 Beta 資產曝險。利差重新翻正後的擴張初期是進場重要視窗。"
)

private val infoMoney = IndicatorInfo(
    title = "台灣 M1B / M2 與美國 M1 年增率",
    summary = "流動性強弱與股市風險偏好的關鍵領先指標",
    details = """M1B 反映民間高流動資金，M2 反映廣義貨幣。M1B 與 M2 的交叉常用於判斷資金風險偏好變化。

• M1B YoY 上升：風險偏好升溫
• M1B YoY > M2 YoY（黃金交叉）：資金偏向活存與風險資產
• M1B YoY < M2 YoY（死亡交叉）：資金轉向保守配置

同時呈現美國 M1 YoY，作為全球流動性對照。""",
    source = "中央銀行金融統計月報（台灣）/ FRED M1SL（美國）",
    investmentNote = "當流動性同步轉強時，風險資產估值通常受支撐；流動性走弱期則需提高防禦權重。"
)
private val infoHySpread = IndicatorInfo(
    title = "HY 高收益債信用利差 (OAS)",
    summary = "信用市場壓力計，400 bps 為警戒，600 bps 為極端恐慌標誌",
    details = """ICE BofA 高收益債選擇調整利差（OAS）衡量高收益債券相對無風險利率的額外報酬，直接反映市場對企業債務違約風險的預期。

• OAS 200–400 bps：正常市場環境，信用風險受控
• OAS 400–600 bps：信用市場壓力升高，需留意風險資產
• OAS > 600 bps：市場恐慌、流動性緊縮，歷史上對應金融危機或經濟衰退

HY 利差擴大通常領先 VIX 飆升 2～6 週，是信用市場壓力的最早預警訊號。""",
    source = "ICE BofA / FRED BAMLH0A0HYM2",
    investmentNote = "HY 利差驟然回落是風險資產的正面訊號；超過 400 bps 時應減低高收益債與高 Beta 股票的曝險比重。"
)

private val infoTwdUsd = IndicatorInfo(
    title = "台幣匯率 TWD/USD",
    summary = "台幣升值 = 外資淨流入，是觀察台股走勢的輔助參考",
    details = """台幣對美元匯率（TWD/USD）數值下降代表台幣升值，即同樣金額的美元能換到更多台幣。

• 台幣升值（數值下降）：外資淨流入台灣，購買台股與債券，並將外幣兌換成台幣，屬強勢訊號
• 台幣貶值（數值上升）：外資撤離或全球風險偏好惡化，需警惕市場風險

台幣劇烈貶值常出現於全球資金大幅外流或地緣政治緊張時期；平穩升值則通常伴隨外資積極加碼台股。""",
    source = "FRED DEXTAUS",
    investmentNote = "台幣平穩升值是台股多頭格局的重要佐證；若台幣急貶與外資大量賣超同步出現，應提高防禦性配置比重。"
)
@Composable
fun RiskScreen(vm: DashboardViewModel) {
    val scroll = rememberScrollState()
    val chartH = adaptiveChartHeight()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(0.dp)
    ) {
        SectionTitle("⚡", "VIX 恐慌指數")
        InfoPanel(infoVix)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.vixState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelC() })
            }
            is LoadState.Success -> {
                SingleValueCard("VIX 恐慌指數", s.data, Danger, SignalLogic.VixBands(20f, 30f))
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList     = listOf(ChartSeries("VIX", Danger, pts, fillArea = true)),
                        referenceY     = 20f,
                        referenceLabel = "20",
                        modifier       = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("📉", "美債 10Y-2Y 殖利率利差")
        InfoPanel(infoSpread)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.spreadState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelC() })
            }
            is LoadState.Success -> {
                SingleValueCard("10Y-2Y 利差", s.data, ColorUS, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("10Y-2Y Spread", ColorUS, pts, splitFill = true)
                        ),
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier       = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── HY Spread ─────────────────────────────────────────────────
        SectionTitle("💳", "HY 高收益債信用利差 (OAS)")
        InfoPanel(infoHySpread)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.hySpreadState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelC() })
            }
            is LoadState.Success -> {
                val pts = s.data.withinYears(vm.rangeYears)
                SingleValueCard("HY OAS", s.data, Danger, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("HY OAS (bps)", Danger, pts, fillArea = true)
                        ),
                        referenceY     = 400f,
                        referenceLabel = "400",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("💰", "台灣 M1B / M2 與美國 M1 年增率 (YoY %)")
        InfoPanel(infoMoney)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.moneyState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelC() })
            }
            is LoadState.Success -> {
                val moneyLabels = mapOf(
                    "tw_m1b" to "🇹🇼 M1B",
                    "tw_m2" to "🇹🇼 M2",
                    "us_m1" to "🇺🇸 M1"
                )
                val moneyColors = mapOf(
                    "tw_m1b" to ColorTW,
                    "tw_m2" to ColorJP,
                    "us_m1" to ColorUS
                )
                val moneyOrder = listOf("tw_m1b", "tw_m2", "us_m1")
                val filtered = s.data.mapValues { (_, pts) -> pts.withinYears(vm.rangeYears) }
                    .filter { (_, pts) -> pts.isNotEmpty() }

                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    filtered.entries
                        .sortedBy { moneyOrder.indexOf(it.key).let { idx -> if (idx == -1) Int.MAX_VALUE else idx } }
                        .forEach { (code, _) ->
                            LatestValueCard(
                                label = moneyLabels[code] ?: code,
                                seriesColor = moneyColors[code] ?: OnSurface,
                                data = s.data[code] ?: emptyList(),
                                logic = SignalLogic.ThresholdExpansion(0f),
                                modifier = Modifier.weight(1f)
                            )
                        }
                }
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = filtered.entries
                            .sortedBy { moneyOrder.indexOf(it.key).let { idx -> if (idx == -1) Int.MAX_VALUE else idx } }
                            .map { (code, pts) ->
                                ChartSeries(
                                    label = moneyLabels[code] ?: code,
                                    color = moneyColors[code] ?: OnSurface,
                                    data = pts
                                )
                            },
                        referenceY = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── TWD/USD ───────────────────────────────────────────────────
        SectionTitle("🇹🇼", "台幣匯率 TWD/USD")
        InfoPanel(infoTwdUsd)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.twdUsdState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelC() })
            }
            is LoadState.Success -> {
                val pts = s.data.withinYears(vm.rangeYears)
                SingleValueCard("台幣 TWD/USD", s.data, ColorTW, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("🇹🇼 TWD/USD", ColorTW, pts, fillArea = true)
                        ),
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }
    }
}
