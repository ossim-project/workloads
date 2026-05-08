#!/usr/bin/env python3
"""Compute vtime skew, Jain's fairness, and CV across N per-VM result files.

Reads cpu_loop result JSONs (which carry `samples: [{mono_ns, ticks}, ...]`),
normalises each VM's samples to elapsed-since-start, resamples on a common
grid, and reports the spread of completed work across VMs over time.

Optional: --plot writes a PNG of completed work vs guest/virtual time, one
line per VM. matplotlib is imported lazily so the basic stats path has no
external deps.

Usage:
  ./skew.py result-vm0.json result-vm1.json ... [--out summary.json] [--plot work.png]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def load_samples(path: Path) -> list[tuple[int, int]]:
    """Return [(elapsed_ns, ticks), ...] sorted by elapsed_ns."""
    d = json.loads(path.read_text())
    samples = d.get("samples") or []
    if not samples:
        return []
    mono_start = d["mono_start"]
    out = sorted(((int(s["mono_ns"]) - mono_start, int(s["ticks"])) for s in samples),
                 key=lambda x: x[0])
    return out


def interp_work(samples: list[tuple[int, int]], t_ns: int) -> float | None:
    """Linear interpolation of ticks at elapsed time t_ns; None if out of range."""
    if not samples or t_ns < samples[0][0] or t_ns > samples[-1][0]:
        return None
    lo, hi = 0, len(samples) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if samples[mid][0] <= t_ns:
            lo = mid
        else:
            hi = mid
    t0, w0 = samples[lo]
    t1, w1 = samples[lo + 1] if lo + 1 < len(samples) else samples[lo]
    if t1 == t0:
        return float(w0)
    frac = (t_ns - t0) / (t1 - t0)
    return w0 + frac * (w1 - w0)


def jains_index(xs: list[float]) -> float:
    s = sum(xs); ss = sum(x * x for x in xs)
    n = len(xs)
    return (s * s) / (n * ss) if n and ss > 0 else 0.0


def cv(xs: list[float]) -> float:
    n = len(xs)
    if n < 2: return 0.0
    mean = sum(xs) / n
    if mean == 0: return 0.0
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var) / mean


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("results", nargs="+", type=Path,
                   help="cpu_loop result JSONs, one per VM")
    p.add_argument("--out", type=Path, default=None,
                   help="write summary JSON to this path")
    p.add_argument("--plot", type=Path, default=None,
                   help="write a work-vs-vtime PNG to this path (requires matplotlib)")
    p.add_argument("--grid-ms", type=int, default=100,
                   help="resampling grid step in elapsed ms (default 100)")
    p.add_argument("--warmup-ms", type=int, default=1000,
                   help="exclude first N ms when computing steady-state metrics (default 1000)")
    args = p.parse_args()

    vms: list[tuple[str, list[tuple[int, int]]]] = []
    for path in args.results:
        d = json.loads(path.read_text())
        label = d.get("args", {}).get("label") or d.get("metadata", {}).get("vm_label") or path.stem
        s = load_samples(path)
        if not s:
            print(f"warning: {path} has no samples; skipping", flush=True)
            continue
        vms.append((label, s))

    if len(vms) < 2:
        print("need at least 2 VM result files with samples", flush=True)
        return 2

    # Common elapsed-time range: intersect [first sample, last sample].
    t_lo = max(v[1][0][0] for v in vms)
    t_hi = min(v[1][-1][0] for v in vms)
    if t_hi <= t_lo:
        print("VM sample windows do not overlap", flush=True)
        return 2

    grid_ns = args.grid_ms * 1_000_000
    grid = list(range(t_lo, t_hi + 1, grid_ns))

    # work[i][k] = ticks of VM i at grid point k
    work_at: list[list[float]] = []
    for label, samples in vms:
        row: list[float] = []
        for t in grid:
            w = interp_work(samples, t)
            row.append(w if w is not None else 0.0)
        work_at.append(row)

    # Per-grid-point spread
    spread = []
    jain = []
    coef = []
    for k in range(len(grid)):
        col = [work_at[i][k] for i in range(len(vms))]
        spread.append(max(col) - min(col))
        jain.append(jains_index(col))
        coef.append(cv(col))

    finals = [row[-1] for row in work_at]

    # Steady-state metrics: drop the first warmup_ms of grid points before
    # computing max-spread/min-Jain so that the startup transient (where one
    # VM's first sample is at zero ticks) doesn't dominate the headline.
    warmup_ns = args.warmup_ms * 1_000_000
    ss_idx = [k for k, t in enumerate(grid) if (t - t_lo) >= warmup_ns]
    if ss_idx:
        ss_spread = [spread[k] for k in ss_idx]
        ss_jain = [jain[k] for k in ss_idx]
        ss_cv = [coef[k] for k in ss_idx]
        steady_state = {
            "warmup_ms": args.warmup_ms,
            "n_grid_points": len(ss_idx),
            "max_spread_ticks": max(ss_spread),
            "min_jain_index": min(ss_jain),
            "max_cv": max(ss_cv),
        }
    else:
        steady_state = {
            "warmup_ms": args.warmup_ms,
            "n_grid_points": 0,
            "max_spread_ticks": 0,
            "min_jain_index": 0.0,
            "max_cv": 0.0,
        }

    summary = {
        "n_vms": len(vms),
        "labels": [v[0] for v in vms],
        "grid_ms": args.grid_ms,
        "grid_points": len(grid),
        "elapsed_window_ns": [t_lo, t_hi],
        "max_spread_ticks": max(spread) if spread else 0,
        "final_spread_ticks": spread[-1] if spread else 0,
        "final_jain_index": jain[-1] if jain else 0.0,
        "final_cv": coef[-1] if coef else 0.0,
        "final_ticks_per_vm": dict(zip([v[0] for v in vms], finals)),
        "steady_state": steady_state,
        "spread_over_time": [
            {"elapsed_ns": grid[k], "spread_ticks": spread[k],
             "jain": jain[k], "cv": coef[k]}
            for k in range(len(grid))
        ],
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2))

    print(f"{len(vms)} VMs, {len(grid)} grid points over "
          f"{(t_hi - t_lo) / 1e9:.1f}s of guest-virtual time")
    print(f"max spread:   {summary['max_spread_ticks']:.0f} ticks")
    print(f"final spread: {summary['final_spread_ticks']:.0f} ticks")
    print(f"final Jain:   {summary['final_jain_index']:.4f}  (1.0 = perfect)")
    print(f"final CV:     {summary['final_cv']:.4f}")
    ss = summary["steady_state"]
    print(f"steady-state (after {ss['warmup_ms']}ms): "
          f"max spread {ss['max_spread_ticks']:.0f}, "
          f"min Jain {ss['min_jain_index']:.4f}, max CV {ss['max_cv']:.4f}")

    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not available; skipping plot", flush=True)
            return 0
        fig, ax = plt.subplots(figsize=(8, 5))
        for (label, _), row in zip(vms, work_at):
            ax.plot([t / 1e9 for t in grid], row, label=label)
        ax.set_xlabel("guest/virtual time (s)")
        ax.set_ylabel("completed work (ticks)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        args.plot.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.plot, dpi=120, bbox_inches="tight")
        print(f"plot written to {args.plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
