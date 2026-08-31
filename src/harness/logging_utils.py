"""Timestamped console output and the shared CPU-list formatting."""

from __future__ import annotations

from datetime import datetime


def now() -> str:
    """Timestamp in the format the old shell scripts wrote with date(1)."""
    return datetime.now().strftime("%a %d %b %Y %H:%M:%S %Z").strip()


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def fmt_cpus(cpus: "list[int] | None") -> str:
    return ",".join(str(c) for c in cpus) if cpus else "all"
