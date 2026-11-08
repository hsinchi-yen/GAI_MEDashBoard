"""Tests for analytics/smart_money.py and the 13F delta naming fix."""
from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import analytics.smart_money as sm
from analytics.smart_money import (
    ETF, OTHER, SECTOR_COLOR, SECTORS, build_rank_table, classify_sector,
    looks_like_cusip, sector_net_flow,
)

NAMES_FILE = Path(__file__).parent / "data" / "13f_names_2026q2.txt"


def real_names() -> list[str]:
    lines = NAMES_FILE.read_text(encoding="utf-8").splitlines()
    return [n for n in lines if n and not n.startswith("#")]


class TestWholeWordMatching:
    @pytest.mark.parametrize("name, wrong", [
        ("CHARTER COMMUNICATIONS INC N", "半導體"),   # "MU" ticker used to match
        ("MUELLER INDS INC", "半導體"),
        ("ALLY FINL INC", "醫療保健"),                 # "LLY"
        ("HUNTSMAN CORP", "半導體"),                   # "TSM"
        ("BRKR BRUKER", "金融"),                       # "BRK"
        ("SANDISK CORP", "能源"),
    ])
    def test_short_keywords_no_longer_hit_inside_words(self, name, wrong):
        assert classify_sector(name) != wrong

    @pytest.mark.parametrize("name, sector", [
        ("ELI LILLY & CO", "醫療保健"),
        ("TAIWAN SEMICONDUCTOR MANUFAC", "半導體"),
        ("META PLATFORMS INC", "通訊服務"),
        ("APPLIED MATLS INC", "半導體"),
        ("AT&T INC", "通訊服務"),
        ("T-MOBILE US INC", "通訊服務"),
        ("JD.COM INC", "非必需消費"),
        ("AMAZON COM INC", "非必需消費"),
        ("ALLY FINL INC", "金融"),
        ("CHARTER COMMUNICATIONS INC N", "通訊服務"),
        ("SANDISK CORP", "資訊科技"),
        ("LINDE PLC", "原物料"),
    ])
    def test_known_issuers(self, name, sector):
        assert classify_sector(name) == sector

    def test_truncated_last_word_matches_by_prefix(self):
        assert classify_sector("VERTEX PHARMACEUTICALS INC NE…") == "醫療保健"
        assert classify_sector("CHARTER COMM…") == "通訊服務"

    def test_industry_words_cover_unlisted_names(self):
        assert classify_sector("ACME THERAPEUTICS INC") == "醫療保健"
        assert classify_sector("FIRST WIDGET BANCORP") == "金融"
        assert classify_sector("NOWHERE GOLD MINES LTD") == "原物料"

    def test_company_phrase_beats_industry_word(self):
        # "HEALTH" alone would say 醫療保健 too, but "PALO ALTO NETWORKS" must
        # win over the generic "NETWORKS" only through the phrase list.
        assert classify_sector("PALO ALTO NETWORKS INC") == "資訊科技"
        assert classify_sector("ICICI BANK LIMITED") == "金融"

    def test_cusips_and_blanks_are_other(self):
        assert looks_like_cusip("03040WBE4")
        assert not looks_like_cusip("NVIDIA CORP")
        assert classify_sector("880881107") == OTHER
        assert classify_sector("") == OTHER

    def test_result_does_not_depend_on_rule_order(self, monkeypatch):
        names = real_names()
        before = {n: classify_sector(n) for n in names}
        rng = random.Random(7)
        for attr in ("_COMPANY_RULES", "_INDUSTRY_RULES"):
            rules = list(getattr(sm, attr))
            rng.shuffle(rules)
            # Re-sort the way the module does; order of the source table is irrelevant.
            monkeypatch.setattr(sm, attr, sorted(
                rules, key=lambda r: (-len(r[0]), -sum(map(len, r[0])))))
        assert {n: classify_sector(n) for n in names} == before


class TestTaxonomy:
    def test_every_sector_used_has_a_color(self):
        used = set(sm._COMPANIES) | set(sm._INDUSTRY_WORDS)
        assert used <= set(SECTOR_COLOR)
        assert OTHER in SECTORS and ETF in SECTORS

    def test_no_duplicate_synonyms(self):
        for a, b in (("科技", "資訊科技"), ("醫療", "醫療保健"), ("消費", "非必需消費")):
            assert not (a in SECTORS and b in SECTORS)

    def test_real_quarter_coverage(self):
        names = real_names()
        result = [classify_sector(n) for n in names]
        non_etf = [s for s in result if s != ETF]
        other_share = non_etf.count(OTHER) / len(non_etf)
        assert other_share <= 0.15, other_share


SMART = {
    "quarter": "2026Q2", "fund_count": 18,
    "top_buy_value":  [("NVIDIA CORP", 980.5, 9), ("MICROSOFT", 420.0, 7)],
    "top_sell_value": [("TESLA", -610.0, 6), ("EXXON", -120.0, 4)],
}


class TestRankTable:
    def test_all_has_both_directions_sorted_by_net_value(self):
        df = build_rank_table(SMART)
        assert list(df["持倉名稱"]) == ["NVIDIA CORP", "MICROSOFT", "EXXON", "TESLA"]
        assert set(df["訊號"]) == {"🟢 買入", "🔴 賣出"}
        assert list(df["排名"]) == [1, 2, 3, 4]

    def test_sell_side_puts_largest_outflow_first(self):
        df = build_rank_table(SMART, side="賣方")
        assert list(df["持倉名稱"]) == ["TESLA", "EXXON"]
        assert (df["淨增持（$M）"] < 0).all()

    def test_buy_side_only_buys(self):
        df = build_rank_table(SMART, side="買方")
        assert (df["淨增持（$M）"] > 0).all()

    @pytest.mark.parametrize("smart", [None, {}, {"top_buy_value": []},
                                       {"top_sell_value": None}])
    def test_empty_snapshot_gives_empty_frame_with_columns(self, smart):
        df = build_rank_table(smart)
        assert df.empty and list(df.columns) == sm.RANK_COLUMNS
        assert sector_net_flow(df).empty

    def test_sector_net_flow_nets_buys_against_sells(self):
        flow = sector_net_flow(build_rank_table(SMART)).set_index("板塊")
        assert flow.loc["半導體", "淨增持（$M）"] == pytest.approx(980.5)
        assert flow.loc["非必需消費", "淨增持（$M）"] == pytest.approx(-610.0)
        assert flow.loc["能源", "淨增持（$M）"] == pytest.approx(-120.0)
        assert flow["淨增持（$M）"].is_monotonic_decreasing


class TestFundDeltaNames:
    def test_sold_out_position_keeps_its_name(self):
        from fetchers import edgar_13f
        cur = [{"cusip": "111111111", "name": "KEPT CORP", "shares": 10, "value_k": 100}]
        prev = [{"cusip": "111111111", "name": "KEPT CORP", "shares": 5, "value_k": 50},
                {"cusip": "880881107", "name": "SOLD OUT INC", "shares": 7, "value_k": 70}]
        with patch.object(edgar_13f, "_edgar_get_13f_accessions",
                          return_value=[{"accession": "a", "reportDate": "2026-06-30"},
                                        {"accession": "b", "reportDate": "2026-03-31"}]), \
             patch.object(edgar_13f, "_edgar_get_infotable_url", side_effect=["cur", "prev"]), \
             patch.object(edgar_13f, "_edgar_parse_infotable", side_effect=[cur, prev]):
            delta, _ = edgar_13f._fetch_fund_delta("F", "0")
        assert delta["880881107"]["name"] == "SOLD OUT INC"
        assert delta["880881107"]["share_delta"] == -7
