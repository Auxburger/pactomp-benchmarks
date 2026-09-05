from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.cpu_layout import (  # noqa: E402
    LayoutError,
    expand_mask,
    one_cpu_per_core,
    pick_domain,
    pick_layout,
)


# Two nodes of 8 CPUs on separate sockets, as CoolMUC-4 presents them.
TWO_NODES = {cpu: (0 if cpu < 8 else 1) for cpu in range(16)}


def node_of(cpu: int) -> int:
    return TWO_NODES[cpu]


# A cm4 node as SLURM presents it: 2 NUMA nodes x 56 cores, the second SMT
# thread of core n numbered n+112.
CM4_CORES = 56
CM4_THREAD_OFFSET = 112


def cm4_node_of(cpu: int) -> int:
    return (cpu % CM4_THREAD_OFFSET) // CM4_CORES


def cm4_core_of(cpu: int) -> int:
    return cpu % CM4_THREAD_OFFSET


def cm4_domain(mask: str, domain_cpus: int = 32, **kwargs):
    return pick_domain(mask, domain_cpus, node_of=cm4_node_of, core_of=cm4_core_of, **kwargs)


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


class SiblingFilterTest(unittest.TestCase):
    def test_only_the_lowest_thread_of_each_core_survives(self) -> None:
        self.assertEqual(
            one_cpu_per_core([0, 1, 112, 113], core_of=cm4_core_of), [0, 1]
        )

    def test_a_core_present_only_as_its_sibling_is_kept(self) -> None:
        self.assertEqual(one_cpu_per_core([112, 113], core_of=cm4_core_of), [112, 113])


class Cm4DomainTest(unittest.TestCase):
    """The allocations this experiment actually sees on cm4_tiny."""

    def test_a_full_node_puts_the_domain_on_one_numa_node(self) -> None:
        domain = cm4_domain("0-223")
        self.assertEqual(domain.node, 0)
        self.assertEqual(domain.rm_cpu, 0)
        self.assertEqual(domain.cpus, list(range(1, 33)))

    def test_smt_siblings_never_enter_the_domain(self) -> None:
        # The dual runs' own mask: 89 cores plus every sibling.
        domain = cm4_domain("0-88,112-200")
        self.assertTrue(all(cpu < CM4_THREAD_OFFSET for cpu in domain.cpus))
        self.assertEqual(len({cm4_core_of(c) for c in domain.cpus}), len(domain.cpus))

    def test_a_fragmented_mask_still_yields_one_node(self) -> None:
        # A real staggered-run mask: a foreign job held cores 9-22.
        domain = cm4_domain("0-8,23-102,112-120,135-214")
        self.assertEqual({cm4_node_of(cpu) for cpu in domain.cpus}, {domain.node})
        self.assertEqual(len(domain.cpus), 32)
        self.assertNotIn(domain.rm_cpu, domain.cpus)

    def test_an_even_split_shrinks_the_domain_instead_of_aborting(self) -> None:
        # 32 free cores per socket: neither node fits 32 workload + coordinator.
        domain = cm4_domain("0-31,56-87")
        self.assertEqual(len(domain.cpus), 31)
        self.assertEqual({cm4_node_of(cpu) for cpu in domain.cpus}, {domain.node})

    def test_strict_domain_aborts_on_the_same_mask(self) -> None:
        with self.assertRaises(LayoutError):
            cm4_domain("0-31,56-87", strict=True)

    def test_a_node_below_the_floor_is_rejected(self) -> None:
        with self.assertRaises(LayoutError):
            cm4_domain("0-4,56-60", min_cpus=8)

    def test_sub_numa_clustering_would_shrink_not_crash(self) -> None:
        # If SNC were ever enabled, nodes are 14 cores — too small for 32.
        snc_node_of = lambda cpu: (cpu % CM4_THREAD_OFFSET) // 14  # noqa: E731
        domain = pick_domain("0-223", 32, node_of=snc_node_of, core_of=cm4_core_of)
        self.assertEqual(len(domain.cpus), 13)


class DomainTest(unittest.TestCase):
    """The single-worker variant, used by the mixed workload experiment."""

    def domain(self, mask="0-15", domain_cpus=4):
        return pick_domain(mask, domain_cpus, node_of=node_of)

    def test_coordinator_sits_beside_the_workload_on_one_node(self) -> None:
        domain = self.domain()
        self.assertEqual(domain.rm_cpu, 0)
        self.assertEqual(domain.node, 0)
        self.assertEqual(domain.cpus, [1, 2, 3, 4])

    def test_the_node_with_the_most_allowed_cpus_wins(self) -> None:
        domain = self.domain(mask="0-1,8-15")
        self.assertEqual(domain.node, 1)
        self.assertEqual(domain.cpus, [9, 10, 11, 12])

    def test_a_node_without_room_for_the_coordinator_is_rejected(self) -> None:
        with self.assertRaises(LayoutError):
            self.domain(domain_cpus=8)  # needs 9 CPUs on one node, only 8 exist

    def test_empty_mask_and_zero_domain_are_rejected(self) -> None:
        with self.assertRaises(LayoutError):
            pick_domain("  ", 4, node_of=node_of)
        with self.assertRaises(LayoutError):
            self.domain(domain_cpus=0)


if __name__ == "__main__":
    unittest.main()
