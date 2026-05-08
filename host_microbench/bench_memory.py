#!/usr/bin/env python3
"""Memory microbench.

Modes:
  bandwidth - sysbench memory streaming throughput.
  latency   - random pointer-chase via the C `pchase` binary; reports ns/load
              that responds correctly to working-set-vs-cache-hierarchy.

Used by Exp M1 to measure DRAM-bound performance under noisy-neighbor
contention, with and without isolation.
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

PCHASE_DIR = HERE / "pchase"


def default_output(mode: str) -> Path:
    return Path(tempfile.gettempdir()) / f"memory_{mode}-{time.time_ns()}.json"


def run_bandwidth(threads: int, total_size_mb: int, block_size_kb: int) -> dict:
    cmd = [
        "sysbench", "memory",
        f"--threads={threads}",
        f"--memory-block-size={block_size_kb}K",
        f"--memory-total-size={total_size_mb}M",
        "--memory-oper=read",
        "--memory-access-mode=seq",
        "run",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    out = p.stdout
    bw_mib = None
    m = re.search(r"transferred \(([\d.]+) MiB/sec\)", out)
    if m:
        bw_mib = float(m.group(1))
    avg_lat_ms = None
    p95_lat_ms = None
    block_match = re.search(r"Latency \(ms\):(.*?)(?:\n\s*\n|\Z)", out, re.DOTALL)
    if block_match:
        block = block_match.group(1)
        am = re.search(r"avg:\s+([\d.]+)", block)
        if am:
            avg_lat_ms = float(am.group(1))
        pm = re.search(r"95th percentile:\s+([\d.]+)", block)
        if pm:
            p95_lat_ms = float(pm.group(1))
    return {
        "threads": threads,
        "total_size_mb": total_size_mb,
        "block_size_kb": block_size_kb,
        "bandwidth_mib_s": bw_mib,
        "avg_latency_ms": avg_lat_ms,
        "p95_latency_ms": p95_lat_ms,
        "raw_stdout": out,
    }


def ensure_pchase() -> Path:
    binary = PCHASE_DIR / "pchase"
    if not binary.exists():
        raise SystemExit(
            f"{binary} not built. On the host, run\n"
            f"  make -C ossim/workloads/host_microbench\n"
            f"(host_microbench/ is mounted read-only into VMs.)"
        )
    return binary


def run_latency(working_set_mb: int, hops: int, seed: int) -> dict:
    binary = ensure_pchase()
    cmd = [str(binary),
           "--working-set-mb", str(working_set_mb),
           "--hops", str(hops),
           "--seed", str(seed)]
    p = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(p.stdout.strip())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=None,
                   help="result JSON path (default: /tmp/memory_<mode>-<ns>.json)")
    p.add_argument("--mode", choices=["bandwidth", "latency"], required=True)
    p.add_argument("--label", type=str, default="")
    p.add_argument("--threads", type=int, default=1)
    p.add_argument("--total-size-mb", type=int, default=4096)
    p.add_argument("--block-size-kb", type=int, default=1024)
    p.add_argument("--working-set-mb", type=int, default=256)
    p.add_argument("--hops", type=int, default=30_000_000)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    if args.output is None:
        args.output = default_output(args.mode)

    sr, sm = now_ns()
    if args.mode == "bandwidth":
        res = run_bandwidth(args.threads, args.total_size_mb, args.block_size_kb)
    else:
        res = run_latency(args.working_set_mb, args.hops, args.seed)
    fr, fm = now_ns()

    write_result(
        output=args.output,
        benchmark=f"memory_{args.mode}",
        args={
            "mode": args.mode, "label": args.label,
            "threads": args.threads,
            "total_size_mb": args.total_size_mb,
            "block_size_kb": args.block_size_kb,
            "working_set_mb": args.working_set_mb,
            "hops": args.hops, "seed": args.seed,
        },
        started_at=sr, mono_start=sm,
        finished_at=fr, mono_end=fm,
        result=res,
    )
    if args.mode == "bandwidth":
        print(f"memory_bandwidth: {res['bandwidth_mib_s']} MiB/s, "
              f"avg={res['avg_latency_ms']} ms, p95={res['p95_latency_ms']} ms")
    else:
        print(f"memory_latency: {res['ns_per_load']:.2f} ns/load "
              f"over {res['hops']} hops, {res['working_set_mb']} MiB working set")
    print(f"-> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
