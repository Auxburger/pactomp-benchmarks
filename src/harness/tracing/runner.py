"""Running one measurement cell: N concurrent microbenchmark processes at a
fixed thread count and OMP_DYNAMIC setting.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import children, npb_out
from .config import Config
from ..logging_utils import fmt_cpus, log, now
from ..paths import LLVM_BUILD


@dataclass
class ProcResult:
    run_name: str
    benchmark: str
    threads: int
    dynamic: bool
    program_id: int
    cpus: str
    drm: bool
    wall_ms: int
    time_seconds: "float | None"
    total_threads: "int | None"
    avail_threads: "int | None"
    pid: "int | None"
    exit_code: int


def allowed_cpus() -> "list[int]":
    return sorted(os.sched_getaffinity(0))


def cell_cpus(pin: str, threads: int, allowed: "list[int]") -> "list[int] | None":
    """CPUs for one cell: the first `threads` allowed CPUs, all of them, or no pinning."""
    if pin == "none":
        return None
    if pin == "all":
        return list(allowed)
    if threads > len(allowed):
        return list(allowed)
    return allowed[:threads]


def build_env(cfg: Config, threads: int, dynamic: bool, cpus: "list[int] | None") -> "dict[str, str]":
    env = os.environ.copy()
    libdir = LLVM_BUILD / "lib"
    existing = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{libdir}:{existing}" if existing else str(libdir)

    env["OMP_NUM_THREADS"] = str(threads)
    env["OMP_DYNAMIC"] = "true" if dynamic else "false"
    # Disable the runtime's load-average heuristic, which can otherwise override
    # the DRM grant and serialise a region (see experiments/CLAUDE.md).
    env["KMP_DYNAMIC_MODE"] = "thread_limit"
    env["OMP_DISPLAY_AFFINITY"] = "true" if cfg.display_affinity else "false"
    if cfg.places:
        env["OMP_PLACES"] = cfg.places
    if cfg.proc_bind:
        env["OMP_PROC_BIND"] = cfg.proc_bind

    # Read by omp_dyn.c: busy-loop length, scaled by the oversubscription factor.
    env["OMP_DYN_BUSY_SECONDS"] = str(cfg.busy_seconds)
    env["OMP_DYN_CORES"] = str(len(cpus) if cpus else len(allowed_cpus()))
    if cfg.region_sizes:
        env["OMP_DYN_REGION_SIZES"] = cfg.region_sizes
        env["OMP_DYN_REGION_DWELL_SECONDS"] = str(cfg.region_dwell_seconds)
    return env


def _pin_to(cpus: "list[int] | None"):
    if not cpus:
        return None

    def _apply() -> None:
        os.sched_setaffinity(0, cpus)

    return _apply


def parse_out_file(path: Path) -> "tuple[float | None, int | None, int | None, int | None]":
    """Read the NPB-shaped summary block: seconds, total threads, avail threads, pid."""
    s = npb_out.parse_out_file(path)
    return s["time_seconds"], s["total_threads"], s["avail_threads"], s["pid"]


def _await_all(entries: list, deadline: float, timeout: float) -> None:
    remaining = list(entries)
    while remaining:
        for entry in list(remaining):
            if entry[1].poll() is not None:
                entry[5] = time.monotonic()
                remaining.remove(entry)
        if not remaining:
            return
        if time.monotonic() > deadline:
            log(f"WARNING: timeout after {timeout}s, killing {len(remaining)} process(es)")
            for entry in remaining:
                entry[1].kill()
                entry[5] = time.monotonic()
            return
        time.sleep(0.02)


def run_cell(
    cfg: Config,
    run_name: str,
    run_dir: Path,
    threads: int,
    dynamic: bool,
    cpus: "list[int] | None",
) -> "list[ProcResult]":
    """Launch cfg.procs concurrent microbenchmark processes and wait for all of them."""
    bench_dir = run_dir / cfg.bench
    bench_dir.mkdir(parents=True, exist_ok=True)
    mode = "true" if dynamic else "false"
    env = build_env(cfg, threads, dynamic, cpus)
    log_path = bench_dir / f"{cfg.bench}_log_t{threads}.txt"

    with log_path.open("a", encoding="utf-8") as cell_log:
        cell_log.write(f"Batch run started: {now()}\n")
        cell_log.write(f"dyn={mode} num_threads={threads} cpus={fmt_cpus(cpus)}\n")

    log(f"{run_name} t={threads} dyn={mode} procs={cfg.procs} cpus={fmt_cpus(cpus)}")

    started = time.monotonic()
    entries = []
    for program_id in range(1, cfg.procs + 1):
        out_file = bench_dir / f"{cfg.bench}_threads_{threads}_dyn_{mode}_{program_id}.out"
        handle = out_file.open("w", encoding="utf-8")
        proc = children.register(
            subprocess.Popen(
                [str(cfg.binary)],
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=str(bench_dir),
                preexec_fn=_pin_to(cpus),
            )
        )
        entries.append([program_id, proc, handle, out_file, time.monotonic(), None])

    _await_all(entries, started + cfg.timeout, cfg.timeout)

    results = []
    for program_id, proc, handle, out_file, t0, t1 in entries:
        proc.wait()
        handle.close()
        children.unregister(proc)
        seconds, total, avail, pid = parse_out_file(out_file)
        results.append(
            ProcResult(
                run_name=run_name,
                benchmark=cfg.bench,
                threads=threads,
                dynamic=dynamic,
                program_id=program_id,
                cpus=fmt_cpus(cpus),
                drm=cfg.drm,
                wall_ms=int(round(((t1 or time.monotonic()) - t0) * 1000)),
                time_seconds=seconds,
                total_threads=total,
                avail_threads=avail,
                pid=pid,
                exit_code=proc.returncode,
            )
        )

    cell_ms = int(round((time.monotonic() - started) * 1000))
    with log_path.open("a", encoding="utf-8") as cell_log:
        cell_log.write(f"dyn {mode} finished: {now()} (Duration: {cell_ms}ms)\n")

    for r in results:
        log(
            f"  proc {r.program_id}: {r.wall_ms}ms  tis={r.time_seconds}  "
            f"threads={r.total_threads}/{r.avail_threads}  rc={r.exit_code}"
        )
    return results
