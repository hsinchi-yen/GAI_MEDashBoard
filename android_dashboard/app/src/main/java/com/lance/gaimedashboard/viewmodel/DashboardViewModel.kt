package com.lance.gaimedashboard.viewmodel

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.lance.gaimedashboard.data.ApiClient
import com.lance.gaimedashboard.data.DataPoint
import com.lance.gaimedashboard.data.LoadState
import com.lance.gaimedashboard.data.MacroIndexEngine
import com.lance.gaimedashboard.data.MacroIndexResult
import kotlinx.coroutines.async
import kotlinx.coroutines.launch

class DashboardViewModel(app: Application) : AndroidViewModel(app) {

    private val defaultFredKey = "13bf3245b1fef176250249752ed063ef"
    private val prefs = app.getSharedPreferences("gdash_prefs", Context.MODE_PRIVATE)
    private val api = ApiClient()

    // ── Settings ──────────────────────────────────────────────────────────────

    var fredApiKey by mutableStateOf(prefs.getString("fred_key", defaultFredKey) ?: defaultFredKey)
        private set

    fun updateFredKey(key: String) {
        fredApiKey = key.trim()
        prefs.edit().putString("fred_key", fredApiKey).apply()
    }

    /** Time range filter applied locally to all charts. */
    var rangeYears by mutableIntStateOf(3)

    // ── Panel A: Demand ───────────────────────────────────────────────────────

    var pmiState: LoadState<Map<String, List<DataPoint>>> by mutableStateOf(LoadState.Idle)
    var retailState: LoadState<Map<String, List<DataPoint>>> by mutableStateOf(LoadState.Idle)
    var sentimentState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var exportState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var koreaExpState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var ndcLeadingState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)

    // ── Panel B: Cost ─────────────────────────────────────────────────────────

    var cliState: LoadState<Map<String, List<DataPoint>>> by mutableStateOf(LoadState.Idle)
    var busInvState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var semiPpiState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var realRateState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var scissorsState: LoadState<Map<String, List<DataPoint>>> by mutableStateOf(LoadState.Idle)
    var chinaPpiState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var brentState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var copperYoyState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var tsmcRevenueState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)

    // ── Panel C: Risk ─────────────────────────────────────────────────────────

    var vixState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var spreadState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var moneyState: LoadState<Map<String, List<DataPoint>>> by mutableStateOf(LoadState.Idle)
    var hySpreadState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var twdUsdState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)

    // ── Panel D: Stock Market Comparison ─────────────────────────────────────

    var sp500YoyState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var taiexYoyState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var fedFundsState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var t10y3mState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var usNewOrdersYoyState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)

    // ── Panel E: Global Macro Index ─────────────────────────────────────────

    var sectorRotationState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)
    var thirteenFProxyState: LoadState<List<DataPoint>> by mutableStateOf(LoadState.Idle)

    // ── Global refresh indicator ──────────────────────────────────────────────

    var isRefreshing by mutableStateOf(false)
        private set

    // ── Init ──────────────────────────────────────────────────────────────────

    init {
        loadAll()
    }

    // ── Loaders ───────────────────────────────────────────────────────────────

    fun loadAll() {
        viewModelScope.launch {
            isRefreshing = true
            api.clearCache()
            val a = async { loadPanelA() }
            val b = async { loadPanelB() }
            val c = async { loadPanelC() }
            val d = async { loadPanelD() }
            val e = async { loadPanelE() }
            a.await(); b.await(); c.await(); d.await(); e.await()
            isRefreshing = false
        }
    }

    fun refreshPanelA() = viewModelScope.launch { loadPanelA() }
    fun refreshPanelB() = viewModelScope.launch { loadPanelB() }
    fun refreshPanelC() = viewModelScope.launch { loadPanelC() }
    fun refreshPanelD() = viewModelScope.launch { loadPanelD() }
    fun refreshPanelE() = viewModelScope.launch { loadPanelE() }

    private suspend fun loadPanelA() {
        val key = fredApiKey
        // PMI – no key needed for DBnomics
        pmiState = LoadState.Loading
        pmiState = try {
            LoadState.Success(api.loadPmi(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "PMI 資料載入失敗")
        }
        // Export YoY
        exportState = LoadState.Loading
        exportState = try {
            LoadState.Success(api.loadExportYoY(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "出口資料載入失敗")
        }

        // Korea Exports YoY (new)
        koreaExpState = LoadState.Loading
        koreaExpState = try {
            LoadState.Success(api.loadKoreaExportsYoy(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "韓國出口載入失敗")
        }

        // NDC Leading Index (new)
        ndcLeadingState = LoadState.Loading
        ndcLeadingState = try {
            LoadState.Success(api.loadNdcLeadingIndex())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "NDC 領先指標載入失敗")
        }

        // US retail sales level + YoY
        retailState = LoadState.Loading
        retailState = try {
            LoadState.Success(api.loadRetailSales(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "零售銷售資料載入失敗")
        }

        // Consumer sentiment
        sentimentState = LoadState.Loading
        sentimentState = try {
            LoadState.Success(api.loadUmcsent(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "消費者信心載入失敗")
        }
    }

    private suspend fun loadPanelB() {
        val key = fredApiKey
        // CLI – no key needed
        cliState = LoadState.Loading
        cliState = try {
            LoadState.Success(api.loadCli())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "CLI 資料載入失敗")
        }

        // Business inventories
        busInvState = LoadState.Loading
        busInvState = try {
            LoadState.Success(api.loadBusinessInventories(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "商業庫存載入失敗")
        }

        // Semi PPI – needs FRED key
        semiPpiState = LoadState.Loading
        semiPpiState = try {
            LoadState.Success(api.loadSemiPpi(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "半導體 PPI 載入失敗")
        }

        // US 10Y real rate
        realRateState = LoadState.Loading
        realRateState = try {
            LoadState.Success(api.loadUsRealRate(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "實質利率載入失敗")
        }

        // Core CPI/PPI scissors
        scissorsState = LoadState.Loading
        scissorsState = try {
            LoadState.Success(api.loadCoreCpiPpiScissors(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "CPI/PPI 剪刀差載入失敗")
        }

        // China PPI YoY
        chinaPpiState = LoadState.Loading
        chinaPpiState = try {
            LoadState.Success(api.loadChinaPpiYoY())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "中國 PPI 載入失敗")
        }

        // Brent crude
        brentState = LoadState.Loading
        brentState = try {
            LoadState.Success(api.loadBrent(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "原油資料載入失敗")
        }

        // Copper YoY (new)
        copperYoyState = LoadState.Loading
        copperYoyState = try {
            LoadState.Success(api.loadCopperYoy(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "銅價 YoY 載入失敗")
        }

        // TSMC Revenue YoY (new)
        tsmcRevenueState = LoadState.Loading
        tsmcRevenueState = try {
            LoadState.Success(api.loadTsmcRevenueYoy())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "台積電營收 YoY 載入失敗")
        }
    }

    private suspend fun loadPanelC() {
        val key = fredApiKey
        // VIX
        vixState = LoadState.Loading
        vixState = try {
            LoadState.Success(api.loadVix(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "VIX 資料載入失敗")
        }
        // 10Y-2Y spread
        spreadState = LoadState.Loading
        spreadState = try {
            LoadState.Success(api.loadSpread(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "殖利率曲線載入失敗")
        }
        // Money supply YoY
        moneyState = LoadState.Loading
        moneyState = try {
            LoadState.Success(api.loadMoneyYoY(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "貨幣供給資料載入失敗")
        }

        // HY Spread (new)
        hySpreadState = LoadState.Loading
        hySpreadState = try {
            LoadState.Success(api.loadHySpread(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "HY 利差載入失敗")
        }

        // TWD/USD (new)
        twdUsdState = LoadState.Loading
        twdUsdState = try {
            LoadState.Success(api.loadTwdUsd(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "台幣匯率載入失敗")
        }
    }

    private suspend fun loadPanelD() {
        val key = fredApiKey

        sp500YoyState = LoadState.Loading
        sp500YoyState = try {
            LoadState.Success(api.loadSp500Yoy(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "S&P 500 資料載入失敗")
        }

        taiexYoyState = LoadState.Loading
        taiexYoyState = try {
            LoadState.Success(api.loadTaiwanStockYoy())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "TAIEX 資料載入失敗")
        }

        fedFundsState = LoadState.Loading
        fedFundsState = try {
            LoadState.Success(api.loadFedFundsRate(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "Fed Funds Rate 載入失敗")
        }

        t10y3mState = LoadState.Loading
        t10y3mState = try {
            LoadState.Success(api.loadT10y3m(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "10Y-3M 利差載入失敗")
        }

        usNewOrdersYoyState = LoadState.Loading
        usNewOrdersYoyState = try {
            LoadState.Success(api.loadUsNewOrdersYoy(key))
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "製造業新訂單載入失敗")
        }
    }

    private suspend fun loadPanelE() {
        sectorRotationState = LoadState.Loading
        sectorRotationState = try {
            LoadState.Success(api.loadSectorRotation())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "內部輪動資料載入失敗")
        }

        thirteenFProxyState = LoadState.Loading
        thirteenFProxyState = try {
            LoadState.Success(api.load13fProxy())
        } catch (e: Exception) {
            LoadState.Error(e.localizedMessage ?: "13F 代理資料載入失敗")
        }
    }

    fun currentMacroIndex(): MacroIndexResult = MacroIndexEngine.compute(currentMacroSeries())

    private fun currentMacroSeries(): Map<String, List<DataPoint>> {
        val pmi = (pmiState as? LoadState.Success)?.data.orEmpty()
        val retail = (retailState as? LoadState.Success)?.data.orEmpty()
        val cli = (cliState as? LoadState.Success)?.data.orEmpty()
        val scissors = (scissorsState as? LoadState.Success)?.data.orEmpty()
        val money = (moneyState as? LoadState.Success)?.data.orEmpty()

        return mapOf(
            "US_PMI" to pmi["us"].orEmpty(),
            "TW_PMI" to pmi["tw"].orEmpty(),
            "CN_PMI" to pmi["cn"].orEmpty(),
            "EU_PMI" to pmi["eu"].orEmpty(),
            "US_NEW_ORDERS_YOY" to successList(usNewOrdersYoyState),
            "TW_EXP_YOY" to successList(exportState),
            "KR_EXP_YOY" to successList(koreaExpState),
            "US_RETAIL_YOY" to retail["yoy"].orEmpty(),
            "US_CLI" to cli["us"].orEmpty(),
            "CN_CLI" to cli["cn"].orEmpty(),
            "JP_CLI" to cli["jp"].orEmpty(),
            "EU_CLI" to cli["eu"].orEmpty(),
            "KR_CLI" to cli["kr"].orEmpty(),
            "NDC_LEADING" to successList(ndcLeadingState),
            "US_CORE_CPI_YOY" to scissors["cpi_yoy"].orEmpty(),
            "US_CORE_PPI_YOY" to scissors["ppi_yoy"].orEmpty(),
            "CPI_PPI_SCISSORS" to scissors["scissors"].orEmpty(),
            "CN_PPI_YOY" to successList(chinaPpiState),
            "HY_SPREAD" to successList(hySpreadState),
            "T10Y3M" to successList(t10y3mState),
            "TW_M1B_YOY" to money["tw_m1b"].orEmpty(),
            "TW_M2_YOY" to money["tw_m2"].orEmpty(),
            "VIX" to successList(vixState),
            "TWD_USD" to successList(twdUsdState),
            "COPPER_YOY" to successList(copperYoyState),
            "SECTOR_ROTATION" to successList(sectorRotationState),
            "THIRTEENF_NET_ADD" to successList(thirteenFProxyState),
        )
    }

    private fun successList(state: LoadState<List<DataPoint>>): List<DataPoint> =
        (state as? LoadState.Success)?.data.orEmpty()
}
