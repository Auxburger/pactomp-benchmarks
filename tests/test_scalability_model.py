from __future__ import annotations

from dataclasses import replace
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from analysis.model.amdahl import (  # noqa: E402
    KERNELS,
    MODES,
    THREAD_COUNTS,
    Observation,
    fit_all,
    karp_flatt_fraction,
    load_dual_observations,
    predict_runtime,
)


class ScalabilityModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observations = load_dual_observations(
            REPO_ROOT / "data" / "dual" / "224633"
        )

    def test_complete_raw_dataset_is_loaded(self) -> None:
        self.assertEqual(len(self.observations), 600)

    def test_prediction_reproduces_baseline(self) -> None:
        self.assertEqual(predict_runtime(42.0, 1.0, 0.2), 42.0)

    def test_karp_flatt_is_zero_for_ideal_scaling(self) -> None:
        self.assertAlmostEqual(karp_flatt_fraction(8.0, 8.0), 0.0)

    def test_checked_in_headline_fits_are_reproduced(self) -> None:
        fits, _ = fit_all(self.observations, bootstrap_samples=100, seed=1)
        by_cell = {(fit.kernel, fit.mode): fit for fit in fits}
        self.assertAlmostEqual(
            by_cell[("FT", "dynamic=true")].effective_fraction,
            0.009527473470275888,
            places=8,
        )
        self.assertAlmostEqual(
            by_cell[("CG", "dynamic=false")].effective_fraction,
            0.0799224941325036,
            places=8,
        )

    def test_bootstrap_does_not_couple_run_labels_across_pool_sizes(self) -> None:
        # Identical run-label multipliers at every size would cancel completely
        # if a single sampled label set were incorrectly shared across sizes.
        observations = [
            Observation(
                run=f"run_{run}", kernel=kernel, threads=threads, mode=mode,
                process=process, seconds=(20.0 + run) * 2.0 / threads,
            )
            for kernel in KERNELS
            for mode in MODES
            for threads in THREAD_COUNTS
            for run in range(1, 11)
            for process in (1, 2)
        ]
        fits, _ = fit_all(observations, bootstrap_samples=300, seed=1)
        for fit in fits:
            self.assertAlmostEqual(fit.effective_fraction, 0.0)
            self.assertLess(fit.ci_low, -0.001)
            self.assertGreater(fit.ci_high, 0.001)
        # Identical conditions stay identical because four-process launches
        # are sampled together, preserving the within-launch pairing.
        for enabled, unmanaged in zip(fits[::2], fits[1::2]):
            self.assertEqual(enabled.ci_low, unmanaged.ci_low)
            self.assertEqual(enabled.ci_high, unmanaged.ci_high)

    def test_process_outcomes_remain_in_their_launch_cluster(self) -> None:
        # Offset the two outcomes oppositely, preserving every launch mean.
        # Treating processes as independent replicates would change the bounds.
        shifted = [
            replace(obs, seconds=obs.seconds + (1 if obs.process == 1 else -1))
            for obs in self.observations
        ]
        original, _ = fit_all(self.observations, bootstrap_samples=100, seed=1)
        modified, _ = fit_all(shifted, bootstrap_samples=100, seed=1)
        for a, b in zip(original, modified):
            self.assertAlmostEqual(a.ci_low, b.ci_low)
            self.assertAlmostEqual(a.ci_high, b.ci_high)


if __name__ == "__main__":
    unittest.main()
