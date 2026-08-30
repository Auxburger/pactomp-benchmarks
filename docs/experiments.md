# DRM Benchmark Suite — Experiment Setup

Benchmarking-Setup für die Evaluierung des Dynamic Resource Managers (DRM) auf LRZ CoolMUC-4.

---

## Überblick

Zwei OpenMP-Prozesse laufen gleichzeitig auf demselben NUMA-Knoten und konkurrieren um CPU-Ressourcen:

- **Worker A (`dyn=true`):** OpenMP-Prozesse nutzen den DRM. Der DRM vergibt über Fair-Share genau `t/2` Threads auf `t` gemeinsam genutzten Kernen → insgesamt `t` Threads auf `t` Kernen, keine Überlastung.
- **Worker B (`dyn=false`):** OpenMP-Prozesse ignorieren den DRM und nutzen alle `t` Threads auf `t` gemeinsamen Kernen → insgesamt `2t` Threads auf `t` Kernen → immer 2× überlastet.

Beide Worker laufen auf getrennten NUMA-Knoten. Die Taskset-Größe wird pro Thread count `t` dynamisch angepasst.

---

## Verzeichnisstruktur

```
data/                             # Messdaten (unveränderlich)
├── dual/                         # Hauptexperiment: 2 nebenläufige Prozesse
│   ├── run_1/ … run_10/          # Pro Run: Ausgabedateien pro Benchmark/Thread count
│   ├── <RUNTAG>/
│   │   ├── node0/meta.txt        # Zeitstempel Worker A (NUMA node 0)
│   │   └── node1/meta.txt        # Zeitstempel Worker B (NUMA node 1)
│   ├── rm.log                    # DRM-Log (Grants, Kapazität, Clients)
│   ├── cpu_util_<JID>.log        # mpstat-Log (per-CPU Auslastung alle 5s)
│   └── pidstat_<JID>.log         # pidstat-Log (Prozess→CPU Zuordnung alle 5s)
├── staggered/<JID>/              # Gestaffeltes Experiment (zeitversetzter Start)
│   ├── <alg>_t<t>_off<s>_A1.log  # Worker A1: per-Iteration Zeiten
│   ├── <alg>_t<t>_off<s>_A2.log  # Worker A2
│   ├── <alg>_t<t>_off<s>_B1.log  # Worker B1
│   ├── <alg>_t<t>_off<s>_B2.log  # Worker B2
│   └── <alg>_t<t>_off<s>_rm.log  # DRM-Log
├── dual-exclusive/               # Vergleichsläufe auf exklusivem Knoten
└── slurm_logs/                   # SLURM stdout/stderr Logs

experiments/
├── paths.sh                      # Zentrale Pfadauflösung (von allen Skripten gesourct)
├── run_npb_tiny.sbatch           # SLURM Job-Skript (Hauptexperiment)
├── run_staggered.sbatch          # SLURM Job-Skript (gestaffeltes Experiment)
├── run_npb_exclusive.sbatch      # SLURM Job-Skript (exklusiver Knoten)
├── test_all.sh                   # Haupt-Orchestrierungsskript
├── test_staggered.sh             # Gestaffeltes Experiment (A2/B2 mit Zeitversatz)
├── test-one.sh                   # Führt einen Benchmark aus (1 Iteration)
├── build_omp.sh                  # Baut die LLVM OpenMP Runtime (libomp.so)
├── build_npb.sh                  # Installiert make.def, baut die NPB-Binaries
├── make.def                      # NPB-Build-Konfiguration (kanonische Kopie)
└── analyze_cpu_util.py           # Analyse & Visualisierung der CPU-Auslastung

NPB3.4-OMP/                       # Unveränderte NPB 3.4.3 (Drittanbieter-Code)
└── bin/                          # Kompilierte NPB-Binaries (gitignored)

docs/
├── REPORT.md                     # Technischer Bericht (Bugs, Fixes, Ergebnisse)
└── experiments.md                # Diese Datei
```

---

## Szenarien

### `dual` — Hauptexperiment (2 nebenläufige Prozesse)

Pro Thread count `t` werden beide Worker auf genau `t` CPUs beschränkt (dynamische Taskset-Anpassung):

| | dyn=true (DRM) | dyn=false (Baseline) |
|---|---|---|
| Threads pro Prozess | `t/2` (vom DRM vergeben) | `t` (unkontrolliert) |
| CPUs (Taskset) | `t` (geteilt zwischen A1+A2) | `t` (geteilt zwischen B1+B2) |
| Gesamt-Threads | `t` auf `t` Kernen → 1:1 | `2t` auf `t` Kernen → 2× überlastet |

### `staggered` — Gestaffeltes Experiment

A1 und B1 starten zuerst mit vollem Zugriff. A2 und B2 starten nach `offset` Sekunden. Jeder Worker läuft mehrere sequenzielle Iterationen und protokolliert pro Iteration Zeit + Zeitstempel.

Zeigt die **dynamische Umverteilung** des DRM: A1 wird automatisch auf `t/2` Threads reduziert sobald A2 beitritt. B1 leidet sofort unter Überlastung ohne Koordination.

---

## Jobs ausführen

```bash
# Hauptexperiment
sbatch --clusters=cm4 experiments/run_npb_tiny.sbatch

# Gestaffeltes Experiment
sbatch --clusters=cm4 experiments/run_staggered.sbatch

# Status prüfen
squeue --clusters=cm4 --me

# Job abbrechen
scancel --clusters=cm4 <JOBID>
```

**SLURM-Parameter:**
- `--cpus-per-task=89 --hint=nomultithread` → 89 physische Kerne, aufgeteilt auf 2 NUMA-Domains
- `--partition=cm4_tiny`, `--clusters=cm4`
- Ausgaben: `data/slurm_logs/slurm-<JOBID>.out/.err`

---

## LLVM Runtime bauen

```bash
# Erstmalig (Configure + Build)
./experiments/build_omp.sh

# Nur Runtime neu bauen (nach Änderungen in kmp_resource_manager.cpp)
./experiments/build_omp.sh --runtime-only
```

NPB-Binaries müssen **nicht** neu kompiliert werden — sie laden `libomp.so` dynamisch aus `$LLVM_BUILD/lib/`.

---

## NPB-Binaries bauen

`NPB3.4-OMP/` ist eine unveränderte Kopie des NPB-3.4.3-Release, daher
liegt die Build-Konfiguration nicht darin. `build_npb.sh` installiert
`experiments/make.def` in den NPB-Baum und baut anschließend:

```bash
./experiments/build_npb.sh          # ft, cg, ep in Klasse C
./experiments/build_npb.sh C mg is  # explizite Klasse und Benchmark-Liste
```

Pfade zu den externen Checkouts kommen aus der Umgebung, mit Defaults relativ
zu `$HOME`:

```bash
LLVM_BUILD=/anderswo/llvm-project/build ./experiments/build_npb.sh
```

---

## Konfiguration (`test_all.sh`)

| Variable | Bedeutung |
|---|---|
| `algorithms` | Benchmarks: `ft cg ep` |
| `runs` | Wiederholungen pro Thread count (Standard: 10) |
| `threads` | Automatisch als Potenzen von 2 bis `domain_cpus` |
| `POMP_CAPACITY` | Wird pro `t` auf `t` gesetzt → Fair-Share gibt `t/2` pro Client |
| `POMP_CPU_LIST` | Erste `t` CPUs des A-Domains → DRM weist disjunkte Hälften zu |
| `KMP_DYNAMIC_MODE` | `thread_limit` — verhindert dass die LLVM-Runtime den DRM-Grant überschreibt |

---

## Ergebnisse analysieren

### Benchmark-Zeiten

Alle Ausgabedateien liegen unter `data/dual/run_<N>/<alg>/`:
```
<alg>_threads_<t>_dyn_<true|false>_<iter>.out
```

Schnelle Auswertung (Durchschnitt über alle Runs):
```bash
for bench in ft cg ep; do
  for t in 2 4 8 16 32; do
    for dyn in true false; do
      avg=$(grep -h "Time in seconds" \
        data/dual/run_{1..10}/${bench}/${bench}_threads_${t}_dyn_${dyn}_{1,2}.out \
        | awk '{s+=$NF; n++} END{printf "%.2f", s/n}')
      echo "$bench t=$t dyn=$dyn avg=${avg}s"
    done
  done
done
```

### CPU-Auslastung visualisieren

```bash
python3 experiments/analyze_cpu_util.py \
  data/dual/cpu_util_<JOBID>.log \
  data/dual/<RUNTAG>/node0/meta.txt \
  data/dual/<RUNTAG>/node1/meta.txt \
  --pidstat data/dual/pidstat_<JOBID>.log \
  --slurm-out data/slurm_logs/slurm-<JOBID>.out \
  --out cpu_utilisation.png
```

---

## Wichtige Umgebungsvariablen

| Variable | Wert | Bedeutung |
|---|---|---|
| `OMP_DISPLAY_AFFINITY` | `1` | Thread-Bindung in Ausgabedateien protokollieren |
| `KMP_DYNAMIC_MODE` | `thread_limit` | LLVM Load-Balance-Heuristik deaktivieren |
| `POMP_CAPACITY` | `t` (pro Thread count) | Kapazität des DRM-Schedulers |
| `POMP_CPU_LIST` | erste `t` CPUs des A-Domains | CPU-Pool für DRM-Zuweisung |

---

## Behobene Bugs

Siehe [REPORT.md](REPORT.md) für Details. Kurzfassung:

1. **`fair_share.rs`** — Hint-Boost überschrieb den Fair-Share-Grant → entfernt
2. **LLVM Runtime** — `dynamic_load_balance` serialisierte Parallelregionen → `KMP_DYNAMIC_MODE=thread_limit`
3. **`test-one.sh`** — Iterationen liefen sequenziell → auf parallele Ausführung umgestellt
4. **`OMP_PROC_BIND=spread`** — Überschrieb DRM-CPU-Pinning via `sched_setaffinity` → entfernt
5. **Taskset-Strategie** — Statische Halbierung ersetzt durch dynamische per-`t` Zuweisung
