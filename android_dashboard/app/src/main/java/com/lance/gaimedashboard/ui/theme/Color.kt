package com.lance.gaimedashboard.ui.theme

import androidx.compose.ui.graphics.Color

// ── App palette ──────────────────────────────────────────────────────────────
val Background      = Color(0xFF0D1117)
val Surface         = Color(0xFF161B22)
val SurfaceVariant  = Color(0xFF21262D)
val SurfaceBright   = Color(0xFF2D333B)

val PrimaryTeal     = Color(0xFF4DD0CF)
val PrimaryTealDim  = Color(0xFF2A8A89)
val OnPrimary       = Color(0xFF001F1F)

val OutlineColor    = Color(0xFF30363D)
val OnSurface       = Color(0xFFE6EDF3)
val OnSurfaceVar    = Color(0xFF8B949E)
val Amber           = Color(0xFFFBBF24)
val Success         = Color(0xFF3FB950)
val Danger          = Color(0xFFF85149)

// ── Country series colours ────────────────────────────────────────────────────
val ColorUS  = Color(0xFF60A5FA)   // Blue
val ColorCN  = Color(0xFFF87171)   // Red
val ColorTW  = Color(0xFF34D399)   // Green
val ColorJP  = Color(0xFFFBBF24)   // Amber
val ColorEU  = Color(0xFFA78BFA)   // Purple
val ColorKR  = Color(0xFFF472B6)   // Pink

val countryColors = mapOf(
    "us" to ColorUS, "cn" to ColorCN, "tw" to ColorTW,
    "jp" to ColorJP, "eu" to ColorEU, "kr" to ColorKR
)

val countryLabels = mapOf(
    "us" to "🇺🇸 美國", "cn" to "🇨🇳 中國", "tw" to "🇹🇼 台灣",
    "jp" to "🇯🇵 日本", "eu" to "🇪🇺 歐洲", "kr" to "🇰🇷 韓國"
)
