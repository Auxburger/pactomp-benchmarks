---
name: DRM benchmark final results
description: Final benchmark results for dual and dual-exclusive experiments, key thesis finding
type: project
---

Experiments completed on CoolMUC-4, NPB3.4-OMP Class C (FT, CG, EP).

**dual-exclusive (1 process per NUMA domain, no contention):** dyn=true ≈ dyn=false for EP and FT. CG dyn=true ~8% faster even alone. DRM adds zero overhead when no contention.

**dual (2 concurrent processes, exclusive CPU partitions, t/2 threads each):** DRM wins at every benchmark and thread count. CG t=32: +26%, FT t=32: +12%.

**Key thesis result:** With DRM, 2 concurrent processes take ~2× single-process time (near-perfect fair-share). Without DRM (dyn=false oversubscribed): 2.2–2.4× single-process time.

**Why:** DRM grants exactly t/2 threads to each of 2 clients on t/2 exclusive CPUs = no oversubscription. dyn=false uses t threads on t/2 CPUs = 2× oversubscribed, OS scheduler adds super-linear penalty.
