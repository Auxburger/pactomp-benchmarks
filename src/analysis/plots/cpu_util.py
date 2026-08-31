from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .style import BENCH_COLORS, PARTITION_COLORS, PARTITION_LABELS


def _cpu_ranges(cpus: list[int]) -> list[tuple[int, int]]:
    """Group a sorted list of CPU ids into contiguous ranges."""
    if not cpus:
        return []
    ranges: list[tuple[int, int]] = []
    lo = hi = cpus[0]
    for c in cpus[1:]:
        if c == hi + 1:
            hi = c
        else:
            ranges.append((lo, hi))
            lo = hi = c
    ranges.append((lo, hi))
    return ranges


def _split_domains(df: pd.DataFrame, max_domains: int = 2) -> list[tuple[str, pd.DataFrame]]:
    """Split active CPUs into contiguous domains, keeping the top-N by total utilisation.

    Limits to max_domains subplots so the figure stays readable even when many
    stray system CPUs appear in the data.
    """
    cpus = sorted(df["cpu"].unique())
    ranges = _cpu_ranges(cpus)

    # Score each range by total usr time (sum across all rows in that range)
    scored = []
    for lo, hi in ranges:
        sub = df[df["cpu"].between(lo, hi)]
        scored.append((sub["pct_usr"].sum(), lo, hi, sub))
    scored.sort(key=lambda x: -x[0])

    labels = [chr(ord("A") + i) for i in range(max_domains)]
    domains = []
    for label, (_, lo, hi, sub) in zip(labels, scored[:max_domains]):
        domains.append((f"{label}-domain (CPUs {lo}–{hi})", sub.copy()))
    # Sort by lo-CPU so A-domain (lower physical CPUs) comes first
    domains.sort(key=lambda lsd: lsd[1]["cpu"].min())
    return domains


def make_cpu_util_heatmap(df: pd.DataFrame, title: str | None = None) -> go.Figure:
    """Heatmap of per-CPU %usr utilisation over time.

    Active CPUs are auto-detected and split into contiguous domains (A, B …).
    Each domain gets its own subplot row so the two NUMA domains are easy to
    compare.  Color = %usr (0–100), white = idle, red = fully loaded.
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    domains = _split_domains(df)
    n = len(domains)

    fig = make_subplots(
        rows=n, cols=1,
        shared_xaxes=True,
        subplot_titles=[label for label, _ in domains],
        vertical_spacing=0.08,
    )

    colorscale = [
        [0.0,  "white"],
        [0.5,  "#f4a460"],
        [1.0,  "#8b0000"],
    ]

    for row_idx, (label, sub) in enumerate(domains, start=1):
        cpus = sorted(sub["cpu"].unique())
        times = sorted(sub["elapsed_sec"].unique())

        # Build z matrix: rows = CPUs (low → high), cols = timestamps
        z = np.full((len(cpus), len(times)), np.nan)
        cpu_idx = {c: i for i, c in enumerate(cpus)}
        time_idx = {t: i for i, t in enumerate(times)}
        for _, row in sub.iterrows():
            z[cpu_idx[row["cpu"]], time_idx[row["elapsed_sec"]]] = row["pct_usr"]

        fig.add_trace(
            go.Heatmap(
                x=times,
                y=cpus,
                z=z,
                zmin=0, zmax=100,
                colorscale=colorscale,
                colorbar=dict(
                    title="%usr",
                    len=1 / n,
                    y=1 - (row_idx - 0.5) / n,
                    yanchor="middle",
                ) if row_idx == 1 else dict(showticklabels=False, len=0),
                showscale=(row_idx == 1),
                hovertemplate=(
                    "CPU: %{y}<br>"
                    "Time: %{x:.0f} s<br>"
                    "%usr: %{z:.1f}%<extra></extra>"
                ),
            ),
            row=row_idx, col=1,
        )
        fig.update_yaxes(title_text="CPU core", row=row_idx, col=1,
                         tickmode="linear", dtick=max(1, len(cpus) // 8))

    fig.update_xaxes(title_text="Elapsed time (s)", row=n, col=1)
    fig.update_layout(
        title=title or "CPU Utilisation Over Time (%usr per core)",
        height=280 * n + 80,
    )
    return fig


def _cpu_partitions(splits: "dict[int, dict[str, list[int]]]") -> "dict[int, str]":
    """CPU → partition, taking the assignment from the largest thread count that covers it."""
    partition: "dict[int, str]" = {}
    seen_at: "dict[int, int]" = {}
    for threads, pools in splits.items():
        for part, cpus in pools.items():
            for cpu in cpus:
                if cpu not in seen_at or threads > seen_at[cpu]:
                    seen_at[cpu] = threads
                    partition[cpu] = part
    return partition


def _benchmark_timeline(events: list[dict], t0) -> list[go.Scatter]:
    """One trace per kernel: a tick per benchmark start, hover naming t and r.

    The old matplotlib version drew a full-height line per event; with several
    hundred starts that buried the heatmap. Here the starts are their own slim
    row, and the shared x-axis spike line does the visual alignment instead.
    """
    by_alg: dict[str, list[dict]] = {}
    for ev in events:
        if ev.get("event") == "alg_start" and ev.get("alg"):
            by_alg.setdefault(ev["alg"].upper(), []).append(ev)

    traces = []
    for alg, alg_events in sorted(by_alg.items()):
        xs = [(ev["ts"] - t0).total_seconds() for ev in alg_events]
        labels = [f"{alg} · t={ev['t']} · r={ev['r']}" for ev in alg_events]
        traces.append(
            go.Scatter(
                x=xs,
                y=[alg] * len(xs),
                mode="markers",
                marker=dict(symbol="line-ns", size=11, line=dict(width=1.5, color=BENCH_COLORS.get(alg, "#888888"))),
                name=alg,
                legendgroup=alg,
                hovertext=labels,
                hoverinfo="text",
            )
        )
    return traces


def make_cpu_util_annotated_figure(
    df_cpu: pd.DataFrame,
    df_pidstat: pd.DataFrame | None = None,
    events: list[dict] | None = None,
    splits: dict[int, dict[str, list[int]]] | None = None,
    title: str | None = None,
) -> go.Figure:
    """Per-CPU utilisation over time, annotated with process placement and benchmarks.

    Row 1 is the %usr heatmap over every CPU in the log, row 2 (when a pidstat
    frame is given) shows where the benchmark threads actually ran, and row 3
    marks each benchmark start. Hovering shows a spike line across all rows, so
    a utilisation feature can be traced to the kernel that caused it. CPUs are
    coloured by worker partition when the SLURM log supplied the CPU splits.
    """
    if df_cpu.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    splits = splits or {}
    events = events or []
    cpu_partition = _cpu_partitions(splits)

    t0 = df_cpu["ts"].min()
    df_cpu = df_cpu.assign(sec=(df_cpu["ts"] - t0).dt.total_seconds())
    pivot = df_cpu.pivot_table(index="cpu", columns="sec", values="pct_usr", aggfunc="mean")
    cpu_order = sorted(pivot.index)
    pivot = pivot.loc[cpu_order]
    cpu_to_row = {cpu: i for i, cpu in enumerate(cpu_order)}
    xmin, xmax = float(pivot.columns.min()), float(pivot.columns.max())

    timeline = _benchmark_timeline(events, t0)
    has_placement = df_pidstat is not None and not df_pidstat.empty

    titles = ["Per-CPU utilisation (mpstat)"]
    heights = [1.0]
    if has_placement and timeline:
        titles += ["Thread placement (pidstat)", "Benchmark starts"]
        heights = [0.60, 0.28, 0.12]
    elif has_placement:
        titles += ["Thread placement (pidstat)"]
        heights = [0.70, 0.30]
    elif timeline:
        titles += ["Benchmark starts"]
        heights = [0.85, 0.15]

    rows = len(titles)
    placement_row = 2 if has_placement else None
    timeline_row = rows if timeline else None

    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        row_heights=heights, vertical_spacing=0.05, subplot_titles=titles,
    )

    fig.add_trace(
        go.Heatmap(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(range(len(cpu_order))),
            colorscale="Hot",
            reversescale=True,
            zmin=0, zmax=100,
            colorbar=dict(title="%usr", len=0.45, y=1.0, yanchor="top", thickness=12),
            hovertemplate="t=%{x:.0f}s<br>CPU %{customdata}<br>%usr=%{z:.1f}<extra></extra>",
            customdata=[[cpu] * len(pivot.columns) for cpu in cpu_order],
            showscale=True,
        ),
        row=1, col=1,
    )

    if placement_row:
        df_p = df_pidstat.assign(sec=(df_pidstat["ts"] - t0).dt.total_seconds())
        df_p = df_p[(df_p["sec"] >= xmin) & (df_p["sec"] <= xmax)].copy()
        df_p["row"] = df_p["cpu"].map(cpu_to_row)
        df_p = df_p.dropna(subset=["row"])
        colors = df_p["cpu"].map(cpu_partition).map(PARTITION_COLORS).fillna("#6E6E6E")
        fig.add_trace(
            go.Scattergl(
                x=df_p["sec"], y=df_p["row"],
                mode="markers",
                marker=dict(size=3, color=list(colors), opacity=0.5),
                name="thread placement",
                showlegend=False,
                hovertext=[f"CPU {c} · {cmd}" for c, cmd in zip(df_p["cpu"], df_p["command"])],
                hoverinfo="text",
            ),
            row=placement_row, col=1,
        )

    if timeline_row:
        for trace in timeline:
            fig.add_trace(trace, row=timeline_row, col=1)

    # Partition dividers, plus one legend entry per partition present.
    previous = None
    for i, cpu in enumerate(cpu_order):
        part = cpu_partition.get(cpu)
        if part != previous and previous is not None:
            for row in [r for r in (1, placement_row) if r]:
                fig.add_hline(
                    y=i - 0.5, row=row, col=1,
                    line=dict(color="rgba(120,120,120,0.8)", width=1, dash="dot"),
                )
        previous = part
    for part in sorted(set(cpu_partition.values())):
        fig.add_trace(
            go.Scatter(
                x=[None], y=[None], mode="markers",
                marker=dict(size=8, color=PARTITION_COLORS[part]),
                name=PARTITION_LABELS[part],
            ),
            row=1, col=1,
        )

    for row, every in ((1, 10), (placement_row, 6)):
        if not row:
            continue
        step = max(1, len(cpu_order) // every)
        tickvals = list(range(0, len(cpu_order), step))
        fig.update_yaxes(
            tickmode="array", tickvals=tickvals,
            ticktext=[str(cpu_order[i]) for i in tickvals],
            title_text="CPU core #",
            range=[-0.5, len(cpu_order) - 0.5],
            row=row, col=1,
        )
    if timeline_row:
        fig.update_yaxes(title_text="", showgrid=False, row=timeline_row, col=1)

    fig.update_xaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikecolor="#888888", spikedash="dot",
    )
    fig.update_xaxes(title_text="Time since job start (s)", row=rows, col=1)
    fig.update_layout(
        title=title or "Per-CPU utilisation and process placement during the NPB run",
        height=1000,
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0),
    )
    return fig
