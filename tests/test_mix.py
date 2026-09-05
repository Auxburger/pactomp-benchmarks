from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.mix import schedule as schedule_mod  # noqa: E402
from harness.mix.config import make_config, parse_args, parse_arms, parse_range  # noqa: E402
from harness.mix.experiment import arm_dir_name, arm_order  # noqa: E402
from harness.mix.record import compare, summarize_arm  # noqa: E402
from harness.mix.runner import IterationResult, build_env, command_for, run_arm  # noqa: E402

ALGORITHMS = ["ft", "cg", "ep"]

# A stand-in for an NPB binary: prints the summary block the runner parses.
STUB_BENCHMARK = """#!/bin/sh
sleep 0.2
echo " Time in seconds =                     0.20"
echo " Total threads   =                        4"
echo " Avail threads   =                        8"
echo " Mop/s total     =                  1234.50"
"""


def draw(seed: int = 42, n_jobs: int = 6) -> schedule_mod.Schedule:
    return schedule_mod.generate(
        seed=seed,
        n_jobs=n_jobs,
        algorithms=ALGORITHMS,
        offset_range=(0.0, 30.0),
        duration_range=(30.0, 90.0),
        threads=32,
    )


class ScheduleTest(unittest.TestCase):
    def test_the_same_seed_draws_the_same_schedule(self) -> None:
        self.assertEqual(draw().to_dict(), draw().to_dict())

    def test_a_different_seed_draws_a_different_schedule(self) -> None:
        self.assertNotEqual(draw(seed=1).to_dict(), draw(seed=2).to_dict())

    def test_the_first_job_starts_immediately(self) -> None:
        self.assertEqual(draw().jobs[0].start_offset, 0.0)

    def test_jobs_are_numbered_in_start_order(self) -> None:
        jobs = draw().jobs
        self.assertEqual([j.job_id for j in jobs], list(range(1, len(jobs) + 1)))
        self.assertEqual(
            [j.start_offset for j in jobs], sorted(j.start_offset for j in jobs)
        )

    def test_draws_stay_inside_the_requested_ranges(self) -> None:
        for job in draw(n_jobs=32).jobs:
            self.assertIn(job.algorithm, ALGORITHMS)
            self.assertGreaterEqual(job.duration, 30.0)
            self.assertLessEqual(job.duration, 90.0)
            self.assertLessEqual(job.start_offset, 30.0)

    def test_span_covers_the_last_window(self) -> None:
        sched = draw()
        self.assertEqual(
            sched.span, max(j.start_offset + j.duration for j in sched.jobs)
        )

    def test_zero_jobs_is_rejected(self) -> None:
        with self.assertRaises(schedule_mod.ScheduleError):
            draw(n_jobs=0)

    def test_a_saved_schedule_replays_verbatim(self) -> None:
        sched = draw()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schedule.json"
            sched.save(path)
            self.assertEqual(schedule_mod.load(path).to_dict(), sched.to_dict())

    def test_a_foreign_schedule_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schedule.json"
            path.write_text(json.dumps({"version": 99, "seed": 1, "jobs": [{}]}), encoding="utf-8")
            with self.assertRaises(schedule_mod.ScheduleError):
                schedule_mod.load(path)

    def test_an_incomplete_job_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schedule.json"
            payload = {"version": schedule_mod.SCHEDULE_VERSION, "seed": 1, "jobs": [{"job_id": 1}]}
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(schedule_mod.ScheduleError):
                schedule_mod.load(path)


class ArgumentParsingTest(unittest.TestCase):
    def test_ranges_accept_low_high_and_a_single_value(self) -> None:
        self.assertEqual(parse_range("5:20"), (5.0, 20.0))
        self.assertEqual(parse_range("7"), (7.0, 7.0))

    def test_an_inverted_range_is_rejected(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_range("20:5")

    def test_arms_must_be_known_and_distinct(self) -> None:
        self.assertEqual(parse_arms("nodrm,drm"), ["nodrm", "drm"])
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_arms("drm,drm")
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_arms("drm,maybe")

    def test_benchmark_binaries_follow_the_class_suffix(self) -> None:
        cfg = make_config(parse_args(["--out", "/tmp/mix-run", "--class", "B", "--npb-bin", "/opt/npb"]))
        self.assertEqual(cfg.binary_for("ft"), Path("/opt/npb/ft.B.x"))

    def test_jobs_are_pinned_with_taskset_not_preexec(self) -> None:
        cfg = make_config(parse_args(["--out", "/tmp/mix-run", "--npb-bin", "/opt/npb"]))
        job = draw().jobs[0]
        self.assertEqual(
            command_for(cfg, job, [4, 5, 6]),
            ["taskset", "-c", "4,5,6", f"/opt/npb/{job.algorithm}.C.x"],
        )
        self.assertEqual(command_for(cfg, job, []), [f"/opt/npb/{job.algorithm}.C.x"])

    def test_the_drm_arm_enables_omp_dynamic_and_the_baseline_does_not(self) -> None:
        cfg = make_config(parse_args(["--out", "/tmp/mix-run"]))
        job = draw().jobs[0]
        self.assertEqual(build_env(cfg, "drm", job)["OMP_DYNAMIC"], "true")
        self.assertEqual(build_env(cfg, "nodrm", job)["OMP_DYNAMIC"], "false")
        self.assertEqual(build_env(cfg, "drm", job)["OMP_NUM_THREADS"], str(job.threads))


def result(arm: str, job_id: int, iteration: int, seconds: float, repeat: int = 1) -> IterationResult:
    return IterationResult(
        arm=arm,
        repeat=repeat,
        job_id=job_id,
        label=f"J{job_id:02d}_ft",
        algorithm="ft",
        threads=32,
        iteration=iteration,
        start_offset=0.0,
        window_seconds=60.0,
        start_epoch_ms=0,
        start_since_arm_ms=1000 * (iteration - 1),
        wall_ms=int(seconds * 1000),
        time_seconds=seconds,
        mops_total=None,
        total_threads=16,
        avail_threads=32,
        overran_window=False,
        pid=1,
        exit_code=0,
    )


class SummaryTest(unittest.TestCase):
    def test_iterations_are_counted_per_job(self) -> None:
        results = [result("drm", 1, 1, 4.0), result("drm", 1, 2, 6.0), result("drm", 2, 1, 2.0)]
        summary = summarize_arm("drm", results)
        self.assertEqual(summary["iterations"], 3)
        self.assertEqual(summary["jobs"]["J01_ft"]["iterations"], 2)
        self.assertEqual(summary["jobs"]["J01_ft"]["mean_time_seconds"], 5.0)

    def test_comparison_reports_the_throughput_gain(self) -> None:
        drm = summarize_arm("drm", [result("drm", 1, i, 2.0) for i in range(1, 5)])
        nodrm = summarize_arm("nodrm", [result("nodrm", 1, i, 4.0) for i in range(1, 3)])
        c = compare([drm, nodrm])
        self.assertEqual(c["iterations_gain_pct"], 100.0)
        self.assertEqual(c["mean_time_speedup"], 2.0)

    def test_repeats_are_pooled_and_makespan_averaged_per_repeat(self) -> None:
        results = [
            result("drm", 1, 1, 2.0, repeat=1),
            result("drm", 1, 2, 2.0, repeat=1),
            result("drm", 1, 1, 2.0, repeat=2),
        ]
        summary = summarize_arm("drm", results)
        self.assertEqual(summary["repeats"], 2)
        self.assertEqual(summary["iterations"], 3)
        self.assertEqual(summary["jobs"]["J01_ft"]["iterations_per_repeat"], 1.5)
        # repeat 1 ends at 1000+2000, repeat 2 at 0+2000 -> mean 2.5 s, not 3.0
        self.assertEqual(summary["makespan_seconds"], 2.5)

    def test_comparison_needs_both_arms(self) -> None:
        drm = summarize_arm("drm", [result("drm", 1, 1, 2.0)])
        self.assertIsNone(compare([drm]))


class ArmOrderTest(unittest.TestCase):
    def test_the_order_alternates_so_drift_cancels(self) -> None:
        arms = ["drm", "nodrm"]
        self.assertEqual(
            [arm_order(arms, r) for r in (1, 2, 3, 4)],
            [["drm", "nodrm"], ["nodrm", "drm"], ["drm", "nodrm"], ["nodrm", "drm"]],
        )

    def test_each_arm_goes_first_equally_often_over_even_repeats(self) -> None:
        firsts = [arm_order(["drm", "nodrm"], r)[0] for r in range(1, 5)]
        self.assertEqual(firsts.count("drm"), firsts.count("nodrm"))

    def test_a_single_run_keeps_the_documented_directory_layout(self) -> None:
        self.assertEqual(arm_dir_name("drm", 1), "drm")
        self.assertEqual(arm_dir_name("drm", 2), "drm_r2")


class ArmRunTest(unittest.TestCase):
    """One arm end to end against the stub benchmark, no DRM involved."""

    def test_every_job_runs_inside_its_window_and_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            npb_bin = root / "bin"
            npb_bin.mkdir()
            stub = npb_bin / "ft.C.x"
            stub.write_text(STUB_BENCHMARK, encoding="utf-8")
            stub.chmod(0o755)

            cfg = make_config(
                parse_args(
                    ["--out", str(root / "out"), "--npb-bin", str(npb_bin), "--gap-seconds", "0"]
                )
            )
            sched = schedule_mod.Schedule(
                seed=0,
                jobs=[
                    schedule_mod.Job(1, "ft", 0.0, 0.5, 2),
                    schedule_mod.Job(2, "ft", 0.3, 0.5, 2),
                ],
            )
            results = run_arm(cfg, sched, "nodrm", sorted(os.sched_getaffinity(0)), root / "arm")

            self.assertEqual({r.job_id for r in results}, {1, 2})
            self.assertTrue(all(r.exit_code == 0 for r in results))
            self.assertTrue(all(r.time_seconds == 0.20 for r in results))
            self.assertTrue(all(r.total_threads == 4 for r in results))
            self.assertTrue((root / "arm" / "J01_ft.out").is_file())

    def test_a_job_starting_after_its_window_records_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_config(parse_args(["--out", str(root / "out"), "--npb-bin", str(root)]))
            sched = schedule_mod.Schedule(seed=0, jobs=[schedule_mod.Job(1, "ft", 0.2, 0.0, 2)])
            self.assertEqual(run_arm(cfg, sched, "nodrm", [0], root / "arm"), [])


if __name__ == "__main__":
    unittest.main()
