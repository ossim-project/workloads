#!/usr/bin/env python3
"""Analyze timer_jitter JSONL result logs.

Usage:
    analyze_timer_jitter.py /workspace/ossim/logs/timer_jitter

The input directory is expected to contain *.log files with JSON objects emitted
by workloads/microbench/timer_jitter/timer_jitter. Non-JSON lines are ignored so
terminal transcripts are tolerated. Unreadable log files are reported in the
output instead of aborting the whole analysis.
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
BENCH = "timer_jitter"
LATENCY_KEY = "wake_latency_ns"


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
            if obj.get("bench") != BENCH or LATENCY_KEY not in obj:
                skipped.append(f"{path.name}:{lineno}: not {BENCH}")
                continue
            rows.append(obj)
    return rows, skipped


def ordered_logs(log_dir: Path) -> list[Path]:
    logs = {p.name: p for p in log_dir.glob("*.log") if p.is_file()}
    ordered = [logs.pop(name) for name in PREFERRED_ORDER if name in logs]
    ordered.extend(logs[name] for name in sorted(logs))
    return ordered


def metrics_for(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    metrics = {
        "lat_mean_ns": [],
        "lat_p50_ns": [],
        "lat_p90_ns": [],
        "lat_p99_ns": [],
        "lat_min_ns": [],
        "lat_max_ns": [],
        "period_us": [],
        "samples_per_run": [],
        "cpu": [],
        "warmup_iters": [],
        "tail_zero": [],
        "tail_gt_1ms": [],
        "tail_gt_100ms": [],
        "tail_gt_1s": [],
    }
    for row in rows:
        lat = row[LATENCY_KEY]
        metrics["lat_mean_ns"].append(float(lat["mean"]))
        metrics["lat_p50_ns"].append(float(lat["p50"]))
        metrics["lat_p90_ns"].append(float(lat["p90"]))
        metrics["lat_p99_ns"].append(float(lat["p99"]))
        metrics["lat_min_ns"].append(float(lat["min"]))
        metrics["lat_max_ns"].append(float(lat["max"]))
        metrics["period_us"].append(float(row.get("period_us", math.nan)))
        metrics["samples_per_run"].append(float(lat.get("n", math.nan)))
        metrics["cpu"].append(float(row.get("cpu", math.nan)))
        metrics["warmup_iters"].append(float(row.get("warmup_iters", math.nan)))
        tails = row.get("tail_counts", {})
        metrics["tail_zero"].append(float(tails.get("zero", math.nan)))
        metrics["tail_gt_1ms"].append(float(tails.get("gt_1ms", math.nan)))
        metrics["tail_gt_100ms"].append(float(tails.get("gt_100ms", math.nan)))
        metrics["tail_gt_1s"].append(float(tails.get("gt_1s", math.nan)))
    return metrics


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
            result["files"][path.name] = {"rows": [], "summary": {}}
            continue
        metrics = metrics_for(rows)
        result["files"][path.name] = {
            "rows": rows,
            "summary": {name: summarize(values) for name, values in metrics.items()},
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
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]
    out = ["| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |"]
    out.append("| " + " | ".join("-" * w for w in widths) + " |")
    for row in rows:
        out.append("| " + " | ".join(c.ljust(w) for c, w in zip(row, widths)) + " |")
    return "\n".join(out)


def print_text(result: dict[str, Any]) -> None:
    files = result["files"]
    if not files:
        print(f"No *.log files found in {result['log_dir']}")
        return

    print(f"# timer_jitter analysis: {result['log_dir']}\n")
    rows = []
    for name, data in files.items():
        s = data.get("summary", {})
        if not s:
            rows.append([name, "0", "?", "?", "?", "?", "nan", "nan", "nan", "nan", "nan", "nan", "nan", "nan", "nan"])
            continue
        period = s["period_us"]["median"]
        samples = s["samples_per_run"]["median"]
        rows.append([
            name,
            str(s["lat_mean_ns"]["n"]),
            fmt(s["cpu"]["median"], 0),
            fmt(period, 0),
            fmt(samples, 0),
            fmt(s["warmup_iters"]["median"], 0),
            fmt(s["lat_mean_ns"]["median"]),
            fmt(s["lat_p50_ns"]["median"]),
            fmt(s["lat_p90_ns"]["median"]),
            fmt(s["lat_p99_ns"]["median"]),
            fmt(s["lat_max_ns"]["median"]),
            f"{s['lat_mean_ns']['cv']:.3f}",
            fmt(s["tail_zero"]["median"], 0),
            fmt(s["tail_gt_100ms"]["median"], 0),
            fmt(s["tail_gt_1s"]["median"], 0),
        ])
    print(markdown_table([
        "setup", "n", "cpu", "period us", "samples/run", "warmup", "mean ns",
        "p50 ns", "p90 ns", "p99 ns", "max ns", "mean CV", "zero",
        ">100ms", ">1s",
    ], rows))

    readable = {name: data for name, data in files.items() if data.get("summary")}
    base_name = "baremetal.log" if "baremetal.log" in readable else (next(iter(readable)) if readable else None)
    if base_name:
        base = readable[base_name]["summary"]["lat_p50_ns"]["median"]
        if base and not math.isnan(base):
            ratio_rows = []
            for name, data in readable.items():
                p50 = data["summary"]["lat_p50_ns"]["median"]
                p99 = data["summary"]["lat_p99_ns"]["median"]
                ratio_rows.append([name, safe_ratio(p50, base), fmt(p99)])
            print(f"\n## Median p50 wake-latency relative to {base_name}\n")
            print(markdown_table(["setup", "p50 latency ratio", "median p99 ns"], ratio_rows))

    print("\n## Raw median p50 wake latency (ns)\n")
    for name, data in readable.items():
        vals = [row[LATENCY_KEY]["p50"] for row in data["rows"]]
        print(f"- {name}: " + ", ".join(str(v) for v in vals))

    if result["file_errors"]:
        print("\n## File errors\n")
        for item in result["file_errors"]:
            print(f"- {item}")

    if result["skipped_lines"]:
        print("\n## Skipped non-result lines")
        for item in result["skipped_lines"][:20]:
            print(f"- {item}")
        if len(result["skipped_lines"]) > 20:
            print(f"- ... {len(result['skipped_lines']) - 20} more")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze timer_jitter JSONL logs")
    parser.add_argument("log_dir", type=Path, help="Directory containing timer_jitter *.log files")
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
