package com.lance.gaimedashboard.data

/**
 * A single time-series observation.
 * [timestamp] is epoch-milliseconds (UTC), [value] is the float measurement.
 */
data class DataPoint(val timestamp: Long, val value: Float)

/**
 * Compute Year-over-Year change (%) for a monthly series.
 * Requires at least 13 data points sorted by timestamp ascending.
 */
fun List<DataPoint>.computeYoY(): List<DataPoint> {
    if (size < 13) return emptyList()
    val sorted = sortedBy { it.timestamp }
    return (12 until sorted.size).mapNotNull { i ->
        val prev = sorted[i - 12].value
        if (prev == 0f) null
        else DataPoint(sorted[i].timestamp, (sorted[i].value - prev) / Math.abs(prev) * 100f)
    }
}

/** Return only data points within the last [years] years. */
fun List<DataPoint>.withinYears(years: Int): List<DataPoint> {
    val cutoff = System.currentTimeMillis() - years * 365L * 24L * 60L * 60L * 1000L
    return filter { it.timestamp >= cutoff }
}
