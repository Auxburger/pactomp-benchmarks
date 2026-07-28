# CLAUDE.md — pactomp-benchmarks Root

Benchmark harness, raw measurement data, and analysis code for the PactOMP DRM
work. Split out of the master-thesis repository, which still holds the thesis
text and the committed figure PDFs.

## Documentation discipline

After any change (code, experiments, results, design decisions), update the
relevant markdown files before finishing:

| File | Update when |
|------|-------------|
| `STAGGERED_HANDOVER.md` | New staggered job, per-job results, interpretation changes |
| `PLOTTING_HANDOVER.md` | Plotting pipeline or staggered analysis changes |
| `plots/CLAUDE.md` | Plot design decisions, source layout, canonical job changes |
| `NPB3.4-OMP/CLAUDE.md` | DRM protocol, key paths, known limitations changes |

Do not leave markdown docs stale after a code or data change.

Architecture changes and key findings that bear on the thesis narrative belong
in `THESIS_HANDOVER.md` in the thesis repository, not here.

## Measurement data is immutable

`NPB3.4-OMP/benchmarks/` holds retained run outputs. Do not edit, reformat, or
regenerate these files — they are the measurement record. Raw `.log` files are
committed deliberately, and the root `.gitignore` negates the generic `*.log`
rule to keep them tracked. Preserve that negation.

## Relationship to the thesis repository

The figure export scripts write to `figures/` at this repo's root by default.
The thesis consumes those PDFs from its own `figures/` directory, so set
`THESIS_FIGURES_DIR` to write there directly (see `README.md`). The local
`figures/` output is gitignored.

The thesis chapters cite paths in this repository as prose references, for
example `plots/export_thesis_figs.py` and `NPB3.4-OMP/benchmarks/dual`. If you
move or rename either, check `chapters/08_benchmarks.tex` in the thesis repo.

## Sub-project CLAUDE.md files

- [plots/CLAUDE.md](plots/CLAUDE.md) — Python plotting pipeline (Plotly, staggered visualisation, thesis figure export)
- [NPB3.4-OMP/CLAUDE.md](NPB3.4-OMP/CLAUDE.md) — NPB benchmark suite, DRM protocol, SLURM experiment setup
