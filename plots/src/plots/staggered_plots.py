from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from .io_utils import add_figure_note

_WORKER_COLORS = {
    "A1": "#4C72B0",
    "A2": "#96B5D8",
    "B1": "#DD8452",
    "B2": "#EDB899",
}
_WORKER_LABELS = {
    "A1": "A1 – DRM (first)",
    "A2": "A2 – DRM (joins later)",
    "B1": "B1 – no-DRM (first)",
    "B2": "B2 – no-DRM (joins later)",
}
_WORKER_DASH = {
    "A1": "solid",
    "A2": "dot",
    "B1": "solid",
    "B2": "dot",
}


def _build_thread_step(
    df: pd.DataFrame, worker: str
) -> tuple[list[float], list[int], list]:
    """Build (x, y, customdata) for a step-function of negotiated thread count.

    For DRM workers, inserts explicit boundary points at the exact moment the
    OTHER A-side worker joins or leaves — so within-iteration transitions are
    visible even when the change happens mid-run.
    For no-DRM workers, returns a flat line at the configured t.

    Returns (elapsed_sec list, threads list, customdata list).
    customdata rows are [iter_or_None, duration_sec_or_None].
    """
    t_val = int(df["t"].iloc[0])
    t_half = t_val // 2

    sub = df[df["worker"] == worker].sort_values("elapsed_sec").reset_index(drop=True)
    dyn = sub["dyn"].iloc[0]

    if dyn != "true":
        xs = sub["elapsed_sec"].tolist()
        ys = [t_val] * len(xs)
        cd = [[int(r["iter"]), float(r["duration_sec"])] for _, r in sub.iterrows()]
        return xs, ys, cd

    # Compute the other A-side worker's active epoch window (in elapsed_sec)
    other_a = df[(df["dyn"] == "true") & (df["worker"] != worker)]
    if other_a.empty:
        xs = sub["elapsed_sec"].tolist()
        ys = [t_val] * len(xs)
        cd = [[int(r["iter"]), float(r["duration_sec"])] for _, r in sub.iterrows()]
        return xs, ys, cd

    other_join = float(other_a["elapsed_sec"].min())
    other_leave = float((other_a["elapsed_sec"] + other_a["duration_sec"]).max())

    this_start = float(sub["elapsed_sec"].min())
    this_end = float((sub["elapsed_sec"] + sub["duration_sec"]).max())

    # Base points: one per iteration
    points: list[tuple[float, int, list]] = []
    for _, row in sub.iterrows():
        start = float(row["elapsed_sec"])
        if start < other_join:
            t_here = t_val
        elif start < other_leave:
            t_here = t_half
        else:
            t_here = t_val
        points.append((start, t_here, [int(row["iter"]), float(row["duration_sec"])]))

    # Inject boundary at other_join if it falls mid-run for this worker
    if this_start < other_join < this_end:
        points.append((other_join, t_half, [None, None]))

    # Inject boundary at other_leave if it falls mid-run for this worker
    if this_start < other_leave < this_end:
        points.append((other_leave, t_val, [None, None]))

    points.sort(key=lambda p: p[0])

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cd = [p[2] for p in points]
    return xs, ys, cd


def make_staggered_threads_figure(
    df: pd.DataFrame,
    df_grants: pd.DataFrame | None = None,
    title: str | None = None,
) -> go.Figure:
    """Step chart of DRM-negotiated thread count vs. elapsed time per worker.

    When df_grants is provided (from load_staggered_grants), each data point is
    one actual DRM grant event with its timestamp interpolated from the worker
    log's epoch window — giving accurate within-iteration transitions.

    Without df_grants, falls back to boundary-injected iteration-level steps.

    B-side workers (no-DRM) are always shown as a flat reference line at t.
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    workers = [w for w in ("A1", "A2", "B1", "B2") if w in df["worker"].unique()]
    offset_sec = df["offset"].iloc[0]
    alg = df["alg"].iloc[0]
    t = int(df["t"].iloc[0])

    a_rows = df[df["dyn"] == "true"]
    join_sec: float = float(offset_sec)
    leave_sec: float | None = None
    if not a_rows.empty and "A2" in a_rows["worker"].values:
        a2 = a_rows[a_rows["worker"] == "A2"]
        join_sec = float(a2["elapsed_sec"].min())
        leave_sec = float((a2["elapsed_sec"] + a2["duration_sec"]).max())

    fig = go.Figure()
    use_grants = df_grants is not None and not df_grants.empty

    all_t_values: set[int] = set()

    for worker in workers:
        sub_w = df[df["worker"] == worker]
        dyn = sub_w["dyn"].iloc[0]

        if use_grants and dyn == "true":
            # Grant-level step function: one point per DRM grant event
            sub_g = df_grants[df_grants["worker"] == worker].sort_values("elapsed_sec")
            xs = sub_g["elapsed_sec"].tolist()
            ys = sub_g["threads_granted"].tolist()
            all_t_values.update(ys)
            cd = sub_g[["iter", "grant_idx"]].values.tolist()
            hover = (
                f"Worker: {worker}<br>"
                "Iter: %{customdata[0]}  Grant: %{customdata[1]}<br>"
                "Time: %{x:.2f} s<br>"
                "Granted t: %{y}<extra></extra>"
            )
        else:
            # Iteration-level fallback (B-side or no rm.log)
            xs, ys, cd = _build_thread_step(df, worker)
            all_t_values.update(ys)
            hover = (
                f"Worker: {worker}<br>"
                "Iter: %{customdata[0]}<br>"
                "Start: %{x:.1f} s<br>"
                "Negotiated t: %{y}<extra></extra>"
            )

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines" if (use_grants and dyn == "true") else "lines+markers",
                line=dict(
                    color=_WORKER_COLORS.get(worker, "#aaaaaa"),
                    dash=_WORKER_DASH.get(worker, "solid"),
                    width=2,
                    shape="hv",
                ),
                marker=dict(size=4),
                name=_WORKER_LABELS.get(worker, worker),
                customdata=cd,
                hovertemplate=hover,
            )
        )

    fig.add_vline(
        x=join_sec,
        line=dict(color="grey", dash="dash", width=1.5),
        annotation_text=f"A2/B2 join (+{join_sec:.0f}s)",
        annotation_position="top right",
        annotation_font_size=11,
    )
    if leave_sec is not None:
        fig.add_vline(
            x=leave_sec,
            line=dict(color="grey", dash="dot", width=1.5),
            annotation_text="A2/B2 leave",
            annotation_position="top left",
            annotation_font_size=11,
        )

    tick_vals = sorted(all_t_values)
    fig.update_layout(
        title=title or f"Staggered – negotiated thread count: {alg} t={t} offset={offset_sec}s",
        xaxis=dict(title="Elapsed time (s)"),
        yaxis=dict(
            title="Granted threads (DRM)",
            tickmode="array",
            tickvals=tick_vals,
            ticktext=[str(v) for v in tick_vals],
        ),
        legend=dict(title=""),
        hovermode="x unified",
    )
    add_figure_note(
        fig,
        "A-side: step function of DRM-granted thread count per iteration (drops t→t/2 on join, recovers on leave). "
        "B-side: flat reference line at fixed t. Source: rm.log (grant events) + worker logs (iteration windows).",
    )
    return fig


def _expand_hv(xs: list, ys: list) -> tuple[list, list]:
    """Expand (x, y) pairs into explicit coordinates for an 'hv' step shape."""
    if not xs:
        return [], []
    rx, ry = [xs[0]], [ys[0]]
    for i in range(1, len(xs)):
        rx.append(xs[i])
        ry.append(ys[i - 1])  # horizontal segment at old y
        rx.append(xs[i])
        ry.append(ys[i])      # vertical jump to new y
    return rx, ry


def _expand_hv_cd(xs: list, cd: list) -> list:
    """Expand customdata to match _expand_hv coordinate count."""
    if not xs:
        return []
    result = [cd[0]]
    for i in range(1, len(xs)):
        result.append(cd[i - 1])  # horizontal segment keeps previous value
        result.append(cd[i])      # vertical jump takes new value
    return result


def make_staggered_cpu_slab_figure(
    df: pd.DataFrame,
    df_grants: pd.DataFrame,
    title: str | None = None,
) -> go.Figure:
    """Filled-band chart showing the DRM-granted CPU slab per A-side worker over time.

    Each grant with cpu_count > 0 defines a slab [cpu_start, cpu_start + cpu_count).
    The band is drawn as a filled area using an 'hv' (step) shape so transitions
    are shown at the exact interpolated grant timestamp.

    Grants with CPUs 0+0 (no slab assigned yet) are filtered out.
    B-side workers are omitted — they have no DRM slab.
    """
    if df_grants.empty:
        fig = go.Figure()
        fig.add_annotation(text="No DRM grant data", showarrow=False)
        return fig

    alg = df["alg"].iloc[0]
    t = int(df["t"].iloc[0])
    offset_sec = df["offset"].iloc[0]

    a_rows = df[df["dyn"] == "true"]
    join_sec: float = float(offset_sec)
    leave_sec: float | None = None
    if not a_rows.empty and "A2" in a_rows["worker"].values:
        a2 = a_rows[a_rows["worker"] == "A2"]
        join_sec = float(a2["elapsed_sec"].min())
        leave_sec = float((a2["elapsed_sec"] + a2["duration_sec"]).max())

    fig = go.Figure()
    workers = [w for w in ("A1", "A2") if w in df_grants["worker"].unique()]

    for worker in workers:
        sub = (
            df_grants[(df_grants["worker"] == worker) & (df_grants["cpu_count"] > 0)]
            .sort_values("elapsed_sec")
        )
        if sub.empty:
            continue

        xs = sub["elapsed_sec"].tolist()
        lo = sub["cpu_start"].tolist()
        hi = (sub["cpu_start"] + sub["cpu_count"]).tolist()

        # Extend the last slab to the end of this worker's run
        w_end = float(
            (df[df["worker"] == worker]["elapsed_sec"] +
             df[df["worker"] == worker]["duration_sec"]).max()
        )
        xs_plot = xs + [w_end]
        lo_plot = lo + [lo[-1]]
        hi_plot = hi + [hi[-1]]
        cd_plot = [[lo_v, hi_v, hi_v - lo_v] for lo_v, hi_v in zip(lo_plot, hi_plot)]

        # Expand into explicit hv step coordinates
        xu, yu = _expand_hv(xs_plot, hi_plot)
        xl, yl = _expand_hv(xs_plot, lo_plot)
        cd_exp = _expand_hv_cd(xs_plot, cd_plot)

        color = _WORKER_COLORS.get(worker, "#aaaaaa")
        r = int(color[1:3], 16)
        g_val = int(color[3:5], 16)
        b = int(color[5:7], 16)
        fill_color = f"rgba({r},{g_val},{b},0.25)"

        # Upper boundary — invisible, defines top of fill, no tooltip
        fig.add_trace(go.Scatter(
            x=xu, y=yu,
            mode="lines",
            line=dict(color=color, width=1.5),
            name=f"{worker} slab top",
            legendgroup=worker,
            showlegend=False,
            hoverinfo="skip",
        ))
        # Lower boundary with fill; tooltip shows the full slab range
        fig.add_trace(go.Scatter(
            x=xl, y=yl,
            mode="lines",
            line=dict(color=color, width=1.5),
            fill="tonexty",
            fillcolor=fill_color,
            name=_WORKER_LABELS.get(worker, worker),
            legendgroup=worker,
            customdata=cd_exp,
            hovertemplate=(
                f"<b>{worker}</b><br>"
                "Time: %{x:.2f} s<br>"
                "Slab: CPU %{customdata[0]}–%{customdata[1]}"
                " (%{customdata[2]} cores)<extra></extra>"
            ),
        ))

    fig.add_vline(
        x=join_sec,
        line=dict(color="grey", dash="dash", width=1.5),
        annotation_text=f"A2/B2 join (+{join_sec:.0f}s)",
        annotation_position="top right",
        annotation_font_size=11,
    )
    if leave_sec is not None:
        fig.add_vline(
            x=leave_sec,
            line=dict(color="grey", dash="dot", width=1.5),
            annotation_text="A2/B2 leave",
            annotation_position="top left",
            annotation_font_size=11,
        )

    fig.update_layout(
        title=title or f"Staggered – DRM granted CPU slab: {alg} t={t} offset={offset_sec}s",
        xaxis=dict(title="Elapsed time (s)"),
        yaxis=dict(title="CPU core #"),
        legend=dict(title=""),
        hovermode="x unified",
        hoverlabel=dict(font=dict(size=13)),
    )
    add_figure_note(
        fig,
        "Filled band = CPU core range (slab) granted by DRM to each A-side worker. "
        "Band width = granted thread count. A1 holds CPUs 1–t/2; A2 gets t/2+1–t while both are active. "
        "B-side has no slab (no DRM). Source: rm.log.",
    )
    return fig


def make_staggered_steadystate_figure(
    dfs: list[pd.DataFrame],
    title: str | None = None,
) -> go.Figure:
    """Grouped bar chart of mean steady-state iteration time: A (DRM) vs B (no DRM).

    Steady state is defined as iterations 3–13, which excludes the warm-up first
    iterations, the solo phase at the start, and the final solo phase when one
    worker finishes before the other.

    All (alg, t, offset) groups are combined. One bar group per algorithm.
    """
    if not dfs:
        fig = go.Figure()
        fig.add_annotation(text="No staggered data", showarrow=False)
        return fig

    combined = pd.concat(dfs, ignore_index=True)
    steady = combined[combined["iter"].between(3, 13)].copy()
    if steady.empty:
        fig = go.Figure()
        fig.add_annotation(text="No steady-state iterations (3–13) found", showarrow=False)
        return fig

    agg = (
        steady.groupby(["alg", "dyn"])["duration_sec"]
        .agg(mean="mean", std="std", n="count")
        .reset_index()
    )

    algs = sorted(agg["alg"].unique())

    fig = go.Figure()
    for dyn, color, label in [
        ("true", _WORKER_COLORS["A1"], "A – DRM"),
        ("false", _WORKER_COLORS["B1"], "B – no DRM"),
    ]:
        sub = agg[agg["dyn"] == dyn].set_index("alg")
        means = [float(sub.loc[a, "mean"]) if a in sub.index else 0.0 for a in algs]
        stds = [float(sub.loc[a, "std"]) if a in sub.index else 0.0 for a in algs]
        ns = [int(sub.loc[a, "n"]) if a in sub.index else 0 for a in algs]

        fig.add_trace(go.Bar(
            x=algs,
            y=means,
            name=label,
            marker_color=color,
            error_y=dict(type="data", array=stds, visible=True),
            customdata=list(zip(stds, ns)),
            hovertemplate=(
                f"{label}<br>"
                "Algorithm: %{{x}}<br>"
                "Mean: %{{y:.2f}} s<br>"
                "Std: %{{customdata[0]:.2f}} s<br>"
                "n: %{{customdata[1]}}<extra></extra>"
            ),
        ))

    # Annotate per-algorithm percentage difference (B vs A relative to A)
    agg_idx = agg.set_index(["alg", "dyn"])
    for alg in algs:
        try:
            drm_t = float(agg_idx.loc[(alg, "true"), "mean"])
            nodrm_t = float(agg_idx.loc[(alg, "false"), "mean"])
        except KeyError:
            continue
        pct = (nodrm_t - drm_t) / drm_t * 100
        sign = "+" if pct >= 0 else ""
        fig.add_annotation(
            x=alg,
            y=max(drm_t, nodrm_t),
            text=f"{sign}{pct:.0f}%",
            showarrow=False,
            yshift=14,
            font=dict(size=11),
        )

    fig.update_layout(
        title=title or "Staggered: steady-state iteration time (iters 3–13)",
        xaxis=dict(title="Benchmark"),
        yaxis=dict(title="Mean iteration duration (s)"),
        barmode="group",
        legend=dict(title=""),
    )
    add_figure_note(
        fig,
        "Mean ± std of iteration duration in steady state (iterations 3–13), excluding warm-up and solo phases. "
        "Percentage annotation = (B − A) / A × 100; positive value means DRM (A) is faster. "
        "Source: worker logs (*_A1/A2/B1/B2.log).",
    )
    return fig


def make_staggered_cpu_assignment_figure(
    df_pins: pd.DataFrame,
    title: str | None = None,
) -> go.Figure:
    """Bar chart of CPU assignment range distribution from DRM pin logs (A-side only).

    Shows how many pin events were recorded per assigned CPU range (e.g. '1-16',
    '17-32', '1-32').  The ideal 2-client split (e.g. '1-16' and '17-32') should
    dominate; transient 3-client windows produce other ranges.
    """
    if df_pins.empty:
        fig = go.Figure()
        fig.add_annotation(text="No DRM pin log data", showarrow=False)
        return fig

    counts = df_pins.groupby("assigned").size().reset_index(name="count")
    counts = counts.sort_values("count", ascending=False).reset_index(drop=True)
    total = counts["count"].sum()
    counts["pct"] = counts["count"] / total * 100

    # Color bars by whether the range matches the expected half-split or full range
    colors = []
    for _, row in counts.iterrows():
        base, top = row["assigned"].split("-")
        span = int(top) - int(base) + 1
        t_half = df_pins["cpu_top"].max() // 2 if "cpu_top" in df_pins.columns else 0
        full_span = df_pins["cpu_top"].max() + 1 if "cpu_top" in df_pins.columns else 0
        if span <= t_half + 1:
            colors.append(_WORKER_COLORS["A1"])   # half-slab: expected 2-client state
        else:
            colors.append(_WORKER_COLORS["A2"])   # full slab: solo state

    fig = go.Figure(go.Bar(
        x=counts["assigned"],
        y=counts["count"],
        marker_color=colors,
        text=[f"{p:.1f}%" for p in counts["pct"]],
        textposition="auto",
        customdata=counts["pct"].round(1).tolist(),
        hovertemplate=(
            "Assignment: %{x}<br>"
            "Count: %{y}<br>"
            "Share: %{customdata}%<extra></extra>"
        ),
    ))

    fig.update_layout(
        title=title or "DRM CPU pin assignment distribution (staggered, A-side only)",
        xaxis=dict(title="Assigned CPU range"),
        yaxis=dict(title="Pin event count"),
    )
    add_figure_note(
        fig,
        "Count of CPU pin events per assigned range (A-side workers only). "
        "Dark bars = half-slab (2-client shared state); light bars = full slab (solo state). "
        "Source: *_drm.log (OpenMP runtime DRM-pin events).",
    )
    return fig


def make_staggered_figure(df: pd.DataFrame, title: str | None = None) -> go.Figure:
    """Scatter + line chart of per-iteration duration vs. elapsed time.

    Each point is one benchmark iteration, positioned at the iteration's
    start time on the x-axis.  The four workers (A1/A2/B1/B2) are shown
    as separate traces so the DRM rebalancing and oversubscription onset
    are immediately visible.

    A vertical dashed line marks the offset at which A2/B2 join.
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No data", showarrow=False)
        return fig

    fig = go.Figure()

    workers = [w for w in ("A1", "A2", "B1", "B2") if w in df["worker"].unique()]
    offset_sec = df["offset"].iloc[0]
    alg = df["alg"].iloc[0]
    t = int(df["t"].iloc[0])

    for worker in workers:
        sub = df[df["worker"] == worker].sort_values("elapsed_sec")
        fig.add_trace(
            go.Scatter(
                x=sub["elapsed_sec"],
                y=sub["duration_sec"],
                mode="lines+markers",
                name=_WORKER_LABELS.get(worker, worker),
                line=dict(
                    color=_WORKER_COLORS.get(worker, "#aaaaaa"),
                    dash=_WORKER_DASH.get(worker, "solid"),
                    width=2,
                ),
                marker=dict(size=7),
                customdata=sub[["iter", "duration_ms"]].values,
                hovertemplate=(
                    f"Worker: {worker}<br>"
                    "Iter: %{customdata[0]}<br>"
                    "Start: %{x:.1f} s<br>"
                    "Duration: %{y:.2f} s (%{customdata[1]} ms)<extra></extra>"
                ),
            )
        )

    # Vertical line at the offset where A2/B2 join
    fig.add_vline(
        x=offset_sec,
        line=dict(color="grey", dash="dash", width=1.5),
        annotation_text=f"A2/B2 join (+{offset_sec}s)",
        annotation_position="top right",
        annotation_font_size=11,
    )

    fig.update_layout(
        title=title or f"Staggered DRM vs. no-DRM: {alg} t={t} offset={offset_sec}s",
        xaxis=dict(title="Elapsed time (s)"),
        yaxis=dict(title="Iteration duration (s)"),
        legend=dict(title=""),
        hovermode="x unified",
    )
    add_figure_note(
        fig,
        "Each point is one benchmark iteration. A1/A2 = DRM-managed; B1/B2 = unmanaged (fixed t threads). "
        "A2 and B2 join after the configured offset. DRM renegotiates thread counts on join/leave. "
        f"Source: {alg.lower()}_t{t}_off{offset_sec}_*.log.",
    )
    return fig
