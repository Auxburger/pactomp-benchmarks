"""Compiling omp_dyn.c against the patched LLVM OpenMP runtime."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..logging_utils import log
from ..paths import LLVM_BUILD


def resolve_compiler(explicit: "str | None") -> Path:
    if explicit:
        found = shutil.which(explicit)
        if not found:
            raise SystemExit(f"compiler not found: {explicit}")
        return Path(found)

    patched = LLVM_BUILD / "bin" / "clang"
    if patched.is_file():
        return patched
    for fallback in ("clang", "gcc"):
        found = shutil.which(fallback)
        if found:
            log(f"WARNING: {patched} missing, falling back to {found}")
            return Path(found)
    raise SystemExit(f"no compiler found (looked for {patched}, clang, gcc)")


def compile_microbench(source: Path, binary: Path, compiler: "str | None") -> "list[str]":
    cc = resolve_compiler(compiler)
    cmd = [str(cc), "-O2", "-fopenmp"]
    include = LLVM_BUILD / "projects" / "openmp" / "runtime" / "src"
    if include.is_dir():
        cmd += ["-I", str(include)]
    libdir = LLVM_BUILD / "lib"
    if libdir.is_dir():
        cmd += [f"-Wl,-rpath,{libdir}"]
    cmd += [str(source), "-o", str(binary)]

    log("compiling: " + " ".join(cmd))
    binary.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    return cmd
