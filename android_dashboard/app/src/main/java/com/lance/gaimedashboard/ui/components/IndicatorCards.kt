package com.lance.gaimedashboard.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lance.gaimedashboard.data.DataPoint
import com.lance.gaimedashboard.ui.theme.*

/** Signal category used to colour-code the status badge. */
sealed interface SignalLogic {
    /** PMI/DI style: > [threshold] is expansion, < is contraction. */
    data class ThresholdExpansion(val threshold: Float = 50f) : SignalLogic
    /** CLI style: > [threshold] is above-trend, < is below-trend. */
    data class ThresholdTrend(val threshold: Float = 100f) : SignalLogic
    /** VIX style: < low is calm, > high is risk-off. */
    data class VixBands(val low: Float = 20f, val high: Float = 30f) : SignalLogic
    /** Spread style: positive = normal, negative = inverted. */
    data object SpreadInversion : SignalLogic
    /** Plain display—no signal colour logic applied. */
    data object Plain : SignalLogic
}

private fun computeSignal(value: Float, logic: SignalLogic): Triple<String, Color, Color> {
    return when (logic) {
        is SignalLogic.ThresholdExpansion -> when {
            value > logic.threshold + 1f  -> Triple("擴張", Color(0xFF1A3A2A), Success)
            value < logic.threshold - 1f  -> Triple("收縮", Color(0xFF3A1A1A), Danger)
            else                          -> Triple("中性", Color(0xFF2A2A1A), Amber)
        }
        is SignalLogic.ThresholdTrend -> when {
            value > logic.threshold -> Triple("高於趨勢", Color(0xFF1A3A2A), Success)
            else                    -> Triple("低於趨勢", Color(0xFF3A1A1A), Danger)
        }
        is SignalLogic.VixBands -> when {
            value < logic.low   -> Triple("低波動", Color(0xFF1A3A2A), Success)
            value > logic.high  -> Triple("高風險", Color(0xFF3A1A1A), Danger)
            else                -> Triple("中等", Color(0xFF2A2A1A), Amber)
        }
        SignalLogic.SpreadInversion -> when {
            value > 0f  -> Triple("正常", Color(0xFF1A3A2A), Success)
            value < 0f  -> Triple("倒掛", Color(0xFF3A1A1A), Danger)
            else        -> Triple("平坦", Color(0xFF2A2A1A), Amber)
        }
        SignalLogic.Plain -> Triple("", Color.Transparent, Color.Transparent)
    }
}

/**
 * A single compact value card showing the latest data point for one series.
 */
@Composable
fun LatestValueCard(
    label: String,
    seriesColor: Color,
    data: List<DataPoint>,
    logic: SignalLogic = SignalLogic.Plain,
    modifier: Modifier = Modifier
) {
    val latest = data.maxByOrNull { it.timestamp }
    val previous = data.sortedBy { it.timestamp }.let { sorted ->
        if (sorted.size >= 2) sorted[sorted.size - 2] else null
    }
    val change = if (latest != null && previous != null) latest.value - previous.value else null
    val changeStr = change?.let { if (it >= 0f) "+%.2f".format(it) else "%.2f".format(it) }
    val changeColor = when {
        change == null -> OnSurfaceVar
        change > 0f   -> Success
        change < 0f   -> Danger
        else          -> OnSurfaceVar
    }
    val (statusText, statusBg, statusFg) = if (latest != null) computeSignal(latest.value, logic)
    else Triple("", Color.Transparent, Color.Transparent)

    Column(
        modifier = modifier
            .width(110.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(SurfaceVariant)
            .padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        // Label row with colour dot
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Box(
                Modifier
                    .size(8.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(seriesColor)
            )
            Text(label, fontSize = 11.sp, color = OnSurfaceVar, maxLines = 1)
        }
        // Value
        Text(
            text = latest?.let {
                if (kotlin.math.abs(it.value) >= 1000f) "%.0f".format(it.value)
                else "%.2f".format(it.value)
            } ?: "—",
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
            color = seriesColor
        )
        // Change vs prior month
        Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
            if (changeStr != null) {
                Text(changeStr, fontSize = 10.sp, color = changeColor, fontWeight = FontWeight.Medium)
            }
            if (statusText.isNotEmpty()) {
                Box(
                    Modifier
                        .clip(RoundedCornerShape(4.dp))
                        .background(statusBg)
                        .padding(horizontal = 4.dp, vertical = 1.dp)
                ) {
                    Text(statusText, fontSize = 9.sp, color = statusFg, fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

/**
 * Horizontal scrolling row of [LatestValueCard]s for a multi-country indicator.
 */
@Composable
fun CountryCardsRow(
    data: Map<String, List<DataPoint>>,
    logic: SignalLogic = SignalLogic.Plain,
    modifier: Modifier = Modifier
) {
    LazyRow(
        modifier = modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 0.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(data.entries.toList()) { (code, pts) ->
            val color = countryColors[code] ?: OnSurface
            val label = countryLabels[code] ?: code
            LatestValueCard(label = label, seriesColor = color, data = pts, logic = logic)
        }
    }
}

/**
 * Single-series latest value card row (1 card, full-width style).
 */
@Composable
fun SingleValueCard(
    label: String,
    data: List<DataPoint>,
    seriesColor: Color,
    logic: SignalLogic = SignalLogic.Plain,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        LatestValueCard(label, seriesColor, data, logic, modifier = Modifier.weight(1f))
    }
}
