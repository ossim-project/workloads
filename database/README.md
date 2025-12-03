# Database Workloads

Tools for running database benchmarks on MySQL using Docker.

## File Structure

```
README.md              # This file
fw/                    # Framework wrappers
├── install_deps.sh    # Install Python 3 and Docker
└── mysql.py           # MySQL server management
bench/                 # Benchmark scripts
├── tpcc_mysql.py      # TPC-C benchmark (OLTP) using sysbench
└── tpch_mysql.py      # TPC-H benchmark (OLAP) using dbgen
```

## Supported Benchmarks

| Benchmark | Type | Description |
|-----------|------|-------------|
| TPC-C (sysbench) | OLTP | Transactional workload (read/write mixed) |
| TPC-H (Q1, Q6, Q14) | OLAP | Analytical queries on decision support data |

---

# Part 1: Common Setup

## Prerequisites

- Docker installed on all machines
- Network connectivity between machines

## Configuration

Replace `<MASTER_IP>` in all commands with your server's IP address:

```bash
# Example: Set your master IP
export MASTER_IP=10.0.0.4
```

## 1.1 Initialize

```bash
# Install dependencies (Python 3 and Docker)
bash fw/install_deps.sh

# Pull MySQL image
python3 fw/mysql.py init
```

## 1.2 Start MySQL Server

```bash
python3 fw/mysql.py start --host <MASTER_IP>
```

**Wait for MySQL to be ready** (~20 seconds for first startup):

```bash
# Check if MySQL is accepting connections
docker logs mysql 2>&1 | tail -3
# Should show: "ready for connections"
```

**Verify MySQL is working:**

```bash
python3 fw/mysql.py cmd --host <MASTER_IP> -- -e "SHOW DATABASES;"
```

## 1.3 MySQL Management

```bash
# Check status
python3 fw/mysql.py status

# View logs
python3 fw/mysql.py logs

# Run SQL commands
python3 fw/mysql.py cmd --host <MASTER_IP> -- -e "SELECT 1;"
python3 fw/mysql.py cmd --host <MASTER_IP> --database tpcc -- -e "SHOW TABLES;"

# Stop MySQL
python3 fw/mysql.py stop
```

---

# Part 2: TPC-C Benchmark (OLTP)

TPC-C simulates an order-entry environment with mixed read/write transactions.
This benchmark uses sysbench's OLTP workload which provides similar characteristics.

## 2.1 Initialize Sysbench

```bash
# Pull sysbench Docker image
python3 bench/tpcc_mysql.py init
```

## 2.2 Prepare TPC-C Data

> **Note:** The prepare command is idempotent - it drops and recreates the database before loading data.

```bash
python3 bench/tpcc_mysql.py prepare --mysql-host <MASTER_IP>
```

**Adjust data size:**

```bash
python3 bench/tpcc_mysql.py prepare --mysql-host <MASTER_IP> \
    --tables 10 \           # Number of tables (default: 10)
    --table-size 100000     # Rows per table (default: 10000)
```

## 2.3 Run TPC-C Benchmark

```bash
python3 bench/tpcc_mysql.py run --mysql-host <MASTER_IP>
```

**Adjust benchmark parameters:**

```bash
python3 bench/tpcc_mysql.py run --mysql-host <MASTER_IP> \
    --threads 8 \           # Concurrent threads (default: 4)
    --duration 120          # Test duration in seconds (default: 60)
```

**Expected output:**

```
============================================================
TPC-C BENCHMARK (OLTP Read/Write)
============================================================

[ 10s ] thds: 4 tps: 2470.89 qps: 49422.87 lat (ms,95%): 1.86
[ 20s ] thds: 4 tps: 2496.44 qps: 49928.98 lat (ms,95%): 1.79
[ 30s ] thds: 4 tps: 2507.73 qps: 50151.72 lat (ms,95%): 1.76

SQL statistics:
    transactions:                        74757  (2491.60 per sec.)
    queries:                             1495140 (49831.90 per sec.)

Latency (ms):
         95th percentile:                        1.79

============================================================
BENCHMARK COMPLETE
============================================================
```

## 2.4 Cleanup

```bash
# Drop TPC-C database
python3 bench/tpcc_mysql.py cleanup --mysql-host <MASTER_IP>
```

---

# Part 3: TPC-H Benchmark (OLAP)

TPC-H is a decision support benchmark with complex analytical queries over a large dataset.

## 3.1 Initialize TPC-H dbgen

```bash
# Download and build TPC-H data generator
python3 bench/tpch_mysql.py init
```

## 3.2 Prepare TPC-H Data

> **Note:** The prepare command is idempotent - it drops and recreates the database, generates data, and loads all tables.

```bash
python3 bench/tpch_mysql.py prepare --mysql-host <MASTER_IP>
```

**Adjust scale factor:**

```bash
python3 bench/tpch_mysql.py prepare --mysql-host <MASTER_IP> \
    --scale 1.0             # Scale factor (0.1 = ~100MB, 1 = ~1GB)
```

## 3.3 Run TPC-H Queries

**Run a specific query:**

```bash
# Query 1: Pricing Summary Report
python3 bench/tpch_mysql.py run --mysql-host <MASTER_IP> --query 1

# Query 6: Forecasting Revenue Change
python3 bench/tpch_mysql.py run --mysql-host <MASTER_IP> --query 6

# Query 14: Promotion Effect
python3 bench/tpch_mysql.py run --mysql-host <MASTER_IP> --query 14
```

**Run all queries:**

```bash
python3 bench/tpch_mysql.py run-all --mysql-host <MASTER_IP>
```

**Available TPC-H queries:**

| Query | Description |
|-------|-------------|
| Q1 | Pricing Summary Report - aggregate pricing data |
| Q6 | Forecasting Revenue Change - revenue from discounts |
| Q14 | Promotion Effect - promotional item percentage |

**Expected output:**

```
============================================================
TPC-H Query 1
============================================================
l_returnflag  l_linestatus  sum_qty     sum_base_price    ...
A             F             3774200.00  5320753880.69     ...
N             F             95257.00    133737795.84      ...
N             O             7459297.00  10512270008.90    ...
R             F             3785523.00  5337950526.47     ...

Query time: 1.15s

============================================================
ALL QUERIES COMPLETE
============================================================
  Query 1: 1.15s
  Query 6: 0.32s
  Query 14: 0.34s
  Total: 1.80s
```

## 3.4 Cleanup

```bash
# Drop TPC-H database
python3 bench/tpch_mysql.py cleanup --mysql-host <MASTER_IP>
```

---

# Reference

## MySQL Configuration

The MySQL server is configured with optimizations for benchmarking:

| Setting | Value | Purpose |
|---------|-------|---------|
| innodb-buffer-pool-size | 1G | Memory for caching data and indexes |
| innodb-log-file-size | 256M | Redo log size for write performance |
| innodb-flush-log-at-trx-commit | 2 | Reduced durability for throughput |
| max-connections | 200 | Support concurrent benchmark clients |
| local-infile | 1 | Enable bulk data loading (TPC-H) |
| default-authentication-plugin | mysql_native_password | Compatibility with sysbench |

## Benchmark Options

### TPC-C Options

```bash
python3 bench/tpcc_mysql.py run \
    --mysql-host <MASTER_IP> \   # MySQL host
    --mysql-port 3306 \          # MySQL port (default: 3306)
    --mysql-user root \          # MySQL user (default: root)
    --mysql-password benchmark \ # MySQL password (default: benchmark)
    --database tpcc \            # Database name (default: tpcc)
    --tables 10 \                # Number of tables
    --table-size 10000 \         # Rows per table
    --threads 4 \                # Concurrent threads
    --duration 60                # Test duration (seconds)
```

### TPC-H Options

```bash
python3 bench/tpch_mysql.py prepare \
    --mysql-host <MASTER_IP> \   # MySQL host
    --mysql-port 3306 \          # MySQL port (default: 3306)
    --mysql-user root \          # MySQL user (default: root)
    --mysql-password benchmark \ # MySQL password (default: benchmark)
    --database tpch \            # Database name (default: tpch)
    --scale 0.1 \                # Scale factor (0.1 = ~100MB)
    --dbgen-dir /tmp/tpch-dbgen  # TPC-H dbgen directory
```

---

# Cleanup

All benchmarks **automatically clean up** before running, making them idempotent. You can run any benchmark multiple times without manual intervention.

## Automatic Behavior

| Benchmark | Auto Cleanup |
|-----------|--------------|
| TPC-C | Drops and recreates database before `prepare` |
| TPC-H | Drops and recreates database before `prepare` |

## Manual Cleanup Commands

```bash
# TPC-C: Drop database
python3 bench/tpcc_mysql.py cleanup --mysql-host <MASTER_IP>

# TPC-H: Drop database
python3 bench/tpch_mysql.py cleanup --mysql-host <MASTER_IP>
```

## Full Cleanup

To completely reset MySQL and data directories:

```bash
# Stop MySQL
python3 fw/mysql.py stop

# Remove MySQL container
docker rm mysql 2>/dev/null

# Clean data directory (requires root-owned file cleanup)
docker run --rm -v /tmp/mysql-data:/cleanup:rw alpine:3.19 \
    sh -c "rm -rf /cleanup/* /cleanup/.[!.]*"

# Restart fresh
python3 fw/mysql.py start --host <MASTER_IP>
```

---

# Quick Start

Run complete benchmarks from scratch:

```bash
# Set your IP
export MASTER_IP=10.0.0.4

# Start MySQL
python3 fw/mysql.py start --host $MASTER_IP
sleep 20

# Run TPC-C benchmark
python3 bench/tpcc_mysql.py prepare --mysql-host $MASTER_IP
python3 bench/tpcc_mysql.py run --mysql-host $MASTER_IP --threads 4 --duration 30

# Run TPC-H benchmark
python3 bench/tpch_mysql.py prepare --mysql-host $MASTER_IP --scale 0.1
python3 bench/tpch_mysql.py run-all --mysql-host $MASTER_IP

# Cleanup
python3 fw/mysql.py stop
```
