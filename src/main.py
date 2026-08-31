"""Entry point for the analysis pipeline.

Discovers the measurement records under data/ and writes every figure group to
output/<group>/. Each report skips itself when its outputs are already newer
than its inputs.

    uv run python src/main.py           # newest staggered job only
    uv run python src/main.py --all     # every staggered job
    uv run python src/main.py --static  # also export PDFs (requires kaleido)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis.reports.drm import process_monitoring_logs  # noqa: E402
from analysis.reports.freshness import up_to_date  # noqa: E402
from analysis.reports.npb import build_groups, process_group  # noqa: E402
from analysis.reports.staggered import process_staggered_logs  # noqa: E402
from analysis.reports.tracing import process_tracing_runs  # noqa: E402


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show-raw", action="store_true", help="Overlay raw points", default=True)
    ap.add_argument("--static", action="store_true", help="Also export PDF (requires kaleido).", default=False)
    ap.add_argument("--png", action="store_true", help="Also export PNG next to each HTML (requires kaleido).", default=False)
    ap.add_argument("--combined", action="store_true", help="Combined multi-benchmark HTML per group (facets).", default=True)
    ap.add_argument("--all", dest="all_jobs", action="store_true",
                    help="Process all staggered jobs; default is newest only.")
    return ap.parse_args()


def process_npb_runs(sources: list[tuple[str, Path]], out_dir: Path, args: argparse.Namespace) -> None:
    """The aggregated dual / dual-exclusive benchmark figures."""
    run_dirs: list[tuple[str, Path]] = []
    for source_name, root in sources:
        run_dirs.extend((source_name, p) for p in root.iterdir() if p.is_dir())
    run_dirs = sorted(run_dirs, key=lambda sp: (sp[0], sp[1].name))

    groups = build_groups(run_dirs)
    if not groups:
        roots = ", ".join(str(p.resolve()) for _, p in sources)
        raise SystemExit(f"No suitable run directories found under: {roots}")

    for group_name, dirs in groups:
        if up_to_date([p for _, p in dirs], out_dir / group_name):
            print(f"Group {group_name}: up to date, skipping.")
            continue
        process_group(
            group_name,
            dirs,
            out_dir=out_dir,
            show_raw=args.show_raw,
            static=args.static,
            combined=args.combined,
        )


def main() -> None:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    data_root = repo_root / "data"
    out_dir = repo_root / "output"

    sources = [
        ("dual-exclusive", data_root / "dual-exclusive"),
        ("dual", data_root / "dual"),
    ]
    missing = [root for _, root in sources if not root.exists()]
    if missing:
        raise SystemExit("benchmarks root(s) not found: " + ", ".join(str(p.resolve()) for p in missing))

    process_npb_runs(sources, out_dir, args)
    process_monitoring_logs([root for _, root in sources], out_dir, static=args.static, png=args.png)

    tracing_dir = data_root / "tracing"
    if tracing_dir.exists():
        process_tracing_runs(
            tracing_dir,
            out_dir,
            show_raw=args.show_raw,
            static=args.static,
            combined=args.combined,
        )

    staggered_dir = data_root / "staggered"
    if staggered_dir.exists():
        process_staggered_logs(
            staggered_dir, out_dir, static=args.static, png=args.png,
            newest_only=not args.all_jobs,
        )

    print("All done.")


if __name__ == "__main__":
    main()
