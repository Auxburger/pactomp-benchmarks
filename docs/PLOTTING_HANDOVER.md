# Plotting Agent Handover — DRM Benchmark Visualizations

> **Superseded evidence note (July 20, 2026):** This plotting handover predates the treatment-fidelity audit. The coordinator-enabled EP condition combines one full-team and one half-team process per launch, and the retained main experiment does not isolate manager overhead or NUMA placement. Preserve the plotted observations, but use `chapters/08_benchmarks.tex` and `REVIEW.md` for interpretation.

This document tells a plotting agent exactly what data exists, where it lives, how to parse it, and what plots to produce for the master thesis.

---

## 1. Context

Two experiments were run on LRZ CoolMUC-4 (SLURM, cm4 cluster):

- **Main dual experiment** (job 172930, May 2026): Compares DRM thread count coordination vs uncoordinated oversubscription across thread counts t ∈ {2,4,8,16,32} for three benchmarks (FT, CG, EP).
- **Staggered experiment** (job 187129, June 2026): Shows DRM dynamic rebalancing. A1/B1 start first with full resources; A2/B2 join after 10 seconds. Per-iteration timing logged with epoch timestamps.

All measurement paths below are relative to the repository root, under `data/`.
(They were originally written as absolute paths under the cluster home
directory, before this repository was split out of the thesis repo.)

---

## 2. Main Dual Experiment

### Data location

```
data/dual/run_1/ … run_10/
  └── {alg}/
      └── {alg}_threads_{t}_dyn_{true|false}_{1|2}.out
```

- `alg` ∈ `{ft, cg, ep}`
- `t` ∈ `{2, 4, 8, 16, 32}`
- Two concurrent workers per run (suffix `_1` and `_2`)
- 10 runs × 2 workers = **20 measurements per (alg, t, dyn)** combination

### Parsing

Each `.out` file contains one line with the timing:
```
 Time in seconds =                     7.76
```

Extract with: `grep "Time in seconds" file.out | awk '{print $NF}'`

### What the experiment measures

- **dyn=true (A side):** DRM grants t/2 threads each → t total threads on t CPUs → 1:1, no oversubscription
- **dyn=false (B side):** t threads each → 2t total threads on t CPUs → 2× oversubscribed
- Both sides get exactly t CPUs via `taskset` (separate NUMA nodes, so no cross-side interference)

**Note:** a `dual-exclusive` directory also exists under `data/`, but it only ever launched one process per configuration (no `_2` output files) — it cannot represent the two-process oversubscription scenario and must not be used as a data source. `dual` (below) is the only valid source for the thesis figures/tables.

### Key numbers (mean per configuration)

| t  | FT dyn=true | FT dyn=false | CG dyn=true | CG dyn=false | EP dyn=true | EP dyn=false |
|----|-------------|--------------|-------------|--------------|-------------|--------------|
| 2  | 104.3 s     | 107.8 s      | 86.4 s      | 96.2 s       | 56.1 s      | 56.1 s       |
| 4  | 53.0 s      | 57.0 s       | 44.5 s      | 53.0 s       | 29.1 s      | 28.3 s       |
| 8  | 26.6 s      | 30.1 s       | 22.7 s      | 31.1 s       | 15.2 s      | 14.3 s       |
| 16 | 13.8 s      | 16.3 s       | 11.8 s      | 17.8 s       | 7.9 s       | 7.6 s        |
| 32 | 7.7 s       | 9.3 s        | 7.3 s       | 11.7 s       | 4.1 s       | 3.7 s        |

### Plots to produce

**Plot 1 — Execution time vs thread count (one subplot per algorithm)**
- x-axis: thread count t (log2 scale: 2, 4, 8, 16, 32)
- y-axis: execution time in seconds
- Two lines per subplot: `dyn=true` (blue, solid) and `dyn=false` (orange, dashed)
- Error bars: ±1 standard deviation across the 20 measurements
- Three subplots side by side: FT, CG, EP
- Caption note: dyn=true runs t/2 threads each (no oversubscription); dyn=false runs t threads each (2× oversubscribed)

**Plot 2 — DRM speedup vs thread count**
- x-axis: thread count t
- y-axis: speedup = `time_dyn_false / time_dyn_true` (>1 means DRM wins)
- Three lines: FT, CG, EP
- Horizontal reference line at y=1 (no difference)
- Annotate the peak values (CG +60% at t=32, FT +21% at t=32, EP −8% at t=32)

---

## 3. Staggered Experiment

### Data location

```
data/staggered/
  {alg}_t32_off10_{A1|A2|B1|B2}.log    # per-iteration timing
  {alg}_t32_off10_rm.log               # DRM grants log
  {alg}_t32_off10_{A1|A2}_drm.log      # per-thread CPU pinning log
```

- `alg` ∈ `{ft, cg, ep}`
- t=32, offset=10s, 15 iterations per worker

### Log format (timing)

```
# label=A1 dyn=true t=32 alg=ft
# iter  start_epoch_ms  duration_ms  time_in_seconds
1  1782649512517  4574  4.02
2  1782649517602  8042  7.54
...
```

Columns: `iter`, `start_epoch_ms`, `duration_ms`, `time_in_seconds`

- Use `start_epoch_ms` as the x-axis (convert to seconds relative to A1's first start)
- Use `time_in_seconds` (or `duration_ms / 1000`) as y-axis
- Plot each iteration as a point at `start_epoch_ms + duration_ms/2` (midpoint) or just at `start_epoch_ms`

### What the experiment shows

- A1 and B1 start together. After ~10s, A2 and B2 join.
- **A side (dyn=true):** DRM renegotiates: grants 32 → 16+16 threads and pins A1 to CPUs 1–16, A2 to CPUs 17–32
- **B side (dyn=false):** No coordination. B1+B2 both run 32 threads on 32 CPUs → 64 total → 2× oversubscribed
- At the end: last process remaining gets full resources back (visible as faster final iterations)

### Expected patterns per algorithm

**FT:** A and B degrade similarly (~10s each). DRM provides no advantage here because FT is memory-bandwidth bound and strict CPU partitioning halves bandwidth per process.

**CG:** A degrades to ~7.6s; B degrades to ~11.7s. Clear DRM advantage (~53%). CG is irregular and cache-sensitive — B suffers from cross-process cache thrashing that DRM prevents.

**EP:** B is faster than A (~3s vs ~7s). EP is compute-bound; DRM limits A to 16 threads, B runs 32. Expected negative control.

### Plots to produce

**Plot 3 — Timeline: iteration time vs wall-clock time (one subplot per algorithm)**
- x-axis: wall-clock time in seconds since experiment start (derived from `start_epoch_ms` - min across all workers)
- y-axis: `time_in_seconds` per iteration
- Four series per subplot: A1 (blue solid), A2 (blue dashed), B1 (orange solid), B2 (orange dashed)
- Vertical dashed line at t=10s marking when A2/B2 join
- Each data point plotted at the midpoint of its iteration: `start_epoch_ms + duration_ms/2 - t0`
- Three subplots: FT (top), CG (middle), EP (bottom)

**Plot 4 — Steady-state comparison bar chart (staggered)**
- For each algorithm, show mean iteration time in steady state (iters 3–13, excluding solo iters and end iters)
- Grouped bars: A (DRM) vs B (no DRM)
- Show standard deviation as error bars
- Annotate the CG bars with the % difference

### Parsing the DRM pinning log (optional Plot 5)

```
[DRM-pin] pid=112063 tid=112089 assigned=1-16 running_on=5
```

Fields: pid, tid, assigned range (base-top), running_on (CPU at time of pinning call).

**Plot 5 — CPU assignment distribution (staggered, A side only)**
- For each unique assigned range, count how many pin events occur
- Stacked bar or pie chart showing: `1-32` (solo), `1-16` (correct A1), `17-32` (correct A2), other (3-client windows)
- Shows that the 2-client ideal split dominates, with brief non-ideal windows at iteration boundaries
- Only use entries from job 187129 (filter by pid ranges from that job, or just use the CG drm logs which have no `0--1` entries)

---

## 4. Style Recommendations

- Use matplotlib with a clean academic style (`plt.style.use('seaborn-v0_8-whitegrid')` or similar)
- Consistent color scheme across all plots: blue = DRM (dyn=true), orange = no DRM (dyn=false)
- Font size ≥ 11pt for readability in thesis (two-column format typical)
- Save as PDF (vector) for thesis inclusion: `plt.savefig('plot.pdf', bbox_inches='tight')`
- All plots should have: title, axis labels with units, legend, grid

---

## 5. Key Messages Each Plot Should Convey

| Plot | Message |
|------|---------|
| 1 (time vs t) | DRM advantage grows with thread count for FT and CG; EP is unaffected |
| 2 (speedup) | CG peaks at +60%, FT at +21%, EP at −8% — confirms memory-bound benefit |
| 3 (timeline) | DRM dynamically rebalances when new processes join; B degrades sharply for CG |
| 4 (steady-state bars) | CG: DRM cuts steady-state time nearly in half; FT: wash; EP: B wins (expected) |
| 5 (CPU assignment) | Pinning is correct during the 2-client phase (0 mismatches); 3-client windows are brief |

---

## 6. Environment

```bash
cd <repo root>
# Python available via:
uv python  # or python3
# Existing analysis script (mpstat/pidstat visualization):
experiments/analyze_cpu_util.py
```

Output plots should go to:
```
<repo root>/output/
```
(create if it doesn't exist)
