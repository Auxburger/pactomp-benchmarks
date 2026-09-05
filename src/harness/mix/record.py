"""The mixed workload experiment's bookkeeping: iterations.csv, the per-arm
summary the log prints at the end, and the manifest.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ..record import append_rows, write_manifest as _write_manifest
from .config import Config
from .runner import IterationResult
from .schedule import Schedule

ITERATION_COLUMNS = [
    "arm",
    "repeat",
    "job_id",
    "label",
    "algorithm",
    "threads",
    "iteration",
    "start_offset",
    "window_seconds",
    "start_epoch_ms",
    "start_since_arm_ms",
    "wall_ms",
    "time_seconds",
    "mops_total",
    "total_threads",
    "avail_threads",
    "overran_window",
    "pid",
    "exit_code",
]


def append_iterations(path: Path, results: "list[IterationResult]") -> None:
    rows = []
    for r in sorted(results, key=lambda r: (r.repeat, r.job_id, r.iteration)):
        row = asdict(r)
        row["overran_window"] = "true" if r.overran_window else "false"
        rows.append(row)
    append_rows(path, ITERATION_COLUMNS, rows)


def _mean(values: "list[float]") -> "float | None":
    return round(sum(values) / len(values), 3) if values else None


def _makespans(results: "list[IterationResult]") -> "list[float]":
    """One makespan per repeat — they are separate runs, not one long timeline."""
    per_repeat: "dict[int, int]" = {}
    for r in results:
        end = r.start_since_arm_ms + r.wall_ms
        per_repeat[r.repeat] = max(per_repeat.get(r.repeat, 0), end)
    return [ms / 1000 for ms in per_repeat.values()]


def summarize_arm(arm: str, results: "list[IterationResult]") -> dict:
    """Throughput and per-iteration cost of one arm — the comparison metrics.

    Iterations completed per job is the headline: both arms get the same time
    windows, so whichever arm finishes more work inside them wins. With
    --repeats the arm ran several times in alternating order; the totals pool
    those runs, which is what cancels drift between the arms.
    """
    per_job: "dict[str, dict]" = {}
    for r in sorted(results, key=lambda r: (r.repeat, r.job_id, r.iteration)):
        entry = per_job.setdefault(
            r.label,
            {"algorithm": r.algorithm, "window_seconds": r.window_seconds, "iterations": 0, "seconds": []},
        )
        entry["iterations"] += 1
        if r.time_seconds is not None:
            entry["seconds"].append(r.time_seconds)

    repeats = len({r.repeat for r in results})
    jobs = {
        label: {
            "algorithm": entry["algorithm"],
            "window_seconds": entry["window_seconds"],
            "iterations": entry["iterations"],
            "iterations_per_repeat": round(entry["iterations"] / max(1, repeats), 3),
            "mean_time_seconds": _mean(entry["seconds"]),
        }
        for label, entry in per_job.items()
    }
    seconds = [r.time_seconds for r in results if r.time_seconds is not None]
    makespans = _makespans(results)
    return {
        "arm": arm,
        "repeats": repeats,
        "iterations": len(results),
        "failed_iterations": sum(1 for r in results if r.exit_code not in (0, None)),
        "makespan_seconds": _mean(makespans),
        "mean_time_seconds": _mean(seconds),
        "mean_total_threads": _mean([float(r.total_threads) for r in results if r.total_threads]),
        "jobs": jobs,
    }


def compare(summaries: "list[dict]") -> "dict | None":
    """drm vs nodrm, once both arms have run."""
    by_arm = {s["arm"]: s for s in summaries}
    drm, nodrm = by_arm.get("drm"), by_arm.get("nodrm")
    if not drm or not nodrm or not nodrm["iterations"]:
        return None

    out = {
        "iterations_drm": drm["iterations"],
        "iterations_nodrm": nodrm["iterations"],
        "iterations_gain_pct": round(
            100 * (drm["iterations"] - nodrm["iterations"]) / nodrm["iterations"], 2
        ),
    }
    if drm["mean_time_seconds"] and nodrm["mean_time_seconds"]:
        out["mean_time_speedup"] = round(nodrm["mean_time_seconds"] / drm["mean_time_seconds"], 3)
    return out


def write_summary(path: Path, schedule: Schedule, summaries: "list[dict]", order: "list[str]") -> dict:
    payload = {
        "seed": schedule.seed,
        "arm_order": order,
        "schedule_span_seconds": round(schedule.span, 3),
        "arms": summaries,
        "comparison": compare(summaries),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def write_manifest(cfg: Config, path: Path, schedule: Schedule, cpus: "list[int]", rm_cpu: int) -> None:
    _write_manifest(
        path,
        {
            "experiment": "mix",
            "seed": schedule.seed,
            "schedule": schedule.to_dict(),
            "workload_cpus": cpus,
            "domain_cpus_requested": cfg.domain_cpus,
            "domain_cpus_actual": len(cpus),
            "coordinator_cpu": rm_cpu,
            "paths": {
                "npb_bin": str(cfg.npb_bin),
                "pomp_bin": str(cfg.drm_binary),
            },
            "config": {
                k: (str(v) if isinstance(v, Path) else v)
                for k, v in asdict(cfg).items()
            },
        },
    )
