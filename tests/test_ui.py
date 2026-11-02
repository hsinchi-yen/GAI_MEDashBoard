"""Unit tests for the ui package: escaping, accessibility cues, chart reduction."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import pytest

from analytics import market_view as mv
from macro_index import build_macro_index_history
from tests.synthetic_data import NOW, macro_dataset
from ui import charts, components as c, theme


@pytest.fixture(scope="module")
def view():
    return mv.compute_market_view(macro_dataset(0.6), now=NOW)


class TestEscaping:
    """Fund and issuer names are external input; none may reach the page raw."""
    PAYLOAD = "<script>alert(1)</script>"

    def test_signal_card(self):
        sig = {"name": self.PAYLOAD, "raw": self.PAYLOAD, "rule": self.PAYLOAD}
        assert "<script>" not in c.signal_card("t", [sig], "bullish", "e")

    def test_changes_card(self):
        assert "<script>" not in c.changes_card([{"name": self.PAYLOAD, "raw": "1", "to": "bull"}])

    def test_alerts_card(self):
        html = c.alerts_card([{"title": self.PAYLOAD, "message": self.PAYLOAD, "level": "alert", "key": "x"}])
        assert "<script>" not in html

    def test_chip_page_head_section(self):
        for html in (c.chip(self.PAYLOAD), c.page_head(self.PAYLOAD, self.PAYLOAD), c.section(self.PAYLOAD)):
            assert "<script>" not in html


class TestHero:
    def test_shows_stance_label_and_headline(self, view):
        html = c.verdict_hero(view)
        assert view["stance"]["label"] in html
        assert view["gmi"]["as_of"] in html

    def test_never_relies_on_colour_alone(self, view):
        assert any(icon in c.verdict_hero(view) for icon in "▲▼●")

    def test_no_newlines_so_markdown_keeps_it_as_html(self, view):
        assert "\n" not in c.verdict_hero(view)

    def test_marks_exactly_one_scale_step_for_a_known_stance(self, view):
        assert c.verdict_hero(view).count('class="on"') == 1

    def test_unknown_stance_marks_no_step(self):
        html = c.verdict_hero(mv.compute_market_view({}, now=NOW))
        assert 'class="on"' not in html
        assert "資料不足" in html

    def test_pending_regime_disclosed(self, view):
        assert "待下月確認" in c.verdict_hero({**view, "pending_regime": "green"})


class TestCards:
    def test_pillars_render_each_name(self, view):
        html = c.pillar_cards(view["pillars"])
        for p in view["pillars"]:
            assert p["name"] in html

    def test_pillar_without_data_shows_placeholder(self):
        p = {"name": "需求", "desc": "d", "pct": None, "bull": 0, "valid": 0, "delta": None, "tone": "neutral"}
        assert "暫無資料" in c.pillar_cards([p])

    def test_empty_states_are_explicit(self):
        assert "沒有指標改變方向" in c.changes_card([])
        assert "目前沒有觸發中的風險警示" in c.alerts_card([])
        assert "空" in c.signal_card("t", [], "bearish", "空的")
        assert "暫無法定位" in c.clock_card(None)
        assert c.evidence_table([], "x") == ""

    def test_alert_card_mentions_stale_data(self):
        assert "3 項指標過期" in c.alerts_card([], stale_count=3)

    def test_clock_card_names_assets(self, view):
        assert view["clock"]["favoured"] in c.clock_card(view["clock"])

    def test_playbook_lists_actions(self, view):
        html = c.playbook_card(view["playbook"])
        assert all(a in html for a in view["playbook"]["actions"])

    @pytest.mark.parametrize("score,valid,expected", [
        (16, 19, "已在擴張區"), (5, 19, "已在收縮區"), (12, 19, "再 3 項轉多"),
    ])
    def test_flip_meter_wording(self, score, valid, expected):
        gmi = {"score": score, "valid_count": valid, "diffusion": score / valid * 100}
        html = c.flip_meter({"gmi": gmi, "flip": mv.flip_distance(gmi)})
        assert expected in html

    def test_flip_meter_without_data(self):
        gmi = {"score": 0, "valid_count": 0, "diffusion": 0.0}
        assert "暫無足夠指標" in c.flip_meter({"gmi": gmi, "flip": mv.flip_distance(gmi)})

    def test_evidence_table_flags_thin_samples(self):
        row = {"horizon": 12, "median": 5.0, "edge": 1.0, "win_rate": 60.0, "p10": -3.0, "n": 20, "n_eff": 1, "thin": True}
        assert "⚠" in c.evidence_table([row], "歷史")

    def test_disclaimer_present(self):
        assert "非投資建議" in c.disclaimer()


class TestTheme:
    def test_template_becomes_default(self):
        theme.register_plotly_theme()
        assert pio.templates.default == theme.TEMPLATE_NAME
        assert tuple(go.Figure().layout.template.layout.colorway or ()) == tuple(theme.CATEGORICAL)

    def test_css_is_a_single_style_block(self):
        css = theme.css()
        assert css.startswith("<style>") and css.endswith("</style>")
        assert css.count("{") == css.count("}")

    def test_css_supports_small_screens_and_keyboard_focus(self):
        css = theme.css()
        assert "@media (max-width" in css
        assert "focus-visible" in css

    def test_every_tone_has_icon_and_word(self):
        for tone in theme.TONES.values():
            assert tone["icon"] and tone["word"]


class TestDecimation:
    def test_short_series_are_untouched(self):
        assert len(charts.decimate_indices(np.arange(100.0))) == 100

    def test_long_series_are_reduced_near_the_cap(self):
        idx = charts.decimate_indices(np.arange(4000.0), max_points=800)
        assert len(idx) <= 820

    def test_spikes_survive(self):
        values = np.zeros(4000)
        values[1234], values[2345] = 80.0, -40.0
        kept = values[charts.decimate_indices(values)]
        assert kept.max() == 80.0 and kept.min() == -40.0

    def test_latest_two_points_are_exact(self):
        idx = charts.decimate_indices(np.random.default_rng(0).normal(size=4000))
        assert idx[-1] == 3999 and idx[-2] == 3998

    def test_indices_are_sorted_unique(self):
        idx = charts.decimate_indices(np.random.default_rng(1).normal(size=5000))
        assert (np.diff(idx) > 0).all()

    def test_all_nan_buckets_are_skipped(self):
        values = np.full(3000, np.nan)
        values[0] = 1.0
        assert len(charts.decimate_indices(values)) >= 1

    def test_figure_traces_are_thinned_with_customdata(self):
        n = 4000
        fig = go.Figure(go.Scatter(x=pd.date_range("2010-01-01", periods=n), y=np.arange(float(n)),
                                   customdata=np.arange(n)))
        charts.decimate_figure(fig)
        assert len(fig.data[0].y) <= charts.MAX_POINTS + 10
        assert len(fig.data[0].x) == len(fig.data[0].y) == len(fig.data[0].customdata)

    def test_non_scatter_traces_are_left_alone(self):
        fig = go.Figure(go.Bar(x=list(range(2000)), y=list(range(2000))))
        charts.decimate_figure(fig)
        assert len(fig.data[0].y) == 2000


class TestViewCharts:
    def test_diffusion_chart_marks_latest(self):
        hist = build_macro_index_history(macro_dataset(0.5), lookback_years=3)
        fig = charts.diffusion_chart(hist)
        assert len(fig.data) == 2
        assert fig.data[1].text[0].endswith("%")

    def test_diffusion_chart_empty(self):
        assert charts.diffusion_chart(pd.DataFrame()) is None
        assert charts.diffusion_chart(None) is None

    def test_clock_chart_has_trail_and_latest(self, view):
        fig = charts.clock_chart(view["clock"])
        assert len(fig.data) == 2
        assert fig.data[1].text[0] == "最新"

    def test_clock_chart_empty(self):
        assert charts.clock_chart(None) is None
