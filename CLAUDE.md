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
| `plots/CLAUDE.md` | Plot design decisions, source layout, canonical job changes |
| `experiments/CLAUDE.md` | DRM protocol, key paths, known limitations changes |

Do not leave markdown docs stale after a code or data change.

Architecture changes and key findings that bear on the thesis narrative belong
in `THESIS_HANDOVER.md` in the thesis repository, not here.

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
example `plots/export_thesis_figs.py` and `data/dual`. If you
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
`DRM_DIR`) from the environment with `$HOME`-relative defaults. Do not
reintroduce absolute cluster paths — they broke once already when this
repository was split out of the thesis repo, and they leak the cluster account
into a public repository.

## Sub-project CLAUDE.md files

- [plots/CLAUDE.md](plots/CLAUDE.md) — Python plotting pipeline (Plotly, staggered visualisation, thesis figure export)
- [experiments/CLAUDE.md](experiments/CLAUDE.md) — DRM protocol, experiment designs, SLURM setup, known limitations
