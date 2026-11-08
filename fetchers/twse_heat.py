"""Market-level buy-score history from the Twse_Top100_Heat service (port 8504).

That service scores ~600 stocks nightly and records how many trip each risk rule.
The share flagged 千張大戶退場 (big holders leaving while retail buys) rising
across the market is warning W10. Both containers run with ``--network host`` on
the production box, so the API is reached on localhost.

The value stored is the *share* of scored stocks, because the scoring pool
changes every day. A failed request returns an empty frame: W10 then reads as
stale and the other nine signals are unaffected.
"""
from __future__ import annotations

import logging
import os

import pandas as pd
import requests

logger = logging.getLogger("gai_me.fetchers.twse_heat")

API_BASE = os.environ.get("TWSE_HEAT_API_BASE", "http://127.0.0.1:8000")
WHALE_EXIT = "千張大戶退場"


def parse_whale_exit(body: dict) -> pd.DataFrame:
    """alert-counts payload → {date, value = % of scored stocks}; partial runs dropped."""
    summary = body.get("summary") or []
    alert = next((a for a in body.get("alerts") or [] if a.get("name") == WHALE_EXIT), None)
    rows = []
    for i, day in enumerate(summary):
        if day.get("partial") or not day.get("scored"):
            continue
        share = alert["shares"][i] if alert else 0.0     # no hits that day is a real 0
        if share is not None:
            rows.append((pd.Timestamp(day["date"]), float(share)))
    return pd.DataFrame(rows, columns=["date", "value"])


def fetch_whale_exit_share(days: int = 400, base: str | None = None) -> pd.DataFrame:
    url = f"{base or API_BASE}/api/market/alert-counts"
    try:
        res = requests.get(url, params={"days": days}, timeout=15)
        res.raise_for_status()
        return parse_whale_exit(res.json())
    except Exception as e:
        logger.warning("Twse_Top100_Heat alert counts unavailable (%s): %s", url, e)
        return pd.DataFrame(columns=["date", "value"])
