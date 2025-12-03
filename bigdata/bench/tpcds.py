#!/usr/bin/env python3
"""Common TPC-DS benchmark utilities shared across engines."""

import os
import subprocess
from pathlib import Path

DEFAULT_SCALE_FACTOR = 1
DEFAULT_HDFS_BASE = "hdfs:///bench/tpcds"
DEFAULT_TPCDS_KIT = "/tmp/tpcds-kit"

# TPC-DS Query 99 - Analyze late shipments from catalog sales by shipping mode and warehouse
# This query measures shipping performance across different modes and warehouses
TPCDS_QUERY_99 = """
SELECT
    SUBSTR(w_warehouse_name, 1, 20) AS warehouse_name,
    sm_type AS ship_mode,
    cc_name AS call_center,
    SUM(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk <= 30) THEN 1 ELSE 0 END) AS days_30,
    SUM(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 30)
             AND (cs_ship_date_sk - cs_sold_date_sk <= 60) THEN 1 ELSE 0 END) AS days_31_60,
    SUM(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 60)
             AND (cs_ship_date_sk - cs_sold_date_sk <= 90) THEN 1 ELSE 0 END) AS days_61_90,
    SUM(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 90)
             AND (cs_ship_date_sk - cs_sold_date_sk <= 120) THEN 1 ELSE 0 END) AS days_91_120,
    SUM(CASE WHEN (cs_ship_date_sk - cs_sold_date_sk > 120) THEN 1 ELSE 0 END) AS days_over_120
FROM
    catalog_sales cs
JOIN warehouse w ON cs.cs_warehouse_sk = w.w_warehouse_sk
JOIN ship_mode sm ON cs.cs_ship_mode_sk = sm.sm_ship_mode_sk
JOIN call_center cc ON cs.cs_call_center_sk = cc.cc_call_center_sk
JOIN date_dim d ON cs.cs_ship_date_sk = d.d_date_sk
WHERE
    d.d_month_seq BETWEEN 1200 AND 1200 + 11
GROUP BY
    SUBSTR(w_warehouse_name, 1, 20),
    sm_type,
    cc_name
ORDER BY
    warehouse_name,
    ship_mode,
    call_center
LIMIT 100
"""

# Table schemas for TPC-DS tables used in Query 99
# Format: list of (column_name, TYPE) tuples
TABLE_SCHEMAS = {
    "catalog_sales": [
        ("cs_sold_date_sk", "INT"),
        ("cs_sold_time_sk", "INT"),
        ("cs_ship_date_sk", "INT"),
        ("cs_bill_customer_sk", "INT"),
        ("cs_bill_cdemo_sk", "INT"),
        ("cs_bill_hdemo_sk", "INT"),
        ("cs_bill_addr_sk", "INT"),
        ("cs_ship_customer_sk", "INT"),
        ("cs_ship_cdemo_sk", "INT"),
        ("cs_ship_hdemo_sk", "INT"),
        ("cs_ship_addr_sk", "INT"),
        ("cs_call_center_sk", "INT"),
        ("cs_catalog_page_sk", "INT"),
        ("cs_ship_mode_sk", "INT"),
        ("cs_warehouse_sk", "INT"),
        ("cs_item_sk", "INT"),
        ("cs_promo_sk", "INT"),
        ("cs_order_number", "INT"),
        ("cs_quantity", "INT"),
        ("cs_wholesale_cost", "DECIMAL(7,2)"),
        ("cs_list_price", "DECIMAL(7,2)"),
        ("cs_sales_price", "DECIMAL(7,2)"),
        ("cs_ext_discount_amt", "DECIMAL(7,2)"),
        ("cs_ext_sales_price", "DECIMAL(7,2)"),
        ("cs_ext_wholesale_cost", "DECIMAL(7,2)"),
        ("cs_ext_list_price", "DECIMAL(7,2)"),
        ("cs_ext_tax", "DECIMAL(7,2)"),
        ("cs_coupon_amt", "DECIMAL(7,2)"),
        ("cs_ext_ship_cost", "DECIMAL(7,2)"),
        ("cs_net_paid", "DECIMAL(7,2)"),
        ("cs_net_paid_inc_tax", "DECIMAL(7,2)"),
        ("cs_net_paid_inc_ship", "DECIMAL(7,2)"),
        ("cs_net_paid_inc_ship_tax", "DECIMAL(7,2)"),
        ("cs_net_profit", "DECIMAL(7,2)"),
    ],
    "warehouse": [
        ("w_warehouse_sk", "INT"),
        ("w_warehouse_id", "STRING"),
        ("w_warehouse_name", "STRING"),
        ("w_warehouse_sq_ft", "INT"),
        ("w_street_number", "STRING"),
        ("w_street_name", "STRING"),
        ("w_street_type", "STRING"),
        ("w_suite_number", "STRING"),
        ("w_city", "STRING"),
        ("w_county", "STRING"),
        ("w_state", "STRING"),
        ("w_zip", "STRING"),
        ("w_country", "STRING"),
        ("w_gmt_offset", "DECIMAL(5,2)"),
    ],
    "ship_mode": [
        ("sm_ship_mode_sk", "INT"),
        ("sm_ship_mode_id", "STRING"),
        ("sm_type", "STRING"),
        ("sm_code", "STRING"),
        ("sm_carrier", "STRING"),
        ("sm_contract", "STRING"),
    ],
    "call_center": [
        ("cc_call_center_sk", "INT"),
        ("cc_call_center_id", "STRING"),
        ("cc_rec_start_date", "DATE"),
        ("cc_rec_end_date", "DATE"),
        ("cc_closed_date_sk", "INT"),
        ("cc_open_date_sk", "INT"),
        ("cc_name", "STRING"),
        ("cc_class", "STRING"),
        ("cc_employees", "INT"),
        ("cc_sq_ft", "INT"),
        ("cc_hours", "STRING"),
        ("cc_manager", "STRING"),
        ("cc_mkt_id", "INT"),
        ("cc_mkt_class", "STRING"),
        ("cc_mkt_desc", "STRING"),
        ("cc_market_manager", "STRING"),
        ("cc_division", "INT"),
        ("cc_division_name", "STRING"),
        ("cc_company", "INT"),
        ("cc_company_name", "STRING"),
        ("cc_street_number", "STRING"),
        ("cc_street_name", "STRING"),
        ("cc_street_type", "STRING"),
        ("cc_suite_number", "STRING"),
        ("cc_city", "STRING"),
        ("cc_county", "STRING"),
        ("cc_state", "STRING"),
        ("cc_zip", "STRING"),
        ("cc_country", "STRING"),
        ("cc_gmt_offset", "DECIMAL(5,2)"),
        ("cc_tax_percentage", "DECIMAL(5,2)"),
    ],
    "date_dim": [
        ("d_date_sk", "INT"),
        ("d_date_id", "STRING"),
        ("d_date", "DATE"),
        ("d_month_seq", "INT"),
        ("d_week_seq", "INT"),
        ("d_quarter_seq", "INT"),
        ("d_year", "INT"),
        ("d_dow", "INT"),
        ("d_moy", "INT"),
        ("d_dom", "INT"),
        ("d_qoy", "INT"),
        ("d_fy_year", "INT"),
        ("d_fy_quarter_seq", "INT"),
        ("d_fy_week_seq", "INT"),
        ("d_day_name", "STRING"),
        ("d_quarter_name", "STRING"),
        ("d_holiday", "STRING"),
        ("d_weekend", "STRING"),
        ("d_following_holiday", "STRING"),
        ("d_first_dom", "INT"),
        ("d_last_dom", "INT"),
        ("d_same_day_ly", "INT"),
        ("d_same_day_lq", "INT"),
        ("d_current_day", "STRING"),
        ("d_current_week", "STRING"),
        ("d_current_month", "STRING"),
        ("d_current_quarter", "STRING"),
        ("d_current_year", "STRING"),
    ],
}


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def get_schema_string(table: str, separator: str = ", ") -> str:
    """Get schema as a string for a table.

    Args:
        table: Table name
        separator: Separator between columns (default: ", ")

    Returns:
        Schema string like "col1 TYPE, col2 TYPE, ..."
    """
    schema = TABLE_SCHEMAS[table]
    return separator.join(f"{col} {dtype}" for col, dtype in schema)


def get_column_list(table: str) -> list[str]:
    """Get list of column names for a table."""
    return [col for col, _ in TABLE_SCHEMAS[table]]


def generate_data(
    scale_factor: int,
    output_dir: str,
    tpcds_kit_dir: str = DEFAULT_TPCDS_KIT,
) -> None:
    """Generate TPC-DS data using dsdgen.

    Args:
        scale_factor: TPC-DS scale factor (1 = ~1GB)
        output_dir: Directory to write generated .dat files
        tpcds_kit_dir: Path to tpcds-kit repository
    """
    print(f"Generating TPC-DS data (scale factor: {scale_factor})...")

    # Clone tpcds-kit if not exists
    if not Path(tpcds_kit_dir).exists():
        run(["git", "clone", "https://github.com/databricks/tpcds-kit.git", tpcds_kit_dir])

    # Build dsdgen
    # Note: Extra flags needed for modern GCC (14+) which treats implicit-int as error
    tools_dir = Path(tpcds_kit_dir) / "tools"
    run([
        "make", "-C", str(tools_dir), "OS=LINUX",
        "LINUX_CFLAGS=-O3 -Wno-error=implicit-int -Wno-error=implicit-function-declaration",
        f"-j{os.cpu_count()}"
    ])

    # Generate data (dsdgen must run from tools directory to find tpcds.idx)
    run(["rm", "-rf", output_dir])
    run(["mkdir", "-p", output_dir])
    # Convert output_dir to absolute path since we change directory
    abs_output_dir = str(Path(output_dir).resolve())
    print(f"+ cd {tools_dir}")
    subprocess.run(
        ["./dsdgen", "-SCALE", str(scale_factor), "-DIR", abs_output_dir, "-FORCE"],
        cwd=tools_dir,
        check=True,
    )

    print(f"Data generated in {output_dir}")


def cleanup_hdfs_data(hdfs_base: str, scale_factor: int) -> None:
    """Clean up TPC-DS data from HDFS for idempotent reruns.

    This removes any stale data that might be corrupted or from a previous HDFS instance.

    Args:
        hdfs_base: HDFS base path (e.g., hdfs://host:9000/bench/tpcds)
        scale_factor: TPC-DS scale factor
    """
    hdfs_path = f"/bench/tpcds/raw/sf{scale_factor}"

    print(f"Cleaning up existing HDFS data at {hdfs_path}...")
    run([
        "docker", "exec", "hdfs-namenode",
        "hdfs", "dfs", "-rm", "-r", "-f", hdfs_path
    ], check=False)


def check_hdfs_data_exists(hdfs_base: str, scale_factor: int) -> bool:
    """Check if TPC-DS data exists in HDFS and is readable.

    Args:
        hdfs_base: HDFS base path (e.g., hdfs://host:9000/bench/tpcds)
        scale_factor: TPC-DS scale factor

    Returns:
        True if all required tables exist in HDFS and are readable
    """
    hdfs_path = f"/bench/tpcds/raw/sf{scale_factor}"

    # Check if first table exists and is readable by trying to list it
    result = subprocess.run(
        ["docker", "exec", "hdfs-namenode",
         "hdfs", "dfs", "-ls", f"{hdfs_path}/catalog_sales"],
        capture_output=True,
    )
    return result.returncode == 0


def upload_data_to_hdfs(
    local_dir: str,
    hdfs_base: str,
    scale_factor: int,
    namenode_data_dir: str = "/tmp/hdfs-data-nn",
) -> None:
    """Upload TPC-DS data to HDFS.

    Args:
        local_dir: Local directory containing .dat files
        hdfs_base: HDFS base path (e.g., hdfs://host:9000/bench/tpcds)
        scale_factor: TPC-DS scale factor
        namenode_data_dir: Local directory mounted to namenode container
    """
    print(f"Uploading TPC-DS data to HDFS...")
    print(f"  Local dir: {local_dir}")
    print(f"  HDFS base: {hdfs_base}")

    hdfs_path = f"/bench/tpcds/raw/sf{scale_factor}"

    # Copy required table files to namenode's mounted directory
    print("Copying data files to namenode mount...")
    for table in TABLE_SCHEMAS:
        src = f"{local_dir}/{table}.dat"
        if Path(src).exists():
            run(["cp", src, namenode_data_dir])

    # Create HDFS directories and upload data via namenode container
    print("Creating HDFS directories...")
    for table in TABLE_SCHEMAS:
        run([
            "docker", "exec", "hdfs-namenode",
            "hdfs", "dfs", "-mkdir", "-p", f"{hdfs_path}/{table}"
        ], check=False)

    print("Uploading data to HDFS...")
    for table in TABLE_SCHEMAS:
        local_file = f"/opt/hadoop/data/{table}.dat"
        hdfs_dir = f"{hdfs_path}/{table}/"

        # Check if file exists in container
        result = subprocess.run(
            ["docker", "exec", "hdfs-namenode", "test", "-f", local_file],
            capture_output=True,
        )
        if result.returncode == 0:
            # Remove existing data first for idempotent uploads
            run([
                "docker", "exec", "hdfs-namenode",
                "hdfs", "dfs", "-rm", "-f", f"{hdfs_dir}{table}.dat"
            ], check=False)
            # Upload
            run([
                "docker", "exec", "hdfs-namenode",
                "hdfs", "dfs", "-put", local_file, hdfs_dir
            ])
            print(f"  Uploaded: {table}")

    print("Data upload complete")


def ensure_data_ready(
    hdfs_base: str,
    scale_factor: int,
    local_dir: str | None = None,
    tpcds_kit_dir: str = DEFAULT_TPCDS_KIT,
    namenode_data_dir: str = "/tmp/hdfs-data-nn",
    force_refresh: bool = False,
) -> None:
    """Ensure TPC-DS data is generated and uploaded to HDFS.

    This function is idempotent - it cleans up stale data and ensures fresh upload.

    Args:
        hdfs_base: HDFS base path (e.g., hdfs://host:9000/bench/tpcds)
        scale_factor: TPC-DS scale factor
        local_dir: Local directory for generated data (default: /tmp/tpcds_sf{scale})
        tpcds_kit_dir: Path to tpcds-kit repository
        namenode_data_dir: Local directory mounted to namenode container
        force_refresh: If True, always re-upload data even if it exists
    """
    if local_dir is None:
        local_dir = f"/tmp/tpcds_sf{scale_factor}"

    # Always clean up existing HDFS data first to handle stale/corrupted data
    # This ensures idempotent behavior even after HDFS cluster restarts
    cleanup_hdfs_data(hdfs_base, scale_factor)

    # Check if local data exists, generate if not
    local_data_exists = all(
        Path(f"{local_dir}/{table}.dat").exists()
        for table in TABLE_SCHEMAS
    )

    if not local_data_exists:
        print("Local TPC-DS data not found, generating...")
        generate_data(scale_factor, local_dir, tpcds_kit_dir)
    else:
        print(f"Using existing local data from {local_dir}")

    # Upload to HDFS
    upload_data_to_hdfs(local_dir, hdfs_base, scale_factor, namenode_data_dir)
