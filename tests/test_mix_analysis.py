from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.datasets.mix import (  # noqa: E402
    load_mix_iterations,
    load_mix_schedule,
    mix_concurrency,
)

JOB_DIR = REPO_ROOT / "data" / "mix" / "209466"


class MixDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.iterations = load_mix_iterations(JOB_DIR)
        cls.schedule = load_mix_schedule(JOB_DIR)

    def test_schedule_labels_match_the_iteration_labels(self) -> None:
        self.assertEqual(
            set(self.schedule["label"]),
            set(self.iterations["label"]),
        )

    def test_iteration_end_follows_its_start(self) -> None:
        self.assertTrue((self.iterations["end_sec"] > self.iterations["start_sec"]).all())

    def test_overrunning_iterations_reach_past_their_window(self) -> None:
        overran = self.iterations[self.iterations["overran_window"]]
        self.assertFalse(overran.empty)
        self.assertTrue((overran["end_sec"] > overran["window_end"]).all())

    def test_concurrency_never_exceeds_the_job_count(self) -> None:
        arm = self.iterations[
            (self.iterations["arm"] == "drm") & (self.iterations["repeat"] == 1)
        ]
        concurrency = mix_concurrency(arm)
        self.assertEqual(concurrency["running"].max(), len(self.schedule))
        self.assertEqual(concurrency["running"].iloc[-1], 0)

    def test_concurrency_of_an_empty_frame_is_empty(self) -> None:
        self.assertTrue(mix_concurrency(self.iterations.head(0)).empty)


if __name__ == "__main__":
    unittest.main()
