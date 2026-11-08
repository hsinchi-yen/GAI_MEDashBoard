"""13F smart-money ranking: sector classification and the net-flow table.

Pure functions, no Streamlit. The dashboard only draws what these return.

Issuer names come from 13F ``nameOfIssuer`` (upper case, abbreviated, cut to
30 characters with a trailing "…"), never tickers. Matching is therefore on
whole words: a keyword like ``MU`` must not hit ``COMMUNICATIONS``, and ``LLY``
must not hit ``ALLY FINL``. Two layers:

1. Company phrases ("ELI LILLY", "TAIWAN SEMI*"), longest phrase first.
2. Industry words ("PHARMA*", "BANCORP", "OIL") for names no phrase covers.

A token written with a trailing ``*`` matches by prefix (``APPLIED MAT*``
matches MATLS and MATERIALS). When the name itself was truncated, its last
word may be a prefix of the keyword.
"""
from __future__ import annotations

import re

import pandas as pd

OTHER = "其他"
ETF = "ETF"

# GICS 11 sectors, with semiconductors split out of IT (the reader tracks the
# Taiwan supply chain) and ETFs kept apart so they do not distort sector sums.
SECTOR_COLOR: dict[str, str] = {
    "資訊科技":   "rgba(55,138,221,0.85)",
    "半導體":     "rgba(127,119,221,0.85)",
    "通訊服務":   "rgba(156,39,176,0.85)",
    "非必需消費": "rgba(212,83,126,0.85)",
    "必需消費":   "rgba(233,120,160,0.85)",
    "金融":       "rgba(186,117,23,0.85)",
    "醫療保健":   "rgba(99,153,34,0.85)",
    "工業":       "rgba(136,135,128,0.85)",
    "能源":       "rgba(186,101,29,0.85)",
    "原物料":     "rgba(121,85,72,0.85)",
    "公用事業":   "rgba(0,150,136,0.85)",
    "房地產":     "rgba(255,160,0,0.85)",
    ETF:          "rgba(96,125,139,0.85)",
    OTHER:        "rgba(100,100,100,0.6)",
}
SECTORS: tuple[str, ...] = tuple(SECTOR_COLOR)

_COMPANIES: dict[str, tuple[str, ...]] = {
    "半導體": (
        "NVIDIA", "BROADCOM", "ADVANCED MICRO", "INTEL CORP", "QUALCOMM", "TEXAS INSTR*",
        "MICRON TECH*", "TAIWAN SEMI*", "LAM RESEARCH", "APPLIED MAT*", "KLA CORP", "ASML",
        "MARVELL", "MICROCHIP", "ON SEMI*", "ASTERA LABS", "ARM HOLDINGS", "SITIME",
        "SYNAPTICS", "CEREBRAS", "ANALOG DEVICES", "NXP SEMI*", "GLOBALFOUNDRIES",
        "MONOLITHIC POWER", "TERADYNE",
    ),
    "資訊科技": (
        "MICROSOFT", "APPLE INC", "ORACLE", "SALESFORCE", "INTERNATIONAL BUSINESS MACH*",
        "SERVICENOW", "ADOBE", "PALANTIR", "CROWDSTRIKE", "PALO ALTO NETWORKS", "CLOUDFLARE",
        "SNOWFLAKE", "DELL TECH*", "SUPER MICRO", "SEAGATE", "WESTERN DIGITAL", "SANDISK",
        "LUMENTUM", "AKAMAI", "A10 NETWORKS", "CYBERARK", "GEN DIGITAL", "SAP SE",
        "ARROW ELECTR*", "FLEX LTD", "TTM TECH*", "VIAVI", "BILL HOLDINGS", "APPLOVIN",
        "STRATEGY INC", "APPLIED DIGITAL", "NEBIUS", "CISCO", "ARISTA", "INTUIT",
        "SHOPIFY", "ACCENTURE", "BIT DIGITAL", "BITDEER", "TERAWULF", "GDS HLDGS",
        "CORNING", "AMPHENOL", "FORTINET", "WORKDAY", "DATADOG",
    ),
    "通訊服務": (
        "ALPHABET", "META PLATFORMS", "NETFLIX", "AT T", "T MOBILE", "VERIZON", "COMCAST",
        "CHARTER COMM*", "WARNER BROS", "SPOTIFY", "LIBERTY MEDIA", "LIONSGATE",
        "MATCH GROUP", "CINEMARK", "WALT DISNEY", "DISNEY", "NEW YORK TIMES",
        "TAKE TWO", "ELECTRONIC ARTS", "TENCENT",
    ),
    "非必需消費": (
        "AMAZON COM", "AMAZON", "TESLA", "HOME DEPOT", "BOOKING HLDGS", "BOOKING HOLDINGS",
        "DOORDASH", "DRAFTKINGS", "CARVANA", "CARNIVAL", "ROSS STORES", "DICKS SPORTING",
        "GAMESTOP", "ALIBABA", "JD COM", "MAKEMYTRIP", "TRIP COM", "NIO INC", "WHIRLPOOL",
        "LIFE TIME GROUP", "CRACKER BARREL", "PATRICK INDS", "COUPANG", "MCDONALDS",
        "NIKE", "STARBUCKS", "LOWES", "CHIPOTLE", "PDD HOLDINGS", "MERCADOLIBRE",
        "AIRBNB", "TJX",
    ),
    "必需消費": (
        "WALMART", "COSTCO", "PROCTER", "PEPSICO", "COCA COLA", "HERSHEY", "KROGER",
        "KEURIG", "TARGET CORP", "J J SNACK", "PHILIP MORRIS", "ALTRIA", "MONDELEZ",
        "COLGATE", "KRAFT HEINZ",
    ),
    "金融": (
        "JPMORGAN", "GOLDMAN SACHS", "MORGAN STANLEY", "BERKSHIRE", "BROOKFIELD CORP",
        "VISA INC", "MASTERCARD", "BANK OF AMER*", "BANK AMER*", "CITIGROUP", "WELLS FARGO",
        "AMERICAN EXPRESS", "CAPITAL ONE", "ALLY FINL", "CITIZENS FINL", "SCHWAB",
        "COINBASE", "SOFI", "ICICI BANK", "CIRCLE INTERNET", "BLACKROCK", "PAYPAL",
        "PROGRESSIVE CORP", "CHUBB", "S P GLOBAL", "MOODYS", "ROBINHOOD",
    ),
    "醫療保健": (
        "ELI LILLY", "JOHNSON JOHNSON", "UNITEDHEALTH", "ABBVIE", "MERCK", "ASTRAZENECA",
        "PFIZER", "BRISTOL MYERS", "BOSTON SCIENTIFIC", "INTUITIVE SURGICAL", "DEXCOM",
        "CARDINAL HEALTH", "CENTENE", "ACADIA HEALTHCARE", "BRIGHTSPRING", "BIOMARIN",
        "BRIDGEBIO", "GOSSAMER BIO", "NUVATION BIO", "VIRIDIAN", "TRANSMEDICS", "LIVANOVA",
        "MERIT MED", "ORGANON", "JAZZ", "THERMO FISHER", "ABBOTT", "AMGEN", "GILEAD",
        "NOVO NORDISK", "VERTEX PHARM*", "REGENERON", "DANAHER", "STRYKER",
    ),
    "工業": (
        "CATERPILLAR", "DELTA AIR", "GENERAL ELECTRIC", "GE AEROSPACE", "GE VERNOVA",
        "LOCKHEED MARTIN", "C H ROBINSON", "COPART", "KBR INC", "TEREX", "JOBY AVIATION",
        "SPACE EXPLORATION", "UBER TECH*", "WILLIS LEASE", "BLOOM ENERGY", "RTX CORP",
        "BOEING", "HONEYWELL", "UNION PACIFIC", "DEERE", "EATON", "T1 ENERGY",
    ),
    "能源": (
        "CHEVRON", "EXXON", "OCCIDENTAL", "BP PLC", "CABOT OIL", "CANADIAN NAT*",
        "NORTHERN OIL", "OVINTIV", "GOLAR LNG", "SASOL", "PEABODY", "CONOCOPHILLIPS",
        "SHELL PLC", "SCHLUMBERGER",
    ),
    "原物料": (
        "CRH PLC", "LINDE", "ALBEMARLE", "HUNTSMAN", "IAMGOLD", "KINROSS", "PURECYCLE",
        "FREEPORT", "NEWMONT", "SHERWIN WILLIAMS",
    ),
    "公用事業": (
        "ALLIANT ENERGY", "CENTERPOINT", "FIRSTENERGY", "SOUTHERN CO", "WEC ENERGY",
        "CONSTELLATION ENERGY", "VISTRA", "NEXTERA", "DUKE ENERGY",
    ),
    "房地產": (
        "CUSHMAN", "OPENDOOR", "PROLOGIS", "EQUINIX", "AMERICAN TOWER", "FERMI INC",
    ),
    ETF: (
        "ISHARES", "SPDR", "INVESCO QQQ", "VANECK", "DIREXION", "SELECT SECTOR",
        "UNITED STS OIL", "PROSHARES", "VANGUARD", "GRAYSCALE",
    ),
}

# Second layer: words that name an industry, used only when no company matched.
_INDUSTRY_WORDS: dict[str, tuple[str, ...]] = {
    "半導體":   ("SEMICONDUCTOR*",),
    "醫療保健": ("PHARMA*", "THERAPEUTICS", "BIO", "BIOSCIENCES", "BIOTECH*", "BIOPHARMA*",
                 "HEALTH", "HEALTHCARE", "MEDICAL", "SURGICAL", "ONCOLOGY", "GENOMICS"),
    "金融":     ("BANK", "BANCORP", "BANCSHARES", "FINL", "FINANCIAL", "INSURANCE"),
    "能源":     ("OIL", "PETE", "PETROLEUM", "LNG", "MIDSTREAM"),
    "原物料":   ("GOLD", "SILVER", "MINING", "MINES", "CHEMICAL*", "STEEL", "COPPER", "LITHIUM"),
    "公用事業": ("UTILITIES",),
    "房地產":   ("REIT", "REALTY", "PROPERTIES"),
    "資訊科技": ("SOFTWARE", "NETWORKS", "CYBER*"),
    ETF:        ("ETF",),
}

_TOKEN = re.compile(r"[A-Z0-9]+")
_CUSIP = re.compile(r"^[0-9A-Z]{8}[0-9]$")


def _phrase_tokens(phrase: str) -> tuple[str, ...]:
    out = []
    for word in phrase.split():
        star = word.endswith("*")
        parts = _TOKEN.findall(word.upper())
        if star and parts:
            parts[-1] += "*"
        out.extend(parts)
    return tuple(out)


def _build(table: dict[str, tuple[str, ...]]) -> list[tuple[tuple[str, ...], str]]:
    # Longer phrases first, so "AMAZON COM" wins over "AMAZON" whatever the order.
    rules =[(_phrase_tokens(p), sector) for sector, phrases in table.items() for p in phrases]
    return sorted(rules, key=lambda r: (-len(r[0]), -sum(map(len, r[0]))))


_COMPANY_RULES = _build(_COMPANIES)
_INDUSTRY_RULES = _build(_INDUSTRY_WORDS)


def _word_matches(key: str, word: str, truncated_last: bool) -> bool:
    if key.endswith("*"):
        stem = key[:-1]
        return word.startswith(stem) or (truncated_last and len(word) >= 3 and stem.startswith(word))
    if word == key:
        return True
    return truncated_last and len(word) >= 3 and key.startswith(word)


def _match(rules, words: list[str], truncated: bool) -> str | None:
    n = len(words)
    for keys, sector in rules:
        k = len(keys)
        for start in range(n - k + 1):
            if all(_word_matches(keys[i], words[start + i],
                                 truncated and start + i == n - 1)
                   for i in range(k)):
                return sector
    return None


def looks_like_cusip(name: str) -> bool:
    return bool(_CUSIP.match(name.strip().upper())) and any(c.isdigit() for c in name[:6])


def classify_sector(name: str) -> str:
    """Issuer name → sector label in ``SECTORS``; unknown names → ``其他``."""
    if not name or looks_like_cusip(name):
        return OTHER
    upper = name.upper().strip()
    truncated = upper.endswith("…")
    # "&" joins words ("AT&T", "J & J") rather than separating meaningful parts.
    words = _TOKEN.findall(upper.replace("&", " "))
    return (_match(_COMPANY_RULES, words, truncated)
            or _match(_INDUSTRY_RULES, words, truncated)
            or OTHER)


RANK_COLUMNS = ["排名", "持倉名稱", "板塊", "淨增持（$M）", "同向基金數", "訊號"]
SIDES = ("全部", "買方", "賣方")


def build_rank_table(smart: dict | None, side: str = "全部") -> pd.DataFrame:
    """Net-flow ranking from the 13F snapshot.

    Buys come from ``top_buy_value`` and sells from ``top_sell_value`` (both
    ``(name, $M, n_funds)``). ``side`` picks 全部 / 買方 / 賣方. Rows are ordered
    by net value, largest inflow first; for 賣方 the largest outflow comes first.
    """
    smart = smart or {}
    rows = []
    if side in ("全部", "買方"):
        rows += [(n, float(v), int(f)) for n, v, f in smart.get("top_buy_value") or []]
    if side in ("全部", "賣方"):
        rows += [(n, float(v), int(f)) for n, v, f in smart.get("top_sell_value") or []]
    if not rows:
        return pd.DataFrame(columns=RANK_COLUMNS)

    df = pd.DataFrame(rows, columns=["持倉名稱", "淨增持（$M）", "同向基金數"])
    df = df.sort_values("淨增持（$M）", ascending=(side == "賣方"), kind="stable")
    df["板塊"] = df["持倉名稱"].map(classify_sector)
    df["訊號"] = df["淨增持（$M）"].map(lambda v: "🟢 買入" if v > 0 else "🔴 賣出")
    df["排名"] = range(1, len(df) + 1)
    return df[RANK_COLUMNS].reset_index(drop=True)


def sector_net_flow(rank_df: pd.DataFrame) -> pd.DataFrame:
    """Net $M per sector (buys minus sells), largest inflow first."""
    if rank_df is None or rank_df.empty:
        return pd.DataFrame(columns=["板塊", "淨增持（$M）", "檔數"])
    out = (rank_df.groupby("板塊", sort=False)["淨增持（$M）"]
           .agg(["sum", "size"]).reset_index()
           .rename(columns={"sum": "淨增持（$M）", "size": "檔數"}))
    return out.sort_values("淨增持（$M）", ascending=False, kind="stable").reset_index(drop=True)
