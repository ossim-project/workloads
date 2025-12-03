#!/usr/bin/env python3
"""Run TPC-H benchmarks on MySQL."""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Default configuration
DEFAULT_MYSQL_HOST = "localhost"
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MYSQL_USER = "root"
DEFAULT_MYSQL_PASSWORD = "benchmark"
DEFAULT_DATABASE = "tpch"

# TPC-H configuration
DEFAULT_SCALE_FACTOR = 0.5  # 0.1 = ~100MB, 1 = ~1GB
DEFAULT_TPCH_DBGEN = "/tmp/tpch-dbgen"


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.run(cmd, check=check)


# TPC-H table schemas for MySQL
TPCH_SCHEMAS = {
    "nation": """
        CREATE TABLE nation (
            n_nationkey INTEGER NOT NULL,
            n_name CHAR(25) NOT NULL,
            n_regionkey INTEGER NOT NULL,
            n_comment VARCHAR(152),
            PRIMARY KEY (n_nationkey)
        )
    """,
    "region": """
        CREATE TABLE region (
            r_regionkey INTEGER NOT NULL,
            r_name CHAR(25) NOT NULL,
            r_comment VARCHAR(152),
            PRIMARY KEY (r_regionkey)
        )
    """,
    "part": """
        CREATE TABLE part (
            p_partkey INTEGER NOT NULL,
            p_name VARCHAR(55) NOT NULL,
            p_mfgr CHAR(25) NOT NULL,
            p_brand CHAR(10) NOT NULL,
            p_type VARCHAR(25) NOT NULL,
            p_size INTEGER NOT NULL,
            p_container CHAR(10) NOT NULL,
            p_retailprice DECIMAL(15,2) NOT NULL,
            p_comment VARCHAR(23) NOT NULL,
            PRIMARY KEY (p_partkey)
        )
    """,
    "supplier": """
        CREATE TABLE supplier (
            s_suppkey INTEGER NOT NULL,
            s_name CHAR(25) NOT NULL,
            s_address VARCHAR(40) NOT NULL,
            s_nationkey INTEGER NOT NULL,
            s_phone CHAR(15) NOT NULL,
            s_acctbal DECIMAL(15,2) NOT NULL,
            s_comment VARCHAR(101) NOT NULL,
            PRIMARY KEY (s_suppkey)
        )
    """,
    "partsupp": """
        CREATE TABLE partsupp (
            ps_partkey INTEGER NOT NULL,
            ps_suppkey INTEGER NOT NULL,
            ps_availqty INTEGER NOT NULL,
            ps_supplycost DECIMAL(15,2) NOT NULL,
            ps_comment VARCHAR(199) NOT NULL,
            PRIMARY KEY (ps_partkey, ps_suppkey)
        )
    """,
    "customer": """
        CREATE TABLE customer (
            c_custkey INTEGER NOT NULL,
            c_name VARCHAR(25) NOT NULL,
            c_address VARCHAR(40) NOT NULL,
            c_nationkey INTEGER NOT NULL,
            c_phone CHAR(15) NOT NULL,
            c_acctbal DECIMAL(15,2) NOT NULL,
            c_mktsegment CHAR(10) NOT NULL,
            c_comment VARCHAR(117) NOT NULL,
            PRIMARY KEY (c_custkey)
        )
    """,
    "orders": """
        CREATE TABLE orders (
            o_orderkey INTEGER NOT NULL,
            o_custkey INTEGER NOT NULL,
            o_orderstatus CHAR(1) NOT NULL,
            o_totalprice DECIMAL(15,2) NOT NULL,
            o_orderdate DATE NOT NULL,
            o_orderpriority CHAR(15) NOT NULL,
            o_clerk CHAR(15) NOT NULL,
            o_shippriority INTEGER NOT NULL,
            o_comment VARCHAR(79) NOT NULL,
            PRIMARY KEY (o_orderkey)
        )
    """,
    "lineitem": """
        CREATE TABLE lineitem (
            l_orderkey INTEGER NOT NULL,
            l_partkey INTEGER NOT NULL,
            l_suppkey INTEGER NOT NULL,
            l_linenumber INTEGER NOT NULL,
            l_quantity DECIMAL(15,2) NOT NULL,
            l_extendedprice DECIMAL(15,2) NOT NULL,
            l_discount DECIMAL(15,2) NOT NULL,
            l_tax DECIMAL(15,2) NOT NULL,
            l_returnflag CHAR(1) NOT NULL,
            l_linestatus CHAR(1) NOT NULL,
            l_shipdate DATE NOT NULL,
            l_commitdate DATE NOT NULL,
            l_receiptdate DATE NOT NULL,
            l_shipinstruct CHAR(25) NOT NULL,
            l_shipmode CHAR(10) NOT NULL,
            l_comment VARCHAR(44) NOT NULL,
            PRIMARY KEY (l_orderkey, l_linenumber)
        )
    """,
}

# TPC-H Query 1 - Pricing Summary Report
TPCH_QUERY_1 = """
SELECT
    l_returnflag,
    l_linestatus,
    SUM(l_quantity) AS sum_qty,
    SUM(l_extendedprice) AS sum_base_price,
    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
    AVG(l_quantity) AS avg_qty,
    AVG(l_extendedprice) AS avg_price,
    AVG(l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM
    lineitem
WHERE
    l_shipdate <= DATE_SUB('1998-12-01', INTERVAL 90 DAY)
GROUP BY
    l_returnflag,
    l_linestatus
ORDER BY
    l_returnflag,
    l_linestatus;
"""

# TPC-H Query 6 - Forecasting Revenue Change
TPCH_QUERY_6 = """
SELECT
    SUM(l_extendedprice * l_discount) AS revenue
FROM
    lineitem
WHERE
    l_shipdate >= '1994-01-01'
    AND l_shipdate < DATE_ADD('1994-01-01', INTERVAL 1 YEAR)
    AND l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01
    AND l_quantity < 24;
"""

# TPC-H Query 14 - Promotion Effect
TPCH_QUERY_14 = """
SELECT
    100.00 * SUM(CASE
        WHEN p_type LIKE 'PROMO%'
        THEN l_extendedprice * (1 - l_discount)
        ELSE 0
    END) / SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
FROM
    lineitem,
    part
WHERE
    l_partkey = p_partkey
    AND l_shipdate >= '1995-09-01'
    AND l_shipdate < DATE_ADD('1995-09-01', INTERVAL 1 MONTH);
"""


def download_tpch_dbgen(dbgen_dir: str) -> None:
    """Download and build TPC-H dbgen.

    Uses Docker with Ubuntu 22.04 to build dbgen, as the old TPC-H dbgen code
    is incompatible with newer GCC versions (14+) due to strict type checking
    on function pointer declarations.
    """
    dbgen_path = Path(dbgen_dir)
    if (dbgen_path / "dbgen").exists():
        print(f"TPC-H dbgen already exists at {dbgen_dir}")
        return

    print("Downloading and building TPC-H dbgen...")
    run(["rm", "-rf", dbgen_dir])
    run(["git", "clone", "https://github.com/electrum/tpch-dbgen.git", dbgen_dir])

    # Build using Docker with GCC 11 for compatibility
    # Newer GCC versions fail due to stricter function pointer type checking
    print("Building dbgen with Docker (GCC 11)...")
    run([
        "docker", "run", "--rm",
        "-v", f"{dbgen_dir}:/build",
        "-w", "/build",
        "gcc:11",
        "make", f"-j{os.cpu_count()}"
    ])
    print(f"TPC-H dbgen built at {dbgen_dir}")


def generate_data(dbgen_dir: str, scale_factor: float, output_dir: str) -> None:
    """Generate TPC-H data."""
    print(f"Generating TPC-H data (scale factor: {scale_factor})...")
    run(["mkdir", "-p", output_dir])

    # dbgen must run from its directory
    subprocess.run(
        ["./dbgen", "-s", str(scale_factor), "-f"],
        cwd=dbgen_dir,
        check=True,
    )

    # Move generated files to output
    for tbl in Path(dbgen_dir).glob("*.tbl"):
        run(["mv", str(tbl), output_dir])

    print(f"Data generated in {output_dir}")


def mysql_exec(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str | None,
    sql: str,
) -> subprocess.CompletedProcess:
    """Execute SQL on MySQL."""
    cmd = [
        "docker", "run", "--rm", "-i",
        "--network", "host",
        "mysql:8.0",
        "mysql",
        "-h", mysql_host,
        "-P", str(mysql_port),
        "-u", mysql_user,
        f"-p{mysql_password}",
        "-e", sql,
    ]
    if database:
        cmd.insert(-2, "-D")
        cmd.insert(-2, database)
    return run(cmd, check=False, capture=True)


def cleanup_database(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
) -> None:
    """Drop and recreate TPC-H database for idempotent reruns."""
    print(f"Cleaning up database '{database}'...")
    sql = f"DROP DATABASE IF EXISTS {database}; CREATE DATABASE {database};"
    result = mysql_exec(mysql_host, mysql_port, mysql_user, mysql_password, None, sql)
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


def prepare_data(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
    scale_factor: float,
    dbgen_dir: str,
) -> None:
    """Prepare TPC-H data for benchmarking.

    This function:
    1. Downloads and builds dbgen if needed
    2. Generates TPC-H data
    3. Creates tables and loads data into MySQL

    Note: MySQL server must already be running.
    """
    print("Preparing TPC-H data...")
    print(f"  MySQL: {mysql_host}:{mysql_port}")
    print(f"  Database: {database}")
    print(f"  Scale factor: {scale_factor}")

    # Wait for MySQL
    if not wait_for_mysql(mysql_host, mysql_port, mysql_user, mysql_password):
        print("Error: MySQL not available")
        sys.exit(1)

    # Download and build dbgen
    download_tpch_dbgen(dbgen_dir)

    # Generate data
    data_dir = f"/tmp/tpch_sf{scale_factor}"
    generate_data(dbgen_dir, scale_factor, data_dir)

    # Cleanup and create database
    cleanup_database(mysql_host, mysql_port, mysql_user, mysql_password, database)

    # Create tables
    print("\nCreating tables...")
    for table, schema in TPCH_SCHEMAS.items():
        result = mysql_exec(mysql_host, mysql_port, mysql_user, mysql_password, database, schema)
        if result.returncode != 0:
            print(f"Error creating {table}: {result.stderr}")
            sys.exit(1)
        print(f"  Created: {table}")

    # Load data
    print("\nLoading data...")
    for table in TPCH_SCHEMAS:
        tbl_file = f"{data_dir}/{table}.tbl"
        if not Path(tbl_file).exists():
            print(f"  Skipping {table} (no data file)")
            continue

        # Use LOAD DATA with MySQL container
        # Copy file to container-accessible location
        load_sql = f"""
            LOAD DATA LOCAL INFILE '/data/{table}.tbl'
            INTO TABLE {table}
            FIELDS TERMINATED BY '|'
            LINES TERMINATED BY '|\\n';
        """
        result = run([
            "docker", "run", "--rm", "-i",
            "--network", "host",
            "-v", f"{data_dir}:/data:ro",
            "mysql:8.0",
            "mysql",
            "-h", mysql_host,
            "-P", str(mysql_port),
            "-u", mysql_user,
            f"-p{mysql_password}",
            "-D", database,
            "--local-infile=1",
            "-e", load_sql,
        ], check=False, capture=True)

        if result.returncode != 0:
            print(f"  Error loading {table}: {result.stderr}")
        else:
            print(f"  Loaded: {table}")

    print("\nTPC-H data preparation complete. You can now run the benchmark.")


def run_benchmark(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
    query: int,
) -> None:
    """Run TPC-H benchmark query.

    Note: This assumes data is already prepared. Run 'prepare' first.
    """
    queries = {
        1: ("Pricing Summary Report", TPCH_QUERY_1),
        6: ("Forecasting Revenue Change", TPCH_QUERY_6),
        14: ("Promotion Effect", TPCH_QUERY_14),
    }

    if query not in queries:
        print(f"Error: Query {query} not supported. Available: {list(queries.keys())}")
        sys.exit(1)

    query_name, query_sql = queries[query]

    print(f"Running TPC-H Query {query}: {query_name}")
    print(f"  MySQL: {mysql_host}:{mysql_port}")
    print(f"  Database: {database}")

    # Wait for MySQL
    if not wait_for_mysql(mysql_host, mysql_port, mysql_user, mysql_password):
        print("Error: MySQL not available")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"TPC-H QUERY {query}: {query_name.upper()}")
    print("=" * 60)

    start_time = time.time()
    result = mysql_exec(mysql_host, mysql_port, mysql_user, mysql_password, database, query_sql)
    elapsed = time.time() - start_time

    print(result.stdout if result.stdout else "No results")
    if result.stderr and "Warning" not in result.stderr:
        print(f"Errors: {result.stderr}")

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"  Query time: {elapsed:.2f}s")


def run_all_queries(
    mysql_host: str,
    mysql_port: int,
    mysql_user: str,
    mysql_password: str,
    database: str,
) -> None:
    """Run all TPC-H benchmark queries."""
    queries = [1, 6, 14]

    print("Running all TPC-H queries...")
    print(f"  MySQL: {mysql_host}:{mysql_port}")
    print(f"  Database: {database}")

    # Wait for MySQL
    if not wait_for_mysql(mysql_host, mysql_port, mysql_user, mysql_password):
        print("Error: MySQL not available")
        sys.exit(1)

    results = []
    for q in queries:
        print(f"\n{'='*60}")
        print(f"TPC-H Query {q}")
        print("=" * 60)

        query_sql = {1: TPCH_QUERY_1, 6: TPCH_QUERY_6, 14: TPCH_QUERY_14}[q]

        start_time = time.time()
        result = mysql_exec(mysql_host, mysql_port, mysql_user, mysql_password, database, query_sql)
        elapsed = time.time() - start_time
        results.append((q, elapsed))

        print(result.stdout[:500] if result.stdout else "No results")
        print(f"Query time: {elapsed:.2f}s")

    print("\n" + "=" * 60)
    print("ALL QUERIES COMPLETE")
    print("=" * 60)
    for q, t in results:
        print(f"  Query {q}: {t:.2f}s")
    print(f"  Total: {sum(t for _, t in results):.2f}s")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TPC-H benchmarks on MySQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download and build TPC-H dbgen
  %(prog)s init

  # Prepare TPC-H data (generate, create tables, load)
  %(prog)s prepare --mysql-host 10.0.0.1 --scale 0.1

  # Run specific TPC-H query
  %(prog)s run --mysql-host 10.0.0.1 --query 1

  # Run all TPC-H queries
  %(prog)s run-all --mysql-host 10.0.0.1

  # Cleanup database
  %(prog)s cleanup --mysql-host 10.0.0.1

Available queries:
  Q1  - Pricing Summary Report
  Q6  - Forecasting Revenue Change
  Q14 - Promotion Effect
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

    # Init subcommand
    init_parser = subparsers.add_parser("init", help="Download and build TPC-H dbgen")
    init_parser.add_argument(
        "--dbgen-dir",
        default=DEFAULT_TPCH_DBGEN,
        help=f"TPC-H dbgen directory (default: {DEFAULT_TPCH_DBGEN})",
    )

    # Cleanup subcommand
    cleanup_parser = subparsers.add_parser("cleanup", help="Drop TPC-H database")
    add_mysql_args(cleanup_parser)

    # Prepare subcommand
    prepare_parser = subparsers.add_parser("prepare", help="Prepare TPC-H data")
    add_mysql_args(prepare_parser)
    prepare_parser.add_argument(
        "--scale",
        type=float,
        default=DEFAULT_SCALE_FACTOR,
        help=f"Scale factor (default: {DEFAULT_SCALE_FACTOR}, 1 = ~1GB)",
    )
    prepare_parser.add_argument(
        "--dbgen-dir",
        default=DEFAULT_TPCH_DBGEN,
        help=f"TPC-H dbgen directory (default: {DEFAULT_TPCH_DBGEN})",
    )

    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run TPC-H query")
    add_mysql_args(run_parser)
    run_parser.add_argument(
        "--query",
        type=int,
        default=1,
        choices=[1, 6, 14],
        help="TPC-H query number (default: 1)",
    )

    # Run-all subcommand
    run_all_parser = subparsers.add_parser("run-all", help="Run all TPC-H queries")
    add_mysql_args(run_all_parser)

    args = parser.parse_args()

    if args.action == "init":
        download_tpch_dbgen(args.dbgen_dir)

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
            args.database, args.scale, args.dbgen_dir,
        )

    elif args.action == "run":
        run_benchmark(
            args.mysql_host, args.mysql_port,
            args.mysql_user, args.mysql_password,
            args.database, args.query,
        )

    elif args.action == "run-all":
        run_all_queries(
            args.mysql_host, args.mysql_port,
            args.mysql_user, args.mysql_password,
            args.database,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
