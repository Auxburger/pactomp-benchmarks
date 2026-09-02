# CLAUDE.md — DRM Experiment Harness

## Project Context

Master thesis evaluating a custom Dynamic Resource Manager (DRM) for OpenMP on LRZ CoolMUC-4. The DRM coordinates thread allocation across concurrent OpenMP processes via a Unix socket (`/tmp/omp-rm.sock`). The custom LLVM OpenMP runtime (`kmp_resource_manager.cpp`) queries the DRM before each parallel region and uses the granted thread count.

## Key Paths

All paths are resolved by `paths.sh`, which every script in this directory
sources. Repository paths come from the script's own location; the two external
checkouts come from the environment with `$HOME`-relative defaults.

`src/harness/paths.py` mirrors this file for the Python side. The duplication
is deliberate — the shell scripts must not need a Python detour for their own
variables — so keep the two in sync when either changes.

| What | Variable | Default |
|------|----------|---------|
| DRM source (Rust) | `$POMP_DIR` | `$HOME/dynamic-resource-manager` |
| DRM binary | `$POMP_BIN` | `$POMP_DIR/target/release/dynamic-resource-manager` |
| LLVM build output | `$LLVM_BUILD` | `$HOME/llvm-project/build` (provides `lib/libomp.so`) |
| LLVM runtime source | — | `$LLVM_BUILD/../openmp/runtime/src/kmp_resource_manager.cpp` |
| Bundled NPB tree | `$NPB_DIR` | `<repo>/NPB3.4-OMP` |
| NPB binaries | `$NPB_BIN` | `$NPB_DIR/bin` — `ft.C.x`, `cg.C.x`, `ep.C.x` |
| Benchmark results | `$DATA_DIR` | `<repo>/data` — `dual/`, `staggered/`, `tracing/` |
| SLURM logs | `$SLURM_LOG_DIR` | `<repo>/data/slurm_logs/slurm-<JOBID>.out/.err` |

Override any of them from the environment:

```bash
LLVM_BUILD=/elsewhere/llvm-project/build ./build_npb.sh
POMP_DIR=~/pactomp-coordinator ./test_all.sh 89
```

The coordinator was called `dynamic-resource-manager` when these runs were
made; it is now `pactomp-coordinator`. The default keeps the original name so
existing cluster checkouts keep working.

## Staggered Experiment

**Files:** `test_staggered.sh`, `run_staggered.sbatch`

**Purpose:** Demonstrates DRM dynamic rebalancing. A1/B1 start first with full resources. After `offset` seconds (default: 10 s), A2/B2 join. Each worker runs sequential benchmark iterations and logs per-iteration timing + epoch timestamp.

**Submit:**
```bash
# Submit from the repository root — the job resolves itself via SLURM_SUBMIT_DIR
sbatch --clusters=cm4 experiments/run_staggered.sbatch
```

**Output files** (in `data/staggered/<jobid>/` — the sbatch passes the job id
as the output directory):
```
<alg>_t<t>_off<s>_A1.log   # dyn=true, starts first
<alg>_t<t>_off<s>_A2.log   # dyn=true, joins after offset
<alg>_t<t>_off<s>_B1.log   # dyn=false, starts first
<alg>_t<t>_off<s>_B2.log   # dyn=false, joins after offset
<alg>_t<t>_off<s>_rm.log   # DRM grants log
```

**Log format** (one line per iteration):
```
# iter  start_epoch_ms  duration_ms  time_in_seconds
1  1779111199365  4419  4.01
```

**What to look for:**
- `rm.log`: DRM renegotiates `32 → 16+16 → 32` threads as processes join/leave
- A1/B1 iter 1: solo performance (~4 s for FT/CG at t=32)
- After offset: A side degrades less than B side (DRM coordination vs uncoordinated oversubscription)
- End of run: last remaining process gets full allocation restored

**Current default** (see `run_staggered.sbatch`): `ft cg ep` at t=32, 15
iterations for A1/B1 and 15 for A2/B2, 10 s offset for FT and CG, 5 s for EP —
EP is short enough that a 10 s offset would let A1/B1 finish before A2/B2 join.

**Calling convention:**
```bash
./test_staggered.sh <total_cpus> [domain_cpus] [threads] [algorithm] [iters1] [offset_sec] [iters2] [outdir]
# As the sbatch calls it:
./test_staggered.sh 89 32 32 ft 15 10 15 "$DATA_DIR/staggered/$SLURM_JOB_ID"
```

`iters2` is what A2/B2 run before leaving again, so A1/B1 see the full cycle:
solo → shared → solo restored.

## Main Experiment

**Files:** `test_all.sh`, `run_npb_tiny.sbatch`

**Design:** Per thread count `t`, both sides get exactly `t` CPUs via taskset:
- `dyn=true` (A side): DRM grants t/2 threads each → t total threads on t CPUs (1:1, no oversubscription)
- `dyn=false` (B side): t threads each → 2t total threads on t CPUs (always 2× oversubscribed)

**Results (job 172930):**
- CG: up to +60% for dyn=true at t=32
- FT: up to +21% for dyn=true at t=32
- EP: ~0% (compute-bound, expected negative control)

## Tracing Microbenchmark

**Files:** `run_llvm_tracing.sbatch` here; the driver itself is the
`src/harness/tracing/` package next to `omp_dyn.c`, entered through
`src/run_llvm_tracing.py`.

**Purpose:** The minimal reproducer for the runtime's thread-allocation
behaviour, without NPB in the way. `omp_dyn.c` runs two parallel regions of a
busy loop and prints an NPB-shaped summary block; the driver sweeps thread
counts and launches `--procs` concurrent processes per (thread count,
`OMP_DYNAMIC`) cell, with `OMP_DISPLAY_AFFINITY` on so each `.out` carries the
runtime's affinity trace next to the timing.

This is the Python rewrite of the old shell scripts, which are kept for
reference in `src/harness/tracing/legacy/` (`test-omp-dyn.sh`, `test-one-dyn.sh`).
The driver uses the standard library only, so the cluster `python3` runs it —
no uv needed.

**Submit:**
```bash
# Submit from the repository root; extra arguments go to run_llvm_tracing.py
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch --runs 3 --threads 2,4,8,16,32

# Locally, without SLURM
python3 src/run_llvm_tracing.py --build --out /tmp/tracing --threads 2,4 --no-drm
```

**Output files** (in `data/tracing/<jobid>/`):
```
run_<r>/omp/omp_threads_<t>_dyn_<true|false>_<i>.out   # stdout + affinity trace per process
run_<r>/omp/omp_log_t<t>.txt                           # per-cell start/finish/duration
timings.csv                                            # one row per process
manifest.json                                          # argv, git rev, compile command, source hash
rm.log                                                 # DRM grants (when the coordinator runs)
cpu_util.log, pidstat.log                              # mpstat/pidstat, from the sbatch wrapper
```

The `.out` names match the NPB experiments, so `src/main.py` plots tracing runs
as its own `output/tracing/` group (`omp` is in `KNOWN_BENCHES`).

**Defaults worth knowing:**
- `--pin threads` gives each cell the first `t` allowed CPUs, so `dyn=false`
  oversubscribes `2t` threads onto `t` CPUs exactly as the main experiment does
- `--drm` defaults to on when `$POMP_BIN` exists; the coordinator is restarted
  per thread count with `POMP_CAPACITY=t`, as in `test_all.sh`
- `OMP_PROC_BIND` is deliberately unset (see limitation 2 below); `--proc-bind`
  sets it if you want the old `spread` behaviour of `legacy/test-omp-dyn.sh`
- `--busy-seconds` (default 2.0) is the per-region busy loop, scaled inside
  `omp_dyn.c` by the oversubscription factor

## CPU Layout Picker

`test_all.sh` and `test_staggered.sh` both need the same decision: which NUMA
node hosts worker A (plus one CPU for the coordinator), which hosts worker B,
and which CPUs each gets. That logic lives in `src/harness/cpu_layout.py` and
is called through `src/pick_cpus.py`:

```bash
readarray -t PICK < <(python3 "$REPO_ROOT/src/pick_cpus.py" --mask "$ALLOWED_RAW" --domain-cpus "$domain_cpus")
```

It prints three lines — coordinator CPU, `<node> <cpus>` for worker A, the same
for worker B — or `ERROR <reason>` with exit code 2, which both callers check.
It used to be a ~90-line heredoc inside each script; the copies had drifted and
the staggered one had lost its error handling. Tests: `tests/test_cpu_layout.py`.

## DRM Protocol

- **Request** (16 bytes): `pid` (u32), `max_threads` (u16), `hint_threads` (u16), `flags` (u32), `seq` (u32)
- **Reply** (12 bytes): `granted` (u16), `ttl_ms` (u16), `epoch` (u32), `base_cpu` (u16), `num_cpus` (u16)
- Fair-share formula: `granted = 1 + (capacity - n_active) / n_active`
- DRM started with `POMP_CAPACITY=t` and `POMP_CPU_LIST=<first t CPUs of A domain>`

## Building

```bash
# After editing kmp_resource_manager.cpp:
./build_omp.sh --runtime-only

# NPB binaries do NOT need recompiling — they load libomp.so dynamically
ldd "$NPB_BIN/ft.C.x" | grep omp  # confirms dynamic link to LLVM build
```

The DRM instrumentation is entirely in the LLVM OpenMP runtime. The benchmark
sources are never patched — `NPB3.4-OMP/` is a byte-identical copy of
upstream NPB 3.4.3 and must stay that way.

Building the benchmarks themselves is a separate step, because the build config
is deliberately not committed inside the pristine NPB tree:

```bash
./build_npb.sh          # installs make.def into NPB3.4-OMP/, builds ft/cg/ep class C
./build_npb.sh C mg is  # explicit class and benchmark list
```

## Known Limitations

1. **CPU pinning applies only to master thread.** `sched_setaffinity` in `kmp_resource_manager.cpp` sets affinity on the master before the parallel region, but LLVM's hot-team worker threads retain their original (full taskset) affinity. Workers are not re-pinned when the DRM assigns a CPU range.

2. **`OMP_PROC_BIND=spread` is incompatible with DRM CPU pinning.** It overrides `sched_setaffinity` on every worker via pre-computed OMP_PLACES. It is intentionally NOT set in the current setup.

3. **First parallel region always uses fallback thread count.** The DRM reply is non-blocking; the first region forks before the reply arrives and uses `OMP_NUM_THREADS` as fallback.

## Important Environment Variables

| Variable | Value | Effect |
|----------|-------|--------|
| `KMP_DYNAMIC_MODE` | `thread_limit` | Disables LLVM load-average heuristic that can override DRM grant |
| `OMP_DYNAMIC` | `true` / `false` | Enables/disables DRM queries in the runtime |
| `POMP_CAPACITY` | `t` | Fair-share capacity → grants t/2 per client with 2 clients |
| `POMP_CPU_LIST` | first t CPUs of A domain | CPU pool for DRM assignment |
| `LLVM_BUILD` | `$HOME/llvm-project/build` (override to relocate) | Used for `LD_LIBRARY_PATH` |
