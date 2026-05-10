package com.lance.gaimedashboard.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.apache.poi.hssf.usermodel.HSSFWorkbook
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream

/**
 * Lightweight HTTP API client that talks to FRED and DBnomics.
 * All public functions are suspending and run on [Dispatchers.IO].
 * Results are cached in memory with a 1-hour TTL.
 */
class ApiClient {

    private val http = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    // In-memory cache: key → (fetchedAt ms, result)
    private val cache = mutableMapOf<String, Pair<Long, List<DataPoint>>>()
    private val cacheTtlMs = 60L * 60L * 1000L

    // ── Internal helpers ─────────────────────────────────────────────────────

    private fun cached(key: String): List<DataPoint>? {
        val entry = cache[key] ?: return null
        return if (System.currentTimeMillis() - entry.first < cacheTtlMs) entry.second else null
    }

    private fun store(key: String, data: List<DataPoint>) {
        cache[key] = System.currentTimeMillis() to data
    }

    private suspend fun getJson(url: String): JSONObject = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url).build()
        http.newCall(req).execute().use { response ->
            if (!response.isSuccessful) throw Exception("HTTP ${response.code}")
            JSONObject(response.body!!.string())
        }
    }

    private suspend fun getText(url: String): String = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url).build()
        http.newCall(req).execute().use { response ->
            if (!response.isSuccessful) throw Exception("HTTP ${response.code}")
            response.body!!.string()
        }
    }

    private suspend fun getBytes(url: String): ByteArray = withContext(Dispatchers.IO) {
        val req = Request.Builder().url(url).build()
        http.newCall(req).execute().use { response ->
            if (!response.isSuccessful) throw Exception("HTTP ${response.code}")
            response.body!!.bytes()
        }
    }

    private val isoSdf = SimpleDateFormat("yyyy-MM-dd", Locale.US)
    private val monthSdf = SimpleDateFormat("yyyy-MM", Locale.US)

    private fun parseTs(s: String): Long? = try {
        // Accept "yyyy-MM-dd" or "yyyy-MM" or "yyyy-Q#" (quarter, skip)
        when {
            s.length == 10 -> isoSdf.parse(s)?.time
            s.length == 7 -> monthSdf.parse("$s-01")?.time
            else -> null
        }
    } catch (_: Exception) { null }

    private fun parseYearMonthCompact(s: String): Long? {
        if (s.length != 6) return null
        val y = s.substring(0, 4).toIntOrNull() ?: return null
        val m = s.substring(4, 6).toIntOrNull() ?: return null
        if (m !in 1..12) return null
        val c = java.util.Calendar.getInstance()
        c.set(y, m - 1, 1, 0, 0, 0)
        c.set(java.util.Calendar.MILLISECOND, 0)
        return c.timeInMillis
    }

    private fun parseMinguoYearMonth(text: String): Long? {
        val m = Regex("(\\d+)年\\s*(\\d+)月").find(text) ?: return null
        val y = (m.groupValues[1].toIntOrNull() ?: return null) + 1911
        val mon = m.groupValues[2].toIntOrNull() ?: return null
        if (mon !in 1..12) return null
        val c = java.util.Calendar.getInstance()
        c.set(y, mon - 1, 1, 0, 0, 0)
        c.set(java.util.Calendar.MILLISECOND, 0)
        return c.timeInMillis
    }

    private fun parseLooseYearMonth(text: String): Long? {
        val m = Regex("(\\d{2,3})\\D+(\\d{1,2})").find(text) ?: return null
        val y = m.groupValues[1].toIntOrNull() ?: return null
        val mon = m.groupValues[2].toIntOrNull() ?: return null
        if (mon !in 1..12) return null
        val c = java.util.Calendar.getInstance()
        c.set(y + 1911, mon - 1, 1, 0, 0, 0)
        c.set(java.util.Calendar.MILLISECOND, 0)
        return c.timeInMillis
    }

    private fun monthStamp(monthLabel: String): Long? {
        val m = Regex("([A-Za-z]{3})\\s+(\\d{4})").find(monthLabel.trim()) ?: return null
        val monthNames = mapOf(
            "Jan" to 0, "Feb" to 1, "Mar" to 2, "Apr" to 3, "May" to 4, "Jun" to 5,
            "Jul" to 6, "Aug" to 7, "Sep" to 8, "Oct" to 9, "Nov" to 10, "Dec" to 11,
        )
        val month = monthNames[m.groupValues[1].replaceFirstChar { it.uppercase() }] ?: return null
        val year = m.groupValues[2].toIntOrNull() ?: return null
        val c = java.util.Calendar.getInstance()
        c.set(year, month, 1, 0, 0, 0)
        c.set(java.util.Calendar.MILLISECOND, 0)
        return c.timeInMillis
    }

    private fun previousMonth(ts: Long): Long {
        val c = java.util.Calendar.getInstance()
        c.timeInMillis = ts
        c.add(java.util.Calendar.MONTH, -1)
        c.set(java.util.Calendar.DAY_OF_MONTH, 1)
        c.set(java.util.Calendar.HOUR_OF_DAY, 0)
        c.set(java.util.Calendar.MINUTE, 0)
        c.set(java.util.Calendar.SECOND, 0)
        c.set(java.util.Calendar.MILLISECOND, 0)
        return c.timeInMillis
    }

    private fun splitCsvLine(line: String): List<String> {
        return line.split(Regex(""",(?=(?:[^"]*"[^"]*")*[^"]*$)"""))
            .map { it.trim().removePrefix("\"").removeSuffix("\"") }
    }

    /** Excel serial date (1900-based) to epoch ms. */
    private fun excelSerialToEpochMs(serial: Double): Long {
        val millisPerDay = 86_400_000L
        return ((serial - 25569.0) * millisPerDay).toLong()
    }

    /** Parses CIER seasonally adjusted PMI history from the latest XLSX. */
    private suspend fun fetchTaiwanPmiCier(): List<DataPoint> {
        val key = "tw_pmi_cier"
        cached(key)?.let { return it }

        val pageUrl = "https://www.cier.edu.tw/en/eco_cat/pmi-en/"
        val pageHtml = getText(pageUrl)
        // 優先抓含 "pmi" 的 xlsx；退而求其次取頁面上第一個 xlsx
        val allXlsx = Regex("""https?://[^\s"'<>]+\.xlsx""", RegexOption.IGNORE_CASE)
            .findAll(pageHtml).map { it.value }.toList()
        val xlsxUrl = allXlsx.firstOrNull { "pmi" in it.lowercase() || "cier" in it.lowercase() }
            ?: allXlsx.firstOrNull()
            ?: return emptyList<DataPoint>().also { store(key, it) }

        val bytes = getBytes(xlsxUrl)
        var sheetXml: String? = null
        ZipInputStream(ByteArrayInputStream(bytes)).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                if (entry.name == "xl/worksheets/sheet1.xml") {
                    sheetXml = zis.readBytes().toString(Charsets.UTF_8)
                    break
                }
            }
        }
        val xml = sheetXml ?: return emptyList<DataPoint>().also { store(key, it) }

        val rowRegex = Regex("<row[^>]*>(.*?)</row>", setOf(RegexOption.DOT_MATCHES_ALL))
        val cellRegex = Regex("<c[^>]*r=\"([A-Z]+)\\d+\"[^>]*>(.*?)</c>", setOf(RegexOption.DOT_MATCHES_ALL))
        val valueRegex = Regex("<v>(.*?)</v>", setOf(RegexOption.DOT_MATCHES_ALL))
        val result = mutableListOf<DataPoint>()

        for (rowMatch in rowRegex.findAll(xml)) {
            val rowXml = rowMatch.groupValues[1]
            var dateSerial: Double? = null
            var pmiValue: Float? = null

            for (cellMatch in cellRegex.findAll(rowXml)) {
                val col = cellMatch.groupValues[1]
                val cellBody = cellMatch.groupValues[2]
                val v = valueRegex.find(cellBody)?.groupValues?.get(1) ?: continue

                if (col == "A") dateSerial = v.toDoubleOrNull()
                if (col == "B") pmiValue = v.toFloatOrNull()
            }

            val ds = dateSerial
            val pv = pmiValue
            if (ds != null && pv != null) {
                result += DataPoint(excelSerialToEpochMs(ds), pv)
            }
        }

        val final = result.sortedBy { it.timestamp }
        store(key, final)
        return final
    }

    /** Taiwan monthly exports amount (USD mn) from MOF HTML table. */
    private suspend fun fetchTaiwanExportsAmount(): List<DataPoint> {
        val key = "tw_exports_mof"
        cached(key)?.let { return it }

        val url = "https://web02.mof.gov.tw/njswww/webMain.aspx?sys=220&ym=10001&ymt=12012&kind=21&type=1&funid=i9121&cycle=41&outmode=0&compmode=00&outkind=1&cod00=1"
        val html = getText(url)
        val rowRegex = Regex("<tr[^>]*>(.*?)</tr>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
        val headRegex = Regex("<(?:th|td)[^>]*>(.*?)</(?:th|td)>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
        val tdRegex = Regex("<td[^>]*>(.*?)</td>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
        val numRegex = Regex("(\\d{1,3}(?:,\\d{3})*(?:\\.\\d+)?)")

        val out = mutableListOf<DataPoint>()
        for (row in rowRegex.findAll(html)) {
            val body = row.groupValues[1]
            val headerCell = headRegex.find(body)?.groupValues?.get(1) ?: continue
            val ts = parseLooseYearMonth(headerCell) ?: continue

            val dataCells = tdRegex.findAll(body).map { it.groupValues[1] }.toList()
            if (dataCells.isEmpty()) continue
            val valueText = numRegex.find(dataCells.first())?.groupValues?.get(1) ?: continue
            val value = valueText.replace(",", "").toFloatOrNull() ?: continue
            out += DataPoint(ts, value)
        }

        val final = out.sortedBy { it.timestamp }
        store(key, final)
        return final
    }

    /** Taiwan M1B / M2 YoY (%) from CBC CSV. */
    private suspend fun fetchCbcMoneyYoY(): Pair<List<DataPoint>, List<DataPoint>> {
        val keyM1b = "tw_cbc_m1b_yoy"
        val keyM2  = "tw_cbc_m2_yoy"
        val c1 = cached(keyM1b)
        val c2 = cached(keyM2)
        if (c1 != null && c2 != null) return c1 to c2

        val bytes = getBytes("https://www.cbc.gov.tw/public/data/economic/statistics/key/ms.csv")

        // 自動偵測字元集：選第一個能解碼出民國年月格式的結果
        val charsets = listOf("MS950", "Big5", "UTF-8", "ISO-8859-1")
        val text = charsets.firstNotNullOfOrNull { cs ->
            runCatching {
                val decoded = String(bytes, charset(cs))
                if (Regex("\\d+年\\d+月").containsMatchIn(decoded)) decoded else null
            }.getOrNull()
        } ?: run {
            // 最後退路：UTF-8 強制解碼
            String(bytes, Charsets.UTF_8)
        }

        val m1b = mutableListOf<DataPoint>()
        val m2  = mutableListOf<DataPoint>()
        val cutoff = System.currentTimeMillis() - 12L * 365L * 24L * 60L * 60L * 1000L

        for (line in text.lineSequence()) {
            val cols = splitCsvLine(line)
            if (cols.size < 13) continue
            val ts = parseMinguoYearMonth(cols[0]) ?: parseLooseYearMonth(cols[0]) ?: continue
            if (ts < cutoff) continue

            val m1v = cols[8].replace("\"", "").replace(",", "").trim().toFloatOrNull()
            val m2v = cols[12].replace("\"", "").replace(",", "").trim().toFloatOrNull()
            if (m1v != null) m1b += DataPoint(ts, m1v)
            if (m2v != null) m2  += DataPoint(ts, m2v)
        }

        val finalM1b = m1b.sortedBy { it.timestamp }
        val finalM2  = m2.sortedBy { it.timestamp }
        store(keyM1b, finalM1b)
        store(keyM2, finalM2)
        return finalM1b to finalM2
    }

    private suspend fun fetchJapanEconomyWatchers(): List<DataPoint> {
        val key = "jp_economy_watchers"
        cached(key)?.let { return it }

        val bytes = getBytes("https://www5.cao.go.jp/keizai3/watcher-e/di.xls")
        val out = mutableListOf<DataPoint>()
        HSSFWorkbook(ByteArrayInputStream(bytes)).use { workbook ->
            val sheet = workbook.getSheet("3. DI by sector(SA)") ?: workbook.getSheetAt(2)
            val monthMap = mapOf(
                "Jan" to 1, "Feb" to 2, "Mar" to 3, "Apr" to 4, "May" to 5, "Jun" to 6,
                "Jul" to 7, "Aug" to 8, "Sep" to 9, "Oct" to 10, "Nov" to 11, "Dec" to 12,
            )
            var currentYear: Int? = null
            for (rowIndex in 7..sheet.lastRowNum) {
                val row = sheet.getRow(rowIndex) ?: continue
                val yearCell = row.getCell(0)
                val monthCell = row.getCell(1)
                val valueCell = row.getCell(9)

                val y = yearCell?.numericCellValue?.toInt()
                if (y != null && y > 1900) currentYear = y
                val year = currentYear ?: continue

                val monthText = monthCell?.toString()?.trim() ?: continue
                val month = monthMap[monthText] ?: continue
                val value = valueCell?.numericCellValue?.toFloat() ?: continue

                val c = java.util.Calendar.getInstance()
                c.set(year, month - 1, 1, 0, 0, 0)
                c.set(java.util.Calendar.MILLISECOND, 0)
                out += DataPoint(c.timeInMillis, value)
            }
        }

        val final = out.distinctBy { it.timestamp }.sortedBy { it.timestamp }
        store(key, final)
        return final
    }

    private suspend fun fetchEurostatIci(): List<DataPoint> {
        val key = "eurostat_ici"
        cached(key)?.let { return it }

        val year = java.util.Calendar.getInstance().get(java.util.Calendar.YEAR) - 12
        // Path-based filter: only BS-ICI + SA + BAL for geo — avoids flat-index shifting
        val geos = listOf("EA20", "EA21", "EU27_2020")
        var data: JSONObject? = null
        var chosenGeo = ""
        for (geo in geos) {
            val url = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/" +
                    "ei_bsin_m_r2/BS-ICI.SA.BAL.$geo?format=JSON&sinceTimePeriod=$year-01"
            val resp = runCatching { getJson(url) }.getOrNull() ?: continue
            val valuesObj = resp.optJSONObject("value")
            if (valuesObj != null && valuesObj.length() > 0) {
                data = resp; chosenGeo = geo; break
            }
        }
        if (data == null) return emptyList<DataPoint>().also { store(key, it) }

        // With path-filter all non-time dimensions are size 1, so flat index == time position
        val dimension = data.getJSONObject("dimension")
        val times = dimension.getJSONObject("time").getJSONObject("category").getJSONObject("index")
        val nt = data.getJSONArray("size").let { it.getInt(it.length() - 1) }
        val values = data.getJSONObject("value")

        val timeLabels = mutableMapOf<Int, String>()
        times.keys().forEach { k -> timeLabels[times.getInt(k)] = k }

        val out = mutableListOf<DataPoint>()
        for (t in 0 until nt) {
            val ts = timeLabels[t]?.let { parseTs(it) } ?: continue
            val v = values.optDouble(t.toString(), Double.NaN)
            if (v.isNaN()) continue
            out += DataPoint(ts, v.toFloat() + 50f)
        }

        val final = out.sortedBy { it.timestamp }
        store(key, final)
        return final
    }

    private suspend fun fetchIsmPmiComposite(apiKey: String = ""): List<DataPoint> {
        val key = "ism_pmi_composite"
        cached(key)?.let { return it }

        val datasets = listOf("neword", "production", "employment", "supdel", "inventories")
        val series = mutableMapOf<String, List<DataPoint>>()
        for (dataset in datasets) {
            val data = runCatching { fetchDbNomics("ISM", dataset, "in") }.getOrDefault(emptyList())
            if (data.isNotEmpty()) series[dataset] = data
        }

        var historic = if (series.size == datasets.size) {
            val byDataset = datasets.associateWith { series[it].orEmpty().associateBy { p -> p.timestamp } }
            val timestamps = datasets.firstNotNullOf { series[it] }.map { it.timestamp }
            timestamps.mapNotNull { ts ->
                val vals = datasets.mapNotNull { byDataset[it]?.get(ts)?.value }
                if (vals.size == datasets.size) DataPoint(ts, vals.average().toFloat()) else null
            }.sortedBy { it.timestamp }
        } else emptyList()

        // FRED NAPM fallback — fills months after last DBnomics date
        if (apiKey.isNotBlank()) {
            val napm = runCatching { fetchFred("NAPM", apiKey) }.getOrDefault(emptyList())
            if (napm.isNotEmpty()) {
                val lastHistoric = historic.lastOrNull()?.timestamp ?: 0L
                val tail = napm.filter { it.timestamp > lastHistoric }
                historic = (historic + tail).sortedBy { it.timestamp }
            }
        }

        if (historic.isEmpty()) return emptyList<DataPoint>().also { store(key, it) }
        store(key, historic)
        return historic
    }

    /** NDC Leading Index — scrapes NDC JSON API (ROC ym format 11401 = 2025-01). */
    private suspend fun fetchNdcLeadingIndex(): List<DataPoint> {
        val key = "ndc_leading"
        cached(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            runCatching {
                val json = getJson("https://index.ndc.gov.tw/n/json/leading")
                val out = mutableListOf<DataPoint>()
                // Response is a JSON array
                val arr = try { JSONArray(json.toString()) } catch (_: Exception) {
                    json.optJSONArray("data") ?: return@runCatching emptyList<DataPoint>()
                }
                for (i in 0 until arr.length()) {
                    val obj = arr.optJSONObject(i) ?: continue
                    // ym like "11401" means ROC 114 year, month 01
                    val ym = obj.optString("ym").trim()
                    if (ym.length < 5) continue
                    val rocStr = ym.dropLast(2); val mon = ym.takeLast(2)
                    val roc = rocStr.toIntOrNull() ?: continue
                    val month = mon.toIntOrNull() ?: continue
                    if (month !in 1..12) continue
                    val c = java.util.Calendar.getInstance()
                    c.set(roc + 1911, month - 1, 1, 0, 0, 0)
                    c.set(java.util.Calendar.MILLISECOND, 0)
                    val v = (obj.optDouble("score", Double.NaN).takeIf { !it.isNaN() }
                        ?: obj.optDouble("value", Double.NaN).takeIf { !it.isNaN() }
                        ?: obj.optDouble("index", Double.NaN).takeIf { !it.isNaN() }
                        ?: continue).toFloat()
                    out += DataPoint(c.timeInMillis, v)
                }
                out.sortedBy { it.timestamp }
            }.getOrDefault(emptyList())
        }.also { store(key, it) }
    }

    /** TSMC monthly revenue YoY (%) — scrapes TWSE MOPS ajax endpoint. */
    private suspend fun fetchTsmcRevenueYoy(): List<DataPoint> {
        val key = "tsmc_rev_yoy"
        cached(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            runCatching {
                val reqBody = okhttp3.FormBody.Builder()
                    .add("encodeURIComponent", "1")
                    .add("step", "1")
                    .add("firstin", "1")
                    .add("off", "1")
                    .add("co_id", "2330")
                    .build()
                val req = Request.Builder()
                    .url("https://mops.twse.com.tw/mops/web/ajax_t05st10_ifrs")
                    .post(reqBody)
                    .addHeader("Referer", "https://mops.twse.com.tw/mops/web/t05st10_ifrs")
                    .build()
                val html = http.newCall(req).execute().use { r ->
                    if (!r.isSuccessful) return@runCatching emptyList<DataPoint>()
                    r.body!!.string()
                }
                val rowRegex = Regex("<tr[^>]*>(.*?)</tr>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
                val tdRegex  = Regex("<td[^>]*>(.*?)</td>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
                val thRegex  = Regex("<th[^>]*>(.*?)</th>", setOf(RegexOption.DOT_MATCHES_ALL, RegexOption.IGNORE_CASE))
                val stripTag = Regex("<[^>]+>")
                val numRegex = Regex("[-+]?[\\d,]+(?:\\.\\d+)?")

                // 先找 header row 確定 YoY 欄位索引
                var yoyColIndex = 3 // 預設 MOPS 第 4 欄
                val headerRow = rowRegex.findAll(html).firstOrNull { row ->
                    thRegex.containsMatchIn(row.groupValues[1]) ||
                    row.groupValues[1].contains("去年同月", ignoreCase = true) ||
                    row.groupValues[1].contains("YoY", ignoreCase = true)
                }
                if (headerRow != null) {
                    val headers = tdRegex.findAll(headerRow.groupValues[1]).map {
                        it.groupValues[1].replace(stripTag, "").trim()
                    }.toList()
                    val yoyIdx = headers.indexOfFirst { h ->
                        "去年同月" in h || "yoy" in h.lowercase() || "年增" in h || "年同" in h
                    }
                    if (yoyIdx >= 0) yoyColIndex = yoyIdx
                }

                val out = mutableListOf<DataPoint>()
                for (row in rowRegex.findAll(html)) {
                    val cells = tdRegex.findAll(row.groupValues[1]).map {
                        it.groupValues[1].replace(stripTag, "").trim()
                    }.toList()
                    if (cells.size <= yoyColIndex) continue
                    val ts = parseMinguoYearMonth(cells[0]) ?: continue
                    val yoyText = numRegex.find(cells[yoyColIndex].replace(",", ""))?.value ?: continue
                    val yoy = yoyText.toFloatOrNull() ?: continue
                    if (yoy !in -100f..500f) continue // 排除非 YoY 的欄位噪音
                    out += DataPoint(ts, yoy)
                }
                out.sortedBy { it.timestamp }
            }.getOrDefault(emptyList())
        }.also { store(key, it) }
    }

    private suspend fun fetchTradingEconomicsChinaPmiTail(): List<DataPoint> {
        val html = getText("https://www.tradingeconomics.com/china/manufacturing-pmi")
        val match = Regex(
            "NBS Manufacturing PMI\\s*</a>\\s*</td>\\s*<td>([^<]+)</td>\\s*<td>([^<]+)</td>.*?<td>([A-Za-z]{3} \\d{4})</td>",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
        ).find(html) ?: return emptyList()

        val current = match.groupValues[1].trim().replace("%", "").toFloatOrNull() ?: return emptyList()
        val previous = match.groupValues[2].trim().replace("%", "").toFloatOrNull() ?: return emptyList()
        val currentTs = monthStamp(match.groupValues[3]) ?: return emptyList()
        return listOf(
            DataPoint(previousMonth(currentTs), previous),
            DataPoint(currentTs, current),
        )
    }

    private suspend fun fetchTradingEconomicsUsPmiTail(): List<DataPoint> {
        val html = getText("https://www.tradingeconomics.com/united-states/manufacturing-pmi")
        val match = Regex(
            "ISM Manufacturing PMI\\s*</a>\\s*</td>\\s*<td>([^<]+)</td>\\s*<td>([^<]+)</td>.*?<td>([A-Za-z]{3} \\d{4})</td>",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
        ).find(html) ?: return emptyList()

        val current = match.groupValues[1].trim().replace("%", "").toFloatOrNull() ?: return emptyList()
        val previous = match.groupValues[2].trim().replace("%", "").toFloatOrNull() ?: return emptyList()
        val currentTs = monthStamp(match.groupValues[3]) ?: return emptyList()
        return listOf(
            DataPoint(previousMonth(currentTs), previous),
            DataPoint(currentTs, current),
        )
    }

    private suspend fun fetchTradingEconomicsChinaPpiTail(): List<DataPoint> {
        val html = getText("https://www.tradingeconomics.com/china/producer-prices-change")
        val rowRegex = Regex(
            "PPI YoY.*?<td id=\"reference\"[^>]*>\\s*([A-Za-z]{3})</span>\\s*</td>\\s*<td id=\"actual\"[^>]*>\\s*([^<]+)\\s*</td>\\s*<td id=\"previous\"[^>]*>\\s*([^<]+)\\s*</td>",
            setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL)
        )
        val rows = rowRegex.findAll(html).toList()
        if (rows.isEmpty()) return emptyList()

        val meta = Regex("Producer Prices in China decreased .*? in ([A-Za-z]+) of (\\d{4})", RegexOption.IGNORE_CASE)
            .find(html)
        val currentMonthLabel = meta?.let { "${it.groupValues[1].take(3)} ${it.groupValues[2]}" }
        val currentTs = currentMonthLabel?.let { monthStamp(it) } ?: return emptyList()

        val currentMonthAbbr = SimpleDateFormat("MMM", Locale.US).format(Date(currentTs))
        val currentRow = rows.firstOrNull { it.groupValues[1].equals(currentMonthAbbr, ignoreCase = true) }
            ?: rows.firstOrNull()
            ?: return emptyList()
        val actual = currentRow.groupValues[2].replace("%", "").trim().toFloatOrNull() ?: return emptyList()
        val previous = currentRow.groupValues[3].replace("%", "").trim().toFloatOrNull() ?: return emptyList()

        return listOf(
            DataPoint(previousMonth(currentTs), previous),
            DataPoint(currentTs, actual),
        )
    }

    private fun mergeAndReplace(base: List<DataPoint>, tail: List<DataPoint>): List<DataPoint> {
        if (tail.isEmpty()) return base.sortedBy { it.timestamp }
        val merged = (base.filter { original -> tail.none { it.timestamp == original.timestamp } } + tail)
            .sortedBy { it.timestamp }
        return merged
    }

    /** Low-level call: start date for FRED queries (10 years back). */
    private fun fredStart(years: Int = 12): String {
        val c = java.util.Calendar.getInstance()
        c.add(java.util.Calendar.YEAR, -years)
        return SimpleDateFormat("yyyy-MM-dd", Locale.US).format(c.time)
    }

    // ── FRED ──────────────────────────────────────────────────────────────────

    /** Fetch a FRED time-series. Returns empty list if no API key provided. */
    suspend fun fetchFred(seriesId: String, apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val key = "fred_$seriesId"
        cached(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            val url = "https://api.stlouisfed.org/fred/series/observations" +
                    "?series_id=${seriesId}" +
                    "&api_key=${apiKey}" +
                    "&file_type=json" +
                    "&observation_start=${fredStart()}" +
                    "&sort_order=asc"
            val json = getJson(url)
            val observations = json.getJSONArray("observations")
            val result = mutableListOf<DataPoint>()
            for (i in 0 until observations.length()) {
                val ob = observations.getJSONObject(i)
                val v = ob.getString("value").toFloatOrNull() ?: continue
                val ts = parseTs(ob.getString("date")) ?: continue
                result += DataPoint(ts, v)
            }
            result.sortBy { it.timestamp }
            store(key, result)
            result
        }
    }

    // ── DBnomics ──────────────────────────────────────────────────────────────

    /**
     * Fetch a DBnomics time-series. Free tier, no key required.
     * [provider]/[dataset]/[series] – e.g. OECD/MEI/USA.LOLITONO.STSA.M
     */
    suspend fun fetchDbNomics(
        provider: String,
        dataset: String,
        series: String,
        /** Optional offset applied to every value (e.g. –50 to convert ICI → PMI scale). */
        valueOffset: Float = 0f,
        /** If true, map values > 80 down by 50 (converts 100-based to 50-based scale). */
        normalize100to50: Boolean = false
    ): List<DataPoint> {
        val key = "dbn_${provider}_${dataset}_${series}"
        cached(key)?.let { return it }
        return withContext(Dispatchers.IO) {
            val encodedSeries = java.net.URLEncoder.encode(series, "UTF-8")
            val url = "https://api.db.nomics.world/v22/series/${provider}/${dataset}/${encodedSeries}" +
                    "?observations=1&format=json"
            val json = getJson(url)
            val docs = json.getJSONObject("series").getJSONArray("docs")
            if (docs.length() == 0) return@withContext emptyList<DataPoint>().also { store(key, it) }
            val doc = docs.getJSONObject(0)
            val periods = doc.getJSONArray("period")
            val values = doc.getJSONArray("value")
            val result = mutableListOf<DataPoint>()
            for (i in 0 until periods.length()) {
                val raw = values.get(i)
                val v = when (raw) {
                    is Number -> raw.toFloat()
                    is String -> raw.toFloatOrNull() ?: continue
                    else -> continue
                }
                val ts = parseTs(periods.getString(i)) ?: continue
                var finalV = v + valueOffset
                if (normalize100to50 && finalV > 80f) finalV -= 50f
                result += DataPoint(ts, finalV)
            }
            result.sortBy { it.timestamp }
            store(key, result)
            result
        }
    }

    // ── Composite loaders ─────────────────────────────────────────────────────

    /** Panel A: 5-country PMI aligned with Web sources. */
    suspend fun loadPmi(apiKey: String = ""): Map<String, List<DataPoint>> {
        val results = mutableMapOf<String, List<DataPoint>>()
        val usBase = runCatching { fetchIsmPmiComposite(apiKey) }.getOrDefault(emptyList())
        val usTail = runCatching { fetchTradingEconomicsUsPmiTail() }.getOrDefault(emptyList())
        results["us"] = mergeAndReplace(usBase, usTail)

        runCatching { fetchTaiwanPmiCier() }
            .onSuccess { results["tw"] = it }

        val chinaBase = runCatching { fetchDbNomics("OECD", "MEI", "CHN.BSCICP03.IXNSA.M", normalize100to50 = true) }
            .getOrDefault(emptyList())
        val chinaTail = runCatching { fetchTradingEconomicsChinaPmiTail() }.getOrDefault(emptyList())
        results["cn"] = mergeAndReplace(chinaBase, chinaTail)

        runCatching { fetchJapanEconomyWatchers() }
            .onSuccess { results["jp"] = it }

        runCatching { fetchEurostatIci() }
            .onSuccess { results["eu"] = it }

        return results
    }

    /** Panel B: 5-economy OECD CLI (normalised, 100 = long-run trend). */
    suspend fun loadCli(): Map<String, List<DataPoint>> {
        val results = mutableMapOf<String, List<DataPoint>>()
        val countryMap = mapOf(
            "us" to "USA.LOLITONO.STSA.M",
            "cn" to "CHN.LOLITONO.STSA.M",
            "jp" to "JPN.LOLITONO.STSA.M",
            "eu" to "G4E.LOLITONO.STSA.M",
            "kr" to "KOR.LOLITONO.STSA.M"
        )
        for ((code, series) in countryMap) {
            runCatching { fetchDbNomics("OECD", "MEI", series) }
                .onSuccess { results[code] = it }
        }
        return results
    }

    /** Panel A: Taiwan export YoY % (FRED primary, DBnomics fallback). */
    suspend fun loadExportYoY(apiKey: String): List<DataPoint> {
        var raw = runCatching { fetchTaiwanExportsAmount() }.getOrDefault(emptyList())

        if (raw.isEmpty()) {
            raw = if (apiKey.isNotBlank())
                runCatching { fetchFred("XTEXVA01TWM667S", apiKey) }.getOrDefault(emptyList())
            else emptyList()
        }

        return raw.computeYoY()
    }

    /** Panel A: US retail sales level + YoY (FRED RSAFS). */
    suspend fun loadRetailSales(apiKey: String): Map<String, List<DataPoint>> {
        val raw = if (apiKey.isNotBlank()) {
            runCatching { fetchFred("RSAFS", apiKey) }.getOrDefault(emptyList())
        } else {
            emptyList()
        }
        return mapOf(
            "level" to raw,
            "yoy" to raw.computeYoY(),
        )
    }

    /** Panel A: M1/M1B/M2 money supply YoY (US M1 + Taiwan M1B/M2). */
    suspend fun loadMoneyYoY(apiKey: String): Map<String, List<DataPoint>> {
        val res = mutableMapOf<String, List<DataPoint>>()
        // US M1 – FRED (fallback to OECD if key unavailable)
        var usRaw = if (apiKey.isNotBlank())
            runCatching { fetchFred("M1SL", apiKey) }.getOrDefault(emptyList())
        else emptyList()
        if (usRaw.isEmpty()) usRaw =
            runCatching { fetchDbNomics("OECD", "MEI", "USA.MANMM101.STSA.M") }.getOrDefault(emptyList())

        val (twM1bYoY, twM2YoY) = runCatching { fetchCbcMoneyYoY() }
            .getOrDefault(emptyList<DataPoint>() to emptyList())

        res["us_m1"] = usRaw.computeYoY()
        res["tw_m1b"] = twM1bYoY
        res["tw_m2"] = twM2YoY
        return res
    }

    /** Panel B: US semiconductor PPI index (FRED PCU33443344). */
    suspend fun loadSemiPpi(apiKey: String): List<DataPoint> =
        if (apiKey.isNotBlank()) runCatching { fetchFred("PCU33443344", apiKey) }.getOrDefault(emptyList())
        else emptyList()

    /** Panel B: US business inventories (FRED BUSINV). */
    suspend fun loadBusinessInventories(apiKey: String): List<DataPoint> =
        if (apiKey.isNotBlank()) runCatching { fetchFred("BUSINV", apiKey) }.getOrDefault(emptyList())
        else emptyList()

    /** Panel B: US 10Y real rate = DGS10 - T10YIE. */
    suspend fun loadUsRealRate(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val nominal = runCatching { fetchFred("DGS10", apiKey) }.getOrDefault(emptyList())
        val breakeven = runCatching { fetchFred("T10YIE", apiKey) }.getOrDefault(emptyList())
        if (nominal.isEmpty() || breakeven.isEmpty()) return emptyList()

        val byDateNom = nominal.associateBy { it.timestamp }
        return breakeven.mapNotNull { p ->
            val n = byDateNom[p.timestamp] ?: return@mapNotNull null
            DataPoint(p.timestamp, n.value - p.value)
        }.sortedBy { it.timestamp }
    }

    /** Panel B: Core CPI/PPI scissors = Core CPI YoY - Core PPI YoY. */
    suspend fun loadCoreCpiPpiScissors(apiKey: String): Map<String, List<DataPoint>> {
        if (apiKey.isBlank()) return mapOf("cpi_yoy" to emptyList(), "ppi_yoy" to emptyList(), "scissors" to emptyList())
        val coreCpi = runCatching { fetchFred("CPILFESL", apiKey) }.getOrDefault(emptyList()).computeYoY()
        val corePpi = runCatching { fetchFred("PPIFES", apiKey) }.getOrDefault(emptyList()).computeYoY()
        if (coreCpi.isEmpty() || corePpi.isEmpty()) {
            return mapOf("cpi_yoy" to coreCpi, "ppi_yoy" to corePpi, "scissors" to emptyList())
        }
        val byDatePpi = corePpi.associateBy { it.timestamp }
        val scissors = coreCpi.mapNotNull { c ->
            val p = byDatePpi[c.timestamp] ?: return@mapNotNull null
            DataPoint(c.timestamp, c.value - p.value)
        }.sortedBy { it.timestamp }
        return mapOf("cpi_yoy" to coreCpi, "ppi_yoy" to corePpi, "scissors" to scissors)
    }

    /** Panel B: China PPI YoY from TradingEconomics release table fallback. */
    suspend fun loadChinaPpiYoY(yearsBack: Int = 12): List<DataPoint> {
        val base = runCatching { fetchDbNomics("OECD", "MEI", "CHN.PIEAMP01.GYSA.M") }.getOrDefault(emptyList())
        val tail = runCatching { fetchTradingEconomicsChinaPpiTail() }.getOrDefault(emptyList())
        val merged = mergeAndReplace(base, tail)
        val cutoff = System.currentTimeMillis() - yearsBack * 365L * 24L * 60L * 60L * 1000L
        return merged.filter { it.timestamp >= cutoff }
    }

    /** Panel B: Brent crude oil price (FRED DCOILBRENTEU). */
    suspend fun loadBrent(apiKey: String): List<DataPoint> =
        if (apiKey.isNotBlank()) runCatching { fetchFred("DCOILBRENTEU", apiKey) }.getOrDefault(emptyList())
        else emptyList()

    /** Panel C: VIX volatility index (FRED VIXCLS, daily – downsample to monthly end). */
    suspend fun loadVix(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("VIXCLS", apiKey) }.getOrDefault(emptyList())
        return downsampleMonthlyLast(raw)
    }

    /** Panel C: 10Y-2Y Treasury spread (FRED T10Y2Y, daily → monthly). */
    suspend fun loadSpread(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("T10Y2Y", apiKey) }.getOrDefault(emptyList())
        return downsampleMonthlyLast(raw)
    }

    /** Panel C: University of Michigan Consumer Sentiment (FRED UMCSENT). */
    suspend fun loadUmcsent(apiKey: String): List<DataPoint> =
        if (apiKey.isNotBlank()) runCatching { fetchFred("UMCSENT", apiKey) }.getOrDefault(emptyList())
        else emptyList()

    /** Reduce daily series to one point per month (last value of each month). */
    private fun downsampleMonthlyLast(data: List<DataPoint>): List<DataPoint> {
        if (data.isEmpty()) return data
        val sdf = SimpleDateFormat("yyyy-MM", Locale.US)
        return data.groupBy { sdf.format(Date(it.timestamp)) }
            .values
            .map { group -> group.maxBy { it.timestamp } }
            .sortedBy { it.timestamp }
    }

    /** Panel A: Korea exports YoY % (FRED XTEXVA01KRM664S). */
    suspend fun loadKoreaExportsYoy(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("XTEXVA01KRM664S", apiKey) }.getOrDefault(emptyList())
        return raw.computeYoY()
    }

    /** Panel A: NDC Leading Index (Taiwan). */
    suspend fun loadNdcLeadingIndex(): List<DataPoint> =
        runCatching { fetchNdcLeadingIndex() }.getOrDefault(emptyList())

    /** Panel B: Copper price YoY % (FRED PCOPPUSDM). */
    suspend fun loadCopperYoy(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("PCOPPUSDM", apiKey) }.getOrDefault(emptyList())
        return raw.computeYoY()
    }

    /** Panel B: TSMC monthly revenue YoY % (TWSE MOPS). */
    suspend fun loadTsmcRevenueYoy(): List<DataPoint> =
        runCatching { fetchTsmcRevenueYoy() }.getOrDefault(emptyList())

    /** Panel C: ICE BofA HY OAS (FRED BAMLH0A0HYM2, bps). */
    suspend fun loadHySpread(apiKey: String): List<DataPoint> =
        if (apiKey.isNotBlank()) runCatching { fetchFred("BAMLH0A0HYM2", apiKey) }.getOrDefault(emptyList())
        else emptyList()

    /** Panel C: TWD/USD exchange rate (FRED DEXTAUS). */
    suspend fun loadTwdUsd(apiKey: String): List<DataPoint> =
        if (apiKey.isNotBlank()) runCatching { fetchFred("DEXTAUS", apiKey) }.getOrDefault(emptyList())
        else emptyList()

    // ── Panel D: Stock Market ────────────────────────────────────────────────

    /** Panel D: S&P 500 monthly YoY % (FRED SP500). */
    suspend fun loadSp500Yoy(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("SP500", apiKey) }.getOrDefault(emptyList())
        // SP500 是日頻；取月末最後一筆
        val monthly = downsampleMonthlyLast(raw)
        return monthly.computeYoY()
    }

    /** Panel D: TAIEX monthly YoY % (Yahoo Finance ^TWII). */
    suspend fun loadTaiwanStockYoy(): List<DataPoint> {
        val cacheKey = "taiex_yoy"
        cached(cacheKey)?.let { return it }
        return withContext(Dispatchers.IO) {
            runCatching {
                val url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1mo&range=15y"
                val req = Request.Builder()
                    .url(url)
                    .addHeader("User-Agent", "Mozilla/5.0")
                    .addHeader("Accept", "application/json")
                    .build()
                val json = http.newCall(req).execute().use { r ->
                    if (!r.isSuccessful) return@runCatching emptyList<DataPoint>()
                    JSONObject(r.body!!.string())
                }
                val result = json.optJSONObject("chart")?.optJSONArray("result")
                    ?: return@runCatching emptyList<DataPoint>()
                if (result.length() == 0) return@runCatching emptyList<DataPoint>()
                val item = result.getJSONObject(0)
                val timestamps = item.optJSONArray("timestamp") ?: return@runCatching emptyList<DataPoint>()
                val closes = item.optJSONObject("indicators")
                    ?.optJSONArray("adjclose")?.optJSONObject(0)
                    ?.optJSONArray("adjclose") ?: return@runCatching emptyList<DataPoint>()
                val raw = (0 until timestamps.length()).mapNotNull { i ->
                    val ts = timestamps.getLong(i) * 1000L
                    val v = closes.optDouble(i, Double.NaN).takeIf { !it.isNaN() }?.toFloat()
                        ?: return@mapNotNull null
                    DataPoint(ts, v)
                }.sortedBy { it.timestamp }
                raw.computeYoY()
            }.getOrDefault(emptyList())
        }.also { store(cacheKey, it) }
    }

    /** Panel D: Fed Funds Rate monthly average (FRED DFF). */
    suspend fun loadFedFundsRate(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("DFF", apiKey) }.getOrDefault(emptyList())
        // DFF 是日頻；取月均
        if (raw.isEmpty()) return emptyList()
        val sdf = SimpleDateFormat("yyyy-MM", Locale.US)
        return raw.groupBy { sdf.format(Date(it.timestamp)) }.map { (_, pts) ->
            val first = pts.minBy { it.timestamp }
            DataPoint(first.timestamp, pts.map { it.value }.average().toFloat())
        }.sortedBy { it.timestamp }
    }

    /** Panel D: 10Y-3M Treasury spread (FRED T10Y3M). */
    suspend fun loadT10y3m(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("T10Y3M", apiKey) }.getOrDefault(emptyList())
        return downsampleMonthlyLast(raw)
    }

    /** Panel D: US Manufacturing New Orders YoY % (FRED AMTMNO). */
    suspend fun loadUsNewOrdersYoy(apiKey: String): List<DataPoint> {
        if (apiKey.isBlank()) return emptyList()
        val raw = runCatching { fetchFred("AMTMNO", apiKey) }.getOrDefault(emptyList())
        return raw.computeYoY()
    }

    /** Panel E: cyclical vs defensive sector rotation (monthly relative strength). */
    suspend fun loadSectorRotation(yearsBack: Int = 11): List<DataPoint> {
        val cacheKey = "sector_rotation_$yearsBack"
        cached(cacheKey)?.let { return it }

        val cyclical = listOf("XLY", "XLI", "XLB", "XLF")
        val defensive = listOf("XLP", "XLU", "XLV", "XLRE")
        val allTickers = cyclical + defensive

        val prices = allTickers.associateWith { ticker ->
            runCatching { fetchYahooMonthlySeries(ticker, "adjclose") }.getOrDefault(emptyList())
        }.filterValues { it.isNotEmpty() }

        val cycSeries = cyclical.mapNotNull { prices[it]?.takeIf(List<DataPoint>::isNotEmpty) }
        val defSeries = defensive.mapNotNull { prices[it]?.takeIf(List<DataPoint>::isNotEmpty) }
        if (cycSeries.isEmpty() || defSeries.isEmpty()) return emptyList<DataPoint>().also { store(cacheKey, it) }

        val monthlyReturns = prices.mapValues { (_, series) ->
            series.sortedBy { it.timestamp }.zipWithNext { prev, curr ->
                if (prev.value == 0f) null
                else DataPoint(curr.timestamp, (curr.value / prev.value) - 1f)
            }.mapNotNull { it }
        }

        val out = alignedAverageDifference(cyclical, defensive, monthlyReturns) { cycAvg, defAvg, ts, prev ->
            val prevGross = (prev?.value ?: 0f) + 1f
            val next = prevGross * ((1f + cycAvg) / (1f + defAvg).coerceAtLeast(0.0001f))
            DataPoint(ts, next - 1f)
        }

        val cutoff = System.currentTimeMillis() - yearsBack * 365L * 24L * 60L * 60L * 1000L
        return out.filter { it.timestamp >= cutoff }.also { store(cacheKey, it) }
    }

    /** Panel E: 13F proxy using cyclical vs defensive ETF volume acceleration. */
    suspend fun load13fProxy(yearsBack: Int = 11): List<DataPoint> {
        val cacheKey = "thirteenf_proxy_$yearsBack"
        cached(cacheKey)?.let { return it }

        val cyclical = listOf("XLY", "XLI", "XLB", "XLF")
        val defensive = listOf("XLP", "XLU", "XLV", "XLRE")
        val allTickers = cyclical + defensive

        val volumes = allTickers.associateWith { ticker ->
            runCatching { fetchYahooMonthlySeries(ticker, "volume") }.getOrDefault(emptyList())
        }.filterValues { it.isNotEmpty() }

        val smoothed = volumes.mapValues { (_, series) -> rollingAverage(series.sortedBy { it.timestamp }, 3) }
        val accel = smoothed.mapValues { (_, series) ->
            series.zipWithNextIndexed(3) { prev, curr ->
                if (prev.value == 0f) null
                else DataPoint(curr.timestamp, (curr.value / prev.value) - 1f)
            }.mapNotNull { it }
        }

        val out = alignedAverageDifference(cyclical, defensive, accel) { cycAvg, defAvg, ts, _ ->
            DataPoint(ts, cycAvg - defAvg)
        }

        val cutoff = System.currentTimeMillis() - yearsBack * 365L * 24L * 60L * 60L * 1000L
        return out.filter { it.timestamp >= cutoff }.also { store(cacheKey, it) }
    }

    private suspend fun fetchYahooMonthlySeries(ticker: String, field: String): List<DataPoint> = withContext(Dispatchers.IO) {
        val url = "https://query1.finance.yahoo.com/v8/finance/chart/$ticker?interval=1mo&range=15y"
        val req = Request.Builder()
            .url(url)
            .addHeader("User-Agent", "Mozilla/5.0")
            .addHeader("Accept", "application/json")
            .build()
        http.newCall(req).execute().use { response ->
            if (!response.isSuccessful) return@withContext emptyList()
            val json = JSONObject(response.body!!.string())
            val item = json.optJSONObject("chart")?.optJSONArray("result")?.optJSONObject(0)
                ?: return@withContext emptyList()
            val timestamps = item.optJSONArray("timestamp") ?: return@withContext emptyList()
            val indicators = item.optJSONObject("indicators") ?: return@withContext emptyList()
            val values = when (field) {
                "volume" -> indicators.optJSONArray("quote")?.optJSONObject(0)?.optJSONArray("volume")
                else -> indicators.optJSONArray("adjclose")?.optJSONObject(0)?.optJSONArray("adjclose")
            } ?: return@withContext emptyList()

            (0 until timestamps.length()).mapNotNull { i ->
                val value = values.optDouble(i, Double.NaN)
                if (value.isNaN()) null else DataPoint(timestamps.getLong(i) * 1000L, value.toFloat())
            }.sortedBy { it.timestamp }
        }
    }

    private fun rollingAverage(series: List<DataPoint>, window: Int): List<DataPoint> {
        if (series.size < window) return emptyList()
        return series.mapIndexedNotNull { idx, point ->
            if (idx + 1 < window) null
            else {
                val slice = series.subList(idx + 1 - window, idx + 1)
                DataPoint(point.timestamp, slice.map { it.value }.average().toFloat())
            }
        }
    }

    private fun <T> List<T>.zipWithNextIndexed(stepBack: Int, transform: (T, T) -> T?): List<T?> {
        if (size <= stepBack) return emptyList()
        return (stepBack until size).map { idx -> transform(this[idx - stepBack], this[idx]) }
    }

    private fun alignedAverageDifference(
        cyclical: List<String>,
        defensive: List<String>,
        data: Map<String, List<DataPoint>>,
        buildPoint: (cycAvg: Float, defAvg: Float, ts: Long, prev: DataPoint?) -> DataPoint,
    ): List<DataPoint> {
        val allTimestamps = data.values.flatten().map { it.timestamp }.distinct().sorted()
        val byTicker = data.mapValues { (_, series) -> series.associateBy { it.timestamp } }
        val out = mutableListOf<DataPoint>()
        for (ts in allTimestamps) {
            val cyc = cyclical.mapNotNull { byTicker[it]?.get(ts)?.value }
            val def = defensive.mapNotNull { byTicker[it]?.get(ts)?.value }
            if (cyc.isEmpty() || def.isEmpty()) continue
            val point = buildPoint(cyc.average().toFloat(), def.average().toFloat(), ts, out.lastOrNull())
            out += point
        }
        return out
    }

    /** Clear all cached data (used by pull-to-refresh). */
    fun clearCache() = cache.clear()
}
