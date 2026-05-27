"""
test_new_fetchers.py — unit tests for the rewritten data sources (no live HTTP):
  - fetch_china_nbs_pmi / fetch_china_nbs_ppi_yoy  (Eastmoney datacenter)
  - fetch_china_credit_impulse                     (MOFCOM social-financing TTM YoY)
  - fetch_ndc_leading_index / fetch_ndc_light_score (NDC SPA: csrf + POST)
  - fetch_tsmc_revenue_yoy                         (FinMind history + TWSE OpenAPI latest)
"""
from __future__ import annotations

import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from fetchers.global_macro import (
    fetch_china_nbs_pmi, fetch_china_nbs_ppi_yoy,
    fetch_ndc_leading_index, fetch_ndc_light_score,
)
from fetchers.fred import fetch_china_credit_impulse
from fetchers.taiwan import fetch_tsmc_revenue_yoy


def _resp(json_obj, status=200, text=""):
    m = MagicMock()
    m.status_code = status
    m.ok = status < 400
    m.json.return_value = json_obj
    m.text = text
    m.raise_for_status = MagicMock()
    return m


# ── Eastmoney (PMI / PPI) ──────────────────────────────────────────────────────

def _eastmoney_payload(value_col, values):
    """values: list of (TIME, number) newest-first, like the real API."""
    return {"result": {"data": [{"TIME": t, value_col: v} for t, v in values]}}


class TestEastmoneyEconomy:
    def test_pmi_parses_make_index(self):
        payload = _eastmoney_payload("MAKE_INDEX",
                                     [("2026年04月份", 50.3), ("2026年03月份", 50.4)])
        with patch("fetchers.utils.requests.get", return_value=_resp(payload)):
            df = fetch_china_nbs_pmi()
        assert list(df.columns) == ["date", "value"]
        assert df.iloc[-1]["date"] == pd.Timestamp("2026-04-01")
        assert df.iloc[-1]["value"] == pytest.approx(50.3)

    def test_ppi_parses_base_same(self):
        payload = _eastmoney_payload("BASE_SAME",
                                     [("2026年04月份", 2.8), ("2026年03月份", 0.5)])
        with patch("fetchers.utils.requests.get", return_value=_resp(payload)):
            df = fetch_china_nbs_ppi_yoy()
        assert df.iloc[-1]["value"] == pytest.approx(2.8)

    def test_empty_on_failure(self):
        with patch("fetchers.utils.requests.get", return_value=_resp({"result": None})):
            assert fetch_china_nbs_pmi().empty


# ── China credit impulse (MOFCOM social financing) ─────────────────────────────

class TestCreditImpulse:
    def _rows(self, n, flow_fn):
        # newest-first like the real endpoint
        out = []
        base = pd.Timestamp("2026-01-01")
        for i in range(n):
            d = (base - pd.DateOffset(months=i))
            out.append({"date": f"{d.year}{d.month:02d}", "tiosfs": flow_fn(n - i)})
        return out

    def _patch_session(self, rows):
        sess = MagicMock()
        sess.post.return_value = _resp(rows)
        return patch("fetchers.fred.legacy_tls_session", return_value=sess)

    def test_rising_flow_gives_positive_impulse(self):
        with self._patch_session(self._rows(30, lambda k: 1000 + 50 * k)):
            df = fetch_china_credit_impulse()
        assert list(df.columns) == ["date", "value"]
        assert df.iloc[-1]["value"] > 0          # accelerating credit → positive impulse

    def test_insufficient_rows_returns_empty(self):
        with self._patch_session(self._rows(10, lambda k: 1000.0)):
            assert fetch_china_credit_impulse().empty


# ── NDC (csrf + POST) ──────────────────────────────────────────────────────────

class TestNDC:
    def _patch(self, line):
        sess = MagicMock()
        sess.get.return_value = _resp(
            {}, text='<meta name="csrf-token" content="TOK123">')
        sess.post.return_value = _resp({"line": line})
        return patch("fetchers.global_macro.requests.Session", return_value=sess)

    def test_leading_parses_yyyymm(self):
        line = [{"x": "202601", "y": 100.5}, {"x": "202602", "y": 101.2}]
        with self._patch(line):
            df = fetch_ndc_leading_index()
        assert df.iloc[-1]["date"] == pd.Timestamp("2026-02-01")
        assert df.iloc[-1]["value"] == pytest.approx(101.2)

    def test_light_score_parses(self):
        with self._patch([{"x": "202603", "y": 39}]):
            df = fetch_ndc_light_score()
        assert df.iloc[-1]["value"] == pytest.approx(39)

    def test_missing_csrf_returns_empty(self):
        sess = MagicMock()
        sess.get.return_value = _resp({}, text="<html>no token</html>")
        with patch("fetchers.global_macro.requests.Session", return_value=sess):
            assert fetch_ndc_leading_index().empty


# ── TSMC (FinMind history + TWSE OpenAPI latest) ───────────────────────────────

class TestTSMC:
    def _finmind(self):
        # 14 months of revenue so compute_yoy (12-period) yields ≥1 point
        data = []
        for i in range(14):
            d = pd.Timestamp("2025-01-01") + pd.DateOffset(months=i)
            data.append({"revenue_year": d.year, "revenue_month": d.month,
                         "revenue": 1_000_000 * (1 + 0.10 * (i // 12))})  # +10% after a year
        return {"data": data}

    def _twse(self):
        return [{"公司代號": "2330", "資料年月": "11503",
                 "營業收入-去年同月增減(%)": 17.5}]

    def test_history_plus_latest_override(self):
        def _side(url, **kw):
            if "finmindtrade" in url:
                return _resp(self._finmind())
            return _resp(self._twse())
        with patch("fetchers.taiwan.requests.get", side_effect=_side):
            df = fetch_tsmc_revenue_yoy(years_back=5)
        assert list(df.columns) == ["date", "value"]
        # TWSE latest month (民國115/03 → 2026-03) present and authoritative
        row = df[df["date"] == pd.Timestamp("2026-03-01")]
        assert not row.empty
        assert row.iloc[0]["value"] == pytest.approx(17.5)

    def test_finmind_fails_but_twse_latest_survives(self):
        def _side(url, **kw):
            if "finmindtrade" in url:
                return _resp({"msg": "limit"}, status=402)
            return _resp(self._twse())
        with patch("fetchers.taiwan.requests.get", side_effect=_side):
            df = fetch_tsmc_revenue_yoy()
        assert len(df) >= 1
        assert df.iloc[-1]["value"] == pytest.approx(17.5)
