from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{2,4})")


def parse_cpu_util(path: Path, min_pct_usr: float = 10.0) -> pd.DataFrame:
    """Parse mpstat -P ALL output → tidy DataFrame.

    Returns only per-CPU rows (not 'all') for CPUs that are ever above
    min_pct_usr, keeping columns: ts, cpu, pct_usr, pct_sys, pct_idle.
    Elapsed seconds (elapsed_sec) are added relative to the first timestamp.
    """
    records: list[dict] = []
    date_str: str | None = None
    current_ts: datetime | None = None

    with open(path, errors="replace") as f:
        for line in f:
            line = line.rstrip()

            if line.startswith("Linux"):
                m = _DATE_RE.search(line)
                if m:
                    date_str = m.group(1)
                continue

            if not line or "CPU" in line or "%usr" in line:
                continue

            parts = line.split()
            if len(parts) < 12:
                continue

            # Time field is the first token; may repeat at the start of each block
            ts_str = parts[0]
            cpu_str = parts[1]

            if cpu_str == "all":
                # Use this row just to capture the timestamp
                if date_str:
                    try:
                        current_ts = datetime.strptime(f"{date_str} {ts_str}", "%m/%d/%y %H:%M:%S")
                    except ValueError:
                        try:
                            current_ts = datetime.strptime(f"{date_str} {ts_str}", "%m/%d/%Y %H:%M:%S")
                        except ValueError:
                            pass
                continue

            if current_ts is None or not cpu_str.isdigit():
                continue

            try:
                cpu = int(cpu_str)
                pct_usr = float(parts[2])
                pct_sys = float(parts[4])
                pct_idle = float(parts[11])
            except (ValueError, IndexError):
                continue

            records.append({
                "ts": current_ts,
                "cpu": cpu,
                "pct_usr": pct_usr,
                "pct_sys": pct_sys,
                "pct_idle": pct_idle,
            })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # Keep only CPUs that are ever meaningfully busy
    active_cpus = df.groupby("cpu")["pct_usr"].max()
    active_cpus = active_cpus[active_cpus >= min_pct_usr].index
    df = df[df["cpu"].isin(active_cpus)].copy()

    if df.empty:
        return df

    t0 = df["ts"].min()
    df["elapsed_sec"] = (df["ts"] - t0).dt.total_seconds()
    return df.sort_values(["cpu", "ts"]).reset_index(drop=True)
