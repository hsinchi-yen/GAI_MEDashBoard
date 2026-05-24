"""
test_taiwan_sector.py — unit tests for fetchers/taiwan_sector.py

Covers (no live HTTP calls):
  - calc_sector_momentum(): column shape, ret/acceleration signs, min-data guard
  - detect_rotation_signal(): quadrant assignment logic
  - SECTOR_NAMES: completeness
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from unittest.mock import patch, MagicMock

from fetchers.taiwan_sector import (
    calc_sector_momentum,
    detect_rotation_signal,
    SECTOR_NAMES,
    fetch_tw_sector_institutional,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_sector_df(
    sector_name: str,
    prices: list[float],
    start: str = "2023-01-02",
    freq: str = "B",
) -> pd.DataFrame:
    """Create a minimal sector_df for a single sector."""
    dates = pd.date_range(start, periods=len(prices), freq=freq)
    return pd.DataFrame({
        "date":        dates,
        "sector_name": sector_name,
        "close":       prices,
    })


def _compound(n: int, monthly_ret: float, start: float = 100.0) -> list[float]:
    p = [start]
    for _ in range(n - 1):
        p.append(p[-1] * (1 + monthly_ret))
    return p


def _make_multi_sector(sector_returns: dict[str, float], n_days: int = 80) -> pd.DataFrame:
    """
    Build a multi-sector sector_df where each sector compounds at a daily rate.
    n_days must be > 60 (d_long=60) for calc_sector_momentum to include the sector.
    """
    frames = []
    for name, daily_ret in sector_returns.items():
        prices = _compound(n_days, daily_ret)
        frames.append(_make_sector_df(name, prices))
    return pd.concat(frames, ignore_index=True)


# ── calc_sector_momentum ──────────────────────────────────────────────────────

class TestCalcSectorMomentum:

    def test_returns_expected_columns(self):
        df = _make_multi_sector({"電子": 0.001}, n_days=80)
        result = calc_sector_momentum(df)
        required = {"sector_name", "ret_short_pct", "ret_long_pct",
                    "acceleration", "last_close", "last_date"}
        assert required.issubset(set(result.columns))

    def test_positive_return_when_price_rises(self):
        df = _make_multi_sector({"電子": 0.005}, n_days=80)
        result = calc_sector_momentum(df)
        assert not result.empty
        row = result[result["sector_name"] == "電子"].iloc[0]
        assert row["ret_short_pct"] > 0
        assert row["ret_long_pct"]  > 0

    def test_negative_return_when_price_falls(self):
        df = _make_multi_sector({"航運": -0.005}, n_days=80)
        result = calc_sector_momentum(df)
        assert not result.empty
        row = result[result["sector_name"] == "航運"].iloc[0]
        assert row["ret_short_pct"] < 0
        assert row["ret_long_pct"]  < 0

    def test_acceleration_positive_when_momentum_strengthening(self):
        """
        Acceleration > 0 means the recent short window return > the prior short window.
        Build a price series that accelerates upward in the last 20 days.
        """
        # Slow rise for the first 60 days, then faster rise for next 20 days.
        # With d_short=20, d_prev=40:  prices[-40...-20] is slow, prices[-20:] is fast.
        slow  = _compound(60, 0.001)
        fast  = _compound(21, 0.010, start=slow[-1])  # continues from last slow price
        prices = slow + fast[1:]          # 60 + 20 = 80 prices total
        df = _make_sector_df("電子", prices)
        result = calc_sector_momentum(df)
        row = result[result["sector_name"] == "電子"].iloc[0]
        assert row["acceleration"] > 0, f"Expected acceleration > 0, got {row['acceleration']}"

    def test_acceleration_negative_when_momentum_slowing(self):
        """Price decelerates: fast rise then slow rise → acceleration < 0."""
        fast  = _compound(40, 0.010)
        slow  = _compound(41, 0.001, start=fast[-1])
        prices = fast + slow[1:]
        df = _make_sector_df("金融", prices)
        result = calc_sector_momentum(df)
        row = result[result["sector_name"] == "金融"].iloc[0]
        assert row["acceleration"] < 0, f"Expected acceleration < 0, got {row['acceleration']}"

    def test_sorted_descending_by_ret_short(self):
        df = _make_multi_sector({"電子": 0.005, "金融": 0.002, "航運": -0.003}, n_days=80)
        result = calc_sector_momentum(df)
        assert result["ret_short_pct"].is_monotonic_decreasing

    def test_excludes_sector_with_insufficient_data(self):
        """Sector with fewer than d_long rows should be excluded."""
        short_df = _make_sector_df("新興", [100.0] * 30)  # only 30 days — < d_long(60)
        result = calc_sector_momentum(short_df)
        assert result.empty or "新興" not in result["sector_name"].values

    def test_empty_input_returns_empty(self):
        result = calc_sector_momentum(pd.DataFrame())
        assert result.empty

    def test_missing_close_column_returns_empty(self):
        df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5),
                           "sector_name": ["電子"] * 5})
        result = calc_sector_momentum(df)
        assert result.empty

    def test_last_close_equals_latest_price(self):
        prices = _compound(80, 0.002)
        df = _make_sector_df("電子", prices)
        result = calc_sector_momentum(df)
        row = result[result["sector_name"] == "電子"].iloc[0]
        assert abs(row["last_close"] - prices[-1]) < 0.01

    def test_multiple_sectors_all_present_in_output(self):
        sectors = {"電子": 0.003, "金融": 0.001, "鋼鐵": -0.002}
        df = _make_multi_sector(sectors, n_days=80)
        result = calc_sector_momentum(df)
        for name in sectors:
            assert name in result["sector_name"].values

    def test_custom_weeks_short_long(self):
        """Passing non-default weeks_short/weeks_long should not crash."""
        df = _make_multi_sector({"電子": 0.002}, n_days=120)
        result = calc_sector_momentum(df, weeks_short=2, weeks_long=8)
        assert not result.empty


# ── detect_rotation_signal ────────────────────────────────────────────────────

class TestDetectRotationSignal:

    def _momentum_row(self, ret_short: float, accel: float,
                      name: str = "X") -> pd.DataFrame:
        return pd.DataFrame({
            "sector_name":   [name],
            "ret_short_pct": [ret_short],
            "ret_long_pct":  [ret_short * 0.8],
            "acceleration":  [accel],
            "last_close":    [100.0],
            "last_date":     [pd.Timestamp.now()],
        })

    def test_hot_quadrant_positive_ret_positive_accel(self):
        df = self._momentum_row(ret_short=5.0, accel=1.0, name="電子")
        signals = detect_rotation_signal(df)
        assert "電子" in signals["hot"]
        assert "電子" not in signals["cooling"]
        assert "電子" not in signals["warming"]
        assert "電子" not in signals["cold"]

    def test_cooling_quadrant_positive_ret_negative_accel(self):
        df = self._momentum_row(ret_short=3.0, accel=-1.0, name="金融")
        signals = detect_rotation_signal(df)
        assert "金融" in signals["cooling"]

    def test_warming_quadrant_negative_ret_positive_accel(self):
        df = self._momentum_row(ret_short=-2.0, accel=0.5, name="航運")
        signals = detect_rotation_signal(df)
        assert "航運" in signals["warming"]

    def test_cold_quadrant_negative_ret_negative_accel(self):
        df = self._momentum_row(ret_short=-4.0, accel=-1.5, name="建材")
        signals = detect_rotation_signal(df)
        assert "建材" in signals["cold"]

    def test_returns_all_four_keys(self):
        df = self._momentum_row(ret_short=1.0, accel=1.0)
        signals = detect_rotation_signal(df)
        assert set(signals.keys()) == {"hot", "cooling", "warming", "cold"}

    def test_empty_input_returns_empty_lists(self):
        signals = detect_rotation_signal(pd.DataFrame())
        assert signals == {"hot": [], "cooling": [], "warming": [], "cold": []}

    def test_zero_boundary_ret_goes_to_hot_or_cooling(self):
        """ret_short_pct == 0 should go to hot/cooling (>=0), not warming/cold."""
        hot_df  = self._momentum_row(ret_short=0.0, accel=1.0,  name="A")
        cool_df = self._momentum_row(ret_short=0.0, accel=-1.0, name="B")
        assert "A" in detect_rotation_signal(hot_df)["hot"]
        assert "B" in detect_rotation_signal(cool_df)["cooling"]

    def test_zero_accel_boundary(self):
        """acceleration == 0 should go to hot/warming (>=0), not cooling/cold."""
        hot_df  = self._momentum_row(ret_short=2.0,  accel=0.0, name="C")
        warm_df = self._momentum_row(ret_short=-2.0, accel=0.0, name="D")
        assert "C" in detect_rotation_signal(hot_df)["hot"]
        assert "D" in detect_rotation_signal(warm_df)["warming"]

    def test_multi_sector_correctly_split(self):
        rows = [
            {"sector_name": "電子",  "ret_short_pct":  5.0, "acceleration":  1.0},
            {"sector_name": "金融",  "ret_short_pct":  3.0, "acceleration": -1.0},
            {"sector_name": "航運",  "ret_short_pct": -2.0, "acceleration":  0.5},
            {"sector_name": "建材",  "ret_short_pct": -4.0, "acceleration": -1.5},
        ]
        df = pd.DataFrame(rows)
        df["ret_long_pct"] = df["ret_short_pct"] * 0.8
        df["last_close"]   = 100.0
        df["last_date"]    = pd.Timestamp.now()
        signals = detect_rotation_signal(df)
        assert "電子" in signals["hot"]
        assert "金融" in signals["cooling"]
        assert "航運" in signals["warming"]
        assert "建材" in signals["cold"]

    def test_sector_appears_in_exactly_one_quadrant(self):
        rows = [
            {"sector_name": s, "ret_short_pct": r, "acceleration": a,
             "ret_long_pct": r, "last_close": 100.0, "last_date": pd.Timestamp.now()}
            for s, r, a in [("A", 1, 1), ("B", 1, -1), ("C", -1, 1), ("D", -1, -1)]
        ]
        df = pd.DataFrame(rows)
        signals = detect_rotation_signal(df)
        all_sectors = signals["hot"] + signals["cooling"] + signals["warming"] + signals["cold"]
        assert len(all_sectors) == len(set(all_sectors)), "Sector appears in multiple quadrants"


# ── SECTOR_NAMES completeness ─────────────────────────────────────────────────

class TestSectorNames:
    def test_has_19_sectors(self):
        assert len(SECTOR_NAMES) == 19

    def test_all_values_are_non_empty_strings(self):
        for code, name in SECTOR_NAMES.items():
            assert isinstance(name, str) and len(name) > 0

    def test_all_codes_are_numeric_strings(self):
        for code in SECTOR_NAMES:
            assert code.isdigit(), f"Non-numeric code: {code!r}"

    def test_electronics_sector_present(self):
        assert "14" in SECTOR_NAMES
        assert SECTOR_NAMES["14"] == "電子"


# ── fetch_tw_sector_institutional ─────────────────────────────────────────────
#
# BFI82U (selectType=ALLBUT0999) returns institution-TYPE rows (not sector rows):
#   fields: [單位名稱, 買進金額, 賣出金額, 買賣差額]
#   rows:   ["外資及陸資", buy, sell, net], ["投信", ...], ["自營商", ...], ...
#
# The function columns are: [date, institution, buy_amt, sell_amt, net_amt]

def _bfi82u_response(rows: list[list]) -> dict:
    """Build a minimal BFI82U ALLBUT0999 API JSON response."""
    return {
        "stat": "OK",
        "fields": ["單位名稱", "買進金額", "賣出金額", "買賣差額"],
        "data": rows,
    }


def _mock_get(response_json: dict, status: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status
    mock_resp.json.return_value = response_json
    return MagicMock(return_value=mock_resp)


class TestFetchTwSectorInstitutional:
    """Tests for fetch_tw_sector_institutional() — no live HTTP calls."""

    def _patch_get(self, response_json: dict, status: int = 200):
        return patch(
            "fetchers.taiwan_sector.requests.get",
            _mock_get(response_json, status),
        )

    # ── normal response parsing ────────────────────────────────────────────────

    def test_institution_name_stored_verbatim(self):
        """Institution names come from BFI82U row[0] and are stored as-is."""
        rows = [["外資及陸資", "1,000", "800", "200"]]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        assert not df.empty
        assert df.iloc[0]["institution"] == "外資及陸資"

    def test_all_institution_rows_captured(self):
        """All non-合計 rows should appear in output."""
        rows = [
            ["外資及陸資",          "5,000", "4,000", "1,000"],
            ["外資自營商",          "200",   "150",   "50"],
            ["投信",                "300",   "250",   "50"],
            ["自營商(自行買賣)",    "400",   "380",   "20"],
            ["自營商(避險)",        "100",   "90",    "10"],
        ]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        assert len(df) == 5
        assert set(df["institution"]) == {r[0] for r in rows}

    # ── stat != OK → empty DataFrame ───────────────────────────────────────────

    def test_stat_not_ok_returns_empty(self):
        bad = {"stat": "FAILURE", "data": []}
        with self._patch_get(bad):
            df = fetch_tw_sector_institutional(n_days=1)
        assert df.empty

    def test_http_error_returns_empty(self):
        with self._patch_get({}, status=503):
            df = fetch_tw_sector_institutional(n_days=1)
        assert df.empty

    # ── connection failure → empty DataFrame ───────────────────────────────────

    def test_connection_error_returns_empty(self):
        import requests as req_mod
        with patch("fetchers.taiwan_sector.requests.get",
                   side_effect=req_mod.ConnectionError("timeout")):
            df = fetch_tw_sector_institutional(n_days=1)
        assert df.empty

    # ── column format checks ───────────────────────────────────────────────────

    def test_returns_expected_columns(self):
        rows = [["外資及陸資", "500", "400", "100"]]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        assert list(df.columns) == ["date", "institution", "buy_amt", "sell_amt", "net_amt"]

    def test_date_column_is_timestamp(self):
        rows = [["投信", "200", "150", "50"]]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        assert pd.api.types.is_datetime64_any_dtype(df["date"])

    def test_amount_columns_are_numeric(self):
        rows = [["自營商", "300", "200", "100"]]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        for col in ("buy_amt", "sell_amt", "net_amt"):
            assert pd.api.types.is_float_dtype(df[col]), f"{col} is not float"

    def test_comma_separated_numbers_parsed(self):
        """Numbers with thousands separators (e.g. '1,234,567') should parse correctly."""
        rows = [["外資及陸資", "1,234,567", "987,654", "246,913"]]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        assert abs(df.iloc[0]["buy_amt"] - 1_234_567) < 1e-3

    def test_skip_total_row(self):
        """Rows with institution '合計' or '總計' must be skipped."""
        rows = [
            ["外資及陸資", "100", "80", "20"],
            ["合計",       "999", "888", "111"],
        ]
        with self._patch_get(_bfi82u_response(rows)):
            df = fetch_tw_sector_institutional(n_days=1)
        assert len(df) == 1
        assert "合計" not in df["institution"].values
