# DRM Benchmark Final Results

## dual-exclusive (1 Prozess pro NUMA-Domain, keine Konkurrenz)

- EP und FT: dyn=true ≈ dyn=false — der DRM fügt keinen Overhead hinzu, wenn keine Konkurrenz besteht
- CG: dyn=true ~8% schneller auch ohne Konkurrenz
- Beweist: DRM ist transparent wenn nur ein Client aktiv ist

## dual (2 nebenläufige Prozesse, exklusive CPU-Partitionen, je t/2 Threads)

- DRM gewinnt bei **jedem** Benchmark und Thread count
- CG t=32: **+26%**, FT t=32: **+12%**, EP t=32: **+3%**

## Kernaussage

| | dual-exclusive (1 Proc) | dual (2 Proc) | Faktor |
|---|---|---|---|
| FT dyn=true  | 4.0 s | 7.8 s | **1.95×** ≈ 2× |
| FT dyn=false | 4.0 s | 8.8 s | **2.19×** |
| CG dyn=true  | 3.6 s | 7.4 s | **2.05×** ≈ 2× |
| CG dyn=false | 3.9 s | 9.3 s | **2.38×** |

Mit DRM: 2 nebenläufige Prozesse brauchen ~2× die Zeit eines einzelnen Prozesses (perfektes Fair-Share).
Ohne DRM: 2.2–2.4× — Überlastung verursacht super-linearen Penalty.

## Warum

- **dyn=true:** DRM vergibt t/2 Threads auf t/2 exklusive Kerne → keine Überlastung, t Threads auf t Kernen gesamt
- **dyn=false:** t Threads auf t/2 Kernen (2× überlastet) → OS-Scheduler-Nicht-Determinismus, hohe Varianz
