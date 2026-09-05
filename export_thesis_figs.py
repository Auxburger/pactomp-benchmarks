"""Export thesis-quality PDFs for staggered job 209445 and aggregated benchmarks."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

sys.path.insert(0, str(Path(__file__).parent / "src"))

from analysis.datasets.staggered import (
    discover_staggered_groups,
    load_staggered_group,
    load_staggered_grants,
)
from analysis.plots.staggered import (
    make_staggered_figure,
    make_staggered_steadystate_figure,
    make_staggered_threads_figure,
    make_staggered_cpu_slab_figure,
)
from analysis.datasets.npb import load_benchmark_dir, KNOWN_BENCHES
from analysis.reports.npb import build_groups
from analysis.plots.style import (
    BENCHMARK_MARKERS,
    THESIS_HEIGHT,
    THESIS_WIDTH,
    apply_thesis_style,
)
from analysis.plots.npb import (
    make_figure,
    make_mops_figure,
)

REPO_ROOT = Path(__file__).resolve().parent
JOB_DIR = REPO_ROOT / "data" / "staggered" / "209445"

# Figures are consumed by the thesis repo, which lives outside this one. Point
# THESIS_FIGURES_DIR at its figures/ directory to write straight into it.
OUT_DIR = Path(os.environ.get("THESIS_FIGURES_DIR", REPO_ROOT / "figures")).resolve()
OUT_DIR.mkdir(parents=True, exist_ok=True)

groups = discover_staggered_groups(JOB_DIR)
dfs = {}
for alg, t, offset in groups:
    df = load_staggered_group(JOB_DIR, alg, t, offset)
    if not df.empty:
        dfs[alg.upper()] = (df, t, offset)

# ── Timeline figures ─────────────────────────────────────────────────────────
for alg_key, (df, t, offset) in dfs.items():
    fig = make_staggered_figure(df, title=None)
    # Clean up title — use None to auto-title, then override
    fig.update_layout(
        title=dict(text=""),   # suppress — LaTeX caption provides the title
        xaxis_title="Elapsed time (s)",
        yaxis_title="Iteration duration (s)",
    )
    apply_thesis_style(fig)
    out = OUT_DIR / f"staggered_{alg_key.lower()}_timeline.pdf"
    fig.write_image(str(out))
    print(f"Wrote {out}")

# ── Steady-state summary ─────────────────────────────────────────────────────
all_dfs = [df for df, _, _ in dfs.values()]
fig_ss = make_staggered_steadystate_figure(all_dfs, title="")
fig_ss.update_layout(
    title=dict(text=""),
    xaxis_title="Benchmark",
    yaxis_title="Mean iteration duration (s)",
)
apply_thesis_style(fig_ss, h=380)
out_ss = OUT_DIR / "staggered_steadystate_summary.pdf"
fig_ss.write_image(str(out_ss))
print(f"Wrote {out_ss}")

# ── Thread-grant step figure for FT (shows 32→16 renegotiation) ──────────────
if "FT" in dfs:
    df_ft, t_ft, off_ft = dfs["FT"]
    df_grants = load_staggered_grants(JOB_DIR, "FT", t_ft, off_ft)
    fig_thr = make_staggered_threads_figure(
        df_ft,
        df_grants=df_grants if not df_grants.empty else None,
        title="",
    )
    fig_thr.update_layout(
        title=dict(text=""),
        xaxis_title="Elapsed time (s)",
        yaxis_title="Granted threads",
    )
    apply_thesis_style(fig_thr)
    out_thr = OUT_DIR / "staggered_ft_threads.pdf"
    fig_thr.write_image(str(out_thr))
    print(f"Wrote {out_thr}")

# ── CPU slab figures (DRM-granted core range per A-side worker) ───────────────
for alg_key, (df, t, offset) in dfs.items():
    df_grants = load_staggered_grants(JOB_DIR, alg_key, t, offset)
    if df_grants.empty or "cpu_count" not in df_grants.columns:
        print(f"  No grant/slab data for {alg_key}, skipping cpu_slab")
        continue
    fig_slab = make_staggered_cpu_slab_figure(df, df_grants, title="")
    fig_slab.update_layout(
        title=dict(text=""),
        xaxis_title="Elapsed time (s)",
        yaxis_title="CPU core #",
    )
    apply_thesis_style(fig_slab)
    out_slab = OUT_DIR / f"staggered_{alg_key.lower()}_cpu_slab.pdf"
    fig_slab.write_image(str(out_slab))
    print(f"Wrote {out_slab}")


def _make_speedup_thesis_fig(df: pd.DataFrame) -> go.Figure:
    """Clean speedup figure: no annotation arrows, readable at thesis dimensions."""
    agg = (
        df.groupby(["benchmark", "threads", "mode"])["duration_ms"]
        .mean()
        .reset_index()
        .rename(columns={"duration_ms": "mean_ms"})
    )
    pivot = agg.pivot_table(
        index=["benchmark", "threads"],
        columns="mode",
        values="mean_ms",
    ).reset_index()
    pivot.columns.name = None

    if "dynamic=true" not in pivot.columns or "dynamic=false" not in pivot.columns:
        return go.Figure()

    pivot["speedup"] = pivot["dynamic=false"] / pivot["dynamic=true"]
    pivot = pivot.dropna(subset=["speedup"])

    benchmarks = sorted(pivot["benchmark"].unique())
    threads_sorted = sorted(pivot["threads"].unique())
    bench_colors = {b: px.colors.qualitative.Plotly[i] for i, b in enumerate(benchmarks)}

    fig = go.Figure()
    for bench in benchmarks:
        sub = pivot[pivot["benchmark"] == bench].sort_values("threads")
        fig.add_trace(go.Scatter(
            x=sub["threads"].astype(str),
            y=sub["speedup"],
            mode="lines+markers",
            name=bench,
            line=dict(color=bench_colors[bench], width=2),
            marker=dict(
                size=9,
                symbol=BENCHMARK_MARKERS.get(bench.upper(), "circle"),
                line=dict(color="white", width=1),
            ),
            hovertemplate=(
                f"Benchmark: {bench}<br>"
                "Threads: %{x}<br>"
                "Speedup: %{y:.3f}×<extra></extra>"
            ),
        ))

    fig.add_hline(y=1.0, line=dict(color="grey", dash="dash", width=1.5))
    fig.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=[str(t) for t in threads_sorted],
        title_text="Thread count (t)",
    )
    fig.update_yaxes(title_text="Speedup (no-DRM time / DRM time)")
    fig.update_layout(title="")
    return fig


# ── Aggregated benchmark figures ─────────────────────────────────────────────
# `dual` (job 172930): two concurrent processes per condition sharing one
# taskset CPU pool per NUMA domain, no worker-thread pinning. This is the
# genuine concurrent-contention experiment and what the thesis tables report.
# `dual-exclusive` is excluded: it only ever launched one process per
# configuration (no `_2` output files), so dyn=true/false are indistinguishable
# there and it cannot represent the two-process oversubscription scenario.
BENCH_ROOT = REPO_ROOT / "data"
agg_sources = [
    ("dual", BENCH_ROOT / "dual"),
]

agg_run_dirs = []
for source_name, root in agg_sources:
    if root.exists():
        agg_run_dirs.extend((source_name, p) for p in root.iterdir() if p.is_dir())
agg_run_dirs = sorted(agg_run_dirs, key=lambda sp: (sp[0], sp[1].name))

for group_name, dirs in build_groups(agg_run_dirs):
    all_dfs = []
    for source, run_dir in dirs:
        for bench_path in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            bench_name = bench_path.name.lower()
            if bench_name not in KNOWN_BENCHES:
                continue
            df = load_benchmark_dir(bench_path, bench_name, run_name=run_dir.name, source=source)
            if not df.empty:
                all_dfs.append(df)

    if not all_dfs:
        continue

    df_group = pd.concat(all_dfs, ignore_index=True)

    for bench in sorted(df_group["benchmark"].unique()):
        df_bench = df_group[df_group["benchmark"] == bench].copy()

        fig_rt = make_figure(df_bench, title="", show_raw_points=True)
        fig_rt.update_layout(title=dict(text=""), xaxis_title="Threads", yaxis_title="Time (ms)")
        apply_thesis_style(fig_rt)
        out = OUT_DIR / f"aggregated_{bench.lower()}_runtime.pdf"
        fig_rt.write_image(str(out))
        print(f"Wrote {out}")

        df_mops = df_bench[df_bench["mops_total"].notna()].copy()
        if not df_mops.empty:
            fig_m = make_mops_figure(df_mops, title="", show_raw_points=True)
            fig_m.update_layout(title=dict(text=""), xaxis_title="Threads", yaxis_title="Mop/s total")
            apply_thesis_style(fig_m)
            out = OUT_DIR / f"aggregated_{bench.lower()}_mops.pdf"
            fig_m.write_image(str(out))
            print(f"Wrote {out}")

    modes = set(df_group["mode"].unique())
    if "dynamic=true" in modes and "dynamic=false" in modes:
        fig_sp = _make_speedup_thesis_fig(df_group)
        apply_thesis_style(fig_sp)
        out = OUT_DIR / "aggregated_drm_speedup.pdf"
        fig_sp.write_image(str(out))
        print(f"Wrote {out}")

print("Done.")
