"""Run bookkeeping shared by every experiment: append rows to a CSV table and
write the manifest that says how a run was produced.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .logging_utils import now
from .paths import LLVM_BUILD, POMP_BIN, POMP_DIR, REPO_ROOT

# The build settings worth recovering from a finished run. Enough to say which
# compiler and configuration produced the runtime a measurement ran against.
CMAKE_KEYS = (
    "CMAKE_BUILD_TYPE",
    "CMAKE_C_COMPILER",
    "CMAKE_CXX_COMPILER",
    "CMAKE_CXX_FLAGS",
    "LLVM_ENABLE_PROJECTS",
)


def append_rows(path: Path, columns: "list[str]", rows: "list[dict]") -> None:
    """Append rows to a CSV, writing the header on first use."""
    exists = path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _git(repo: Path, *args: str) -> "str | None":
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def git_revision(repo: Path = REPO_ROOT) -> "str | None":
    return _git(repo, "rev-parse", "HEAD")


def file_identity(path: Path) -> "dict | None":
    """Hash and timestamp of a built artefact, so a run names the exact binary."""
    if not path.is_file():
        return None
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def cmake_config(build_dir: Path) -> "dict | None":
    cache = build_dir / "CMakeCache.txt"
    if not cache.is_file():
        return None
    found = {}
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        name, sep, value = line.partition(":")
        if not sep:
            continue
        if name in CMAKE_KEYS:
            found[name] = value.partition("=")[2]
    return found


def toolchain_manifest() -> dict:
    """Which runtime and coordinator a run was produced with.

    A measurement is only reconstructible if the artefacts behind it can be
    identified later: the LLVM revision, whether the runtime source was clean at
    the time, how it was configured, and which coordinator answered the grants.
    """
    llvm_source = LLVM_BUILD.parent
    dirty = _git(llvm_source, "status", "--porcelain", "openmp/runtime/src")
    return {
        "llvm": {
            "source_root": str(llvm_source),
            "revision": git_revision(llvm_source),
            "runtime_source_clean": (dirty == "") if dirty is not None else None,
            "build_config": cmake_config(LLVM_BUILD),
            "libomp": file_identity(LLVM_BUILD / "lib" / "libomp.so"),
        },
        "coordinator": {
            "source_root": str(POMP_DIR),
            "revision": git_revision(POMP_DIR),
            "binary": file_identity(POMP_BIN),
        },
    }


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
        "toolchain": toolchain_manifest(),
    }


def write_manifest(path: Path, payload: dict) -> None:
    manifest = {**environment_manifest(), **payload}
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
