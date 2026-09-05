"""The NPB summary block, as every benchmark process prints it on stdout.

Both the tracing microbenchmark (`omp_dyn.c` imitates the block) and the mixed
workload experiment read the same fields back, so the patterns live here rather
than in either experiment's runner.
"""

from __future__ import annotations

import re
from pathlib import Path

# (regex, cast) per field. Every line carries a leading space in NPB's output.
PATTERNS: "dict[str, tuple[re.Pattern, type]]" = {
    "time_seconds": (re.compile(r"^\s*Time in seconds\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE), float),
    "mops_total": (re.compile(r"^\s*Mop/s total\s*=\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE), float),
    "total_threads": (re.compile(r"^\s*Total threads\s*=\s*([0-9]+)", re.IGNORECASE), int),
    "avail_threads": (re.compile(r"^\s*Avail threads\s*=\s*([0-9]+)", re.IGNORECASE), int),
    "pid": (re.compile(r"^\s*PID:\s*([0-9]+)"), int),
}


def parse_summary(text: str) -> dict:
    """First occurrence of each field, None for the ones the text does not carry."""
    found: dict = {key: None for key in PATTERNS}
    for line in text.splitlines():
        for key, (pattern, cast) in PATTERNS.items():
            if found[key] is None:
                match = pattern.match(line)
                if match:
                    found[key] = cast(match.group(1))
    return found


def parse_out_file(path: Path) -> dict:
    return parse_summary(path.read_text(encoding="utf-8", errors="replace"))
