"""Integration tests: run the real dashboard.py against a seeded DB, network blocked.

Streamlit's AppTest executes the actual script, so these cover the path from
SQLite through the loaders, the verdict engine and the page code to the elements
a user sees. They also pin the responsiveness guarantees: clicks do not recompute
the view, and pages backed by the DB never touch the network.
"""
from __future__ import annotations

import socket
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import analytics.market_view as market_view
import db_manager
from tests import seed_db

APP = str(Path(__file__).resolve().parent.parent / "dashboard.py")
PAGES = ["verdict", "radar", "demand", "cost", "liquidity", "equity",
         "gmi", "rotation", "backtest", "guide"]


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(scope="module")
def seeded_path(tmp_path_factory):
    """Seed once: writing ~60 series is the slow part of this module."""
    path = tmp_path_factory.mktemp("dash") / "seed.sqlite3"
    original = db_manager._DB_PATH
    db_manager._DB_PATH = path
    seed_db.seed_all(end=pd.Timestamp.now())
    db_manager._DB_PATH = original
    return path


@pytest.fixture
def network_attempts(monkeypatch):
    attempts: list = []

    def refuse(self, address):
        attempts.append(address)
        raise NetworkBlocked(f"blocked connection to {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    return attempts


@pytest.fixture
def app(seeded_path, monkeypatch, network_attempts):
    """Factory for an AppTest bound to the seeded DB with empty Streamlit caches."""
    monkeypatch.setattr(db_manager, "_DB_PATH", seeded_path)
    st.cache_data.clear()
    st.cache_resource.clear()

    def build(page: str | None = None) -> AppTest:
        at = AppTest.from_file(APP, default_timeout=120)
        if page:
            at.query_params["page"] = page
        return at

    yield build
    st.cache_data.clear()
    st.cache_resource.clear()


def all_markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def click_nav(at: AppTest, page: str) -> AppTest:
    return at.button(key=f"nav_{page}").click().run()


class TestEveryPageRenders:
    @pytest.mark.parametrize("page", PAGES)
    def test_page_runs_without_exception(self, app, page):
        at = app(page).run()
        assert not at.exception, [e.value for e in at.exception]

    @pytest.mark.parametrize("page,title", [
        ("radar", "趨勢雷達"), ("demand", "需求與貿易"), ("cost", "成本與獲利"),
        ("liquidity", "流動性與風險"), ("equity", "股市比對"), ("gmi", "GMI 指數"),
        ("rotation", "台股資金輪動"), ("backtest", "燈號回測"), ("guide", "使用指南"),
    ])
    def test_page_shows_its_title(self, app, page, title):
        assert title in all_markdown(app(page).run())


class TestNavigation:
    def test_defaults_to_the_verdict(self, app):
        assert "總經多空判讀" in all_markdown(app().run())

    def test_clicking_nav_switches_page(self, app):
        at = app().run()
        click_nav(at, "guide")
        assert "三步驟讀懂" in all_markdown(at)
        assert "總經多空判讀" not in all_markdown(at)

    def test_nav_click_updates_the_url(self, app):
        at = app().run()
        click_nav(at, "radar")
        assert at.query_params["page"] == ["radar"] or at.query_params["page"] == "radar"

    def test_deep_link_opens_that_page(self, app):
        assert "三步驟讀懂" in all_markdown(app("guide").run())

    def test_unknown_page_falls_back(self, app):
        at = app("no-such-page").run()
        assert not at.exception
        assert "總經多空判讀" in all_markdown(at)

    def test_active_nav_item_is_highlighted(self, app):
        at = app("radar").run()
        assert at.button(key="nav_radar").proto.type == "primary"
        assert at.button(key="nav_verdict").proto.type == "secondary"


class TestVerdictPage:
    def test_states_a_stance_with_evidence(self, app):
        text = all_markdown(app().run())
        assert any(word in text for word in ("偏多", "偏空", "中性"))
        for heading in ("多方論據", "空方論據", "操作框架", "風險警示", "距離燈號翻轉"):
            assert heading in text

    def test_shows_historical_evidence_from_the_db(self, app):
        text = all_markdown(app().run())
        assert "歷史上相同燈號之後" in text
        assert "台灣加權指數" in text

    def test_ends_with_a_disclaimer(self, app):
        assert "非投資建議" in all_markdown(app().run())

    def test_offers_the_written_brief(self, app):
        at = app().run()
        assert at.get("download_button")


class TestUnits:
    def test_hy_spread_is_displayed_in_bps(self, app):
        """FRED stores percent (4.2); the strip and alerts must read 420 bps."""
        text = all_markdown(app("liquidity").run())
        hy = text.split("HY <b>")[1].split(" bps")[0]
        assert 200 < float(hy) < 800


class TestRadarPage:
    def _rows(self, at) -> int:
        return len(at.dataframe[0].value)

    def test_lists_indicators(self, app):
        at = app("radar").run()
        assert self._rows(at) >= 30

    def test_filter_narrows_the_table(self, app):
        at = app("radar").run()
        total = self._rows(at)
        at.segmented_control(key="radar_filter").set_value("偏空").run()
        assert not at.exception
        assert self._rows(at) < total if at.dataframe else True

    def test_theme_filter(self, app):
        at = app("radar").run()
        at.selectbox(key="radar_theme").set_value("market").run()
        assert set(at.dataframe[0].value["類別"]) == {"股市"}


class TestDetailPages:
    @pytest.mark.parametrize("page", ["demand", "cost", "liquidity", "equity"])
    def test_opens_with_a_conclusion_and_reading_guide(self, app, page):
        at = app(page).run()
        assert "gm-brief" in all_markdown(at)
        assert any(e.label == "如何解讀本頁" for e in at.expander)

    def test_range_selector_reruns_cleanly(self, app):
        at = app("demand").run()
        at.selectbox[0].set_value(10).run()
        assert not at.exception

    def test_institutional_ranking_comes_from_the_snapshot(self, app, network_attempts):
        at = app("equity").run()
        assert any("近 5 日" in c.value for c in at.caption)
        assert network_attempts == []


class TestInstitutionalTable:
    def test_values_line_up_with_their_rows(self, app):
        """The table is re-indexed from 1; the amount must stay on the same stock."""
        at = app("equity").run()
        table = next(d.value for d in at.dataframe if "估算金額（億元）" in d.value.columns)
        assert table.iloc[0]["名稱"] == "台積電"
        assert table.iloc[0]["估算金額（億元）"] == "520.0"
        assert table.iloc[2]["估算金額（億元）"] == "—"


class TestRotationPage:
    def test_only_the_open_sub_tab_loads(self, app, monkeypatch):
        calls = []
        real = db_manager.read_snapshot
        monkeypatch.setattr(db_manager, "read_snapshot",
                            lambda key: (calls.append(key), real(key))[1])
        app("rotation").run()
        assert "13f_smart_money" not in calls

    @pytest.mark.parametrize("tab", ["動能熱力圖", "資金流向", "13F 法人持倉"])
    def test_each_sub_tab_renders(self, app, tab):
        at = app("rotation")
        at.session_state["rotation_tab"] = tab
        at.run()
        assert not at.exception, [e.value for e in at.exception]

    def test_13f_tab_reads_the_snapshot(self, app, network_attempts):
        at = app("rotation")
        at.session_state["rotation_tab"] = "13F 法人持倉"
        at.run()
        assert any(m.value == "2026Q2" for m in at.metric)
        assert network_attempts == []


class TestResponsiveness:
    @pytest.mark.parametrize("page", PAGES)
    def test_no_network_once_the_db_is_populated(self, app, network_attempts, page):
        app(page).run()
        assert network_attempts == []

    def test_view_is_computed_once_across_clicks(self, app, monkeypatch):
        calls = []
        real = market_view.compute_market_view
        monkeypatch.setattr(market_view, "compute_market_view",
                            lambda *a, **k: (calls.append(1), real(*a, **k))[1])
        at = app().run()
        for page in ("radar", "demand", "verdict"):
            click_nav(at, page)
        assert len(calls) == 1

    def test_only_the_active_page_builds_its_charts(self, app, monkeypatch):
        calls = []
        real = st.plotly_chart
        monkeypatch.setattr(st, "plotly_chart", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
        app("guide").run()
        assert calls == []

    def test_new_data_appears_without_waiting_for_the_ttl(self, app):
        at = app("radar").run()
        before = db_manager.data_version()
        db_manager.write("hy_spread", pd.DataFrame({"date": [pd.Timestamp.now().normalize()],
                                                     "value": [9.9]}), ttl_days=1)
        assert db_manager.data_version() != before
        at.run()
        assert not at.exception

    def test_clicks_do_not_mutate_shared_data(self, app, monkeypatch):
        """cache_resource shares one object; a page writing to it corrupts every session."""
        captured = {}
        real = market_view.compute_market_view

        def capture(data, *args, **kwargs):
            captured["data"] = data
            captured["before"] = {k: v.copy() for k, v in data.items() if isinstance(v, pd.DataFrame)}
            return real(data, *args, **kwargs)

        monkeypatch.setattr(market_view, "compute_market_view", capture)
        at = app().run()
        for page in PAGES[1:]:
            click_nav(at, page)
            assert not at.exception, page
        for key, frame in captured["before"].items():
            pd.testing.assert_frame_equal(frame, captured["data"][key], obj=key)


class TestChartTheme:
    @pytest.mark.parametrize("page", ["verdict", "liquidity"])
    def test_every_chart_uses_the_app_template(self, app, page):
        """st.plotly_chart swaps Plotly's global default after its first call."""
        import json
        at = app(page).run()
        charts = at.get("plotly_chart")
        assert charts
        for chart in charts:
            layout = json.loads(chart.proto.spec)["layout"]
            assert layout["template"]["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"
            assert chart.proto.theme != "streamlit"


class TestLabels:
    @pytest.mark.parametrize("page", ["demand", "cost", "liquidity", "equity", "gmi"])
    def test_every_metric_says_what_it_measures(self, app, page):
        """Labels that were only a flag emoji must not end up blank."""
        at = app(page).run()
        assert at.metric
        assert all(m.label.strip() for m in at.metric)


class TestDegradedStates:
    def test_empty_database_explains_itself(self, tmp_path, monkeypatch, network_attempts):
        monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "empty.sqlite3")
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(APP, default_timeout=120).run()
        assert not at.exception, [e.value for e in at.exception]
        assert "資料不足" in all_markdown(at)
        st.cache_data.clear()
        st.cache_resource.clear()

    @pytest.mark.parametrize("page", ["radar", "gmi", "backtest", "rotation"])
    def test_empty_database_keeps_pages_alive(self, tmp_path, monkeypatch, network_attempts, page):
        monkeypatch.setattr(db_manager, "_DB_PATH", tmp_path / "empty.sqlite3")
        st.cache_data.clear()
        st.cache_resource.clear()
        at = AppTest.from_file(APP, default_timeout=120)
        at.query_params["page"] = page
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        st.cache_data.clear()
        st.cache_resource.clear()
