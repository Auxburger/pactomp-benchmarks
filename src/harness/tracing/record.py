"""The tracing sweep's own bookkeeping: timings.csv rows and the manifest."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

from ..record import append_rows, write_manifest as _write_manifest
from .config import Config
from .runner import ProcResult

TIMINGS_COLUMNS = [
    "run_name",
    "benchmark",
    "threads",
    "dynamic",
    "program_id",
    "cpus",
    "drm",
    "wall_ms",
    "time_seconds",
    "total_threads",
    "avail_threads",
    "pid",
    "exit_code",
]


def append_timings(path: Path, results: "list[ProcResult]") -> None:
    rows = []
    for r in results:
        row = asdict(r)
        row["dynamic"] = "true" if r.dynamic else "false"
        row["drm"] = "true" if r.drm else "false"
        rows.append(row)
    append_rows(path, TIMINGS_COLUMNS, rows)


def write_manifest(
    cfg: Config,
    path: Path,
    compile_cmd: "list[str] | None",
    allowed: "list[int]",
) -> None:
    _write_manifest(
        path,
        {
            "experiment": "tracing",
            "compile_command": compile_cmd,
            "source_sha256": hashlib.sha256(cfg.source.read_bytes()).hexdigest(),
            "allowed_cpus": allowed,
            "paths": {
                "pomp_bin": str(cfg.drm_binary),
                "binary": str(cfg.binary),
                "source": str(cfg.source),
            },
            "config": {
                **{k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(cfg).items()},
                "modes": ["true" if m else "false" for m in cfg.modes],
            },
        },
    )
