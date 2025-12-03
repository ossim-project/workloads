#!/usr/bin/env python3
"""
Flink SQL Benchmark using built-in connectors.

This benchmark tests Flink's batch processing capabilities with various workloads:
- identity: Pass-through (baseline throughput)
- wordcount: Stateful word counting (GROUP BY)
- window: Range-based aggregation (GROUP BY with SUM)

Uses built-in Flink connectors (no external dependencies):
- Source: DataGen (generates synthetic data)
- Sink: BlackHole (discards output for throughput testing)

Prerequisites:
- Flink cluster running (JobManager + TaskManagers)
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request


# Workload descriptions
WORKLOADS = {
    "identity": "Pass-through (baseline throughput)",
    "wordcount": "Stateful word counting (GROUP BY)",
    "window": "Range-based aggregation (GROUP BY with SUM)",
}


def run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.run(cmd, check=check)


def get_host_ip() -> str:
    """Get the host's IP address."""
    result = subprocess.run(
        ["hostname", "-I"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip().split()[0]


def run_identity_benchmark(
    flink_host: str,
    flink_port: int,
    num_records: int,
    parallelism: int = 4,
) -> dict:
    """Run identity (pass-through) benchmark using Flink SQL.

    Uses DataGen source and BlackHole sink.
    """

    print("\n=== Identity Benchmark ===")
    print("Testing pass-through throughput (source -> sink)")
    print(f"  Records: {num_records:,}")
    print(f"  Parallelism: {parallelism}")

    sql = f"""
SET 'execution.runtime-mode' = 'batch';
SET 'parallelism.default' = '{parallelism}';
SET 'rest.address' = '{flink_host}';
SET 'rest.port' = '{flink_port}';

CREATE TABLE source_table (
    id BIGINT,
    data STRING
) WITH (
    'connector' = 'datagen',
    'number-of-rows' = '{num_records}',
    'fields.id.kind' = 'sequence',
    'fields.id.start' = '1',
    'fields.id.end' = '{num_records}',
    'fields.data.length' = '100'
);

CREATE TABLE sink_table (
    id BIGINT,
    data STRING
) WITH (
    'connector' = 'blackhole'
);

INSERT INTO sink_table SELECT * FROM source_table;
"""

    return _run_sql_job(sql, "identity", flink_host, flink_port)


def run_wordcount_benchmark(
    flink_host: str,
    flink_port: int,
    num_records: int,
    parallelism: int = 4,
) -> dict:
    """Run word count benchmark using Flink SQL.

    Uses DataGen source and BlackHole sink.
    """

    print("\n=== WordCount Benchmark ===")
    print("Testing stateful aggregation (word counting)")
    print(f"  Records: {num_records:,}")
    print(f"  Parallelism: {parallelism}")

    sql = f"""
SET 'execution.runtime-mode' = 'batch';
SET 'parallelism.default' = '{parallelism}';
SET 'rest.address' = '{flink_host}';
SET 'rest.port' = '{flink_port}';

CREATE TABLE source_table (
    id BIGINT,
    word_id INT
) WITH (
    'connector' = 'datagen',
    'number-of-rows' = '{num_records}',
    'fields.id.kind' = 'sequence',
    'fields.id.start' = '1',
    'fields.id.end' = '{num_records}',
    'fields.word_id.kind' = 'random',
    'fields.word_id.min' = '0',
    'fields.word_id.max' = '999'
);

CREATE TABLE sink_table (
    word_id INT,
    cnt BIGINT
) WITH (
    'connector' = 'blackhole'
);

INSERT INTO sink_table
SELECT word_id, COUNT(*) as cnt
FROM source_table
GROUP BY word_id;
"""

    return _run_sql_job(sql, "wordcount", flink_host, flink_port)


def run_window_benchmark(
    flink_host: str,
    flink_port: int,
    num_records: int,
    parallelism: int = 4,
    window_size_sec: int = 5,
) -> dict:
    """Run tumbling window benchmark using Flink SQL.

    Uses DataGen source and BlackHole sink.
    """

    print("\n=== Window Benchmark ===")
    print("Testing range-based aggregation (GROUP BY with SUM)")
    print(f"  Records: {num_records:,}")
    print(f"  Parallelism: {parallelism}")

    # Window aggregation with grouping by id ranges (batch mode equivalent)
    sql = f"""
SET 'execution.runtime-mode' = 'batch';
SET 'parallelism.default' = '{parallelism}';
SET 'rest.address' = '{flink_host}';
SET 'rest.port' = '{flink_port}';

CREATE TABLE source_table (
    id BIGINT,
    word_id INT,
    amount DOUBLE
) WITH (
    'connector' = 'datagen',
    'number-of-rows' = '{num_records}',
    'fields.id.kind' = 'sequence',
    'fields.id.start' = '1',
    'fields.id.end' = '{num_records}',
    'fields.word_id.kind' = 'random',
    'fields.word_id.min' = '0',
    'fields.word_id.max' = '99',
    'fields.amount.kind' = 'random',
    'fields.amount.min' = '0',
    'fields.amount.max' = '1000'
);

CREATE TABLE sink_table (
    window_id BIGINT,
    word_id INT,
    total_amount DOUBLE,
    cnt BIGINT
) WITH (
    'connector' = 'blackhole'
);

INSERT INTO sink_table
SELECT
    FLOOR(id / 10000) as window_id,
    word_id,
    SUM(amount) as total_amount,
    COUNT(*) as cnt
FROM source_table
GROUP BY
    FLOOR(id / 10000),
    word_id;
"""

    return _run_sql_job(sql, "window", flink_host, flink_port)


def _run_sql_job(
    sql: str,
    job_name: str,
    flink_host: str,
    flink_port: int,
) -> dict:
    """Execute Flink SQL job and collect metrics."""

    # Write SQL to temp file
    sql_file = f"/tmp/flink_{job_name}.sql"
    with open(sql_file, "w") as f:
        f.write(sql)

    # Copy to container
    run(["docker", "cp", sql_file, "flink-jobmanager:/tmp/job.sql"])

    # Get existing job IDs to filter out later
    existing_job_ids = set()
    try:
        url = f"http://{flink_host}:{flink_port}/jobs"
        with urllib.request.urlopen(url, timeout=5) as resp:
            jobs_data = json.loads(resp.read().decode())
            for job in jobs_data.get("jobs", []):
                existing_job_ids.add(job["id"])
    except Exception:
        pass

    # Submit job via SQL client
    print(f"Submitting {job_name} job...")
    start_time = time.time()

    result = run([
        "docker", "exec", "flink-jobmanager",
        "/opt/flink/bin/sql-client.sh", "embedded",
        "-f", "/tmp/job.sql",
    ], check=False, capture=True)

    # Wait for new job to appear
    print("Waiting for job to complete...")
    max_wait = 120  # 2 minutes max
    poll_interval = 2

    job_id = None
    final_status = "UNKNOWN"
    final_metrics = {}

    for _ in range(max_wait // poll_interval):
        time.sleep(poll_interval)

        # Find the new job (not in existing_job_ids)
        try:
            url = f"http://{flink_host}:{flink_port}/jobs"
            with urllib.request.urlopen(url, timeout=5) as resp:
                jobs_data = json.loads(resp.read().decode())

            new_job = None
            for job in jobs_data.get("jobs", []):
                if job["id"] not in existing_job_ids:
                    new_job = job
                    break

            if new_job:
                job_id = new_job["id"]
                status = new_job["status"]

                # Get detailed metrics for this specific job
                metrics = _get_job_metrics(flink_host, flink_port, target_job_id=job_id)

                if metrics.get("jobs"):
                    job_metrics = metrics["jobs"][0]
                    records = job_metrics.get("records_in", 0)
                    print(f"  Job: {job_id[:8]}... Status: {status}, Records: {records:,}", end="\r")

                if status in ["FINISHED", "FAILED", "CANCELED"]:
                    final_status = status
                    final_metrics = metrics
                    print()  # newline
                    break
            else:
                # No new job found yet, SQL client might still be running
                print(f"  Waiting for job to start...", end="\r")

        except Exception as e:
            print(f"  Error polling: {e}", end="\r")

    elapsed = time.time() - start_time

    # If we never found a new job, check if SQL client succeeded
    if final_status == "UNKNOWN" and result.returncode == 0:
        final_status = "FINISHED"
        print(f"  Job completed (SQL client returned success)")

    return {
        "job_name": job_name,
        "job_id": job_id,
        "status": final_status,
        "elapsed_sec": elapsed,
        "metrics": final_metrics,
    }


def _get_job_metrics(flink_host: str, flink_port: int, target_job_id: str = None) -> dict:
    """Get metrics for jobs.

    Args:
        flink_host: Flink REST API host
        flink_port: Flink REST API port
        target_job_id: If specified, only return metrics for this job.
                       Otherwise, return the most recent non-CANCELED job.
    """

    try:
        url = f"http://{flink_host}:{flink_port}/jobs"
        with urllib.request.urlopen(url, timeout=5) as resp:
            jobs_data = json.loads(resp.read().decode())

        metrics = {"jobs": []}

        # Filter to target job or find best candidate
        jobs_to_check = []
        for job in jobs_data.get("jobs", []):
            job_id = job["id"]
            status = job["status"]

            if target_job_id:
                # Only check the target job
                if job_id == target_job_id:
                    jobs_to_check.append(job)
                    break
            else:
                # Skip CANCELED jobs when looking for active job
                if status != "CANCELED":
                    jobs_to_check.append(job)

        for job in jobs_to_check:
            job_id = job["id"]
            status = job["status"]

            url = f"http://{flink_host}:{flink_port}/jobs/{job_id}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                job_details = json.loads(resp.read().decode())

            job_metrics = {
                "id": job_id,
                "name": job_details.get("name", "unknown"),
                "status": status,
                "duration_ms": job_details.get("duration", 0),
                "records_in": 0,
                "records_out": 0,
                "bytes_in": 0,
                "bytes_out": 0,
            }

            for vertex in job_details.get("vertices", []):
                vm = vertex.get("metrics", {})
                job_metrics["records_in"] += vm.get("read-records", 0)
                job_metrics["records_out"] += vm.get("write-records", 0)
                job_metrics["bytes_in"] += vm.get("read-bytes", 0)
                job_metrics["bytes_out"] += vm.get("write-bytes", 0)

            metrics["jobs"].append(job_metrics)

        return metrics

    except Exception as e:
        return {}


def cancel_all_jobs(flink_host: str, flink_port: int = 8081) -> None:
    """Cancel all running Flink jobs."""

    try:
        url = f"http://{flink_host}:{flink_port}/jobs"
        with urllib.request.urlopen(url, timeout=5) as resp:
            jobs_data = json.loads(resp.read().decode())

        for job in jobs_data.get("jobs", []):
            if job["status"] == "RUNNING":
                job_id = job["id"]
                print(f"Cancelling job {job_id}...")
                cancel_url = f"http://{flink_host}:{flink_port}/jobs/{job_id}/cancel"
                req = urllib.request.Request(cancel_url, method="PATCH")
                with urllib.request.urlopen(req, timeout=5):
                    pass
    except Exception as e:
        print(f"Warning: Could not cancel jobs: {e}")


def run_benchmark(
    workload: str,
    flink_host: str,
    flink_port: int = 8081,
    num_records: int = 1000000,
    parallelism: int = 4,
) -> dict:
    """Run a complete benchmark for a workload."""

    print(f"\n{'='*60}")
    print(f"Running {workload} benchmark")
    print(f"{'='*60}")

    # Auto-cleanup for idempotent reruns
    print("Cleaning up previous jobs...")
    cancel_all_jobs(flink_host, flink_port)
    time.sleep(2)

    # Run workload
    if workload == "identity":
        result = run_identity_benchmark(
            flink_host, flink_port, num_records, parallelism
        )
    elif workload == "wordcount":
        result = run_wordcount_benchmark(
            flink_host, flink_port, num_records, parallelism
        )
    elif workload == "window":
        result = run_window_benchmark(
            flink_host, flink_port, num_records, parallelism
        )
    else:
        print(f"Unknown workload: {workload}")
        return {}

    # Print summary
    print(f"\n{'='*60}")
    print(f"BENCHMARK RESULTS: {workload.upper()}")
    print(f"{'='*60}")

    status = result.get("status", "UNKNOWN")
    elapsed = result.get("elapsed_sec", 0)

    print(f"\nJob Status: {status}")
    print(f"Total Time: {elapsed:.2f}s")

    metrics = result.get("metrics", {})
    if metrics.get("jobs"):
        job = metrics["jobs"][0]
        records_in = job.get("records_in", 0)
        records_out = job.get("records_out", 0)
        bytes_in = job.get("bytes_in", 0)
        duration_ms = job.get("duration_ms", 0)
        duration_sec = duration_ms / 1000 if duration_ms > 0 else elapsed

        # For batch jobs with DataGen, metrics may show 0 or output count
        # For aggregations, output is reduced. Use configured record count.
        if status == "FINISHED":
            records_in = num_records

        throughput = records_in / duration_sec if duration_sec > 0 else 0

        print(f"\nPerformance Metrics:")
        print(f"  Records Processed: {records_in:,}")
        print(f"  Processing Time:   {duration_sec:.2f}s")
        print(f"  Throughput:        {throughput:,.0f} records/sec")

        if status == "FINISHED":
            print(f"\n  SUCCESS: Processed {records_in:,} records in {duration_sec:.2f}s")

    print(f"\n{'='*60}")

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flink SQL Benchmark (using DataGen/BlackHole)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Run identity benchmark with 1M records
  %(prog)s run --workload identity --records 1000000

  # Run wordcount benchmark with 500K records
  %(prog)s run --workload wordcount --records 500000

  # Run all workloads
  %(prog)s run --workload all

  # Cancel all running jobs
  %(prog)s cancel

Workloads:
{chr(10).join(f'  {k:12} - {v}' for k, v in WORKLOADS.items())}

Note: Uses built-in DataGen source and BlackHole sink.
      No external dependencies (Kafka, etc.) required.
""",
    )

    parser.add_argument(
        "action",
        choices=["run", "cancel", "cleanup"],
        help="Action to perform (cleanup is alias for cancel)",
    )
    parser.add_argument(
        "--workload",
        choices=["identity", "wordcount", "window", "all"],
        default="identity",
        help="Workload to run (default: identity)",
    )
    parser.add_argument(
        "--flink-host",
        default=None,
        help="Flink JobManager host (default: auto-detect)",
    )
    parser.add_argument(
        "--flink-port",
        type=int,
        default=8081,
        help="Flink REST API port (default: 8081)",
    )
    parser.add_argument(
        "--records",
        type=int,
        default=100000,
        help="Number of records to process (default: 100000)",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=1,
        help="Job parallelism (default: 1)",
    )

    args = parser.parse_args()

    # Auto-detect host IP
    host_ip = get_host_ip()
    flink_host = args.flink_host or host_ip

    if args.action in ("cancel", "cleanup"):
        print("Cleaning up Flink jobs for idempotent reruns...")
        cancel_all_jobs(flink_host, args.flink_port)
        print("Cleanup complete")
        return 0

    elif args.action == "run":
        workloads = ["identity", "wordcount", "window"] if args.workload == "all" else [args.workload]

        results = []
        for workload in workloads:
            result = run_benchmark(
                workload=workload,
                flink_host=flink_host,
                flink_port=args.flink_port,
                num_records=args.records,
                parallelism=args.parallelism,
            )
            results.append(result)

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
