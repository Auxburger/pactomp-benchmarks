"""Staggered runs: per-iteration durations and the steady-state comparison."""

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
    for dyn, color, label, pattern in [
        ("true", _WORKER_COLORS["A1"], "A – DRM", ""),
        ("false", _WORKER_COLORS["B1"], "B – no DRM", "/"),
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
            marker_pattern_shape=pattern,
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
                marker=dict(
                    size=8,
                    symbol=_WORKER_MARKERS.get(worker, "circle"),
                    line=dict(color="white", width=1),
                ),
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
