# Staggered Results Handover

This document records all staggered DRM experiments.
It supplements `THESIS_HANDOVER.md` in the thesis repository and
[PLOTTING_HANDOVER.md](PLOTTING_HANDOVER.md).

**Current ground truth: job 187303** (2026-06-29).
Where numbers differ from earlier jobs, 187303 governs.

---

## 1. TL;DR

Under strict per-worker CPU pinning (fork-barrier affinity), the staggered
experiment shows a DRM benefit for **CG only**:

| Alg | A (DRM) | B (no DRM) | B/A  | DRM effect            |
|-----|---------|------------|------|-----------------------|
| CG  | 7.58 s  | 12.32 s    | 1.62 | **DRM saves 38 %** ✓  |
| FT  | 11.36 s | 9.24 s     | 0.81 | DRM 19 % slower       |
| EP  | 6.66 s  | 3.22 s     | 0.48 | DRM ~2× slower        |

(Steady-state mean over iterations 3–13, t=32, from job 187303.)

The pattern is consistent across all staggered runs (187129, 187202, 187303):
CG benefits from exclusive CPU partitioning; FT loses bandwidth due to pinning;
EP is an honest negative control with pinning instability.

---

## 2. All staggered jobs

| Job    | Date       | Offset        | Iters | Status           |
|--------|------------|---------------|-------|------------------|
| 187129 | 2026-06-26 | 10 s          | 15    | Superseded       |
| 187180 | 2026-06-29 | 2 s (cg/ft), 1 s (ep) | 1 | Smoke test — do not use for numbers |
| 187202 | 2026-06-29 | 2 s (cg/ft), 1 s (ep) | 15 | Superseded       |
| **187303** | **2026-06-29** | **10 s (cg/ft), 5 s (ep)** | **15** | **Canonical** |

All live under `data/staggered/<job>/`.

### Why 187303 is the canonical run

187303 has the 10 s offset (same as 187129), which is long enough to show the
join dynamics — A1 runs solo at 32 threads for ~10 s, then A2 joins and the DRM
renegotiates to 16+16. With only 1–2 s offset (187202), the second worker joins
almost immediately and the join/leave dynamics are invisible. EP uses a 5 s offset
because its iterations are shorter. All three use 15 iterations → reliable
steady-state statistics from iters 3–13.

The `rm.log` for each algorithm in 187303 confirms the correct
`32 → 16+16 → 32` renegotiation on A2 join. All `.err` logs are empty (clean run).

---

## 3. Per-algorithm findings (job 187303, iters 3–13)

**CG — DRM win (headline positive result).**
A (16+16 split): 7.58 s — consistent across workers (A1: 7.62 s, A2: 7.54 s).
B (64 threads on 32 CPUs): 12.32 s — also consistent (B1: 12.41 s, B2: 12.23 s).
Cross-process cache thrashing under oversubscription costs B ~62 % vs A.
The DRM's spatial isolation is the decisive factor here.

**FT — DRM clear loss (−19 %).**
A: 11.36 s vs B: 9.24 s. The fork-barrier pinning confines A1 to CPUs 1–16 and
A2 to CPUs 17–32, halving each process's available memory bandwidth. FT is
bandwidth-bound, so B's full 32-CPU bandwidth beats A despite 2× oversubscription.
This is the pinning bandwidth penalty identified in insight #8 of THESIS_HANDOVER.md.
The unpinned main dual experiment shows FT at +21 % — the DRM's *thread count
coordination* does help FT; it is only the spatial partitioning that harms it.

**EP — DRM clearly worse and unstable.**
A: 6.66 s vs B: 3.22 s. The A side oscillates between ~3.6 and ~7.1 s within
the same run (A1 iters 3–13: 7.10, 7.09, 7.12, 7.20, 3.60, 7.20, 3.65, …).
EP is compute-bound with short per-iteration processes, triggering the documented
3-client / CPU-pinning instability at iteration boundaries. Honest negative
control. The 500 ms inter-iteration sleep in the staggered script reduces but does
not eliminate this effect for EP.

---

## 4. Comparison to earlier runs

| Alg | 187202 A | 187202 B | 187202 B/A | 187303 A | 187303 B | 187303 B/A |
|-----|----------|----------|-----------|----------|----------|-----------|
| CG  | 8.05 s   | 11.99 s  | 1.49      | 7.58 s   | 12.32 s  | 1.62      |
| FT  | 10.04 s  | 9.32 s   | 0.93      | 11.36 s  | 9.24 s   | 0.81      |
| EP  | 6.74 s   | 3.26 s   | 0.48      | 6.66 s   | 3.22 s   | 0.48      |

The CG DRM advantage is stronger in 187303 (38 % vs 33 %) because the longer
solo phase means A1 warms up its 32-thread pool before the split, and the
steady-state 16+16 window is cleaner. The FT loss is larger in 187303 (−19 %
vs −8 %) for the same reason: more steady-state iterations in the pinned phase
where the bandwidth penalty is fully expressed. EP is identical.

---

## 5. How to reproduce the numbers

Steady-state = iterations 3–13 (excludes warm-up iters 1–2 and the brief solo
end iters 14–15 where the other worker has already finished).

Log format:
```
<alg>_t32_off<o>_<A1|A2|B1|B2>.log
# iter  start_epoch_ms  duration_ms  time_in_seconds
```

A = mean of (mean(A1 iters 3–13) + mean(A2 iters 3–13)) / 2, similarly for B.
The same parse logic is in `plots/src/plots/staggered_parsing.py`.

Plots exist under `plots/plots/staggered/187303/` (cpu_placement, cpu_pins,
cpu_slab, threads, timeline per alg, plus cpu_util and steadystate_summary).
Regenerate with `cd plots && uv run python ./src/plots/main.py`.

---

## 6. What the thesis needs to say

The staggered section must clearly separate two DRM contributions:

1. **Thread count coordination** (visible in unpinned main dual experiment):
   reduces oversubscription → helps both CG (+60 %) and FT (+21 %).

2. **Spatial CPU partitioning** (fork-barrier pinning, visible in staggered):
   prevents cross-process cache thrashing → helps CG (+38 %); *hurts* FT (−19 %)
   by halving per-process memory bandwidth.

EP is a negative control for both: compute-bound workloads gain nothing from
thread count reduction, and the pinning instability is an explicit limitation
of the current implementation for short-lived per-iteration processes.

---

## 7. Open questions

- **EP instability** should be framed as a limitation of pinning short-lived
  processes; increasing class size or using a single long-lived worker would
  stabilize it but change the benchmark character.
- **FT in staggered**: consider acknowledging in the thesis that spatial pinning
  harms bandwidth-bound kernels, and the net DRM value for FT comes from the
  unpinned path (thread count coordination only).
