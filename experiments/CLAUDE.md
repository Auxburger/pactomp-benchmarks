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
| DRM source (Rust) | `$POMP_DIR` | `$HOME/pactomp-coordinator` |
| DRM binary | `$POMP_BIN` | `$POMP_DIR/target/release/pactomp-coordinator` |
| LLVM build output | `$LLVM_BUILD` | `$HOME/llvm-project/build` (provides `lib/libomp.so`) |
| LLVM runtime source | — | `$LLVM_BUILD/../openmp/runtime/src/kmp_resource_manager.cpp` |
| Bundled NPB tree | `$NPB_DIR` | `<repo>/NPB3.4-OMP` |
| NPB binaries | `$NPB_BIN` | `$NPB_DIR/bin` — `ft.C.x`, `cg.C.x`, `ep.C.x` |
| Benchmark results | `$DATA_DIR` | `<repo>/data` — `dual/`, `staggered/`, `tracing/`, `mix/` |
| SLURM logs | `$SLURM_LOG_DIR` | `<repo>/data/slurm_logs/slurm-<JOBID>.out/.err` |

Override any of them from the environment:

```bash
LLVM_BUILD=/elsewhere/llvm-project/build ./build_npb.sh
POMP_DIR=~/pactomp-coordinator ./test_all.sh 89
```

The coordinator was called `dynamic-resource-manager` when the dual and
staggered runs were made; it is now `pactomp-coordinator`. The rename went with
a rename of its environment variables: the old binary reads `DRM_CAPACITY` and
`DRM_CPU_LIST`, while the harness passes `POMP_CAPACITY` and `POMP_CPU_LIST`.
An old checkout therefore starts, ignores both settings and falls back to its
own defaults — a silently wrong experiment rather than an error. Point
`$POMP_DIR` at a current checkout, not at a leftover `dynamic-resource-manager`
or `drm` directory.

## Checking on a submitted job

LRZ policy caps how often the queue may be queried: roughly one `squeue` or
`sacct` per ten minutes, with a user-ID ban as the stated sanction for
persistent high-frequency polling. Do not wrap either command in a short wait
loop. Prefer watching the job's own output:

```bash
tail -f data/slurm_logs/slurm-<jobid>.out   # no queue query at all
watch -n 600 squeue --clusters=cm4 --me     # if the queue state is needed
```

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

**Placement is `taskset` only.** `numactl --cpunodebind --membind` was dropped as
redundant: `--cpunodebind` repeated the `taskset` after it, and `--membind`
repeated first touch, since each worker is pinned to one node's CPUs from `exec`
onwards. Runs up to and including 187303 used it, later ones do not.

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

### Worker-lifecycle mode (`--region-sizes`)

`--region-sizes 16,4,4` replaces the two busy regions with a sequence of regions
of the given team sizes, each held open for `--region-dwell-seconds`. Every
thread records its OpenMP number, its `pthread_self` handle **and** its Linux
thread id, and the process's native thread count is sampled from
`/proc/self/task` before and after each region.

This exists to reconstruct the worker-lifecycle observation the thesis
previously had to cite as unreproducible historical context: that a later,
smaller region reuses identities from an earlier larger one and that the native
worker population does not shrink with the team. Run it without the DRM — the
claim is about libomp itself, and a grant would confound the `num_threads`
clause:

```bash
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch \
  --region-sizes 16,4,4 --threads 16 --modes false --procs 1 --no-drm --runs 3
```

`manifest.json` carries the provenance that makes such a run citable: the LLVM
revision, whether its runtime source was clean, the CMake configuration, and
SHA256 plus mtime of both `libomp.so` and the coordinator binary.

## Mixed Workload Experiment

**Files:** `run_mix.sbatch` here; the driver is the `src/harness/mix/` package,
entered through `src/run_mix.py`.

**Purpose:** The realistic-contention case. Instead of a fixed pair of
processes, several different NPB kernels join at random offsets and each runs
for a random time window, so the number of concurrent OpenMP processes rises
and falls the way it does on a shared node. The schedule is drawn from a seed
and replayed twice — once with the coordinator up and `OMP_DYNAMIC=true`, once
with neither — so both arms face the identical workload.

**Design:**

| | arm `drm` | arm `nodrm` |
|---|---|---|
| Coordinator | running, `POMP_CAPACITY` = domain CPUs | not started |
| `OMP_DYNAMIC` | `true` → runtime asks for its share | `false` → every job takes all threads |
| CPUs | the whole domain per job (coordinator hands out disjoint slices) | the whole domain per job |
| Oversubscription | none — grants sum to the capacity | `n_active × threads` on `domain_cpus` |

Both arms run on the same NUMA node, one after the other rather than side by
side: a single arm's job mix already saturates the domain, so there is no
second domain left to compare against in the same instant. The seed is what
makes the two arms comparable, not simultaneity — which is the one way this
experiment differs from `dual` and `staggered`.

**The allocation is not a fixed NUMA node by itself.** A cm4 node is 2 sockets
× 56 cores × 2 threads (224 CPUs, 2 NUMA nodes of 56 cores), and `cm4_tiny`
shares a node between jobs — `OverSubscribe=NO`, `ExclusiveUser=NO` — so a
partial request returns whichever cores were free, straddling both sockets.
Our own logs show both cases: `0-88,112-200` (clean) and
`0-8,23-102,112-120,135-214` (a foreign job held cores 9-22). Three
consequences, all handled:

1. `run_mix.sbatch` asks for 89 cores, the same allocation as
   `run_npb_tiny.sbatch`, `run_staggered.sbatch` and `run_npb_exclusive.sbatch`
   — the request size is what buys the NUMA guarantee, and staying at 89 keeps
   all four experiments comparable. With 89 of 112 cores at most 23 are
   foreign, so the better NUMA node always keeps ≥45 free cores. This
   experiment needs one domain of 33 (32 + coordinator), which 65 cores would
   already guarantee by pigeonhole; the two-domain experiments need 33 + 32,
   and that is the bound 89 was sized to (88 is the minimum, 89 leaves a core
   of slack). What 89 does not buy is an empty node — see the caveat below.
2. `pick_domain` filters SMT siblings, so a domain never contains a core and
   its own second thread. The mask lists both (`0-88` *and* `112-200`), and
   taking the first N of a fragmented mask would otherwise halve the real
   capacity while reporting the requested number.
3. If no node fits anyway — a smaller allocation, or sub-NUMA clustering, as
   on the login nodes with their 4 nodes × 20 cores — the domain shrinks to
   what the best node offers and logs a WARNING instead of throwing away a job
   that already waited in the queue. Both arms use the shrunken domain, so they
   stay comparable, and `manifest.json` records `domain_cpus_requested` next to
   `domain_cpus_actual`. `--strict-domain` aborts instead, and a node offering
   fewer than 8 cores aborts either way.

The workload domain is therefore always single-node: `pick_domain` groups the
mask by `/sys` node and takes cores from one node only. Scattered CPUs across
domains are not a failure mode here; an aborted or shrunken run is.

**Residual caveat, specific to this experiment, and what handles it.** 89 cores
leave up to 23 for a foreign job — LRZ documents `cm4_tiny` as *shared*, 17–112
cores per job, while `cm4_std` is exclusive but demands 2–4 nodes. `dual` and
`staggered` run their two sides simultaneously, so a co-tenant perturbs both at
once; the mix arms run one after the other, so a co-tenant arriving between
them would land entirely on the second arm.

`--repeats N` is the answer: the arm order alternates every repeat
(`drm,nodrm | nodrm,drm | …`), so each arm goes first equally often and the
linear part of any drift cancels instead of being charged to one side.
`run_mix.sbatch` passes `--repeats 3`. Results pool across repeats in
`summary.json`, `iterations.csv` carries a `repeat` column, and the actual
order is recorded as `arm_order`.

If you would rather remove the co-tenant than average it out,
`sbatch --cpus-per-task=112 …` overrides the header on the command line and
reserves the node — within cm4_tiny's documented range, at the price of
comparability with the other three experiments. The textbook NUMA tool,
`--sockets-per-node=1 --cores-per-socket=33`, does work here (verified with
`sbatch --test-only`) but is the wrong choice: it guarantees locality while
leaving 23 cores of *our own* socket free for a co-tenant, which is the worst
place for a contention measurement.

Each job re-runs its kernel back to back until its window closes. A benchmark
already running when the window ends is *not* killed, so the last iteration of
a job usually overruns it — those rows carry `overran_window=true`.

**Submit:**
```bash
# Submit from the repository root; extra arguments go to run_mix.py
sbatch --clusters=cm4 experiments/run_mix.sbatch
sbatch --clusters=cm4 experiments/run_mix.sbatch --seed 7 --jobs 8
sbatch --clusters=cm4 experiments/run_mix.sbatch --arms nodrm,drm   # flip the arm order

# Locally, without SLURM
python3 src/run_mix.py --seed 42 --dry-run          # print the schedule and stop
python3 src/run_mix.py --seed 42 --arms nodrm       # baseline only, no coordinator needed
```

**Output files** (in `data/mix/<jobid>/`):
```
schedule.json                # the drawn schedule — replay it with --schedule
manifest.json                # argv, git rev, seed, CPU layout, full config
iterations.csv               # one row per benchmark process; arm + repeat columns
summary.json                 # per-arm totals pooled over repeats, arm_order, comparison
drm/J01_ft.out               # raw stdout per job, one "=== iteration n ===" block per run
nodrm/J01_ft.out
drm_r2/, nodrm_r2/, …        # further repeats; repeat 1 keeps the plain names
rm.log                       # DRM grants (drm arm only, appended across repeats)
cpu_util.log, pidstat.log    # mpstat/pidstat, from the sbatch wrapper
```

**What to look for:**
- `iterations.csv`: `total_threads` per iteration — the DRM arm should shrink
  teams as jobs join, the baseline should always report the full count
- `summary.json`: `comparison.iterations_gain_pct` — both arms get the same
  time windows, so the arm that completes more iterations inside them wins
- `rm.log`: renegotiation as each job joins and leaves

**Reproducibility:** `--seed` fixes the algorithm choice, start offset and time
window of every job. `schedule.json` is written before the first arm starts and
can be replayed verbatim with `--schedule <file>`, which keeps a run
reproducible even if the drawing code changes later. What is *not* fixed is how
many iterations a job completes — that is the measurement.

**Defaults worth knowing:**
- 6 jobs drawn from `ft cg ep`, offsets `0:30 s`, windows `30:90 s`, so an arm
  spans roughly two minutes; `run_mix.sbatch` runs 3 repeats of both arms,
  about 15 minutes of the 45 requested
- `--repeats` defaults to 1 on the command line and 3 in the job file: the tool
  does the minimal thing, the cluster job does the statistically sound one
- `--threads` defaults to the domain's CPU count (32), so the baseline
  oversubscribes by exactly the number of concurrent jobs
- `--capacity` defaults to the same number, giving fair-share grants of
  `capacity / n_active` per client
- Only `ft cg ep` class C are built by default — `build_npb.sh C mg is` first
  if you want to draw from more kernels
- `--domain-cpus` (default 32) is a maximum, not a promise — see the
   allocation note above
- Jobs are pinned with `taskset -c <domain cpus>`, not `preexec_fn` — the
  driver runs a thread per job and `preexec_fn` is not thread-safe. There is no
  `numactl --membind`: the whole domain sits on one node, so first touch keeps
  the memory local anyway

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

The mixed workload experiment needs the single-worker variant instead —
`pick_domain()` in the same module — because it puts the whole workload on one
node and replays it twice rather than running two sides at once. It returns the
coordinator CPU plus that node's `domain_cpus`, and the Python driver calls it
directly instead of going through `pick_cpus.py`.

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
