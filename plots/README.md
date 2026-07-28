
## Windows PowerShell:

```powershell
uv run python .\src\plots\main.py
```

## Thesis scalability model

The configuration-level Amdahl--Karp--Flatt analysis reads the 600 raw
process outputs under `NPB3.4-OMP/benchmarks/dual`, validates the expected
two-process cells, fits one effective scaling-loss fraction per kernel and
condition, performs launch-group bootstrap resampling and a `t=32` forward
hold-out check, and exports the model data and thesis figure:

```bash
python export_scalability_model.py
```

Outputs:

- `plots/model/amdahl_karp_flatt_summary.csv`
- `plots/model/amdahl_karp_flatt_points.csv`
- `../figures/amdahl_karp_flatt_capacity.pdf`

The exporter uses only the Python standard library and does not require
Kaleido or a browser.
