"""Incremental builds: skip a report whose outputs are newer than its inputs."""

from __future__ import annotations

from pathlib import Path


def max_mtime(paths: list[Path]) -> float:
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


def up_to_date(inputs: list[Path], output_dir: Path) -> bool:
    """True if output_dir has *.html files and all are newer than every input file."""
    if not output_dir.exists():
        return False
    outputs = list(output_dir.glob("*.html"))
    if not outputs:
        return False
    oldest_out = min(p.stat().st_mtime for p in outputs)
    return max_mtime(inputs) <= oldest_out
