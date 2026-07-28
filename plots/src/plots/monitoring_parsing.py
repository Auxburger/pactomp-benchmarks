from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd


# ── rm.log patterns ────────────────────────────────────────────────────────────

_STARTING_POOL_RE = re.compile(
    r"^Starting DRM at (.+?),\s*capacity=(\d+),\s*cpu_pool="
)
_STOPPED_RE = re.compile(r"^DRM stopped at (.+?),\s*was capacity=\d+")
_GRANTED_CPU_RE = re.compile(
    r"^(?:\[(\d+)\]\s+)?Granted (\d+) threads to pid (\d+) \(CPUs (\d+)\+(\d+)\)"
)

# ── pidstat patterns ───────────────────────────────────────────────────────────

_DATE_HEADER_RE = re.compile(r"(\d{2}/\d{2}/\d{2,4})")
_BENCH_CMD_RE = re.compile(r"([a-z]+)\.C\.x$")

_PROC_NAMES = ["Process A", "Process B"]


def _parse_drm_date(s: str) -> datetime | None:
    s = s.strip()
    for tz, offset in (("CEST", "+0200"), ("CET", "+0100")):
        if tz in s:
            s = s.replace(tz, offset)
            break
    for fmt in (
        "%a %b %d %H:%M:%S +0200 %Y",
        "%a %b %d %H:%M:%S +0100 %Y",
        "%a %b  %d %H:%M:%S +0200 %Y",
        "%a %b  %d %H:%M:%S +0100 %Y",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def parse_rm_log(path: Path) -> pd.DataFrame:
    """Parse rm.log → DataFrame of DRM grant events (cpu_pool format only).

    Columns: capacity, process, pid, threads_granted, cpu_start, cpu_count,
             grant_idx, elapsed_sec

    elapsed_sec uses real timestamps from `[epoch_ms]` prefixes when present
    (new server.rs format); falls back to linear interpolation within each
    capacity block for older logs without timestamps.
    """
    records: list[dict] = []
    current_capacity: int | None = None
    current_start: datetime | None = None
    block: list[dict] = []
    pid_labels: dict[int, str] = {}

    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()

            # New capacity block start (only cpu_pool format)
            if _STARTING_POOL_RE.match(line):
                cap_m = re.search(r"capacity=(\d+)", line)
                date_m = _STARTING_POOL_RE.match(line)
                if date_m and cap_m:
                    current_start = _parse_drm_date(date_m.group(1))
                    current_capacity = int(cap_m.group(1))
                    block = []
                    pid_labels = {}
                continue

            # End of block – compute elapsed_sec and flush
            m = _STOPPED_RE.match(line)
            if m and current_capacity is not None:
                n = len(block)
                has_ts = any(rec.get("_epoch_ms") is not None for rec in block)
                if has_ts:
                    # Use real timestamps: elapsed from first grant in block
                    first_ms = next(
                        rec["_epoch_ms"] for rec in block if rec.get("_epoch_ms") is not None
                    )
                    for rec in block:
                        rec["elapsed_sec"] = (
                            (rec["_epoch_ms"] - first_ms) / 1000.0
                            if rec.get("_epoch_ms") is not None
                            else 0.0
                        )
                        del rec["_epoch_ms"]
                        records.append(rec)
                else:
                    # Interpolate from block start/end dates
                    stop_time = _parse_drm_date(m.group(1))
                    block_dur = (
                        (stop_time - current_start).total_seconds()
                        if current_start and stop_time
                        else None
                    )
                    for idx, rec in enumerate(block):
                        rec.pop("_epoch_ms", None)
                        rec["elapsed_sec"] = (
                            (idx / max(n - 1, 1)) * block_dur
                            if block_dur is not None
                            else float(idx)
                        )
                        records.append(rec)
                block = []
                current_capacity = None
                current_start = None
                continue

            # Grant line with CPU info
            m = _GRANTED_CPU_RE.match(line)
            if m and current_capacity is not None:
                epoch_ms = int(m.group(1)) if m.group(1) else None
                threads = int(m.group(2))
                pid = int(m.group(3))
                cpu_start = int(m.group(4))
                cpu_count = int(m.group(5))
                if pid not in pid_labels:
                    idx = len(pid_labels)
                    pid_labels[pid] = (
                        _PROC_NAMES[idx] if idx < len(_PROC_NAMES) else f"Process {idx + 1}"
                    )
                block.append({
                    "capacity": current_capacity,
                    "pid": pid,
                    "process": pid_labels[pid],
                    "threads_granted": threads,
                    "cpu_start": cpu_start,
                    "cpu_count": cpu_count,
                    "grant_idx": len(block),
                    "_epoch_ms": epoch_ms,
                })

    return pd.DataFrame(records)


def compute_inter_grant_times(df: pd.DataFrame) -> pd.DataFrame:
    """From parse_rm_log output, compute time between consecutive grants per process.

    Returns DataFrame with columns: capacity, process, inter_grant_sec, grant_idx.
    """
    rows: list[dict] = []
    for (cap, proc), grp in df.groupby(["capacity", "process"]):
        grp = grp.sort_values("grant_idx").reset_index(drop=True)
        for i in range(1, len(grp)):
            dt = grp.loc[i, "elapsed_sec"] - grp.loc[i - 1, "elapsed_sec"]
            rows.append({
                "capacity": cap,
                "process": proc,
                "inter_grant_sec": dt,
                "grant_idx": int(grp.loc[i, "grant_idx"]),
            })
    return pd.DataFrame(rows)


def parse_pidstat(path: Path) -> pd.DataFrame:
    """Parse pidstat -u -t output → tidy DataFrame of benchmark thread CPU placements.

    Columns: ts, pid, tid, cpu, pct_cpu, command, benchmark, worker_count, t_inferred.

    worker_count  – number of openmp_worker threads seen under this TGID in the
                    same 5-second sample (for process-level rows only).
    t_inferred    – OMP_NUM_THREADS that was configured for this sample window.
                    Derived from the maximum (worker_count + 1) across all
                    benchmark processes at the same timestamp: non-DRM processes
                    use all t threads, so max(workers + 1) == t regardless of
                    whether a given process is DRM-managed.
    """
    records: list[dict] = []
    # worker counting: tracks workers per (ts_str, tgid) as we stream the file
    worker_counts: dict[tuple, int] = {}
    date_str: str | None = None
    current_tgid: int | None = None
    current_benchmark: str | None = None
    current_ts_str: str | None = None

    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip()

            if line.startswith("Linux"):
                m = _DATE_HEADER_RE.search(line)
                if m:
                    date_str = m.group(1)
                continue

            if not line or "UID" in line:
                continue

            parts = line.split()
            if len(parts) < 10:
                continue

            raw_cmd = parts[-1]
            command = raw_cmd.lstrip("|_")
            bench_m = _BENCH_CMD_RE.search(command)
            is_bench = bench_m is not None
            is_worker = command == "openmp_worker"

            if not is_bench and not is_worker:
                continue

            if not date_str:
                continue

            ts_str = parts[0]
            try:
                ts = datetime.strptime(f"{date_str} {ts_str}", "%m/%d/%y %H:%M:%S")
            except ValueError:
                continue

            try:
                tgid_s = parts[2]
                tid_s = parts[3]
                pct_cpu = float(parts[-3])
                cpu = int(parts[-2])
            except (ValueError, IndexError):
                continue

            if is_bench and tgid_s != "-":
                # Process-level row – start tracking this TGID
                current_tgid = int(tgid_s)
                current_benchmark = bench_m.group(1).upper()
                current_ts_str = ts_str
                records.append({
                    "ts": ts,
                    "parent_tgid": current_tgid,
                    "tid": None,
                    "cpu": cpu,
                    "pct_cpu": pct_cpu,
                    "command": command,
                    "benchmark": current_benchmark,
                    "_ts_str": ts_str,
                })
            elif is_worker and current_tgid is not None:
                # Worker thread – count it and record with parent's benchmark
                key = (current_ts_str, current_tgid)
                worker_counts[key] = worker_counts.get(key, 0) + 1
                records.append({
                    "ts": ts,
                    "parent_tgid": current_tgid,
                    "tid": int(tid_s) if tid_s != "-" else None,
                    "cpu": cpu,
                    "pct_cpu": pct_cpu,
                    "command": command,
                    "benchmark": current_benchmark,
                    "_ts_str": ts_str,
                })

    df = pd.DataFrame(records)
    if df.empty:
        return df

    # Attach worker_count only to process-level rows (tid is NaN/None)
    import pandas as _pd
    df["worker_count"] = df.apply(
        lambda r: worker_counts.get((r["_ts_str"], r["parent_tgid"]), 0)
        if _pd.isna(r["tid"]) else 0,
        axis=1,
    )
    df = df.drop(columns=["_ts_str"])

    # Infer t per timestamp from process-level rows only
    ts_max_workers = (
        df[df["tid"].isna()].groupby("ts")["worker_count"].max().rename("_max_workers")
    )
    df = df.join(ts_max_workers, on="ts")
    # Snap to known t values {2,4,8,16,32}; t_inferred=1 happens when only
    # DRM-managed (serial) processes are visible in a window → round up to 2.
    _KNOWN_T = [2, 4, 8, 16, 32]
    def _snap_t(v: int) -> int:
        return min(_KNOWN_T, key=lambda x: (abs(x - v), x))
    df["t_inferred"] = (df["_max_workers"] + 1).apply(_snap_t)
    df = df.drop(columns=["_max_workers"])

    # Classify each tgid as DRM-managed (dynamic=true).
    # Primary: worker-count evidence — DRM gives t/2 threads, so the process
    # is DRM-managed if it ever shows worker_count in [t/4-1, t/2+1].
    proc_mask = df["tid"].isna()
    proc_rows = df[proc_mask].copy()
    drm_tgids = set(
        proc_rows[
            (proc_rows["worker_count"] + 1 >= proc_rows["t_inferred"] // 4)
            & (proc_rows["worker_count"] + 1 <= proc_rows["t_inferred"] // 2 + 1)
        ]["parent_tgid"].unique()
    )

    # CPU-domain classification overrides worker-count where they conflict.
    # The two NUMA domains are always well-separated in physical CPU numbers
    # (e.g. A-domain CPUs 1–32, B-domain CPUs 56–87), so the midpoint between
    # the global min and max per-tgid median CPU gives a reliable threshold.
    # A-domain processes are always DRM-managed; B-domain are never DRM —
    # this also fixes t=2 where both groups look identical by thread count.
    tgid_median_cpu = proc_rows.groupby("parent_tgid")["cpu"].median()
    if len(tgid_median_cpu) >= 2:
        cpu_threshold = (tgid_median_cpu.min() + tgid_median_cpu.max()) / 2
        a_domain_tgids = set(tgid_median_cpu[tgid_median_cpu < cpu_threshold].index)
        b_domain_tgids = set(tgid_median_cpu[tgid_median_cpu >= cpu_threshold].index)
        drm_tgids = (drm_tgids | a_domain_tgids) - b_domain_tgids

    df["dynamic"] = df["parent_tgid"].map(
        lambda tgid: "true" if tgid in drm_tgids else "false"
    )

    return df


def parse_drm_blocks(path: Path) -> list[tuple[datetime, datetime, int]]:
    """Parse rm.log → list of (start, end, capacity) for each DRM capacity block."""
    blocks: list[tuple[datetime, datetime, int]] = []
    current_start: datetime | None = None
    current_cap: int | None = None

    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            m = _STARTING_POOL_RE.match(line)
            if m:
                cap_m = re.search(r"capacity=(\d+)", line)
                if cap_m:
                    current_start = _parse_drm_date(m.group(1))
                    current_cap = int(cap_m.group(1))
            m = _STOPPED_RE.match(line)
            if m and current_start is not None and current_cap is not None:
                end_time = _parse_drm_date(m.group(1))
                if end_time is not None:
                    blocks.append((current_start, end_time, current_cap))
                current_start = None
                current_cap = None

    return blocks
