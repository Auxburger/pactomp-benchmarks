# pactomp-benchmarks

Benchmark harness, raw measurement data, and analysis code for the PactOMP
dynamic resource management (DRM) work. Split out of the master-thesis
repository so the thesis text stays lightweight and the measurement artifacts
have a home of their own.

## Layout

| Path | Contents |
|------|----------|
| `NPB3.4-OMP/` | NAS Parallel Benchmarks (OpenMP) with the DRM instrumentation, build and SLURM launch scripts, and all retained run outputs under `benchmarks/` |
| `plots/` | Python analysis pipeline (Plotly): parsing, staggered visualisation, the scalability model, and the thesis figure export |
| `STAGGERED_HANDOVER.md` | Per-job staggered results and their interpretation |
| `PLOTTING_HANDOVER.md` | Plotting pipeline and staggered analysis notes |

The primary measurement data lives in `NPB3.4-OMP/benchmarks/`:

- `dual/` — the main dual-launch experiment, SLURM job 172930 on LRZ CoolMUC-4
- `staggered/<jobid>/` — the staggered-launch jobs
- `dual-exclusive/` — exclusive-node comparison runs

Raw `.log` files here (`cpu_util`, `pidstat`, `rm.log`, per-node stdout) are
primary research artifacts and are committed deliberately. The root
`.gitignore` carries an explicit negation so the generic `*.log` rule does not
swallow them.

## Analysis

The Python project is managed with [uv](https://docs.astral.sh/uv/):

```sh
cd plots
uv sync
uv run python -m pytest tests/ -q
```

## Regenerating the thesis figures

`plots/export_thesis_figs.py` and `plots/export_scalability_model.py` write the
PDFs that the thesis includes. By default they write to `figures/` at the root
of this repository. Because the thesis now lives in a separate checkout, point
`THESIS_FIGURES_DIR` at its `figures/` directory to write straight into it:

```sh
cd plots
THESIS_FIGURES_DIR=../../master-thesis/figures uv run python export_thesis_figs.py
THESIS_FIGURES_DIR=../../master-thesis/figures uv run python export_scalability_model.py
```

Adjust the relative path to wherever the thesis repository is checked out.
`export_scalability_model.py` additionally writes its fitted summary and
pointwise Karp--Flatt diagnostics to `plots/plots/model/`, which is committed.
