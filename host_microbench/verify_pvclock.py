#!/usr/bin/env python3
"""Confirm the guest userspace clock_gettime path before running S1.

What we want to know:
  1. Which clocksource is the kernel using?
     /sys/devices/system/clocksource/clocksource0/current_clocksource
  2. Does clock_gettime(CLOCK_MONOTONIC) reach the kernel via vDSO or via
     the syscall path?

The kernel's chosen clocksource is the strong signal. The vDSO check is a
sanity confirmation: if userspace is doing direct rdtsc instead of going
through the kernel-controlled path, no time virtualisation will catch it.

Python's time.clock_gettime_ns ultimately calls libc clock_gettime, which
on Linux uses the vDSO when available. We measure per-call cost in Python
to confirm; if available we also use `strace` for a definitive yes/no on
syscall entry.

Run on the host once, then in each guest. Expected guest result on a
working ossim PV-clock setup:
  clocksource = ossim_pvclock (or whatever the PV clocksource is named)
  vdso_active = true
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_results import collect_metadata, now_ns  # noqa: E402

CLOCKSOURCE_DIR = "/sys/devices/system/clocksource/clocksource0"


def default_output() -> Path:
    return Path(tempfile.gettempdir()) / f"verify_pvclock-{time.time_ns()}.json"


def read_or_empty(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return ""


def measure_per_call_ns(iters: int = 1_000_000) -> float:
    """Tight loop of clock_gettime calls, return mean ns per call.

    Through Python's wrapper, vDSO calls land around 100-300 ns/call and
    syscall-path calls around 700-1500 ns/call. The gap is wide enough to
    distinguish reliably without micro-benchmarking magic.
    """
    cg = time.clock_gettime_ns
    cm = time.CLOCK_MONOTONIC
    # Warm Python's bytecode caches.
    for _ in range(10000):
        cg(cm)
    t0 = cg(cm)
    for _ in range(iters):
        cg(cm)
    t1 = cg(cm)
    return (t1 - t0) / iters


def strace_count_clock_gettime_calls(iters: int = 1000) -> int | None:
    """If strace is available, run a tiny Python program under strace and
    count clock_gettime syscalls. Returns the count, or None if strace
    isn't usable.

    A vDSO-served clock_gettime should NOT show up in strace; we expect 0
    (or only setup-time calls, not iter-proportional). A failing vDSO will
    show iters-proportional calls.
    """
    if not shutil.which("strace"):
        return None
    snippet = (
        "import time\n"
        f"for _ in range({iters}):\n"
        "    time.clock_gettime_ns(time.CLOCK_MONOTONIC)\n"
    )
    try:
        p = subprocess.run(
            ["strace", "-e", "trace=clock_gettime", "-c", "-q",
             sys.executable, "-c", snippet],
            capture_output=True, text=True, check=False, timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    # strace -c prints a summary like:
    #   % time     seconds  usecs/call     calls    errors syscall
    #   100.00    0.000123           1       100           clock_gettime
    # Calls column is parts[3] when the line ends with the syscall name.
    for line in p.stderr.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == "clock_gettime":
            try:
                return int(parts[3])
            except (ValueError, IndexError):
                pass
    return 0


VDSO_THRESHOLD_NS = 500.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=None,
                   help="result JSON path (default: /tmp/verify_pvclock-<ns>.json)")
    p.add_argument("--label", type=str, default="")
    p.add_argument("--iters", type=int, default=1_000_000)
    args = p.parse_args()
    if args.output is None:
        args.output = default_output()

    clocksource = read_or_empty(f"{CLOCKSOURCE_DIR}/current_clocksource")
    available = read_or_empty(f"{CLOCKSOURCE_DIR}/available_clocksource")

    sr, sm = now_ns()
    ns_per_call = measure_per_call_ns(args.iters)
    fr, fm = now_ns()

    syscall_count = strace_count_clock_gettime_calls(iters=1000)
    if syscall_count is not None:
        # 0 (or near-0) syscalls under strace means vDSO; iters-proportional means not.
        vdso_active = syscall_count < 50
        vdso_basis = "strace"
    else:
        vdso_active = ns_per_call < VDSO_THRESHOLD_NS
        vdso_basis = "timing"

    probe = {
        "clocksource": clocksource,
        "available_clocksources": available,
        "clock_gettime_ns_per_call": ns_per_call,
        "clock_gettime_iters": args.iters,
        "vdso_active": vdso_active,
        "vdso_basis": vdso_basis,
        "strace_clock_gettime_count": syscall_count,
    }

    payload = {
        "benchmark": "verify_pvclock",
        "schema": 2,
        "args": {"label": args.label, "iters": args.iters},
        "started_at": sr, "finished_at": fr,
        "mono_start": sm, "mono_end": fm,
        "metadata": collect_metadata(),
        "result": probe,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2))

    print(f"clocksource = {clocksource or '(unknown)'}")
    print(f"available    = {available or '(unknown)'}")
    print(f"ns/call      = {ns_per_call:.1f}  ({vdso_basis} basis)")
    print(f"vdso_active  = {vdso_active}")
    if syscall_count is not None:
        print(f"strace count = {syscall_count}")
    print(f"-> {args.output}")
    if not vdso_active:
        print("WARNING: clock_gettime appears to take the syscall path. "
              "Sysbench/cpu_loop guest-time measurements will pay syscall cost; "
              "more importantly, verify the PV clocksource is actually selected.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
