"""Driver for the LLVM OpenMP tracing microbenchmark (``omp_dyn.c``).

The Python rewrite of the shell scripts in ``legacy/``: compile the
microbenchmark against the patched LLVM OpenMP runtime, sweep thread counts,
and launch concurrent processes per (thread count, ``OMP_DYNAMIC``) cell while
capturing the runtime's affinity trace and per-process timing.

Output files use the same names as the NPB experiments
(``<bench>_threads_<t>_dyn_<mode>_<i>.out`` under ``<out>/run_<r>/<bench>/``),
so ``src/main.py`` parses tracing runs like any other measurement.

Standard library only — it runs with the cluster ``python3``, no uv needed.
Entry point: ``src/run_llvm_tracing.py``, or ``python3 -m harness.tracing``.
"""

from .config import Config, make_config, parse_args
from .sweep import main, sweep

__all__ = ["Config", "main", "make_config", "parse_args", "sweep"]
