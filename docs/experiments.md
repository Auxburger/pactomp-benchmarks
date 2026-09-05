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
├── tracing/<JID>/                # Tracing-Microbenchmark (omp_dyn.c)
│   ├── run_<r>/omp/*.out         # stdout + Affinity-Trace pro Prozess
│   ├── timings.csv               # eine Zeile pro Prozess
│   ├── manifest.json             # argv, git rev, Compile-Kommando, Quell-Hash
│   └── rm.log                    # DRM-Log
├── mix/<JID>/                    # Gemischte Last (Seed-Schedule, zwei Arme)
│   ├── schedule.json             # gezogener Schedule — mit --schedule wiederholbar
│   ├── iterations.csv            # eine Zeile pro Benchmark-Prozess, beide Arme
│   ├── summary.json              # Kennzahlen pro Arm/Job + drm/nodrm-Vergleich
│   ├── manifest.json             # argv, git rev, Seed, CPU-Layout, Konfiguration
│   ├── drm/J01_ft.out            # rohes stdout pro Job, ein Block pro Iteration
│   ├── nodrm/J01_ft.out
│   └── rm.log                    # DRM-Log (nur Arm drm)
├── dual-exclusive/               # Vergleichsläufe auf exklusivem Knoten
└── slurm_logs/                   # SLURM stdout/stderr Logs

experiments/
├── paths.sh                      # Zentrale Pfadauflösung (von allen Skripten gesourct)
├── run_npb_tiny.sbatch           # SLURM Job-Skript (Hauptexperiment)
├── run_staggered.sbatch          # SLURM Job-Skript (gestaffeltes Experiment)
├── run_npb_exclusive.sbatch      # SLURM Job-Skript (exklusiver Knoten)
├── run_llvm_tracing.sbatch       # SLURM Job-Skript (Tracing-Microbenchmark)
├── run_mix.sbatch                # SLURM Job-Skript (gemischte Last)
├── test_all.sh                   # Haupt-Orchestrierungsskript
├── test_staggered.sh             # Gestaffeltes Experiment (A2/B2 mit Zeitversatz)
├── test-one.sh                   # Führt einen Benchmark aus (1 Iteration)
├── build_omp.sh                  # Baut die LLVM OpenMP Runtime (libomp.so)
├── build_npb.sh                  # Installiert make.def, baut die NPB-Binaries
└── make.def                      # NPB-Build-Konfiguration (kanonische Kopie)

NPB3.4-OMP/                       # Unveränderte NPB 3.4.3 (Drittanbieter-Code)
└── bin/                          # Kompilierte NPB-Binaries (gitignored)

src/harness/                      # läuft auf dem Cluster — nur stdlib, kein uv
├── paths.py                      # Python-Spiegel von experiments/paths.sh
├── cpu_layout.py                 # NUMA-Picker (früher Heredoc in den .sh)
├── coordinator.py                # DRM starten/stoppen
├── children.py, logging_utils.py, record.py
├── npb_out.py                    # NPB-Zusammenfassungsblock parsen (gemeinsam genutzt)
├── tracing/                      # Tracing-Microbenchmark + Treiber
│   ├── omp_dyn.c                 # Microbenchmark (zwei parallele Regionen)
│   ├── config.py, build.py, runner.py, record.py, sweep.py
│   └── legacy/                   # die abgelösten Shell-Skripte, zur Referenz
└── mix/                          # Gemischte Last: Seed-Schedule, zwei Arme
    ├── schedule.py               # Schedule ziehen/speichern/wiederholen
    ├── config.py, runner.py, record.py, experiment.py

src/analysis/                     # läuft lokal — datasets/, plots/, reports/, model/

src/main.py                       # Einstiegspunkt: Analyse-Pipeline
src/run_llvm_tracing.py           # Einstiegspunkt: Tracing-Sweep
src/run_mix.py                    # Einstiegspunkt: gemischte Last
src/analyze_cpu_util.py           # Einstiegspunkt: CPU-Auslastungs-Figur
src/pick_cpus.py                  # Einstiegspunkt: NUMA-Picker für die .sh

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

### `tracing` — Tracing-Microbenchmark

Ersetzt die früheren Shell-Skripte (jetzt in `src/harness/tracing/legacy/`). Statt NPB läuft
`omp_dyn.c`: zwei parallele Regionen mit Busy-Loop und eine NPB-förmige
Zusammenfassung. Der Treiber übersetzt die Quelle gegen die gepatchte Runtime
und fährt pro Thread count zwei nebenläufige Prozesse — einmal mit
`OMP_DYNAMIC=true`, einmal mit `false` — bei aktivem `OMP_DISPLAY_AFFINITY`.

Damit lässt sich das Verhalten der Runtime (Grant, Thread-Team-Größe,
Affinität) ohne den Umweg über die NPB-Kernel nachvollziehen. Die
Ausgabedateien heißen wie die der NPB-Läufe, `src/main.py` erzeugt daraus die
Gruppe `output/tracing/`.

**Worker-Lifecycle-Modus.** `--region-sizes 16,4,4` ersetzt die beiden
Busy-Regionen durch eine Folge von Regionen mit den angegebenen Teamgrößen.
Jeder Thread protokolliert pro Region seine OpenMP-Nummer, sein
`pthread_self`-Handle *und* seine Linux-Thread-ID; die native Thread-Anzahl des
Prozesses wird aus `/proc/self/task` vor und nach jeder Region gemessen. Damit
wird die Beobachtung rekonstruierbar, dass eine spätere kleinere Region die
Identitäten der früheren größeren wiederverwendet und die native
Worker-Population dabei nicht schrumpft. Ohne DRM laufen lassen (`--no-drm`),
sonst überlagert ein Grant die `num_threads`-Klausel.

### `mix` — Gemischte Last (Seed-Schedule)

Mehrere verschiedene NPB-Kernel starten mit zufälligem Offset und laufen für
ein zufälliges Zeitfenster; jeder Job wiederholt seinen Kernel, bis sein
Fenster endet. Die Anzahl gleichzeitiger OpenMP-Prozesse steigt und fällt also
so, wie es auf einem geteilten Knoten tatsächlich passiert.

Alles Zufällige kommt aus `--seed`: Algorithmus, Offset und Fenster jedes Jobs.
Derselbe Schedule wird zweimal abgespielt — als Arm `drm` mit laufendem
Koordinator und `OMP_DYNAMIC=true`, als Arm `nodrm` ohne beides:

| | Arm `drm` | Arm `nodrm` |
|---|---|---|
| Koordinator | läuft, `POMP_CAPACITY` = CPUs der Domain | wird nicht gestartet |
| `OMP_DYNAMIC` | `true` → Runtime fragt ihren Anteil an | `false` → jeder Job nimmt alle Threads |
| Überlastung | keine — Grants summieren sich zur Kapazität | `n_aktiv × threads` auf `domain_cpus` |

Beide Arme laufen auf demselben NUMA-Knoten, nacheinander statt gleichzeitig:
ein Arm sättigt die Domain schon allein, es bleibt also kein zweiter Knoten
zum Vergleich im selben Moment. Vergleichbar macht die Arme der Seed, nicht die
Gleichzeitigkeit — das ist der einzige Unterschied im Aufbau gegenüber `dual`
und `staggered`.

Kennzahl ist die Zahl abgeschlossener Iterationen pro Job: beide Arme bekommen
identische Zeitfenster, der Arm mit mehr fertiger Arbeit darin gewinnt
(`summary.json`, `comparison.iterations_gain_pct`).

---

## Jobs ausführen

```bash
# Hauptexperiment
sbatch --clusters=cm4 experiments/run_npb_tiny.sbatch

# Gestaffeltes Experiment
sbatch --clusters=cm4 experiments/run_staggered.sbatch

# Tracing-Microbenchmark (weitere Argumente gehen an run_llvm_tracing.py)
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch
sbatch --clusters=cm4 experiments/run_llvm_tracing.sbatch --runs 3 --threads 2,4,8,16,32

# Gemischte Last (weitere Argumente gehen an run_mix.py)
sbatch --clusters=cm4 experiments/run_mix.sbatch
sbatch --clusters=cm4 experiments/run_mix.sbatch --seed 7 --jobs 8

# Tracing lokal, ohne SLURM
python3 src/run_llvm_tracing.py --build --out /tmp/tracing --no-drm

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
