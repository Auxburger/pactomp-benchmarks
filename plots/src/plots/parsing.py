from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


OUT_FILENAME_RE = re.compile(
    r"^(?P<bench>[a-z0-9]+)_threads_(?P<threads>\d+)_dyn_(?P<dynamic>true|false)_(?P<program>\d+)\.out$",
    re.IGNORECASE,
)
TIME_SECONDS_RE = re.compile(r"^Time in seconds\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
MOPS_TOTAL_RE = re.compile(r"^Mop/s total\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
INIT_SECONDS_RE = re.compile(
    r"^\s*Initialization time\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)\s*seconds",
    re.IGNORECASE,
)
MOPS_THREAD_RE = re.compile(r"^Mop/s/thread\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
TOTAL_THREADS_RE = re.compile(r"^Total threads\s*=\s*([0-9]+)", re.IGNORECASE)
AVAIL_THREADS_RE = re.compile(r"^Avail threads\s*=\s*([0-9]+)", re.IGNORECASE)
OP_TYPE_RE = re.compile(r"^Operation type\s*=\s*(.+)$", re.IGNORECASE)
PID_RE = re.compile(r"^OMP:\s*pid\s+(\d+)\b", re.IGNORECASE)

KNOWN_BENCHES = {"is", "cg", "ep", "ft", "mg"}  # NPB kernels you have


@dataclass(frozen=True)
class Measurement:
    run_name: str
    source: str
    benchmark: str
    threads: int
    dynamic: bool
    program_id: int
    duration_ms: int
    mops_total: float | None
    init_ms: int | None
    mops_per_thread: float | None
    total_threads: int | None
    avail_threads: int | None
    operation_type: str | None
    pid: int | None


def parse_out_file(path: Path, benchmark: str, run_name: str, source: str) -> list[Measurement]:
    m = OUT_FILENAME_RE.match(path.name)
    if not m:
        return []
    if m.group("bench").lower() != benchmark.lower():
        return []

    threads = int(m.group("threads"))
    dynamic = m.group("dynamic").lower() == "true"
    program_id = int(m.group("program"))

    duration_ms: int | None = None
    mops_total: float | None = None
    init_ms: int | None = None
    mops_per_thread: float | None = None
    total_threads: int | None = None
    avail_threads: int | None = None
    operation_type: str | None = None
    pid: int | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if pid is None:
            p_match = PID_RE.search(line.strip())
            if p_match:
                pid = int(p_match.group(1))
                continue
        t_match = TIME_SECONDS_RE.search(line.strip())
        if t_match:
            seconds = float(t_match.group(1))
            duration_ms = int(round(seconds * 1000))
            continue
        m_match = MOPS_TOTAL_RE.search(line.strip())
        if m_match:
            mops_total = float(m_match.group(1))
            continue
        mp_match = MOPS_THREAD_RE.search(line.strip())
        if mp_match:
            mops_per_thread = float(mp_match.group(1))
            continue
        tt_match = TOTAL_THREADS_RE.search(line.strip())
        if tt_match:
            total_threads = int(tt_match.group(1))
            continue
        at_match = AVAIL_THREADS_RE.search(line.strip())
        if at_match:
            avail_threads = int(at_match.group(1))
            continue
        op_match = OP_TYPE_RE.search(line.strip())
        if op_match:
            operation_type = op_match.group(1).strip()
            continue
        i_match = INIT_SECONDS_RE.search(line.strip())
        if i_match:
            seconds = float(i_match.group(1))
            init_ms = int(round(seconds * 1000))

    if duration_ms is None:
        return []

    return [
        Measurement(
            run_name=run_name,
            source=source,
            benchmark=benchmark.upper(),
            threads=threads,
            dynamic=dynamic,
            program_id=program_id,
            duration_ms=duration_ms,
            mops_total=mops_total,
            init_ms=init_ms,
            mops_per_thread=mops_per_thread,
            total_threads=total_threads,
            avail_threads=avail_threads,
            operation_type=operation_type,
            pid=pid,
        )
    ]


def load_benchmark_dir(bench_dir: Path, bench_name: str, run_name: str, source: str) -> pd.DataFrame:
    files = sorted(bench_dir.glob(f"{bench_name}_threads_*_dyn_*_*.out"))
    rows: list[Measurement] = []
    for f in files:
        rows.extend(parse_out_file(f, benchmark=bench_name, run_name=run_name, source=source))

    df = pd.DataFrame([r.__dict__ for r in rows])
    if df.empty:
        return df

    df = df[df["threads"] >= 2].reset_index(drop=True)
    if df.empty:
        return df

    df["mode"] = df["dynamic"].map(lambda d: "dynamic=true" if d else "dynamic=false")
    df = df.sort_values(
        ["source", "run_name", "benchmark", "mode", "threads", "program_id", "duration_ms"]
    ).reset_index(drop=True)

    # run index per (run_name, benchmark, mode, threads) — shows "two runs" within the same kernel/thread/mode
    df["rep"] = df.groupby(["run_name", "benchmark", "mode", "threads"]).cumcount() + 1
    return df
