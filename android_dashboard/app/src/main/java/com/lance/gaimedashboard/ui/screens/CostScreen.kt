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

private val infoCli = IndicatorInfo(
    title = "OECD 綜合領先指標 (CLI)",
    summary = "100 為長期趨勢基準，領先 GDP 轉折約 6-9 個月",
    details = """OECD CLI（Composite Leading Indicator）是由 OECD 針對主要經濟體編制的綜合領先指標，整合股市、訂單、信用、産業調查等多個子指標，旨在提前 6-9 個月預測景氣轉折點。

• CLI > 100：景氣高於長期趨勢，擴張動能強
• CLI < 100：景氣低於長期趨勢，放緩訊號
• CLI 持續上升並突破 100：景氣復甦確認
• CLI 見頂後向下：景氣可能在未來 2-3 季觸頂

OECD CLI 透過正規化處理消除季節性影響，提供跨國可比較的景氣循環位置資訊。""",
    source = "OECD / DBnomics OECD MEI LOLITONO",
    investmentNote = "美國 CLI 是全球股市最具指導性的領先指標。CLI 自底部回升通常對應全球股市的中期底部；自高點滑落則是降低股票部位的預警訊號。"
)

private val infoSemiPpi = IndicatorInfo(
    title = "美國半導體 PPI（生產者物價指數）",
    summary = "衡量半導體生産成本與通縮/通脹壓力",
    details = """PCU33443344（NAICS 334413）追蹤美國半導體製造業的生産者物價指數，反映晶片製造的成本趨勢。

• PPI 上升：生産成本增加，可能壓縮製造商利潤或推升終端售價
• PPI 下降：產業處於供給過剩或需求不振，可能引發存貨修正
• 半導體是現代經濟的基礎建材，其 PPI 走勢影響廣泛供應鏈""",
    source = "美國勞工統計局 / FRED PCU33443344",
    investmentNote = "半導體 PPI 下滑時期通常對應記憶體與晶片庫存修正週期；觸底回升是半導體股佈局的參考訊號。"
)

private val infoBusInv = IndicatorInfo(
    title = "美國商業庫存 (BUSINV)",
    summary = "企業庫存變化反映供需平衡與成本壓力",
    details = """商業庫存上升若伴隨銷售放緩，通常代表去庫存壓力增加；庫存下降則代表需求或補庫循環回升。

此指標可搭配零售與 PMI 交叉檢視景氣循環位置。""",
    source = "FRED BUSINV",
    investmentNote = "庫存去化末段常是製造業與科技股重新評價的起點。"
)

private val infoRealRate = IndicatorInfo(
    title = "10 年期美債實質利率",
    summary = "實質利率上升通常壓抑成長股估值",
    details = """實質利率 = 名目利率 (DGS10) - 預期通膨 (T10YIE)。

• 實質利率上升：折現率提高，成長股估值壓力升高
• 實質利率下降：估值壓力緩解，有利風險資產""",
    source = "FRED DGS10 / T10YIE",
    investmentNote = "實質利率見頂回落通常有利科技股與長久期資產修復。"
)

private val infoScissors = IndicatorInfo(
    title = "核心 CPI/PPI 剪刀差",
    summary = "Core CPI YoY - Core PPI YoY，衡量企業定價權",
    details = """剪刀差為核心 CPI 年增率減去核心 PPI 年增率。

• 正值擴大：企業較能轉嫁成本，利潤率相對有撐
• 負值擴大：成本壓力高於終端價格轉嫁能力""",
    source = "FRED CPILFESL / PPIFES",
    investmentNote = "剪刀差回升有利中下游與品牌端毛利率改善。"
)

private val infoChinaPpi = IndicatorInfo(
    title = "中國 PPI 年增率",
    summary = "全球製造業通膨/通縮外溢的重要來源",
    details = """中國工業生產者出廠價格年增率可觀察上游製造成本壓力與全球報價方向。

• PPI > 0：成本通膨壓力升溫
• PPI < 0：工業品通縮與需求偏弱""",
    source = "NBS 官方口徑 / DBnomics 歷史序列 / 最新月份 fallback 補點",
    investmentNote = "中國 PPI 長期負值通常對全球製造鏈報價形成壓力。"
)

private val infoBrent = IndicatorInfo(
    title = "布蘭特原油現貨價格",
    summary = "全球能源成本基準，影響通膨與企業成本",
    details = """布蘭特原油（Brent Crude）是全球能源市場的主要定價基準，佔全球石油交易近 70%。

• 油價上漲：通膨壓力上升，能源類股獲利改善，但製造業成本增加
• 油價下跌：有利降低通膨，但可能反映全球需求疲弱

布蘭特原油深受地緣政治（中東、俄羅斯）與 OPEC+ 減産政策影響，是觀測全球通膨走勢的核心指標之一。""",
    source = "洲際交易所 ICE / FRED DCOILBRENTEU",
    investmentNote = "原油走強通常支撐通膨預期，使央行偏向維持高利率；顯著下跌可能為降息提供空間，有利成長股估值修復。"
)
private val infoCopperYoy = IndicatorInfo(
    title = "銅價年增率 (Copper YoY)",
    summary = "「技術博士」銅價 YoY 領先反映全球工業與軟信需求",
    details = """銅價年增率説明當前銅價相對前一年同期的變化百分比。

• YoY深入正區：工業與建築需求旺盛，對全球制造楫夏會忎通滞別
• YoY轉負：預示全球通銀與圖賣放緩，警惕進入成本拟圧階段

銅/金 比例是常用的風險情緒指標，銅價領先工業需求 2～4 個月。""",
    source = "FRED PCOPPUSDM",
    investmentNote = "銅價 YoY 連續三個月正度可作為工業製造與新能源類股的參考進幚訊號。"
)

private val infoTsmcRevenue = IndicatorInfo(
    title = "台積電月營收年增率",
    summary = "全球最大晶圓代工厂的營收變動，進一步領先半導體景氣",
    details = """台積電月營收年增率採用台證展 MOPS 公告資料，表示香切發帮汉之月相對前一年同期的營收成長百分比。

• YoY > 30％：AI、高效能運算需求爆發，大立廠满穞
• YoY < 0％：消費性電子需求縮退，建議觀望忌追

台積電占全球先進制程（5nm 以下）超過 90％市場份額，營收訊號直按影響全球半導體循環展望。""",
    source = "台證展 MOPS 上市公司月營收公告 (2330)",
    investmentNote = "台積電營收 YoY 提升連續兩個月進入正十％之上，對全球 AI 硬體與 IC設計類股有進一步追漲夺勢參考價值。"
)
@Composable
fun CostScreen(vm: DashboardViewModel) {
    val scroll  = rememberScrollState()
    val chartH  = adaptiveChartHeight()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(0.dp)
    ) {
        SectionTitle("📈", "OECD 綜合領先指標 (CLI)")
        InfoPanel(infoCli)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.cliState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            is LoadState.Success -> {
                CountryCardsRow(s.data, logic = SignalLogic.ThresholdTrend(100f))
                Spacer(Modifier.height(10.dp))
                val filtered = s.data.mapValues { (_, pts) -> pts.withinYears(vm.rangeYears) }
                    .filter { (_, pts) -> pts.isNotEmpty() }
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = filtered.entries.map { (code, pts) ->
                            ChartSeries(
                                label = countryLabels[code] ?: code,
                                color = countryColors[code] ?: OnSurface,
                                data  = pts
                            )
                        },
                        referenceY     = 100f,
                        referenceLabel = "100",
                        modifier = Modifier.fillMaxSize()
                    )
                }
                CountryLegendCost(filtered.keys.toList())
            }
        }

        // ── Copper YoY ─────────────────────────────────────────────────
        SectionTitle("🧪", "銅價年增率 (Copper YoY)")
        InfoPanel(infoCopperYoy)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.copperYoyState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            }
            is LoadState.Success -> {
                val pts = s.data.withinYears(vm.rangeYears)
                SingleValueCard("銅價 YoY", s.data, Amber, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("🧪 銅價 YoY %", Amber, pts, splitFill = true)
                        ),
                        referenceY     = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("📦", "美國商業庫存 (BUSINV)")
        InfoPanel(infoBusInv)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.busInvState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            }
            is LoadState.Success -> {
                SingleValueCard("美國商業庫存", s.data, ColorUS, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("BUSINV", ColorUS, pts, fillArea = true)),
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("💾", "美國半導體 PPI")
        InfoPanel(infoSemiPpi)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.semiPpiState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            }
            is LoadState.Success -> {
                SingleValueCard("半導體 PPI", s.data, PrimaryTeal, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("PCU33443344", PrimaryTeal, pts, fillArea = true)),
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        // ── TSMC Revenue YoY ───────────────────────────────────────
        SectionTitle("🇹🇼", "台積電月營收年增率")
        InfoPanel(infoTsmcRevenue)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.tsmcRevenueState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            is LoadState.Success -> {
                if (s.data.isEmpty()) {
                    androidx.compose.material3.Text(
                        "台積電營收資料程式筆載入中，請稍後再試。",
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        color = OnSurfaceVar,
                    )
                } else {
                    val pts = s.data.withinYears(vm.rangeYears)
                    SingleValueCard("台積電營收 YoY", s.data, PrimaryTeal, SignalLogic.SpreadInversion)
                    Spacer(Modifier.height(8.dp))
                    Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                        MacroLineChart(
                            seriesList = listOf(
                                ChartSeries("🇹🇼 TSMC 營收 YoY %", PrimaryTeal, pts, splitFill = true)
                            ),
                            referenceY     = 0f,
                            referenceLabel = "0%",
                            modifier = Modifier.fillMaxSize()
                        )
                    }
                }
            }
        }

        SectionTitle("📐", "10 年期美債實質利率")
        InfoPanel(infoRealRate)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.realRateState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            }
            is LoadState.Success -> {
                SingleValueCard("美債實質利率", s.data, Danger, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("US 10Y Real Rate", Danger, pts, fillArea = true)),
                        referenceY = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("✂️", "核心 CPI / PPI 剪刀差")
        InfoPanel(infoScissors)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.scissorsState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            }
            is LoadState.Success -> {
                val cpi = s.data["cpi_yoy"].orEmpty().withinYears(vm.rangeYears)
                val ppi = s.data["ppi_yoy"].orEmpty().withinYears(vm.rangeYears)
                val sc = s.data["scissors"].orEmpty().withinYears(vm.rangeYears)

                SingleValueCard("CPI-PPI 剪刀差", s.data["scissors"].orEmpty(), Success, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(
                            ChartSeries("Core CPI YoY", Danger, cpi),
                            ChartSeries("Core PPI YoY", ColorUS, ppi),
                            ChartSeries("Scissors", Success, sc, splitFill = true)
                        ),
                        referenceY = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("🇨🇳", "中國 PPI 年增率")
        InfoPanel(infoChinaPpi)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.chinaPpiState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            is LoadState.Success -> {
                SingleValueCard("中國 PPI YoY", s.data, Danger, SignalLogic.SpreadInversion)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("China PPI YoY", Danger, pts, splitFill = true)),
                        referenceY = 0f,
                        referenceLabel = "0%",
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }

        SectionTitle("🛢", "布蘭特原油現貨 (USD/桶)")
        InfoPanel(infoBrent)
        Spacer(Modifier.height(8.dp))

        when (val s = vm.brentState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> {
                if (vm.fredApiKey.isBlank()) NoApiKeyCard()
                else ErrorCard(s.message, onRetry = { vm.refreshPanelB() })
            }
            is LoadState.Success -> {
                SingleValueCard("布蘭特原油", s.data, Amber, SignalLogic.Plain)
                Spacer(Modifier.height(8.dp))
                val pts = s.data.withinYears(vm.rangeYears)
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(chartH)) {
                    MacroLineChart(
                        seriesList = listOf(ChartSeries("布蘭特 USD/桶", Amber, pts, fillArea = true)),
                        modifier = Modifier.fillMaxSize()
                    )
                }
            }
        }
    }
}

@Composable
private fun CountryLegendCost(codes: List<String>, modifier: Modifier = Modifier) {
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
                androidx.compose.foundation.Canvas(Modifier.size(8.dp)) { drawCircle(color) }
                androidx.compose.material3.Text(label, fontSize = 10.sp, color = OnSurfaceVar)
            }
        }
    }
}
