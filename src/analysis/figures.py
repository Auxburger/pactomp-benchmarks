"""Where the exported thesis figures land.

The export scripts write into this repository's figures/ directory by default.
THESIS_FIGURES_DIR overrides it.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_FIGURES = REPO_ROOT / "figures"


def thesis_figures_dir() -> Path:
    """Resolve the output directory and create it."""
    raw = os.environ.get("THESIS_FIGURES_DIR")
    out = Path(raw).expanduser() if raw else LOCAL_FIGURES
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out
