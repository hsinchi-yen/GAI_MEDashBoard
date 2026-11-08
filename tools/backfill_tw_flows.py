"""Build fetchers/data/tw_flows_seed.csv: 10+ years of Taiwan market flows.

Run once on a workstation; the CSV is committed and the scheduler bulk-loads it
into an empty DB, so production needs neither this script nor a FinMind token.

    python tools/backfill_tw_flows.py breadth            # TWSE MI_INDEX, ~2 h, resumable
    python tools/backfill_tw_flows.py finmind            # margin / foreign / futures / turnover
    python tools/backfill_tw_flows.py build              # → fetchers/data/tw_flows_seed.csv

Sources:
    breadth, closes   TWSE MI_INDEX ALLBUT0999, one request per weekday (official
                      counts match the daily job exactly; FinMind's classification
                      differs by a few stocks)
    margin            FinMind TaiwanStockTotalMarginPurchaseShortSale (MarginPurchaseMoney)
    foreign cash      FinMind TaiwanStockTotalInstitutionalInvestors (Foreign_Investor)
    foreign futures   FinMind TaiwanFuturesInstitutionalInvestors TX and MTX (外資)
    turnover, close   FinMind TaiwanStockPrice TAIEX (Trading_money, close)

The FinMind values equal the TWSE / TAIFEX ones they stand in for (checked on
2026-10-13/14: foreign buy 342,184,505,336, TX foreign short OI 115,803).

The token is read from FINMIND_TOKEN or --token-file and only ever sent in the
Authorization header; it is never printed or written anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fetchers.taiwan import _HDR_TWSE  # noqa: E402
from fetchers.taiwan_market import (  # noqa: E402
    CLOSE_WINDOW_DAYS, CLOSES_SEED_CSV, MTX_PER_TX, SEED_CSV, SERIES, TWSE, ma_breadth,
    parse_mi_index,
)

CACHE = ROOT / "app_data" / "cache" / "tw_backfill"
FINMIND = "https://api.finmindtrade.com/api/v4/data"
START = pd.Timestamp("2015-01-01")
_BN = 1e8


# ── breadth (TWSE, resumable day files) ───────────────────────────────────────

def _day_file(day: pd.Timestamp) -> Path:
    return CACHE / "mi" / f"{day:%Y%m%d}.csv"


def _none_file(day: pd.Timestamp) -> Path:
    return CACHE / "mi" / f"{day:%Y%m%d}.none"


def _mi_index(day: pd.Timestamp) -> dict | None:
    """Raw MI_INDEX body; None only when the request itself kept failing.

    A holiday comes back as a normal answer with a "no data" stat, which must be
    told apart from throttling (HTTP error or HTML instead of JSON).
    """
    for attempt in range(4):
        try:
            res = requests.get(f"{TWSE}/afterTrading/MI_INDEX",
                               params={"date": f"{day:%Y%m%d}", "type": "ALLBUT0999",
                                       "response": "json"},
                               headers=_HDR_TWSE, timeout=60)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            wait = 60 * (attempt + 1)
            print(f"  {day:%Y-%m-%d} failed ({e.__class__.__name__}); retry in {wait}s", flush=True)
            time.sleep(wait)
    return None


def backfill_breadth(start: pd.Timestamp, end: pd.Timestamp, sleep: float) -> None:
    (CACHE / "mi").mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(start, end)
    todo = [d for d in days if not _day_file(d).exists() and not _none_file(d).exists()]
    print(f"breadth: {len(days)} weekdays, {len(todo)} to fetch")
    for i, day in enumerate(todo, 1):
        body = _mi_index(day)
        if body is None:
            continue                       # gave up for now; a rerun retries this day
        if body.get("stat") != "OK":       # holiday / typhoon day: TWSE says "no data"
            _none_file(day).touch()
        else:
            counts, closes = parse_mi_index(body)
            with _day_file(day).open("w", encoding="utf-8", newline="") as fh:
                fh.write("#" + json.dumps(counts) + "\n")
                closes.to_csv(fh, index=False)
        if i % 50 == 0:
            print(f"  {i}/{len(todo)} {day:%Y-%m-%d}", flush=True)
        time.sleep(sleep)


def load_breadth() -> tuple[pd.DataFrame, pd.DataFrame]:
    counts, closes = [], []
    for path in sorted((CACHE / "mi").glob("*.csv")):
        day = pd.Timestamp(path.stem)
        with path.open(encoding="utf-8") as fh:
            meta = json.loads(fh.readline()[1:])
            df = pd.read_csv(fh, dtype={"code": str})
        counts.append({"date": day, "tw_adv": meta.get("adv"), "tw_dec": meta.get("dec")})
        closes.append(df.assign(date=day))
    if not counts:
        return pd.DataFrame(columns=["date"]), pd.DataFrame(columns=["date", "code", "close"])
    return pd.DataFrame(counts), pd.concat(closes, ignore_index=True)


# ── FinMind ───────────────────────────────────────────────────────────────────

def _token(path: str | None) -> str:
    tok = os.environ.get("FINMIND_TOKEN", "").strip()
    if not tok and path:
        tok = next((ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
                    if ln.strip()), "")
    if not tok:
        sys.exit("FINMIND_TOKEN not set and no --token-file given")
    return tok


def _finmind(token: str, dataset: str, start: str, end: str, **params) -> pd.DataFrame:
    for attempt in range(5):
        res = requests.get(FINMIND, params={"dataset": dataset, "start_date": start,
                                            "end_date": end, **params},
                           headers={"Authorization": f"Bearer {token}"}, timeout=120)
        if res.status_code == 402:          # hourly quota: wait it out
            print("  FinMind quota reached; waiting 10 min", flush=True)
            time.sleep(600)
            continue
        res.raise_for_status()
        return pd.DataFrame(res.json().get("data", []))
    raise RuntimeError(f"FinMind {dataset} failed after retries")


def backfill_finmind(token: str, start: pd.Timestamp, end: pd.Timestamp) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    frames: dict[str, list[pd.DataFrame]] = {k: [] for k in ("margin", "fini", "tx", "mtx", "taiex")}
    for year in range(start.year, end.year + 1):
        s, e = f"{year}-01-01", f"{year}-12-31"
        print(f"finmind {year}", flush=True)
        frames["margin"].append(_finmind(token, "TaiwanStockTotalMarginPurchaseShortSale", s, e))
        frames["fini"].append(_finmind(token, "TaiwanStockTotalInstitutionalInvestors", s, e))
        frames["tx"].append(_finmind(token, "TaiwanFuturesInstitutionalInvestors", s, e, data_id="TX"))
        frames["mtx"].append(_finmind(token, "TaiwanFuturesInstitutionalInvestors", s, e, data_id="MTX"))
        frames["taiex"].append(_finmind(token, "TaiwanStockPrice", s, e, data_id="TAIEX"))
        time.sleep(1)
    for name, parts in frames.items():
        pd.concat(parts, ignore_index=True).to_csv(CACHE / f"finmind_{name}.csv", index=False)


def _fut_net(df: pd.DataFrame) -> pd.Series:
    f = df[df["institutional_investors"] == "外資"]
    net = f["long_open_interest_balance_volume"] - f["short_open_interest_balance_volume"]
    return pd.Series(net.values, index=pd.to_datetime(f["date"])).groupby(level=0).last()


def load_finmind() -> pd.DataFrame:
    def read(name):
        return pd.read_csv(CACHE / f"finmind_{name}.csv")

    m = read("margin")
    m = m[m["name"] == "MarginPurchaseMoney"]
    margin = pd.Series(m["TodayBalance"].values / _BN, index=pd.to_datetime(m["date"]))

    f = read("fini")
    f = f[f["name"] == "Foreign_Investor"]
    fini = pd.Series((f["buy"] - f["sell"]).values / _BN, index=pd.to_datetime(f["date"]))

    tx, mtx = _fut_net(read("tx")), _fut_net(read("mtx"))
    fut = tx.add(mtx.reindex(tx.index).fillna(0) / MTX_PER_TX)

    t = read("taiex")
    turnover = pd.Series(t["Trading_money"].values / _BN, index=pd.to_datetime(t["date"]))
    taiex = pd.Series(t["close"].values, index=pd.to_datetime(t["date"]))

    out = pd.DataFrame({"tw_margin": margin, "tw_fini_net": fini,
                        "tw_fini_fut_oi": fut, "tw_turnover": turnover, "taiex_daily": taiex})
    out.index.name = "date"
    return out.reset_index()


# ── build ─────────────────────────────────────────────────────────────────────

def build() -> None:
    counts, closes = load_breadth()
    print(f"breadth days: {len(counts)}; close rows: {len(closes)}")
    ma = ma_breadth(closes).rename(columns={"pct_ma20": "tw_pct_ma20", "pct_ma60": "tw_pct_ma60"})
    flows = load_finmind()
    wide = (flows.merge(counts, on="date", how="outer").merge(ma, on="date", how="left")
            .sort_values("date"))
    wide = wide[wide["date"] >= START]
    cols = ["date", *[c for c in (*SERIES, "taiex_daily") if c in wide.columns]]
    wide[cols].to_csv(SEED_CSV, index=False, float_format="%.4f", date_format="%Y-%m-%d")
    recent = sorted(closes["date"].unique())[-CLOSE_WINDOW_DAYS:]
    tail = closes[closes["date"].isin(recent)][["date", "code", "close"]]
    tail.to_csv(CLOSES_SEED_CSV, index=False, date_format="%Y-%m-%d", compression="gzip")
    print(f"wrote {CLOSES_SEED_CSV.relative_to(ROOT)}: {len(tail)} rows")
    print(f"wrote {SEED_CSV.relative_to(ROOT)}: {len(wide)} rows, "
          f"{wide['date'].min():%Y-%m-%d} → {wide['date'].max():%Y-%m-%d}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("breadth", "finmind", "build"))
    ap.add_argument("--start", default=str(START.date()))
    ap.add_argument("--end", default=str(pd.Timestamp.now().date()))
    ap.add_argument("--sleep", type=float, default=2.5, help="seconds between TWSE requests")
    ap.add_argument("--token-file")
    args = ap.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    if args.step == "breadth":
        backfill_breadth(start, end, args.sleep)
    elif args.step == "finmind":
        backfill_finmind(_token(args.token_file), start, end)
    else:
        build()


if __name__ == "__main__":
    main()
