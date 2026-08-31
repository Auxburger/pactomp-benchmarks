"""Pick the CPU layout for a two-worker experiment.

Both workers need `domain_cpus` CPUs on separate NUMA nodes, and the DRM
coordinator needs one more CPU on worker A's node. Preferring nodes on
different sockets keeps the two workers from sharing a memory controller.

Was duplicated as a heredoc inside test_all.sh and test_staggered.sh; the
staggered copy had drifted and lost its error handling.
"""

from __future__ import annotations

import glob
import os
import subprocess
from collections import defaultdict
from dataclasses import dataclass


class LayoutError(Exception):
    """No layout satisfies the request — reported to the shell as ERROR + exit 2."""


@dataclass(frozen=True)
class Layout:
    rm_cpu: int
    node_a: int
    cpus_a: "list[int]"
    node_b: int
    cpus_b: "list[int]"

    def format(self) -> str:
        """The three lines the shell scripts read back via readarray."""
        return "\n".join(
            [
                str(self.rm_cpu),
                f"{self.node_a} {','.join(map(str, self.cpus_a))}",
                f"{self.node_b} {','.join(map(str, self.cpus_b))}",
            ]
        )


def expand_mask(mask: str) -> "list[int]":
    """Expand a Cpus_allowed_list string ("0-3,8,12-13") into CPU numbers."""
    out: "list[int]" = []
    for part in mask.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def node_of(cpu: int) -> int:
    for path in glob.glob(f"/sys/devices/system/cpu/cpu{cpu}/node*"):
        name = os.path.basename(path)
        if name.startswith("node"):
            return int(name[4:])
    return -1


def socket_map() -> "dict[int, int]":
    """CPU → socket, from lscpu. Empty when lscpu is unavailable."""
    try:
        txt = subprocess.check_output(["lscpu", "-e=CPU,SOCKET,NODE"], universal_newlines=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    mapping = {}
    for line in txt.strip().splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2:
            mapping[int(fields[0])] = int(fields[1])
    return mapping


def pick_layout(
    mask: str,
    domain_cpus: int,
    node_of=node_of,
    sockets: "dict[int, int] | None" = None,
) -> Layout:
    """Choose worker A (coordinator + domain_cpus) and worker B (domain_cpus).

    node_of and sockets are injectable so the choice can be tested without
    touching /sys or lscpu.
    """
    if not mask.strip():
        raise LayoutError("empty CPU mask")
    if domain_cpus < 1:
        raise LayoutError(f"domain_cpus={domain_cpus} too small")

    by_node: "dict[int, list[int]]" = defaultdict(list)
    for cpu in expand_mask(mask):
        by_node[node_of(cpu)].append(cpu)

    candidates = sorted((n, sorted(v)) for n, v in by_node.items() if n >= 0)
    need_a = 1 + domain_cpus  # coordinator + worker A
    need_b = domain_cpus

    good_a = [(n, v) for n, v in candidates if len(v) >= need_a]
    good_b = [(n, v) for n, v in candidates if len(v) >= need_b]
    if not good_a or not good_b:
        sizes = " ".join(f"node{n}={len(v)}" for n, v in candidates)
        raise LayoutError(
            f"not enough CPUs per NUMA within allowed mask: {sizes} "
            f"(needA={need_a}, needB={need_b})"
        )

    if sockets is None:
        sockets = socket_map()
    good_a.sort(key=lambda nv: len(nv[1]), reverse=True)
    good_b.sort(key=lambda nv: len(nv[1]), reverse=True)

    # Prefer two nodes on different sockets; fall back to any two distinct nodes.
    best = None
    for node_a, cpus_a in good_a:
        socket_a = sockets.get(cpus_a[0], -1)
        for node_b, cpus_b in good_b:
            if node_b == node_a:
                continue
            socket_b = sockets.get(cpus_b[0], -1)
            if socket_a != -1 and socket_b != -1 and socket_a != socket_b:
                best = (node_a, cpus_a, node_b, cpus_b)
                break
        if best:
            break
    if best is None:
        node_a, cpus_a = good_a[0]
        node_b, cpus_b = next(((n, v) for n, v in good_b if n != node_a), good_b[0])
        best = (node_a, cpus_a, node_b, cpus_b)

    node_a, cpus_a, node_b, cpus_b = best
    return Layout(
        rm_cpu=cpus_a[0],
        node_a=node_a,
        cpus_a=cpus_a[1 : 1 + domain_cpus],
        node_b=node_b,
        cpus_b=cpus_b[:domain_cpus],
    )


def current_mask() -> str:
    """This process's Cpus_allowed_list, as the shell scripts read it."""
    with open("/proc/self/status", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("Cpus_allowed_list:"):
                return line.split(":", 1)[1].strip()
    return ""
