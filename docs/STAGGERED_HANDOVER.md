# Staggered Results Handover

This document records the staggered DRM experiment.
It supplements `THESIS_HANDOVER.md` in the thesis repository and
[PLOTTING_HANDOVER.md](PLOTTING_HANDOVER.md).

**Current ground truth: job 224607** (2026-10-10), under
`data/staggered/224607/`, measured with coordinator revision `038e652`. It
replaces job 209445, which was removed from `data/` on 2026-10-10 and lives
on in the Git history.

> **Why 209445 was replaced.** Up to coordinator revision `7bd9ee8`, a client
> was removed from the active set only when its connection ended with EOF. FT
> and EP processes exit with an unread reply in the socket, which ends the
> connection with `Connection reset by peer`, so the dead process stayed
> active until it aged out after 5 s. The successor process of the same
> stream started immediately, so the coordinator saw three clients and
> granted 32/3 = 10 threads on CPUs 11–20 and 21–30 (838 of 1430 FT grants);
> the dead PID held rank 0, CPUs 1–10. 209445 therefore reported FT as 12 %
> slower managed (B/A 0.88) and EP as ~2× slower (0.48). CG was unaffected,
> and 224607 reproduces it (1.51 → 1.48).

---

## 1. TL;DR

Steady-state mean over iterations 3–13 at t=32:

| Alg | A (DRM) | B (no DRM) | B/A  | DRM effect               |
|-----|---------|------------|------|--------------------------|
| CG  | 7.84 s  | 11.64 s    | 1.48 | **DRM saves 33 %**       |
| FT  | 8.14 s  | 9.80 s     | 1.20 | **DRM saves 17 %**       |
| EP  | 7.67 s  | 6.88 s     | 0.90 | DRM 11 % slower, bimodal |

CG and FT favour the managed side, consistent with the main experiment
(t=32 ratios 1.51 and 1.13). EP is slower managed because of the activity
window, not a coordinator defect (§3).

---

## 2. Checks to run on every staggered job

Every grant must carry a CPU interval:

```sh
grep -c '(CPUs [0-9]*+0)' data/staggered/<job>/*_rm.log   # want: 0
```

Every accepted connection must end in a removal, and no grant may assume a
third client:

```sh
for f in data/staggered/<job>/*_rm.log; do
  echo "$f $(grep -c 'Accepted connection' $f)" \
       "$(grep -c -e 'removed from state' -e 'before first request' $f)"
done                                                        # want: equal
grep -c 'Granted 10 threads' data/staggered/<job>/*_rm.log  # want: 0
```

224607 passes all three: 0 of 2813 grants without an interval, 30 of 30
connections removed per kernel (FT and EP still reset, CG closes cleanly),
and no 10-thread grants.

The interval check dates from jobs before 209445, which had 17.8 %
interval-less grants because the coordinator searched for a free CPU slice
first-fit. The coordinator now derives each slice from the client's rank
among the active clients (`assign_cpus` in the coordinator's `state.rs`).

---

## 3. Per-algorithm findings (job 224607, iters 3–13)

**CG — DRM win.**
A (16+16 split): 7.84 s. B (64 threads on 32 CPUs): 11.64 s. Grants are only
16 on CPUs 1–16 or 17–32, and 32 while one client is alone.

**FT — DRM win.**
A: 8.14 s (7.7–8.6 s) vs B: 9.80 s. Grants and applied intervals match the
CG pattern (worker diagnostics: 1-16, 17-32 and 1-32 only).

**EP — DRM slower, bimodal.**
A: 7.67 s vs B: 6.88 s. A-side iterations take either ~5.8 s or ~11.2 s.
Every slow one is a process that received 16 threads on CPUs 17–32 while
its partner ran 32 threads on CPUs 1–32; every fast one received 32. EP
requests only twice per process, at start and in the final reporting
region, so during its ~6 s timed region it ages out of the coordinator's
5 s activity window. The next process then sees itself alone and gets the
full pool, giving 48 threads on 32 CPUs. This is the same mechanism behind
the asymmetric EP teams in the main experiment, not the reset defect.

**Solo phase** (iteration 1, before the second worker joins): FT 4.27 s,
CG 3.79 s, EP 3.62 s on the A side, with B within a few percent.

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
an effect cannot be attributed to either mechanism alone. The thesis text
still describes 209445; all reruns have landed (dual 224633, solo 224769),
so it is next to be revised.

---

## 6. Open questions

- **EP and the activity window.** Counting a client as active while its
  connection is open, instead of by request recency, would remove the
  asymmetric EP teams. It would change EP in every experiment, so it is
  future work, not a fix for these runs.
- **Separating the two mechanisms.** A staggered run with `POMP_CPU_LIST`
  unset would coordinate thread counts without pinning.
- **No domain alternation.** A1/A2 always sit on the first domain and B1/B2 on
  the second, so condition stays confounded with NUMA domain here. The main and
  uncontended experiments alternate; this one has no repetition dimension to
  alternate over, so it would need two runs with swapped sides.
