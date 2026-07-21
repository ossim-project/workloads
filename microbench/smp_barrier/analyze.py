#!/usr/bin/env python3
"""Analyze smp_barrier JSONL result logs.

Usage:
    analyze_smp_barrier.py /workspace/ossim/logs/smp_barrier

The input directory is expected to contain one or more *.log files whose lines
are JSON objects emitted by workloads/microbench/smp_barrier/smp_barrier.
Non-JSON lines are ignored so copied terminal transcripts are tolerated.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as stats
import sys
from pathlib import Path
from typing import Any

PREFERRED_ORDER = [
    "baremetal.log",
    "upstream.log",
    "ossim_async.log",
    "ossim_sync.log",
]


def signed_u64(value: int) -> int:
    """Interpret an unsigned 64-bit value as signed."""
    if value >= 1 << 63:
        return value - (1 << 64)
    return value


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
        return {k: math.nan for k in ("mean", "median", "min", "max", "stdev", "cv", "p10", "p90")} | {"n": 0}
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
            if obj.get("bench") != "smp_barrier":
                skipped.append(f"{path.name}:{lineno}: bench={obj.get('bench')!r}")
                continue
            rows.append(obj)
    return rows, skipped


def metrics_for(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    metrics: dict[str, list[float]] = {
        "rps": [],
        "elapsed_ms": [],
        "elapsed_signed_ms": [],
        "wait_mean_ns": [],
        "wait_p50_ns": [],
        "wait_p90_ns": [],
        "wait_p99_ns": [],
        "wait_max_ns": [],
        "cpu_first": [],
        "cpu_last": [],
        "tail_zero": [],
        "tail_gt_10ms": [],
        "tail_gt_100ms": [],
    }
    for row in rows:
        elapsed_ns = int(row["elapsed_ns"])
        wait = row["t0_wait_ns"]
        metrics["rps"].append(float(row["rounds_per_sec"]))
        metrics["elapsed_ms"].append(elapsed_ns / 1e6)
        metrics["elapsed_signed_ms"].append(signed_u64(elapsed_ns) / 1e6)
        metrics["wait_mean_ns"].append(float(wait["mean"]))
        metrics["wait_p50_ns"].append(float(wait["p50"]))
        metrics["wait_p90_ns"].append(float(wait["p90"]))
        metrics["wait_p99_ns"].append(float(wait["p99"]))
        metrics["wait_max_ns"].append(float(wait["max"]))
        metrics["cpu_first"].append(float(row.get("cpu_first", math.nan)))
        metrics["cpu_last"].append(float(row.get("cpu_last", math.nan)))
        tails = row.get("tail_counts", {})
        metrics["tail_zero"].append(float(tails.get("zero", math.nan)))
        metrics["tail_gt_10ms"].append(float(tails.get("gt_10ms", math.nan)))
        metrics["tail_gt_100ms"].append(float(tails.get("gt_100ms", math.nan)))
    return metrics


def fmt(value: float, digits: int = 2) -> str:
    if isinstance(value, float) and math.isnan(value):
        return "nan"
    abs_v = abs(value)
    if abs_v >= 1_000_000:
        return f"{value / 1_000_000:.{digits}f}M"
    if abs_v >= 1_000:
        return f"{value / 1_000:.{digits}f}K"
    return f"{value:.{digits}f}"


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]
    lines = ["| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |"]
    lines.append("| " + " | ".join("-" * w for w in widths) + " |")
    for row in rows:
        lines.append("| " + " | ".join(c.ljust(w) for c, w in zip(row, widths)) + " |")
    return "\n".join(lines)


def ordered_logs(log_dir: Path) -> list[Path]:
    logs = {p.name: p for p in log_dir.glob("*.log") if p.is_file()}
    ordered = [logs.pop(name) for name in PREFERRED_ORDER if name in logs]
    ordered.extend(logs[name] for name in sorted(logs))
    return ordered


def analyze(log_dir: Path) -> dict[str, Any]:
    if not log_dir.is_dir():
        raise NotADirectoryError(log_dir)
    result: dict[str, Any] = {"log_dir": str(log_dir), "files": {}, "skipped_lines": []}
    for path in ordered_logs(log_dir):
        rows, skipped = parse_log(path)
        metrics = metrics_for(rows)
        summaries = {name: summarize(values) for name, values in metrics.items()}
        wrapped = [signed_u64(int(r["elapsed_ns"])) for r in rows if signed_u64(int(r["elapsed_ns"])) < 0]
        result["files"][path.name] = {
            "rows": rows,
            "summary": summaries,
            "wrapped_elapsed_count": len(wrapped),
            "wrapped_elapsed_signed_ns": wrapped,
        }
        result["skipped_lines"].extend(skipped)
    return result


def print_text(result: dict[str, Any]) -> None:
    files: dict[str, Any] = result["files"]
    if not files:
        print(f"No *.log files found in {result['log_dir']}")
        return

    print(f"# smp_barrier analysis: {result['log_dir']}\n")
    rows = []
    for name, data in files.items():
        s = data["summary"]
        rows.append([
            name,
            str(s["rps"]["n"]),
            f"{fmt(s['cpu_first']['median'], 0)}-{fmt(s['cpu_last']['median'], 0)}",
            fmt(s["rps"]["mean"]),
            fmt(s["rps"]["median"]),
            fmt(s["rps"]["min"]),
            fmt(s["rps"]["max"]),
            f"{s['rps']['cv']:.3f}",
            f"{s['elapsed_signed_ms']['median']:.3f}",
            f"{s['wait_mean_ns']['median']:.1f}",
            f"{s['wait_p50_ns']['median']:.1f}",
            f"{s['wait_p90_ns']['median']:.1f}",
            f"{s['wait_p99_ns']['median']:.1f}",
            f"{s['wait_max_ns']['median']:.1f}",
            str(data["wrapped_elapsed_count"]),
            fmt(s["tail_zero"]["median"], 0),
            fmt(s["tail_gt_10ms"]["median"], 0),
            fmt(s["tail_gt_100ms"]["median"], 0),
        ])
    print(markdown_table([
        "setup", "n", "cpus", "rps mean", "rps median", "rps min", "rps max", "rps CV",
        "elapsed median ms", "wait mean ns", "wait p50 ns", "wait p90 ns",
        "wait p99 ns", "wait max ns", "wrapped elapsed", "zero", ">10ms", ">100ms",
    ], rows))

    base_name = "baremetal.log" if "baremetal.log" in files else next(iter(files))
    base = files[base_name]["summary"]["rps"]["median"]
    if base and not math.isnan(base):
        ratio_rows = []
        for name, data in files.items():
            med = data["summary"]["rps"]["median"]
            ratio_rows.append([name, f"{med / base:.3f}x", f"{base / med:.3f}x" if med else "inf"])
        print(f"\n## Median throughput relative to {base_name}\n")
        print(markdown_table(["setup", "throughput ratio", "slowdown"], ratio_rows))

    print("\n## Raw rounds/sec (millions)\n")
    for name, data in files.items():
        rps = [r["rounds_per_sec"] / 1e6 for r in data["rows"]]
        print(f"- {name}: " + ", ".join(f"{x:.3f}" for x in rps))

    problems = []
    for name, data in files.items():
        if data["wrapped_elapsed_count"]:
            signed = [x / 1e9 for x in data["wrapped_elapsed_signed_ns"]]
            problems.append(
                f"{name}: {data['wrapped_elapsed_count']} wrapped elapsed samples "
                f"({', '.join(f'{x:.6f}s' for x in signed)})"
            )
    if problems:
        print("\n## Warnings\n")
        for problem in problems:
            print(f"- {problem}")

    if result["skipped_lines"]:
        print("\n## Skipped non-result lines\n")
        for item in result["skipped_lines"][:20]:
            print(f"- {item}")
        extra = len(result["skipped_lines"]) - 20
        if extra > 0:
            print(f"- ... {extra} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze smp_barrier JSONL logs")
    parser.add_argument("log_dir", type=Path, help="Directory containing smp_barrier *.log files")
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
