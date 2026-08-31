"""Staggered experiment jobs (data/staggered/<jobid>/) → output/staggered/."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..datasets.cpu_util import parse_cpu_util
from ..datasets.drm import parse_drm_blocks, parse_pidstat
from ..datasets.staggered import (
    discover_staggered_groups,
    load_staggered_drm_pins,
    load_staggered_grants,
    load_staggered_group,
)
from ..io import write_outputs
from ..plots.cpu_util import make_cpu_util_heatmap
from ..plots.drm import make_cpu_placement_figure
from ..plots.staggered import (
    make_staggered_cpu_assignment_figure,
    make_staggered_cpu_slab_figure,
    make_staggered_figure,
    make_staggered_steadystate_figure,
    make_staggered_threads_figure,
)
from .freshness import up_to_date


def _resolve_jobid(df: "pd.DataFrame", stag_pidstat: dict) -> str | None:
    """Return the job ID whose pidstat time range covers the worker log timestamps.

    Matches by finding the pidstat file with the greatest time overlap with
    the worker log window.  Returns None if no pidstat is available.
    """
    from datetime import datetime

    if df.empty or not stag_pidstat:
        return None

    t0_ms = df["start_epoch_ms"].min()
    t1_ms = (df["start_epoch_ms"] + df["duration_ms"]).max()
    t0_dt = datetime.fromtimestamp(t0_ms / 1000)
    t1_dt = datetime.fromtimestamp(t1_ms / 1000)

    best_jobid: str | None = None
    best_overlap = 0.0
    for ps_tag, df_ps in stag_pidstat.items():
        ps_t0 = df_ps["ts"].min().to_pydatetime().replace(tzinfo=None)
        ps_t1 = df_ps["ts"].max().to_pydatetime().replace(tzinfo=None)
        overlap = (min(t1_dt, ps_t1) - max(t0_dt, ps_t0)).total_seconds()
        if overlap > best_overlap:
            best_overlap = overlap
            best_jobid = ps_tag.removeprefix("pidstat_")

    return best_jobid


def _process_one_staggered_job(
    jobid: str,
    log_dir: Path,
    job_out: Path,
    df_ps,
    drm_blocks: list,
    static: bool,
    png: bool = False,
) -> list:
    """Process all (alg, t, offset) groups in log_dir for one staggered job.

    Returns a list of loaded DataFrames (one per group) for the steady-state summary.
    """
    job_dfs: list = []
    groups = discover_staggered_groups(log_dir)
    for alg, t, offset in groups:
        print(f"  Staggered: {alg} t={t} offset={offset}s")
        df = load_staggered_group(log_dir, alg, t, offset)
        if df.empty:
            print(f"    No data, skipping.")
            continue
        job_dfs.append(df)

        alg_l = alg.lower()
        fig = make_staggered_figure(df, title=f"Staggered DRM vs. no-DRM: {alg} t={t} offset={offset}s")
        write_outputs(fig, job_out / f"{alg_l}_timeline.html", also_static=static, also_png=png)

        df_grants = load_staggered_grants(log_dir, alg, t, offset)
        if not df_grants.empty:
            print(f"    Loaded {len(df_grants)} DRM grants for {alg} t={t} off={offset}")
        fig_t = make_staggered_threads_figure(
            df,
            df_grants=df_grants if not df_grants.empty else None,
            title=f"Staggered – negotiated threads: {alg} t={t} offset={offset}s",
        )
        write_outputs(fig_t, job_out / f"{alg_l}_threads.html", also_static=static, also_png=png)

        if not df_grants.empty and "cpu_count" in df_grants.columns:
            fig_slab = make_staggered_cpu_slab_figure(
                df, df_grants,
                title=f"Staggered – DRM CPU slab: {alg} t={t} offset={offset}s",
            )
            write_outputs(fig_slab, job_out / f"{alg_l}_cpu_slab.html", also_static=static, also_png=png)

        df_pins = load_staggered_drm_pins(log_dir, alg, t, offset)
        if not df_pins.empty:
            print(f"    Loaded {len(df_pins)} DRM pin events for {alg} t={t} off={offset}")
            fig_pins = make_staggered_cpu_assignment_figure(
                df_pins,
                title=f"DRM CPU pin assignment: {alg} t={t} offset={offset}s",
            )
            write_outputs(fig_pins, job_out / f"{alg_l}_cpu_pins.html", also_static=static, also_png=png)

        if df_ps is not None and not df_ps.empty:
            fig_place = make_cpu_placement_figure(
                df_ps,
                title=f"CPU placement – {alg} t={t} offset={offset}s ({jobid})",
                drm_blocks=drm_blocks or None,
                filter_benchmark=alg,
            )
            write_outputs(fig_place, job_out / f"{alg_l}_cpu_placement.html", also_static=static, also_png=png)

    return job_dfs


def process_staggered_logs(staggered_dir: Path, out_dir: Path, static: bool, png: bool = False,
                           newest_only: bool = True) -> None:
    stag_out = out_dir / "staggered"
    stag_out.mkdir(parents=True, exist_ok=True)

    # Collect new-format job subdirectories: data/staggered/<jobid>/
    # Each subdir contains the logs for one SLURM job (pidstat.log, cpu_util.log, *_A1.log …)
    # Sort numerically by job ID so the newest (highest) ID is last.
    all_job_subdirs: list[tuple[str, Path]] = sorted(
        [(d.name, d) for d in staggered_dir.iterdir() if d.is_dir() and list(d.glob("*_A1.log"))],
        key=lambda nd: int(nd[0]) if nd[0].isdigit() else 0,
    )

    if newest_only and all_job_subdirs:
        job_subdirs = all_job_subdirs[-1:]
        print(f"[newest-only] staggered job {job_subdirs[0][0]} (use --all to process all jobs)")
    else:
        job_subdirs = all_job_subdirs

    # Pre-parse all rm.logs for DRM block boundaries (both formats)
    stag_drm_blocks: list = []
    for rm_log in sorted(staggered_dir.glob("*_rm.log")):  # old format (flat)
        stag_drm_blocks.extend(parse_drm_blocks(rm_log))
    for _, job_dir in job_subdirs:
        for rm_log in sorted(job_dir.glob("*_rm.log")):    # new format (subdir)
            stag_drm_blocks.extend(parse_drm_blocks(rm_log))

    # Parse old-format pidstat files (pidstat_<jobid>.log in flat dir)
    stag_pidstat: dict = {}
    for ps_log in sorted(staggered_dir.glob("pidstat_*.log")):
        df_ps = parse_pidstat(ps_log)
        if not df_ps.empty:
            stag_pidstat[ps_log.stem] = df_ps

    all_staggered_dfs: list = []
    written_jobids: set[str] = set()
    jobid_to_dfs: dict[str, list] = {}

    # ── New-format jobs (one subdir per SLURM job) ────────────────────────────
    for jobid, job_dir in job_subdirs:
        print(f"Staggered job {jobid} (new format)")
        job_out = stag_out / jobid

        if up_to_date([job_dir], job_out):
            print(f"Staggered job {jobid}: up to date, skipping.")
            continue

        job_out.mkdir(exist_ok=True)

        job_drm_blocks = []
        for rm_log in sorted(job_dir.glob("*_rm.log")):
            job_drm_blocks.extend(parse_drm_blocks(rm_log))

        pidstat_path = job_dir / "pidstat.log"
        df_ps_job = parse_pidstat(pidstat_path) if pidstat_path.exists() else None

        job_dfs = _process_one_staggered_job(
            jobid, job_dir, job_out, df_ps_job, job_drm_blocks, static, png
        )
        all_staggered_dfs.extend(job_dfs)
        if job_dfs:
            jobid_to_dfs[jobid] = job_dfs
            written_jobids.add(jobid)

        # Steady-state summary for this job
        if job_dfs:
            fig_ss = make_staggered_steadystate_figure(
                job_dfs,
                title=f"Staggered: steady-state iteration time (iters 3–13) — job {jobid}",
            )
            write_outputs(fig_ss, job_out / "steadystate_summary.html", also_static=static, also_png=png)

        # CPU util heatmap (cpu_util.log in the job subdir)
        cpu_util_path = job_dir / "cpu_util.log"
        if cpu_util_path.exists():
            print(f"  Parsing cpu_util: {cpu_util_path}")
            df_cu = parse_cpu_util(cpu_util_path)
            if not df_cu.empty:
                fig_cu = make_cpu_util_heatmap(df_cu, title=f"CPU Utilisation – staggered ({jobid})")
                write_outputs(fig_cu, job_out / "cpu_util.html", also_static=static, also_png=png)

    # ── Old-format groups (flat files directly in staggered_dir) ─────────────
    old_groups = [] if newest_only else discover_staggered_groups(staggered_dir)
    if not old_groups and not job_subdirs:
        print("No staggered log groups found.")
        return

    for alg, t, offset in old_groups:
        print(f"Staggered: {alg} t={t} offset={offset}s (old format)")
        df = load_staggered_group(staggered_dir, alg, t, offset)
        if df.empty:
            print(f"  No data, skipping.")
            continue
        all_staggered_dfs.append(df)

        jobid = _resolve_jobid(df, stag_pidstat)
        if jobid:
            print(f"  → job {jobid}")
            job_dir = stag_out / jobid
            job_dir.mkdir(exist_ok=True)
            jobid_to_dfs.setdefault(jobid, []).append(df)
        else:
            job_dir = stag_out

        df_ps_old = stag_pidstat.get(f"pidstat_{jobid}") if jobid else None
        alg_l = alg.lower()
        fig = make_staggered_figure(df, title=f"Staggered DRM vs. no-DRM: {alg} t={t} offset={offset}s")
        write_outputs(fig, job_dir / f"{alg_l}_timeline.html", also_static=static, also_png=png)

        df_grants = load_staggered_grants(staggered_dir, alg, t, offset)
        if not df_grants.empty:
            print(f"  Loaded {len(df_grants)} DRM grants for {alg} t={t} off={offset}")
        fig_t = make_staggered_threads_figure(
            df,
            df_grants=df_grants if not df_grants.empty else None,
            title=f"Staggered – negotiated threads: {alg} t={t} offset={offset}s",
        )
        write_outputs(fig_t, job_dir / f"{alg_l}_threads.html", also_static=static, also_png=png)

        if not df_grants.empty and "cpu_count" in df_grants.columns:
            fig_slab = make_staggered_cpu_slab_figure(
                df, df_grants,
                title=f"Staggered – DRM CPU slab: {alg} t={t} offset={offset}s",
            )
            write_outputs(fig_slab, job_dir / f"{alg_l}_cpu_slab.html", also_static=static, also_png=png)

        df_pins = load_staggered_drm_pins(staggered_dir, alg, t, offset)
        if not df_pins.empty:
            print(f"  Loaded {len(df_pins)} DRM pin events for {alg} t={t} off={offset}")
            fig_pins = make_staggered_cpu_assignment_figure(
                df_pins,
                title=f"DRM CPU pin assignment: {alg} t={t} offset={offset}s",
            )
            write_outputs(fig_pins, job_dir / f"{alg_l}_cpu_pins.html", also_static=static, also_png=png)

        if df_ps_old is not None and not df_ps_old.empty:
            fig_place = make_cpu_placement_figure(
                df_ps_old,
                title=f"CPU placement – {alg} t={t} offset={offset}s ({jobid})",
                drm_blocks=stag_drm_blocks or None,
                filter_benchmark=alg,
            )
            write_outputs(fig_place, job_dir / f"{alg_l}_cpu_placement.html", also_static=static, also_png=png)

    # Steady-state summary for old-format jobs (skip jobids already written)
    for jobid, dfs in jobid_to_dfs.items():
        if jobid in written_jobids:
            continue
        fig_ss = make_staggered_steadystate_figure(
            dfs,
            title=f"Staggered: steady-state iteration time (iters 3–13) — job {jobid}",
        )
        write_outputs(fig_ss, stag_out / jobid / "steadystate_summary.html", also_static=static, also_png=png)

    if all_staggered_dfs and not jobid_to_dfs:
        fig_ss = make_staggered_steadystate_figure(all_staggered_dfs)
        write_outputs(fig_ss, stag_out / "steadystate_summary.html", also_static=static, also_png=png)

    # CPU placement for pidstat-only job IDs (no worker logs were matched to them)
    covered_ids = set(jobid_to_dfs) | written_jobids
    pidstat_only_ids = sorted(
        k.removeprefix("pidstat_") for k in stag_pidstat
        if k.removeprefix("pidstat_") not in covered_ids
    )
    for jobid in pidstat_only_ids:
        df_ps = stag_pidstat[f"pidstat_{jobid}"]
        if df_ps.empty:
            continue
        print(f"  cpu_placement (pidstat only): job {jobid}")
        job_dir = stag_out / jobid
        job_dir.mkdir(exist_ok=True)
        fig_place = make_cpu_placement_figure(
            df_ps,
            title=f"CPU placement – job {jobid}",
            drm_blocks=stag_drm_blocks or None,
        )
        write_outputs(fig_place, job_dir / "cpu_placement.html", also_static=static, also_png=png)

    # Old-format cpu_util files (cpu_util_<jobid>.log in flat dir)
    if newest_only:
        return
    for cu_log in sorted(staggered_dir.glob("cpu_util_*.log")):
        print(f"  Parsing cpu_util: {cu_log}")
        df_cu = parse_cpu_util(cu_log)
        if df_cu.empty:
            continue
        jobid = cu_log.stem.removeprefix("cpu_util_")
        job_dir = stag_out / jobid
        job_dir.mkdir(exist_ok=True)
        fig_cu = make_cpu_util_heatmap(df_cu, title=f"CPU Utilisation – staggered ({jobid})")
        write_outputs(fig_cu, job_dir / "cpu_util.html", also_static=static, also_png=png)

    print("Done staggered plots.")
