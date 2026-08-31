"""NPB benchmark figures: runtime, MOPS, initialisation time, DRM speedup."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from ._metrics import _make_combined_metric_figure, _make_metric_figure
from .style import MODE_MARKERS as _MODE_MARKERS, add_figure_note

def make_figure(df: pd.DataFrame, title: str, show_raw_points: bool) -> go.Figure:
    fig = _make_metric_figure(
        df,
        title=title,
        show_raw_points=show_raw_points,
        value_col="duration_ms",
        value_label="Time (ms)",
        value_suffix=" ms",
        value_tickformat="d",
    )
    add_figure_note(
        fig,
        "Mean runtime per thread count with ±std-dev error bars and min/max band. "
        "Each run = one complete NPB Class C kernel execution. Source: NPB benchmark output logs.",
    )
    return fig


def make_mops_figure(df: pd.DataFrame, title: str, show_raw_points: bool) -> go.Figure:
    fig = _make_metric_figure(
        df,
        title=title,
        show_raw_points=show_raw_points,
        value_col="mops_total",
        value_label="Mop/s total",
        value_suffix="",
        value_tickformat=".2f",
    )
    add_figure_note(
        fig,
        "Mean Mop/s throughput per thread count (higher = better). "
        "Source: NPB benchmark stdout (Mop/s total field).",
    )
    return fig


def make_init_figure(df: pd.DataFrame, title: str, show_raw_points: bool) -> go.Figure:
    fig = _make_metric_figure(
        df,
        title=title,
        show_raw_points=show_raw_points,
        value_col="init_ms",
        value_label="Initialization time (ms)",
        value_suffix=" ms",
        value_tickformat="d",
    )
    add_figure_note(
        fig,
        "Time spent before the first parallel region (memory initialisation, data setup). "
        "Source: NPB benchmark output logs.",
    )
    return fig


def make_combined_figure(df_group: pd.DataFrame, group_name: str) -> go.Figure:
    fig = _make_combined_metric_figure(
        df_group,
        group_name=group_name,
        value_col="duration_ms",
        value_label="Time (ms)",
        value_suffix=" ms",
        value_tickformat="d",
        title=f"{group_name}: NPB kernels runtime vs threads (mean across all reps/runs)",
    )
    add_figure_note(
        fig,
        "Mean runtime per benchmark and thread count. Solid = dynamic=true (DRM); dashed = dynamic=false (no-DRM). "
        "Band = min/max range across runs. Source: NPB Class C benchmark output logs.",
    )
    return fig


def make_combined_mops_figure(df_group: pd.DataFrame, group_name: str) -> go.Figure:
    fig = _make_combined_metric_figure(
        df_group,
        group_name=group_name,
        value_col="mops_total",
        value_label="Mop/s total",
        value_suffix="",
        value_tickformat=".2f",
        title=f"{group_name}: NPB kernels Mop/s total vs threads (mean across all reps/runs)",
    )
    add_figure_note(
        fig,
        "Mean Mop/s per benchmark and thread count (higher = better). "
        "Source: NPB Class C benchmark stdout (Mop/s total field).",
    )
    return fig


def make_combined_init_figure(df_group: pd.DataFrame, group_name: str) -> go.Figure:
    fig = _make_combined_metric_figure(
        df_group,
        group_name=group_name,
        value_col="init_ms",
        value_label="Initialization time (ms)",
        value_suffix=" ms",
        value_tickformat="d",
        title=f"{group_name}: NPB kernels initialization time vs threads (mean across all reps/runs)",
    )
    add_figure_note(
        fig,
        "Time before the first parallel region per benchmark and thread count. "
        "Source: NPB Class C benchmark output logs.",
    )
    return fig


def make_speedup_figure(df_group: pd.DataFrame, group_name: str) -> go.Figure:
    """DRM speedup ratio (time_dyn_false / time_dyn_true) vs thread count per benchmark.

    Speedup > 1 means DRM wins; < 1 means uncoordinated is faster.
    One line per benchmark; if multiple sources exist, one subplot per source.
    A horizontal reference line at y=1 marks no difference.
    """
    agg = (
        df_group.groupby(["source", "benchmark", "threads", "mode"], as_index=False)["duration_ms"]
        .median()
        .rename(columns={"duration_ms": "median_ms"})
    )

    pivot = agg.pivot_table(
        index=["source", "benchmark", "threads"],
        columns="mode",
        values="median_ms",
    ).reset_index()
    pivot.columns.name = None

    dyn_true_col = "dynamic=true"
    dyn_false_col = "dynamic=false"
    if dyn_true_col not in pivot.columns or dyn_false_col not in pivot.columns:
        fig = go.Figure()
        fig.add_annotation(text="Need both dyn=true and dyn=false data", showarrow=False)
        return fig

    pivot["speedup"] = pivot[dyn_false_col] / pivot[dyn_true_col]
    pivot = pivot.dropna(subset=["speedup"])
    if pivot.empty:
        fig = go.Figure()
        fig.add_annotation(text="No speedup data", showarrow=False)
        return fig

    sources = sorted(pivot["source"].unique())
    benchmarks = sorted(pivot["benchmark"].unique())
    threads_sorted = sorted(pivot["threads"].unique())
    threads_sorted_str = [str(t) for t in threads_sorted]

    bench_colors = {
        b: px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)]
        for i, b in enumerate(benchmarks)
    }

    if len(sources) == 1:
        fig = go.Figure()
        sub_src = pivot[pivot["source"] == sources[0]]

        for bench in benchmarks:
            sub = sub_src[sub_src["benchmark"] == bench].sort_values("threads")
            if sub.empty:
                continue
            fig.add_trace(go.Scatter(
                x=sub["threads"].astype(str),
                y=sub["speedup"],
                mode="lines+markers",
                name=bench,
                line=dict(color=bench_colors[bench], width=2),
                marker=dict(size=8),
                hovertemplate=(
                    f"Benchmark: {bench}<br>"
                    "Threads: %{x}<br>"
                    "Speedup: %{y:.3f}×<extra></extra>"
                ),
            ))

            # Annotate peak (max) value
            peak_row = sub.loc[sub["speedup"].idxmax()]
            fig.add_annotation(
                x=str(int(peak_row["threads"])),
                y=peak_row["speedup"],
                text=f"{peak_row['speedup']:.2f}×",
                showarrow=True,
                arrowhead=2,
                arrowwidth=1,
                ax=0,
                ay=-22,
                font=dict(size=10),
            )

        fig.add_hline(y=1.0, line=dict(color="grey", dash="dash", width=1.5))
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=threads_sorted_str,
            title_text="Thread count (t)",
        )
        fig.update_yaxes(title_text="Speedup (time_no_DRM / time_DRM)")
        fig.update_layout(
            title=f"{group_name}: DRM speedup vs thread count (median across runs)",
            legend=dict(title="Benchmark"),
            hovermode="x unified",
        )
    else:
        # Multiple sources: one subplot per source
        from plotly.subplots import make_subplots

        fig = make_subplots(
            rows=1,
            cols=len(sources),
            subplot_titles=[f"Source: {s}" for s in sources],
            shared_yaxes=True,
        )
        shown_in_legend: set[str] = set()
        for col_idx, src in enumerate(sources, start=1):
            sub_src = pivot[pivot["source"] == src]
            for bench in benchmarks:
                sub = sub_src[sub_src["benchmark"] == bench].sort_values("threads")
                if sub.empty:
                    continue
                show_leg = bench not in shown_in_legend
                if show_leg:
                    shown_in_legend.add(bench)
                fig.add_trace(
                    go.Scatter(
                        x=sub["threads"].astype(str),
                        y=sub["speedup"],
                        mode="lines+markers",
                        name=bench,
                        line=dict(color=bench_colors[bench], width=2),
                        marker=dict(size=8),
                        showlegend=show_leg,
                        legendgroup=bench,
                        hovertemplate=(
                            f"Benchmark: {bench}<br>"
                            "Threads: %{x}<br>"
                            "Speedup: %{y:.3f}×<extra></extra>"
                        ),
                    ),
                    row=1,
                    col=col_idx,
                )
            fig.add_hline(y=1.0, line=dict(color="grey", dash="dash", width=1.5), row=1, col=col_idx)
            fig.update_xaxes(
                type="category",
                categoryorder="array",
                categoryarray=threads_sorted_str,
                title_text="Thread count (t)",
                row=1,
                col=col_idx,
            )

        fig.update_yaxes(title_text="Speedup (×)", col=1)
        fig.update_layout(
            title=f"{group_name}: DRM speedup vs thread count",
            legend=dict(title="Benchmark"),
            hovermode="x unified",
        )

    add_figure_note(
        fig,
        "Speedup = median runtime(dynamic=false) / median runtime(dynamic=true). "
        ">1 means DRM is faster; dashed line at 1.0 = no difference. "
        "Source: NPB Class C benchmark output logs.",
    )
    return fig
