"""
db_manager.py — eMMC-optimised SQLite persistence for GAI_MEDashBoard.

Three-table schema
──────────────────
ts_rows    : time-series data — one row per (indicator_id, series_key, day_epoch).
             Incremental delta writes: daily scheduler only touches the last
             DELTA_DAYS rows; the 15-year history is never rewritten after
             the initial bulk load.
ts_meta    : per-indicator TTL & last-updated bookkeeping.
blob_cache : complex / non-time-series snapshots (13F rankings, sector top-30).
             Full INSERT OR REPLACE on each update; expected to be written at
             most weekly.

Routing (auto-detected by write())
───────────────────────────────────
  DataFrame columns == {date, value}  →  ts_rows   (incremental delta writes)
  Anything else                       →  blob_cache (full replace)

Backward compat
───────────────
The old indicator_cache table is preserved read-only.  read() falls through to
it if neither ts_rows nor blob_cache has a fresh entry.

eMMC tuning applied at every connection open
────────────────────────────────────────────
  WAL · autocheckpoint 2000 · synchronous NORMAL
  16 MB page cache · 64 MB mmap · temp_store MEMORY
"""

from __future__ import annotations

import io
import logging
import sqlite3
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger("gai_me.db")

_DB_PATH = Path(__file__).parent / "app_data" / "db" / "indicator_cache.sqlite3"

DELTA_DAYS: int = 30        # daily scheduler writes only last N days to ts_rows
HISTORY_YEARS: int = 15     # trim_to_window() retains up to this many years


# ── DDL ───────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS ts_rows (
    indicator_id  TEXT    NOT NULL,
    series_key    TEXT    NOT NULL DEFAULT '',
    day_epoch     INTEGER NOT NULL,
    value         REAL,
    PRIMARY KEY (indicator_id, series_key, day_epoch)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS ts_meta (
    indicator_id  TEXT    NOT NULL PRIMARY KEY,
    last_updated  INTEGER NOT NULL DEFAULT 0,
    ttl_seconds   INTEGER NOT NULL DEFAULT 86400
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS blob_cache (
    cache_key     TEXT    NOT NULL PRIMARY KEY,
    payload_json  TEXT    NOT NULL,
    fetched_at    INTEGER NOT NULL,
    ttl_seconds   INTEGER NOT NULL DEFAULT 86400
) WITHOUT ROWID;

-- Legacy table kept for migration reads (never written to by this version).
CREATE TABLE IF NOT EXISTS indicator_cache (
    indicator_id  TEXT NOT NULL,
    params_key    TEXT NOT NULL DEFAULT 'default',
    payload_json  TEXT NOT NULL,
    fetched_at    INTEGER NOT NULL,
    ttl_seconds   INTEGER NOT NULL,
    PRIMARY KEY (indicator_id, params_key)
);
"""

# Applied on every connection open.
# page_size only takes effect when the DB is first created; harmless on existing DBs.
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA wal_autocheckpoint = 2000",   # checkpoint less often → fewer write cycles
    "PRAGMA synchronous = NORMAL",         # vs FULL: halves fsync calls
    "PRAGMA page_size = 4096",             # match eMMC 4 KB erase block
    "PRAGMA cache_size = -16384",          # 16 MB page cache (reduce read I/O)
    "PRAGMA temp_store = MEMORY",          # no temp files on eMMC
    "PRAGMA mmap_size = 67108864",         # 64 MB read-mmap
)


# ── connection ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    for p in _PRAGMAS:
        con.execute(p)
    con.executescript(_DDL)
    con.commit()
    return con


# ── internal helpers ──────────────────────────────────────────────────────────

def _to_day(ts) -> int:
    """pandas Timestamp → integer days since 1970-01-01 (compact storage key)."""
    return int(pd.Timestamp(ts).value // 86_400_000_000_000)


def _from_day(day: int) -> pd.Timestamp:
    return pd.Timestamp(day * 86_400, unit="s")


def _is_simple_ts(df: pd.DataFrame) -> bool:
    """True when df has exactly {date, value} columns → routes to ts_rows."""
    return set(df.columns) == {"date", "value"}


def _is_grouped_ts(df: pd.DataFrame) -> tuple[bool, str, str]:
    """
    Detect DataFrames that are time-series grouped by a string dimension.

    Matches: {date, <group_col>, value_col} where group_col is TEXT.
    Returns (is_grouped, group_col, value_col).

    Supported shapes:
      {date, sector_name, close}  → series_key=sector_name, value=close
      {date, sector_name, chg_pct} → series_key=sector_name, value=chg_pct
    """
    cols = set(df.columns)
    if "date" not in cols:
        return False, "", ""
    rest = cols - {"date"}
    if len(rest) != 2:
        return False, "", ""
    for group_col in rest:
        # Use is_string_dtype to handle both legacy object and pandas 2.x StringDtype
        if (pd.api.types.is_string_dtype(df[group_col])
                and not pd.api.types.is_numeric_dtype(df[group_col])):
            value_col = (rest - {group_col}).pop()
            if pd.api.types.is_numeric_dtype(df[value_col]):
                return True, group_col, value_col
    return False, "", ""


def _today_day() -> int:
    return int(time.time()) // 86400


_EPOCH = pd.Timestamp("1970-01-01")


def _dates_to_days(dates) -> list[int]:
    """Convert a pandas DatetimeSeries or sequence of Timestamps to integer day_epoch.

    Uses timedelta arithmetic so it is correct for both datetime64[ns] (pandas < 2)
    and datetime64[us] (pandas 2.x default) without any hardcoded divisor.
    """
    return (pd.to_datetime(dates) - _EPOCH).dt.days.tolist()


def _df_to_ts_rows(key: str, df: pd.DataFrame) -> list[tuple]:
    """Vectorised conversion of {date, value} DataFrame → ts_rows tuples."""
    days   = _dates_to_days(df["date"])
    values = df["value"].tolist()
    return [
        (key, "", d, v if not pd.isna(v) else None)
        for d, v in zip(days, values)
    ]


def _df_to_grouped_ts_rows(key: str, df: pd.DataFrame,
                            group_col: str, value_col: str) -> list[tuple]:
    """Vectorised conversion of grouped DataFrame → ts_rows tuples with series_key."""
    days   = _dates_to_days(df["date"])
    groups = df[group_col].tolist()
    values = df[value_col].tolist()
    return [
        (key, str(g), d, v if not pd.isna(v) else None)
        for g, d, v in zip(groups, days, values)
    ]


# ── public write API ──────────────────────────────────────────────────────────

def write(key: str, df: pd.DataFrame, ttl_days: int = 1, *, initial: bool = False) -> None:
    """
    Persist a DataFrame to SQLite.

    Parameters
    ----------
    key      : indicator identifier string.
    df       : DataFrame to store.
    ttl_days : freshness TTL in days.
    initial  : True → bulk-load mode (INSERT OR IGNORE, preserves existing history).
               False → delta mode for ts_rows (only last DELTA_DAYS rows are written);
                       blob_cache always does a full INSERT OR REPLACE.

    Routing
    -------
    DataFrame columns == {date, value}  →  _write_ts_bulk / _write_ts_delta
    Anything else                       →  _write_blob
    """
    if df is None or df.empty:
        return
    try:
        if _is_simple_ts(df):
            if initial:
                _write_ts_bulk(key, df, ttl_days)
            else:
                _write_ts_delta(key, df, ttl_days)
        else:
            grouped, group_col, value_col = _is_grouped_ts(df)
            if grouped:
                if initial:
                    _write_grouped_ts_bulk(key, df, ttl_days, group_col, value_col)
                else:
                    _write_grouped_ts_delta(key, df, ttl_days, group_col, value_col)
            else:
                _write_blob(key, df, ttl_days)
    except Exception as e:
        logger.error("db write failed [%s]: %s", key, e)


def _write_ts_bulk(key: str, df: pd.DataFrame, ttl_days: int) -> None:
    """INSERT OR IGNORE all rows — idempotent, safe to re-run."""
    rows = _df_to_ts_rows(key, df)
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO ts_rows (indicator_id, series_key, day_epoch, value)"
            " VALUES (?,?,?,?)",
            rows,
        )
        con.execute(
            "INSERT OR REPLACE INTO ts_meta (indicator_id, last_updated, ttl_seconds)"
            " VALUES (?,?,?)",
            (key, int(time.time()), ttl_days * 86400),
        )
    logger.info("ts_rows bulk  %-30s  %d rows", key, len(rows))


def _write_ts_delta(key: str, df: pd.DataFrame, ttl_days: int) -> None:
    """INSERT OR REPLACE only rows within the last DELTA_DAYS window."""
    cutoff = _from_day(_today_day() - DELTA_DAYS)
    recent = df[df["date"] >= cutoff]
    if recent.empty:
        logger.debug("ts_rows delta [%s]: no rows in last %d days — skipped", key, DELTA_DAYS)
        return
    rows = _df_to_ts_rows(key, recent)
    with _conn() as con:
        con.executemany(
            "INSERT OR REPLACE INTO ts_rows (indicator_id, series_key, day_epoch, value)"
            " VALUES (?,?,?,?)",
            rows,
        )
        con.execute(
            "INSERT OR REPLACE INTO ts_meta (indicator_id, last_updated, ttl_seconds)"
            " VALUES (?,?,?)",
            (key, int(time.time()), ttl_days * 86400),
        )
    logger.info("ts_rows delta %-30s  %d rows (last %dd)", key, len(rows), DELTA_DAYS)


def _write_grouped_ts_bulk(key: str, df: pd.DataFrame, ttl_days: int,
                            group_col: str, value_col: str) -> None:
    """INSERT OR IGNORE all grouped rows — idempotent, preserves 15-year history."""
    rows = _df_to_grouped_ts_rows(key, df, group_col, value_col)
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO ts_rows (indicator_id, series_key, day_epoch, value)"
            " VALUES (?,?,?,?)",
            rows,
        )
        con.execute(
            "INSERT OR REPLACE INTO ts_meta (indicator_id, last_updated, ttl_seconds)"
            " VALUES (?,?,?)",
            (key, int(time.time()), ttl_days * 86400),
        )
    logger.info("ts_rows grp_bulk %-28s  %d rows (%d series)",
                key, len(rows), df[group_col].nunique())


def _write_grouped_ts_delta(key: str, df: pd.DataFrame, ttl_days: int,
                             group_col: str, value_col: str) -> None:
    """INSERT OR REPLACE only rows within the last DELTA_DAYS window (all series)."""
    cutoff = _from_day(_today_day() - DELTA_DAYS)
    recent = df[df["date"] >= cutoff]
    if recent.empty:
        logger.debug("ts_rows grp_delta [%s]: no rows in last %d days — skipped", key, DELTA_DAYS)
        return
    rows = _df_to_grouped_ts_rows(key, recent, group_col, value_col)
    with _conn() as con:
        con.executemany(
            "INSERT OR REPLACE INTO ts_rows (indicator_id, series_key, day_epoch, value)"
            " VALUES (?,?,?,?)",
            rows,
        )
        con.execute(
            "INSERT OR REPLACE INTO ts_meta (indicator_id, last_updated, ttl_seconds)"
            " VALUES (?,?,?)",
            (key, int(time.time()), ttl_days * 86400),
        )
    logger.info("ts_rows grp_delta %-27s  %d rows (last %dd)", key, len(rows), DELTA_DAYS)


def _write_blob(key: str, df: pd.DataFrame, ttl_days: int) -> None:
    """Full replace — for complex DataFrames that can't be stored row-per-date."""
    payload = df.to_json(orient="split", date_format="iso")
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO blob_cache"
            " (cache_key, payload_json, fetched_at, ttl_seconds) VALUES (?,?,?,?)",
            (key, payload, int(time.time()), ttl_days * 86400),
        )
    logger.info("blob_cache    %-30s  %d rows", key, len(df))


# ── public read API ───────────────────────────────────────────────────────────

def read(key: str) -> pd.DataFrame | None:
    """
    Return the cached DataFrame, or None if missing / expired.

    Read order: ts_rows (via ts_meta) → blob_cache → legacy indicator_cache.
    """
    try:
        df = _read_ts(key)
        if df is not None:
            return df
        df = _read_blob(key)
        if df is not None:
            return df
        return _read_legacy(key)
    except Exception as e:
        logger.error("db read failed [%s]: %s", key, e)
        return None


def _read_ts(key: str) -> pd.DataFrame | None:
    with _conn() as con:
        meta = con.execute(
            "SELECT last_updated, ttl_seconds FROM ts_meta WHERE indicator_id=?", (key,)
        ).fetchone()
        if meta is None:
            return None
        # NOTE: TTL is intentionally NOT used to gate reads. The latest stored
        # observation is always returned (stale-while-revalidate). A monthly
        # series published last month is still the most recent value today, so
        # a 1-day TTL must not make it vanish from the dashboard / GMI scoring.
        # Use is_stale(key) to decide whether to *re-fetch*, not whether the
        # cached data is usable.

        # Peek at distinct series_key values to detect grouped vs simple
        peek = con.execute(
            "SELECT DISTINCT series_key FROM ts_rows WHERE indicator_id=? LIMIT 2", (key,)
        ).fetchall()
        if not peek:
            return None

        if all(sk[0] == "" for sk in peek):
            # Simple time series → {date, value}
            rows = con.execute(
                "SELECT day_epoch, value FROM ts_rows"
                " WHERE indicator_id=? AND series_key='' ORDER BY day_epoch",
                (key,),
            ).fetchall()
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["day_epoch", "value"])
            df["date"] = df["day_epoch"].map(_from_day)
            return df[["date", "value"]].reset_index(drop=True)
        else:
            # Grouped time series → {date, series_key, value}
            rows = con.execute(
                "SELECT series_key, day_epoch, value FROM ts_rows"
                " WHERE indicator_id=? ORDER BY day_epoch, series_key",
                (key,),
            ).fetchall()
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["series_key", "day_epoch", "value"])
            df["date"] = df["day_epoch"].map(_from_day)
            return df[["date", "series_key", "value"]].reset_index(drop=True)


def _read_blob(key: str) -> pd.DataFrame | None:
    with _conn() as con:
        row = con.execute(
            "SELECT payload_json, fetched_at, ttl_seconds FROM blob_cache WHERE cache_key=?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    payload_json, fetched_at, ttl_seconds = row
    # Serve-stale: return the cached snapshot regardless of TTL age (see _read_ts).
    df = pd.read_json(io.StringIO(payload_json), orient="split")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    return df


def _read_legacy(key: str) -> pd.DataFrame | None:
    """Fallback: read from old indicator_cache table (migration compatibility)."""
    now = int(time.time())
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT payload_json, fetched_at, ttl_seconds FROM indicator_cache"
                " WHERE indicator_id=? AND params_key='default'",
                (key,),
            ).fetchone()
        if row is None:
            return None
        payload_json, fetched_at, ttl_seconds = row
        if now - fetched_at > ttl_seconds:
            return None
        df = pd.read_json(io.StringIO(payload_json), orient="split")
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        logger.debug("legacy read [%s]", key)
        return df
    except Exception:
        return None


# ── freshness & maintenance ───────────────────────────────────────────────────

def is_fresh(key: str) -> bool:
    """True if the key exists and TTL has not been exceeded."""
    now = int(time.time())
    try:
        with _conn() as con:
            meta = con.execute(
                "SELECT last_updated, ttl_seconds FROM ts_meta WHERE indicator_id=?", (key,)
            ).fetchone()
            if meta and (now - meta[0]) <= meta[1]:
                return True
            blob = con.execute(
                "SELECT fetched_at, ttl_seconds FROM blob_cache WHERE cache_key=?", (key,)
            ).fetchone()
            return bool(blob and (now - blob[0]) <= blob[1])
    except Exception:
        return False


def is_stale(key: str) -> bool:
    """
    True if `key` is missing entirely, or its TTL has been exceeded (needs re-fetch).

    Counterpart to is_fresh(). Reads no longer gate on TTL (stale-while-revalidate),
    so this is the canonical signal for schedulers / catch-up to decide whether to
    re-fetch. Missing → True (definitely fetch).
    """
    return not is_fresh(key)


def max_date(key: str) -> pd.Timestamp | None:
    """
    Latest observation date stored for `key` in ts_rows, or None if absent.

    Used for conditional fetch: skip writing when the source has no observation
    newer than what we already hold.
    """
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT MAX(day_epoch) FROM ts_rows WHERE indicator_id=?", (key,)
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return _from_day(row[0])
    except Exception:
        return None


def cleanup_expired() -> int:
    """
    Remove expired blob_cache rows.

    ts_rows are not touched here — use trim_to_window() for age-based pruning.
    """
    try:
        now = int(time.time())
        with _conn() as con:
            cur = con.execute(
                "DELETE FROM blob_cache WHERE (? - fetched_at) > ttl_seconds", (now,)
            )
        n = cur.rowcount
        if n:
            logger.info("blob_cache: removed %d expired rows", n)
        return n
    except Exception as e:
        logger.error("cleanup_expired: %s", e)
        return 0


def purge_stale_series(key: str, keep: set[str]) -> int:
    """
    Delete ts_rows for `key` whose series_key is NOT in `keep`.
    Used after sector writes to evict stale numeric keys left by old code.
    Returns the number of rows deleted.
    """
    try:
        placeholders = ",".join("?" * len(keep))
        with _conn() as con:
            cur = con.execute(
                f"DELETE FROM ts_rows WHERE indicator_id=?"
                f" AND series_key NOT IN ({placeholders})",
                [key] + list(keep),
            )
        if cur.rowcount:
            logger.info("purge_stale_series %-30s  removed %d stale keys", key, cur.rowcount)
        return cur.rowcount
    except Exception as e:
        logger.error("purge_stale_series %s: %s", key, e)
        return 0


def purge_test_keys() -> int:
    """
    Remove leftover test/auxiliary keys (indicator_id / cache_key starting with '_')
    from ts_rows, ts_meta and blob_cache. Returns total rows removed.
    """
    removed = 0
    try:
        with _conn() as con:
            for stmt in (
                "DELETE FROM ts_rows  WHERE indicator_id LIKE '\\_%' ESCAPE '\\'",
                "DELETE FROM ts_meta  WHERE indicator_id LIKE '\\_%' ESCAPE '\\'",
                "DELETE FROM blob_cache WHERE cache_key LIKE '\\_%' ESCAPE '\\'",
            ):
                removed += con.execute(stmt).rowcount
        if removed:
            logger.info("purge_test_keys: removed %d rows", removed)
        return removed
    except Exception as e:
        logger.error("purge_test_keys: %s", e)
        return 0


def trim_to_window(years: int = HISTORY_YEARS) -> int:
    """
    Delete ts_rows older than `years`.

    Intended to run monthly (or at initial-load completion), NOT nightly.
    Returns the number of rows deleted.
    """
    cutoff_day = _today_day() - int(years * 365.25)
    try:
        with _conn() as con:
            # Fast-path: skip the DELETE if nothing is older than cutoff.
            oldest = con.execute(
                "SELECT MIN(day_epoch) FROM ts_rows"
            ).fetchone()[0]
            if oldest is None or oldest >= cutoff_day:
                return 0
            cur = con.execute(
                "DELETE FROM ts_rows WHERE day_epoch < ?", (cutoff_day,)
            )
        n = cur.rowcount
        if n:
            logger.info("trim_to_window: removed %d rows older than %d years", n, years)
        return n
    except Exception as e:
        logger.error("trim_to_window: %s", e)
        return 0


def checkpoint() -> None:
    """
    Force a WAL TRUNCATE checkpoint.

    Resets the WAL file to near-zero size, reclaiming eMMC space.
    Call after large bulk writes (initial load) or monthly maintenance.
    """
    try:
        with _conn() as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        logger.info("WAL checkpoint (TRUNCATE) complete")
    except Exception as e:
        logger.error("checkpoint: %s", e)


def list_keys() -> list[dict]:
    """Debug helper: return all cached keys with freshness info."""
    now = int(time.time())
    result: list[dict] = []
    try:
        with _conn() as con:
            for row in con.execute(
                "SELECT indicator_id, last_updated, ttl_seconds FROM ts_meta"
            ).fetchall():
                result.append({
                    "key":   row[0],
                    "store": "ts_rows",
                    "age_h": round((now - row[1]) / 3600, 1),
                    "ttl_d": round(row[2] / 86400, 1),
                    "fresh": (now - row[1]) <= row[2],
                })
            for row in con.execute(
                "SELECT cache_key, fetched_at, ttl_seconds FROM blob_cache"
            ).fetchall():
                result.append({
                    "key":   row[0],
                    "store": "blob",
                    "age_h": round((now - row[1]) / 3600, 1),
                    "ttl_d": round(row[2] / 86400, 1),
                    "fresh": (now - row[1]) <= row[2],
                })
    except Exception:
        pass
    return result
