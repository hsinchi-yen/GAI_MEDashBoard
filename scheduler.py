"""
scheduler.py — nightly background data updater for GAI_MEDashBoard.

Runs as a standalone process (docker-compose service: scheduler).
Fetches all macro indicators and writes results to SQLite via db_manager.

Fetch-year strategy
───────────────────
  _YEARS_INITIAL = 15  → used by --run-now  (INSERT OR IGNORE, full history)
  _YEARS_DELTA   = 2   → used by daily jobs (INSERT OR REPLACE last 30 days only)

  Using 2 years for delta covers publication lags in monthly series without
  pulling unnecessary history.  db_manager.write(initial=False) filters down
  to DELTA_DAYS (30) rows before writing, so the extra fetch is cheap.

Schedule
────────
  02:00 Asia/Taipei daily         → all macro indicators
  02:30 Asia/Taipei daily         → Taiwan sector indices + turnover
  06:00 Asia/Taipei Mon + Thu     → US sector ETF rotation + 13F smart money
  03:00 Asia/Taipei 1st of month  → DB trim (15-year window) + WAL checkpoint

Indicators covered
──────────────────
  FRED         : VIX, retail, Michigan, inventories, semi-PPI, yields (11 mats),
                 T10Y2Y, real-rate components, CPI/PPI, M1, Brent,
                 HY spread, TWD/USD, T10Y3M, DFF, copper, Korea exports,
                 US new orders, S&P 500 YoY, DXY, China credit impulse
  DBnomics     : ISM PMI (5 sub-indices), OECD CLI (US/CN/JP/EU/KR)
  Taiwan govt  : MOF exports, CBC M1B/M2, CIER PMI, MOPS TSMC revenue, NDC leading
  Global scrape: NBS PMI (CN), Japan economy watchers, NBS PPI YoY, Eurostat ICI
  Yahoo Finance: TAIEX YoY, VKOSPI, N225/KS11/HSI/CSI300 YoY
  TWSE T86     : Institutional net buy/sell (5-day & 20-day snapshots)
  TWSE MI_INDEX: Taiwan 19-sector daily indices + turnover
  SEC EDGAR    : 13F smart money (20 major funds, quarterly snapshot)
  Yahoo ETF    : US sector rotation + 13F volume proxy
"""

from __future__ import annotations

import logging
import os
import sys

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("gai_me.scheduler")

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    logger.error("APScheduler not installed. Run: pip install APScheduler>=3.10")
    sys.exit(1)

import pandas as pd

import db_manager
from fetchers import (
    fetch_fred, fetch_dbnomics,
    fetch_dxy, fetch_china_credit_impulse, fetch_copper_yoy,
    fetch_hy_spread, fetch_twd_usd, fetch_korea_exports_yoy,
    fetch_fed_funds_rate, fetch_t10y3m, fetch_us_new_orders_yoy, fetch_sp500_yoy,
    fetch_taiwan_exports_amount, fetch_cbc_money_supply, fetch_taiwan_pmi,
    fetch_tsmc_revenue_yoy, fetch_taiex_yoy, fetch_tw_institutional,
    fetch_ism_pmi, fetch_ndc_leading_index, fetch_china_nbs_pmi,
    fetch_japan_economy_watchers, fetch_china_nbs_ppi_yoy, fetch_eurostat_ici,
    fetch_etf_bulk, fetch_sector_rotation, fetch_13f_proxy,
    fetch_index_yoy, fetch_vkospi, fetch_13f_smart_money,
)
from fetchers.taiwan_sector import (
    fetch_tw_sector_indices,
    fetch_tw_sector_turnover,
    fetch_tw_sector_institutional,
    SECTOR_NAMES as _TW_SECTOR_NAMES,
)

FRED_KEY = os.environ.get("FRED_API_KEY", "")

_YEARS_INITIAL = 15   # --run-now: full history (INSERT OR IGNORE)
_YEARS_DELTA   = 2    # daily jobs: enough to cover publication lag


# ── helper ────────────────────────────────────────────────────────────────────

def _run(key: str, fn, ttl_days: int = 1, *, initial: bool = False,
         post_sleep: float = 0.0, **kwargs) -> None:
    """
    Call fetcher fn(**kwargs), then persist the result to the DB.

    initial=True  → db_manager INSERT OR IGNORE  (bulk load, preserves history)
    initial=False → db_manager delta write        (last 30 days only for ts_rows)

    post_sleep: seconds to sleep after the call (rate-limit courtesy for initial loads).
    Handles both plain DataFrame and dict-of-DataFrames return types.
    """
    import time as _time
    try:
        result = fn(**kwargs)
        if result is None:
            return
        mode = "BULK" if initial else "DELTA"
        if isinstance(result, pd.DataFrame):
            db_manager.write(key, result, ttl_days=ttl_days, initial=initial)
            logger.info("%-5s %-32s %d rows", mode, key, len(result))
        else:
            for sub_key, sub_df in result.items():
                if isinstance(sub_df, pd.DataFrame) and not sub_df.empty:
                    fk = f"{key}.{sub_key}"
                    db_manager.write(fk, sub_df, ttl_days=ttl_days, initial=initial)
                    logger.info("%-5s %-32s %d rows", mode, fk, len(sub_df))
    except Exception as e:
        logger.error("Failed to update %s: %s", key, e)
    finally:
        if post_sleep > 0:
            _time.sleep(post_sleep)


# ── job: all macro indicators ─────────────────────────────────────────────────

def job_macro_indicators(*, initial: bool = False) -> None:
    """
    Daily macro update — every indicator used by dashboard.py.

    Covers: FRED · DBnomics (OECD) · Taiwan govt · Global scrape · Yahoo Finance.
    Does NOT cover: TWSE sector indices (job_taiwan_sector) or 13F/ETF rotation
    (job_sector_and_13f).
    """
    y = _YEARS_INITIAL if initial else _YEARS_DELTA
    logger.info("=== macro indicators [%s, years_back=%d] ===",
                "INITIAL" if initial else "DELTA", y)

    # When pulling 15-year history, sleep 1 s between each API call so we are
    # not throttled by FRED (120 req/min limit) or DBnomics.
    api_sleep = 1.0 if initial else 0.0

    # ── FRED raw series ───────────────────────────────────────────────────────
    if FRED_KEY:
        fred_series = [
            ("VIXCLS",        "vix"),
            ("RSAFS",         "us_retail"),
            ("UMCSENT",       "umcsent"),
            ("BUSINV",        "us_businv"),
            ("PCU33443344",   "semi_ppi"),
            ("DCOILBRENTEU",  "brent"),
            ("CPILFESL",      "us_core_cpi"),
            ("PPIFES",        "us_core_ppi"),
            ("DGS10",         "dgs10"),
            ("T10YIE",        "t10y_bei"),
            ("T10Y2Y",        "t10y2y"),
            ("DFF",           "dff"),
            ("M1SL",          "us_m1"),
            ("BAMLH0A0HYM2",  "hy_spread"),
            ("DEXTAUS",       "twd_usd"),
            ("T10Y3M",        "t10y3m"),
        ]
        for series_id, key in fred_series:
            _run(key, fetch_fred, ttl_days=1, initial=initial, post_sleep=api_sleep,
                 series_id=series_id, api_key=FRED_KEY, years_back=y)

        # Yield curve — 11 maturities
        yield_mats = {
            "1M": "DGS1MO", "3M": "DGS3MO", "6M": "DGS6MO",
            "1Y": "DGS1",   "2Y": "DGS2",   "3Y": "DGS3",
            "5Y": "DGS5",   "7Y": "DGS7",   "10Y": "DGS10",
            "20Y": "DGS20", "30Y": "DGS30",
        }
        for mat, sid in yield_mats.items():
            _run(f"yield_{mat}", fetch_fred, ttl_days=1, initial=initial,
                 post_sleep=api_sleep, series_id=sid, api_key=FRED_KEY, years_back=y)

        # Composite FRED-based series
        _run("fed_funds_rate",    fetch_fed_funds_rate,       ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("copper_yoy",        fetch_copper_yoy,           ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("korea_exports_yoy", fetch_korea_exports_yoy,    ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("us_new_orders_yoy", fetch_us_new_orders_yoy,    ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("sp500_yoy",         fetch_sp500_yoy,            ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("dxy",               fetch_dxy,                  ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("china_credit",      fetch_china_credit_impulse, ttl_days=1, initial=initial,
             post_sleep=api_sleep, api_key=FRED_KEY, years_back=y)
        _run("ism_pmi",           fetch_ism_pmi,              ttl_days=1, initial=initial,
             post_sleep=api_sleep, fred_key=FRED_KEY, years_back=y)
    else:
        logger.warning("FRED_API_KEY not set — skipping FRED indicators")
        _run("ism_pmi", fetch_ism_pmi, ttl_days=1, initial=initial,
             post_sleep=api_sleep, years_back=y)

    # ── OECD CLI via DBnomics ─────────────────────────────────────────────────
    oecd_cli = [
        ("USA.LOLITONO.STSA.M", "cli_us"),
        ("CHN.LOLITONO.STSA.M", "cli_cn"),
        ("JPN.LOLITONO.STSA.M", "cli_jp"),
        ("G4E.LOLITONO.STSA.M", "cli_eu"),
        ("KOR.LOLITONO.STSA.M", "cli_kr"),
    ]
    for series, key in oecd_cli:
        _run(key, fetch_dbnomics, ttl_days=3, initial=initial, post_sleep=api_sleep,
             provider="OECD", dataset="MEI", series=series, years_back=y)

    # ── Taiwan government sources ─────────────────────────────────────────────
    _run("taiwan_exports",   fetch_taiwan_exports_amount, ttl_days=3, initial=initial,
         post_sleep=api_sleep)
    _run("cbc_money_supply", fetch_cbc_money_supply,      ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)
    _run("taiwan_pmi",       fetch_taiwan_pmi,            ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)
    _run("tsmc_revenue_yoy", fetch_tsmc_revenue_yoy,      ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=min(y, 15))
    _run("taiex_yoy",        fetch_taiex_yoy,             ttl_days=1, initial=initial,
         post_sleep=api_sleep, years_back=y)
    _run("ndc_leading",      fetch_ndc_leading_index,     ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)

    # ── Global scrape (NBS / Japan / Eurostat) ────────────────────────────────
    _run("china_nbs_pmi",  fetch_china_nbs_pmi,          ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)
    _run("japan_watchers", fetch_japan_economy_watchers,  ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)
    _run("china_ppi_yoy",  fetch_china_nbs_ppi_yoy,      ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)
    _run("eurostat_ici",   fetch_eurostat_ici,            ttl_days=3, initial=initial,
         post_sleep=api_sleep, years_back=y)

    # ── Yahoo Finance equity indices ──────────────────────────────────────────
    # Yahoo Finance has no strict rate limit, but 1 s between calls avoids 429s.
    yf_sleep = 1.0 if initial else 0.0
    indices = [
        ("^N225",      "nikkei_yoy"),
        ("^KS11",      "kospi_yoy"),
        ("^HSI",       "hsi_yoy"),
        ("000300.SS",  "csi300_yoy"),
    ]
    for ticker, key in indices:
        _run(key, fetch_index_yoy, ttl_days=1, initial=initial, post_sleep=yf_sleep,
             ticker=ticker, years_back=y)

    _run("vkospi", fetch_vkospi, ttl_days=1, initial=initial,
         post_sleep=yf_sleep, years_back=min(y, 6))

    # ── TWSE T86 institutional flows (always snapshot) ────────────────────────
    _run("tw_institutional_5d",  fetch_tw_institutional, ttl_days=1, initial=initial,
         n_days=5)
    _run("tw_institutional_20d", fetch_tw_institutional, ttl_days=1, initial=initial,
         n_days=20)

    db_manager.cleanup_expired()
    logger.info("=== macro indicators complete ===")


# ── job: Taiwan sector ────────────────────────────────────────────────────────

def job_taiwan_sector(*, initial: bool = False) -> None:
    """
    Daily update of TWSE MI_INDEX20 sector indices and turnover.

    Initial load requests 15 years of trading days (~3780 days).
    Delta load requests 252 days; db_manager filters to last 30.

    fetch_tw_sector_indices() returns 5 columns (date, sector_code, sector_name,
    close, chg_pct).  We split into two 3-column DataFrames so that
    _is_grouped_ts() routes them to ts_rows (incremental) instead of blob_cache
    (full-replace).  This preserves the full 15-year history across daily updates.
    """
    logger.info("=== Taiwan sector [%s] ===", "INITIAL" if initial else "DELTA")
    n_idx = 3780 if initial else 252   # 15y × ~252 trading days/y
    mode  = "BULK" if initial else "DELTA"

    try:
        idx_df = fetch_tw_sector_indices(n_days=n_idx)
        if not idx_df.empty:
            for col, db_key in [("close", "tw_sector_close"),
                                 ("chg_pct", "tw_sector_chg_pct")]:
                sub = idx_df[["date", "sector_name", col]].copy()
                db_manager.write(db_key, sub, ttl_days=1, initial=initial)
                logger.info("%-5s %-32s %d rows", mode, db_key, len(sub))
            # Remove stale keys not in current SECTOR_NAMES (e.g. old rank numbers "1"–"20")
            _valid = set(_TW_SECTOR_NAMES.values())
            for _db_key in ("tw_sector_close", "tw_sector_chg_pct"):
                db_manager.purge_stale_series(_db_key, keep=_valid)
    except Exception as e:
        logger.error("Failed to update tw_sector_close/chg_pct: %s", e)

    _run("tw_sector_turnover",       fetch_tw_sector_turnover,       ttl_days=1,
         initial=initial, n_days=60)
    _run("tw_sector_institutional",  fetch_tw_sector_institutional,  ttl_days=1,
         initial=initial, n_days=5)
    logger.info("=== Taiwan sector complete ===")


# ── job: sector rotation + 13F ───────────────────────────────────────────────

def job_sector_and_13f(*, initial: bool = False) -> None:
    """
    US sector ETF rotation + SEC EDGAR 13F smart money.
    Runs Mon + Thu (heavier fetch, ~30–60 s for 13F).
    """
    y = _YEARS_INITIAL if initial else _YEARS_DELTA
    logger.info("=== sector/13F [%s, years_back=%d] ===",
                "INITIAL" if initial else "DELTA", y)

    etf_bulk = fetch_etf_bulk(years_back=y)
    # Brief pause after the multi-threaded ETF bulk fetch when doing initial load.
    if initial:
        import time as _time
        _time.sleep(2.0)
    _run("sector_rotation", fetch_sector_rotation, ttl_days=3, initial=initial,
         post_sleep=1.0 if initial else 0.0, etf_bulk=etf_bulk, years_back=y)
    _run("13f_proxy",       fetch_13f_proxy,       ttl_days=3, initial=initial,
         etf_bulk=etf_bulk, years_back=y)

    # 13F smart money — quarterly snapshot, always stored as blob regardless of mode
    try:
        smart = fetch_13f_smart_money(n_top=20)
        rows = []
        for entry in smart.get("top_buy_shares", []):
            rows.append({"type": "buy_shares",  "name": entry[0],
                         "delta": entry[1], "n_funds": entry[2]})
        for entry in smart.get("top_sell_shares", []):
            rows.append({"type": "sell_shares", "name": entry[0],
                         "delta": entry[1], "n_funds": entry[2]})
        if rows:
            df = pd.DataFrame(rows)
            db_manager.write("13f_smart_money", df, ttl_days=7)
            logger.info("%-5s %-32s %d rows", "BLOB", "13f_smart_money", len(df))
    except Exception as e:
        logger.error("Failed to update 13f_smart_money: %s", e)

    logger.info("=== sector/13F complete ===")


# ── job: monthly DB maintenance ───────────────────────────────────────────────

def job_monthly_maintenance() -> None:
    """
    Monthly housekeeping — 1st of month at 03:00 Asia/Taipei.

    1. Remove ts_rows older than 15 years.
    2. Truncate the WAL file (reclaims eMMC blocks).
    3. Remove expired blob_cache rows.
    """
    logger.info("=== monthly maintenance ===")
    trimmed = db_manager.trim_to_window(years=db_manager.HISTORY_YEARS)
    db_manager.checkpoint()
    expired = db_manager.cleanup_expired()
    logger.info("Maintenance done: trimmed %d ts_rows, removed %d expired blobs",
                trimmed, expired)


# ── initial bulk load ─────────────────────────────────────────────────────────

def run_all_now() -> None:
    """
    Pull 15 years of data for every indicator (INSERT OR IGNORE).

    Safe to re-run: existing rows are never overwritten.
    Ends with a trim + WAL checkpoint to reclaim eMMC space.

    Usage:
        python scheduler.py --run-now
    """
    logger.info("=== Initial bulk load — %d-year history ===", _YEARS_INITIAL)
    job_macro_indicators(initial=True)
    job_taiwan_sector(initial=True)
    job_sector_and_13f(initial=True)
    logger.info("Trimming to %d-year window and checkpointing WAL…",
                db_manager.HISTORY_YEARS)
    db_manager.trim_to_window()
    db_manager.checkpoint()
    logger.info("=== Initial bulk load complete ===")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GAI_ME Scheduler")
    parser.add_argument(
        "--run-now", action="store_true",
        help="Run the 15-year initial bulk load immediately and exit.",
    )
    args = parser.parse_args()

    if args.run_now:
        run_all_now()
        sys.exit(0)

    scheduler = BlockingScheduler(timezone="Asia/Taipei")

    scheduler.add_job(
        job_macro_indicators, CronTrigger(hour=2, minute=0),
        id="macro_daily", name="Daily macro indicators",
    )
    scheduler.add_job(
        job_taiwan_sector, CronTrigger(hour=2, minute=30),
        id="tw_sector_daily", name="Taiwan sector indices",
    )
    scheduler.add_job(
        job_sector_and_13f, CronTrigger(day_of_week="mon,thu", hour=6, minute=0),
        id="sector_13f", name="Sector rotation + 13F",
    )
    scheduler.add_job(
        job_monthly_maintenance, CronTrigger(day=1, hour=3, minute=0),
        id="monthly_maint", name="Monthly DB maintenance",
    )

    logger.info("Scheduler started. Jobs: %s",
                [job.name for job in scheduler.get_jobs()])
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
