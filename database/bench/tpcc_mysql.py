#!/usr/bin/env python3
"""Run TPC-C-like benchmarks on MySQL using sysbench."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

# Default configuration
DEFAULT_MYSQL_HOST = "localhost"
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_USER = "root"
DEFAULT_MYSQL_PASSWORD = "benchmark"
DEFAULT_DATABASE = "tpcc"

# TPC-C configuration
DEFAULT_TABLES = 10
DEFAULT_TABLE_SIZE = 10000
DEFAULT_THREADS = 1
DEFAULT_DURATION = 20  # seconds

# Sysbench Docker image
SYSBENCH_IMAGE = "severalnines/sysbench:latest"


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.run(cmd, check=check)


def pull_sysbench() -> None:
    """Pull sysbench Docker image."""
    print(f"Pulling sysbench image: {SYSBENCH_IMAGE}")
    run(["docker", "pull", SYSBENCH_IMAGE])
    print("Init complete.")


def cleanup_database(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
) -> None:
    """Drop and recreate TPC-C database for idempotent reruns."""
    print(f"Cleaning up database '{database}'...")

    # Drop and recreate database
    sql_commands = f"DROP DATABASE IF EXISTS {database}; CREATE DATABASE {database};"
    result = run([
        "docker", "run", "--rm", "-i",
        "--network", "host",
        "mysql:8.0",
        "mysql",
        "-h", mysql_host,
        "-P", str(mysql_port),
        "-u", mysql_user,
        f"-p{mysql_password}",
        "-e", sql_commands,
    ], check=False, capture=True)

    if result.returncode != 0:
        print(f"Warning: Could not cleanup database: {result.stderr}")
    else:
        print(f"Database '{database}' recreated")


def wait_for_mysql(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    timeout: int = 60,
) -> bool:
    """Wait for MySQL to be ready."""
    print(f"Waiting for MySQL at {mysql_host}:{mysql_port}...")
    start = time.time()
    while time.time() - start < timeout:
        result = run([
            "docker", "run", "--rm",
            "--network", "host",
            "mysql:8.0",
            "mysqladmin",
            "-h", mysql_host,
            "-P", str(mysql_port),
            "-u", mysql_user,
            f"-p{mysql_password}",
            "ping",
        ], check=False, capture=True)

        if result.returncode == 0:
            print("MySQL is ready")
            return True
        time.sleep(2)

    print("Timeout waiting for MySQL")
    return False


def sysbench_cmd(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
    tables: int,
    table_size: int,
    threads: int,
    action: str,
    duration: int = 0,
) -> list[str]:
    """Build sysbench command."""
    cmd = [
        "docker", "run", "--rm",
        "--network", "host",
        SYSBENCH_IMAGE,
        "sysbench",
        f"--mysql-host={mysql_host}",
        f"--mysql-port={mysql_port}",
        f"--mysql-user={mysql_user}",
        f"--mysql-password={mysql_password}",
        f"--mysql-db={database}",
        f"--tables={tables}",
        f"--table-size={table_size}",
        f"--threads={threads}",
        "--db-driver=mysql",
        "/usr/share/sysbench/oltp_read_write.lua",
    ]
    if action == "run" and duration > 0:
        cmd.insert(-1, f"--time={duration}")
        cmd.insert(-1, "--report-interval=10")
    cmd.append(action)
    return cmd


def prepare_data(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
    tables: int,
    table_size: int,
) -> None:
    """Prepare TPC-C data for benchmarking.

    This function:
    1. Pulls sysbench if needed
    2. Cleans up existing database
    3. Creates and populates benchmark tables

    Note: MySQL server must already be running.
    """
    print("Preparing TPC-C data...")
    print(f"  MySQL: {mysql_host}:{mysql_port}")
    print(f"  Database: {database}")
    print(f"  Tables: {tables}")
    print(f"  Table size: {table_size} rows each")

    # Wait for MySQL
    if not wait_for_mysql(mysql_host, mysql_port, mysql_user, mysql_password):
        print("Error: MySQL not available")
        sys.exit(1)

    # Cleanup existing data
    cleanup_database(mysql_host, mysql_port, mysql_user, mysql_password, database)

    # Prepare tables
    print("\nCreating and populating tables...")
    cmd = sysbench_cmd(
        mysql_host, mysql_port, mysql_user, mysql_password,
        database, tables, table_size, 1, "prepare"
    )
    run(cmd)

    print("\nTPC-C data preparation complete. You can now run the benchmark.")


def run_benchmark(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
    tables: int,
    table_size: int,
    threads: int,
    duration: int,
) -> None:
    """Run TPC-C benchmark.

    Note: This assumes data is already prepared. Run 'prepare' first.
    """
    print("Running TPC-C benchmark...")
    print(f"  MySQL: {mysql_host}:{mysql_port}")
    print(f"  Database: {database}")
    print(f"  Tables: {tables}")
    print(f"  Table size: {table_size}")
    print(f"  Threads: {threads}")
    print(f"  Duration: {duration}s")

    # Wait for MySQL
    if not wait_for_mysql(mysql_host, mysql_port, mysql_user, mysql_password):
        print("Error: MySQL not available")
        sys.exit(1)

    # Run benchmark
    print("\n" + "=" * 60)
    print("TPC-C BENCHMARK (OLTP Read/Write)")
    print("=" * 60)

    cmd = sysbench_cmd(
        mysql_host, mysql_port, mysql_user, mysql_password,
        database, tables, table_size, threads, "run", duration
    )

    start_time = time.time()
    run(cmd)
    elapsed = time.time() - start_time

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"  Total time: {elapsed:.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TPC-C-like benchmarks on MySQL using sysbench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pull sysbench Docker image
  %(prog)s init

  # Prepare TPC-C data
  %(prog)s prepare --mysql-host 10.0.0.1

  # Run TPC-C benchmark
  %(prog)s run --mysql-host 10.0.0.1 --threads 4 --duration 60

  # Cleanup database
  %(prog)s cleanup --mysql-host 10.0.0.1

Sysbench OLTP Read/Write workload:
  - Point selects, range selects
  - Updates (indexed and non-indexed)
  - Deletes and inserts
""",
    )

    subparsers = parser.add_subparsers(dest="action", required=True)

    # Common arguments
    def add_mysql_args(p):
        p.add_argument(
            "--mysql-host", "--host",
            default=DEFAULT_MYSQL_HOST,
            help=f"MySQL host (default: {DEFAULT_MYSQL_HOST})",
        )
        p.add_argument(
            "--mysql-port",
            type=int,
            default=DEFAULT_MYSQL_PORT,
            help=f"MySQL port (default: {DEFAULT_MYSQL_PORT})",
        )
        p.add_argument(
            "--mysql-user",
            default=DEFAULT_MYSQL_USER,
            help=f"MySQL user (default: {DEFAULT_MYSQL_USER})",
        )
        p.add_argument(
            "--mysql-password",
            default=DEFAULT_MYSQL_PASSWORD,
            help=f"MySQL password (default: {DEFAULT_MYSQL_PASSWORD})",
        )
        p.add_argument(
            "--database",
            default=DEFAULT_DATABASE,
            help=f"Database name (default: {DEFAULT_DATABASE})",
        )

    def add_table_args(p):
        p.add_argument(
            "--tables",
            type=int,
            default=DEFAULT_TABLES,
            help=f"Number of tables (default: {DEFAULT_TABLES})",
        )
        p.add_argument(
            "--table-size",
            type=int,
            default=DEFAULT_TABLE_SIZE,
            help=f"Rows per table (default: {DEFAULT_TABLE_SIZE})",
        )

    # Init subcommand
    subparsers.add_parser("init", help="Pull sysbench Docker image")

    # Cleanup subcommand
    cleanup_parser = subparsers.add_parser("cleanup", help="Drop TPC-C database")
    add_mysql_args(cleanup_parser)

    # Prepare subcommand
    prepare_parser = subparsers.add_parser("prepare", help="Prepare TPC-C data")
    add_mysql_args(prepare_parser)
    add_table_args(prepare_parser)

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run TPC-C benchmark")
    add_mysql_args(run_parser)
    add_table_args(run_parser)
    run_parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"Number of threads (default: {DEFAULT_THREADS})",
    )
    run_parser.add_argument(
        "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help=f"Test duration in seconds (default: {DEFAULT_DURATION})",
    )

    args = parser.parse_args()

    if args.action == "init":
        pull_sysbench()

    elif args.action == "cleanup":
        cleanup_database(
            args.mysql_host, args.mysql_port,
            args.mysql_user, args.mysql_password,
            args.database,
        )

    elif args.action == "prepare":
        prepare_data(
            args.mysql_host, args.mysql_port,
            args.mysql_user, args.mysql_password,
            args.database, args.tables, args.table_size,
        )

    elif args.action == "run":
        run_benchmark(
            args.mysql_host, args.mysql_port,
            args.mysql_user, args.mysql_password,
            args.database, args.tables, args.table_size,
            args.threads, args.duration,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
