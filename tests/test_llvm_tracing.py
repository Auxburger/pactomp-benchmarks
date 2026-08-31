from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.tracing.config import (  # noqa: E402
    make_config,
    parse_args,
    parse_modes,
    parse_thread_list,
)
from harness.tracing.runner import cell_cpus, parse_out_file  # noqa: E402


SAMPLE_OUT = """PID: 4711
[REGION 1] pthread id: 1, omp tid: 0/8
 Iterations      =                        2
 Time in seconds =                         4.01
 Total threads   =                        8
 Avail threads   =                       16
 Mop/s total     =                     0.00
 Operation type  =           floating point
done
"""


class ArgumentParsingTest(unittest.TestCase):
    def test_thread_list_accepts_commas_and_whitespace(self) -> None:
        self.assertEqual(parse_thread_list("2,4, 8"), [2, 4, 8])

    def test_thread_list_rejects_non_positive(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_thread_list("2,0")

    def test_modes_map_to_booleans(self) -> None:
        self.assertEqual(parse_modes("true,false"), [True, False])

    def test_modes_reject_unknown_value(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_modes("maybe")

    def test_binary_defaults_into_the_output_directory(self) -> None:
        cfg = make_config(parse_args(["--out", "/tmp/tracing-run", "--no-drm"]))
        self.assertEqual(cfg.binary, Path("/tmp/tracing-run/omp"))
        self.assertFalse(cfg.drm)


class CpuSelectionTest(unittest.TestCase):
    allowed = [0, 1, 2, 3, 4, 5, 6, 7]

    def test_threads_mode_takes_the_first_t_cpus(self) -> None:
        self.assertEqual(cell_cpus("threads", 4, self.allowed), [0, 1, 2, 3])

    def test_threads_mode_falls_back_to_all_when_oversubscribed(self) -> None:
        self.assertEqual(cell_cpus("threads", 32, self.allowed), self.allowed)

    def test_none_mode_leaves_affinity_untouched(self) -> None:
        self.assertIsNone(cell_cpus("none", 4, self.allowed))


class OutputParsingTest(unittest.TestCase):
    def test_summary_block_is_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "omp_threads_8_dyn_true_1.out"
            path.write_text(SAMPLE_OUT, encoding="utf-8")
            self.assertEqual(parse_out_file(path), (4.01, 8, 16, 4711))


if __name__ == "__main__":
    unittest.main()
