#!/usr/bin/env python3
"""Analyze simple_compute JSONL result logs.

The input directory is expected to contain *.log files with JSON objects emitted
by workloads/microbench/simple_compute/simple_compute. Non-JSON lines are
ignored so terminal transcripts are tolerated. Unreadable files are reported
without aborting analysis of the remaining logs.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as stats
import sys
from pathlib import Path
from typing import Any

PREFERRED_ORDER = ["baremetal.log", "upstream.log", "ossim_async.log", "ossim_sync.log"]
BENCH = "simple_compute"


def percentile(values: list[float], p: float) -> float:
    data = sorted(values)
    k = (len(data) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return data[lo]
    return data[lo] * (hi - k) + data[hi] * (k - lo)


def summarize(values: list[float]) -> dict[str, float | int]:
    values = [value for value in values if not math.isnan(value)]
    if not values:
        return {
            "n": 0,
            "mean": math.nan,
            "median": math.nan,
            "min": math.nan,
            "max": math.nan,
            "stdev": math.nan,
            "cv": math.nan,
            "p10": math.nan,
            "p90": math.nan,
        }
    mean = stats.mean(values)
    stdev = stats.stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": mean,
        "median": stats.median(values),
        "min": min(values),
        "max": max(values),
        "stdev": stdev,
        "cv": stdev / mean if mean else math.nan,
        "p10": percentile(values, 0.10),
        "p90": percentile(values, 0.90),
    }


def parse_log(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            text = line.strip()
            if not text:
                continue
            if not text.startswith("{"):
                skipped.append(f"{path.name}:{lineno}: non-json")
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                skipped.append(f"{path.name}:{lineno}: json error: {exc}")
                continue
            if obj.get("bench") != BENCH:
                skipped.append(f"{path.name}:{lineno}: bench={obj.get('bench')!r}")
                continue
            rows.append(obj)
    return rows, skipped


def ordered_logs(log_dir: Path) -> list[Path]:
    logs = {path.name: path for path in log_dir.glob("*.log") if path.is_file()}
    ordered = [logs.pop(name) for name in PREFERRED_ORDER if name in logs]
    ordered.extend(logs[name] for name in sorted(logs))
    return ordered


def optional_float(row: dict[str, Any], key: str, scale: float = 1.0) -> float:
    value = row.get(key)
    return float(value) / scale if value is not None else math.nan


def metrics_for(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    metrics: dict[str, list[float]] = {
        "aggregate_iterations_per_sec": [],
        "elapsed_window_ms": [],
        "threads": [],
        "iterations_per_thread": [],
        "cpu_first": [],
        "cpu_last": [],
        "start_skew_ns": [],
        "finish_skew_ns": [],
        "clock_regressions": [],
        "thread_elapsed_mean_ns": [],
        "thread_elapsed_min_ns": [],
        "thread_elapsed_max_ns": [],
        "thread_rate_mean": [],
        "thread_rate_min": [],
        "thread_rate_max": [],
        "thread_rate_imbalance_pct": [],
    }
    for row in rows:
        metrics["aggregate_iterations_per_sec"].append(
            optional_float(row, "aggregate_iterations_per_sec")
        )
        metrics["elapsed_window_ms"].append(optional_float(row, "elapsed_window_ns", 1e6))
        for key in (
            "threads",
            "iterations_per_thread",
            "cpu_first",
            "cpu_last",
            "start_skew_ns",
            "finish_skew_ns",
            "clock_regressions",
        ):
            metrics[key].append(optional_float(row, key))

        thread_rows = row.get("thread_results", [])
        elapsed = [float(item["elapsed_ns"]) for item in thread_rows if "elapsed_ns" in item]
        rates = [
            float(item["iterations_per_sec"])
            for item in thread_rows
            if "iterations_per_sec" in item
        ]
        metrics["thread_elapsed_mean_ns"].append(stats.mean(elapsed) if elapsed else math.nan)
        metrics["thread_elapsed_min_ns"].append(min(elapsed) if elapsed else math.nan)
        metrics["thread_elapsed_max_ns"].append(max(elapsed) if elapsed else math.nan)
        metrics["thread_rate_mean"].append(stats.mean(rates) if rates else math.nan)
        metrics["thread_rate_min"].append(min(rates) if rates else math.nan)
        metrics["thread_rate_max"].append(max(rates) if rates else math.nan)
        rate_mean = stats.mean(rates) if rates else 0.0
        imbalance = (max(rates) - min(rates)) / rate_mean * 100.0 if rate_mean else math.nan
        metrics["thread_rate_imbalance_pct"].append(imbalance)
    return metrics


def per_cpu_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    samples: dict[int, dict[str, list[float]]] = {}
    for row in rows:
        for item in row.get("thread_results", []):
            if "cpu" not in item:
                continue
            cpu = int(item["cpu"])
            cpu_samples = samples.setdefault(
                cpu,
                {"elapsed_ns": [], "iterations_per_sec": [], "clock_regression": []},
            )
            if "elapsed_ns" in item:
                cpu_samples["elapsed_ns"].append(float(item["elapsed_ns"]))
            if "iterations_per_sec" in item:
                cpu_samples["iterations_per_sec"].append(float(item["iterations_per_sec"]))
            if "clock_regression" in item:
                cpu_samples["clock_regression"].append(float(bool(item["clock_regression"])))
    return {
        str(cpu): {metric: summarize(values) for metric, values in cpu_samples.items()}
        for cpu, cpu_samples in sorted(samples.items())
    }


def analyze(log_dir: Path) -> dict[str, Any]:
    if not log_dir.is_dir():
        raise NotADirectoryError(log_dir)
    result: dict[str, Any] = {
        "log_dir": str(log_dir),
        "files": {},
        "skipped_lines": [],
        "file_errors": [],
    }
    for path in ordered_logs(log_dir):
        try:
            rows, skipped = parse_log(path)
        except OSError as exc:
            result["file_errors"].append(f"{path.name}: {exc}")
            result["files"][path.name] = {"rows": [], "summary": {}, "per_cpu": {}}
            continue
        incomplete = sum(
            1
            for row in rows
            if "threads" in row and len(row.get("thread_results", [])) != int(row["threads"])
        )
        metrics = metrics_for(rows)
        result["files"][path.name] = {
            "rows": rows,
            "summary": {name: summarize(values) for name, values in metrics.items()},
            "per_cpu": per_cpu_for(rows),
            "incomplete_thread_rows": incomplete,
        }
        result["skipped_lines"].extend(skipped)
    return result


def fmt(value: float, digits: int = 1) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.{digits}f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.{digits}f}K"
    return f"{value:.{digits}f}"


def safe_ratio(numer: float, denom: float) -> str:
    if not denom or math.isnan(numer) or math.isnan(denom):
        return "nan"
    return f"{numer / denom:.3f}x"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]
    output = [
        "| " + " | ".join(header.ljust(width) for header, width in zip(headers, widths)) + " |",
        "| " + " | ".join("-" * width for width in widths) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(cell.ljust(width) for cell, width in zip(row, widths)) + " |")
    return "\n".join(output)


def print_text(result: dict[str, Any]) -> None:
    files: dict[str, Any] = result["files"]
    if not files:
        print(f"No *.log files found in {result['log_dir']}")
        return

    print(f"# simple_compute analysis: {result['log_dir']}\n")
    table_rows = []
    for name, data in files.items():
        summary = data.get("summary", {})
        if not summary:
            table_rows.append([name, "0", "?", "?", "nan", "nan", "nan", "nan", "nan", "nan", "nan"])
            continue
        table_rows.append([
            name,
            str(summary["aggregate_iterations_per_sec"]["n"]),
            fmt(summary["threads"]["median"], 0),
            f"{fmt(summary['cpu_first']['median'], 0)}-{fmt(summary['cpu_last']['median'], 0)}",
            fmt(summary["aggregate_iterations_per_sec"]["median"]),
            f"{summary['aggregate_iterations_per_sec']['cv']:.3f}",
            fmt(summary["thread_rate_min"]["median"]),
            fmt(summary["thread_rate_max"]["median"]),
            f"{summary['thread_rate_imbalance_pct']['median']:.2f}",
            fmt(summary["start_skew_ns"]["median"]),
            fmt(summary["clock_regressions"]["max"], 0),
        ])
    print(markdown_table(
        [
            "setup", "runs", "threads", "cpus", "aggregate iter/s", "aggregate CV",
            "thread min iter/s", "thread max iter/s", "imbalance %", "start skew ns",
            "clock regressions",
        ],
        table_rows,
    ))

    readable = {name: data for name, data in files.items() if data.get("summary")}
    base_name = "baremetal.log" if "baremetal.log" in readable else (next(iter(readable)) if readable else None)
    if base_name:
        base = readable[base_name]["summary"]["aggregate_iterations_per_sec"]["median"]
        if base and not math.isnan(base):
            ratio_rows = []
            for name, data in readable.items():
                throughput = data["summary"]["aggregate_iterations_per_sec"]["median"]
                ratio_rows.append([name, safe_ratio(throughput, base), safe_ratio(base, throughput)])
            print(f"\n## Median throughput relative to {base_name}\n")
            print(markdown_table(["setup", "throughput ratio", "slowdown"], ratio_rows))

    print("\n## Per-CPU median elapsed time and throughput\n")
    for name, data in readable.items():
        values = []
        for cpu, cpu_summary in data["per_cpu"].items():
            elapsed = cpu_summary["elapsed_ns"]["median"]
            rate = cpu_summary["iterations_per_sec"]["median"]
            values.append(f"CPU {cpu}: {fmt(elapsed)} ns, {fmt(rate)} iter/s")
        print(f"- {name}: " + ("; ".join(values) if values else "unavailable"))

    warnings = []
    for name, data in readable.items():
        regressions = data["summary"]["clock_regressions"]["max"]
        if regressions and not math.isnan(regressions):
            warnings.append(f"{name}: clock regressions observed (maximum {int(regressions)} per run)")
        if data["incomplete_thread_rows"]:
            warnings.append(
                f"{name}: {data['incomplete_thread_rows']} rows have fewer thread_results than threads"
            )
    warnings.extend(result["file_errors"])
    if warnings:
        print("\n## Warnings\n")
        for warning in warnings:
            print(f"- {warning}")

    if result["skipped_lines"]:
        print("\n## Skipped non-result lines\n")
        for item in result["skipped_lines"][:20]:
            print(f"- {item}")
        if len(result["skipped_lines"]) > 20:
            print(f"- ... {len(result['skipped_lines']) - 20} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze simple_compute JSONL logs")
    parser.add_argument("log_dir", type=Path, help="Directory containing simple_compute *.log files")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    args = parser.parse_args(argv)
    try:
        result = analyze(args.log_dir)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
