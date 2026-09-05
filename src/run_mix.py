#!/usr/bin/env python3
"""Entry point for the mixed workload experiment.

Several NPB kernels start in parallel at random offsets and run for random
time windows; the schedule comes from a seed, so the DRM arm and the
uncoordinated arm face exactly the same workload.

    python3 src/run_mix.py --seed 42
    python3 src/run_mix.py --seed 42 --jobs 8 --dry-run
    python3 src/run_mix.py --help

See src/harness/mix/ for the driver itself and experiments/run_mix.sbatch for
the SLURM job that wraps it.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.mix.experiment import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
