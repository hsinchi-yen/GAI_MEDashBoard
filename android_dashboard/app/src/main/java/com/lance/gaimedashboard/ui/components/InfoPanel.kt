package com.lance.gaimedashboard.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.lance.gaimedashboard.ui.theme.*

/** Data model for a collapsible indicator explanation panel. */
data class IndicatorInfo(
    val title: String,
    val summary: String,
    val details: String,          // Full zh-Hant explanation (rich text as plain string)
    val source: String,
    val investmentNote: String
)

/**
 * Collapsible information card displayed above each chart.
 * Tapping the header toggles the full explanation open/closed.
 */
@Composable
fun InfoPanel(info: IndicatorInfo, modifier: Modifier = Modifier) {
    var expanded by remember { mutableStateOf(false) }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(SurfaceVariant)
    ) {
        // Header – always visible
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(horizontal = 14.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text("ℹ️ ${info.title}", fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = PrimaryTeal)
                if (!expanded) {
                    Text(info.summary, fontSize = 11.sp, color = OnSurfaceVar, maxLines = 1)
                }
            }
            Icon(
                imageVector = if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore,
                contentDescription = if (expanded) "收起" else "展開",
                tint = PrimaryTeal.copy(alpha = 0.7f),
                modifier = Modifier.size(20.dp)
            )
        }

        // Expanded body
        AnimatedVisibility(
            visible = expanded,
            enter = expandVertically(animationSpec = tween(200)),
            exit  = shrinkVertically(animationSpec = tween(200))
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 14.dp, end = 14.dp, bottom = 14.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                HorizontalDivider(color = OutlineColor, thickness = 0.5.dp)
                Spacer(Modifier.height(2.dp))

                Text(info.details, fontSize = 12.sp, color = OnSurface, lineHeight = 18.sp)

                // Investment note with accent border
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(6.dp))
                        .background(SurfaceBright)
                        .padding(10.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Box(
                        Modifier
                            .width(3.dp)
                            .fillMaxHeight()
                            .background(Amber)
                            .align(Alignment.CenterVertically)
                    )
                    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        Text("📌 投資意義", fontSize = 11.sp, color = Amber, fontWeight = FontWeight.SemiBold)
                        Text(info.investmentNote, fontSize = 11.sp, color = OnSurfaceVar, lineHeight = 16.sp)
                    }
                }

                // Source
                Text(
                    "📎 資料來源：${info.source}",
                    fontSize = 10.sp,
                    color = OnSurfaceVar.copy(alpha = 0.7f)
                )
            }
        }
    }
}

// ── A shared section title composable ────────────────────────────────────────

@Composable
fun SectionTitle(icon: String, title: String, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(icon, fontSize = 16.sp)
        Text(title, style = MaterialTheme.typography.titleLarge, color = OnSurface)
    }
}

// ── Loading / Error placeholders ─────────────────────────────────────────────

@Composable
fun LoadingCard(message: String = "載入資料中…", modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .height(80.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(SurfaceVariant)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(20.dp),
            color = PrimaryTeal,
            strokeWidth = 2.dp
        )
        Text(message, fontSize = 13.sp, color = OnSurfaceVar)
    }
}

@Composable
fun ErrorCard(message: String, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(SurfaceVariant)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("⚠ 載入失敗", fontSize = 12.sp, color = Danger, fontWeight = FontWeight.SemiBold)
            Text(message, fontSize = 11.sp, color = OnSurfaceVar, maxLines = 2)
        }
        TextButton(onClick = onRetry) {
            Text("重試", color = PrimaryTeal, fontSize = 13.sp)
        }
    }
}

/** "請設定 FRED API Key" placeholder for FRED-dependent indicators. */
@Composable
fun NoApiKeyCard(modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(SurfaceVariant)
            .padding(16.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text("🔑", fontSize = 20.sp)
        Column {
            Text("需要 FRED API Key", fontSize = 13.sp, color = Amber, fontWeight = FontWeight.SemiBold)
            Text("請點右上角設定圖示輸入您的免費 API Key", fontSize = 11.sp, color = OnSurfaceVar)
        }
    }
}
