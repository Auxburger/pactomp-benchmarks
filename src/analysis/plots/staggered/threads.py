"""Staggered runs: the thread count each worker was granted over time."""

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
                mode="lines+markers",
                line=dict(
                    color=_WORKER_COLORS.get(worker, "#aaaaaa"),
                    dash=_WORKER_DASH.get(worker, "solid"),
                    width=2,
                    shape="hv",
                ),
                marker=dict(
                    size=7,
                    symbol=_WORKER_MARKERS.get(worker, "circle"),
                    line=dict(color="white", width=1),
                ),
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

