"""Tracing microbenchmark runs (data/tracing/<jobid>/) → output/tracing/."""

from __future__ import annotations

import re
from pathlib import Path

from .freshness import up_to_date
from .npb import process_group


def process_tracing_runs(
    tracing_dir: Path,
    out_dir: Path,
    show_raw: bool,
    static: bool,
    combined: bool,
) -> None:
    """Plot the tracing microbenchmark runs as their own group.

    Layout is data/tracing/<jobid>/run_<n>/<bench>/, one level deeper than the
    dual experiment, so the job id becomes the source label.
    """
    run_dirs: list[tuple[str, Path]] = []
    for job_dir in sorted(p for p in tracing_dir.iterdir() if p.is_dir()):
        run_dirs.extend(
            (f"tracing/{job_dir.name}", p)
            for p in sorted(job_dir.iterdir())
            if p.is_dir() and re.fullmatch(r"run_\d+", p.name.lower())
        )

    if not run_dirs:
        print(f"No tracing runs found under {tracing_dir}.")
        return

    if up_to_date([p for _, p in run_dirs], out_dir / "tracing"):
        print("Group tracing: up to date, skipping.")
        return

    process_group(
        "tracing",
        run_dirs,
        out_dir=out_dir,
        show_raw=show_raw,
        static=static,
        combined=combined,
    )
