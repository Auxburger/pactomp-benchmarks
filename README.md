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

## License

Copyright 2026 Darius Augsburger.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this software except in compliance with the License. A copy of the full
license text is in [LICENSE](LICENSE), and you may also obtain it at
<http://www.apache.org/licenses/LICENSE-2.0>.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an **"AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND**, either express or implied. See the
License for the specific language governing permissions and limitations under
the License.

In short, and with the License text itself being authoritative: you may use,
modify, and redistribute this code, including commercially, provided you
retain the copyright and license notices, state significant changes you made,
and include the [NOTICE](NOTICE) file in redistributions. The License also
grants you a patent license from each contributor, and terminates that grant
if you initiate patent litigation over the work.

Unless you explicitly state otherwise, any contribution intentionally
submitted for inclusion in this work shall be licensed as above, without any
additional terms or conditions.

**Third-party code.** `NPB3.4-OMP/` contains the NAS Parallel Benchmarks 3.4
(OpenMP), developed by the NAS Parallel Benchmarks Group at NASA Ames Research
Center and distributed under the permissive NPB license, not Apache-2.0 — see
[NPB3.4-OMP/LICENSE](NPB3.4-OMP/LICENSE). That copy is unmodified: the DRM
instrumentation is in a patched LLVM OpenMP runtime that the benchmark binaries
load dynamically, not in the benchmark sources. The Apache grant above covers
the build and launch scripts, analysis code, and measurement data added
alongside it. See [NOTICE](NOTICE) for the breakdown.
