#!/usr/bin/env python3
"""Entry point for the LLVM OpenMP tracing microbenchmark sweep.

    python3 src/run_llvm_tracing.py --build --threads 2,4,8 --runs 3
    python3 src/run_llvm_tracing.py --help

See src/harness/tracing/ for the driver itself and experiments/run_llvm_tracing.sbatch
for the SLURM job that wraps it.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.tracing.sweep import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
