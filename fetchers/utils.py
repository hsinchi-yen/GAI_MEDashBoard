from __future__ import annotations

import logging
import re
import time

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

logger = logging.getLogger("gai_me.fetchers")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

_MINGUO_PATTERN = re.compile(r'(\d+)年(\d+)月')


def roc_to_ad(roc_year: int) -> int:
    return roc_year + 1911


def parse_minguo_ym(text: str) -> pd.Timestamp:
    """Convert '115年02月' or similar ROC year-month strings to pd.Timestamp."""
    text = str(text).replace(' ', '').replace(',', '')
    m = _MINGUO_PATTERN.match(text)
    if m:
        return pd.Timestamp(year=roc_to_ad(int(m.group(1))), month=int(m.group(2)), day=1)
    return pd.NaT


# Keep legacy name as alias
_parse_minguo_ym = parse_minguo_ym


def compute_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute YoY % from monthly data (12-period pct_change)."""
    if df.empty or len(df) < 13:
        return pd.DataFrame()
    df = df.copy()
    df['value'] = df['value'].pct_change(12) * 100
    return df.dropna()


def fetch_with_retry(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 2.0,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """GET with exponential backoff. Raises on final failure."""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                sleep_s = backoff ** attempt
                logger.warning("fetch_with_retry: attempt %d failed for %s (%s), retrying in %.1fs",
                               attempt + 1, url, exc, sleep_s)
                time.sleep(sleep_s)
            else:
                logger.error("fetch_with_retry: all %d attempts failed for %s: %s", retries, url, exc)
    raise last_exc
