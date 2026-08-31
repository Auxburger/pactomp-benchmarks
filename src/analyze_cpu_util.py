#!/usr/bin/env python3
"""Per-CPU utilisation figure, annotated with process placement and benchmarks.

    uv run python src/analyze_cpu_util.py <cpu_util_log> <meta_a> <meta_b> \
        [--pidstat pidstat_<JOBID>.log] \
        [--slurm-out slurm-<JOBID>.out] \
        [--out cpu_utilisation.html] [--static] [--png]

Logs must have been produced with:
    mpstat -P ALL 5 >> cpu_util_<JOBID>.log
    pidstat -u -t 5 >> pidstat_<JOBID>.log

Parsing and plotting live in src/analysis; this is only the entry point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.datasets.cpu_util import parse_cpu_util  # noqa: E402
from analysis.datasets.drm import parse_pidstat  # noqa: E402
from analysis.datasets.meta import parse_cpu_splits, parse_meta  # noqa: E402
from analysis.io import write_outputs  # noqa: E402
from analysis.plots.cpu_util import make_cpu_util_annotated_figure  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cpu_log", type=Path, help="mpstat log (cpu_util_<JOBID>.log)")
    ap.add_argument("meta_a", type=Path, help="worker A meta.txt")
    ap.add_argument("meta_b", type=Path, help="worker B meta.txt")
    ap.add_argument("--pidstat", type=Path, default=None, help="pidstat log (pidstat_<JOBID>.log)")
    ap.add_argument("--slurm-out", type=Path, default=None, help="SLURM stdout log, for the CPU splits")
    ap.add_argument("--out", type=Path, default=Path("cpu_utilisation.html"))
    ap.add_argument("--static", action="store_true", help="also write a PDF (requires kaleido)")
    ap.add_argument("--png", action="store_true", help="also write a PNG (requires kaleido)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    print("Parsing mpstat …")
    df_cpu = parse_cpu_util(args.cpu_log, min_pct_usr=0.0)
    if df_cpu.empty:
        raise SystemExit("ERROR: no data parsed from mpstat log")
    print(f"  {len(df_cpu)} records, {df_cpu['cpu'].nunique()} CPUs")

    df_pidstat = None
    if args.pidstat:
        print("Parsing pidstat …")
        df_pidstat = parse_pidstat(args.pidstat)
        if df_pidstat.empty:
            print("  WARNING: no benchmark processes found in pidstat log")
        else:
            print(f"  {len(df_pidstat)} thread records")

    print("Parsing meta files …")
    events = parse_meta(args.meta_a) + parse_meta(args.meta_b)

    splits = {}
    if args.slurm_out:
        print("Parsing CPU splits …")
        splits = parse_cpu_splits(args.slurm_out)
        print(f"  t = {sorted(splits)}")

    print("Rendering …")
    fig = make_cpu_util_annotated_figure(df_cpu, df_pidstat, events, splits)
    write_outputs(fig, args.out.with_suffix(".html"), also_static=args.static, also_png=args.png)


if __name__ == "__main__":
    main()
