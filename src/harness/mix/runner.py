"""Running one arm of the mixed workload experiment.

An arm replays the whole schedule once: every job waits out its start offset,
then re-runs its NPB kernel back to back until its time window closes. One
thread per job drives one benchmark process at a time, so the number of
concurrent OpenMP processes rises and falls exactly as the schedule says.

The two arms differ only in `OMP_DYNAMIC` and in whether the coordinator is up:
- `drm`   — coordinator running, `OMP_DYNAMIC=true`  → the runtime asks for its share
- `nodrm` — no coordinator,     `OMP_DYNAMIC=false` → every job takes all threads
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .. import children, npb_out
from ..logging_utils import fmt_cpus, log
from ..paths import LLVM_BUILD
from .config import Config
from .schedule import Job, Schedule

STOP = threading.Event()


@dataclass
class IterationResult:
    """One benchmark process: what ran, when, and how long it took."""

    arm: str
    repeat: int
    job_id: int
    label: str
    algorithm: str
    threads: int
    iteration: int
    start_offset: float
    window_seconds: float
    start_epoch_ms: int
    start_since_arm_ms: int
    wall_ms: int
    time_seconds: "float | None"
    mops_total: "float | None"
    total_threads: "int | None"
    avail_threads: "int | None"
    overran_window: bool
    pid: "int | None"
    exit_code: "int | None"


def build_env(cfg: Config, arm: str, job: Job) -> "dict[str, str]":
    env = os.environ.copy()
    libdir = LLVM_BUILD / "lib"
    existing = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{libdir}:{existing}" if existing else str(libdir)

    env["OMP_NUM_THREADS"] = str(job.threads)
    env["OMP_DYNAMIC"] = "true" if arm == "drm" else "false"
    # Disable the runtime's load-average heuristic, which can otherwise override
    # the DRM grant and serialise a region (see experiments/CLAUDE.md).
    env["KMP_DYNAMIC_MODE"] = "thread_limit"
    env["OMP_DISPLAY_AFFINITY"] = "true" if cfg.display_affinity else "false"
    return env


def command_for(cfg: Config, job: Job, cpus: "list[int]") -> "list[str]":
    """The benchmark command, pinned with taskset(1) as the shell scripts do.

    Not `preexec_fn=os.sched_setaffinity`, the way the single-threaded tracing
    driver pins its cells: this driver runs a thread per job, and preexec_fn
    between fork and exec is not thread-safe.
    """
    binary = str(cfg.binary_for(job.algorithm))
    if not cpus:
        return [binary]
    return ["taskset", "-c", fmt_cpus(cpus), binary]


def _sleep_until(target: float) -> bool:
    """Wait for the monotonic deadline. False if the run was cut short."""
    while True:
        remaining = target - time.monotonic()
        if remaining <= 0:
            return not STOP.is_set()
        if STOP.wait(min(remaining, 0.25)):
            return False


def _run_iteration(
    cfg: Config,
    arm: str,
    repeat: int,
    job: Job,
    cpus: "list[int]",
    env: "dict[str, str]",
    out_file: Path,
    iteration: int,
    arm_start: float,
    deadline: float,
) -> IterationResult:
    command = command_for(cfg, job, cpus)
    start_epoch_ms = int(round(time.time() * 1000))
    started = time.monotonic()

    with out_file.open("a", encoding="utf-8") as handle:
        handle.write(f"=== iteration {iteration} start_epoch_ms={start_epoch_ms} ===\n")
        handle.flush()
        proc = children.register(
            subprocess.Popen(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                env=env,
                cwd=str(out_file.parent),
            )
        )
        try:
            proc.wait(timeout=cfg.timeout)
        except subprocess.TimeoutExpired:
            log(f"WARNING: {arm}/{job.label} iteration {iteration} timed out, killing it")
            proc.kill()
            proc.wait()
        finally:
            children.unregister(proc)

    finished = time.monotonic()
    # Only this iteration's own block, so a job's summary values stay separate.
    text = out_file.read_text(encoding="utf-8", errors="replace")
    block = text.rsplit(f"=== iteration {iteration} ", 1)[-1]
    summary = npb_out.parse_summary(block)

    return IterationResult(
        arm=arm,
        repeat=repeat,
        job_id=job.job_id,
        label=job.label,
        algorithm=job.algorithm,
        threads=job.threads,
        iteration=iteration,
        start_offset=job.start_offset,
        window_seconds=job.duration,
        start_epoch_ms=start_epoch_ms,
        start_since_arm_ms=int(round((started - arm_start) * 1000)),
        wall_ms=int(round((finished - started) * 1000)),
        time_seconds=summary["time_seconds"],
        mops_total=summary["mops_total"],
        total_threads=summary["total_threads"],
        avail_threads=summary["avail_threads"],
        overran_window=finished > deadline,
        pid=proc.pid,
        exit_code=proc.returncode,
    )


def _run_job(
    cfg: Config,
    arm: str,
    repeat: int,
    job: Job,
    cpus: "list[int]",
    arm_dir: Path,
    arm_start: float,
    sink: "list[IterationResult]",
    lock: threading.Lock,
) -> None:
    out_file = arm_dir / f"{job.label}.out"
    out_file.write_text(
        f"# arm={arm} repeat={repeat} job={job.label} alg={job.algorithm} threads={job.threads} "
        f"start_offset={job.start_offset:.3f} window={job.duration:.3f}\n",
        encoding="utf-8",
    )
    env = build_env(cfg, arm, job)
    deadline = arm_start + job.start_offset + job.duration

    if not _sleep_until(arm_start + job.start_offset):
        return
    log(f"{arm}: {job.label} joins (alg={job.algorithm} window={job.duration:.1f}s)")

    iteration = 0
    while not STOP.is_set() and time.monotonic() < deadline:
        iteration += 1
        result = _run_iteration(
            cfg, arm, repeat, job, cpus, env, out_file, iteration, arm_start, deadline
        )
        with lock:
            sink.append(result)
        log(
            f"{arm}: {job.label} iter={iteration} {result.wall_ms}ms "
            f"tis={result.time_seconds} threads={result.total_threads}/{result.avail_threads}"
        )
        if cfg.gap_seconds > 0 and time.monotonic() + cfg.gap_seconds < deadline:
            if STOP.wait(cfg.gap_seconds):
                return

    log(f"{arm}: {job.label} done after {iteration} iteration(s)")


def run_arm(
    cfg: Config,
    schedule: Schedule,
    arm: str,
    cpus: "list[int]",
    arm_dir: Path,
    repeat: int = 1,
) -> "list[IterationResult]":
    """Replay the schedule once. Returns every benchmark process that ran."""
    arm_dir.mkdir(parents=True, exist_ok=True)
    results: "list[IterationResult]" = []
    lock = threading.Lock()

    log(f"=== arm {arm} (repeat {repeat}): {len(schedule.jobs)} jobs on CPUs {fmt_cpus(cpus)} ===")
    arm_start = time.monotonic()
    threads = [
        threading.Thread(
            target=_run_job,
            args=(cfg, arm, repeat, job, cpus, arm_dir, arm_start, results, lock),
            name=f"{arm}-{job.label}",
            daemon=True,
        )
        for job in schedule.jobs
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    makespan_ms = int(round((time.monotonic() - arm_start) * 1000))
    log(f"=== arm {arm} (repeat {repeat}) finished: {len(results)} iterations "
        f"in {makespan_ms / 1000:.1f}s ===")
    return results
