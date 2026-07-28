"""Fit and export the configuration-level Amdahl--Karp--Flatt model."""

from __future__ import annotations

import csv
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from plots.scalability_model import KERNELS, MODES, fit_all, load_dual_observations


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data" / "dual"

# See export_thesis_figs.py: THESIS_FIGURES_DIR redirects output into the
# thesis repo's figures/ directory, which no longer sits alongside this one.
FIGURE_DIR = Path(os.environ.get("THESIS_FIGURES_DIR", REPO_ROOT / "figures")).resolve()
FIGURE_PATH = FIGURE_DIR / "amdahl_karp_flatt_capacity.pdf"
OUTPUT_DIR = Path(__file__).resolve().parent / "plots" / "model"
SUMMARY_PATH = OUTPUT_DIR / "amdahl_karp_flatt_summary.csv"
POINTS_PATH = OUTPUT_DIR / "amdahl_karp_flatt_points.csv"

# Thesis figure styling, matching export_thesis_figs.py.
FIGURE_WIDTH = 900
FIGURE_HEIGHT = 420
AXIS_FONT = 13
LEGEND_FONT = 13
TITLE_FONT = 14

# TUM corporate colours, as used by settings.tex. The pair passes the
# categorical colour checks for normal vision and for all three CVD types;
# the solid/dashed line styles add a second, colour-independent encoding.
MODE_COLORS = {"dynamic=true": "#0065BD", "dynamic=false": "#E37222"}
MODE_LABELS = {"dynamic=true": "Enabled", "dynamic=false": "Unmanaged"}
MODE_DASHES = {"dynamic=true": "solid", "dynamic=false": "dash"}

INK_COLOR = "#333333"
MUTED_COLOR = "#808080"
GRID_COLOR = "#E6E6E1"
GRID_LINE_COLOR = "#B8B8B2"
AXIS_COLOR = "#808080"

MIN_MULTIPLIER = 1.0
MAX_MULTIPLIER = 16.0


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_model_pdf(path: Path, fits, points) -> None:
    """Render the three-kernel model figure with the shared Plotly pipeline."""
    figure = make_subplots(
        rows=1,
        cols=len(KERNELS),
        shared_yaxes=True,
        subplot_titles=KERNELS,
        horizontal_spacing=0.045,
    )

    # The fitted capacity P / (1 + f (P - 1)) is continuous in P, so the model
    # is drawn as a smooth curve rather than a point-to-point line.
    curve_x = [
        MIN_MULTIPLIER * (MAX_MULTIPLIER / MIN_MULTIPLIER) ** (step / 120.0)
        for step in range(121)
    ]

    for column, kernel in enumerate(KERNELS, start=1):
        # Linear scaling (f = 0). The vertical distance between this line and a
        # fitted curve is the scaling loss the parameter summarises.
        figure.add_trace(
            go.Scatter(
                x=curve_x,
                y=curve_x,
                mode="lines",
                name="Ideal (f = 0)",
                legendgroup="ideal",
                showlegend=column == 1,
                line=dict(color=GRID_LINE_COLOR, width=1.5, dash="dot"),
                hoverinfo="skip",
            ),
            row=1,
            col=column,
        )

        for mode in MODES:
            selected = sorted(
                (
                    point
                    for point in points
                    if point["kernel"] == kernel and point["mode"] == mode
                ),
                key=lambda point: float(point["pool_multiplier"]),
            )
            fit = next(
                candidate
                for candidate in fits
                if candidate.kernel == kernel and candidate.mode == mode
            )
            label = MODE_LABELS[mode]
            color = MODE_COLORS[mode]

            figure.add_trace(
                go.Scatter(
                    x=curve_x,
                    y=[
                        multiplier
                        / (1.0 + fit.effective_fraction * (multiplier - 1.0))
                        for multiplier in curve_x
                    ],
                    mode="lines",
                    name=label,
                    legendgroup=mode,
                    showlegend=column == 1,
                    line=dict(color=color, width=2, dash=MODE_DASHES[mode]),
                    hovertemplate=f"{label} model<br>P=%{{x:.2f}}<br>capacity=%{{y:.2f}}<extra></extra>",
                ),
                row=1,
                col=column,
            )
            figure.add_trace(
                go.Scatter(
                    x=[float(point["pool_multiplier"]) for point in selected],
                    y=[float(point["capacity"]) for point in selected],
                    mode="markers",
                    name=label,
                    legendgroup=mode,
                    showlegend=False,
                    marker=dict(
                        color=color,
                        size=9,
                        symbol="square",
                        line=dict(color="white", width=1),
                    ),
                    hovertemplate=f"{label} observed<br>t=%{{customdata}}<br>capacity=%{{y:.2f}}<extra></extra>",
                    customdata=[point["threads"] for point in selected],
                ),
                row=1,
                col=column,
            )

            # Naming the condition inside the annotation keeps identity readable
            # without relying on colour alone.
            figure.add_annotation(
                row=1,
                col=column,
                xref=f"x{'' if column == 1 else column} domain",
                yref=f"y{'' if column == 1 else column} domain",
                x=0.04,
                y=1.0 if mode == MODES[0] else 0.90,
                xanchor="left",
                yanchor="top",
                showarrow=False,
                text=f"{label} f = {100.0 * fit.effective_fraction:.2f}%",
                font=dict(size=11, color=color),
            )

        figure.update_xaxes(
            row=1,
            col=column,
            type="log",
            tickmode="array",
            tickvals=[1, 2, 4, 8, 16],
            ticktext=["1", "2", "4", "8", "16"],
            title_text="Pool multiplier P = t/2",
            title_font=dict(size=AXIS_FONT),
            range=[math.log10(0.9), math.log10(18.0)],
            showgrid=True,
            gridcolor=GRID_COLOR,
            zeroline=False,
            linecolor=AXIS_COLOR,
            ticks="outside",
            tickcolor=AXIS_COLOR,
        )
        figure.update_yaxes(
            row=1,
            col=column,
            range=[0, 16.5],
            tickvals=[0, 4, 8, 12, 16],
            title_text="Relative capacity" if column == 1 else None,
            title_font=dict(size=AXIS_FONT),
            showgrid=True,
            gridcolor=GRID_COLOR,
            zeroline=False,
            linecolor=AXIS_COLOR,
            ticks="outside",
            tickcolor=AXIS_COLOR,
        )

    figure.update_layout(
        width=FIGURE_WIDTH,
        height=FIGURE_HEIGHT,
        template="plotly_white",
        font=dict(size=AXIS_FONT, color=INK_COLOR),
        margin=dict(l=70, r=20, t=40, b=110),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.24,
            xanchor="center",
            x=0.5,
            font=dict(size=LEGEND_FONT),
        ),
    )
    figure.add_annotation(
        xref="paper",
        yref="paper",
        x=0.5,
        y=-0.38,
        xanchor="center",
        showarrow=False,
        text="Squares: observations. Lines: fitted Amdahl configuration model.",
        font=dict(size=11, color=MUTED_COLOR),
    )
    for annotation in figure.layout.annotations:
        if annotation.text in KERNELS:
            annotation.font = dict(size=TITLE_FONT, color=INK_COLOR)

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_image(str(path))


observations = load_dual_observations(DATA_ROOT)
fits, points = fit_all(observations)

summary_rows = [
    {
        "kernel": fit.kernel,
        "mode": fit.mode,
        "effective_fraction": fit.effective_fraction,
        "bootstrap_95_low": fit.ci_low,
        "bootstrap_95_high": fit.ci_high,
        "rmse_seconds": fit.rmse_seconds,
        "nrmse_percent": fit.nrmse_percent,
        "holdout_prediction_seconds": fit.holdout_prediction_seconds,
        "holdout_observed_seconds": fit.holdout_observed_seconds,
        "holdout_error_percent": fit.holdout_error_percent,
    }
    for fit in fits
]
_write_csv(SUMMARY_PATH, summary_rows)
_write_csv(POINTS_PATH, points)
_write_model_pdf(FIGURE_PATH, fits, points)

print(f"Loaded {len(observations)} process outcomes")
print(f"Wrote {SUMMARY_PATH}")
print(f"Wrote {POINTS_PATH}")
print(f"Wrote {FIGURE_PATH}")
