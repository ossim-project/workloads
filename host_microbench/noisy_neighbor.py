#!/usr/bin/env python3
"""Noisy-neighbor driver: runs stress-ng with one of a few canned profiles.

Profiles target different parts of the memory hierarchy:
  cache     - LLC pollution via stress-ng --cache
  bandwidth - DRAM bus contention via stress-ng --stream
  vm        - page allocation / fault thrash via stress-ng --vm
"""

from __future__ import annotations

import argparse
import shlex
import signal
import subprocess
import sys
import time

PROFILES = {
    "cache":     ["--cache", "{workers}", "--cache-level", "3"],
    "bandwidth": ["--stream", "{workers}"],
    "vm":        ["--vm", "{workers}", "--vm-bytes", "75%", "--vm-method", "all"],
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", choices=PROFILES.keys(), required=True)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--duration", type=int, default=30,
                   help="seconds; 0 = run until SIGTERM")
    args = p.parse_args()

    flags = [f.format(workers=str(args.workers)) for f in PROFILES[args.profile]]
    cmd = ["stress-ng", *flags]
    if args.duration > 0:
        cmd += ["--timeout", f"{args.duration}s"]
    cmd += ["--metrics-brief"]

    print(f"noisy_neighbor: {shlex.join(cmd)}", flush=True)
    proc = subprocess.Popen(cmd)

    def _stop(signo, _frame):
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    rc = proc.wait()
    print(f"noisy_neighbor: exit={rc}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
