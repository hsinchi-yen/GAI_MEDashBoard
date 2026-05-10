package com.lance.gaimedashboard.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Fill
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lance.gaimedashboard.data.DataPoint
import com.lance.gaimedashboard.ui.theme.Amber
import com.lance.gaimedashboard.ui.theme.OnSurfaceVar
import com.lance.gaimedashboard.ui.theme.Surface
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Private helper for crosshair tooltip entries – kept outside Canvas lambda for Kotlin 2.0 compat
private data class TipEntry(val label: String, val value: Float, val color: Color)

/** One data series to display on the chart. */
data class ChartSeries(
    val label: String,
    val color: Color,
    val data: List<DataPoint>,
    val visible: Boolean = true,
    /** If true, fill the area below the line (e.g. VIX). */
    val fillArea: Boolean = false,
    /** If true, split fill: green above zero, red below zero (e.g. spread). */
    val splitFill: Boolean = false
)

/**
 * Responsive chart height that scales with screen width.
 * QHD tablets (≥600 dp) get taller charts for better readability.
 */
@Composable
fun adaptiveChartHeight(): Dp {
    val screenWidth = LocalConfiguration.current.screenWidthDp
    return when {
        screenWidth >= 700 -> 300.dp
        screenWidth >= 420 -> 250.dp
        else -> 220.dp
    }
}

/**
 * Interactive multi-series line chart drawn with Compose Canvas.
 *
 * Features:
 * – Multi-series smooth cubic bezier lines
 * – Optional dashed reference/threshold line with label
 * – Optional area fill and split-colour fill (for positive/negative)
 * – Touch crosshair with per-series value tooltip
 * – Subtle grid, left Y-axis labels, bottom X-axis labels
 * – QHD / FHD adaptive height via [adaptiveChartHeight]
 */
@Composable
fun MacroLineChart(
    seriesList: List<ChartSeries>,
    referenceY: Float? = null,
    referenceLabel: String? = null,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()

    // Pre-compute pixel sizes outside the Canvas block
    val padLeft   = with(density) { 50.dp.toPx() }
    val padRight  = with(density) { 12.dp.toPx() }
    val padTop    = with(density) { 10.dp.toPx() }
    val padBottom = with(density) { 32.dp.toPx() }
    val dp1       = with(density) { 1.dp.toPx() }
    val dp2       = with(density) { 2.dp.toPx() }
    val dp3       = with(density) { 3.dp.toPx() }
    val dp6       = with(density) { 6.dp.toPx() }
    val sdf = remember { SimpleDateFormat("yy/MM", Locale.US) }

    var crosshairX by remember { mutableStateOf<Float?>(null) }

    Box(modifier = modifier) {
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .matchParentSize()
                .pointerInput(seriesList) {
                    awaitEachGesture {
                        val down = awaitFirstDown(requireUnconsumed = false)
                        crosshairX = down.position.x
                        var event = awaitPointerEvent()
                        while (event.changes.any { it.pressed }) {
                            crosshairX = event.changes.firstOrNull()?.position?.x
                            event = awaitPointerEvent()
                        }
                        crosshairX = null
                    }
                }
        ) {
            val W = size.width
            val H = size.height
            val cLeft  = padLeft
            val cRight = W - padRight
            val cTop   = padTop
            val cBot   = H - padBottom
            val cW     = cRight - cLeft
            val cH     = cBot - cTop

            val visible = seriesList.filter { it.visible && it.data.isNotEmpty() }
            if (visible.isEmpty()) return@Canvas

            // ── Compute domains ──────────────────────────────────────────────
            val allPts = visible.flatMap { it.data }
            val minT = allPts.minOf { it.timestamp }
            val maxT = allPts.maxOf { it.timestamp }
            val rawMinY = allPts.minOf { it.value }
            val rawMaxY = allPts.maxOf { it.value }
            val refY = referenceY ?: rawMinY
            val domainMinY = minOf(rawMinY, refY) - (rawMaxY - rawMinY) * 0.08f
            val domainMaxY = maxOf(rawMaxY, refY) + (rawMaxY - rawMinY) * 0.08f
            val rangeY = (domainMaxY - domainMinY).coerceAtLeast(0.001f)
            val rangeT = (maxT - minT).coerceAtLeast(1L)

            fun tX(t: Long) = cLeft + (t - minT).toFloat() / rangeT * cW
            fun vY(v: Float) = cTop + (1f - (v - domainMinY) / rangeY) * cH

            // ── Grid lines (horizontal) ──────────────────────────────────────
            val gridCount = 4
            val gridColor = Color(0xFF4DD0CF).copy(alpha = 0.08f)
            for (i in 0..gridCount) {
                val gy = cTop + cH * i / gridCount
                drawLine(gridColor, Offset(cLeft, gy), Offset(cRight, gy), dp1)
            }

            // ── Reference / threshold line (dashed) ──────────────────────────
            if (referenceY != null) {
                val ry = vY(referenceY)
                if (ry in cTop..cBot) {
                    drawLine(
                        color = Amber.copy(alpha = 0.65f),
                        start = Offset(cLeft, ry),
                        end   = Offset(cRight, ry),
                        strokeWidth = dp1 * 1.5f,
                        pathEffect  = PathEffect.dashPathEffect(floatArrayOf(dp6 * 2f, dp6), 0f)
                    )
                    // Reference label (right-aligned)
                    if (referenceLabel != null) {
                        val refStyle = TextStyle(
                            fontSize = 8.sp,
                            color = Amber.copy(alpha = 0.85f),
                            fontWeight = FontWeight.Bold
                        )
                        val refMeasured = textMeasurer.measure(referenceLabel, refStyle)
                        drawText(
                            textMeasurer = textMeasurer,
                            text = referenceLabel,
                            topLeft = Offset(
                                cRight - dp6 * 6f - refMeasured.size.width,
                                ry - refMeasured.size.height - dp1
                            ),
                            style = refStyle
                        )
                    }
                }
            }

            // ── Series ───────────────────────────────────────────────────────
            for (series in visible) {
                val sorted = series.data.sortedBy { it.timestamp }
                if (sorted.size < 2) continue

                // Build smooth cubic bezier path
                val linePath = Path().apply {
                    moveTo(tX(sorted[0].timestamp), vY(sorted[0].value))
                    for (i in 1 until sorted.size) {
                        val x0 = tX(sorted[i - 1].timestamp)
                        val y0 = vY(sorted[i - 1].value)
                        val x1 = tX(sorted[i].timestamp)
                        val y1 = vY(sorted[i].value)
                        val cx = (x0 + x1) / 2f
                        cubicTo(cx, y0, cx, y1, x1, y1)
                    }
                }

                // Area fill options
                if (series.splitFill) {
                    // Positive (above 0)
                    val posPath = Path().apply {
                        val zeroY = vY(0f).coerceIn(cTop, cBot)
                        moveTo(tX(sorted[0].timestamp), zeroY)
                        for (pt in sorted) lineTo(tX(pt.timestamp), vY(pt.value).coerceIn(cTop, zeroY))
                        lineTo(tX(sorted.last().timestamp), zeroY)
                        close()
                    }
                    drawPath(posPath, Color(0xFF34D399).copy(alpha = 0.18f))
                    // Negative (below 0)
                    val negPath = Path().apply {
                        val zeroY = vY(0f).coerceIn(cTop, cBot)
                        moveTo(tX(sorted[0].timestamp), zeroY)
                        for (pt in sorted) lineTo(tX(pt.timestamp), vY(pt.value).coerceIn(zeroY, cBot))
                        lineTo(tX(sorted.last().timestamp), zeroY)
                        close()
                    }
                    drawPath(negPath, Color(0xFFF87171).copy(alpha = 0.18f))
                } else if (series.fillArea) {
                    val areaPath = Path().apply {
                        moveTo(tX(sorted[0].timestamp), cBot)
                        lineTo(tX(sorted[0].timestamp), vY(sorted[0].value))
                        for (i in 1 until sorted.size) {
                            val x0 = tX(sorted[i - 1].timestamp)
                            val y0 = vY(sorted[i - 1].value)
                            val x1 = tX(sorted[i].timestamp)
                            val y1 = vY(sorted[i].value)
                            val cx = (x0 + x1) / 2f
                            cubicTo(cx, y0, cx, y1, x1, y1)
                        }
                        lineTo(tX(sorted.last().timestamp), cBot)
                        close()
                    }
                    drawPath(areaPath, series.color.copy(alpha = 0.15f))
                }

                // Main line
                drawPath(
                    path = linePath,
                    color = series.color,
                    style = Stroke(width = dp2, cap = StrokeCap.Round, join = StrokeJoin.Round)
                )
            }

            // ── Y-axis labels ────────────────────────────────────────────────
            val yStyle = TextStyle(fontSize = 9.sp, color = OnSurfaceVar.copy(alpha = 0.7f))
            for (i in 0..gridCount) {
                val v = domainMinY + rangeY * (gridCount - i) / gridCount
                val gy = cTop + cH * i / gridCount
                val label = when {
                    kotlin.math.abs(v) >= 10000 -> "%.0f".format(v)
                    kotlin.math.abs(v) >= 100   -> "%.0f".format(v)
                    kotlin.math.abs(v) >= 10    -> "%.1f".format(v)
                    else                        -> "%.2f".format(v)
                }
                val yMeasured = textMeasurer.measure(label, yStyle)
                drawText(
                    textMeasurer = textMeasurer,
                    text = label,
                    topLeft = Offset(cLeft - dp6 - yMeasured.size.width, gy - yMeasured.size.height / 2f),
                    style = yStyle
                )
            }

            // ── X-axis labels ────────────────────────────────────────────────
            val xStyle = TextStyle(fontSize = 8.sp, color = OnSurfaceVar.copy(alpha = 0.7f))
            val tickCount = 5
            for (i in 0..tickCount) {
                val t = minT + rangeT * i / tickCount
                val gx = tX(t)
                val xText = sdf.format(Date(t))
                val xMeasured = textMeasurer.measure(xText, xStyle)
                drawText(
                    textMeasurer = textMeasurer,
                    text = xText,
                    topLeft = Offset(gx - xMeasured.size.width / 2f, cBot + dp3),
                    style = xStyle
                )
            }

            // ── Crosshair & tooltip ──────────────────────────────────────────
            val cx = crosshairX
            if (cx != null && cx in cLeft..cRight) {
                val tAtX = minT + ((cx - cLeft) / cW * rangeT).toLong()

                // Vertical line
                drawLine(
                    color = Color.White.copy(alpha = 0.25f),
                    start = Offset(cx, cTop),
                    end   = Offset(cx, cBot),
                    strokeWidth = dp1
                )

                // Collect tooltip data
                    val tipEntries = visible.mapNotNull { series ->
                    val nearest = series.data.minByOrNull { kotlin.math.abs(it.timestamp - tAtX) }
                        ?: return@mapNotNull null
                    // Draw dot on each series line
                    val dotX = tX(nearest.timestamp)
                    val dotY = vY(nearest.value)
                    drawCircle(series.color, radius = dp3, center = Offset(dotX, dotY))
                    drawCircle(Color.Black, radius = dp1, center = Offset(dotX, dotY))
                    TipEntry(series.label, nearest.value, series.color)
                }

                if (tipEntries.isNotEmpty()) {
                    val dateStyle   = TextStyle(fontSize = 8.sp, color = OnSurfaceVar.copy(alpha = 0.9f))
                    val valBaseStyle = TextStyle(fontSize = 9.sp, fontWeight = FontWeight.Bold)
                    val dateMeasured = textMeasurer.measure(sdf.format(Date(tAtX)), dateStyle)
                    val lineH   = dateMeasured.size.height * 2f
                    val tipW    = dp6 * 20f
                    val tipH    = lineH * (tipEntries.size + 1) + dp6 * 2f
                    val tipX    = if (cx > W / 2) cx - tipW - dp6 else cx + dp6 * 1.5f
                    val tipY    = cTop + dp6

                    drawRoundRect(
                        color        = Surface.copy(alpha = 0.93f),
                        topLeft      = Offset(tipX - dp6 * 0.5f, tipY),
                        size         = Size(tipW + dp6, tipH),
                        cornerRadius = CornerRadius(dp6)
                    )
                    drawText(
                        textMeasurer = textMeasurer,
                        text = sdf.format(Date(tAtX)),
                        topLeft = Offset(tipX, tipY + dp3),
                        style = dateStyle
                    )
                    for ((idx, entry) in tipEntries.withIndex()) {
                        val vStr = when {
                            kotlin.math.abs(entry.value) >= 100 -> "%.1f".format(entry.value)
                            else -> "%.2f".format(entry.value)
                        }
                        drawText(
                            textMeasurer = textMeasurer,
                            text = "${entry.label}: $vStr",
                            topLeft = Offset(tipX, tipY + (idx + 1.8f) * lineH),
                            style = valBaseStyle.copy(color = entry.color)
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun DualAxisBarLineChart(
    barSeries: List<DataPoint>,
    lineSeries: List<DataPoint>,
    barColor: Color,
    lineColor: Color,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()
    val padLeft = with(density) { 52.dp.toPx() }
    val padRight = with(density) { 56.dp.toPx() }
    val padTop = with(density) { 10.dp.toPx() }
    val padBottom = with(density) { 32.dp.toPx() }
    val dp1 = with(density) { 1.dp.toPx() }
    val dp2 = with(density) { 2.dp.toPx() }
    val sdf = remember { SimpleDateFormat("yy/MM", Locale.US) }

    Canvas(modifier = modifier.fillMaxWidth()) {
        if (barSeries.isEmpty() || lineSeries.isEmpty()) return@Canvas

        val bars = barSeries.sortedBy { it.timestamp }
        val line = lineSeries.sortedBy { it.timestamp }
        val allTimestamps = (bars.map { it.timestamp } + line.map { it.timestamp }).distinct().sorted()
        if (allTimestamps.isEmpty()) return@Canvas

        val cLeft = padLeft
        val cRight = size.width - padRight
        val cTop = padTop
        val cBottom = size.height - padBottom
        val cWidth = cRight - cLeft
        val cHeight = cBottom - cTop
        val minT = allTimestamps.first()
        val maxT = allTimestamps.last().coerceAtLeast(minT + 1)
        val rangeT = (maxT - minT).coerceAtLeast(1L)

        val leftMin = minOf(0f, line.minOf { it.value })
        val leftMax = maxOf(0f, line.maxOf { it.value })
        val leftPad = ((leftMax - leftMin).takeIf { it > 0f } ?: 1f) * 0.12f
        val leftDomainMin = leftMin - leftPad
        val leftDomainMax = leftMax + leftPad
        val leftRange = (leftDomainMax - leftDomainMin).coerceAtLeast(0.001f)

        val rightMin = 0f
        val rightMax = barSeries.maxOf { it.value }
        val rightPad = (rightMax * 0.08f).coerceAtLeast(1f)
        val rightDomainMax = rightMax + rightPad
        val rightRange = (rightDomainMax - rightMin).coerceAtLeast(0.001f)

        fun tX(t: Long) = cLeft + (t - minT).toFloat() / rangeT * cWidth
        fun leftY(v: Float) = cTop + (1f - (v - leftDomainMin) / leftRange) * cHeight
        fun rightY(v: Float) = cTop + (1f - (v - rightMin) / rightRange) * cHeight

        val gridColor = Color(0xFF4DD0CF).copy(alpha = 0.08f)
        val gridCount = 4
        for (i in 0..gridCount) {
            val y = cTop + cHeight * i / gridCount
            drawLine(gridColor, Offset(cLeft, y), Offset(cRight, y), dp1)
        }

        val zeroY = leftY(0f)
        if (zeroY in cTop..cBottom) {
            drawLine(
                color = Amber.copy(alpha = 0.65f),
                start = Offset(cLeft, zeroY),
                end = Offset(cRight, zeroY),
                strokeWidth = dp1 * 1.5f,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 6f), 0f)
            )
        }

        val xPositions = allTimestamps.map { tX(it) }
        val barWidth = if (xPositions.size >= 2) {
            ((xPositions[1] - xPositions[0]) * 0.6f).coerceAtLeast(6.dp.toPx())
        } else {
            (cWidth * 0.2f).coerceAtMost(28.dp.toPx())
        }

        bars.forEach { point ->
            val x = tX(point.timestamp)
            val top = rightY(point.value)
            drawRect(
                color = barColor.copy(alpha = 0.32f),
                topLeft = Offset(x - barWidth / 2f, top),
                size = Size(barWidth, cBottom - top),
                style = Fill
            )
        }

        if (line.size >= 2) {
            val path = Path().apply {
                moveTo(tX(line[0].timestamp), leftY(line[0].value))
                for (i in 1 until line.size) {
                    val x0 = tX(line[i - 1].timestamp)
                    val y0 = leftY(line[i - 1].value)
                    val x1 = tX(line[i].timestamp)
                    val y1 = leftY(line[i].value)
                    val cx = (x0 + x1) / 2f
                    cubicTo(cx, y0, cx, y1, x1, y1)
                }
            }
            drawPath(path, lineColor, style = Stroke(width = dp2, cap = StrokeCap.Round, join = StrokeJoin.Round))
            line.forEach { point ->
                drawCircle(lineColor, radius = 3.5.dp.toPx(), center = Offset(tX(point.timestamp), leftY(point.value)))
            }
        }

        val leftStyle = TextStyle(fontSize = 9.sp, color = lineColor.copy(alpha = 0.9f), fontWeight = FontWeight.Medium)
        val rightStyle = TextStyle(fontSize = 9.sp, color = barColor.copy(alpha = 0.9f), fontWeight = FontWeight.Medium)
        for (i in 0..gridCount) {
            val leftValue = leftDomainMin + leftRange * (gridCount - i) / gridCount
            val y = cTop + cHeight * i / gridCount
            val leftLabel = String.format(Locale.US, "%.1f%%", leftValue)
            val leftMeasured = textMeasurer.measure(leftLabel, leftStyle)
            drawText(textMeasurer, leftLabel, Offset(cLeft - 8.dp.toPx() - leftMeasured.size.width, y - leftMeasured.size.height / 2f), leftStyle)

            val rightValue = rightMin + rightRange * (gridCount - i) / gridCount
            val rightLabel = when {
                rightValue >= 1_000_000f -> String.format(Locale.US, "%.1fM", rightValue / 1_000_000f)
                rightValue >= 1000f -> String.format(Locale.US, "%.0fK", rightValue / 1000f)
                else -> String.format(Locale.US, "%.0f", rightValue)
            }
            drawText(textMeasurer, rightLabel, Offset(cRight + 8.dp.toPx(), y - leftMeasured.size.height / 2f), rightStyle)
        }

        val xStyle = TextStyle(fontSize = 8.sp, color = OnSurfaceVar.copy(alpha = 0.7f))
        val tickCount = 5
        for (i in 0..tickCount) {
            val t = minT + rangeT * i / tickCount
            val x = tX(t)
            val label = sdf.format(Date(t))
            val measured = textMeasurer.measure(label, xStyle)
            drawText(textMeasurer, label, Offset(x - measured.size.width / 2f, cBottom + 3.dp.toPx()), xStyle)
        }
    }
}
