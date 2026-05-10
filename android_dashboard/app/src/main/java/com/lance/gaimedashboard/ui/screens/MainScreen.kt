package com.lance.gaimedashboard.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Public
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.ShowChart
import androidx.compose.material.icons.filled.Speed
import androidx.compose.material.icons.filled.TrendingUp
import androidx.compose.material.icons.filled.WaterDrop
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.lance.gaimedashboard.ui.components.IndicatorInfo
import com.lance.gaimedashboard.ui.theme.*
import com.lance.gaimedashboard.viewmodel.DashboardViewModel

private enum class Tab { DEMAND, COST, RISK, STOCK, MACRO }
private data class NavItem(val tab: Tab, val label: String, val icon: ImageVector)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(vm: DashboardViewModel = viewModel()) {
    var selectedTab by remember { mutableStateOf(Tab.DEMAND) }
    var showSettings by remember { mutableStateOf(false) }
    var rangeMenuExpanded by remember { mutableStateOf(false) }

    val navItems = listOf(
        NavItem(Tab.DEMAND, "需求感測",  Icons.Default.Speed),
        NavItem(Tab.COST,   "成本獲利",  Icons.Default.ShowChart),
        NavItem(Tab.RISK,   "風險流動",  Icons.Default.WaterDrop),
        NavItem(Tab.STOCK,  "股市比對",  Icons.Default.TrendingUp),
        NavItem(Tab.MACRO,  "總經指數",  Icons.Default.Public),
    )

    Scaffold(
        containerColor = Background,
        // 讓 Scaffold 正確消費系統 WindowInsets（含系統導覽列），避免內容被遮擋
        contentWindowInsets = WindowInsets.systemBars,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = "全球經濟雷達",
                            fontSize = 16.sp,
                            fontWeight = FontWeight.Bold,
                            color = OnSurface
                        )
                        Text(
                            text = "PMI · CLI · VIX · M1B · TAIEX",
                            fontSize = 10.sp,
                            color = OnSurfaceVar
                        )
                    }
                },
                actions = {
                    Box {
                        TextButton(onClick = { rangeMenuExpanded = true }) {
                            Text("${vm.rangeYears}Y", color = PrimaryTeal, fontWeight = FontWeight.SemiBold)
                        }
                        DropdownMenu(
                            expanded = rangeMenuExpanded,
                            onDismissRequest = { rangeMenuExpanded = false },
                            modifier = Modifier.background(SurfaceVariant)
                        ) {
                            listOf(3, 5, 8, 10).forEach { y ->
                                DropdownMenuItem(
                                    text = { Text("${y}Y", color = if (vm.rangeYears == y) PrimaryTeal else OnSurface) },
                                    onClick = { vm.rangeYears = y; rangeMenuExpanded = false }
                                )
                            }
                        }
                    }
                    IconButton(onClick = { showSettings = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "設定", tint = OnSurfaceVar)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Surface,
                    scrolledContainerColor = Surface
                ),
                // TopAppBar 消費 status bar insets
                windowInsets = TopAppBarDefaults.windowInsets
            )
        },
        bottomBar = {
            // NavigationBar 自動消費 navigation bar insets（加上系統導覽列高度）
            NavigationBar(
                containerColor = Surface,
                tonalElevation = 0.dp,
                windowInsets   = NavigationBarDefaults.windowInsets,
            ) {
                navItems.forEach { item ->
                    NavigationBarItem(
                        selected = selectedTab == item.tab,
                        onClick  = { selectedTab = item.tab },
                        icon     = { Icon(item.icon, contentDescription = null) },
                        label    = { Text(item.label, fontSize = 10.sp) },
                        colors   = NavigationBarItemDefaults.colors(
                            selectedIconColor   = PrimaryTeal,
                            selectedTextColor   = PrimaryTeal,
                            unselectedIconColor = OnSurfaceVar,
                            unselectedTextColor = OnSurfaceVar,
                            indicatorColor      = SurfaceVariant
                        )
                    )
                }
            }
        }
    ) { innerPadding ->
        PullToRefreshBox(
            isRefreshing = vm.isRefreshing,
            onRefresh    = { vm.loadAll() },
            modifier     = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .background(Background)
        ) {
            when (selectedTab) {
                Tab.DEMAND -> DemandScreen(vm)
                Tab.COST   -> CostScreen(vm)
                Tab.RISK   -> RiskScreen(vm)
                Tab.STOCK  -> StockScreen(vm)
                Tab.MACRO  -> MacroIndexScreen(vm)
            }
        }
    }

    if (showSettings) {
        SettingsDialog(vm = vm, onDismiss = { showSettings = false })
    }
}
