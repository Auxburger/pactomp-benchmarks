# Projektstatus

## Abgeschlossen

- Alle drei Bugs behoben:
  1. `fair_share.rs` — Hint-Boost entfernt (Fair-Share wurde überschrieben)
  2. `KMP_DYNAMIC_MODE=thread_limit` — Load-Average-Serialisierung in LLVM-Runtime verhindert
  3. `test-one.sh` — Iterationen parallelisiert (Fair-Share wurde nie ausgelöst)
- CPU-Set-Partitionierung in `test_all.sh` (exklusive Tasksets pro Iteration)
- DRM wird pro Thread count neu gestartet mit passender Kapazität (`DRM_CAPACITY=t`)
- Benchmark-Läufe abgeschlossen:
  - `benchmarks/dual/` — 2 nebenläufige Prozesse, exklusive CPU-Partitionen
  - `benchmarks/dual-exclusive/` — 1 Prozess als Baseline ohne Konkurrenz
- Besprechungsnotizen (Deutsch): `/dss/dsshome1/09/ga27qam2/master-thesis/meeting-notes-2026-03-09.md`
- Technischer Bericht: `REPORT.md`

## Nächste Schritte

- Thesis-Kapitel zu experimenteller Methodik und Ergebnissen schreiben
- dual vs. dual-exclusive vergleichen um Fair-Share-Overhead vs. Nutzen zu quantifizieren
