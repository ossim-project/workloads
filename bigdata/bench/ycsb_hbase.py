#!/usr/bin/env python3
"""Run YCSB benchmarks on HBase cluster."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# YCSB configuration
DEFAULT_YCSB_VERSION = "0.17.0"
DEFAULT_YCSB_DIR = "/tmp/ycsb"
DEFAULT_ZOOKEEPER = "localhost:2181"
DEFAULT_TABLE = "usertable"
DEFAULT_RECORD_COUNT = 10000
DEFAULT_OPERATION_COUNT = 10000

# YCSB workloads
WORKLOADS = {
    "a": "Update heavy (50% read, 50% update)",
    "b": "Read heavy (95% read, 5% update)",
    "c": "Read only (100% read)",
    "d": "Read latest (95% read, 5% insert)",
    "e": "Short ranges (95% scan, 5% insert)",
    "f": "Read-modify-write (50% read, 50% RMW)",
}

# Path to framework wrapper
FW_DIR = Path(__file__).parent.parent / "fw"
HBASE_PY = FW_DIR / "hbase.py"


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.run(cmd, check=check)


def prepare_data(
    ycsb_dir: str,
    version: str,
    zookeeper: str,
    table: str,
) -> None:
    """Prepare YCSB data for benchmarking.

    This function:
    1. Downloads YCSB if not already present
    2. Creates the HBase table for benchmarking

    Note: HBase cluster must already be running.
    """
    print("Preparing YCSB data...")
    print(f"  ZooKeeper: {zookeeper}")
    print(f"  Table: {table}")
    print(f"  YCSB dir: {ycsb_dir}")

    # Download YCSB
    download_ycsb(ycsb_dir, version)

    # Cleanup existing table and create fresh
    cleanup_table(zookeeper, table)
    create_table(zookeeper, table)

    print("\nYCSB data preparation complete. You can now run the benchmark.")


def download_ycsb(ycsb_dir: str, version: str) -> None:
    """Download and extract YCSB."""
    ycsb_path = Path(ycsb_dir)
    if ycsb_path.exists() and (ycsb_path / "bin" / "ycsb.sh").exists():
        print(f"YCSB already exists at {ycsb_dir}")
        return

    print(f"Downloading YCSB {version}...")
    url = f"https://github.com/brianfrankcooper/YCSB/releases/download/{version}/ycsb-{version}.tar.gz"

    run(["rm", "-rf", ycsb_dir])
    run(["mkdir", "-p", str(ycsb_path.parent)])
    run(["curl", "-fSL", url, "-o", "/tmp/ycsb.tar.gz"])
    run(["tar", "-xzf", "/tmp/ycsb.tar.gz", "-C", str(ycsb_path.parent)])
    run(["mv", f"{ycsb_path.parent}/ycsb-{version}", ycsb_dir])
    run(["rm", "/tmp/ycsb.tar.gz"])

    print(f"YCSB downloaded to {ycsb_dir}")


def create_table(zookeeper: str, table: str) -> None:
    """Create YCSB table in HBase."""
    print(f"Creating table '{table}' in HBase...")

    # Get ZooKeeper host
    zk_host = zookeeper.split(":")[0]

    # Create table using HBase shell via docker
    hbase_cmd = f"create '{table}', 'family'"
    result = run([
        "docker", "exec", "hbase-master",
        "bash", "-c",
        f"echo \"{hbase_cmd}\" | /opt/hbase/bin/hbase shell 2>/dev/null"
    ], check=False, capture=True)

    if "TableExistsException" in result.stderr or "already exists" in result.stdout:
        print(f"Table '{table}' already exists")
    elif result.returncode != 0:
        print(f"Warning: Could not create table: {result.stderr}")
    else:
        print(f"Table '{table}' created")


def cleanup_table(zookeeper: str, table: str) -> None:
    """Drop YCSB table from HBase for idempotent reruns."""
    print(f"Cleaning up table '{table}' from HBase...")

    # Disable and drop table using HBase shell via docker
    hbase_cmd = f"disable '{table}'; drop '{table}'"
    result = run([
        "docker", "exec", "hbase-master",
        "bash", "-c",
        f"echo \"{hbase_cmd}\" | /opt/hbase/bin/hbase shell 2>/dev/null"
    ], check=False, capture=True)

    if "TableNotFoundException" in result.stderr or "does not exist" in result.stdout:
        print(f"Table '{table}' does not exist (already clean)")
    elif result.returncode != 0:
        print(f"Warning: Could not drop table: {result.stderr}")
    else:
        print(f"Table '{table}' dropped")


def run_ycsb(
    ycsb_dir: str,
    phase: str,
    workload: str,
    zookeeper: str,
    table: str,
    record_count: int,
    operation_count: int,
    threads: int,
) -> None:
    """Run YCSB load or run phase."""
    ycsb_bin = Path(ycsb_dir) / "bin" / "ycsb.sh"

    if not ycsb_bin.exists():
        print(f"Error: YCSB not found at {ycsb_dir}")
        sys.exit(1)

    # Parse ZooKeeper
    if ":" in zookeeper:
        zk_host, zk_port = zookeeper.rsplit(":", 1)
    else:
        zk_host = zookeeper
        zk_port = "2181"

    # Build command
    cmd = [
        str(ycsb_bin), phase, "hbase20",
        "-P", f"{ycsb_dir}/workloads/workload{workload}",
        "-p", f"hbase.zookeeper.quorum={zk_host}",
        "-p", f"hbase.zookeeper.property.clientPort={zk_port}",
        "-p", f"table={table}",
        "-p", "columnfamily=family",
        "-p", f"recordcount={record_count}",
        "-p", f"operationcount={operation_count}",
        "-threads", str(threads),
        "-s",  # Print status
    ]

    print(f"\n{'='*60}")
    print(f"YCSB {phase.upper()} - Workload {workload.upper()}: {WORKLOADS.get(workload, 'Unknown')}")
    print(f"{'='*60}")
    print(f"  ZooKeeper: {zookeeper}")
    print(f"  Table: {table}")
    print(f"  Record count: {record_count}")
    print(f"  Operation count: {operation_count}")
    print(f"  Threads: {threads}")
    print()

    start_time = time.time()
    run(cmd)
    elapsed = time.time() - start_time

    print(f"\n{phase.upper()} completed in {elapsed:.2f} seconds")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run YCSB benchmarks on HBase cluster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download YCSB
  %(prog)s init

  # Prepare YCSB data (download YCSB and create table)
  %(prog)s prepare --zookeeper 10.0.0.1:2181

  # Load data for workload A
  %(prog)s load --workload a --zookeeper 10.0.0.1:2181

  # Run workload A benchmark
  %(prog)s run --workload a --zookeeper 10.0.0.1:2181

  # Run all workloads
  %(prog)s run-all --zookeeper 10.0.0.1:2181

Available workloads:
  a - Update heavy (50%% read, 50%% update)
  b - Read heavy (95%% read, 5%% update)
  c - Read only (100%% read)
  d - Read latest (95%% read, 5%% insert)
  e - Short ranges (95%% scan, 5%% insert)
  f - Read-modify-write (50%% read, 50%% RMW)
""",
    )

    subparsers = parser.add_subparsers(dest="action", required=True)

    # Cleanup subcommand
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up YCSB table for idempotent reruns")
    cleanup_parser.add_argument(
        "--zookeeper",
        default=DEFAULT_ZOOKEEPER,
        help=f"ZooKeeper host:port (default: {DEFAULT_ZOOKEEPER})",
    )
    cleanup_parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"HBase table name (default: {DEFAULT_TABLE})",
    )

    # Init subcommand
    init_parser = subparsers.add_parser("init", help="Download YCSB")
    init_parser.add_argument(
        "--ycsb-dir",
        default=DEFAULT_YCSB_DIR,
        help=f"YCSB installation directory (default: {DEFAULT_YCSB_DIR})",
    )
    init_parser.add_argument(
        "--version",
        default=DEFAULT_YCSB_VERSION,
        help=f"YCSB version (default: {DEFAULT_YCSB_VERSION})",
    )

    # Prepare subcommand
    prepare_parser = subparsers.add_parser("prepare", help="Prepare YCSB data (download YCSB and create table)")
    prepare_parser.add_argument(
        "--zookeeper",
        default=DEFAULT_ZOOKEEPER,
        help=f"ZooKeeper host:port (default: {DEFAULT_ZOOKEEPER})",
    )
    prepare_parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help=f"HBase table name (default: {DEFAULT_TABLE})",
    )
    prepare_parser.add_argument(
        "--ycsb-dir",
        default=DEFAULT_YCSB_DIR,
        help=f"YCSB installation directory (default: {DEFAULT_YCSB_DIR})",
    )
    prepare_parser.add_argument(
        "--version",
        default=DEFAULT_YCSB_VERSION,
        help=f"YCSB version (default: {DEFAULT_YCSB_VERSION})",
    )

    # Common benchmark options
    def add_benchmark_args(p):
        p.add_argument(
            "--zookeeper",
            default=DEFAULT_ZOOKEEPER,
            help=f"ZooKeeper host:port (default: {DEFAULT_ZOOKEEPER})",
        )
        p.add_argument(
            "--table",
            default=DEFAULT_TABLE,
            help=f"HBase table name (default: {DEFAULT_TABLE})",
        )
        p.add_argument(
            "--record-count",
            type=int,
            default=DEFAULT_RECORD_COUNT,
            help=f"Number of records (default: {DEFAULT_RECORD_COUNT})",
        )
        p.add_argument(
            "--operation-count",
            type=int,
            default=DEFAULT_OPERATION_COUNT,
            help=f"Number of operations (default: {DEFAULT_OPERATION_COUNT})",
        )
        p.add_argument(
            "--threads",
            type=int,
            default=1,
            help="Number of client threads (default: 1)",
        )
        p.add_argument(
            "--ycsb-dir",
            default=DEFAULT_YCSB_DIR,
            help=f"YCSB installation directory (default: {DEFAULT_YCSB_DIR})",
        )

    # Load subcommand
    load_parser = subparsers.add_parser("load", help="Load data into HBase")
    load_parser.add_argument(
        "--workload",
        choices=list(WORKLOADS.keys()),
        default="a",
        help="Workload type (default: a)",
    )
    add_benchmark_args(load_parser)

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run YCSB workload")
    run_parser.add_argument(
        "--workload",
        choices=list(WORKLOADS.keys()),
        default="a",
        help="Workload type (default: a)",
    )
    add_benchmark_args(run_parser)

    # Run-all subcommand
    run_all_parser = subparsers.add_parser("run-all", help="Run all YCSB workloads")
    add_benchmark_args(run_all_parser)

    args = parser.parse_args()

    if args.action == "cleanup":
        cleanup_table(args.zookeeper, args.table)

    elif args.action == "init":
        download_ycsb(args.ycsb_dir, args.version)

    elif args.action == "prepare":
        prepare_data(args.ycsb_dir, args.version, args.zookeeper, args.table)

    elif args.action == "load":
        # Auto-cleanup for idempotent reruns
        cleanup_table(args.zookeeper, args.table)
        create_table(args.zookeeper, args.table)
        run_ycsb(
            args.ycsb_dir, "load", args.workload, args.zookeeper, args.table,
            args.record_count, args.operation_count, args.threads
        )

    elif args.action == "run":
        run_ycsb(
            args.ycsb_dir, "run", args.workload, args.zookeeper, args.table,
            args.record_count, args.operation_count, args.threads
        )

    elif args.action == "run-all":
        # First load data using workload A
        create_table(args.zookeeper, args.table)
        run_ycsb(
            args.ycsb_dir, "load", "a", args.zookeeper, args.table,
            args.record_count, args.operation_count, args.threads
        )

        # Run each workload
        for workload in WORKLOADS:
            run_ycsb(
                args.ycsb_dir, "run", workload, args.zookeeper, args.table,
                args.record_count, args.operation_count, args.threads
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
