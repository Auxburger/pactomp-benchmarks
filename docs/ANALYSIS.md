# Analysis Pipeline — NPB DRM Benchmark Visualisation

## What this directory is

Python plotting pipeline for a master thesis evaluating a Dynamic Resource Manager (DRM) for OpenMP on LRZ CoolMUC-4. The DRM coordinates thread allocation across concurrent OpenMP processes. This pipeline reads benchmark output logs and produces interactive Plotly HTML figures.

Run everything from the repository root:
```bash
uv run python src/main.py           # newest staggered job only (fast, skips unchanged outputs)
uv run python src/main.py --all     # all staggered jobs
uv run python src/main.py --static  # also export PDFs next to each HTML (requires kaleido)
uv run python src/main.py --png     # also export PNGs next to each HTML (requires kaleido)
```

Flags can be combined: `--static --png` exports both. Outputs land in `output/<group>/`.

**Incremental builds**: all three processing stages (aggregated benchmarks, monitoring, staggered) skip regenerating a plot if the output HTML is already newer than every input file. To force a rebuild: touch any input log file (`touch data/staggered/187303/cg_t32_off10_A1.log`) or delete the output directory.

**Thesis figure export**: `export_thesis_figs.py` (at the repository root, not under `src/`) is a separate script that regenerates the thesis-quality PDFs for job 187303 (staggered) and job 172930 (aggregated `dual`) and writes them to `figures/`. It applies thesis styling (legend at bottom, suppressed title, 900×420 px). Run with `uv run python export_thesis_figs.py` (requires Chrome for kaleido rendering — run `uv run plotly_get_chrome` once if missing). Does **not** generate cpu_placement figures — see warning below.

**Scalability model export**: `export_scalability_model.py` fits the configuration-level Amdahl--Karp--Flatt model over `data/dual` and writes `amdahl_karp_flatt_capacity.pdf` to `figures/` plus two CSVs to `output/model/`. Run with `uv run python export_scalability_model.py` from the repository root. Same thesis styling and TUM colours as above.

**Every figure in `figures/` must be produced through kaleido.** `main.tex` loads `\usepackage[a-2u]{pdfx}` for PDF/A-2u, which requires all fonts to be embedded; kaleido embeds a subsetted OpenSans, so figures written this way comply. Hand-written PDF (e.g. raw content streams using base-14 Helvetica) does **not** embed fonts and silently breaks PDF/A for the whole thesis. Verify with `pdffonts figures/<name>.pdf` — the `emb` column must read `yes` for every row.

**Aggregated benchmark figures source from `dual`, not `dual-exclusive`.** `dual-exclusive` only ever launched one process per configuration (no `_2` output files exist anywhere in it) — it cannot represent the two-process oversubscription scenario the thesis tables describe, and using it previously produced figures that flatly contradicted the thesis text (near-identical dyn=true/false lines instead of the reported CG +60%/FT +21% gap). Do not switch the aggregated figures back to `dual-exclusive` without first verifying it actually contains two concurrent processes per run. The DRM-speedup aggregation also uses `.mean()` (not `.median()`) to match how the thesis table percentages are computed.

---

## Experiments

### Main experiment (`data/dual/`)
Two concurrent processes per benchmark (FT, CG, EP from NPB suite):
- **A-side (`dyn=true`)**: DRM-managed — grants `t/2` threads each → `t` total threads on `t` CPUs (no oversubscription)
- **B-side (`dyn=false`)**: unmanaged — each uses `t` threads → `2t` total threads on `t` CPUs (2× oversubscription)

Results (job 172930): CG +60%, FT +21% for DRM at t=32. EP ~0% (expected, compute-bound).

### Tracing microbenchmark (`data/tracing/<jobid>/`)
Produced by the `src/harness/tracing/` driver package (entry point `src/run_llvm_tracing.py`, submitted via `experiments/run_llvm_tracing.sbatch`). The `omp_dyn.c` microbenchmark stands in for the NPB kernels: two concurrent processes per (thread count, `OMP_DYNAMIC`) cell, `OMP_DISPLAY_AFFINITY` on, and an NPB-shaped summary block so `datasets/npb.py` reads the `.out` files unchanged. `omp` is therefore part of `KNOWN_BENCHES`, and `reports/tracing.py` plots these runs as the separate `output/tracing/` group — the run directories sit one level deeper (`<jobid>/run_<n>/omp/`) than the dual experiment, so `reports/tracing.py` handles the discovery. Each job directory also carries `timings.csv` and `manifest.json` written by the driver.

### Staggered experiment (`data/staggered/`)
Demonstrates DRM dynamic rebalancing. A1/B1 start first with full resources; A2/B2 join after `offset` seconds (default 10 s). Each worker logs per-iteration timing. DRM renegotiates `32 → 16+16 → 32` threads as processes join/leave.

**New-format layout** (from `run_staggered.sbatch` / `test_staggered.sh`): logs are written into a per-job subdirectory named after the SLURM job ID:
```
data/staggered/<SLURM_JOB_ID>/
  ft_t32_off2_A1.log
  ft_t32_off2_rm.log
  ...
  pidstat.log       ← replaces pidstat_<jobid>.log
  cpu_util.log      ← replaces cpu_util_<jobid>.log
```
Old flat-file layout (`pidstat_<jobid>.log` directly in `staggered/`) is still supported and processed with `--all`.

Worker log format (one line per iteration):
```
# label=A1 dyn=true t=32 alg=ft
# iter  start_epoch_ms  duration_ms  time_in_seconds
1  1779111199365  4419  4.01
```

**rm.log format**: grant and disconnect lines are now prefixed with the epoch in milliseconds, matching the worker log timeline:
```
[1782666117548] Granted 32 threads to pid 217518 (CPUs 1+32)
[1782666142090] Client pid 217518 disconnected — removed from state
```
Both parsers (`datasets/staggered.py`, `datasets/drm.py`) handle old logs without timestamps via linear interpolation as fallback.

---

## Source layout

The package is cut by layer, and the dependency direction follows the folders:
`datasets → plots → reports`, never backwards. `datasets/` returns DataFrames
and never plots; `plots/` returns figures and never writes files; `reports/`
decides which measurements become which figures and where they land. `model/`
sits outside that chain — it fits numbers, not figures, and uses only the
standard library.

| File | Purpose |
|------|---------|
| `src/main.py` | Entry point — resolves paths, calls the four reports |
| `src/analysis/datasets/npb.py` | NPB `.out` files → runtime/MOPS DataFrame |
| `src/analysis/datasets/staggered.py` | Staggered worker logs, DRM grants, DRM pins |
| `src/analysis/datasets/drm.py` | `rm.log` (grants) and `pidstat_*.log` |
| `src/analysis/datasets/cpu_util.py` | `mpstat -P ALL` output (`cpu_util_*.log`) |
| `src/analysis/datasets/meta.py` | `meta.txt` benchmark start events and the SLURM log's CPU splits |
| `src/analysis/plots/style.py` | Palettes, markers, figure note, thesis layout — the single source for all of them |
| `src/analysis/plots/npb.py` | Runtime/MOPS/init/speedup figures |
| `src/analysis/plots/_metrics.py` | The two generic metric builders behind them |
| `src/analysis/plots/drm.py` | DRM allocation violin, slab assignment, CPU placement Gantt |
| `src/analysis/plots/cpu_util.py` | Per-CPU utilisation heatmap, and the annotated composite (heatmap + thread placement + benchmark timeline) |
| `src/analysis/plots/staggered/` | `threads.py`, `cpu.py`, `iterations.py` |
| `src/analysis/reports/npb.py` | Groups dual/dual-exclusive runs, writes the aggregated figures |
| `src/analysis/reports/drm.py` | `output/monitoring/<jobid>/` |
| `src/analysis/reports/staggered.py` | `output/staggered/<jobid>/` |
| `src/analysis/reports/tracing.py` | `output/tracing/` |
| `src/analysis/reports/freshness.py` | The incremental-build check shared by all reports |
| `src/analysis/model/amdahl.py` | Amdahl–Karp–Flatt fit over `dual` (standard library only) |
| `src/analysis/io.py` | `write_outputs()` — HTML, optionally PDF (`also_static=True`) and/or PNG (`also_png=True`, `scale=2`) |
| `src/analyze_cpu_util.py` | Entry point for that composite figure — needs the job's `meta.txt` files, optionally `pidstat` and the SLURM log |
| `export_thesis_figs.py` | Standalone script: thesis-quality PDFs for job 187303 into `figures/` |
| `export_scalability_model.py` | Standalone script: model CSVs to `output/model/`, `amdahl_karp_flatt_capacity.pdf` to `figures/` |

Both export scripts take their styling from `plots/style.py`, so the thesis
PDFs and the interactive HTML cannot drift apart.

**Everything renders through Plotly.** `analyze_cpu_util.py` was the last
matplotlib holdout; it now builds a Plotly composite and writes HTML through
`io.write_outputs()` like every other figure, with `--static`/`--png` for the
kaleido exports. Its benchmark starts are a slim timeline row rather than the
old full-height lines — several hundred of them buried the heatmap — and the
shared x-axis spike line does the visual alignment instead.

---

## Canonical staggered job

**Job 187303** (2026-06-29) is the canonical staggered run: 10 s offset for CG/FT, 5 s for EP, 15 iterations each. Steady-state results (iters 3–13, t=32):

| Alg | A (DRM) | B (no DRM) | B/A  | Effect              |
|-----|---------|------------|------|---------------------|
| CG  | 7.58 s  | 12.32 s    | 1.62 | DRM saves 38 %      |
| FT  | 11.36 s | 9.24 s     | 0.81 | DRM 19 % slower (bandwidth pinning) |
| EP  | 6.66 s  | 3.22 s     | 0.48 | DRM ~2× slower, unstable |

See `docs/STAGGERED_HANDOVER.md` for full per-job history and interpretation.

---

## cpu_placement figure size warning

The pidstat-based `*_cpu_placement` figures from CoolMUC-4 produce **50–80 MB PDFs** because pidstat records all 224 cores on the node at 5-second intervals across a 5+ minute run. This makes them unsuitable for thesis inclusion. The interactive HTML versions are fine. `export_thesis_figs.py` deliberately excludes cpu_placement for this reason. The `--static`/`--png` flags in `main.py` will still write them if you run the full pipeline — that is intentional for interactive exploration, just don't include them in the thesis PDF.

---

## CPU placement Gantt (`plots/drm.py`)

Key design decisions, hard-won through iteration:

**Per-domain CPU normalisation** (not per-tgid): All DRM (A-domain) processes share a single reference minimum CPU, all no-DRM (B-domain) share theirs. This preserves disjoint DRM slab assignments — with t=8 DRM, Process A on CPUs {1–4} stays C1–C4 and Process B on CPUs {5–8} stays C5–C8. Per-tgid normalisation would collapse both to C1–C4 and make them look like they share cores (they don't).

**`t_inferred` override via `rm.log` blocks**: EP runs so fast it may appear in only one 5-second pidstat window, which can straddle a t-block boundary. `parse_drm_blocks()` extracts exact DRM capacity block timestamps from `rm.log`; each tgid's median timestamp is looked up in those blocks to get the correct `t`. This is passed as `drm_blocks=` to `make_cpu_placement_figure()`.

**Band assignment** (interval scheduling): Concurrent tgids within the same `(benchmark, t, dynamic)` group are assigned band 0 or 1 using a greedy interval scheduler. Band 0 gets y-offset −0.27 or −0.09 (DRM), band 1 gets +0.09 or +0.27 (no-DRM). Bar width = 0.16.

**Y-axis**: Integer CPU core ticks only (C1, C2, …), computed from actual bar positions — no phantom ticks in gaps.

**Colour**: Benchmark family (FT blue, CG orange, EP green). Band 1 (Process 2) gets a 55%-toward-white lighter shade. Pattern: solid = DRM, hatched = no-DRM.

---

## CPU utilisation heatmap (`plots/cpu_util.py`)

Parses `mpstat -P ALL 5` output. Active CPUs (ever >10% usr) are auto-detected and grouped into contiguous domains. Only the top-2 domains by total utilisation are shown (to avoid system-process noise creating 20+ subplots). Colour scale: white=0% → rust=100% usr.

**What the data says for the staggered run (job 177053):**
- B-domain (no-DRM, CPUs 56–87): uniformly ~83% usr across all cores. The missing ~17% is context-switching overhead from 2× oversubscription (64 threads on 32 CPUs).
- A-domain (DRM, CPUs 1–32): ~60–68% average, with a mild asymmetry (CPUs 1–16 slightly hotter than 17–32 reflecting the DRM slab split). Lower per-core load than B-side because total thread count is halved — less contention, less cache thrashing — which is why DRM is faster despite looking "less loaded".
- DRM pins only the master thread (`sched_setaffinity`); OMP workers roam across the full taskset, which is why both slab halves show activity rather than a clean 50/50 split.

---

## Known DRM limitations

1. **CPU pinning applies only to the master thread.** `sched_setaffinity` in `kmp_resource_manager.cpp` affects only the process's main thread. LLVM hot-team worker threads retain their original (full taskset) affinity and roam outside the assigned slab.

2. **First parallel region uses fallback thread count.** The DRM reply is non-blocking; the first region forks before the reply arrives and uses `OMP_NUM_THREADS` as fallback.

3. **DRM speedup mechanism is primarily thread count reduction**, not CPU pinning. Halving the thread count eliminates oversubscription; the CPU affinity benefit is secondary and partially lost due to limitation 1.

---

## Staggered grant parsing (`datasets/staggered.py`)

**`load_staggered_grants()`** builds a per-grant DataFrame from the rm.log and worker logs.

Each staggered iteration is a fresh process (new pid per run). After A2 joins, A1 and A2 pids appear interleaved in the rm.log with overlapping iteration windows, so matching a single grant timestamp to a worker is ambiguous.

**Majority-vote pid→worker assignment**: for each unique pid, count how many of its grant timestamps fall inside each candidate `(worker, iter)` window (±500 ms tolerance). Assign to the window with the highest count. Pids are processed in connection order; `taken` set prevents two pids from claiming the same iteration slot. This is robust even when A1 and A2 have overlapping iteration windows (e.g. CG with multi-second iterations and a 10 s offset).

**Slab non-stickiness**: the DRM does not lock A1 to the lower half across iterations. Each time a process reconnects, the DRM assigns whichever slab is available. The cpu_slab plot therefore shows genuine iteration-to-iteration alternation (e.g. A1 on CPUs 1+16 in iter 4, then 17+16 in iter 5) — this is real behaviour, not a bug.

---

## Adding new benchmark results

1. Drop the new SLURM job directory into `data/staggered/` (new format), run dirs into `data/dual/`, or a tracing job into `data/tracing/`
2. Run `cd src && python main.py` — only the newest staggered job is plotted; unchanged outputs are skipped
3. Use `--all` to regenerate everything across all staggered jobs
4. The `rm.log` DRM blocks are used for `t_inferred` correction in pidstat figures — keep it alongside `pidstat.log`
5. If the new job should become the canonical thesis run, update `export_thesis_figs.py` (`JOB_DIR`) and re-run it to refresh `../figures/`
6. Update `docs/STAGGERED_HANDOVER.md` with the new numbers
