"""Mixed workload runs: the seeded schedule and what actually ran.

`iterations.csv` records one row per benchmark process — when it started
relative to its arm, how long it took, and the thread grant it saw. The
schedule that produced it lives in `schedule.json`, so the planned window and
the realised execution can be drawn against each other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ARMS = ("drm", "nodrm")
ARM_LABELS = {"drm": "Coordinator enabled", "nodrm": "Unmanaged"}


def load_mix_schedule(job_dir: Path) -> pd.DataFrame:
    """The seeded schedule: one row per job, in start order."""
    payload = json.loads((job_dir / "schedule.json").read_text(encoding="utf-8"))
    jobs = pd.DataFrame(payload["jobs"])
    if jobs.empty:
        return jobs
    jobs["label"] = [
        f"J{int(job_id):02d}_{algorithm}"
        for job_id, algorithm in zip(jobs["job_id"], jobs["algorithm"])
    ]
    jobs["window_end"] = jobs["start_offset"] + jobs["duration"]
    return jobs.sort_values("start_offset").reset_index(drop=True)


def load_mix_iterations(job_dir: Path) -> pd.DataFrame:
    """Every benchmark process of every arm and repeat, with derived times.

    Adds `start_sec` / `end_sec` (relative to the arm start) and `window_end`,
    so an iteration can be placed against the window it belongs to. Wall time
    is what bounds the process, not the NPB-reported `time_seconds`, which
    excludes startup.
    """
    df = pd.read_csv(job_dir / "iterations.csv")
    if df.empty:
        return df
    df["start_sec"] = df["start_since_arm_ms"] / 1000.0
    df["end_sec"] = df["start_sec"] + df["wall_ms"] / 1000.0
    df["window_end"] = df["start_offset"] + df["window_seconds"]
    df["overran_window"] = df["overran_window"].astype(str).str.lower() == "true"
    return df


def mix_concurrency(df: pd.DataFrame) -> pd.DataFrame:
    """Realised concurrency: how many benchmark processes ran at each instant.

    Returns the step points (`sec`, `running`) of one arm and repeat — pass an
    already filtered frame. Ends at zero so the curve closes.
    """
    if df.empty:
        return pd.DataFrame(columns=["sec", "running"])

    events = [(float(t), 1) for t in df["start_sec"]]
    events += [(float(t), -1) for t in df["end_sec"]]
    events.sort()

    rows: list[dict[str, float]] = []
    running = 0
    for sec, delta in events:
        running += delta
        if rows and rows[-1]["sec"] == sec:
            rows[-1]["running"] = running
        else:
            rows.append({"sec": sec, "running": running})
    return pd.DataFrame(rows)
