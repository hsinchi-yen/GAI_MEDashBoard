package com.lance.gaimedashboard.data

data class MacroSignal(
    val group: String,
    val id: Int,
    val name: String,
    val score: Int,
    val raw: String,
    val rule: String,
)

data class MacroGroupScore(
    val raw: Int,
    val capped: Int,
)

data class MacroIndexResult(
    val score: Int,
    val diffusion: Float,
    val regime: String,
    val regimeLabel: String,
    val confidence: String,
    val validCount: Int,
    val signals: List<MacroSignal>,
    val groupScores: Map<String, MacroGroupScore>,
    val topDrivers: List<MacroSignal>,
    val topDrags: List<MacroSignal>,
)

object MacroIndexEngine {
    private const val REGIME_GREEN = 15
    private const val REGIME_RED = 9
    private const val MIN_VALID = 16
    private const val GROUP_CAP = 5

    private val regimeLabels = mapOf(
        "green" to "🟢 擴張",
        "yellow" to "🟡 觀望",
        "red" to "🔴 收縮",
        "unknown" to "⚪ 資料不足",
    )

    fun compute(data: Map<String, List<DataPoint>>): MacroIndexResult {
        val signals = mutableListOf<MacroSignal>()
        val groups = linkedMapOf("A" to mutableListOf<Int>(), "B" to mutableListOf(), "C" to mutableListOf(), "D" to mutableListOf())

        fun add(group: String, id: Int, signal: MacroSignal) {
            signals += signal
            groups.getValue(group) += signal.score
        }

        add("A", 1, pmiExpansion("A", 1, "美國 PMI", data["US_PMI"]))
        add("A", 2, pmiExpansion("A", 2, "台灣 PMI", data["TW_PMI"]))
        add("A", 3, pmiExpansion("A", 3, "中國 PMI", data["CN_PMI"]))
        add("A", 4, pmiExpansion("A", 4, "歐洲工業信心", data["EU_PMI"]))
        add("A", 5, yoyPositive("A", 5, "美國製造業新訂單 YoY", data["US_NEW_ORDERS_YOY"]))

        add("B", 6, yoyImproving("B", 6, "台灣出口 YoY", data["TW_EXP_YOY"]))
        add("B", 7, yoyImproving("B", 7, "韓國出口 YoY", data["KR_EXP_YOY"]))
        add("B", 8, yoyPositive("B", 8, "美國零售銷售 YoY", data["US_RETAIL_YOY"]))
        add("B", 9, oecdBreadth(data))
        add("B", 10, slopeUp("B", 10, "NDC 景氣領先指標", data["NDC_LEADING"]))

        add("C", 11, scissorsNarrowing(data["US_CORE_CPI_YOY"], data["US_CORE_PPI_YOY"], data["CPI_PPI_SCISSORS"]))
        add("C", 12, slopeUp("C", 12, "中國 PPI YoY", data["CN_PPI_YOY"], suffix = "%"))
        add("C", 13, threeMonthDown("C", 13, "HY 信用利差", data["HY_SPREAD"], rule = "3M 下降", suffix = " bps"))
        add("C", 14, positiveAndSlopeUp("C", 14, "10Y-3M 利差", data["T10Y3M"], rule = ">0 且 3M 斜率向上", suffix = "%"))
        add("C", 15, m1bM2Spread(data["TW_M1B_YOY"], data["TW_M2_YOY"]))

        add("D", 16, threeMonthDown("D", 16, "VIX", data["VIX"], rule = "3M 下降"))
        add("D", 17, threeMonthDown("D", 17, "台幣匯率 TWD/USD", data["TWD_USD"], rule = "台幣 3M 升值趨勢"))
        add("D", 18, yoyPositive("D", 18, "銅價 YoY", data["COPPER_YOY"]))
        add("D", 19, positiveAndSlopeUp("D", 19, "內部輪動指數", data["SECTOR_ROTATION"], rule = ">0 且 3M 斜率向上"))
        add("D", 20, positiveSimple("D", 20, "13F 循環/防禦淨加碼", data["THIRTEENF_NET_ADD"], rule = ">0"))

        val groupScores = groups.mapValues { (_, scores) ->
            MacroGroupScore(raw = scores.sum(), capped = minOf(scores.sum(), GROUP_CAP))
        }
        val score = groupScores.values.sumOf { it.capped }
        val validCount = signals.count { !it.raw.startsWith("N/A") }
        val confidence = if (validCount >= MIN_VALID) "normal" else "low"
        val regime = when {
            validCount < 10 -> "unknown"
            score >= REGIME_GREEN -> "green"
            score <= REGIME_RED -> "red"
            else -> "yellow"
        }

        return MacroIndexResult(
            score = score,
            diffusion = score / 20f * 100f,
            regime = regime,
            regimeLabel = regimeLabels.getValue(regime),
            confidence = confidence,
            validCount = validCount,
            signals = signals,
            groupScores = groupScores,
            topDrivers = signals.filter { it.score == 1 }.take(3),
            topDrags = signals.filter { it.score == 0 && !it.raw.startsWith("N/A") }.take(3),
        )
    }

    fun regimeColor(regime: String): String = regime

    private fun latest(series: List<DataPoint>?): Float? = series?.maxByOrNull { it.timestamp }?.value

    private fun slopePositive(series: List<DataPoint>?, months: Int = 3): Boolean? {
        val pts = series.orEmpty().sortedBy { it.timestamp }.takeLast(months)
        if (pts.size < 2) return null
        return pts.last().value > pts.first().value
    }

    private fun avgImproving(series: List<DataPoint>?, months: Int = 3): Boolean? {
        val pts = series.orEmpty().sortedBy { it.timestamp }
        if (pts.size < months * 2) return null
        val recent = pts.takeLast(months).map { it.value }.average().toFloat()
        val prior = pts.dropLast(months).takeLast(months).map { it.value }.average().toFloat()
        return recent > prior
    }

    private fun threeMonthDownBool(series: List<DataPoint>?): Boolean? {
        val pts = series.orEmpty().sortedBy { it.timestamp }
        if (pts.size < 3) return null
        return pts.last().value < pts[pts.size - 3].value
    }

    private fun pmiExpansion(group: String, id: Int, name: String, series: List<DataPoint>?): MacroSignal {
        val value = latest(series)
        val cond = (value != null && value > 50f) && (slopePositive(series) == true)
        return MacroSignal(group, id, name, score(cond), value?.let { "%.1f".format(it) } ?: "N/A", ">50 且 3M 斜率向上")
    }

    private fun yoyImproving(group: String, id: Int, name: String, series: List<DataPoint>?): MacroSignal {
        val value = latest(series)
        val cond = (value != null && value > 0f) && (avgImproving(series) == true)
        return MacroSignal(group, id, name, score(cond), value?.let { "%.1f%%".format(it) } ?: "N/A", ">0 且 3M 均值改善")
    }

    private fun yoyPositive(group: String, id: Int, name: String, series: List<DataPoint>?): MacroSignal =
        positiveSimple(group, id, name, series, rule = ">0", suffix = "%")

    private fun positiveSimple(group: String, id: Int, name: String, series: List<DataPoint>?, rule: String, suffix: String = ""): MacroSignal {
        val value = latest(series)
        val cond = value != null && value > 0f
        return MacroSignal(group, id, name, score(cond), value?.let { formatValue(it, suffix) } ?: "N/A", rule)
    }

    private fun positiveAndSlopeUp(group: String, id: Int, name: String, series: List<DataPoint>?, rule: String, suffix: String = ""): MacroSignal {
        val value = latest(series)
        val cond = (value != null && value > 0f) && (slopePositive(series) == true)
        return MacroSignal(group, id, name, score(cond), value?.let { formatValue(it, suffix) } ?: "N/A", rule)
    }

    private fun slopeUp(group: String, id: Int, name: String, series: List<DataPoint>?, suffix: String = ""): MacroSignal {
        val value = latest(series)
        return MacroSignal(group, id, name, score(slopePositive(series) == true), value?.let { formatValue(it, suffix) } ?: "N/A", "3M 斜率向上")
    }

    private fun threeMonthDown(group: String, id: Int, name: String, series: List<DataPoint>?, rule: String, suffix: String = ""): MacroSignal {
        val value = latest(series)
        return MacroSignal(group, id, name, score(threeMonthDownBool(series) == true), value?.let { formatValue(it, suffix) } ?: "N/A", rule)
    }

    private fun oecdBreadth(data: Map<String, List<DataPoint>>): MacroSignal {
        val economies = listOf("US_CLI" to "US", "CN_CLI" to "CN", "JP_CLI" to "JP", "EU_CLI" to "EU", "KR_CLI" to "KR")
        val details = economies.mapNotNull { (key, label) ->
            latest(data[key])?.let { value -> label to value }
        }
        val count = details.count { it.second > 100f }
        val raw = if (details.isEmpty()) "N/A" else "$count/5 (" + details.joinToString(", ") { "${it.first}:%.1f".format(it.second) } + ")"
        return MacroSignal("B", 9, "OECD CLI 廣度", score(count >= 3), raw, "≥3/5 國家 CLI>100")
    }

    private fun scissorsNarrowing(cpi: List<DataPoint>?, ppi: List<DataPoint>?, scissors: List<DataPoint>?): MacroSignal {
        val cpiLatest = latest(cpi)
        val ppiLatest = latest(ppi)
        val gapLatest = latest(scissors)
        val cond = when {
            gapLatest != null -> gapLatest <= 0f || threeMonthDownBool(scissors) == true
            cpiLatest != null && ppiLatest != null -> (cpiLatest - ppiLatest) <= 0f
            else -> false
        }
        val raw = if (cpiLatest != null && ppiLatest != null) {
            "CPI %.1f%% - PPI %.1f%% = %.1fpp".format(cpiLatest, ppiLatest, (gapLatest ?: cpiLatest - ppiLatest))
        } else "N/A"
        return MacroSignal("C", 11, "核心 CPI-PPI 剪刀差", score(cond), raw, "差值收斂或<0")
    }

    private fun m1bM2Spread(m1b: List<DataPoint>?, m2: List<DataPoint>?): MacroSignal {
        val latestM1b = latest(m1b)
        val latestM2 = latest(m2)
        if (latestM1b == null || latestM2 == null) {
            return MacroSignal("C", 15, "台灣 M1B-M2 利差", 0, "N/A", ">0 或 3M 斜率向上")
        }
        val spreadSeries = alignBinaryOp(m1b.orEmpty(), m2.orEmpty()) { left, right -> left - right }
        val spread = latestM1b - latestM2
        val cond = spread > 0f || slopePositive(spreadSeries) == true
        val raw = "M1B %.1f%% vs M2 %.1f%% → 差 %.1fpp".format(latestM1b, latestM2, spread)
        return MacroSignal("C", 15, "台灣 M1B-M2 利差", score(cond), raw, ">0 或 3M 斜率向上")
    }

    private fun alignBinaryOp(left: List<DataPoint>, right: List<DataPoint>, op: (Float, Float) -> Float): List<DataPoint> {
        val byRight = right.associateBy { it.timestamp }
        return left.mapNotNull { item ->
            val other = byRight[item.timestamp] ?: return@mapNotNull null
            DataPoint(item.timestamp, op(item.value, other.value))
        }.sortedBy { it.timestamp }
    }

    private fun formatValue(value: Float, suffix: String): String = when {
        suffix == " bps" -> "%.0f%s".format(value, suffix)
        kotlin.math.abs(value) >= 100f -> "%.1f%s".format(value, suffix)
        else -> "%.3f%s".format(value, suffix)
    }

    private fun score(condition: Boolean): Int = if (condition) 1 else 0
}