"""Configuration and command-line interface for the mixed workload experiment."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import DATA_DIR, DRM_SOCKET, NPB_BIN, POMP_BIN

ARMS = ("drm", "nodrm")
DEFAULT_ALGORITHMS = ("ft", "cg", "ep")


@dataclass
class Config:
    out_dir: Path
    npb_bin: Path
    npb_class: str
    algorithms: "list[str]"
    arms: "list[str]"
    repeats: int
    jobs: int
    seed: int
    threads: "int | None"
    domain_cpus: int
    strict_domain: bool
    offset_range: "tuple[float, float]"
    duration_range: "tuple[float, float]"
    gap_seconds: float
    settle_seconds: float
    timeout: float
    schedule_file: "Path | None"
    display_affinity: bool
    drm_binary: Path
    drm_socket: Path
    capacity: "int | None"

    def binary_for(self, algorithm: str) -> Path:
        return self.npb_bin / f"{algorithm}.{self.npb_class}.x"


def parse_algorithms(raw: str) -> "list[str]":
    values = [part.lower() for part in re.split(r"[,\s]+", raw.strip()) if part]
    if not values:
        raise argparse.ArgumentTypeError("no algorithms given")
    if any(not v.isalnum() for v in values):
        raise argparse.ArgumentTypeError(f"invalid algorithm list: {raw!r}")
    return values


def parse_arms(raw: str) -> "list[str]":
    values = [part.lower() for part in re.split(r"[,\s]+", raw.strip()) if part]
    unknown = [v for v in values if v not in ARMS]
    if not values or unknown:
        raise argparse.ArgumentTypeError(f"arms must be from {','.join(ARMS)}, got {raw!r}")
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError(f"duplicate arm in {raw!r}")
    return values


def parse_range(raw: str) -> "tuple[float, float]":
    parts = [part for part in re.split(r"[:,\s]+", raw.strip()) if part]
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid range: {raw!r}") from exc
    if len(values) == 1:
        values = [values[0], values[0]]
    if len(values) != 2 or values[0] < 0 or values[1] < values[0]:
        raise argparse.ArgumentTypeError(f"invalid range: {raw!r} (expected LOW:HIGH)")
    return values[0], values[1]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_mix.py",
        description=(
            "Mixed workload experiment: several NPB benchmarks start in parallel at "
            "random offsets and run for random windows, drawn from a seed. The same "
            "schedule is replayed once with the DRM coordinating the runtime and once "
            "without it."
        ),
        epilog=(
            "examples:\n"
            "  python3 src/run_mix.py --seed 42\n"
            "  python3 src/run_mix.py --seed 42 --jobs 8 --arms nodrm,drm\n"
            "  python3 src/run_mix.py --schedule data/mix/209300/schedule.json\n"
            "  sbatch --clusters=cm4 experiments/run_mix.sbatch --seed 42\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_out = DATA_DIR / "mix" / (os.environ.get("SLURM_JOB_ID") or str(os.getpid()))

    p.add_argument("--out", type=Path, default=default_out, help=f"output directory (default: {default_out})")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for the schedule (default: 42)")
    p.add_argument("--jobs", type=int, default=6, help="concurrent workloads to draw (default: 6)")
    p.add_argument("--algorithms", type=parse_algorithms, default=list(DEFAULT_ALGORITHMS),
                   help="NPB kernels to draw from (default: ft,cg,ep)")
    p.add_argument("--class", dest="npb_class", default="C", help="NPB class suffix (default: C)")
    p.add_argument("--arms", type=parse_arms, default=list(ARMS),
                   help="arms to run, in order (default: drm,nodrm)")
    p.add_argument("--repeats", type=int, default=1,
                   help="replay the arm sequence N times, alternating its order each "
                        "time (drm,nodrm | nodrm,drm | ...) so drift between arms cancels")
    p.add_argument("--offsets", dest="offset_range", type=parse_range, default=parse_range("0:30"),
                   help="start offset range in seconds, LOW:HIGH (default: 0:30)")
    p.add_argument("--durations", dest="duration_range", type=parse_range, default=parse_range("30:90"),
                   help="per-job time window in seconds, LOW:HIGH (default: 30:90)")
    p.add_argument("--threads", type=int, default=None,
                   help="OMP_NUM_THREADS per job (default: the domain's CPU count)")
    p.add_argument("--domain-cpus", type=int, default=32,
                   help="cores the whole workload shares, at most (default: 32)")
    p.add_argument("--strict-domain", dest="strict_domain", action="store_true", default=False,
                   help="abort if no NUMA node fits --domain-cpus (default: shrink to what fits)")
    p.add_argument("--capacity", type=int, default=None,
                   help="POMP_CAPACITY for the DRM arm (default: the domain's CPU count)")
    p.add_argument("--gap-seconds", type=float, default=0.5,
                   help="pause between a job's benchmark iterations (default: 0.5)")
    p.add_argument("--settle-seconds", type=float, default=10.0,
                   help="pause between the two arms (default: 10)")
    p.add_argument("--timeout", type=float, default=900.0,
                   help="per-benchmark-iteration timeout in seconds (default: 900)")
    p.add_argument("--schedule", dest="schedule_file", type=Path, default=None,
                   help="replay a schedule.json instead of drawing one from --seed")

    p.add_argument("--display-affinity", dest="display_affinity", action="store_true", default=False,
                   help="set OMP_DISPLAY_AFFINITY=true (off by default: one trace per iteration is a lot)")

    p.add_argument("--drm-binary", type=Path, default=POMP_BIN, help=f"coordinator binary (default: {POMP_BIN})")
    p.add_argument("--drm-socket", type=Path, default=DRM_SOCKET, help=f"coordinator socket (default: {DRM_SOCKET})")
    p.add_argument("--npb-bin", type=Path, default=NPB_BIN, help=f"NPB binary directory (default: {NPB_BIN})")

    p.add_argument("--dry-run", action="store_true", help="print the schedule and exit")
    return p


def parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def make_config(args: argparse.Namespace) -> Config:
    return Config(
        out_dir=args.out.expanduser().resolve(),
        npb_bin=args.npb_bin.expanduser(),
        npb_class=args.npb_class.upper(),
        algorithms=args.algorithms,
        arms=args.arms,
        repeats=args.repeats,
        jobs=args.jobs,
        seed=args.seed,
        threads=args.threads,
        domain_cpus=args.domain_cpus,
        strict_domain=args.strict_domain,
        offset_range=args.offset_range,
        duration_range=args.duration_range,
        gap_seconds=args.gap_seconds,
        settle_seconds=args.settle_seconds,
        timeout=args.timeout,
        schedule_file=args.schedule_file.expanduser() if args.schedule_file else None,
        display_affinity=args.display_affinity,
        drm_binary=args.drm_binary.expanduser(),
        drm_socket=args.drm_socket,
        capacity=args.capacity,
    )
