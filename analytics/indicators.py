"""Indicator catalogue: what each macro series is and how to read it.

The dashboard's `data` dict holds ~40 series. This registry states, in one place,
which way is bullish for risk assets, how often a series updates, and why an
investor should care. Everything downstream (trend radar, verdict, page briefs)
reads from here rather than hard-coding per-series rules.

`polarity`:
    +1  higher is bullish for risk assets
    -1  lower is bullish for risk assets
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Indicator:
    key: str
    name: str
    theme: str        # demand | trade | cost | liquidity | market
    polarity: int     # +1 / -1, see module docstring
    unit: str         # display suffix ("%", " bps", "")
    freq: str         # daily | monthly | quarterly
    role: str         # leading | coincident | lagging
    why: str          # one-line reason an investor cares
    decimals: int = 1

    @property
    def page(self) -> str:
        """Dashboard page that carries this indicator's detailed charts."""
        return THEME_PAGE[self.theme]


THEMES: dict[str, str] = {
    "demand":    "需求",
    "trade":     "貿易信用",
    "cost":      "成本通膨",
    "liquidity": "流動風險",
    "market":    "股市",
}

THEME_PAGE: dict[str, str] = {
    "demand":    "demand",
    "trade":     "demand",
    "cost":      "cost",
    "liquidity": "liquidity",
    "market":    "equity",
}

ROLE_LABELS: dict[str, str] = {
    "leading":    "領先",
    "coincident": "同時",
    "lagging":    "落後",
}

# Days a series may go without an update before it counts as stale. Monthly points
# are dated the 1st and published up to ~5 weeks after month-end, so the newest print
# is routinely ~95 days old just before the next release.
STALE_DAYS: dict[str, int] = {"daily": 10, "monthly": 110, "quarterly": 200}

_CATALOGUE: tuple[Indicator, ...] = (
    # ── Demand ────────────────────────────────────────────────────────────────
    Indicator("US_PMI", "美國製造業 PMI", "demand", +1, "", "monthly", "leading",
              "50 為榮枯線；全球製造業景氣的風向球"),
    Indicator("TW_PMI", "台灣製造業 PMI", "demand", +1, "", "monthly", "leading",
              "反映電子供應鏈訂單，對台股最直接"),
    Indicator("CN_PMI", "中國官方 PMI", "demand", +1, "", "monthly", "leading",
              "全球原物料與亞洲出口的需求來源"),
    Indicator("EU_PMI", "歐洲工業信心", "demand", +1, "", "monthly", "leading",
              "歐元區製造業景氣溫度"),
    Indicator("JP_PMI", "日本景氣觀察", "demand", +1, "", "monthly", "leading",
              "第一線服務業對景氣的體感"),
    Indicator("US_NEW_ORDERS_YOY", "美國製造業新訂單 YoY", "demand", +1, "%", "monthly", "leading",
              "訂單領先生產，先於營收反映"),
    Indicator("UMCSENT", "密西根消費者信心", "demand", +1, "", "monthly", "leading",
              "消費占美國 GDP 約七成，信心領先支出"),
    Indicator("US_RETAIL_YOY", "美國零售銷售 YoY", "demand", +1, "%", "monthly", "coincident",
              "終端需求的實際成交"),
    Indicator("NDC_LEADING", "台灣景氣領先指標", "demand", +1, "", "monthly", "leading",
              "國發會編製，領先台灣景氣約 3-6 個月", 2),
    Indicator("NDC_LIGHT_SCORE", "台灣景氣對策信號", "demand", +1, "", "monthly", "coincident",
              "9 項綜合分數；≥32 紅燈過熱、≤16 藍燈低迷", 0),
    # ── Trade & credit ────────────────────────────────────────────────────────
    Indicator("TW_EXP_YOY", "台灣出口 YoY", "trade", +1, "%", "monthly", "coincident",
              "台灣 GDP 的核心引擎"),
    Indicator("KR_EXP_YOY", "韓國出口 YoY", "trade", +1, "%", "monthly", "leading",
              "全球最早公布的貿易數據，半導體景氣先行指標"),
    Indicator("TSMC_REVENUE_YOY", "台積電營收 YoY", "trade", +1, "%", "monthly", "coincident",
              "AI 與先進製程需求的實際成績單"),
    Indicator("COPPER_YOY", "銅價 YoY", "trade", +1, "%", "monthly", "leading",
              "「銅博士」：工業需求的市場定價"),
    Indicator("CHINA_CREDIT_IMPULSE", "中國信貸脈衝", "trade", +1, "%", "monthly", "leading",
              "領先全球總需求約 9-12 個月"),
    # ── Cost & inflation ──────────────────────────────────────────────────────
    Indicator("US_CORE_CPI_YOY", "美國核心 CPI YoY", "cost", -1, "%", "monthly", "lagging",
              "決定 Fed 能否降息", 2),
    Indicator("US_CORE_PPI_YOY", "美國核心 PPI YoY", "cost", -1, "%", "monthly", "lagging",
              "企業投入成本，領先 CPI", 2),
    Indicator("CN_PPI_YOY", "中國 PPI YoY", "cost", +1, "%", "monthly", "coincident",
              "脫離通縮代表中國需求回溫，對循環股為正向"),
    Indicator("BRENT", "布蘭特原油", "cost", -1, "", "daily", "coincident",
              "能源進口國（台韓日）的成本壓力", 1),
    Indicator("US_REAL_RATE", "美國 10Y 實質利率", "cost", -1, "%", "daily", "coincident",
              "成長股估值的折現率", 2),
    # ── Liquidity & risk ──────────────────────────────────────────────────────
    Indicator("VIX", "VIX 恐慌指數", "liquidity", -1, "", "daily", "coincident",
              ">30 市場壓力，<15 過度安逸"),
    Indicator("HY_SPREAD", "高收益債利差", "liquidity", -1, " bps", "daily", "leading",
              "信用市場對違約風險的定價，常早於股市示警", 0),
    Indicator("T10Y3M", "美債 10Y-3M 利差", "liquidity", +1, " pp", "daily", "leading",
              "紐約 Fed 衰退機率模型的輸入，倒掛後轉正尤須留意", 2),
    Indicator("T10Y2Y", "美債 10Y-2Y 利差", "liquidity", +1, " pp", "daily", "leading",
              "殖利率曲線斜率，反映市場對景氣與政策的預期", 2),
    Indicator("FED_FUNDS", "聯邦基金利率", "liquidity", -1, "%", "monthly", "lagging",
              "全球資金成本的錨", 2),
    Indicator("DXY", "美元指數（廣義）", "liquidity", -1, "", "daily", "coincident",
              "美元走強壓縮新興市場資金空間"),
    Indicator("TWD_USD", "美元兌台幣", "liquidity", -1, "", "daily", "coincident",
              "數值下降＝台幣升值，外資通常同步流入", 3),
    Indicator("TW_M1B_YOY", "台灣 M1B YoY", "liquidity", +1, "%", "monthly", "leading",
              "活錢增速，領先台股資金行情", 2),
    Indicator("TW_M2_YOY", "台灣 M2 YoY", "liquidity", +1, "%", "monthly", "coincident",
              "廣義貨幣；M1B 高於 M2 為黃金交叉", 2),
    Indicator("US_M1_YOY", "美國 M1 YoY", "liquidity", +1, "%", "monthly", "leading",
              "美元體系的活錢增速"),
    # ── Equity markets ────────────────────────────────────────────────────────
    Indicator("SP500_YOY", "S&P 500 YoY", "market", +1, "%", "monthly", "coincident",
              "全球風險資產的基準"),
    Indicator("TAIEX_YOY", "台灣加權 YoY", "market", +1, "%", "monthly", "coincident",
              "台股長期動能"),
    Indicator("NIKKEI_YOY", "日經 225 YoY", "market", +1, "%", "monthly", "coincident",
              "日本企業與匯率循環的縮影"),
    Indicator("KOSPI_YOY", "KOSPI YoY", "market", +1, "%", "monthly", "coincident",
              "記憶體循環的高 beta 市場"),
    Indicator("HSI_YOY", "恆生指數 YoY", "market", +1, "%", "monthly", "coincident",
              "中國境外資金的情緒"),
    Indicator("CSI300_YOY", "滬深 300 YoY", "market", +1, "%", "monthly", "coincident",
              "中國境內資金的情緒"),
    Indicator("VKOSPI", "VKOSPI 韓股波動率", "market", -1, "", "daily", "coincident",
              "亞洲半導體權重市場的恐慌指標"),
    Indicator("SECTOR_ROTATION", "循環 vs 防禦輪動", "market", +1, "", "monthly", "leading",
              "資金偏向景氣循環類股代表風險偏好上升", 3),
)

REGISTRY: dict[str, Indicator] = {ind.key: ind for ind in _CATALOGUE}


def by_theme(theme: str) -> list[Indicator]:
    """Indicators of one theme, in catalogue order."""
    return [ind for ind in _CATALOGUE if ind.theme == theme]


def all_indicators() -> list[Indicator]:
    return list(_CATALOGUE)
