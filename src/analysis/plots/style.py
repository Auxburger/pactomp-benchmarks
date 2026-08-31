"""Shared figure styling.

One place for the palettes, markers, the figure note and the thesis layout, so
the interactive HTML and the exported thesis PDFs cannot drift apart. Every
value here is the one the individual plot modules used before they were
consolidated — changing one changes every figure that uses it.
"""

from __future__ import annotations

import plotly.graph_objects as go

# ── Thesis layout (export_thesis_figs.py, export_scalability_model.py) ───────
THESIS_WIDTH = 900   # px — roughly \linewidth at 96 dpi
THESIS_HEIGHT = 420
AXIS_FONT = 15
LEGEND_FONT = 15
TITLE_FONT = 16

# ── Palettes ─────────────────────────────────────────────────────────────────
# TUM corporate colours, as used by settings.tex in the thesis.
MODE_COLORS = {"dynamic=true": "#0065BD", "dynamic=false": "#E37222"}
MODE_LABELS = {"dynamic=true": "Enabled", "dynamic=false": "Unmanaged"}
MODE_DASHES = {"dynamic=true": "solid", "dynamic=false": "dash"}
MODE_MARKERS = {"dynamic=true": "circle", "dynamic=false": "diamond"}

BENCH_COLORS = {"FT": "#4C72B0", "CG": "#DD8452", "EP": "#55A868"}
BENCHMARK_MARKERS = {"CG": "circle", "EP": "diamond", "FT": "square"}
SLAB_COLORS = ["#1f77b4", "#ff7f0e"]

WORKER_COLORS = {"A1": "#4C72B0", "A2": "#96B5D8", "B1": "#DD8452", "B2": "#EDB899"}
WORKER_LABELS = {
    "A1": "A1 – DRM (first)",
    "A2": "A2 – DRM (joins later)",
    "B1": "B1 – no-DRM (first)",
    "B2": "B2 – no-DRM (joins later)",
}
WORKER_DASH = {"A1": "solid", "A2": "dot", "B1": "solid", "B2": "dot"}
WORKER_MARKERS = {"A1": "circle", "A2": "square", "B1": "diamond", "B2": "cross"}

# ── Ink (export_scalability_model.py) ────────────────────────────────────────
INK_COLOR = "#333333"
MUTED_COLOR = "#808080"
GRID_COLOR = "#E6E6E1"
GRID_LINE_COLOR = "#B8B8B2"
AXIS_COLOR = "#808080"


def add_figure_note(fig: go.Figure, text: str) -> None:
    """Add a small source/description note below the chart area."""
    fig.add_annotation(
        text=text,
        xref="paper", yref="paper",
        x=0.0, y=-0.13,
        showarrow=False,
        font=dict(size=10, color="#666666"),
        align="left",
        xanchor="left",
    )
    current_b = fig.layout.margin.b
    fig.update_layout(margin=dict(b=max(current_b if current_b else 60, 80)))


def apply_thesis_style(fig: go.Figure, w: int = THESIS_WIDTH, h: int = THESIS_HEIGHT) -> go.Figure:
    """Thesis layout: fixed size, legend at the bottom, larger fonts."""
    fig.update_layout(
        width=w,
        height=h,
        margin=dict(l=60, r=20, t=50, b=110),
        font=dict(size=AXIS_FONT),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.22,
            xanchor="center",
            x=0.5,
            font=dict(size=LEGEND_FONT),
        ),
        title=dict(font=dict(size=TITLE_FONT)),
    )
    # Remove the source note margin — it's for the interactive HTML
    for ann in fig.layout.annotations:
        if ann.yref == "paper" and ann.y < 0:
            ann.visible = False
    return fig
