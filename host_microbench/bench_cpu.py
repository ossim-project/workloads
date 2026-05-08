#!/usr/bin/env python3
"""CPU microbench.

Modes:
  sysbench - wrapper around `sysbench cpu`. Reports events/sec the way
             sysbench does. Sysbench measures elapsed time using
             clock_gettime(CLOCK_MONOTONIC), so under ossim sync the
             "events/sec" number is events/guest-virtual-second; pair with
             the host-side bracket to also get events/host-second.
  loop     - deterministic CPU loop with periodic (mono_ns, ticks) samples,
             implemented in C (host_microbench/cpu_loop). Preferred for the
             scheduling experiments because the per-VM samples support
             skew/CV computation across concurrent guests.

Both modes write the standard result JSON via lib_results.write_result.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_results import now_ns, write_result  # noqa: E402

CPU_LOOP_DIR = HERE / "cpu_loop"


def default_output(mode: str) -> Path:
    return Path(tempfile.gettempdir()) / f"cpu_{mode}-{time.time_ns()}.json"


def run_sysbench_cpu(threads: int, runtime_s: int, cpu_max_prime: int) -> dict:
    cmd = [
        "sysbench", "cpu",
        f"--threads={threads}",
        f"--time={runtime_s}",
        f"--cpu-max-prime={cpu_max_prime}",
        "run",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = p.stdout
    events_per_sec = total_events = avg_lat_ms = p95_lat_ms = None

    m = re.search(r"events per second:\s+([\d.]+)", out)
    if m:
        events_per_sec = float(m.group(1))
    m = re.search(r"total number of events:\s+(\d+)", out)
    if m:
        total_events = int(m.group(1))
    block_match = re.search(r"Latency \(ms\):(.*?)(?:\n\s*\n|\Z)", out, re.DOTALL)
    if block_match:
        block = block_match.group(1)
        am = re.search(r"avg:\s+([\d.]+)", block)
        if am: avg_lat_ms = float(am.group(1))
        pm = re.search(r"95th percentile:\s+([\d.]+)", block)
        if pm: p95_lat_ms = float(pm.group(1))

    return {
        "threads": threads,
        "runtime_s": runtime_s,
        "cpu_max_prime": cpu_max_prime,
        "events_per_sec": events_per_sec,
        "total_events": total_events,
        "avg_latency_ms": avg_lat_ms,
        "p95_latency_ms": p95_lat_ms,
        "raw_stdout": out,
    }


def ensure_cpu_loop() -> Path:
    binary = CPU_LOOP_DIR / "cpu_loop"
    if not binary.exists():
        raise SystemExit(
            f"{binary} not built. On the host, run\n"
            f"  make -C ossim/workloads/host_microbench\n"
            f"(host_microbench/ is mounted read-only into VMs.)"
        )
    return binary


def run_cpu_loop(duration_s: int, sample_ms: int, inner: int) -> tuple[dict, list]:
    binary = ensure_cpu_loop()
    cmd = [str(binary),
           "--duration-s", str(duration_s),
           "--sample-ms", str(sample_ms),
           "--inner", str(inner)]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raw = json.loads(p.stdout.strip())
    samples = [{"mono_ns": m, "ticks": t} for m, t in raw.pop("samples")]
    return raw, samples


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=None,
                   help="result JSON path (default: /tmp/cpu_<mode>-<ns>.json)")
    p.add_argument("--mode", choices=["sysbench", "loop"], default="loop")
    p.add_argument("--label", type=str, default="")
    # sysbench mode
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--time", type=int, default=30, dest="runtime_s",
                   help="benchmark duration in seconds (guest-monotonic)")
    p.add_argument("--cpu-max-prime", type=int, default=20000)
    # loop mode
    p.add_argument("--sample-ms", type=int, default=100)
    p.add_argument("--inner", type=int, default=100000)
    args = p.parse_args()
    if args.output is None:
        args.output = default_output(args.mode)

    sr, sm = now_ns()
    samples = None
    if args.mode == "sysbench":
        res = run_sysbench_cpu(args.threads, args.runtime_s, args.cpu_max_prime)
    else:
        res, samples = run_cpu_loop(args.runtime_s, args.sample_ms, args.inner)
    fr, fm = now_ns()

    write_result(
        output=args.output,
        benchmark=f"cpu_{args.mode}",
        args={
            "mode": args.mode, "label": args.label,
            "threads": args.threads,
            "runtime_s": args.runtime_s,
            "cpu_max_prime": args.cpu_max_prime,
            "sample_ms": args.sample_ms,
            "inner": args.inner,
        },
        started_at=sr, mono_start=sm,
        finished_at=fr, mono_end=fm,
        result=res,
        samples=samples,
    )
    if args.mode == "sysbench":
        print(f"cpu_sysbench: {res['events_per_sec']} events/s, "
              f"total={res['total_events']}, "
              f"avg={res['avg_latency_ms']} ms, p95={res['p95_latency_ms']} ms")
    else:
        print(f"cpu_loop: {res['total_ticks']} ticks, "
              f"{res['work_per_guest_s']:.0f} ticks/guest-s, "
              f"{len(samples)} samples")
    print(f"-> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
