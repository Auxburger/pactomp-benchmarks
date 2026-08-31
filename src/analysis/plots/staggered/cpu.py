"""Staggered runs: which CPU slab each worker occupied over time."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..style import (
    WORKER_COLORS as _WORKER_COLORS,
    WORKER_DASH as _WORKER_DASH,
    WORKER_LABELS as _WORKER_LABELS,
    WORKER_MARKERS as _WORKER_MARKERS,
    add_figure_note,
)


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
            mode="lines+markers",
            line=dict(color=color, width=1.5),
            marker=dict(
                size=5,
                symbol=_WORKER_MARKERS.get(worker, "circle"),
            ),
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

