#!/usr/bin/env python3
"""
Visualise per-CPU utilisation from an mpstat log, annotated with which
benchmark application was running, which CPU partition it owned, and
which processes (from pidstat) were running on which CPUs.

Usage:
    uv run python src/analyze_cpu_util.py <cpu_util_log> <meta_a_txt> <meta_b_txt> \
        [--pidstat pidstat_<JOBID>.log] \
        [--slurm-out slurm-XXXX.out] \
        [--out plot.png]

Logs must have been produced with:
    mpstat -P ALL 5 >> cpu_util_<JOBID>.log
    pidstat -u -t 5 >> pidstat_<JOBID>.log

The mpstat and pidstat parsers live in src/analysis — this script only adds the
meta.txt/SLURM-log parsing and the composite matplotlib figure.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.cpu_util_parsing import parse_cpu_util
from analysis.monitoring_parsing import parse_pidstat


# ── parsers (meta.txt and SLURM log; the rest comes from analysis/) ──────────

def parse_meta(path: str):
    events, cur_t, cur_r = [], None, None
    with open(path) as f:
        for line in f:
            line = line.strip()
            m = re.match(r"start (.+?) host", line)
            if m:
                try:
                    ts = datetime.strptime(m.group(1), "%a %b %d %H:%M:%S %Z %Y")
                    events.append({"ts": ts, "event": "start", "t": None, "r": None, "alg": None})
                except Exception:
                    pass
                continue
            m = re.match(r"==== t=(\d+) r=(\d+)", line)
            if m:
                cur_t, cur_r = int(m.group(1)), int(m.group(2))
                continue
            m = re.match(r"alg=(\w+) start (.+)", line)
            if m:
                try:
                    ts = datetime.strptime(m.group(2), "%a %b %d %H:%M:%S %Z %Y")
                    events.append({"ts": ts, "event": "alg_start",
                                   "t": cur_t, "r": cur_r, "alg": m.group(1)})
                except Exception:
                    pass
    return events


def parse_cpu_splits(slurm_out: str):
    splits = {}
    pattern = re.compile(
        r"t=(\d+) \| A_pool: \[([^\]]*)\] \| B_pool: \[([^\]]*)\]"
    )
    def expand(s):
        if not s.strip():
            return []
        cpus = []
        for part in s.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-")
                cpus.extend(range(int(a), int(b) + 1))
            else:
                try:
                    cpus.append(int(part))
                except ValueError:
                    pass
        return cpus
    with open(slurm_out) as f:
        for line in f:
            m = pattern.search(line)
            if m:
                t = int(m.group(1))
                a_pool = expand(m.group(2))
                b_pool = expand(m.group(3))
                half = t // 2
                # A1/A2 get disjoint halves of the A pool (as assigned by DRM).
                # B1/B2 share the full B pool (oversubscribed, no DRM).
                splits[t] = {
                    "A1": a_pool[:half],
                    "A2": a_pool[half: half * 2],
                    "B1": b_pool,
                    "B2": b_pool,
                }
    return splits


# ── plotting ──────────────────────────────────────────────────────────────────

ALG_COLORS = {"ft": "#4C72B0", "cg": "#DD8452", "ep": "#55A868"}
PARTITION_COLORS = {
    "A1": "#d62728", "A2": "#ff7f0e",
    "B1": "#1f77b4", "B2": "#17becf",
}
PARTITION_LABELS = {
    "A1": "Worker A iter 1 (dyn=true)",
    "A2": "Worker A iter 2 (dyn=true)",
    "B1": "Worker B iter 1 (dyn=false)",
    "B2": "Worker B iter 2 (dyn=false)",
}


def make_plot(df_mpstat, df_pidstat, events_a, events_b, splits, out_path):
    t0 = df_mpstat["ts"].min()

    df_mpstat = df_mpstat.copy()
    df_mpstat["sec"] = (df_mpstat["ts"] - t0).dt.total_seconds()

    # CPU → partition (from the largest t split that covers it)
    cpu_partition, cpu_t_max = {}, {}
    for t, sp in splits.items():
        for part, cpus in sp.items():
            for c in cpus:
                if c not in cpu_t_max or t > cpu_t_max[c]:
                    cpu_t_max[c] = t
                    cpu_partition[c] = part

    pivot = df_mpstat.pivot_table(index="cpu", columns="sec", values="pct_usr", aggfunc="mean")
    cpu_order = sorted(pivot.index)
    pivot = pivot.loc[cpu_order]
    cpu_to_row = {c: i for i, c in enumerate(cpu_order)}

    # ── figure layout ─────────────────────────────────────────────────────────
    n_rows = 3 if df_pidstat is not None and not df_pidstat.empty else 2
    height_ratios = [7, 2, 1] if n_rows == 3 else [8, 1]
    fig, axes = plt.subplots(
        n_rows, 1, figsize=(22, 14),
        gridspec_kw={"height_ratios": height_ratios},
        sharex=True,
    )
    ax_heat = axes[0]
    ax_proc = axes[1] if n_rows == 3 else None
    ax_ann  = axes[-1]

    xmin = pivot.columns.min()
    xmax = pivot.columns.max()

    # ── heatmap ───────────────────────────────────────────────────────────────
    img = ax_heat.imshow(
        pivot.values, aspect="auto", origin="lower",
        cmap="hot_r", vmin=0, vmax=100,
        extent=[xmin, xmax, -0.5, len(cpu_order) - 0.5],
    )
    ax_heat.set_ylabel("CPU core #")
    ax_heat.set_yticks(range(len(cpu_order)))
    ax_heat.set_yticklabels(cpu_order, fontsize=5)

    for ytick, cpu in zip(ax_heat.get_yticklabels(), cpu_order):
        part = cpu_partition.get(cpu)
        if part:
            ytick.set_color(PARTITION_COLORS[part])

    prev_part = None
    for i, cpu in enumerate(cpu_order):
        part = cpu_partition.get(cpu)
        if part != prev_part and prev_part is not None:
            ax_heat.axhline(i - 0.5, color="white", linewidth=1.5, linestyle="--")
        prev_part = part

    # Partition labels on right
    ax_r = ax_heat.twinx()
    ax_r.set_ylim(ax_heat.get_ylim())
    ax_r.set_yticks([])
    part_idxs = defaultdict(list)
    for i, cpu in enumerate(cpu_order):
        part = cpu_partition.get(cpu)
        if part:
            part_idxs[part].append(i)
    for part, idxs in part_idxs.items():
        mid = np.mean(idxs)
        ax_r.text(1.002, mid / len(cpu_order), PARTITION_LABELS[part],
                  transform=ax_r.transAxes, fontsize=8,
                  color=PARTITION_COLORS[part], va="center")

    plt.colorbar(img, ax=ax_heat, label="CPU %usr", fraction=0.015, pad=0.01)

    # ── process scatter plot ───────────────────────────────────────────────────
    if ax_proc is not None and df_pidstat is not None and not df_pidstat.empty:
        df_p = df_pidstat.copy()
        df_p["sec"] = (df_p["ts"] - t0).dt.total_seconds()
        df_p = df_p[(df_p["sec"] >= xmin) & (df_p["sec"] <= xmax)]
        df_p["row"] = df_p["cpu"].map(cpu_to_row)
        df_p = df_p.dropna(subset=["row"])

        # Colour dots by which partition the CPU belongs to
        df_p["part"] = df_p["cpu"].map(cpu_partition)
        df_p["color"] = df_p["part"].map(PARTITION_COLORS).fillna("gray")

        ax_proc.scatter(
            df_p["sec"], df_p["row"],
            c=df_p["color"], s=4, alpha=0.5, linewidths=0,
        )
        ax_proc.set_ylabel("CPU core #\n(process location)")
        ax_proc.set_ylim(-0.5, len(cpu_order) - 0.5)
        ax_proc.set_yticks(range(0, len(cpu_order), max(1, len(cpu_order) // 10)))
        ax_proc.set_yticklabels(
            [cpu_order[i] for i in range(0, len(cpu_order), max(1, len(cpu_order) // 10))],
            fontsize=6,
        )

        # Add partition dividers
        prev_part = None
        for i, cpu in enumerate(cpu_order):
            part = cpu_partition.get(cpu)
            if part != prev_part and prev_part is not None:
                ax_proc.axhline(i - 0.5, color="gray", linewidth=0.8, linestyle="--")
            prev_part = part

        ax_proc.set_title("Process/thread CPU placement (pidstat, benchmark processes only)",
                          fontsize=8, loc="left")

    # ── benchmark annotation bar ──────────────────────────────────────────────
    all_events = sorted(
        [e for e in events_a + events_b if e["event"] == "alg_start"],
        key=lambda e: e["ts"],
    )
    ax_ann.set_xlim(xmin, xmax)
    ax_ann.set_ylim(0, 1)
    ax_ann.axis("off")

    for i, ev in enumerate(all_events):
        x = (ev["ts"] - t0).total_seconds()
        if x < xmin or x > xmax:
            continue
        alg = ev["alg"]
        color = ALG_COLORS.get(alg, "gray")
        ax_heat.axvline(x, color=color, linewidth=0.5, alpha=0.5)
        if ax_proc is not None:
            ax_proc.axvline(x, color=color, linewidth=0.5, alpha=0.5)
        label = f"t={ev['t']} {alg.upper()} r={ev['r']}"
        ypos = 0.6 if i % 2 == 0 else 0.05
        ax_ann.text(x, ypos, label, fontsize=5, rotation=90,
                    color=color, ha="center", va="bottom")

    ax_ann.set_xlabel("Time since job start (s)")

    # Legend
    alg_patches  = [mpatches.Patch(color=c, label=a.upper()) for a, c in ALG_COLORS.items()]
    part_patches = [mpatches.Patch(color=c, label=PARTITION_LABELS[p])
                    for p, c in PARTITION_COLORS.items()]
    ax_heat.legend(handles=alg_patches + part_patches,
                   loc="upper left", fontsize=7, ncol=2,
                   framealpha=0.7, title="Benchmark / Partition")

    fig.suptitle("Per-CPU Utilisation & Process Placement During NPB Benchmark Run",
                 fontsize=13)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved → {out_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cpu_log",  help="mpstat log  (cpu_util_<JOBID>.log)")
    ap.add_argument("meta_a",   help="META_A meta.txt")
    ap.add_argument("meta_b",   help="META_B meta.txt")
    ap.add_argument("--pidstat",    default=None, help="pidstat log (pidstat_<JOBID>.log)")
    ap.add_argument("--slurm-out",  default=None, help="SLURM stdout log")
    ap.add_argument("--out", default="cpu_utilisation.png")
    args = ap.parse_args()

    print("Parsing mpstat …")
    df_mpstat = parse_cpu_util(Path(args.cpu_log), min_pct_usr=0.0)
    if df_mpstat.empty:
        sys.exit("ERROR: no data parsed from mpstat log")
    print(f"  {len(df_mpstat)} records, {df_mpstat['cpu'].nunique()} CPUs")

    df_pidstat = None
    if args.pidstat:
        print("Parsing pidstat …")
        df_pidstat = parse_pidstat(Path(args.pidstat))
        if df_pidstat.empty:
            print("  WARNING: no benchmark processes found in pidstat log")
        else:
            print(f"  {len(df_pidstat)} thread records, "
                  f"commands: {df_pidstat['command'].unique()}")

    print("Parsing meta files …")
    events_a = parse_meta(args.meta_a)
    events_b = parse_meta(args.meta_b)

    splits = {}
    if args.slurm_out:
        print("Parsing CPU splits …")
        splits = parse_cpu_splits(args.slurm_out)
        print(f"  t = {sorted(splits)}")

    print("Rendering …")
    make_plot(df_mpstat, df_pidstat, events_a, events_b, splits, args.out)


if __name__ == "__main__":
    main()
