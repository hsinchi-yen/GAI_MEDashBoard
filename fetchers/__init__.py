"""
fetchers — modular data fetching package for GAI_MEDashBoard.

Public API re-exported here for backward compatibility with
existing `import data_fetcher` callers (via data_fetcher.py shim).
"""

from .utils import compute_yoy, parse_minguo_ym, roc_to_ad, fetch_with_retry, DEFAULT_HEADERS

from .fred import (
    fetch_fred,
    fetch_dbnomics,
    fetch_dxy,
    fetch_china_credit_impulse,
    fetch_copper_yoy,
    fetch_hy_spread,
    fetch_twd_usd,
    fetch_korea_exports_yoy,
    fetch_fed_funds_rate,
    fetch_t10y3m,
    fetch_us_new_orders_yoy,
    fetch_sp500_yoy,
    FRED_BASE,
    DBNOMICS_BASE,
)

from .taiwan import (
    fetch_taiwan_exports_amount,
    fetch_cbc_money_supply,
    fetch_taiwan_pmi,
    fetch_tsmc_revenue_yoy,
    fetch_taiex_yoy,
    fetch_tw_institutional,
)

from .global_macro import (
    fetch_ism_pmi,
    fetch_ndc_leading_index,
    fetch_china_nbs_pmi,
    fetch_japan_economy_watchers,
    fetch_china_nbs_ppi_yoy,
    fetch_eurostat_ici,
)

from .yahoo_finance import (
    fetch_index_yoy,
    fetch_vkospi,
    fetch_etf_bulk,
    fetch_sector_rotation,
    fetch_13f_proxy,
    SECTOR_ETFS,
)

from .edgar_13f import (
    fetch_13f_smart_money,
    edgar_connectivity_test,
    _13F_MAJOR_FUNDS,
)

from .taiwan_sector import (
    fetch_tw_sector_indices,
    fetch_tw_sector_turnover,
    fetch_tw_sector_institutional,
    calc_sector_momentum,
    detect_rotation_signal,
    SECTOR_NAMES,
)

__all__ = [
    # utils
    "compute_yoy", "parse_minguo_ym", "roc_to_ad", "fetch_with_retry", "DEFAULT_HEADERS",
    # fred
    "fetch_fred", "fetch_dbnomics", "fetch_dxy", "fetch_china_credit_impulse",
    "fetch_copper_yoy", "fetch_hy_spread", "fetch_twd_usd", "fetch_korea_exports_yoy",
    "fetch_fed_funds_rate", "fetch_t10y3m", "fetch_us_new_orders_yoy", "fetch_sp500_yoy",
    "FRED_BASE", "DBNOMICS_BASE",
    # taiwan
    "fetch_taiwan_exports_amount", "fetch_cbc_money_supply", "fetch_taiwan_pmi",
    "fetch_tsmc_revenue_yoy", "fetch_taiex_yoy", "fetch_tw_institutional",
    # global_macro
    "fetch_ism_pmi", "fetch_ndc_leading_index", "fetch_china_nbs_pmi",
    "fetch_japan_economy_watchers", "fetch_china_nbs_ppi_yoy", "fetch_eurostat_ici",
    # yahoo_finance
    "fetch_index_yoy", "fetch_vkospi", "fetch_etf_bulk", "fetch_sector_rotation",
    "fetch_13f_proxy", "SECTOR_ETFS",
    # edgar_13f
    "fetch_13f_smart_money", "edgar_connectivity_test", "_13F_MAJOR_FUNDS",
    # taiwan_sector
    "fetch_tw_sector_indices", "fetch_tw_sector_turnover", "fetch_tw_sector_institutional",
    "calc_sector_momentum", "detect_rotation_signal", "SECTOR_NAMES",
]
