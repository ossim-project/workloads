#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

MICROBENCH = Path(__file__).resolve().parents[1]
COMMON = MICROBENCH / "common"


class BenchHelperTests(unittest.TestCase):
    def compile_and_run(self, source: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            c_file = tmpdir / "test.c"
            binary = tmpdir / "test"
            c_file.write_text(source)
            subprocess.run(
                ["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(COMMON),
                 "-o", str(binary), str(c_file)],
                check=True,
                text=True,
                capture_output=True,
            )
            return subprocess.run(
                [str(binary)], check=True, text=True, capture_output=True
            )

    def test_stats_compute_preserves_temporal_sample_order(self) -> None:
        result = self.compile_and_run(textwrap.dedent(r"""
            #include "bench.h"
            #include <inttypes.h>
            #include <stdio.h>

            int main(void)
            {
                uint64_t samples[] = { 5, 1, 3 };
                struct bench_stats st;

                bench_stats_compute(samples, 3, &st);
                printf("%" PRIu64 " %" PRIu64 " %" PRIu64 "\n",
                       samples[0], samples[1], samples[2]);
                return 0;
            }
        """))
        self.assertEqual(result.stdout, "5 1 3\n")

    def test_tail_counts_report_zero_and_extreme_samples(self) -> None:
        result = self.compile_and_run(textwrap.dedent(r"""
            #include "bench.h"

            int main(void)
            {
                uint64_t samples[] = {
                    0, 10001, 1000001, 10000001, 100000001, 1000000001
                };
                struct bench_tail_counts tails;

                bench_tail_counts_compute(samples, 6, &tails);
                bench_tail_counts_json(stdout, &tails);
                putchar('\n');
                return 0;
            }
        """))
        self.assertEqual(
            json.loads(result.stdout),
            {
                "zero": 1,
                "gt_10us": 5,
                "gt_1ms": 4,
                "gt_10ms": 3,
                "gt_100ms": 2,
                "gt_1s": 1,
            },
        )


class BenchmarkOutputTests(unittest.TestCase):
    def run_benchmark(self, name: str, *args: str) -> dict:
        bench_dir = MICROBENCH / name
        subprocess.run(
            ["make", "-C", str(bench_dir)],
            check=True,
            text=True,
            capture_output=True,
        )
        result = subprocess.run(
            [str(bench_dir / name), *args],
            check=True,
            text=True,
            capture_output=True,
        )
        return json.loads(result.stdout)

    def run_analyzer(self, name: str, row: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            (log_dir / "sample.log").write_text(json.dumps(row) + "\n")
            result = subprocess.run(
                ["python3", str(MICROBENCH / name / "analyze.py"), "--json", str(log_dir)],
                check=True,
                text=True,
                capture_output=True,
            )
        return json.loads(result.stdout)

    def test_timer_jitter_reports_cpu_clock_warmup_and_tails(self) -> None:
        cpu = min(os.sched_getaffinity(0))
        result = self.run_benchmark(
            "timer_jitter", "-p", "1", "-n", "4", "-w", "0", "-c", str(cpu)
        )
        self.assertEqual(result["clock"], "CLOCK_MONOTONIC")
        self.assertEqual(result["cpu"], cpu)
        self.assertEqual(result["warmup_iters"], 0)
        self.assertEqual(
            set(result["tail_counts"]),
            {"zero", "gt_10us", "gt_1ms", "gt_10ms", "gt_100ms", "gt_1s"},
        )

    def test_timer_analyzer_summarizes_cpu_warmup_and_tails(self) -> None:
        result = self.run_analyzer(
            "timer_jitter",
            {
                "bench": "timer_jitter",
                "clock": "CLOCK_MONOTONIC",
                "cpu": 1,
                "period_us": 1000,
                "warmup_iters": 100,
                "wake_latency_ns": {
                    "n": 10, "min": 1, "mean": 2.0, "p50": 2,
                    "p90": 3, "p99": 4, "max": 5,
                },
                "tail_counts": {
                    "zero": 0, "gt_10us": 4, "gt_1ms": 3,
                    "gt_10ms": 2, "gt_100ms": 2, "gt_1s": 1,
                },
            },
        )
        summary = result["files"]["sample.log"]["summary"]
        self.assertEqual(summary["cpu"]["median"], 1)
        self.assertEqual(summary["warmup_iters"]["median"], 100)
        self.assertEqual(summary["tail_gt_100ms"]["median"], 2)

    def test_timer_analyzer_accepts_legacy_rows_without_metadata(self) -> None:
        result = self.run_analyzer(
            "timer_jitter",
            {
                "bench": "timer_jitter", "period_us": 1000,
                "wake_latency_ns": {
                    "n": 10, "min": 1, "mean": 2.0, "p50": 2,
                    "p90": 3, "p99": 4, "max": 5,
                },
            },
        )
        summary = result["files"]["sample.log"]["summary"]
        self.assertEqual(summary["cpu"]["n"], 0)
        self.assertEqual(summary["tail_gt_100ms"]["n"], 0)

    def test_smp_pingpong_reports_clock_and_tails(self) -> None:
        cpus = sorted(os.sched_getaffinity(0))
        if len(cpus) < 2:
            self.skipTest("requires two allowed CPUs")
        result = self.run_benchmark(
            "smp_pingpong", "-a", str(cpus[0]), "-b", str(cpus[1]), "-n", "100"
        )
        self.assertEqual(result["clock"], "CLOCK_MONOTONIC")
        self.assertEqual(result["cpu_a"], cpus[0])
        self.assertEqual(result["cpu_b"], cpus[1])
        self.assertEqual(
            set(result["tail_counts"]),
            {"zero", "gt_10us", "gt_1ms", "gt_10ms", "gt_100ms", "gt_1s"},
        )

    def test_pingpong_analyzer_summarizes_tail_counts(self) -> None:
        result = self.run_analyzer(
            "smp_pingpong",
            {
                "bench": "smp_pingpong", "clock": "CLOCK_MONOTONIC",
                "cpu_a": 0, "cpu_b": 1, "iters": 100, "mode": "spin",
                "round_trip_ns": {
                    "n": 100, "min": 0, "mean": 10.0, "p50": 5,
                    "p90": 8, "p99": 9, "max": 100000001,
                },
                "tail_counts": {
                    "zero": 3, "gt_10us": 2, "gt_1ms": 2,
                    "gt_10ms": 1, "gt_100ms": 1, "gt_1s": 0,
                },
            },
        )
        summary = result["files"]["sample.log"]["summary"]
        self.assertEqual(summary["tail_zero"]["median"], 3)
        self.assertEqual(summary["tail_gt_10ms"]["median"], 1)
        self.assertEqual(summary["tail_gt_100ms"]["median"], 1)

    def test_smp_barrier_reports_cpu_range_clock_tails_and_raw_samples(self) -> None:
        cpus = sorted(os.sched_getaffinity(0))
        if len(cpus) < 2 or cpus[1] != cpus[0] + 1:
            self.skipTest("requires two consecutive allowed CPUs")
        with tempfile.TemporaryDirectory() as tmp:
            raw_path = Path(tmp) / "barrier.raw"
            result = self.run_benchmark(
                "smp_barrier", "-a", str(cpus[0]), "-t", "2", "-n", "100",
                "-r", str(raw_path)
            )
            self.assertEqual(len(raw_path.read_text().splitlines()), 100)
        self.assertEqual(result["clock"], "CLOCK_MONOTONIC")
        self.assertEqual(result["cpu_first"], cpus[0])
        self.assertEqual(result["cpu_last"], cpus[1])
        self.assertEqual(
            set(result["tail_counts"]),
            {"zero", "gt_10us", "gt_1ms", "gt_10ms", "gt_100ms", "gt_1s"},
        )

    def test_barrier_analyzer_summarizes_cpu_range_and_tail_counts(self) -> None:
        result = self.run_analyzer(
            "smp_barrier",
            {
                "bench": "smp_barrier", "clock": "CLOCK_MONOTONIC",
                "cpu_first": 2, "cpu_last": 3, "threads": 2, "iters": 100,
                "work_cycles": 0, "mode": "spin", "elapsed_ns": 1000,
                "rounds_per_sec": 100000000.0,
                "t0_wait_ns": {
                    "n": 100, "min": 0, "mean": 10.0, "p50": 5,
                    "p90": 8, "p99": 9, "max": 10000001,
                },
                "tail_counts": {
                    "zero": 2, "gt_10us": 2, "gt_1ms": 1,
                    "gt_10ms": 1, "gt_100ms": 0, "gt_1s": 0,
                },
            },
        )
        summary = result["files"]["sample.log"]["summary"]
        self.assertEqual(summary["cpu_first"]["median"], 2)
        self.assertEqual(summary["cpu_last"]["median"], 3)
        self.assertEqual(summary["tail_zero"]["median"], 2)
        self.assertEqual(summary["tail_gt_10ms"]["median"], 1)

    def test_simple_compute_reports_per_thread_and_aggregate_results(self) -> None:
        cpus = sorted(os.sched_getaffinity(0))
        if len(cpus) < 2 or cpus[1] != cpus[0] + 1:
            self.skipTest("requires two consecutive allowed CPUs")
        result = self.run_benchmark(
            "simple_compute", "-a", str(cpus[0]), "-t", "2", "-n", "10000"
        )
        self.assertEqual(result["bench"], "simple_compute")
        self.assertEqual(result["clock"], "CLOCK_MONOTONIC")
        self.assertEqual(result["compute_kernel"], "xorshift64")
        self.assertEqual(result["threads"], 2)
        self.assertEqual(result["cpu_first"], cpus[0])
        self.assertEqual(result["cpu_last"], cpus[1])
        self.assertEqual(result["iterations_per_thread"], 10000)
        self.assertEqual(result["total_iterations"], 20000)
        self.assertGreater(result["elapsed_window_ns"], 0)
        self.assertGreater(result["aggregate_iterations_per_sec"], 0)
        self.assertEqual(len(result["thread_results"]), 2)
        self.assertEqual({row["cpu"] for row in result["thread_results"]}, set(cpus[:2]))
        for row in result["thread_results"]:
            self.assertGreater(row["elapsed_ns"], 0)
            self.assertGreater(row["iterations_per_sec"], 0)

    def test_simple_compute_analyzer_summarizes_runs_and_per_cpu_results(self) -> None:
        result = self.run_analyzer(
            "simple_compute",
            {
                "bench": "simple_compute",
                "clock": "CLOCK_MONOTONIC",
                "compute_kernel": "xorshift64",
                "threads": 2,
                "cpu_first": 2,
                "cpu_last": 3,
                "iterations_per_thread": 10000,
                "total_iterations": 20000,
                "elapsed_window_ns": 1200,
                "aggregate_iterations_per_sec": 16000000.0,
                "start_skew_ns": 100,
                "finish_skew_ns": 200,
                "clock_regressions": 0,
                "thread_results": [
                    {
                        "cpu": 2,
                        "elapsed_ns": 1000,
                        "iterations_per_sec": 10000000.0,
                        "clock_regression": False,
                    },
                    {
                        "cpu": 3,
                        "elapsed_ns": 1200,
                        "iterations_per_sec": 8000000.0,
                        "clock_regression": False,
                    },
                ],
            },
        )
        data = result["files"]["sample.log"]
        summary = data["summary"]
        self.assertEqual(summary["aggregate_iterations_per_sec"]["median"], 16000000.0)
        self.assertEqual(summary["thread_elapsed_min_ns"]["median"], 1000)
        self.assertEqual(summary["thread_elapsed_max_ns"]["median"], 1200)
        self.assertAlmostEqual(summary["thread_rate_imbalance_pct"]["median"], 200 / 9)
        self.assertEqual(data["per_cpu"]["2"]["elapsed_ns"]["median"], 1000)
        self.assertEqual(data["per_cpu"]["3"]["iterations_per_sec"]["median"], 8000000.0)
        self.assertEqual(data["incomplete_thread_rows"], 0)

    def test_simple_compute_analyzer_accepts_rows_without_optional_metadata(self) -> None:
        result = self.run_analyzer("simple_compute", {"bench": "simple_compute"})
        data = result["files"]["sample.log"]
        self.assertEqual(data["summary"]["aggregate_iterations_per_sec"]["n"], 0)
        self.assertEqual(data["per_cpu"], {})
        self.assertEqual(data["incomplete_thread_rows"], 0)


if __name__ == "__main__":
    unittest.main()
