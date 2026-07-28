from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean


THREAD_COUNTS = (2, 4, 8, 16, 32)
KERNELS = ("EP", "FT", "CG")
MODES = ("dynamic=true", "dynamic=false")

_OUT_RE = re.compile(
    r"^(?P<kernel>ep|ft|cg)_threads_(?P<threads>\d+)_"
    r"dyn_(?P<dynamic>true|false)_(?P<process>[12])\.out$"
)
_TIME_RE = re.compile(
    r"^Time in seconds\s*=\s*(?P<seconds>[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Observation:
    run: str
    kernel: str
    threads: int
    mode: str
    process: int
    seconds: float


@dataclass(frozen=True)
class ModelFit:
    kernel: str
    mode: str
    effective_fraction: float
    ci_low: float
    ci_high: float
    rmse_seconds: float
    nrmse_percent: float
    holdout_prediction_seconds: float
    holdout_observed_seconds: float
    holdout_error_percent: float


def load_dual_observations(root: Path) -> list[Observation]:
    observations: list[Observation] = []
    run_dirs = sorted(
        (path for path in root.iterdir() if re.fullmatch(r"run_\d+", path.name)),
        key=lambda path: int(path.name.split("_")[1]),
    )

    for run_dir in run_dirs:
        for kernel_lower in ("ep", "ft", "cg"):
            for path in sorted((run_dir / kernel_lower).glob("*.out")):
                match = _OUT_RE.fullmatch(path.name)
                if match is None:
                    continue

                seconds = None
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                    time_match = _TIME_RE.match(line.strip())
                    if time_match is not None:
                        seconds = float(time_match.group("seconds"))
                        break
                if seconds is None:
                    raise ValueError(f"No benchmark runtime found in {path}")

                dynamic = match.group("dynamic")
                observations.append(
                    Observation(
                        run=run_dir.name,
                        kernel=match.group("kernel").upper(),
                        threads=int(match.group("threads")),
                        mode=f"dynamic={dynamic}",
                        process=int(match.group("process")),
                        seconds=seconds,
                    )
                )

    _validate_observations(observations)
    return observations


def _validate_observations(observations: list[Observation]) -> None:
    runs = sorted({observation.run for observation in observations})
    if len(runs) != 10:
        raise ValueError(f"Expected 10 run groups, found {len(runs)}")

    for run in runs:
        for kernel in KERNELS:
            for threads in THREAD_COUNTS:
                for mode in MODES:
                    cell = [
                        observation
                        for observation in observations
                        if observation.run == run
                        and observation.kernel == kernel
                        and observation.threads == threads
                        and observation.mode == mode
                    ]
                    processes = sorted(observation.process for observation in cell)
                    if processes != [1, 2]:
                        raise ValueError(
                            "Expected process IDs 1 and 2 for "
                            f"{run}, {kernel}, t={threads}, {mode}; found {processes}"
                        )


def _configuration_means(
    observations: list[Observation],
    kernel: str,
    mode: str,
) -> dict[int, float]:
    return {
        threads: mean(
            observation.seconds
            for observation in observations
            if observation.kernel == kernel
            and observation.mode == mode
            and observation.threads == threads
        )
        for threads in THREAD_COUNTS
    }


def fit_effective_fraction(means: dict[int, float], fit_threads=THREAD_COUNTS) -> float:
    baseline = means[2]
    numerator = 0.0
    denominator = 0.0
    for threads in fit_threads:
        pool_multiplier = threads / 2.0
        x = baseline * (1.0 - 1.0 / pool_multiplier)
        y = means[threads] - baseline / pool_multiplier
        numerator += x * y
        denominator += x * x
    if denominator == 0.0:
        raise ValueError("At least one scaling point beyond t=2 is required")
    return numerator / denominator


def predict_runtime(baseline_seconds: float, pool_multiplier: float, fraction: float) -> float:
    return baseline_seconds * (
        fraction + (1.0 - fraction) / pool_multiplier
    )


def karp_flatt_fraction(capacity: float, pool_multiplier: float) -> float | None:
    if pool_multiplier == 1.0:
        return None
    return (
        1.0 / capacity - 1.0 / pool_multiplier
    ) / (
        1.0 - 1.0 / pool_multiplier
    )


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def fit_all(
    observations: list[Observation],
    bootstrap_samples: int = 10_000,
    seed: int = 20260726,
) -> tuple[list[ModelFit], list[dict[str, float | int | str | None]]]:
    rng = random.Random(seed)
    runs = sorted({observation.run for observation in observations})
    fits: list[ModelFit] = []
    points: list[dict[str, float | int | str | None]] = []

    for kernel in KERNELS:
        for mode in MODES:
            means = _configuration_means(observations, kernel, mode)
            launch_means = {
                threads: {
                    run: mean(
                        observation.seconds
                        for observation in observations
                        if observation.run == run
                        and observation.kernel == kernel
                        and observation.mode == mode
                        and observation.threads == threads
                    )
                    for run in runs
                }
                for threads in THREAD_COUNTS
            }
            fraction = fit_effective_fraction(means)
            predictions = {
                threads: predict_runtime(means[2], threads / 2.0, fraction)
                for threads in THREAD_COUNTS
            }
            rmse = math.sqrt(
                mean(
                    (means[threads] - predictions[threads]) ** 2
                    for threads in THREAD_COUNTS
                )
            )

            holdout_fraction = fit_effective_fraction(
                means,
                fit_threads=(2, 4, 8, 16),
            )
            holdout_prediction = predict_runtime(means[2], 16.0, holdout_fraction)
            holdout_observed = means[32]
            holdout_error = (
                100.0 * (holdout_prediction - holdout_observed) / holdout_observed
            )

            bootstrap_fractions = []
            for _ in range(bootstrap_samples):
                selected_runs = [rng.choice(runs) for _ in runs]
                bootstrap_means = {
                    threads: mean(
                        launch_means[threads][run] for run in selected_runs
                    )
                    for threads in THREAD_COUNTS
                }
                bootstrap_fractions.append(
                    fit_effective_fraction(bootstrap_means)
                )

            fits.append(
                ModelFit(
                    kernel=kernel,
                    mode=mode,
                    effective_fraction=fraction,
                    ci_low=_percentile(bootstrap_fractions, 0.025),
                    ci_high=_percentile(bootstrap_fractions, 0.975),
                    rmse_seconds=rmse,
                    nrmse_percent=100.0 * rmse / mean(means.values()),
                    holdout_prediction_seconds=holdout_prediction,
                    holdout_observed_seconds=holdout_observed,
                    holdout_error_percent=holdout_error,
                )
            )

            for threads in THREAD_COUNTS:
                pool_multiplier = threads / 2.0
                capacity = means[2] / means[threads]
                points.append(
                    {
                        "kernel": kernel,
                        "mode": mode,
                        "threads": threads,
                        "pool_multiplier": pool_multiplier,
                        "mean_seconds": means[threads],
                        "capacity": capacity,
                        "karp_flatt_fraction": karp_flatt_fraction(
                            capacity,
                            pool_multiplier,
                        ),
                        "predicted_seconds": predictions[threads],
                        "predicted_capacity": means[2] / predictions[threads],
                    }
                )

    return fits, points
