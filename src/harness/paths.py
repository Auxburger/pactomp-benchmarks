"""Path resolution — the Python mirror of experiments/paths.sh.

Repository paths come from this file's own location so a checkout works
wherever it lives; the external checkouts come from the environment with
$HOME-relative defaults. Keep this in sync with experiments/paths.sh — the
shell scripts need the same values without a Python detour.
"""

from __future__ import annotations

import os
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parents[1]


def env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


# ── This repository ──────────────────────────────────────────────────────────
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
NPB_DIR = env_path("NPB_DIR", REPO_ROOT / "NPB3.4-OMP")
NPB_BIN = env_path("NPB_BIN", NPB_DIR / "bin")
DATA_DIR = env_path("DATA_DIR", REPO_ROOT / "data")
SLURM_LOG_DIR = env_path("SLURM_LOG_DIR", DATA_DIR / "slurm_logs")

# ── External dependencies ────────────────────────────────────────────────────
LLVM_BUILD = env_path("LLVM_BUILD", Path.home() / "llvm-project" / "build")
POMP_DIR = env_path("POMP_DIR", Path.home() / "pactomp-coordinator")
POMP_BIN = env_path("POMP_BIN", POMP_DIR / "target" / "release" / "pactomp-coordinator")
DRM_SOCKET = Path(os.environ.get("POMP_SOCKET", "/tmp/omp-rm.sock"))
