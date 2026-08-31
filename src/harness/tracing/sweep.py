"""The sweep itself: compile, then walk thread counts × runs × OMP_DYNAMIC modes."""

from __future__ import annotations

import time

from .. import children
from .build import compile_microbench
from .config import Config, make_config, parse_args
from ..coordinator import Coordinator, NoCoordinator
from ..logging_utils import fmt_cpus, log
from .record import append_timings, write_manifest
from .runner import allowed_cpus, cell_cpus, run_cell


def describe(cfg: Config, allowed: "list[int]") -> None:
    log(f"output dir : {cfg.out_dir}")
    log(f"allowed CPUs: {len(allowed)} ({fmt_cpus(allowed)})")
    log(f"threads    : {cfg.threads}")
    log(f"modes      : {['true' if m else 'false' for m in cfg.modes]}")
    log(f"runs       : {cfg.runs}   procs/cell: {cfg.procs}   pin: {cfg.pin}")
    log(f"DRM        : {'on — ' + str(cfg.drm_binary) if cfg.drm else 'off'}")
    for t in cfg.threads:
        if t > len(allowed):
            log(f"WARNING: t={t} exceeds the {len(allowed)} allowed CPUs — cells will oversubscribe")


def sweep(cfg: Config, allowed: "list[int]") -> None:
    timings = cfg.out_dir / "timings.csv"
    rm_log = cfg.out_dir / "rm.log"

    # Thread count outermost so the coordinator's capacity matches each cell,
    # exactly as test_all.sh does for the NPB experiment.
    for threads in cfg.threads:
        cpus = cell_cpus(cfg.pin, threads, allowed)
        coordinator = (
            Coordinator(cfg.drm_binary, threads, cpus or allowed, rm_log, cfg.drm_socket)
            if cfg.drm
            else NoCoordinator()
        )
        with coordinator:
            for run_index in range(1, cfg.runs + 1):
                run_name = f"run_{run_index}"
                for dynamic in cfg.modes:
                    results = run_cell(cfg, run_name, cfg.out_dir / run_name, threads, dynamic, cpus)
                    append_timings(timings, results)
                    if cfg.settle_seconds > 0:
                        time.sleep(cfg.settle_seconds)

    log(f"done — results in {cfg.out_dir}")
    log(f"timings: {timings}")
    if cfg.drm:
        log(f"DRM log: {rm_log}")


def main(argv: "list[str] | None" = None) -> int:
    args = parse_args(argv)
    cfg = make_config(args)
    allowed = allowed_cpus()

    if not cfg.source.is_file():
        raise SystemExit(f"microbenchmark source not found: {cfg.source}")
    if cfg.drm and not cfg.drm_binary.is_file():
        raise SystemExit(f"DRM binary not found: {cfg.drm_binary} (pass --no-drm to run without it)")

    describe(cfg, allowed)
    if args.dry_run:
        cells = cfg.runs * len(cfg.threads) * len(cfg.modes)
        log(f"dry run: {cells} cells, {cells * cfg.procs} processes")
        return 0

    children.install_signal_handlers(log)
    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    build = args.build
    if build is None:
        build = not cfg.binary.is_file()
    compile_cmd = None
    if build:
        compile_cmd = compile_microbench(cfg.source, cfg.binary, args.compiler)
    elif not cfg.binary.is_file():
        raise SystemExit(f"binary not found: {cfg.binary} (pass --build)")

    write_manifest(cfg, cfg.out_dir / "manifest.json", compile_cmd, allowed)
    sweep(cfg, allowed)
    return 0
