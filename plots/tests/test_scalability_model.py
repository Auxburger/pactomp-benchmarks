from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLOTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLOTS_ROOT.parent
sys.path.insert(0, str(PLOTS_ROOT / "src"))

from plots.scalability_model import (  # noqa: E402
    fit_all,
    karp_flatt_fraction,
    load_dual_observations,
    predict_runtime,
)


class ScalabilityModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observations = load_dual_observations(
            REPO_ROOT / "data" / "dual"
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
            0.0102185251,
            places=8,
        )
        self.assertAlmostEqual(
            by_cell[("CG", "dynamic=false")].effective_fraction,
            0.0767434730,
            places=8,
        )


if __name__ == "__main__":
    unittest.main()
