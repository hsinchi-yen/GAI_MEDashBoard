"""Design tokens, global CSS and the Plotly template.

Everything visual derives from TOKENS, so one change restyles the whole app.
Colours come from a validated palette (CVD-checked against the chart surface).
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

FONT_STACK = ('"Segoe UI", -apple-system, BlinkMacSystemFont, "PingFang TC", '
              '"Microsoft JhengHei", "Noto Sans TC", system-ui, sans-serif')

TOKENS = {
    "bg":        "#0d0d0d",
    "surface":   "#1a1a19",
    "surface_2": "#242423",
    "line":      "rgba(255,255,255,0.10)",
    "grid":      "#2c2c2a",
    "axis":      "#383835",
    "ink":       "#f0efec",
    "ink_2":     "#c3c2b7",
    "muted":     "#989691",
    "accent":    "#3987e5",
    # Status colours carry meaning; each ships with an icon and a label.
    "bull":      "#2fbf5b",
    "bear":      "#e66767",
    "flat":      "#fab219",
    "serious":   "#ec835a",
}

CATEGORICAL = ["#3987e5", "#d95926", "#199e70", "#c98500",
               "#d55181", "#008300", "#9085e9", "#e66767"]

TONES = {
    "bullish": {"color": TOKENS["bull"], "icon": "▲", "word": "偏多"},
    "bearish": {"color": TOKENS["bear"], "icon": "▼", "word": "偏空"},
    "neutral": {"color": TOKENS["flat"], "icon": "●", "word": "中性"},
}

TEMPLATE_NAME = "gmi"
HIDDEN_MODEBAR = ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"]


def _axis(grid: bool) -> dict:
    return dict(
        showgrid=grid, gridcolor=TOKENS["grid"], gridwidth=1,
        zeroline=False, showline=not grid, linecolor=TOKENS["axis"],
        ticks="", tickfont=dict(color=TOKENS["muted"], size=11),
        title=dict(font=dict(color=TOKENS["muted"], size=11)),
        automargin=True,
    )


def register_plotly_theme() -> None:
    """Install the template as the default for every go/px figure."""
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(family=FONT_STACK, color=TOKENS["ink_2"], size=12),
        title=dict(font=dict(size=14, color=TOKENS["ink"]), x=0, xanchor="left",
                   xref="container", pad=dict(l=14)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        colorway=CATEGORICAL,
        xaxis=_axis(grid=False),
        yaxis=_axis(grid=True),
        hoverlabel=dict(bgcolor=TOKENS["surface_2"], bordercolor=TOKENS["axis"],
                        font=dict(color=TOKENS["ink"], family=FONT_STACK, size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor="rgba(0,0,0,0)", font=dict(color=TOKENS["ink_2"], size=11)),
        hovermode="x unified",
        margin=dict(t=48, b=28, l=14, r=14),
    )
    template.data.scatter = [go.Scatter(line=dict(width=2))]
    pio.templates[TEMPLATE_NAME] = template
    pio.templates.default = TEMPLATE_NAME


def css() -> str:
    t = TOKENS
    return f"""<style>
:root {{
  --bg:{t['bg']}; --surface:{t['surface']}; --surface-2:{t['surface_2']}; --line:{t['line']};
  --ink:{t['ink']}; --ink-2:{t['ink_2']}; --muted:{t['muted']}; --accent:{t['accent']};
  --bull:{t['bull']}; --bear:{t['bear']}; --flat:{t['flat']};
}}
html, body, [class*="css"], .stApp {{ font-family:{FONT_STACK}; }}
[data-testid="stHeader"] {{ background:transparent; height:0; }}
[data-testid="stAppDeployButton"], [data-testid="stStatusWidget"] {{ display:none; }}
.block-container {{ padding:1.25rem 2rem 3rem; max-width:1320px; }}

h1, h2, h3, h4 {{ letter-spacing:0; font-weight:600; color:var(--ink); }}
h2 {{ font-size:1.25rem !important; margin-top:.75rem !important; }}
h3 {{ font-size:1.05rem !important; }}
h4, h5 {{ font-size:.95rem !important; color:var(--ink-2); }}
hr {{ border-color:var(--line); margin:1.25rem 0; }}

/* Sidebar navigation */
section[data-testid="stSidebar"] {{ background:var(--bg); border-right:1px solid var(--line); }}
section[data-testid="stSidebar"] .stButton button {{
  justify-content:flex-start; text-align:left; width:100%; min-height:34px; padding:4px 10px;
  border:0; border-radius:6px; background:transparent; color:var(--ink-2); font-weight:400;
}}
section[data-testid="stSidebar"] .stButton button > div,
section[data-testid="stSidebar"] .stButton button p {{ justify-content:flex-start; text-align:left; width:100%; }}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] {{ margin-bottom:0 !important; }}
section[data-testid="stSidebar"] .stButton button:hover {{ background:var(--surface-2); color:var(--ink); }}
section[data-testid="stSidebar"] .stButton button:focus-visible {{ outline:2px solid var(--accent); }}
section[data-testid="stSidebar"] .stButton button[kind="primary"] {{
  background:var(--surface-2); color:var(--ink); font-weight:600;
  box-shadow:inset 2px 0 0 var(--accent);
}}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap:.25rem; }}

/* Native widgets */
[data-testid="stMetric"] {{
  background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:10px 14px;
}}
[data-testid="stMetricLabel"] {{ color:var(--muted); }}
[data-testid="stMetricValue"] {{ font-size:1.35rem; font-weight:600; }}
[data-testid="stExpander"] details {{ border:1px solid var(--line); border-radius:8px; background:var(--surface); }}
.stTabs [data-baseweb="tab-list"] {{ gap:1.25rem; border-bottom:1px solid var(--line); }}
.stTabs [data-baseweb="tab"] {{ padding:6px 0; background:transparent; }}
[data-testid="stPlotlyChart"] {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
/* Streamlit's frontend paints its own colours over a transparent chart background. */
[data-testid="stPlotlyChart"] .main-svg {{ background:transparent !important; }}
[data-testid="stPlotlyChart"] .bglayer .bg {{ fill:transparent !important; }}

/* Components */
.gm-eyebrow {{ color:var(--muted); font-size:.75rem; letter-spacing:.04em; }}
.gm-brand {{ font-size:1rem; font-weight:600; line-height:1.4; color:var(--ink); padding:4px 10px 0; }}
.gm-navlabel {{ color:var(--muted); font-size:.72rem; line-height:1.4; padding:12px 10px 2px; }}

.gm-hero {{ display:grid; grid-template-columns:minmax(0,1.5fr) minmax(280px,1fr); gap:24px;
  background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--tone);
  border-radius:8px; padding:20px 24px; }}
.gm-stance {{ font-size:2.5rem; font-weight:700; line-height:1.15; color:var(--tone); margin:4px 0 8px; }}
.gm-headline {{ font-size:1rem; color:var(--ink); line-height:1.6; margin:0; }}
.gm-meaning {{ font-size:.875rem; color:var(--ink-2); margin:4px 0 0; }}
.gm-kv {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 20px; align-content:start; }}
.gm-kv dt {{ color:var(--muted); font-size:.75rem; margin:0; }}
.gm-kv dd {{ color:var(--ink); font-size:1.05rem; font-weight:600; margin:0; }}

.gm-scale {{ display:grid; grid-template-columns:repeat(5,1fr); gap:2px; margin:14px 0 4px; }}
.gm-scale span {{ height:6px; background:var(--surface-2); }}
.gm-scale span:first-child {{ border-radius:3px 0 0 3px; }}
.gm-scale span:last-child {{ border-radius:0 3px 3px 0; }}
.gm-scale span.on {{ background:var(--tone); }}
.gm-scale-labels {{ display:grid; grid-template-columns:repeat(5,1fr); color:var(--muted); font-size:.7rem; }}
.gm-scale-labels b {{ color:var(--ink); font-weight:600; }}

.gm-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin:12px 0; }}
.gm-card {{ background:var(--surface); border:1px solid var(--line); border-radius:8px; padding:14px 16px; min-width:0; }}
.gm-card h4 {{ margin:0 0 2px; padding:0; font-size:.9rem !important; color:var(--ink); font-weight:600; }}
.gm-card p {{ margin:0; color:var(--ink-2); font-size:.85rem; line-height:1.55; }}
.gm-card ul {{ margin:6px 0 0; padding:0; list-style:none; }}
.gm-card li {{ margin:0; padding:6px 0; font-size:.85rem; color:var(--ink-2); border-top:1px solid var(--line); line-height:1.45; }}
.gm-card li:first-child {{ border-top:0; }}
.gm-card li b {{ color:var(--ink); font-weight:500; }}
.gm-card li small {{ color:var(--muted); display:block; font-size:.75rem; }}
.gm-big {{ font-size:1.5rem; font-weight:600; color:var(--ink); }}
.gm-sub {{ color:var(--muted); font-size:.78rem; }}
.gm-bar {{ height:6px; border-radius:3px; background:var(--surface-2); overflow:hidden; margin:8px 0 6px; }}
.gm-bar i {{ display:block; height:100%; background:var(--tone); border-radius:3px; }}

.gm-meter {{ position:relative; height:10px; margin:30px 0 26px; border-radius:5px; overflow:visible; display:flex; }}
.gm-meter .z {{ height:100%; opacity:.28; }}
.gm-meter .z.red {{ background:var(--bear); border-radius:5px 0 0 5px; }}
.gm-meter .z.yel {{ background:var(--flat); }}
.gm-meter .z.grn {{ background:var(--bull); border-radius:0 5px 5px 0; }}
.gm-meter .pin {{ position:absolute; top:-5px; width:3px; height:20px; background:var(--ink); border-radius:2px; transform:translateX(-50%); }}
.gm-meter .val {{ position:absolute; top:-26px; transform:translateX(-50%); font-size:.8rem; font-weight:600; color:var(--ink); white-space:nowrap; }}
.gm-meter .tick {{ position:absolute; top:14px; transform:translateX(-50%); font-size:.7rem; color:var(--muted); }}

.gm-chip {{ display:inline-flex; align-items:center; gap:6px; padding:2px 10px; border-radius:999px;
  background:var(--surface-2); color:var(--ink); font-size:.8rem; white-space:nowrap; }}
.gm-chip i {{ color:var(--tone); font-style:normal; font-size:.7rem; }}
.gm-strip {{ display:flex; flex-wrap:wrap; align-items:center; gap:6px 18px; padding:8px 14px; margin-bottom:12px;
  background:var(--surface); border:1px solid var(--line); border-radius:8px; font-size:.8rem; color:var(--muted); }}
.gm-strip b {{ color:var(--ink); font-weight:600; }}

.gm-pagehead {{ margin:4px 0 12px; }}
.gm-pagehead h1 {{ font-size:1.5rem !important; margin:0 !important; padding:0 !important; }}
.gm-pagehead p {{ margin:2px 0 0; color:var(--ink-2); font-size:.9rem; }}
.gm-brief {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; padding:10px 14px; margin-bottom:12px;
  background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--tone); border-radius:8px;
  color:var(--ink); font-size:.9rem; }}

.gm-alert {{ border-left:3px solid var(--tone); }}
.gm-section {{ margin:20px 0 6px; font-size:1rem; font-weight:600; color:var(--ink); }}
.gm-section small {{ display:block; font-weight:400; color:var(--muted); font-size:.8rem; }}

.gm-table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
.gm-table th {{ text-align:right; color:var(--muted); font-weight:400; padding:4px 8px; border-bottom:1px solid var(--line); }}
.gm-table td {{ text-align:right; padding:6px 8px; color:var(--ink); border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }}
.gm-table th:first-child, .gm-table td:first-child {{ text-align:left; }}

@media (max-width: 760px) {{
  .block-container {{ padding:3rem 1rem 2rem; }}
  .gm-hero {{ grid-template-columns:minmax(0,1fr); padding:16px; }}
  .gm-stance {{ font-size:2rem; }}
}}
@media (forced-colors: active) {{
  .gm-bar i, .gm-scale span.on {{ background:Highlight; }}
}}
</style>"""
