#!/usr/bin/env python3
"""Write a host-wall sidecar JSON next to a guest result.

The host driver invokes this twice per phase: once to capture start (--start)
and once to capture end (--end), pointing at the same --output. The end
invocation merges and finalises.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_results import collect_metadata, now_ns  # noqa: E402


def default_output(benchmark: str, label: str) -> Path:
    """Deterministic per-(benchmark,label) tempfile so --phase start/end pair
    automatically without the caller plumbing an explicit path."""
    suffix = f"-{label}" if label else ""
    return Path(tempfile.gettempdir()) / f"{benchmark}{suffix}.host_bracket.json"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, default=None,
                   help="bracket JSON path (default: /tmp/<benchmark>[-<label>].host_bracket.json)")
    p.add_argument("--phase", choices=["start", "end"], required=True)
    p.add_argument("--benchmark", type=str, required=True)
    p.add_argument("--label", type=str, default="")
    args = p.parse_args()
    if args.output is None:
        args.output = default_output(args.benchmark, args.label)

    real_ns, mono_ns = now_ns()
    if args.phase == "start":
        payload = {
            "benchmark": args.benchmark,
            "schema": 2,
            "kind": "host_bracket",
            "label": args.label,
            "started_at": real_ns,
            "mono_start": mono_ns,
            "metadata": collect_metadata(),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2))
    else:
        existing = json.loads(args.output.read_text())
        existing["finished_at"] = real_ns
        existing["mono_end"] = mono_ns
        args.output.write_text(json.dumps(existing, indent=2))
    print(f"-> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
