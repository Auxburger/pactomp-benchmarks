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


def gcc_toolchain() -> "Path | None":
    """Prefix of the GCC installation clang should link against.

    Compute nodes carry no system GCC, so clang finds neither crtbeginS.o nor
    libgcc and the link fails. The module-provided GCC is not picked up on its
    own, so point clang at it explicitly.
    """
    found = shutil.which("gcc")
    if not found:
        return None
    prefix = Path(found).resolve().parent.parent
    return prefix if (prefix / "lib" / "gcc").is_dir() else None


def compile_microbench(source: Path, binary: Path, compiler: "str | None") -> "list[str]":
    cc = resolve_compiler(compiler)
    cmd = [str(cc), "-O2", "-fopenmp"]
    if cc.name.startswith("clang"):
        toolchain = gcc_toolchain()
        if toolchain:
            cmd += [f"--gcc-toolchain={toolchain}"]
        else:
            log("WARNING: no GCC toolchain found for clang — the link may fail")
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
