#!/usr/bin/env python3
"""
File I/O Benchmark using fio

A Python wrapper for fio (Flexible I/O Tester) that runs common I/O benchmarks
and produces structured results.

Usage:
    ./bench_fileio.py [OPTIONS]
    ./bench_fileio.py --profile randread --size 1G --runtime 30
    ./bench_fileio.py --profile all --output results.json
"""

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FioProfile:
    """Fio test profile configuration."""
    name: str
    rw: str  # readwrite mode
    description: str
    bs: str = "4k"  # block size
    iodepth: int = 32
    direct: int = 1  # O_DIRECT
    ioengine: str = "libaio"


# Predefined test profiles
PROFILES = {
    "seqread": FioProfile(
        name="seqread",
        rw="read",
        bs="128k",
        description="Sequential read",
    ),
    "seqwrite": FioProfile(
        name="seqwrite",
        rw="write",
        bs="128k",
        description="Sequential write",
    ),
    "randread": FioProfile(
        name="randread",
        rw="randread",
        bs="4k",
        description="Random read (4K)",
    ),
    "randwrite": FioProfile(
        name="randwrite",
        rw="randwrite",
        bs="4k",
        description="Random write (4K)",
    ),
    "randrw": FioProfile(
        name="randrw",
        rw="randrw",
        bs="4k",
        description="Random read/write mix (4K)",
    ),
}


def check_fio() -> bool:
    """Check if fio is installed."""
    try:
        subprocess.run(["fio", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def run_fio(
    profile: FioProfile,
    size: str,
    runtime: int,
    numjobs: int,
    directory: Path,
) -> dict:
    """Run fio with the given profile and return parsed JSON results."""

    job_config = f"""[{profile.name}]
rw={profile.rw}
bs={profile.bs}
size={size}
runtime={runtime}
time_based=1
numjobs={numjobs}
iodepth={profile.iodepth}
direct={profile.direct}
ioengine={profile.ioengine}
group_reporting=1
directory={directory}
filename=fio_testfile
"""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".fio", delete=False) as f:
        f.write(job_config)
        job_file = Path(f.name)

    try:
        result = subprocess.run(
            ["fio", str(job_file), "--output-format=json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)
    finally:
        job_file.unlink()
        # Clean up test file
        test_file = directory / "fio_testfile"
        if test_file.exists():
            test_file.unlink()


def format_bytes(n: float) -> str:
    """Format bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def format_iops(n: float) -> str:
    """Format IOPS to human readable string."""
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.2f}K"
    return f"{n:.2f}"


def extract_results(fio_output: dict, profile: FioProfile) -> dict:
    """Extract relevant metrics from fio JSON output."""
    job = fio_output["jobs"][0]

    results = {
        "profile": profile.name,
        "description": profile.description,
        "block_size": profile.bs,
    }

    # Extract read stats if present
    if job["read"]["io_bytes"] > 0:
        read = job["read"]
        results["read"] = {
            "iops": read["iops"],
            "bw_bytes": read["bw_bytes"],
            "lat_ns_mean": read["lat_ns"]["mean"],
            "lat_ns_p99": read["clat_ns"]["percentile"].get("99.000000", 0),
        }

    # Extract write stats if present
    if job["write"]["io_bytes"] > 0:
        write = job["write"]
        results["write"] = {
            "iops": write["iops"],
            "bw_bytes": write["bw_bytes"],
            "lat_ns_mean": write["lat_ns"]["mean"],
            "lat_ns_p99": write["clat_ns"]["percentile"].get("99.000000", 0),
        }

    return results


def print_results(results: dict) -> None:
    """Print results in a human-readable format."""
    print(f"\n{'='*60}")
    print(f"Profile: {results['description']} ({results['profile']})")
    print(f"Block Size: {results['block_size']}")
    print(f"{'='*60}")

    for op in ["read", "write"]:
        if op not in results:
            continue
        stats = results[op]
        print(f"\n  {op.upper()}:")
        print(f"    IOPS:        {format_iops(stats['iops'])}")
        print(f"    Bandwidth:   {format_bytes(stats['bw_bytes'])}/s")
        print(f"    Latency avg: {stats['lat_ns_mean']/1000:.2f} us")
        print(f"    Latency p99: {stats['lat_ns_p99']/1000:.2f} us")


def main():
    parser = argparse.ArgumentParser(
        description="File I/O Benchmark using fio",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Profiles:
  seqread    Sequential read (128K blocks)
  seqwrite   Sequential write (128K blocks)
  randread   Random read (4K blocks)
  randwrite  Random write (4K blocks)
  randrw     Random read/write mix (4K blocks)
  all        Run all profiles

Examples:
  %(prog)s --profile randread
  %(prog)s --profile all --size 1G --runtime 30
  %(prog)s --profile seqwrite --directory /mnt/nvme --output results.json
""",
    )
    parser.add_argument(
        "--profile", "-p",
        choices=list(PROFILES.keys()) + ["all"],
        default="randrw",
        help="Test profile to run (default: randrw)",
    )
    parser.add_argument(
        "--size", "-s",
        default="512M",
        help="Test file size (default: 512M)",
    )
    parser.add_argument(
        "--runtime", "-t",
        type=int,
        default=10,
        help="Test duration in seconds (default: 10)",
    )
    parser.add_argument(
        "--numjobs", "-j",
        type=int,
        default=1,
        help="Number of parallel jobs (default: 1)",
    )
    parser.add_argument(
        "--directory", "-d",
        type=Path,
        default=None,
        help="Directory for test files (default: temp directory)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output JSON file for results",
    )

    args = parser.parse_args()

    if not check_fio():
        print("Error: fio is not installed. Install with: sudo apt install fio", file=sys.stderr)
        sys.exit(1)

    # Determine test directory
    if args.directory:
        test_dir = args.directory
        test_dir.mkdir(parents=True, exist_ok=True)
        cleanup_dir = False
    else:
        test_dir = Path(tempfile.mkdtemp(prefix="fio_bench_"))
        cleanup_dir = True

    # Determine profiles to run
    if args.profile == "all":
        profiles_to_run = list(PROFILES.values())
    else:
        profiles_to_run = [PROFILES[args.profile]]

    all_results = []

    try:
        print(f"Running fio benchmarks in: {test_dir}")
        print(f"File size: {args.size}, Runtime: {args.runtime}s, Jobs: {args.numjobs}")

        for profile in profiles_to_run:
            print(f"\nRunning {profile.description}...")
            fio_output = run_fio(
                profile=profile,
                size=args.size,
                runtime=args.runtime,
                numjobs=args.numjobs,
                directory=test_dir,
            )
            results = extract_results(fio_output, profile)
            all_results.append(results)
            print_results(results)

        # Save JSON output if requested
        if args.output:
            with open(args.output, "w") as f:
                json.dump(all_results, f, indent=2)
            print(f"\nResults saved to: {args.output}")

    finally:
        if cleanup_dir:
            import shutil
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
