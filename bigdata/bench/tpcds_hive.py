#!/usr/bin/env python3
"""Run TPC-DS benchmarks on Hive cluster."""

import argparse
import sys
import tempfile
import time
import os
from pathlib import Path

from tpcds import (
    DEFAULT_HDFS_BASE,
    DEFAULT_SCALE_FACTOR,
    DEFAULT_TPCDS_KIT,
    TABLE_SCHEMAS,
    TPCDS_QUERY_99,
    ensure_data_ready,
    generate_data,
    get_schema_string,
    run,
)

DEFAULT_HIVESERVER2 = "localhost:10000"

# Path to framework wrapper
FW_DIR = Path(__file__).parent.parent / "fw"
HIVE_PY = FW_DIR / "hive.py"


def generate_create_table_sql(table: str, hdfs_base: str, scale_factor: int) -> str:
    """Generate CREATE EXTERNAL TABLE statement for a TPC-DS table."""
    schema_str = get_schema_string(table, separator=",\n    ")
    # LOCATION points to directory containing data files
    location = f"{hdfs_base}/raw/sf{scale_factor}/{table}"

    return f"""
CREATE EXTERNAL TABLE IF NOT EXISTS {table} (
    {schema_str}
)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY '|'
STORED AS TEXTFILE
LOCATION '{location}';
"""


def generate_cleanup_sql() -> str:
    """Generate HiveQL script to drop TPC-DS tables."""
    drop_statements = "\n".join(f"DROP TABLE IF EXISTS {table};" for table in TABLE_SCHEMAS)
    return f"""-- TPC-DS Cleanup Script for Hive
-- Drop all TPC-DS tables for idempotent reruns

{drop_statements}

-- Verify tables are dropped
SHOW TABLES;
"""


def cleanup_tables(hiveserver2: str) -> None:
    """Drop TPC-DS tables from Hive for idempotent reruns."""
    print("Cleaning up TPC-DS tables from Hive...")
    print(f"  HiveServer2: {hiveserver2}")

    # Generate cleanup script
    script_content = generate_cleanup_sql()

    # Write script to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sql", delete=False
    ) as f:
        f.write(script_content)
        script_path = f.name
    os.chmod(script_path, 0o644)

    try:
        # Run via framework wrapper
        run([
            sys.executable, str(HIVE_PY), "cmd",
            "--hiveserver2", hiveserver2,
            "--", "-f", script_path,
        ])
        print("Cleanup complete")
    finally:
        os.unlink(script_path)


def generate_hive_script(
    hdfs_base: str,
    scale_factor: int,
) -> str:
    """Generate HiveQL script for TPC-DS Query 99."""
    # Generate CREATE TABLE statements for all required tables
    create_statements = []
    for table in TABLE_SCHEMAS:
        create_statements.append(generate_create_table_sql(table, hdfs_base, scale_factor))

    return f"""-- TPC-DS Query 99 Benchmark for Hive
-- Scale factor: {scale_factor}
-- HDFS base: {hdfs_base}

SET hive.cli.print.header=true;
SET hive.resultset.use.unique.column.names=false;

-- Drop existing tables if any
{"".join(f"DROP TABLE IF EXISTS {table};" for table in TABLE_SCHEMAS)}

-- Create external tables pointing to HDFS data
{"".join(create_statements)}

-- Verify tables are loaded
{"".join(f"SELECT COUNT(*) AS {table}_count FROM {table};" for table in TABLE_SCHEMAS)}

-- TPC-DS Query 99: Analyze late shipments by shipping mode and warehouse
{TPCDS_QUERY_99}
"""


def prepare_data(
    hdfs_base: str,
    scale_factor: int,
    namenode_data_dir: str = "/tmp/hdfs-data-nn",
) -> None:
    """Prepare TPC-DS data in HDFS (generate locally and upload)."""
    print("Preparing TPC-DS data...")
    print(f"  Scale factor: {scale_factor}")
    print(f"  HDFS base: {hdfs_base}")
    ensure_data_ready(hdfs_base, scale_factor, namenode_data_dir=namenode_data_dir)
    print("\nData preparation complete. You can now run the benchmark.")


def run_benchmark(
    hiveserver2: str,
    hdfs_base: str,
    scale_factor: int,
    database: str,
) -> None:
    """Run the TPC-DS Q99 benchmark using hive.py cmd.

    Note: This assumes data is already prepared in HDFS. Run 'prepare' first.
    """
    print("=" * 60)
    print("TPC-DS Query 99 Benchmark (Hive)")
    print("=" * 60)
    print(f"HiveServer2: {hiveserver2}")
    print(f"HDFS base: {hdfs_base}")
    print(f"Scale factor: {scale_factor}")
    print(f"Database: {database}")
    print("=" * 60)

    total_start = time.time()

    # Auto-cleanup for idempotent reruns
    print("\nCleaning up previous tables...")
    cleanup_tables(hiveserver2)

    # Generate HiveQL script
    script_content = generate_hive_script(hdfs_base, scale_factor)

    # Write script to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sql", delete=False
    ) as f:
        f.write(script_content)
        script_path = f.name
    os.chmod(script_path, 0o644)

    try:
        # Run via framework wrapper
        run([
            sys.executable, str(HIVE_PY), "cmd",
            "--hiveserver2", hiveserver2,
            "--", "-f", script_path, "--verbose=true",
        ])
    finally:
        os.unlink(script_path)

    total_time = time.time() - total_start

    print("\n" + "=" * 60)
    print("Benchmark Summary")
    print("=" * 60)
    print(f"Total time: {total_time:.2f} seconds")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TPC-DS benchmarks on Hive cluster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate TPC-DS data (scale factor 1 = ~1GB)
  %(prog)s generate --scale 1

  # Prepare TPC-DS data in HDFS (generate if needed, upload to HDFS)
  %(prog)s prepare --hdfs-base hdfs://10.0.0.1:9000/bench/tpcds

  # Run TPC-DS Query 99 benchmark (data must be prepared first)
  %(prog)s run --hiveserver2 10.0.0.1:10000 --hdfs-base hdfs://10.0.0.1:9000/bench/tpcds

  # Run with custom scale factor and database
  %(prog)s run --hiveserver2 10.0.0.1:10000 --scale 10 --database tpcds
""",
    )

    subparsers = parser.add_subparsers(dest="action", required=True)

    # Cleanup subcommand
    cleanup_parser = subparsers.add_parser("cleanup", help="Drop TPC-DS tables for idempotent reruns")
    cleanup_parser.add_argument(
        "--hiveserver2",
        default=DEFAULT_HIVESERVER2,
        help=f"HiveServer2 host:port (default: {DEFAULT_HIVESERVER2})",
    )

    # Generate subcommand (data generation only)
    gen_parser = subparsers.add_parser("generate", help="Generate TPC-DS data")
    gen_parser.add_argument(
        "--scale",
        type=int,
        default=DEFAULT_SCALE_FACTOR,
        help=f"Scale factor (default: {DEFAULT_SCALE_FACTOR}, 1 = ~1GB)",
    )
    gen_parser.add_argument(
        "--output-dir",
        default="/tmp/tpcds_sf1",
        help="Output directory for generated data (default: /tmp/tpcds_sf1)",
    )
    gen_parser.add_argument(
        "--tpcds-kit",
        default=DEFAULT_TPCDS_KIT,
        help=f"Path to tpcds-kit directory (default: {DEFAULT_TPCDS_KIT})",
    )

    # Prepare subcommand (generate + upload to HDFS)
    prep_parser = subparsers.add_parser("prepare", help="Prepare TPC-DS data in HDFS")
    prep_parser.add_argument(
        "--scale",
        type=int,
        default=DEFAULT_SCALE_FACTOR,
        help=f"Scale factor (default: {DEFAULT_SCALE_FACTOR}, 1 = ~1GB)",
    )
    prep_parser.add_argument(
        "--hdfs-base",
        default=DEFAULT_HDFS_BASE,
        help=f"HDFS base path (default: {DEFAULT_HDFS_BASE})",
    )
    prep_parser.add_argument(
        "--namenode-data-dir",
        default="/tmp/hdfs-data-nn",
        help="Local directory mounted to namenode container (default: /tmp/hdfs-data-nn)",
    )

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run TPC-DS Query 99 benchmark")
    run_parser.add_argument(
        "--hiveserver2",
        default=DEFAULT_HIVESERVER2,
        help=f"HiveServer2 host:port (default: {DEFAULT_HIVESERVER2})",
    )
    run_parser.add_argument(
        "--scale",
        type=int,
        default=DEFAULT_SCALE_FACTOR,
        help=f"Scale factor (default: {DEFAULT_SCALE_FACTOR})",
    )
    run_parser.add_argument(
        "--hdfs-base",
        default=DEFAULT_HDFS_BASE,
        help=f"HDFS base path (default: {DEFAULT_HDFS_BASE})",
    )
    run_parser.add_argument(
        "--database",
        default="default",
        help="Hive database to use (default: default)",
    )

    args = parser.parse_args()

    if args.action == "cleanup":
        cleanup_tables(args.hiveserver2)
    elif args.action == "generate":
        output_dir = args.output_dir.replace("sf1", f"sf{args.scale}")
        generate_data(args.scale, output_dir, args.tpcds_kit)
    elif args.action == "prepare":
        prepare_data(args.hdfs_base, args.scale, args.namenode_data_dir)
    elif args.action == "run":
        run_benchmark(
            args.hiveserver2,
            args.hdfs_base,
            args.scale,
            args.database,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
