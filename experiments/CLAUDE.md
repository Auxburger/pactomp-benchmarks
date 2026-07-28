# CLAUDE.md — DRM Experiment Harness

## Project Context

Master thesis evaluating a custom Dynamic Resource Manager (DRM) for OpenMP on LRZ CoolMUC-4. The DRM coordinates thread allocation across concurrent OpenMP processes via a Unix socket (`/tmp/omp-rm.sock`). The custom LLVM OpenMP runtime (`kmp_resource_manager.cpp`) queries the DRM before each parallel region and uses the granted thread count.

## Key Paths

All paths are resolved by `paths.sh`, which every script in this directory
sources. Repository paths come from the script's own location; the two external
checkouts come from the environment with `$HOME`-relative defaults.

| What | Variable | Default |
|------|----------|---------|
| DRM source (Rust) | `$DRM_DIR` | `$HOME/dynamic-resource-manager` |
| DRM binary | `$DRM_BIN` | `$DRM_DIR/target/release/dynamic-resource-manager` |
| LLVM build output | `$LLVM_BUILD` | `$HOME/llvm-project/build` (provides `lib/libomp.so`) |
| LLVM runtime source | — | `$LLVM_BUILD/../openmp/runtime/src/kmp_resource_manager.cpp` |
| Bundled NPB tree | `$NPB_DIR` | `<repo>/NPB3.4-OMP` |
| NPB binaries | `$NPB_BIN` | `$NPB_DIR/bin` — `ft.C.x`, `cg.C.x`, `ep.C.x` |
| Benchmark results | `$DATA_DIR` | `<repo>/data` — `dual/`, `staggered/` |
| SLURM logs | `$SLURM_LOG_DIR` | `<repo>/data/slurm_logs/slurm-<JOBID>.out/.err` |

Override any of them from the environment:

```bash
LLVM_BUILD=/elsewhere/llvm-project/build ./build_npb.sh
DRM_DIR=~/pactomp-coordinator ./test_all.sh 89
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

**Output files** (in `data/staggered/`):
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

**Current default:** `ft cg ep`, t=32, 15 iterations, 10 s offset (see `run_staggered.sbatch`)

**Calling convention:**
```bash
./test_staggered.sh <total_cpus> [domain_cpus] [threads] [algorithm] [iters] [offset_sec]
# Example: ./test_staggered.sh 89 32 32 ft 15 10
```

## Main Experiment

**Files:** `test_all.sh`, `run_npb_tiny.sbatch`

**Design:** Per thread count `t`, both sides get exactly `t` CPUs via taskset:
- `dyn=true` (A side): DRM grants t/2 threads each → t total threads on t CPUs (1:1, no oversubscription)
- `dyn=false` (B side): t threads each → 2t total threads on t CPUs (always 2× oversubscribed)

**Results (job 172930):**
- CG: up to +60% for dyn=true at t=32
- FT: up to +21% for dyn=true at t=32
- EP: ~0% (compute-bound, expected negative control)

## DRM Protocol

- **Request** (16 bytes): `pid` (u32), `max_threads` (u16), `hint_threads` (u16), `flags` (u32), `seq` (u32)
- **Reply** (12 bytes): `granted` (u16), `ttl_ms` (u16), `epoch` (u32), `base_cpu` (u16), `num_cpus` (u16)
- Fair-share formula: `granted = 1 + (capacity - n_active) / n_active`
- DRM started with `DRM_CAPACITY=t` and `DRM_CPU_LIST=<first t CPUs of A domain>`

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
| `DRM_CAPACITY` | `t` | Fair-share capacity → grants t/2 per client with 2 clients |
| `DRM_CPU_LIST` | first t CPUs of A domain | CPU pool for DRM assignment |
| `LLVM_BUILD` | `$HOME/llvm-project/build` (override to relocate) | Used for `LD_LIBRARY_PATH` |
