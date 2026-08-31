"""Run metadata written by the experiment scripts.

`meta.txt` records when each benchmark started (test_all.sh), and the SLURM
stdout log records which CPU pool each worker owned per thread count. Both are
context for the CPU-utilisation figure rather than measurements of their own.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

_START_RE = re.compile(r"start (.+?) host")
_RUN_RE = re.compile(r"==== t=(\d+) r=(\d+)")
_ALG_RE = re.compile(r"alg=(\w+) start (.+)")
_POOL_RE = re.compile(r"t=(\d+) \| A_pool: \[([^\]]*)\] \| B_pool: \[([^\]]*)\]")
_TIMESTAMP = "%a %b %d %H:%M:%S %Z %Y"


def _parse_ts(text: str) -> "datetime | None":
    try:
        return datetime.strptime(text.strip(), _TIMESTAMP)
    except ValueError:
        return None


def parse_meta(path: Path) -> "list[dict]":
    """Parse a worker's meta.txt → job start and per-benchmark start events.

    Each alg_start event carries the thread count and repetition it belongs to,
    from the "==== t=<t> r=<r> ====" line above it.
    """
    events: "list[dict]" = []
    thread_count: "int | None" = None
    repetition: "int | None" = None

    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.strip()

            m = _START_RE.match(line)
            if m:
                ts = _parse_ts(m.group(1))
                if ts:
                    events.append({"ts": ts, "event": "start", "t": None, "r": None, "alg": None})
                continue

            m = _RUN_RE.match(line)
            if m:
                thread_count, repetition = int(m.group(1)), int(m.group(2))
                continue

            m = _ALG_RE.match(line)
            if m:
                ts = _parse_ts(m.group(2))
                if ts:
                    events.append({
                        "ts": ts,
                        "event": "alg_start",
                        "t": thread_count,
                        "r": repetition,
                        "alg": m.group(1),
                    })

    return events


def _expand(cpu_list: str) -> "list[int]":
    cpus: "list[int]" = []
    for part in cpu_list.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            cpus.extend(range(int(lo), int(hi) + 1))
        else:
            try:
                cpus.append(int(part))
            except ValueError:
                pass
    return cpus


def parse_cpu_splits(path: Path) -> "dict[int, dict[str, list[int]]]":
    """Parse the SLURM log → {thread_count: {partition: cpus}}.

    A1/A2 get disjoint halves of the A pool, as the DRM assigns them; B1/B2
    share the whole B pool, since they are uncoordinated and oversubscribe it.
    """
    splits: "dict[int, dict[str, list[int]]]" = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            m = _POOL_RE.search(line)
            if not m:
                continue
            threads = int(m.group(1))
            a_pool = _expand(m.group(2))
            b_pool = _expand(m.group(3))
            half = threads // 2
            splits[threads] = {
                "A1": a_pool[:half],
                "A2": a_pool[half : half * 2],
                "B1": b_pool,
                "B2": b_pool,
            }
    return splits
