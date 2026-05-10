package com.lance.gaimedashboard.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val DarkColors = darkColorScheme(
    primary          = PrimaryTeal,
    onPrimary        = OnPrimary,
    primaryContainer = PrimaryTealDim,
    secondary        = ColorUS,
    tertiary         = ColorTW,
    background       = Background,
    surface          = Surface,
    surfaceVariant   = SurfaceVariant,
    onBackground     = OnSurface,
    onSurface        = OnSurface,
    onSurfaceVariant = OnSurfaceVar,
    outline          = OutlineColor,
    error            = Danger
)

@Composable
fun GaiMeDashboardTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColors,
        typography  = AppTypography,
        content     = content
    )
}
