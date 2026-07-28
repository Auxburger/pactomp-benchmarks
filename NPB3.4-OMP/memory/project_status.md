---
name: Thesis project current status
description: What has been completed and what comes next
type: project
---

**Completed:**
- All three bugs fixed (fair_share.rs hint boost, KMP_DYNAMIC_MODE, sequential iterations)
- CPU-set partitioning implemented in test_all.sh (exclusive per-iteration tasksets)
- DRM restarts per thread count with matching capacity
- Full benchmark runs: dual (2 concurrent, exclusive partitions) and dual-exclusive (1 process baseline)
- Meeting notes in German: `/dss/dsshome1/09/ga27qam2/master-thesis/meeting-notes-2026-03-09.md`
- Technical report: `/dss/dsshome1/09/ga27qam2/master-thesis/NPB3.4-OMP/REPORT.md`

**Next:** Write thesis chapter on experimental methodology and results. Compare dual vs dual-exclusive to quantify fair-share overhead vs benefit.
