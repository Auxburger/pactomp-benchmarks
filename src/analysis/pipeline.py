from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .io_utils import write_outputs
from .parsing import KNOWN_BENCHES, load_benchmark_dir
from .plotting import (
    make_combined_figure,
    make_combined_init_figure,
    make_combined_mops_figure,
    make_figure,
    make_init_figure,
    make_mops_figure,
    make_speedup_figure,
)


def build_groups(run_dirs: list[tuple[str, Path]]) -> list[tuple[str, list[tuple[str, Path]]]]:
    """
    Split run directories into groups.
    - aggregated: run_0, run_1, ...
    """
    numbered_runs = [
        (source, p) for (source, p) in run_dirs if re.fullmatch(r"run_\d+", p.name.lower())
    ]

    if not numbered_runs:
        print("Warning: no run_<n> folders found (run_0..).")

    groups: list[tuple[str, list[tuple[str, Path]]]] = []
    if numbered_runs:
        groups.append(("aggregated", numbered_runs))

    return groups


def process_group(
    group_name: str,
    group_run_dirs: list[tuple[str, Path]],
    out_dir: Path,
    show_raw: bool,
    static: bool,
    combined: bool,
) -> None:
    all_dfs_this_group: list[pd.DataFrame] = []

    # Iterate all runs in group, then all kernels within each run
    for source, run_dir in group_run_dirs:
        run_name = run_dir.name  # keep original run name in df for traceability

        kernel_dirs = [p for p in run_dir.iterdir() if p.is_dir()]
        kernel_dirs = sorted(kernel_dirs, key=lambda p: p.name)

        for bench_path in kernel_dirs:
            bench_name = bench_path.name.lower()
            if bench_name not in KNOWN_BENCHES:
                continue

            df = load_benchmark_dir(bench_path, bench_name, run_name=run_name, source=source)
            if df.empty:
                continue

            all_dfs_this_group.append(df)

    if not all_dfs_this_group:
        print(f"Skipping group '{group_name}': no data found.")
        return

    df_group = pd.concat(all_dfs_this_group, ignore_index=True)

    # Output folder for the group
    group_out = out_dir / group_name
    group_out.mkdir(parents=True, exist_ok=True)

    # Write per-benchmark plots for this group
    for bench in sorted(df_group["benchmark"].unique()):
        df_bench = df_group[df_group["benchmark"] == bench].copy()
        if df_bench.empty:
            continue

        title = f"{bench} runtime vs threads ({group_name})"
        fig = make_figure(df_bench, title=title, show_raw_points=show_raw)

        out_html = group_out / f"{bench.lower()}_runtime.html"
        write_outputs(fig, out_html, also_static=static)

        # Long-form CSV per benchmark (all stats)
        df_bench.to_csv(group_out / f"{bench.lower()}_stats_long.csv", index=False)

        df_bench_mops = df_bench[df_bench["mops_total"].notna()].copy()
        if not df_bench_mops.empty:
            title_mops = f"{bench} Mop/s total vs threads ({group_name})"
            fig_mops = make_mops_figure(df_bench_mops, title=title_mops, show_raw_points=show_raw)
            out_html_mops = group_out / f"{bench.lower()}_mops_total.html"
            write_outputs(fig_mops, out_html_mops, also_static=static)

        df_bench_init = df_bench[df_bench["init_ms"].notna()].copy()
        if not df_bench_init.empty:
            title_init = f"{bench} initialization time vs threads ({group_name})"
            fig_init = make_init_figure(df_bench_init, title=title_init, show_raw_points=show_raw)
            out_html_init = group_out / f"{bench.lower()}_init_time.html"
            write_outputs(fig_init, out_html_init, also_static=static)

        # Long-form CSV per benchmark (contains run_name + rep, useful later)
        # df_bench.to_csv(group_out / f"{bench.lower()}_runtime_long.csv", index=False)

    # Combined facet plot per group
    if combined:
        fig_all = make_combined_figure(df_group, group_name=group_name)
        out_html = group_out / "npb_all_kernels_runtime.html"
        write_outputs(fig_all, out_html, also_static=False)

        # Long-form CSV for the whole group
        df_group.to_csv(group_out / "npb_all_kernels_stats_long.csv", index=False)

        df_group_mops = df_group[df_group["mops_total"].notna()].copy()
        if not df_group_mops.empty:
            fig_all_mops = make_combined_mops_figure(df_group_mops, group_name=group_name)
            out_html_mops = group_out / "npb_all_kernels_mops_total.html"
            write_outputs(fig_all_mops, out_html_mops, also_static=False)

        df_group_init = df_group[df_group["init_ms"].notna()].copy()
        if not df_group_init.empty:
            fig_all_init = make_combined_init_figure(df_group_init, group_name=group_name)
            out_html_init = group_out / "npb_all_kernels_init_time.html"
            write_outputs(fig_all_init, out_html_init, also_static=False)

    # Speedup plot: requires both dyn=true and dyn=false data
    modes_present = set(df_group["mode"].unique()) if not df_group.empty else set()
    if "dynamic=true" in modes_present and "dynamic=false" in modes_present:
        fig_speedup = make_speedup_figure(df_group, group_name=group_name)
        write_outputs(fig_speedup, group_out / "npb_drm_speedup.html", also_static=static)

    print(f"Done group: {group_name}")
