"""DRM and monitoring logs (rm.log, pidstat, mpstat) → output/monitoring/."""

from __future__ import annotations

from pathlib import Path

from ..datasets.cpu_util import parse_cpu_util
from ..datasets.drm import parse_drm_blocks, parse_pidstat, parse_rm_log
from ..io import write_outputs
from ..plots.cpu_util import make_cpu_util_heatmap
from ..plots.drm import (
    make_cpu_placement_figure,
    make_drm_allocation_figure,
    make_drm_cpu_assignment_figure,
)
from .freshness import up_to_date


def process_monitoring_logs(dual_dirs: list[Path], out_dir: Path, static: bool, png: bool = False) -> None:
    """Process monitoring data (rm.log, pidstat, cpu_util) from dual experiment directories.

    Staggered experiment logs are intentionally excluded — those are handled by
    process_staggered_logs so that all staggered output lands in one place.
    """
    mon_out = out_dir / "monitoring"
    mon_out.mkdir(parents=True, exist_ok=True)

    rm_logs = sorted(p for d in dual_dirs for p in d.rglob("rm.log"))
    pidstat_logs = sorted(p for d in dual_dirs for p in d.glob("pidstat_*.log"))
    cpu_util_logs = sorted(p for d in dual_dirs for p in d.glob("cpu_util_*.log"))
    pidstat_jobids = [p.stem.removeprefix("pidstat_") for p in pidstat_logs]

    # Always parse DRM block boundaries — used as context in cpu_placement figures.
    all_drm_blocks: list = []
    # Also build DRM allocation/CPU-assignment figures, but only parse rm.log
    # when at least one target job dir is missing or stale.
    drm_figs: list[tuple] = []
    for rm_log in rm_logs:
        all_drm_blocks.extend(parse_drm_blocks(rm_log))

        targets = pidstat_jobids if pidstat_jobids else [rm_log.parent.name]
        needs_drm = any(
            not up_to_date([rm_log], mon_out / jid) for jid in targets
        )
        if not needs_drm:
            print(f"DRM log {rm_log.parent.name}: up to date, skipping.")
            continue

        print(f"Parsing DRM log: {rm_log}")
        df_rm = parse_rm_log(rm_log)
        if df_rm.empty:
            print(f"  No cpu_pool-format grants found in {rm_log.name}, skipping.")
            continue

        tag = rm_log.parent.name
        drm_figs.append((tag, targets,
            make_drm_allocation_figure(df_rm,
                title=f"DRM: Estimated Allocation Duration per Parallel Region ({tag})"),
            make_drm_cpu_assignment_figure(df_rm,
                title=f"DRM: CPU Slab Assignment per Process ({tag})"),
        ))

    for tag, targets, fig_dur, fig_cpu in drm_figs:
        for jobid in targets:
            job_dir = mon_out / jobid
            job_dir.mkdir(exist_ok=True)
            write_outputs(fig_dur, job_dir / "drm_allocation_duration.html", also_static=static, also_png=png)
            write_outputs(fig_cpu, job_dir / "drm_cpu_assignment.html", also_static=static, also_png=png)

    # pidstat logs → monitoring/{jobid}/cpu_placement.html
    for ps_log in pidstat_logs:
        jobid = ps_log.stem.removeprefix("pidstat_")
        out_file = mon_out / jobid / "cpu_placement.html"
        if out_file.exists() and ps_log.stat().st_mtime <= out_file.stat().st_mtime:
            print(f"pidstat {jobid}: up to date, skipping.")
            continue

        print(f"Parsing pidstat: {ps_log}")
        df_ps = parse_pidstat(ps_log)
        if df_ps.empty:
            print(f"  No benchmark processes found in {ps_log.name}, skipping.")
            continue

        job_dir = mon_out / jobid
        job_dir.mkdir(exist_ok=True)
        fig_place = make_cpu_placement_figure(
            df_ps,
            title=f"Thread CPU Placement Over Time ({jobid})",
            drm_blocks=all_drm_blocks or None,
        )
        write_outputs(fig_place, out_file, also_static=static, also_png=png)

    # cpu_util logs → monitoring/{jobid}/cpu_util.html
    for cu_log in cpu_util_logs:
        jobid = cu_log.stem.removeprefix("cpu_util_")
        out_file = mon_out / jobid / "cpu_util.html"
        if out_file.exists() and cu_log.stat().st_mtime <= out_file.stat().st_mtime:
            print(f"cpu_util {jobid}: up to date, skipping.")
            continue

        print(f"Parsing cpu_util: {cu_log}")
        df_cu = parse_cpu_util(cu_log)
        if df_cu.empty:
            print(f"  No active CPUs found, skipping.")
            continue
        job_dir = mon_out / jobid
        job_dir.mkdir(exist_ok=True)
        fig_cu = make_cpu_util_heatmap(df_cu, title=f"CPU Utilisation ({jobid})")
        write_outputs(fig_cu, out_file, also_static=static, also_png=png)

    print("Done monitoring plots.")
