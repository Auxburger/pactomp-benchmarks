from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.cpu_layout import LayoutError, expand_mask, pick_layout  # noqa: E402


# Two nodes of 8 CPUs on separate sockets, as CoolMUC-4 presents them.
TWO_NODES = {cpu: (0 if cpu < 8 else 1) for cpu in range(16)}


def node_of(cpu: int) -> int:
    return TWO_NODES[cpu]


class MaskTest(unittest.TestCase):
    def test_ranges_and_singles_expand(self) -> None:
        self.assertEqual(expand_mask("0-3,8,12-13"), [0, 1, 2, 3, 8, 12, 13])

    def test_empty_mask_is_rejected(self) -> None:
        with self.assertRaises(LayoutError):
            pick_layout("  ", 2, node_of=node_of, sockets={})


class LayoutTest(unittest.TestCase):
    def layout(self, mask="0-15", domain=4, sockets=None):
        return pick_layout(mask, domain, node_of=node_of, sockets=sockets if sockets is not None else {})

    def test_coordinator_takes_the_first_cpu_of_worker_a(self) -> None:
        layout = self.layout()
        self.assertEqual(layout.rm_cpu, 0)
        self.assertNotIn(layout.rm_cpu, layout.cpus_a)

    def test_workers_land_on_separate_nodes(self) -> None:
        layout = self.layout()
        self.assertNotEqual(layout.node_a, layout.node_b)
        self.assertEqual(layout.cpus_a, [1, 2, 3, 4])
        self.assertEqual(layout.cpus_b, [8, 9, 10, 11])

    def test_separate_sockets_are_preferred(self) -> None:
        sockets = {cpu: (0 if cpu < 8 else 1) for cpu in range(16)}
        layout = self.layout(sockets=sockets)
        self.assertNotEqual(sockets[layout.cpus_a[0]], sockets[layout.cpus_b[0]])

    def test_too_few_cpus_is_rejected(self) -> None:
        with self.assertRaises(LayoutError):
            self.layout(domain=8)  # needs 9 on node A, only 8 exist

    def test_shell_format_is_three_lines(self) -> None:
        lines = self.layout().format().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "0")
        self.assertEqual(lines[1], "0 1,2,3,4")
        self.assertEqual(lines[2], "1 8,9,10,11")

    def test_domain_cpus_below_one_is_rejected(self) -> None:
        with self.assertRaises(LayoutError):
            self.layout(domain=0)


if __name__ == "__main__":
    unittest.main()
