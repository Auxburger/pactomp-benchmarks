# PactOMP Benchmarks

Benchmark harness, raw measurement data, and analysis code for the PactOMP
dynamic resource management (DRM) work. Split out of the master-thesis
repository so the thesis text stays lightweight and the measurement artifacts
have a home of their own.

## Related repositories

- **The coordinator** — [Auxburger/pactomp-coordinator](https://github.com/Auxburger/pactomp-coordinator):
  the DRM daemon itself, a dependency-free Rust binary that arbitrates thread
  counts and CPU ranges between co-scheduled OpenMP processes. The experiments
  here launch it and record its `rm.log`.
- **The client counterpart** — [Auxburger/llvm-project @ `feature/PO-1-implement-llvm-pactomp-connection`](https://github.com/Auxburger/llvm-project/tree/feature/PO-1-implement-llvm-pactomp-connection):
  an LLVM fork whose OpenMP runtime queries the coordinator before forming a
  thread team and applies the returned thread count and affinity. This is the
  `libomp.so` that `experiments/build_omp.sh` builds and the NPB binaries load.
- **Thesis text** — [Auxburger/master-thesis](https://github.com/Auxburger/master-thesis):
  the write-up that motivates the design and interprets these measurements. It
  consumes the figure PDFs exported from this repository.

## Layout

| Path | Contents |
|------|----------|
| `data/` | The measurement record — all retained run outputs |
| `experiments/` | Shell side of the harness: build scripts, SLURM job files, the NPB build config |
| `src/harness/` | Everything that runs on the cluster — standard library only, no uv |
| `src/analysis/` | Everything that reads the results — `datasets/`, `plots/`, `reports/`, `model/` |
| `src/main.py` | Entry point: the analysis pipeline |
| `src/run_llvm_tracing.py` | Entry point: a tracing microbenchmark sweep |
| `src/run_mix.py` | Entry point: the seeded mixed workload experiment |
| `src/analyze_cpu_util.py` | Entry point: the annotated CPU-utilisation figure |
| `src/pick_cpus.py` | Entry point: the NUMA layout picker the shell scripts call |
| `export_*.py` | Standalone thesis figure exports |
| `tests/` | Tests: scalability model, CPU layout picker, tracing driver, meta parsing, the stdlib rule for `src/harness/` |
| `NPB3.4-OMP/` | Unmodified NAS Parallel Benchmarks 3.4.3 (OpenMP), third-party — see [NOTICE](NOTICE) |
| `docs/` | Report, per-job handover notes, analysis pipeline guide, project status |

The Python project lives at the repository root: `pyproject.toml`, `src/`, and
`tests/`. Inside `src/`, the split follows the runtime environment:
`src/harness/` runs on the cluster with the system `python3` and may use only
the standard library, while `src/analysis/` runs locally and may use everything
in `pyproject.toml`. Runnable entry points are the scripts directly under
`src/`; everything below them is a package.

Generated figures land in `output/<group>/` and are gitignored — they are fully
reproducible from `data/`.

Nothing of ours lives inside `NPB3.4-OMP/`. It is byte-identical to the upstream
NPB 3.4.3 release, so it can be re-verified against the official tarball at any
time and swapped wholesale for a newer version. Everything the NPB build
produces or needs in place — `bin/`, object files, generated headers, and
`config/make.def` — is gitignored; the canonical `make.def` lives in
[experiments/make.def](experiments/make.def) and `build_npb.sh` installs it.

The primary measurement data lives in `data/`:

- `dual/` — the main dual-launch experiment, SLURM job 172930 on LRZ CoolMUC-4
- `staggered/<jobid>/` — the staggered-launch jobs
- `dual-exclusive/` — exclusive-node comparison runs
- `tracing/<jobid>/` — the LLVM OpenMP tracing microbenchmark runs
- `mix/<jobid>/` — the seeded mixed workload runs, one directory per arm

plus `slurm_logs/` for the per-job SLURM stdout and stderr.

Raw `.log` files here (`cpu_util`, `pidstat`, `rm.log`, per-node stdout) are
primary research artifacts and are committed deliberately. The root
`.gitignore` carries an explicit negation so the generic `*.log` rule does not
swallow them.

## Running the experiments

The scripts in `experiments/` resolve every path from their own location, so a
checkout works wherever it lives. The two external dependencies — the patched
LLVM OpenMP runtime and the DRM coordinator — default to `$HOME/llvm-project`
and `$HOME/pactomp-coordinator`, and are overridable:

```sh
./experiments/build_omp.sh --runtime-only    # build the patched libomp.so
./experiments/build_npb.sh                   # install make.def, build ft/cg/ep class C

LLVM_BUILD=/elsewhere/llvm-project/build ./experiments/build_npb.sh
```

SLURM jobs must be submitted from the repository root, since they resolve
themselves through `SLURM_SUBMIT_DIR`:

```sh
sbatch --clusters=cm4 experiments/run_staggered.sbatch
sbatch --clusters=cm4 experiments/run_npb_tiny.sbatch
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch
sbatch --clusters=cm4 experiments/run_mix.sbatch
```

The tracing job wraps `src/run_llvm_tracing.py`, the entry point of the
`src/harness/tracing/` driver package that sits next to the OpenMP
microbenchmark it runs (`omp_dyn.c`). It compiles the microbenchmark against the patched
runtime, sweeps thread counts, and runs two concurrent processes per cell —
once with `OMP_DYNAMIC=true`, once with `false` — recording each process's
affinity trace and runtime. Arguments after the sbatch script are forwarded to
it, and it also runs standalone:

```sh
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch --runs 3 --threads 2,4,8,16,32
python3 src/run_llvm_tracing.py --build --out /tmp/tracing --no-drm
python3 src/run_llvm_tracing.py --help
```

It writes `data/tracing/<jobid>/`, needs only the standard library — no uv, so
the cluster `python3` runs it — and its per-process `.out` files carry the same
names as the NPB runs, so `src/main.py` picks them up as the `output/tracing/`
figure group. The shell scripts it replaces are kept in
`src/harness/tracing/legacy/`.

The mix job wraps `src/run_mix.py`, the entry point of the `src/harness/mix/`
driver package. It draws a schedule of concurrent NPB kernels from a seed —
random algorithm, random start offset, random time window per job — and replays
that same schedule twice on one NUMA node: once with the DRM coordinating the
runtime, once without it. Each job re-runs its kernel until its window closes,
so the number of competing processes rises and falls as the schedule dictates,
and the arm that completes more iterations in the identical windows wins:

```sh
sbatch --clusters=cm4 experiments/run_mix.sbatch --seed 7 --jobs 8
python3 src/run_mix.py --seed 42 --dry-run      # print the schedule and stop
python3 src/run_mix.py --seed 42 --arms nodrm   # baseline only, no coordinator needed
python3 src/run_mix.py --help
```

The job asks for 89 cores, the same allocation as the other three experiments.
`cm4_tiny` shares nodes between jobs, so the request size is what guarantees a
NUMA node large enough for the workload domain — with 23 cores at most in
foreign hands, the better node always keeps 45. The domain is always taken from
a single NUMA node with SMT siblings filtered out; if the allocated node is too
small it shrinks with a warning (`--strict-domain` to abort instead). Since these two arms run sequentially, a co-tenant appearing between them is
the one confound 89 cores does not remove; the job therefore runs `--repeats 3`
with the arm order alternating each time, so each arm goes first equally often
and drift cancels. `--cpus-per-task=112` reserves the node instead.

It writes `data/mix/<jobid>/` — `iterations.csv`, `summary.json` with the
`drm`/`nodrm` comparison, and the `schedule.json` that makes the run
reproducible (replay it verbatim with `--schedule`). Standard library only, so
the cluster `python3` runs this one too.

See [experiments/CLAUDE.md](experiments/CLAUDE.md) for the DRM protocol, the
experiment designs, and the known runtime limitations.

## Analysis

The Python project is managed with [uv](https://docs.astral.sh/uv/), and runs
from the repository root:

```sh
uv sync
uv run python -m pytest tests/ -q

uv run python src/main.py           # newest staggered job only (skips unchanged outputs)
uv run python src/main.py --all     # every staggered job
uv run python src/main.py --static  # also export PDFs (requires kaleido + Chrome)
```

Figures land in `output/<group>/`. See [docs/ANALYSIS.md](docs/ANALYSIS.md) for
the plot design decisions, parsing details, and the canonical staggered job.

The annotated per-CPU utilisation figure is a separate entry point, since it
needs the job's `meta.txt` files and optionally the SLURM log:

```sh
uv run python src/analyze_cpu_util.py data/dual/cpu_util_172930.log \
  data/dual/89/node0/meta.txt data/dual/89/node1/meta.txt \
  --pidstat data/dual/pidstat_172930.log --out cpu_utilisation.html
```

It writes interactive HTML; add `--static` or `--png` for the kaleido exports.
Every figure in this repository is a Plotly figure — there is no second
plotting stack to keep in sync.

## Regenerating the thesis figures

`export_thesis_figs.py` and `export_scalability_model.py` write the PDFs that
the thesis includes. By default they write to `figures/` at the root of this
repository. Because the thesis lives in a separate checkout, point
`THESIS_FIGURES_DIR` at its `figures/` directory to write straight into it:

```sh
THESIS_FIGURES_DIR=../master-thesis/figures uv run python export_thesis_figs.py
THESIS_FIGURES_DIR=../master-thesis/figures uv run python export_scalability_model.py
```

Adjust the relative path to wherever the thesis repository is checked out.
`export_scalability_model.py` additionally writes its fitted summary and
pointwise Karp--Flatt diagnostics to `output/model/`.

### Scalability model

The configuration-level Amdahl--Karp--Flatt analysis reads the 600 raw process
outputs under `data/dual`, validates the expected two-process cells, fits one
effective scaling-loss fraction per kernel and condition, performs launch-group
bootstrap resampling and a `t=32` forward hold-out check, then writes:

- `output/model/amdahl_karp_flatt_summary.csv`
- `output/model/amdahl_karp_flatt_points.csv`
- `figures/amdahl_karp_flatt_capacity.pdf`

The CSV half needs only the standard library; the PDF needs Kaleido and Chrome
(`uv run plotly_get_chrome` once, if missing).

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

**Third-party code.** `NPB3.4-OMP/` contains the NAS Parallel Benchmarks
3.4 (OpenMP), developed by the NAS Parallel Benchmarks Group at NASA Ames
Research Center and distributed under the permissive NPB license, not
Apache-2.0 — see
[NPB3.4-OMP/LICENSE](NPB3.4-OMP/LICENSE). That copy is unmodified: the DRM
instrumentation is in a patched LLVM OpenMP runtime that the benchmark binaries
load dynamically, not in the benchmark sources. The Apache grant above covers
the build and launch scripts, analysis code, and measurement data added
alongside it. See [NOTICE](NOTICE) for the breakdown.
