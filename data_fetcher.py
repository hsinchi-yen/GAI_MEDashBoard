"""
data_fetcher.py — backward-compatibility shim.

All logic has been moved into the fetchers/ package.
Existing code that does `import data_fetcher as df` continues to work.
"""

from fetchers import *  # noqa: F401, F403
from fetchers import (
    compute_yoy,
    parse_minguo_ym as _parse_minguo_ym,
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
    fetch_taiwan_exports_amount,
    fetch_cbc_money_supply,
    fetch_taiwan_pmi,
    fetch_tsmc_revenue_yoy,
    fetch_taiex_yoy,
    fetch_tw_institutional,
    fetch_ism_pmi,
    fetch_ndc_leading_index,
    fetch_china_nbs_pmi,
    fetch_japan_economy_watchers,
    fetch_china_nbs_ppi_yoy,
    fetch_eurostat_ici,
    fetch_index_yoy,
    fetch_vkospi,
    fetch_etf_bulk,
    fetch_sector_rotation,
    fetch_13f_proxy,
    fetch_13f_smart_money,
    edgar_connectivity_test,
    SECTOR_ETFS,
    FRED_BASE,
    DBNOMICS_BASE,
)
from fetchers.yahoo_finance import (
    _etf_bulk_to_prices,
    _etf_bulk_to_volumes,
    _ALL_SECTOR_ETFS,
)

# Legacy name kept for any direct usage
_parse_minguo_ym = _parse_minguo_ym
