from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..datasets.drm import compute_inter_grant_times
from .style import BENCH_COLORS as _BENCH_COLORS, SLAB_COLORS as _SLAB_COLORS, add_figure_note


def _band_color(hex_color: str, band: int) -> str:
    """Return a lighter shade of hex_color for band 1, unchanged for band 0."""
    if band == 0:
        return hex_color
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    factor = 0.55  # blend 55% toward white
    r2 = int(r + (255 - r) * factor)
    g2 = int(g + (255 - g) * factor)
    b2 = int(b + (255 - b) * factor)
    return f"#{r2:02x}{g2:02x}{b2:02x}"


# ── Plot 1: Thread-grant distribution (allocation duration proxy) ──────────────

def make_drm_allocation_figure(df_rm: pd.DataFrame, title: str | None = None) -> go.Figure:
    """Violin plot of threads_granted per DRM capacity level.

    Shows the fair-share behaviour: the first request per session gets all N
    threads (monopoly), every subsequent request gets N/2 (steady-state).
    Higher capacity → larger steady-state allocation per process.
    """
    if df_rm.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    capacities = sorted(df_rm["capacity"].unique())
    cap_labels = [str(c) for c in capacities]

    fig = go.Figure()

    for cap in capacities:
        sub = df_rm[df_rm["capacity"] == cap]["threads_granted"]
        fig.add_trace(
            go.Violin(
                x=[str(cap)] * len(sub),
                y=sub,
                name=f"{cap} threads",
                box_visible=True,
                meanline_visible=True,
                points="outliers",
                hovertemplate=(
                    f"Capacity: {cap}<br>"
                    "Threads granted: %{y}<extra></extra>"
                ),
                legendgroup=str(cap),
            )
        )

    # Overlay the expected fair-share line (capacity/2)
    fig.add_trace(
        go.Scatter(
            x=cap_labels,
            y=[c // 2 for c in capacities],
            mode="lines+markers",
            name="Fair-share (N/2)",
            line=dict(color="red", dash="dash", width=2),
            marker=dict(size=8, symbol="diamond"),
            hovertemplate="Capacity: %{x}<br>Fair-share target: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        title=title or "DRM: Thread Grants per Request (allocation duration proxy)",
        xaxis=dict(
            title="DRM capacity (total threads in pool)",
            categoryorder="array",
            categoryarray=cap_labels,
        ),
        yaxis=dict(title="Threads granted"),
        violinmode="overlay",
        legend_title_text="",
        showlegend=True,
    )
    add_figure_note(
        fig,
        "Each point is one DRM grant event. First request per session receives the full pool (monopoly); "
        "subsequent requests receive N/2 (fair-share). Source: rm.log.",
    )
    return fig


# ── Plot 2: CPU slab assignment (precise CPU allocation) ─────────────────────

def make_drm_cpu_assignment_figure(df_rm: pd.DataFrame, title: str | None = None) -> go.Figure:
    """Horizontal bar chart showing exact CPU slab assignments per capacity level.

    For each capacity the DRM partitions the CPU pool into two disjoint slabs –
    one per competing process.  The chart displays both slabs as stacked
    horizontal bars per capacity row, making the partitioning immediately
    visible.
    """
    if df_rm.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    # Keep only steady-state fair-share grants with a real CPU slab assigned.
    # Excludes: monopoly grants (threads == capacity), zero CPU-count grants
    # (CPUs 0+0, meaning no CPU pinning), and zero-thread grants.
    steady = df_rm[
        (df_rm["threads_granted"] > 0)
        & (df_rm["cpu_count"] > 0)
        & (df_rm["threads_granted"] == df_rm["capacity"] // 2)
    ].copy()
    slab_rows = (
        steady.drop_duplicates(subset=["capacity", "cpu_start", "cpu_count"])
        .sort_values(["capacity", "cpu_start"])
        .reset_index(drop=True)
    )

    capacities = sorted(slab_rows["capacity"].unique())

    fig = go.Figure()

    shown_legends: set[str] = set()
    for cap in capacities:
        sub = slab_rows[slab_rows["capacity"] == cap].reset_index(drop=True)
        for rank, (_, row) in enumerate(sub.iterrows()):
            lo = row["cpu_start"]
            count = row["cpu_count"]
            hi = lo + count - 1
            slab_name = f"Slab {rank + 1}"
            color = _SLAB_COLORS[rank % len(_SLAB_COLORS)]
            show = slab_name not in shown_legends
            if show:
                shown_legends.add(slab_name)
            fig.add_trace(
                go.Bar(
                    y=[str(cap)],
                    x=[count],
                    base=[lo - 1],  # base is 0-indexed so bar starts at `lo`
                    orientation="h",
                    name=slab_name,
                    marker_color=color,
                    legendgroup=slab_name,
                    showlegend=show,
                    hovertemplate=(
                        f"Capacity: {cap}<br>"
                        f"{slab_name}: CPUs {lo}–{hi} ({count} cores)<extra></extra>"
                    ),
                )
            )

    fig.update_layout(
        title=title or "DRM: Precise CPU Slab Assignment per Capacity Level",
        xaxis=dict(title="CPU core #"),
        yaxis=dict(
            title="DRM capacity (total threads)",
            categoryorder="array",
            categoryarray=[str(c) for c in capacities],
        ),
        barmode="overlay",
        legend_title_text="",
        height=350,
    )
    add_figure_note(
        fig,
        "CPU core ranges (slabs) assigned by DRM at steady-state fair-share. "
        "Two disjoint slabs per capacity level — no CPU overlap between the two processes. Source: rm.log.",
    )
    return fig


# ── Plot 3: Thread CPU placement (pidstat) ────────────────────────────────────

def _build_cpu_segments(df: pd.DataFrame, interval_sec: float = 5.0) -> pd.DataFrame:
    """Merge consecutive per-5s pidstat samples into continuous occupation segments.

    Groups by (pid, cpu, benchmark, t_inferred).  Within each group, samples
    within 1.4× the interval are merged; a larger gap starts a new segment.
    Each segment represents an uninterrupted stay on a given CPU core at a
    given thread count.
    """
    segments: list[dict] = []
    gap_tol = interval_sec * 1.4

    has_t = "t_inferred" in df.columns
    has_dyn = "dynamic" in df.columns
    # Use parent_tgid so workers are grouped under their parent process
    id_col = "parent_tgid" if "parent_tgid" in df.columns else "pid"
    group_keys = (
        [id_col, "cpu", "benchmark"]
        + (["t_inferred"] if has_t else [])
        + (["dynamic"] if has_dyn else [])
    )

    for keys, grp in df.groupby(group_keys):
        pid, cpu, bench = keys[0], keys[1], keys[2]
        t_val = int(keys[3]) if has_t else None
        dyn_val = keys[4] if has_t and has_dyn else (keys[3] if has_dyn else None)

        rows = grp.sort_values("elapsed_sec")
        times = rows["elapsed_sec"].tolist()
        if not times:
            continue

        seg_start = max(0.0, times[0] - interval_sec)
        seg_end = times[0]

        def _flush(s, e):
            segments.append({
                "pid": pid, "cpu": cpu, "benchmark": bench,
                "t": t_val,
                "dynamic": dyn_val,
                "start": s, "end": e,
                "duration": e - s,
            })

        for t in times[1:]:
            if t - seg_end <= gap_tol:
                seg_end = t
            else:
                _flush(seg_start, seg_end)
                seg_start = t - interval_sec
                seg_end = t

        _flush(seg_start, seg_end)

    return pd.DataFrame(segments)


# Sub-offsets within each CPU tick: 4 positions for (dyn, band) combinations.
# Bars are 0.16 wide; offsets are spaced 0.18 apart → small gap between each.
_DYN_BAND_OFFSETS: dict[tuple, float] = {
    ("true",  0): -0.27,
    ("true",  1): -0.09,
    ("false", 0): +0.09,
    ("false", 1): +0.27,
}
_BAR_WIDTH  = 0.16


def make_cpu_placement_figure(
    df_pidstat: pd.DataFrame,
    title: str | None = None,
    drm_blocks: list | None = None,
    filter_benchmark: str | None = None,
) -> go.Figure:
    """Gantt-style bar chart showing continuous CPU occupation per benchmark.

    Each horizontal bar spans the full duration that a benchmark process
    occupied a given CPU core without interruption.  Consecutive 5-second
    pidstat samples are merged into single bars.

    x-axis: elapsed seconds since job start.
    y-axis: CPU core # (normalised per process: lowest core → 1).
    Colour: benchmark (FT / CG / EP).
    Position: DRM-managed (dynamic=true) bars sit 0.22 above each core tick;
              non-DRM (dynamic=false) bars sit 0.22 below — no overlap.
    Opacity encodes t (heavier workloads appear more opaque).
    """
    if df_pidstat.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    df = df_pidstat.copy()
    benchmarks_to_show = [filter_benchmark] if filter_benchmark else ["FT", "CG", "EP"]
    df_proc = df[df["benchmark"].isin(benchmarks_to_show)].copy()

    # Rebase elapsed_sec so t=0 is always the first sample for the shown benchmarks.
    t0 = df_proc["ts"].min() if not df_proc.empty else df["ts"].min()
    df_proc["elapsed_sec"] = (df_proc["ts"] - t0).dt.total_seconds()

    # Override t_inferred per tgid using DRM block boundaries when available.
    # Worker-count inference is noisy at block boundaries (especially for fast
    # benchmarks like EP that may only appear in 1–2 pidstat windows), causing
    # tgids to land in the wrong t-group.  The rm.log timestamps tell us exactly
    # which DRM capacity was active, so we use each tgid's median timestamp to
    # look up the correct t.
    if drm_blocks:
        tgid_median_ts = df_proc.groupby("parent_tgid")["ts"].median()
        def _cap_for_ts(ts):
            for blk_start, blk_end, cap in drm_blocks:
                if blk_start <= ts <= blk_end:
                    return cap
            return None
        tgid_t = tgid_median_ts.apply(_cap_for_ts).dropna().astype(int)
        df_proc["t_inferred"] = df_proc["parent_tgid"].map(tgid_t).fillna(df_proc["t_inferred"]).astype(int)

    # Record the pre-normalisation median physical CPU per tgid for band assignment.
    pre_norm_median = (
        df_proc.groupby("parent_tgid")["cpu"].median().rename("_pre_norm_median")
    )

    # Normalise CPUs per domain (DRM / no-DRM) rather than per tgid.
    # Per-tgid normalisation collapses all processes to C1 because each
    # tgid's own minimum maps to 1 — making disjoint DRM slabs look like
    # they share the same cores.  Using the domain minimum preserves the
    # relative positions: DRM slab A stays at C1–Ct/2, slab B at C(t/2+1)–Ct.
    tgid_to_dynamic = df_proc.groupby("parent_tgid")["dynamic"].first()
    domain_min_cpu = (
        df_proc.groupby("parent_tgid")["cpu"].min()
        .groupby(tgid_to_dynamic).min()
    )  # Series indexed by "true"/"false"
    df_proc["_domain_min"] = df_proc["dynamic"].map(domain_min_cpu)
    df_proc["cpu"] = df_proc["cpu"] - df_proc["_domain_min"] + 1
    df_proc = df_proc.drop(columns=["_domain_min"])

    # Auto-detect pidstat sampling interval (supports both 1s and 5s pidstat).
    ts_sorted = sorted(df_proc["ts"].unique())
    if len(ts_sorted) >= 2:
        diffs = sorted((ts_sorted[i + 1] - ts_sorted[i]).total_seconds()
                       for i in range(len(ts_sorted) - 1))
        interval_sec = diffs[len(diffs) // 2]
        interval_sec = max(0.5, min(interval_sec, 10.0))
    else:
        interval_sec = 1.0

    df_seg = _build_cpu_segments(df_proc, interval_sec=interval_sec)
    if df_seg.empty:
        fig = go.Figure()
        fig.add_annotation(text="No segments found", showarrow=False)
        return fig

    # Attach pre-normalisation median CPU so we can rank concurrent processes.
    df_seg = df_seg.join(pre_norm_median, on="pid")

    # Assign band 0 or 1 via interval scheduling: sort tgids by
    # (first_start, median_cpu, pid) and greedily assign each to the lowest
    # free band.  "Free" means the band's last occupant has already ended, so
    # truly concurrent processes are always forced into different bands.
    # Sorting by median_cpu within the same start time keeps the lower-CPU
    # process in band 0 for visual consistency with the DRM slab ordering.
    def _assign_band(grp: pd.DataFrame) -> pd.Series:
        tgid_info = (
            grp.groupby("pid")
            .agg(first_start=("start", "min"), last_end=("end", "max"),
                 median_cpu=("_pre_norm_median", "first"))
            .sort_values(["first_start", "median_cpu", "pid"])
            .reset_index()
        )
        band_map: dict = {}
        band_ends: dict = {0: -float("inf"), 1: -float("inf")}
        for _, row in tgid_info.iterrows():
            pid, start, end = row["pid"], row["first_start"], row["last_end"]
            free = sorted(b for b, e in band_ends.items() if e <= start)
            band = free[0] if free else min(band_ends, key=band_ends.__getitem__)
            band_map[pid] = band
            band_ends[band] = max(band_ends[band], end)
        return grp["pid"].map(band_map)

    band_series = pd.Series(index=df_seg.index, dtype=int)
    for _, grp in df_seg.groupby(["benchmark", "t", "dynamic"]):
        band_series.loc[grp.index] = _assign_band(grp).values
    df_seg["band"] = band_series

    benchmarks = sorted(df_seg["benchmark"].unique())
    color_map = {b: _BENCH_COLORS.get(b, "#aaaaaa") for b in benchmarks}

    t_values = sorted(df_seg["t"].dropna().unique()) if "t" in df_seg.columns else []
    dyn_values = sorted(df_seg["dynamic"].dropna().unique()) if "dynamic" in df_seg.columns else []
    band_values = sorted(int(b) for b in df_seg["band"].dropna().unique()) if "band" in df_seg.columns else [0]

    fig = go.Figure()
    # Track which (bench, t, dyn) legend entries have been shown so that
    # the per-band split doesn't produce duplicate legend items.
    shown_legends: set = set()

    for bench in benchmarks:
        sub_bench = df_seg[df_seg["benchmark"] == bench]

        if t_values and dyn_values:
            for t_val in t_values:
                for dyn in dyn_values:
                    for band in band_values:
                        sub = sub_bench[
                            (sub_bench["t"] == t_val)
                            & (sub_bench["dynamic"] == dyn)
                            & (sub_bench["band"] == band)
                        ]
                        if sub.empty:
                            continue

                        legend_key = (bench, t_val, dyn, band)
                        show_leg = legend_key not in shown_legends
                        if show_leg:
                            shown_legends.add(legend_key)

                        opacity = 0.4 + 0.55 * (t_values.index(t_val) / max(len(t_values) - 1, 1))
                        y_offset = _DYN_BAND_OFFSETS.get((dyn, band), 0.0)
                        worker_lbl = ("A" if dyn == "true" else "B") + str(band + 1)
                        drm_lbl = "DRM" if dyn == "true" else "no-DRM"
                        fig.add_trace(
                            go.Bar(
                                orientation="h",
                                y=sub["cpu"] + y_offset,
                                x=sub["duration"],
                                base=sub["start"],
                                width=_BAR_WIDTH,
                                name=f"{bench} {worker_lbl} t={int(t_val)} ({drm_lbl})",
                                showlegend=show_leg,
                                legendgroup=f"{bench}-{int(t_val)}-{dyn}-{band}",
                                customdata=sub[["pid", "cpu"]].values,
                                marker=dict(
                                    color=_band_color(color_map[bench], band),
                                    opacity=opacity,
                                    line=dict(width=0),
                                    pattern=dict(shape="/" if dyn == "false" else ""),
                                ),
                                hovertemplate=(
                                    f"Benchmark: {bench}<br>"
                                    f"Worker: {worker_lbl} ({drm_lbl})<br>"
                                    f"t = {int(t_val)}<br>"
                                    "PID: %{customdata[0]}<br>"
                                    "CPU core: %{customdata[1]}<br>"
                                    "Start: %{base:.0f} s<br>"
                                    "Duration: %{x:.0f} s<extra></extra>"
                                ),
                            )
                        )
        elif t_values:
            for t_val in t_values:
                sub = sub_bench[sub_bench["t"] == t_val]
                if sub.empty:
                    continue
                opacity = 0.4 + 0.55 * (t_values.index(t_val) / max(len(t_values) - 1, 1))
                fig.add_trace(
                    go.Bar(
                        orientation="h",
                        y=sub["cpu"],
                        x=sub["duration"],
                        base=sub["start"],
                        name=f"{bench} t={int(t_val)}",
                        marker_color=color_map[bench],
                        opacity=opacity,
                        hovertemplate=(
                            f"Benchmark: {bench}<br>"
                            f"t = {int(t_val)}<br>"
                            "CPU core: %{y}<br>"
                            "Start: %{base:.0f} s<br>"
                            "Duration: %{x:.0f} s<extra></extra>"
                        ),
                    )
                )
        else:
            fig.add_trace(
                go.Bar(
                    orientation="h",
                    y=sub_bench["cpu"],
                    x=sub_bench["duration"],
                    base=sub_bench["start"],
                    name=bench,
                    marker_color=color_map[bench],
                    opacity=0.75,
                    hovertemplate=(
                        f"Benchmark: {bench}<br>"
                        "CPU core: %{y}<br>"
                        "Start: %{base:.0f} s<br>"
                        "Duration: %{x:.0f} s<extra></extra>"
                    ),
                )
            )

    # Y-axis: one tick per normalised CPU core, labelled C1, C2, ...
    max_cpu = int(df_seg["cpu"].max()) if not df_seg.empty else 1
    tickvals = list(range(1, max_cpu + 1))
    ticktext = [f"C{c}" for c in tickvals]

    fig.update_layout(
        title=title or "Benchmark Thread CPU Placement Over Time (pidstat)",
        xaxis=dict(title="Elapsed time (s)", rangemode="tozero"),
        yaxis=dict(
            title="CPU core (normalised per process)",
            tickmode="array",
            tickvals=tickvals,
            ticktext=ticktext,
        ),
        barmode="overlay",
        legend_title_text="",
    )
    add_figure_note(
        fig,
        "Each bar = continuous CPU core occupation by a benchmark master thread (TGID row from pidstat). "
        "Consecutive samples on the same core are merged. CPU numbers are normalised per domain: "
        "A-domain (DRM-managed) and B-domain (no-DRM) each start at C1. Source: pidstat -u -t.",
    )
    return fig
