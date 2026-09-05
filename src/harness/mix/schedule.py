"""The seeded schedule: which benchmark starts when, and for how long.

The schedule is drawn once from `random.Random(seed)` and then replayed for
every arm, so the DRM arm and the uncoordinated arm face the identical
workload: same algorithms, same start offsets, same time windows. A schedule is
written to `schedule.json` next to the results and can be replayed verbatim
with `--schedule`, which makes a run reproducible even if the drawing code ever
changes.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

SCHEDULE_VERSION = 1


@dataclass(frozen=True)
class Job:
    """One concurrent workload: `algorithm`, started at `start_offset`,
    re-running its benchmark until `duration` seconds have passed."""

    job_id: int
    algorithm: str
    start_offset: float
    duration: float
    threads: int

    @property
    def label(self) -> str:
        return f"J{self.job_id:02d}_{self.algorithm}"


@dataclass(frozen=True)
class Schedule:
    seed: int
    jobs: "list[Job]"

    @property
    def span(self) -> float:
        """Wall-clock length of the schedule, ignoring benchmark overrun."""
        return max((j.start_offset + j.duration for j in self.jobs), default=0.0)

    def to_dict(self) -> dict:
        return {
            "version": SCHEDULE_VERSION,
            "seed": self.seed,
            "jobs": [asdict(j) for j in self.jobs],
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    def table(self) -> "list[str]":
        lines = [f"{'job':<10} {'alg':<4} {'start':>7} {'until':>7} {'window':>7} {'threads':>7}"]
        for j in self.jobs:
            lines.append(
                f"{j.label:<10} {j.algorithm:<4} {j.start_offset:>7.1f} "
                f"{j.start_offset + j.duration:>7.1f} {j.duration:>7.1f} {j.threads:>7d}"
            )
        return lines


class ScheduleError(Exception):
    """A schedule file that cannot be replayed."""


def generate(
    seed: int,
    n_jobs: int,
    algorithms: "list[str]",
    offset_range: "tuple[float, float]",
    duration_range: "tuple[float, float]",
    threads: int,
) -> Schedule:
    """Draw `n_jobs` workloads: random algorithm, random offset, random window.

    Offsets are shifted so the earliest job starts at 0 — otherwise a schedule
    would open with dead time that says nothing about either arm — and the jobs
    are numbered in start order so the logs read chronologically.
    """
    if n_jobs < 1:
        raise ScheduleError(f"n_jobs={n_jobs} too small")
    if not algorithms:
        raise ScheduleError("no algorithms to draw from")

    rng = random.Random(seed)
    draws = []
    for _ in range(n_jobs):
        # One draw per field, in a fixed order, so a seed always yields the
        # same schedule regardless of how many jobs are asked for.
        algorithm = rng.choice(algorithms)
        offset = rng.uniform(*offset_range)
        duration = rng.uniform(*duration_range)
        draws.append((offset, algorithm, duration))

    draws.sort(key=lambda d: (d[0], d[1]))
    first = draws[0][0]
    jobs = [
        Job(
            job_id=index,
            algorithm=algorithm,
            start_offset=round(offset - first, 3),
            duration=round(duration, 3),
            threads=threads,
        )
        for index, (offset, algorithm, duration) in enumerate(draws, start=1)
    ]
    return Schedule(seed=seed, jobs=jobs)


def load(path: Path) -> Schedule:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScheduleError(f"cannot read schedule {path}: {exc}") from exc

    version = payload.get("version")
    if version != SCHEDULE_VERSION:
        raise ScheduleError(f"schedule {path} has version {version}, expected {SCHEDULE_VERSION}")
    raw_jobs = payload.get("jobs") or []
    if not raw_jobs:
        raise ScheduleError(f"schedule {path} contains no jobs")

    fields = {f for f in Job.__dataclass_fields__}
    jobs = []
    for raw in raw_jobs:
        missing = fields - set(raw)
        if missing:
            raise ScheduleError(f"schedule {path} job is missing {sorted(missing)}")
        jobs.append(
            Job(
                job_id=int(raw["job_id"]),
                algorithm=str(raw["algorithm"]),
                start_offset=float(raw["start_offset"]),
                duration=float(raw["duration"]),
                threads=int(raw["threads"]),
            )
        )
    return Schedule(seed=int(payload.get("seed", -1)), jobs=jobs)
