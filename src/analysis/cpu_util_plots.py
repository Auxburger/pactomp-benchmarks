from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


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
