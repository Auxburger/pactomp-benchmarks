"""Where the exported thesis figures land.

The thesis is a separate checkout, so the export scripts write into its
figures/ directory by default and fall back to this repository's figures/ only
when that checkout is not next to us. THESIS_FIGURES_DIR overrides both.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCAL_FIGURES = REPO_ROOT / "figures"
THESIS_REPO_FIGURES = REPO_ROOT.parent / "master-thesis" / "figures"


def thesis_figures_dir() -> Path:
    """Resolve the output directory and create it."""
    raw = os.environ.get("THESIS_FIGURES_DIR")
    if raw:
        out = Path(raw).expanduser()
    elif THESIS_REPO_FIGURES.is_dir():
        out = THESIS_REPO_FIGURES
    else:
        out = LOCAL_FIGURES
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out
