from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_FILENAME_RE = re.compile(r"^(?P<alg>[a-z]+)_t(?P<t>\d+)_off(?P<offset>\d+)_(?P<worker>[AB][12])\.log$")
_HEADER_META_RE = re.compile(r"#\s*label=(\S+)\s+dyn=(\S+)\s+t=(\d+)\s+alg=(\S+)")
_RM_GRANT_RE = re.compile(r"^(?:\[(\d+)\]\s+)?Granted (\d+) threads to pid (\d+) \(CPUs (\d+)\+(\d+)\)")
_DRM_PIN_RE = re.compile(r"\[DRM-pin\]\s+pid=(\d+)\s+tid=(\d+)\s+assigned=(\d+)-(\d+)\s+running_on=(\d+)")


def parse_staggered_log(path: Path) -> pd.DataFrame | None:
    """Parse one staggered worker log file.

    Returns a DataFrame with columns:
        alg, t, offset, worker, dyn, iter, start_epoch_ms, duration_ms, duration_sec
    or None if the file cannot be parsed.
    """
    m = _FILENAME_RE.match(path.name)
    if not m:
        return None

    alg = m.group("alg").upper()
    t = int(m.group("t"))
    offset = int(m.group("offset"))
    worker = m.group("worker")

    rows: list[dict] = []
    dyn: str | None = None

    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#"):
                hm = _HEADER_META_RE.search(line)
                if hm:
                    dyn = hm.group(2)
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                it = int(parts[0])
                start_ms = int(parts[1])
                dur_ms = int(parts[2])
                dur_sec = float(parts[3]) if len(parts) >= 4 and parts[3] != "NA" else dur_ms / 1000
            except ValueError:
                continue
            rows.append({
                "alg": alg,
                "t": t,
                "offset": offset,
                "worker": worker,
                "dyn": dyn or ("true" if worker.startswith("A") else "false"),
                "iter": it,
                "start_epoch_ms": start_ms,
                "duration_ms": dur_ms,
                "duration_sec": dur_sec,
            })

    if not rows:
        return None
    return pd.DataFrame(rows)


def load_staggered_group(directory: Path, alg: str, t: int, offset: int) -> pd.DataFrame:
    """Load all four worker logs for one (alg, t, offset) group into a single DataFrame."""
    frames = []
    for worker in ("A1", "A2", "B1", "B2"):
        fname = f"{alg.lower()}_t{t}_off{offset}_{worker}.log"
        df = parse_staggered_log(directory / fname)
        if df is not None:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    # Compute elapsed seconds from the earliest start across all workers
    t0 = combined["start_epoch_ms"].min()
    combined["elapsed_sec"] = (combined["start_epoch_ms"] - t0) / 1000.0
    return combined


def load_staggered_grants(directory: Path, alg: str, t: int, offset: int) -> pd.DataFrame:
    """Per-DRM-grant DataFrame with wall-clock timestamps.

    Supports two rm.log formats:
    - New: `[epoch_ms] Granted N threads to pid P (CPUs s+c)` — uses real timestamps.
    - Old: no timestamps — linearly interpolates within each A-side process window.

    Returns DataFrame with columns:
        worker, iter, grant_idx, epoch_ms, elapsed_sec, threads_granted, cpu_start, cpu_count
    or an empty DataFrame if the rm.log is missing.
    """
    rm_path = directory / f"{alg.lower()}_t{t}_off{offset}_rm.log"
    if not rm_path.exists():
        return pd.DataFrame()

    # --- parse rm.log ---------------------------------------------------------
    pid_order: list[int] = []
    grants_per_pid: dict[int, list[tuple]] = {}  # pid -> [(epoch_ms|None, threads, cpu_start, cpu_count)]
    has_timestamps = False

    with open(rm_path, errors="replace") as f:
        for line in f:
            m = _RM_GRANT_RE.match(line.strip())
            if m:
                epoch_ms = int(m.group(1)) if m.group(1) else None
                threads, pid = int(m.group(2)), int(m.group(3))
                cpu_start, cpu_count = int(m.group(4)), int(m.group(5))
                if epoch_ms is not None:
                    has_timestamps = True
                if pid not in grants_per_pid:
                    grants_per_pid[pid] = []
                    pid_order.append(pid)
                grants_per_pid[pid].append((epoch_ms, threads, cpu_start, cpu_count))

    if not pid_order:
        return pd.DataFrame()

    # --- load A-side iterations sorted by start time --------------------------
    a_iters: list[dict] = []
    for worker in ("A1", "A2"):
        fname = f"{alg.lower()}_t{t}_off{offset}_{worker}.log"
        df_w = parse_staggered_log(directory / fname)
        if df_w is None:
            continue
        for _, row in df_w.iterrows():
            a_iters.append({
                "worker": worker,
                "iter": int(row["iter"]),
                "start_epoch_ms": int(row["start_epoch_ms"]),
                "duration_ms": int(row["duration_ms"]),
            })
    if not a_iters:
        return pd.DataFrame()

    a_iters.sort(key=lambda x: x["start_epoch_ms"])
    t0_ms = a_iters[0]["start_epoch_ms"]

    rows: list[dict] = []

    if has_timestamps:
        # --- new format: use real grant timestamps ----------------------------
        # Each staggered iteration is a separate process (new pid per run).
        # After A2 joins, A1 and A2 pids appear interleaved in the rm.log with
        # overlapping iteration windows, so matching a single timestamp is
        # ambiguous.  Instead, assign each pid to the (worker, iter) whose window
        # contains the most of that pid's grant timestamps (majority vote).
        # Pids are processed in connection order; taken prevents double-assignment.
        TOLERANCE_MS = 500

        pid_to_wi: dict[int, tuple[str, int]] = {}
        taken: dict[str, set] = {}

        for pid in pid_order:
            grant_times = [g[0] for g in grants_per_pid[pid] if g[0] is not None]
            if not grant_times:
                continue

            best_worker, best_iter, best_count = "A1", 0, -1
            for it in a_iters:
                if it["iter"] in taken.get(it["worker"], set()):
                    continue
                lo = it["start_epoch_ms"] - TOLERANCE_MS
                hi = it["start_epoch_ms"] + it["duration_ms"] + TOLERANCE_MS
                count = sum(1 for ms in grant_times if lo <= ms <= hi)
                if count > best_count:
                    best_count, best_worker, best_iter = count, it["worker"], it["iter"]

            pid_to_wi[pid] = (best_worker, best_iter)
            taken.setdefault(best_worker, set()).add(best_iter)

        for pid in pid_order:
            worker, matched_iter = pid_to_wi.get(pid, ("A1", 0))
            for g_idx, (epoch_ms, threads, cpu_start, cpu_count) in enumerate(grants_per_pid[pid]):
                if epoch_ms is None:
                    continue
                rows.append({
                    "worker": worker,
                    "iter": matched_iter,
                    "grant_idx": g_idx,
                    "cpu_start": cpu_start,
                    "cpu_count": cpu_count,
                    "epoch_ms": float(epoch_ms),
                    "elapsed_sec": (epoch_ms - t0_ms) / 1000.0,
                    "threads_granted": threads,
                })
    else:
        # --- old format: interpolate within each A-side process window --------
        # k-th unique pid ↔ k-th A-side process by start time (one iter per process).
        for pid, iter_info in zip(pid_order, a_iters):
            grants = grants_per_pid[pid]
            n = len(grants)
            start_ms = iter_info["start_epoch_ms"]
            dur_ms = iter_info["duration_ms"]
            for g_idx, (_, threads, cpu_start, cpu_count) in enumerate(grants):
                frac = g_idx / max(n - 1, 1)
                grant_ms = start_ms + frac * dur_ms
                rows.append({
                    "worker": iter_info["worker"],
                    "iter": iter_info["iter"],
                    "grant_idx": g_idx,
                    "cpu_start": cpu_start,
                    "cpu_count": cpu_count,
                    "epoch_ms": grant_ms,
                    "elapsed_sec": (grant_ms - t0_ms) / 1000.0,
                    "threads_granted": threads,
                })

    return pd.DataFrame(rows)


def parse_drm_pin_log(path: Path) -> pd.DataFrame:
    """Parse a `{alg}_t{t}_off{offset}_{worker}_drm.log` file.

    Each line has the form:
        [DRM-pin] pid=<pid> tid=<tid> assigned=<base>-<top> running_on=<cpu>

    Returns a DataFrame with columns: pid, tid, cpu_base, cpu_top, running_on, assigned.
    """
    rows: list[dict] = []
    with open(path, errors="replace") as f:
        for line in f:
            m = _DRM_PIN_RE.search(line.strip())
            if m:
                rows.append({
                    "pid": int(m.group(1)),
                    "tid": int(m.group(2)),
                    "cpu_base": int(m.group(3)),
                    "cpu_top": int(m.group(4)),
                    "running_on": int(m.group(5)),
                    "assigned": f"{m.group(3)}-{m.group(4)}",
                })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def load_staggered_drm_pins(directory: Path, alg: str, t: int, offset: int) -> pd.DataFrame:
    """Load `_drm.log` files for A-side workers (A1 and A2) into one DataFrame.

    Adds a `worker` column. Returns an empty DataFrame if no files are found.
    """
    frames: list[pd.DataFrame] = []
    for worker in ("A1", "A2"):
        fname = f"{alg.lower()}_t{t}_off{offset}_{worker}_drm.log"
        p = directory / fname
        if not p.exists():
            continue
        df = parse_drm_pin_log(p)
        if not df.empty:
            df["worker"] = worker
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def discover_staggered_groups(directory: Path) -> list[tuple[str, int, int]]:
    """Return sorted list of (alg, t, offset) tuples found in directory."""
    groups: set[tuple[str, int, int]] = set()
    for p in directory.glob("*_A1.log"):
        m = _FILENAME_RE.match(p.name)
        if m:
            groups.add((m.group("alg").upper(), int(m.group("t")), int(m.group("offset"))))
    return sorted(groups)
