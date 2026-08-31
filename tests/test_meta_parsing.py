from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.datasets.meta import parse_cpu_splits, parse_meta  # noqa: E402


META = """start Sat Jun 28 14:02:11 CEST 2026 host cm4tiny host mask 0-88
==== t=32 r=1 ====
alg=ft start Sat Jun 28 14:02:12 CEST 2026
alg=cg start Sat Jun 28 14:02:30 CEST 2026
==== t=32 r=2 ====
alg=ep start Sat Jun 28 14:03:00 CEST 2026
"""

SLURM = """Cpus_allowed_list: 0-88
t=4 | A_pool: [1,2,3,4] | B_pool: [56-59]
t=8 | A_pool: [1-8] | B_pool: [56-63]
unrelated line
"""


class MetaTest(unittest.TestCase):
    def events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "meta.txt"
            path.write_text(META, encoding="utf-8")
            return parse_meta(path)

    def test_job_start_and_three_benchmarks(self) -> None:
        events = self.events()
        self.assertEqual([e["event"] for e in events],
                         ["start", "alg_start", "alg_start", "alg_start"])

    def test_benchmark_events_carry_their_run_context(self) -> None:
        ft, cg, ep = self.events()[1:]
        self.assertEqual((ft["alg"], ft["t"], ft["r"]), ("ft", 32, 1))
        self.assertEqual((cg["alg"], cg["t"], cg["r"]), ("cg", 32, 1))
        self.assertEqual((ep["alg"], ep["t"], ep["r"]), ("ep", 32, 2))


class CpuSplitTest(unittest.TestCase):
    def splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "slurm.out"
            path.write_text(SLURM, encoding="utf-8")
            return parse_cpu_splits(path)

    def test_one_entry_per_thread_count(self) -> None:
        self.assertEqual(sorted(self.splits()), [4, 8])

    def test_a_pool_is_halved_between_the_drm_workers(self) -> None:
        split = self.splits()[4]
        self.assertEqual(split["A1"], [1, 2])
        self.assertEqual(split["A2"], [3, 4])

    def test_b_workers_share_the_whole_pool(self) -> None:
        split = self.splits()[4]
        self.assertEqual(split["B1"], [56, 57, 58, 59])
        self.assertEqual(split["B1"], split["B2"])

    def test_ranges_expand(self) -> None:
        self.assertEqual(self.splits()[8]["A1"], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
