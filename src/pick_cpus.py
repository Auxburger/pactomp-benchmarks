#!/usr/bin/env python3
"""Print the CPU layout for a two-worker experiment, for the shell scripts.

    readarray -t PICK < <(python3 src/pick_cpus.py --domain-cpus 32)

Writes three lines — coordinator CPU, "<node> <cpus>" for worker A, the same
for worker B — or "ERROR <reason>" and exit code 2.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness.cpu_layout import LayoutError, current_mask, pick_layout  # noqa: E402


def main(argv: "list[str] | None" = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mask", default=None, help="Cpus_allowed_list (default: this process's own)")
    p.add_argument("--domain-cpus", type=int, required=True, help="CPUs per worker")
    args = p.parse_args(argv)

    try:
        layout = pick_layout(args.mask if args.mask is not None else current_mask(), args.domain_cpus)
    except LayoutError as exc:
        print(f"ERROR {exc}")
        return 2
    print(layout.format())
    return 0


if __name__ == "__main__":
    sys.exit(main())
