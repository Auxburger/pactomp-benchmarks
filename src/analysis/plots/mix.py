"""Mixed workload figure: the seeded schedule as it actually ran, per arm."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from ..datasets.mix import ARM_LABELS
from .style import BENCH_COLORS, GRID_LINE_COLOR, MUTED_COLOR

WINDOW_COLOR = "#CFCFC6"
WINDOW_HEIGHT = 0.82
BAR_HEIGHT = 0.5

# Colour alone does not separate three kernels for a red-green colour blind
# reader, so every kernel also carries its own hatch. Plotly anchors a pattern
# to the panel rather than to the bar, so a tiled shape like "x" is cut at a
# different phase in every lane — opposed diagonals tile without a seam.
ALGORITHM_PATTERNS = {"cg": "/", "ep": "\\", "ft": "-"}
# Horizontal lines need a finer tile than the diagonals to read as a hatch
# rather than as a single split through the bar.
PATTERN_SIZES = {"ft": 3}
PATTERN_SIZE = 8


def _lane_label(label: str) -> str:
    """`J04_cg` reads as a filename; the axis wants `J04 CG`."""
    job, _, algorithm = label.partition("_")
    return f"{job}&nbsp;&nbsp;{algorithm.upper()}"


def _algorithm_color(algorithm: str) -> str:
    return BENCH_COLORS.get(algorithm.upper(), MUTED_COLOR)


def make_mix_timeline_figure(
    df: pd.DataFrame,
    df_schedule: pd.DataFrame,
    repeat: int = 1,
    arms: tuple[str, ...] = ("drm", "nodrm"),
    title: str | None = None,
) -> go.Figure:
    """One Gantt lane per job and arm, over the window the schedule gave it.

    The pale bar is the window; every filled bar is one completed benchmark
    process. A bar reaching past its pale bar is the last iteration of that
    job, which the driver lets finish beyond the deadline.
    """
    labels = list(df_schedule["label"])
    lane_of = {label: index for index, label in enumerate(labels)}

    figure = make_subplots(
        rows=len(arms),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.16,
        subplot_titles=[ARM_LABELS.get(arm, arm) for arm in arms],
    )

    seen_algorithms: set[str] = set()
    window_in_legend = False

    for index, arm in enumerate(arms):
        row = index + 1
        arm_df = df[(df["arm"] == arm) & (df["repeat"] == repeat)]

        for _, job in df_schedule.iterrows():
            figure.add_trace(
                go.Bar(
                    x=[job["duration"]],
                    y=[lane_of[job["label"]]],
                    base=[job["start_offset"]],
                    orientation="h",
                    width=WINDOW_HEIGHT,
                    marker=dict(
                        color=WINDOW_COLOR,
                        line=dict(color=GRID_LINE_COLOR, width=1),
                    ),
                    name="Scheduled window",
                    legendgroup="window",
                    showlegend=not window_in_legend,
                    hovertemplate=(
                        f"{job['label']} window<br>"
                        f"{job['start_offset']:.1f}–{job['window_end']:.1f}s<extra></extra>"
                    ),
                ),
                row=row,
                col=1,
            )
            window_in_legend = True

        for algorithm in sorted(arm_df["algorithm"].unique()):
            sub = arm_df[arm_df["algorithm"] == algorithm]
            figure.add_trace(
                go.Bar(
                    x=(sub["end_sec"] - sub["start_sec"]).tolist(),
                    y=[lane_of[label] for label in sub["label"]],
                    base=sub["start_sec"].tolist(),
                    orientation="h",
                    width=BAR_HEIGHT,
                    name=algorithm.upper(),
                    legendgroup=algorithm,
                    showlegend=algorithm not in seen_algorithms,
                    marker=dict(
                        color=_algorithm_color(algorithm),
                        pattern=dict(
                            shape=ALGORITHM_PATTERNS.get(algorithm, ""),
                            fgcolor="white",
                            size=PATTERN_SIZES.get(algorithm, PATTERN_SIZE),
                            solidity=0.28,
                        ),
                    ),
                    customdata=sub[["label", "iteration", "total_threads"]].values,
                    hovertemplate=(
                        "%{customdata[0]} iteration %{customdata[1]}<br>"
                        "start %{base:.1f}s, %{x:.1f}s wall<br>"
                        "%{customdata[2]} threads<extra></extra>"
                    ),
                ),
                row=row,
                col=1,
            )
            seen_algorithms.add(algorithm)

        figure.update_yaxes(
            row=row,
            col=1,
            tickmode="array",
            tickvals=list(range(len(labels))),
            ticktext=[_lane_label(label) for label in labels],
            # Explicit range rather than autorange: Plotly pads a bar axis by a
            # fraction of the bar width, which left a lane and a half of empty
            # space under the last job.
            range=[len(labels) - 0.4, -0.6],
        )

    figure.update_xaxes(row=len(arms), col=1, title_text="Elapsed time (s)")
    figure.update_layout(
        barmode="overlay",
        bargap=0.25,
        title=title,
    )
    return figure
