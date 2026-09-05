# CLAUDE.md — pactomp-benchmarks Root

Benchmark harness, raw measurement data, and analysis code for the PactOMP DRM
work. Split out of the master-thesis repository, which still holds the thesis
text and the committed figure PDFs.

## Documentation discipline

After any change (code, experiments, results, design decisions), update the
relevant markdown files before finishing:

| File | Update when |
|------|-------------|
| `docs/STAGGERED_HANDOVER.md` | New staggered job, per-job results, interpretation changes |
| `docs/PLOTTING_HANDOVER.md` | Plotting pipeline or staggered analysis changes |
| `docs/ANALYSIS.md` | Plot design decisions, source layout, canonical job changes |
| `experiments/CLAUDE.md` | DRM protocol, key paths, known limitations changes |
| `docs/experiments.md` | Directory layout, experiment designs, submit commands (German) |
| `README.md` | Layout, entry points, dependencies, anything a newcomer runs |

Do not leave markdown docs stale after a code or data change.

Architecture changes and key findings that bear on the thesis narrative belong
in `THESIS_HANDOVER.md` in the thesis repository, not here.

## Never poll SLURM in a tight loop

LRZ policy forbids high-frequency queries to `squeue` and `sacct`. Their
guidance is one query per ten minutes, and permanent high-frequency polling
"may lead to a ban of the user ID". A `sleep 20` wait loop around `squeue` is
exactly the prohibited pattern, and the account it costs is the user's.

When waiting for a job, either sleep 600 seconds or more between queries, or do
not poll the queue at all and watch `data/slurm_logs/slurm-<jobid>.out` instead.
The login nodes are likewise for preparing jobs, compiling and moving data —
not for running the benchmarks themselves.

## Measurement data is immutable

`data/` holds retained run outputs. Do not edit, reformat, or
regenerate these files — they are the measurement record. Raw `.log` files are
committed deliberately, and the root `.gitignore` negates the generic `*.log`
rule to keep them tracked. Preserve that negation.

## Relationship to the thesis repository

The figure export scripts write to `figures/` at this repo's root by default.
The thesis consumes those PDFs from its own `figures/` directory, so set
`THESIS_FIGURES_DIR` to write there directly (see `README.md`). The local
`figures/` output is gitignored.

The thesis chapters cite paths in this repository as prose references, for
example `export_thesis_figs.py` and `data/dual`. If you
move or rename either, check `chapters/08_benchmarks.tex` in the thesis repo.

## The bundled NPB tree is pristine

`NPB3.4-OMP/` is byte-identical to the upstream NPB 3.4.3 release, and
must stay that way. Verify with:

```sh
curl -sSLO https://www.nas.nasa.gov/assets/npb/NPB3.4.3.tar.gz
tar xzf NPB3.4.3.tar.gz && diff -rq NPB3.4.3/NPB3.4-OMP NPB3.4-OMP
# expect: differing files none; extra files only NPB3.4-OMP/LICENSE
#         plus whatever a local build has produced (all gitignored)
```

Never add our own files to that tree, and never patch the benchmark sources.
The DRM instrumentation belongs in the LLVM OpenMP runtime, which lives in a
separate checkout. Build inputs and outputs are gitignored; the canonical
`config/make.def` lives in `experiments/make.def` and `experiments/build_npb.sh`
installs it before building.

## Experiment scripts must stay relocatable

Scripts in `experiments/` derive every repository path from their own location
via `experiments/paths.sh`, and take external dependencies (`LLVM_BUILD`,
`POMP_DIR`) from the environment with `$HOME`-relative defaults. The same holds
for `src/harness/paths.py`, which mirrors `paths.sh` for the Python side and
resolves the repository from its own `__file__` — keep the two in sync. Do not
reintroduce absolute cluster paths — they broke once already when this
repository was split out of the thesis repo, and they leak the cluster account
into a public repository.

## The Python project is rooted at the repository root

`pyproject.toml`, `src/`, `tests/`, and the `export_*.py` scripts all sit at
the top level; run everything with `uv run` from there. Generated figures go to
`output/<group>/`, which is gitignored and fully reproducible from `data/` — do
not commit them.

## src/ is split by runtime environment, not by topic

| Package | Runs | May import |
|---------|------|------------|
| `src/harness/` | on the cluster, with the system `python3` | **standard library only** |
| `src/analysis/` | locally, under `uv run` | anything in `pyproject.toml` |

`src/harness/` is what produces measurements (the tracing sweep, the DRM
coordinator, the NUMA layout picker the shell scripts call). Adding a
third-party import there breaks the cluster runs, where there is no uv and no
virtualenv. `src/analysis/` is what reads them, cut by layer:
`datasets/ → plots/ → reports/`, never backwards, plus `model/` for fits.

Runnable entry points are the scripts directly under `src/`
(`main.py`, `run_llvm_tracing.py`, `run_mix.py`, `analyze_cpu_util.py`,
`pick_cpus.py`);
everything below them is a package. Keep source files under 500 lines.

## Further guidance

- [docs/ANALYSIS.md](docs/ANALYSIS.md) — Python analysis pipeline: plot design
  decisions, parsing details, the canonical staggered job, and the PDF/A
  constraint on exported figures. Read this before touching
  `src/analysis/` or the `export_*.py` scripts.
- [experiments/CLAUDE.md](experiments/CLAUDE.md) — DRM protocol, experiment
  designs, SLURM setup, known limitations
