# Staggered Results Handover

This document records the staggered DRM experiment.
It supplements `THESIS_HANDOVER.md` in the thesis repository and
[PLOTTING_HANDOVER.md](PLOTTING_HANDOVER.md).

**Current ground truth: job 209445** (2026-09-04), under
`data/staggered/209445/`. It is the only staggered job the thesis cites.

---

## 1. TL;DR

Steady-state mean over iterations 3–13 at t=32:

| Alg | A (DRM) | B (no DRM) | B/A  | DRM effect           |
|-----|---------|------------|------|----------------------|
| CG  | 7.76 s  | 11.69 s    | 1.51 | **DRM saves 34 %** ✓ |
| FT  | 11.09 s | 9.76 s     | 0.88 | DRM 12 % slower      |
| EP  | 14.30 s | 6.88 s     | 0.48 | DRM ~2× slower       |

CG benefits from exclusive CPU partitioning; FT loses memory bandwidth to it;
EP is harmed most.

---

## 2. Every grant carries a CPU interval

This is the property that separates 209445 from every earlier staggered job.
Check it on any future run before trusting the numbers:

```sh
grep -c '(CPUs [0-9]*+0)' data/staggered/<job>/*_rm.log   # want: 0
```

209445 has **0 of 2898** grants without an interval.

Earlier jobs had 17.8 %, concentrated in FT (31 %) and EP (61 %), because the
coordinator searched for a free CPU slice first-fit against the ranges other
clients happened to hold. A client that requested while it was alone kept a
slice covering the whole pool, and every later client then found no free block
and ran unpinned. Those runs therefore mixed pinned and unpinned regions, and
their per-algorithm numbers are not comparable with these. The coordinator now
derives each slice from the client's rank among the active clients
(`assign_cpus` in the coordinator's `state.rs`).

---

## 3. Per-algorithm findings (job 209445, iters 3–13)

**CG — DRM win (headline positive result).**
A (16+16 split): 7.76 s. B (64 threads on 32 CPUs): 11.69 s. Cross-process
cache thrashing under oversubscription costs B about half again as much as A.
Spatial isolation is the decisive factor.

**FT — DRM loss (−12 %).**
A: 11.09 s vs B: 9.76 s. Fork-barrier pinning confines A1 to CPUs 1–16 and A2
to CPUs 17–32, halving each process's available memory bandwidth. FT is
bandwidth-bound, so B's full 32-CPU bandwidth beats A despite 2×
oversubscription.

**EP — DRM clearly worse, and highly variable.**
A: 14.30 s vs B: 6.88 s. The A side ranges from 6.3 s to 22.8 s and drifts
upward over the trace, while B stays near 6.9 s with little spread.
Assignments are well formed — a full interval while one client is visible,
disjoint halves once two are — so this is the cost of confining a
compute-bound kernel, not an assignment defect. Grant *sizes* still vary
(32/16/10/8 threads) because every iteration is a new process and the manager
briefly observes a different client count at iteration boundaries.

**Solo phase** (iteration 1, before the second worker joins), useful as a
placement sanity check: FT 4.28 s, CG 3.59 s, EP 3.62 s on the A side, with B
within a few percent.

---

## 4. How to reproduce the numbers

Steady state = iterations 3–13 (excludes warm-up iters 1–2 and the brief solo
end where the other worker has already finished).

Log format:
```
<alg>_t32_off<o>_<A1|A2|B1|B2>.log
# iter  start_epoch_ms  duration_ms  time_in_seconds
```

A = mean of (mean(A1 iters 3–13), mean(A2 iters 3–13)), similarly for B. The
same parse logic is in `src/analysis/datasets/staggered.py`.

Regenerate the exploratory plots with `uv run python src/main.py`; the thesis
PDFs come from `export_thesis_figs.py`, whose `JOB_DIR` points at this job.

---

## 5. What the thesis says

The staggered section reports this as a demonstrative trace with per-iteration
timings, not as a replicated performance measurement — one job, no
repetitions. It combines team-size coordination with spatial partitioning, so
an effect cannot be attributed to either mechanism alone.

---

## 6. Open questions

- **Separating the two mechanisms.** A staggered run with `POMP_CPU_LIST`
  unset would coordinate thread counts without pinning, which is the control
  needed to attribute FT's bandwidth loss.
- **EP's upward drift** across the trace is unexplained.
- **No domain alternation.** A1/A2 always sit on the first domain and B1/B2 on
  the second, so condition stays confounded with NUMA domain here. The main and
  uncontended experiments alternate; this one has no repetition dimension to
  alternate over, so it would need two runs with swapped sides.
