"""One-off data migration to run inside the container after deploying this release.

    python post_deploy.py                  # report only; changes nothing
    python post_deploy.py --backfill       # fill snapshots, re-date Asian indices
    python post_deploy.py --purge          # delete the legacy keys listed by the report

The purge only touches LEGACY_BLOBS and LEGACY_SERIES, explicit lists of keys this
release retired. It never guesses from a pattern.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

for candidate in (Path("/app"), Path(__file__).resolve().parent.parent):
    if (candidate / "db_manager.py").exists():
        sys.path.insert(0, str(candidate))
        break

import db_manager  # noqa: E402

# Superseded by snapshot:13f_smart_money and snapshot:tw_institutional_{5,20}d.
LEGACY_BLOBS = (
    "13f_smart_money",
    "tw_institutional_5d.top30_buy", "tw_institutional_5d.top30_sell",
    "tw_institutional_20d.top30_buy", "tw_institutional_20d.top30_sell",
)

# Written daily but never read: the UI uses the monthly fed_funds_rate instead.
LEGACY_SERIES = ("dff",)

# Bars were stored under the previous UTC day, so these rows sit a month early and
# would duplicate new rows. (key, ticker)
REDATED_INDICES = (
    ("taiex_yoy", "^TWII"), ("nikkei_yoy", "^N225"), ("kospi_yoy", "^KS11"),
    ("hsi_yoy", "^HSI"), ("csi300_yoy", "000300.SS"),
)


def legacy_rows() -> list[tuple[str, int]]:
    """(key, payload bytes) for each legacy blob present."""
    marks = ",".join("?" * len(LEGACY_BLOBS))
    with db_manager._conn() as con:
        return con.execute(
            f"SELECT cache_key, LENGTH(payload_json) FROM blob_cache WHERE cache_key IN ({marks})",
            LEGACY_BLOBS,
        ).fetchall()


def legacy_table_rows() -> int:
    with db_manager._conn() as con:
        return con.execute("SELECT COUNT(*) FROM indicator_cache").fetchone()[0]


def legacy_series_rows() -> list[tuple[str, int]]:
    marks = ",".join("?" * len(LEGACY_SERIES))
    with db_manager._conn() as con:
        return con.execute(
            f"SELECT indicator_id, COUNT(*) FROM ts_rows WHERE indicator_id IN ({marks})"
            " GROUP BY indicator_id", LEGACY_SERIES,
        ).fetchall()


def purge_legacy() -> int:
    blob_marks = ",".join("?" * len(LEGACY_BLOBS))
    series_marks = ",".join("?" * len(LEGACY_SERIES))
    with db_manager._conn() as con:
        removed = con.execute(f"DELETE FROM blob_cache WHERE cache_key IN ({blob_marks})",
                              LEGACY_BLOBS).rowcount
        removed += con.execute(f"DELETE FROM ts_rows WHERE indicator_id IN ({series_marks})",
                               LEGACY_SERIES).rowcount
        con.execute(f"DELETE FROM ts_meta WHERE indicator_id IN ({series_marks})", LEGACY_SERIES)
    return removed


def report() -> None:
    print("legacy blobs:")
    rows = legacy_rows()
    for key, size in rows:
        print(f"  {key}  {size} bytes")
    if not rows:
        print("  none")
    print(f"legacy series: {legacy_series_rows() or 'none'}")
    print(f"legacy indicator_cache rows: {legacy_table_rows()}")
    for key in ("13f_smart_money", "tw_institutional_5d", "tw_institutional_20d"):
        age = db_manager.snapshot_age_hours(key)
        print(f"snapshot {key}: {'missing' if age is None else f'{age:.1f}h old'}")
    for key in ("index_close_twii", "index_close_spx"):
        df = db_manager.read(key)
        print(f"{key}: {0 if df is None else len(df)} rows")


def backfill() -> None:
    from fetchers import (
        fetch_13f_smart_money, fetch_index_monthly_close, fetch_index_yoy, fetch_tw_institutional,
    )

    for key, ticker in REDATED_INDICES:
        fresh = fetch_index_yoy(ticker, years_back=15)
        db_manager.replace_series(key, fresh, ttl_days=1)
        print(f"{key}: {len(fresh)} rows")
    for key, ticker in (("index_close_twii", "^TWII"), ("index_close_spx", "^GSPC")):
        df = fetch_index_monthly_close(ticker, years_back=15)
        db_manager.replace_series(key, df, ttl_days=7)
        print(f"{key}: {len(df)} rows")
    for n_days in (5, 20):
        result = fetch_tw_institutional(n_days=n_days)
        if result.get("actual_days"):
            db_manager.write_snapshot(f"tw_institutional_{n_days}d", result, ttl_days=1)
        print(f"tw_institutional_{n_days}d: {result.get('actual_days', 0)} days")
    smart = fetch_13f_smart_money(n_top=20)
    if smart.get("fund_count"):
        db_manager.write_snapshot("13f_smart_money", smart, ttl_days=7)
    print(f"13f: {smart.get('fund_count', 0)} funds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--purge", action="store_true")
    args = parser.parse_args()
    if args.backfill:
        backfill()
    if args.purge:
        print(f"purged {purge_legacy()} legacy rows")
    report()


if __name__ == "__main__":
    main()
