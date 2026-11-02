"""Chart builders and the point-reduction step that keeps pages responsive."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from macro_index import REGIME_GREEN_PCT, REGIME_RED_PCT
from ui.theme import TOKENS

MAX_POINTS = 900  # per trace; beyond this a browser draws slower, not better


def decimate_indices(values: np.ndarray, max_points: int = MAX_POINTS) -> np.ndarray:
    """Indices to keep: each bucket's min and max, so spikes survive.

    The first and last two points are always kept so the visible latest value and
    its delta stay exact.
    """
    n = len(values)
    if n <= max_points:
        return np.arange(n)
    step = math.ceil(n * 2 / max_points)
    keep = {0, n - 2, n - 1}
    for start in range(0, n, step):
        chunk = values[start:start + step]
        if chunk.size == 0 or np.isnan(chunk).all():
            continue
        keep.add(start + int(np.nanargmin(chunk)))
        keep.add(start + int(np.nanargmax(chunk)))
    return np.fromiter(sorted(keep), dtype=int)


def decimate_figure(fig: go.Figure, max_points: int = MAX_POINTS) -> go.Figure:
    """Thin out dense line traces in place. A 15-year daily series is ~3,900 points;
    a chart cannot show more than its pixel width, but every point costs JSON
    serialisation, a websocket transfer and an SVG path in the browser."""
    for trace in fig.data:
        if trace.type != "scatter" or trace.y is None or trace.x is None:
            continue
        y = np.asarray(trace.y, dtype=float) if not isinstance(trace.y, np.ndarray) else trace.y
        if len(y) <= max_points or y.dtype.kind not in "fiu":
            continue
        idx = decimate_indices(y.astype(float), max_points)
        updates = {"x": np.asarray(trace.x)[idx], "y": y[idx]}
        if trace.customdata is not None:
            updates["customdata"] = np.asarray(trace.customdata)[idx]
        if isinstance(trace.text, (list, tuple, np.ndarray)):
            updates["text"] = np.asarray(trace.text)[idx]
        trace.update(updates)
    return fig


def diffusion_chart(history: pd.DataFrame, height: int = 300) -> go.Figure | None:
    """Diffusion over time with the regime zones as a backdrop."""
    if history is None or history.empty:
        return None
    fig = go.Figure()
    fig.add_hrect(y0=REGIME_GREEN_PCT, y1=100, fillcolor=TOKENS["bull"], opacity=0.07, line_width=0)
    fig.add_hrect(y0=0, y1=REGIME_RED_PCT, fillcolor=TOKENS["bear"], opacity=0.07, line_width=0)
    fig.add_trace(go.Scatter(
        x=history["date"], y=history["diffusion"], mode="lines", name="擴散比例",
        line=dict(color=TOKENS["accent"], width=2),
        hovertemplate="%{x|%Y-%m} · 擴散 %{y:.0f}%<extra></extra>",
    ))
    last = history.iloc[-1]
    fig.add_trace(go.Scatter(
        x=[last["date"]], y=[last["diffusion"]], mode="markers+text",
        marker=dict(size=9, color=TOKENS["accent"], line=dict(width=2, color=TOKENS["surface"])),
        text=[f"{last['diffusion']:.0f}%"], textposition="top left",
        textfont=dict(color=TOKENS["ink"], size=12), hoverinfo="skip", showlegend=False,
    ))
    fig.update_layout(
        title="景氣擴散比例", height=height, showlegend=False, hovermode="closest",
        yaxis=dict(range=[0, 105], ticksuffix="%", tickvals=[0, REGIME_RED_PCT, REGIME_GREEN_PCT, 100]),
    )
    return fig


def clock_chart(clock: dict | None, height: int = 300) -> go.Figure | None:
    """Trail through the growth × inflation quadrants over the last year."""
    if not clock or clock["trail"].empty:
        return None
    trail = clock["trail"]
    limit = max(1.5, float(trail[["growth", "inflation"]].abs().max().max()) * 1.2)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trail["growth"], y=trail["inflation"], mode="lines+markers",
        line=dict(color=TOKENS["accent"], width=2),
        marker=dict(size=6, color=TOKENS["accent"], line=dict(width=1, color=TOKENS["surface"])),
        customdata=trail["date"].dt.strftime("%Y-%m"),
        hovertemplate="%{customdata}<br>成長動能 %{x:+.2f}σ · 通膨動能 %{y:+.2f}σ<extra></extra>",
    ))
    last = trail.iloc[-1]
    fig.add_trace(go.Scatter(
        x=[last["growth"]], y=[last["inflation"]], mode="markers+text",
        marker=dict(size=11, color=TOKENS["ink"], line=dict(width=2, color=TOKENS["surface"])),
        text=["最新"], textposition="top center", textfont=dict(color=TOKENS["ink"], size=12),
        hoverinfo="skip",
    ))
    for x, y, label in ((1, -1, "復甦"), (1, 1, "過熱"), (-1, 1, "停滯性通膨"), (-1, -1, "衰退式降溫")):
        fig.add_annotation(x=x * limit * 0.98, y=y * limit * 0.94, text=label, showarrow=False,
                           xanchor="right" if x > 0 else "left",
                           font=dict(color=TOKENS["muted"], size=11))
    fig.add_hline(y=0, line_color=TOKENS["axis"], line_width=1)
    fig.add_vline(x=0, line_color=TOKENS["axis"], line_width=1)
    fig.update_layout(
        title="成長／通膨動能（近 12 個月軌跡）", height=height, showlegend=False,
        hovermode="closest", margin=dict(t=48, b=44, l=14, r=14),
        xaxis=dict(range=[-limit, limit], title="成長動能（標準差）", showgrid=False, showline=False),
        yaxis=dict(range=[-limit, limit], title="通膨動能（標準差）", showgrid=False),
    )
    return fig
