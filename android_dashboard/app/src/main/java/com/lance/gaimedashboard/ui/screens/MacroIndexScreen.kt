package com.lance.gaimedashboard.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lance.gaimedashboard.data.LoadState
import com.lance.gaimedashboard.data.MacroIndexResult
import com.lance.gaimedashboard.data.MacroSignal
import com.lance.gaimedashboard.data.withinYears
import com.lance.gaimedashboard.ui.components.ChartSeries
import com.lance.gaimedashboard.ui.components.ErrorCard
import com.lance.gaimedashboard.ui.components.LoadingCard
import com.lance.gaimedashboard.ui.components.MacroLineChart
import com.lance.gaimedashboard.ui.components.SectionTitle
import com.lance.gaimedashboard.ui.components.adaptiveChartHeight
import com.lance.gaimedashboard.ui.theme.Amber
import com.lance.gaimedashboard.ui.theme.Background
import com.lance.gaimedashboard.ui.theme.Danger
import com.lance.gaimedashboard.ui.theme.OnSurface
import com.lance.gaimedashboard.ui.theme.OnSurfaceVar
import com.lance.gaimedashboard.ui.theme.PrimaryTeal
import com.lance.gaimedashboard.ui.theme.Success
import com.lance.gaimedashboard.ui.theme.Surface
import com.lance.gaimedashboard.ui.theme.SurfaceBright
import com.lance.gaimedashboard.ui.theme.SurfaceVariant
import com.lance.gaimedashboard.viewmodel.DashboardViewModel

private val groupLabels = linkedMapOf(
    "A" to "A｜需求與領先活動",
    "B" to "B｜貿易與同時流量",
    "C" to "C｜成本、流動性、金融條件",
    "D" to "D｜市場內部與部位",
)

@Composable
fun MacroIndexScreen(vm: DashboardViewModel) {
    val scroll = rememberScrollState()
    val chartH = adaptiveChartHeight()
    val result = vm.currentMacroIndex()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(0.dp)
    ) {
        SectionTitle("🌐", "Global Macro Index")
        Text(
            text = "20 指標二元擴散評分，整合需求、貿易、金融條件與市場內部輪動。",
            color = OnSurfaceVar,
            fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 16.dp)
        )
        Spacer(Modifier.height(10.dp))

        MacroSummary(result = result)
        Spacer(Modifier.height(12.dp))

        groupLabels.forEach { (group, label) ->
            MacroSignalGroup(
                label = label,
                signals = result.signals.filter { it.group == group },
                scoreText = "${result.groupScores[group]?.capped ?: 0}/5"
            )
            Spacer(Modifier.height(10.dp))
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            MacroSignalListCard(
                title = "正向驅動",
                signals = result.topDrivers,
                accent = Success,
                modifier = Modifier.weight(1f)
            )
            MacroSignalListCard(
                title = "拖累因子",
                signals = result.topDrags,
                accent = Danger,
                modifier = Modifier.weight(1f)
            )
        }

        Spacer(Modifier.height(12.dp))
        SectionTitle("🔄", "內部輪動與 13F 代理")
        Spacer(Modifier.height(8.dp))

        when (val s = vm.sectorRotationState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelE() })
            is LoadState.Success -> {
                MetricChartCard(
                    title = "內部輪動指數",
                    subtitle = "景氣循環籃子相對防禦籃子 > 0 代表 Risk-On",
                    metricLabel = if ((s.data.lastOrNull()?.value ?: 0f) > 0f) "Risk-On" else "Risk-Off",
                    metricValue = s.data.lastOrNull()?.value,
                    series = s.data.withinYears(vm.rangeYears),
                    color = PrimaryTeal,
                    splitFill = true,
                    chartH = chartH,
                )
            }
        }

        when (val s = vm.thirteenFProxyState) {
            LoadState.Idle, LoadState.Loading -> LoadingCard()
            is LoadState.Error -> ErrorCard(s.message, onRetry = { vm.refreshPanelE() })
            is LoadState.Success -> {
                MetricChartCard(
                    title = "13F 持股偏好指數（代理）",
                    subtitle = "循環 ETF vs 防禦 ETF 量能加速度差值，正值代表機構偏向 cyclical",
                    metricLabel = if ((s.data.lastOrNull()?.value ?: 0f) > 0f) "偏向循環" else "偏向防禦",
                    metricValue = s.data.lastOrNull()?.value,
                    series = s.data.withinYears(vm.rangeYears),
                    color = Amber,
                    splitFill = true,
                    chartH = chartH,
                )
            }
        }
    }
}

@Composable
private fun MacroSummary(result: MacroIndexResult) {
    Column(modifier = Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SummaryCard(
                title = result.regimeLabel,
                subtitle = "景氣燈號",
                accent = regimeAccent(result.regime),
                modifier = Modifier.weight(1.2f)
            )
            SummaryCard(
                title = "${result.score} / 20",
                subtitle = "GMI 分數",
                accent = PrimaryTeal,
                modifier = Modifier.weight(1f)
            )
            SummaryCard(
                title = "%.1f%%".format(result.diffusion),
                subtitle = "擴散比例",
                accent = Amber,
                modifier = Modifier.weight(1f)
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SummaryCard(
                title = if (result.confidence == "normal") "正常" else "低信心",
                subtitle = "信心等級",
                accent = if (result.confidence == "normal") Success else Amber,
                modifier = Modifier.weight(1f)
            )
            SummaryCard(
                title = "${result.validCount} / 20",
                subtitle = "有效指標",
                accent = SurfaceBright,
                modifier = Modifier.weight(1f)
            )
        }
    }
}

@Composable
private fun SummaryCard(title: String, subtitle: String, accent: Color, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(SurfaceVariant)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        Box(
            modifier = Modifier
                .height(4.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(999.dp))
                .background(accent)
        )
        Text(text = title, color = OnSurface, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text(text = subtitle, color = OnSurfaceVar, fontSize = 11.sp)
    }
}

@Composable
private fun MacroSignalGroup(label: String, signals: List<MacroSignal>, scoreText: String) {
    Column(modifier = Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(label, color = OnSurface, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            Text(scoreText, color = PrimaryTeal, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        }
        signals.chunked(2).forEach { rowSignals ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                rowSignals.forEach { signal ->
                    SignalCell(signal = signal, modifier = Modifier.weight(1f))
                }
                if (rowSignals.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun SignalCell(signal: MacroSignal, modifier: Modifier = Modifier) {
    val accent = if (signal.score == 1) Success else Danger
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(Surface)
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(if (signal.score == 1) "🟢" else "🔴", fontSize = 18.sp)
        Text(text = "#${signal.id} ${signal.name}", color = OnSurface, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
        Text(text = signal.raw, color = accent, fontSize = 11.sp)
        Text(text = signal.rule, color = OnSurfaceVar, fontSize = 10.sp, lineHeight = 12.sp)
    }
}

@Composable
private fun MacroSignalListCard(
    title: String,
    signals: List<MacroSignal>,
    accent: Color,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .clip(RoundedCornerShape(14.dp))
            .background(SurfaceVariant)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(text = title, color = accent, fontWeight = FontWeight.Bold)
        if (signals.isEmpty()) {
            Text("目前無資料", color = OnSurfaceVar, fontSize = 12.sp)
        } else {
            signals.forEach { signal ->
                Text("#${signal.id} ${signal.name}", color = OnSurface, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                Text(signal.raw, color = accent, fontSize = 11.sp)
                Text(signal.rule, color = OnSurfaceVar, fontSize = 10.sp)
                if (signal != signals.last()) Spacer(Modifier.height(4.dp))
            }
        }
    }
}

@Composable
private fun MetricChartCard(
    title: String,
    subtitle: String,
    metricLabel: String,
    metricValue: Float?,
    series: List<com.lance.gaimedashboard.data.DataPoint>,
    color: Color,
    splitFill: Boolean,
    chartH: androidx.compose.ui.unit.Dp,
) {
    Column(modifier = Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(title, color = OnSurface, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 4.dp))
        Text(subtitle, color = OnSurfaceVar, fontSize = 11.sp)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(SurfaceVariant)
                .padding(12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(metricLabel, color = color, fontWeight = FontWeight.Bold)
            Text(metricValue?.let { "%+.3f".format(it) } ?: "—", color = OnSurface, fontWeight = FontWeight.SemiBold)
        }
        Box(Modifier.fillMaxWidth().height(chartH).padding(bottom = 6.dp)) {
            MacroLineChart(
                seriesList = listOf(ChartSeries(title, color, series, splitFill = splitFill)),
                referenceY = 0f,
                referenceLabel = "0%",
                modifier = Modifier.fillMaxSize()
            )
        }
    }
}

private fun regimeAccent(regime: String): Color = when (regime) {
    "green" -> Success
    "yellow" -> Amber
    "red" -> Danger
    else -> OnSurfaceVar
}