#!/usr/bin/env python3
"""Run TPC-DS benchmarks on Spark cluster."""

import argparse
import os
import sys
import tempfile
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

DEFAULT_MASTER = "spark://localhost:7077"

# Path to framework wrapper
FW_DIR = Path(__file__).parent.parent / "fw"
SPARK_PY = FW_DIR / "spark.py"


def generate_pyspark_script(
    master: str,
    hdfs_base: str,
    scale_factor: int,
    output_path: str | None,
    shuffle_partitions: int,
) -> str:
    """Generate PySpark script for TPC-DS Query 99."""
    tables_code = []
    for table in TABLE_SCHEMAS:
        schema_str = get_schema_string(table)
        tables_code.append(f'''
    # Load {table}
    spark.read.option("delimiter", "|").csv(
        f"{{base_path}}/{table}",
        schema="{schema_str}"
    ).createOrReplaceTempView("{table}")
    print(f"Loaded: {table}")
''')

    output_code = ""
    if output_path:
        output_code = f'''
    # Save results
    result_df.write.mode("overwrite").csv("{output_path}")
    print(f"Results saved to: {output_path}")
'''

    return f'''#!/usr/bin/env python3
"""TPC-DS Query 99 benchmark for Spark."""

from pyspark.sql import SparkSession
import time

def main():
    # Configuration
    master = "{master}"
    base_path = "{hdfs_base}/raw/sf{scale_factor}"

    print("=" * 60)
    print("TPC-DS Query 99 Benchmark (Spark)")
    print("=" * 60)
    print(f"Master: {{master}}")
    print(f"Data path: {{base_path}}")
    print(f"Scale factor: {scale_factor}")
    print("=" * 60)

    # Create Spark session
    spark = SparkSession.builder \\
        .appName("TPC-DS Query 99") \\
        .master(master) \\
        .config("spark.sql.shuffle.partitions", "{shuffle_partitions}") \\
        .config("spark.sql.adaptive.enabled", "true") \\
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true") \\
        .getOrCreate()

    print("\\nLoading tables...")
    load_start = time.time()

{"".join(tables_code)}

    load_time = time.time() - load_start
    print(f"\\nTables loaded in {{load_time:.2f}} seconds")

    # TPC-DS Query 99
    query = """
{TPCDS_QUERY_99}
    """

    print("\\nExecuting TPC-DS Query 99...")
    print("Query: Analyze late shipments by shipping mode and warehouse")

    query_start = time.time()
    result_df = spark.sql(query)

    # Force execution and collect results
    results = result_df.collect()
    query_time = time.time() - query_start

    print(f"\\nQuery completed in {{query_time:.2f}} seconds")
    print(f"Rows returned: {{len(results)}}")

    # Display results
    print("\\nResults:")
    print("-" * 100)
    result_df.show(100, truncate=False)
{output_code}
    # Summary
    print("\\n" + "=" * 60)
    print("Benchmark Summary")
    print("=" * 60)
    print(f"Load time:  {{load_time:.2f}} seconds")
    print(f"Query time: {{query_time:.2f}} seconds")
    print(f"Total time: {{load_time + query_time:.2f}} seconds")
    print("=" * 60)

    spark.stop()

if __name__ == "__main__":
    main()
'''


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
    master: str,
    hdfs_base: str,
    scale_factor: int,
    output_path: str | None,
    shuffle_partitions: int,
    executor_memory: str,
    executor_cores: int,
) -> None:
    """Run the TPC-DS Q99 benchmark using spark.py submit.

    Note: This assumes data is already prepared in HDFS. Run 'prepare' first.
    """
    print("Running TPC-DS Query 99 benchmark...")
    print(f"  Master: {master}")
    print(f"  Scale factor: {scale_factor}")
    print(f"  HDFS base: {hdfs_base}")

    # Generate script
    script_content = generate_pyspark_script(
        master, hdfs_base, scale_factor, output_path, shuffle_partitions
    )

    # Write script to temp file with world-readable permissions
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False
    ) as f:
        f.write(script_content)
        script_path = f.name
    os.chmod(script_path, 0o644)

    try:
        # Run via framework wrapper
        run([
            sys.executable, str(SPARK_PY), "submit",
            "--master", master,
            "--script", script_path,
            "--executor-memory", executor_memory,
            "--executor-cores", str(executor_cores),
        ])
    finally:
        os.unlink(script_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TPC-DS benchmarks on Spark cluster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate TPC-DS data (scale factor 1 = ~1GB)
  %(prog)s generate --scale 1

  # Prepare TPC-DS data in HDFS (generate if needed, upload to HDFS)
  %(prog)s prepare --hdfs-base hdfs://10.0.0.1:9000/bench/tpcds

  # Run TPC-DS Query 99 benchmark (data must be prepared first)
  %(prog)s run --master spark://10.0.0.1:7077 --hdfs-base hdfs://10.0.0.1:9000/bench/tpcds

  # Run with custom scale factor and save results
  %(prog)s run --master spark://10.0.0.1:7077 --scale 10 --output hdfs:///results/q99

  # Run with more executor resources
  %(prog)s run --master spark://10.0.0.1:7077 --executor-memory 4g --executor-cores 4
""",
    )

    subparsers = parser.add_subparsers(dest="action", required=True)

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
        "--master",
        default=DEFAULT_MASTER,
        help=f"Spark master URL (default: {DEFAULT_MASTER})",
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
        "--output",
        help="HDFS path to save results (optional)",
    )
    run_parser.add_argument(
        "--shuffle-partitions",
        type=int,
        default=64,
        help="Number of shuffle partitions (default: 64)",
    )
    run_parser.add_argument(
        "--executor-memory",
        default="1g",
        help="Executor memory (default: 1g)",
    )
    run_parser.add_argument(
        "--executor-cores",
        type=int,
        default=1,
        help="Executor cores (default: 1)",
    )

    args = parser.parse_args()

    if args.action == "generate":
        output_dir = args.output_dir.replace("sf1", f"sf{args.scale}")
        generate_data(args.scale, output_dir, args.tpcds_kit)
    elif args.action == "prepare":
        prepare_data(args.hdfs_base, args.scale, args.namenode_data_dir)
    elif args.action == "run":
        run_benchmark(
            args.master,
            args.hdfs_base,
            args.scale,
            args.output,
            args.shuffle_partitions,
            args.executor_memory,
            args.executor_cores,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
