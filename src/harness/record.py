"""Run bookkeeping shared by every experiment: append rows to a CSV table and
write the manifest that says how a run was produced.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

from .logging_utils import now
from .paths import LLVM_BUILD, REPO_ROOT


def append_rows(path: Path, columns: "list[str]", rows: "list[dict]") -> None:
    """Append rows to a CSV, writing the header on first use."""
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def git_revision() -> "str | None":
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def environment_manifest() -> dict:
    """The part of a manifest that is the same for every experiment."""
    return {
        "started": now(),
        "host": os.uname().nodename,
        "argv": sys.argv,
        "git_revision": git_revision(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "repo_root": str(REPO_ROOT),
        "llvm_build": str(LLVM_BUILD),
    }


def write_manifest(path: Path, payload: dict) -> None:
    manifest = {**environment_manifest(), **payload}
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
