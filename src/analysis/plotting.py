from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .io_utils import add_figure_note

_MODE_MARKERS = {
    "dynamic=true": "circle",
    "dynamic=false": "diamond",
}


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _extract_benchmark_from_hover(hovertemplate: str) -> str | None:
    marker = "benchmark="
    if marker not in hovertemplate:
        return None
    start = hovertemplate.find(marker) + len(marker)
    end = hovertemplate.find("<", start)
    if end == -1:
        end = len(hovertemplate)
    return hovertemplate[start:end]


def _split_trace_name(name: str) -> tuple[str, str] | None:
    if ", " not in name:
        return None
    source, mode = name.split(", ", 1)
    return source, mode


def _make_metric_figure(
    df: pd.DataFrame,
    title: str,
    show_raw_points: bool,
    value_col: str,
    value_label: str,
    value_suffix: str,
    value_tickformat: str,
) -> go.Figure:
    df = df.copy()
    sources = sorted(df["source"].unique())
    base_colors = px.colors.qualitative.Plotly
    color_map = {s: base_colors[i % len(base_colors)] for i, s in enumerate(sources)}
    agg = (
        df.groupby(["source", "mode", "threads"], as_index=False)[value_col]
        .agg(mean="mean", std="std", n="count", min="min", max="max")
        .sort_values(["source", "mode", "threads"])
    )
    agg["std"] = agg["std"].fillna(0.0)
    agg["threads_str"] = agg["threads"].astype(str)
    df["threads_str"] = df["threads"].astype(str)

    fig = px.line(
        agg,
        x="threads_str",
        y="mean",
        color="source",
        line_dash="mode",
        markers=True,
        title=title,
        labels={
            "threads_str": "Threads used",
            "mean": value_label,
            "mode": "Mode",
            "source": "Source",
        },
        color_discrete_map=color_map,
    )

    # Add min/max to hover for line traces
    for trace in fig.data:
        if trace.type != "scatter" or not trace.name or trace.mode is None:
            continue
        if "lines" not in trace.mode:
            continue
        parts = _split_trace_name(trace.name or "")
        if not parts:
            continue
        source, mode = parts
        trace.legendgroup = trace.name
        sub = agg[(agg["source"] == source) & (agg["mode"] == mode)].sort_values("threads")
        if sub.empty:
            continue
        trace.marker.update(
            size=9,
            symbol=_MODE_MARKERS.get(mode, "circle"),
            line=dict(color="white", width=1),
        )
        trace.customdata = list(zip(sub["min"], sub["max"], sub["n"]))
        trace.hovertemplate = (
            f"Source={source}<br>"
            f"Mode={mode}<br>"
            "Threads used=%{x}<br>"
            f"Mean=%{{y:{value_tickformat}}}{value_suffix}<br>"
            f"Min=%{{customdata[0]:{value_tickformat}}}{value_suffix}<br>"
            f"Max=%{{customdata[1]:{value_tickformat}}}{value_suffix}<extra></extra>"
        )

    # Axis formatting: only show actual thread counts; y without SI shortening
    threads_sorted = sorted(df["threads"].unique())
    threads_sorted_str = [str(t) for t in threads_sorted]
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=threads_sorted_str,
    )
    fig.update_yaxes(tickformat=value_tickformat, ticksuffix=value_suffix)
    fig.update_layout(legend_title_text="")

    # Min/Max band
    for (source, mode), sub in agg.groupby(["source", "mode"]):
        sub = sub.sort_values("threads")
        x_vals = sub["threads"].astype(str).tolist()
        y_max = sub["max"].tolist()
        y_min = sub["min"].tolist()
        band_x = x_vals + x_vals[::-1]
        band_y = y_max + y_min[::-1]
        fig.add_trace(
            go.Scatter(
                x=band_x,
                y=band_y,
                fill="toself",
                mode="lines",
                line=dict(width=0),
                fillcolor=_hex_to_rgba(color_map[source], 0.15),
                hoverinfo="skip",
                showlegend=False,
                legendgroup=f"{source}, {mode}",
            )
        )

    # Error bars (std dev)
    for (source, mode), sub in agg.groupby(["source", "mode"]):
        fig.add_trace(
            go.Scatter(
                x=sub["threads"].astype(str),
                y=sub["mean"],
                mode="markers",
                marker=dict(opacity=0),
                showlegend=False,
                error_y=dict(type="data", array=sub["std"], visible=True),
                hovertemplate=(
                    "Source: %{customdata[0]}<br>"
                    "Mode: %{customdata[1]}<br>"
                    "Threads: %{x}<br>"
                    "Mean: %{y:.0f} ms<br>"
                    "Std: %{customdata[2]:.0f} ms<br>"
                    "n: %{customdata[3]}<extra></extra>"
                ),
                customdata=list(zip(sub["source"], sub["mode"], sub["std"], sub["n"])),
            )
        )

    # Optional raw points overlay (replicate points)
    if show_raw_points:
        pts = px.scatter(
            df,
            x="threads_str",
            y=value_col,
            color="source",
            symbol="mode",
            labels={"threads_str": "Threads used", value_col: value_label},
            color_discrete_map=color_map,
        )
        for t in pts.data:
            t.update(showlegend=False, opacity=0.55)
            fig.add_trace(t)

    return fig


def _make_combined_metric_figure(
    df_group: pd.DataFrame,
    group_name: str,
    value_col: str,
    value_label: str,
    value_suffix: str,
    value_tickformat: str,
    title: str,
) -> go.Figure:
    sources = sorted(df_group["source"].unique())
    base_colors = px.colors.qualitative.Plotly
    color_map = {s: base_colors[i % len(base_colors)] for i, s in enumerate(sources)}
    agg_all = (
        df_group.groupby(["benchmark", "source", "mode", "threads"], as_index=False)[value_col]
        .agg(mean="mean", min="min", max="max")
        .sort_values(["benchmark", "source", "mode", "threads"])
    )
    agg_all["threads_str"] = agg_all["threads"].astype(str)

    benchmarks = sorted(agg_all["benchmark"].unique())
    fig_all = px.line(
        agg_all,
        x="threads_str",
        y="mean",
        color="source",
        line_dash="mode",
        facet_col="benchmark",
        facet_col_wrap=3,
        markers=True,
        title=title,
        labels={
            "threads_str": "Threads used",
            "mean": value_label,
            "mode": "Mode",
            "source": "Source",
        },
        color_discrete_map=color_map,
        category_orders={"benchmark": benchmarks},
    )

    threads_sorted = sorted(df_group["threads"].unique())
    fig_all.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=[str(t) for t in threads_sorted],
    )
    fig_all.update_yaxes(tickformat=value_tickformat, ticksuffix=value_suffix)
    fig_all.update_layout(legend_title_text="")

    # Add min/max to hover for combined line traces
    for trace in fig_all.data:
        if trace.type != "scatter" or not trace.name or trace.mode is None:
            continue
        if "lines" not in trace.mode:
            continue
        parts = _split_trace_name(trace.name or "")
        if not parts:
            continue
        source, mode = parts
        bench = _extract_benchmark_from_hover(trace.hovertemplate or "")
        if not bench:
            continue
        trace.legendgroup = trace.name
        sub = agg_all[
            (agg_all["benchmark"] == bench)
            & (agg_all["source"] == source)
            & (agg_all["mode"] == mode)
        ].sort_values("threads")
        if sub.empty:
            continue
        trace.marker.update(
            size=9,
            symbol=_MODE_MARKERS.get(mode, "circle"),
            line=dict(color="white", width=1),
        )
        trace.customdata = list(zip(sub["min"], sub["max"]))
        trace.hovertemplate = (
            f"Source={source}<br>"
            f"Mode={mode}<br>"
            f"benchmark={bench}<br>"
            "Threads used=%{x}<br>"
            f"Mean=%{{y:{value_tickformat}}}{value_suffix}<br>"
            f"Min=%{{customdata[0]:{value_tickformat}}}{value_suffix}<br>"
            f"Max=%{{customdata[1]:{value_tickformat}}}{value_suffix}<extra></extra>"
        )

    # Min/Max band per benchmark facet (map to the correct subplot via hovertemplate)
    bench_axes: dict[str, tuple[str, str]] = {}
    for trace in fig_all.data:
        ht = trace.hovertemplate or ""
        bench = _extract_benchmark_from_hover(ht)
        if bench and bench not in bench_axes:
            bench_axes[bench] = (trace.xaxis, trace.yaxis)

    for bench in benchmarks:
        if bench not in bench_axes:
            continue
        xaxis, yaxis = bench_axes[bench]
        sub_bench = agg_all[agg_all["benchmark"] == bench]
        for (source, mode), sub in sub_bench.groupby(["source", "mode"]):
            sub = sub.sort_values("threads")
            x_vals = sub["threads"].astype(str).tolist()
            y_max = sub["max"].tolist()
            y_min = sub["min"].tolist()
            band_x = x_vals + x_vals[::-1]
            band_y = y_max + y_min[::-1]
            fig_all.add_trace(
                go.Scatter(
                    x=band_x,
                    y=band_y,
                    fill="toself",
                    mode="lines",
                    line=dict(width=0),
                    fillcolor=_hex_to_rgba(color_map[source], 0.15),
                    hoverinfo="skip",
                    showlegend=False,
                    legendgroup=f"{source}, {mode}",
                    xaxis=xaxis,
                    yaxis=yaxis,
                )
            )

    return fig_all


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
