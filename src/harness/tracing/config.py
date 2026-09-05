"""Configuration and command-line interface for the tracing driver."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..paths import DATA_DIR, DRM_SOCKET, LLVM_BUILD, POMP_BIN

MICROBENCH_SOURCE = Path(__file__).resolve().parent / "omp_dyn.c"


@dataclass
class Config:
    out_dir: Path
    binary: Path
    source: Path
    bench: str
    threads: "list[int]"
    modes: "list[bool]"
    runs: int
    procs: int
    pin: str
    busy_seconds: float
    region_sizes: "str | None"
    region_dwell_seconds: float
    settle_seconds: float
    timeout: float
    display_affinity: bool
    places: "str | None"
    proc_bind: "str | None"
    drm: bool
    drm_binary: Path
    drm_socket: Path


def parse_thread_list(raw: str) -> "list[int]":
    values = [int(part) for part in re.split(r"[,\s]+", raw.strip()) if part]
    if not values or any(v < 1 for v in values):
        raise argparse.ArgumentTypeError(f"invalid thread list: {raw!r}")
    return values


def parse_modes(raw: str) -> "list[bool]":
    modes = []
    for part in re.split(r"[,\s]+", raw.strip().lower()):
        if not part:
            continue
        if part not in ("true", "false"):
            raise argparse.ArgumentTypeError(f"invalid OMP_DYNAMIC mode: {part!r}")
        modes.append(part == "true")
    if not modes:
        raise argparse.ArgumentTypeError("no OMP_DYNAMIC modes given")
    return modes


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_llvm_tracing.py",
        description=(
            "Sweep thread counts with concurrent OpenMP processes against the patched "
            "LLVM runtime, recording each process's affinity trace and runtime."
        ),
        epilog=(
            "examples:\n"
            "  python3 src/run_llvm_tracing.py --build\n"
            "  python3 src/run_llvm_tracing.py --build --threads 2,4,8 --runs 3\n"
            "  sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_out = DATA_DIR / "tracing" / (os.environ.get("SLURM_JOB_ID") or str(os.getpid()))

    p.add_argument("--out", type=Path, default=default_out, help=f"output directory (default: {default_out})")
    p.add_argument("--threads", type=parse_thread_list, default=parse_thread_list("2,4,8,16,32,64"),
                   help="comma-separated thread counts (default: 2,4,8,16,32,64)")
    p.add_argument("--modes", type=parse_modes, default=parse_modes("true,false"),
                   help="OMP_DYNAMIC values to sweep (default: true,false)")
    p.add_argument("--runs", type=int, default=1, help="repetitions of the whole sweep (default: 1)")
    p.add_argument("--procs", type=int, default=2, help="concurrent processes per cell (default: 2)")
    p.add_argument("--bench", default="omp", help="benchmark name used in output filenames (default: omp)")
    p.add_argument("--pin", choices=("threads", "all", "none"), default="threads",
                   help="CPU set per cell: first <t> allowed CPUs, all allowed CPUs, or no pinning")
    p.add_argument("--busy-seconds", type=float, default=2.0,
                   help="OMP_DYN_BUSY_SECONDS: busy-loop length per region (default: 2.0)")
    p.add_argument("--region-sizes", default=None,
                   help="worker-lifecycle mode: comma-separated team sizes for a region "
                        "sequence (e.g. 16,4,4). Replaces the two busy regions.")
    p.add_argument("--region-dwell-seconds", type=float, default=1.0,
                   help="how long each region of --region-sizes stays active (default: 1.0)")
    p.add_argument("--settle-seconds", type=float, default=5.0, help="pause between cells (default: 5)")
    p.add_argument("--timeout", type=float, default=600.0, help="per-cell timeout in seconds (default: 600)")

    p.add_argument("--source", type=Path, default=MICROBENCH_SOURCE,
                   help=f"microbenchmark source (default: {MICROBENCH_SOURCE})")
    p.add_argument("--binary", type=Path, default=None, help="compiled binary path (default: <out>/omp)")
    p.add_argument("--build", dest="build", action="store_true", default=None,
                   help="compile the microbenchmark first")
    p.add_argument("--no-build", dest="build", action="store_false", help="use an existing --binary as is")
    p.add_argument("--compiler", default=None,
                   help=f"compiler to use (default: {LLVM_BUILD / 'bin' / 'clang'}, else clang/gcc)")

    p.add_argument("--display-affinity", dest="display_affinity", action="store_true", default=True,
                   help="set OMP_DISPLAY_AFFINITY=true (default)")
    p.add_argument("--no-display-affinity", dest="display_affinity", action="store_false")
    p.add_argument("--places", default=None, help="OMP_PLACES (unset by default)")
    p.add_argument("--proc-bind", default=None,
                   help="OMP_PROC_BIND (unset by default: 'spread' overrides the DRM's CPU pinning)")

    p.add_argument("--drm", dest="drm", action="store_true", default=None,
                   help="run the DRM coordinator per thread count (default: on if $POMP_BIN exists)")
    p.add_argument("--no-drm", dest="drm", action="store_false", help="never start the coordinator")
    p.add_argument("--drm-binary", type=Path, default=POMP_BIN, help=f"coordinator binary (default: {POMP_BIN})")
    p.add_argument("--drm-socket", type=Path, default=DRM_SOCKET, help=f"coordinator socket (default: {DRM_SOCKET})")

    p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    return p


def parse_args(argv: "list[str] | None" = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def make_config(args: argparse.Namespace) -> Config:
    out_dir = args.out.expanduser().resolve()
    drm = args.drm
    if drm is None:
        drm = args.drm_binary.is_file()
    return Config(
        out_dir=out_dir,
        binary=(args.binary or out_dir / "omp").expanduser(),
        source=args.source.expanduser().resolve(),
        bench=args.bench.lower(),
        threads=args.threads,
        modes=args.modes,
        runs=args.runs,
        procs=args.procs,
        pin=args.pin,
        busy_seconds=args.busy_seconds,
        region_sizes=args.region_sizes,
        region_dwell_seconds=args.region_dwell_seconds,
        settle_seconds=args.settle_seconds,
        timeout=args.timeout,
        display_affinity=args.display_affinity,
        places=args.places,
        proc_bind=args.proc_bind,
        drm=drm,
        drm_binary=args.drm_binary.expanduser(),
        drm_socket=args.drm_socket,
    )
