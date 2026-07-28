from __future__ import annotations

import argparse
from pathlib import Path


def _max_mtime(paths: list[Path]) -> float:
    """Return the newest mtime across all files under the given paths (recursive)."""
    mtimes: list[float] = []
    for p in paths:
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    mtimes.append(f.stat().st_mtime)
        elif p.is_file():
            mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0


def _up_to_date(inputs: list[Path], output_dir: Path) -> bool:
    """True if output_dir has *.html files and all are newer than every input file."""
    if not output_dir.exists():
        return False
    outputs = list(output_dir.glob("*.html"))
    if not outputs:
        return False
    oldest_out = min(p.stat().st_mtime for p in outputs)
    return _max_mtime(inputs) <= oldest_out

if __package__ in (None, ""):
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[1]))
    from plots.pipeline import build_groups, process_group
    from plots.monitoring_parsing import parse_rm_log, parse_pidstat, parse_drm_blocks
    from plots.monitoring_plots import (
        make_drm_allocation_figure,
        make_drm_cpu_assignment_figure,
        make_cpu_placement_figure,
    )
    from plots.io_utils import write_outputs
    from plots.staggered_parsing import discover_staggered_groups, load_staggered_group
    from plots.staggered_plots import make_staggered_figure, make_staggered_threads_figure, make_staggered_cpu_slab_figure, make_staggered_steadystate_figure, make_staggered_cpu_assignment_figure
    from plots.staggered_parsing import load_staggered_grants, load_staggered_drm_pins
    from plots.cpu_util_parsing import parse_cpu_util
    from plots.cpu_util_plots import make_cpu_util_heatmap
else:
    from .pipeline import build_groups, process_group
    from .monitoring_parsing import parse_rm_log, parse_pidstat, parse_drm_blocks
    from .monitoring_plots import (
        make_drm_allocation_figure,
        make_drm_cpu_assignment_figure,
        make_cpu_placement_figure,
    )
    from .io_utils import write_outputs
    from .staggered_parsing import discover_staggered_groups, load_staggered_group
    from .cpu_util_parsing import parse_cpu_util
    from .cpu_util_plots import make_cpu_util_heatmap
    from .staggered_plots import make_staggered_figure, make_staggered_threads_figure, make_staggered_cpu_slab_figure, make_staggered_steadystate_figure, make_staggered_cpu_assignment_figure
    from .staggered_parsing import load_staggered_grants, load_staggered_drm_pins


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show-raw", action="store_true", help="Overlay raw points", default=True)
    ap.add_argument("--static", action="store_true", help="Also export PDF (requires kaleido).", default=False)
    ap.add_argument("--png", action="store_true", help="Also export PNG next to each HTML (requires kaleido).", default=False)
    ap.add_argument("--combined", action="store_true", help="Combined multi-benchmark HTML per group (facets).", default=True)
    ap.add_argument("--all", dest="all_jobs", action="store_true",
                    help="Process all staggered jobs; default is newest only.")
    args = ap.parse_args()

    # Resolve paths relative to repository root (works on Windows and Linux)
    plots_root = Path(__file__).resolve().parents[1]
    repo_root = plots_root.parent
    benchmarks_base = repo_root / "data"
    out_dir = plots_root / "plots"  # outputs into ./plots/<group>

    sources = [
        ("dual-exclusive", benchmarks_base / "dual-exclusive"),
        ("dual", benchmarks_base / "dual"),
    ]

    missing = [root for _, root in sources if not root.exists()]
    if missing:
        raise SystemExit(
            "benchmarks root(s) not found: " + ", ".join(str(p.resolve()) for p in missing)
        )

    run_dirs: list[tuple[str, Path]] = []
    for source_name, root in sources:
        run_dirs.extend((source_name, p) for p in root.iterdir() if p.is_dir())
    run_dirs = sorted(run_dirs, key=lambda sp: (sp[0], sp[1].name))

    groups = build_groups(run_dirs)
    if not groups:
        roots_msg = ", ".join(str(p.resolve()) for _, p in sources)
        raise SystemExit(f"No suitable run directories found under: {roots_msg}")

    # Process groups
    for group_name, dirs in groups:
        input_dirs = [p for _, p in dirs]
        if _up_to_date(input_dirs, out_dir / group_name):
            print(f"Group {group_name}: up to date, skipping.")
            continue
        process_group(
            group_name,
            dirs,
            out_dir=out_dir,
            show_raw=args.show_raw,
            static=args.static,
            combined=args.combined,
        )

    # ── Monitoring plots (rm.log + pidstat, dual experiments only) ───────────
    dual_dirs = [root for _, root in sources]
    process_monitoring_logs(dual_dirs, out_dir, static=args.static, png=args.png)

    # ── Staggered experiment plots ─────────────────────────────────────────────
    staggered_dir = benchmarks_base / "staggered"
    if staggered_dir.exists():
        process_staggered_logs(staggered_dir, out_dir, static=args.static, png=args.png,
                               newest_only=not args.all_jobs)

    print("All done.")


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
            not _up_to_date([rm_log], mon_out / jid) for jid in targets
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

        if _up_to_date([job_dir], job_out):
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


if __name__ == "__main__":
    main()
