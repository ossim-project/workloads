# Big Data Workloads

Tools for running big data workloads on distributed clusters.

## File Structure

```
README.md              # This file
fw/                    # Framework wrappers
├── hdfs.py            # HDFS cluster management
├── spark.py           # Spark cluster management
├── hive.py            # Hive cluster management
├── hbase.py           # HBase cluster management
└── flink.py           # Kafka cluster management
bench/                 # Benchmark scripts
├── tpcds.py           # Common TPC-DS utilities
├── tpcds_spark.py     # TPC-DS benchmark for Spark
├── tpcds_hive.py      # TPC-DS benchmark for Hive
├── ycsb_hbase.py      # YCSB benchmark for HBase
└── flink_bench.py     # Flink SQL benchmark (DataGen/BlackHole)
```

## Supported Benchmarks

| Benchmark | Engine |
|-----------|--------|
| TPC-DS Q99 | Spark |
| TPC-DS Q99 | Hive |
| YCSB (A-F) | HBase |
| Flink SQL (DataGen) | Flink |

---

# Part 1: Common Setup

## Prerequisites

- Docker installed on all machines
- Network connectivity between machines

## Configuration

Replace `${MASTER_IP}` in all commands with your master node's IP address:

```bash
# Example: Set your master IP
export MASTER_IP=10.0.0.4
```

## 1.1 Initialize

```bash
# Install dependencies
bash fw/install_deps.sh

# Pull Hadoop image (required for HDFS)
python3 fw/hdfs.py init
```

## 1.2 Start HDFS Cluster

HDFS is the shared storage layer for all benchmarks.

**On the namenode machine:**

```bash
python3 fw/hdfs.py start --role namenode --host ${MASTER_IP} --data-dir /tmp/hdfs-data-nn
```

**On datanode machines** (can be same or different machines):

```bash
python3 fw/hdfs.py start --role datanode --namenode hdfs://${MASTER_IP}:9000 \
    --name hdfs-datanode
```

> **Note:** Each HDFS node (namenode and datanodes) must have its own separate data directory. Sharing data directories between nodes causes cluster ID conflicts.
If lauching multiple logical nodes on the same physical machine, use different data directories and ports:

```bash
python3 fw/hdfs.py start --role datanode --namenode hdfs://${MASTER_IP}:9000 \
    --host ${MASTER_IP} --name hdfs-datanode-1 \
    --data-dir /tmp/hdfs-data-dn1 \
    --datanode-port 9876 --datanode-http-port 9874 \
    --datanode-ipc-port 9877
```

**Verify HDFS is working:**

```bash
python3 fw/hdfs.py cmd --namenode hdfs://${MASTER_IP}:9000 -- -ls /
```

## 1.3 Prepare TPC-DS Data

Before running TPC-DS benchmarks, prepare the data in HDFS.

> **Note:** Run this command on the namenode machine, as it uses `docker exec` to access the namenode container.

```bash
# Install build dependencies
sudo apt-get install -y build-essential

# Prepare TPC-DS data in HDFS (generates data if needed, uploads to HDFS)
python3 bench/tpcds_spark.py prepare \
    --hdfs-base hdfs://${MASTER_IP}:9000/bench/tpcds
```

**Verify HDFS data:**

```bash
python3 fw/hdfs.py cmd --namenode hdfs://${MASTER_IP}:9000 -- -ls /bench/tpcds/raw/sf1/
```

---

# Part 2: Spark Benchmarks

## 2.1 Start Spark Cluster

**On the master machine:**

```bash
python3 fw/spark.py start --role master --host ${MASTER_IP}
```

**On worker machines**:

```bash
python3 fw/spark.py start --role worker --master spark://${MASTER_IP}:7077
```

Run multiple workers on the same host with differnt names: 

```bash
python3 fw/spark.py start --role worker --master spark://${MASTER_IP}:7077 --name spark-worker-1
```

## 2.2 Run TPC-DS Q99 on Spark

> **Note:** Ensure TPC-DS data is prepared first (see section 1.3). The run command can be executed multiple times - table cleanup is automatic.

```bash
python3 bench/tpcds_spark.py run \
    --master spark://${MASTER_IP}:7077 \
    --hdfs-base hdfs://${MASTER_IP}:9000/bench/tpcds
```

**Expected output:**
```
============================================================
TPC-DS Query 99 Benchmark (Spark)
============================================================
Load time:  1.93 seconds
Query time: 8.17 seconds
Total time: 10.10 seconds
============================================================
```

## 2.3 Spark Management

```bash
# Check status
python3 fw/spark.py status --role master
python3 fw/spark.py status --role worker --name spark-worker-1

# View logs
python3 fw/spark.py logs --role master

# Stop nodes
python3 fw/spark.py stop --role worker --name spark-worker-1
python3 fw/spark.py stop --role worker --name spark-worker-2
python3 fw/spark.py stop --role master
```

---

# Part 3: Hive Benchmarks

## 3.1 Start Hive Cluster

Hive requires HDFS to be running (see Part 1).

**Pull Hive image:**

```bash
python3 fw/hive.py init
```

**Start HiveServer2 in standalone mode** (embedded Derby metastore):

```bash
python3 fw/hive.py start --role hiveserver2 --host ${MASTER_IP} \
    --hdfs hdfs://${MASTER_IP}:9000 --data-dir /tmp/hive-data
```

**Wait for HiveServer2 to be ready** (takes ~30 seconds):

```bash
# Check if port 10000 is listening
ss -tln | grep ':10000'
```

**Verify Hive is working:**

```bash
python3 fw/hive.py cmd --hiveserver2 ${MASTER_IP}:10000 -- -e "SHOW DATABASES;"
```

## 3.2 Run TPC-DS Q99 on Hive

Ensure TPC-DS data is prepared first (see section 1.3). The run command will automatically clean up previous tables and can be executed multiple times.

```bash
python3 bench/tpcds_hive.py run \
    --hiveserver2 ${MASTER_IP}:10000 \
    --hdfs-base hdfs://${MASTER_IP}:9000/bench/tpcds
```

**Expected output:**
```
============================================================
TPC-DS Query 99 Benchmark (Hive)
============================================================
...
============================================================
Benchmark Summary
============================================================
Total time: 51.23 seconds
============================================================
```

To manually clean up tables (optional):

```bash
python3 bench/tpcds_hive.py cleanup --hiveserver2 ${MASTER_IP}:10000
```

## 3.3 Hive Management

```bash
# Check status
python3 fw/hive.py status --role hiveserver2

# View logs
python3 fw/hive.py logs --role hiveserver2

# Interactive beeline shell
python3 fw/hive.py shell --hiveserver2 ${MASTER_IP}:10000

# Stop HiveServer2
python3 fw/hive.py stop --role hiveserver2
```

---

# Part 4: HBase Benchmarks

HBase is a distributed column-oriented database built on top of Hadoop.

## 4.1 Build HBase Image

```bash
python3 fw/hbase.py init
```

This builds a custom HBase Docker image supporting true distributed mode and pulls ZooKeeper.

## 4.2 Start HBase Cluster

HBase requires ZooKeeper for coordination. The cluster consists of:
- ZooKeeper (coordination service)
- HBase Master (manages regions and metadata)
- RegionServers (store and serve data)

> **Note:** The hbase.py script supports both IP addresses and hostnames. Hostnames are automatically resolved to IP addresses for Docker's `--add-host` flag.

### Option A: Single-Node Setup (Local Storage)

For testing on a single machine with local storage:

**Start ZooKeeper:**

```bash
python3 fw/hbase.py start --role zookeeper --host ${MASTER_IP}
```

**Start HBase Master:**

```bash
python3 fw/hbase.py start --role master --zookeeper ${MASTER_IP}:2181 --host ${MASTER_IP}
```

**Start RegionServers** (wait ~10 seconds after master starts):

```bash
# First RegionServer
python3 fw/hbase.py start --role regionserver --name hbase-rs-1 \
    --zookeeper ${MASTER_IP}:2181 --host ${MASTER_IP}

# Second RegionServer (same host requires different ports)
python3 fw/hbase.py start --role regionserver --name hbase-rs-2 \
    --zookeeper ${MASTER_IP}:2181 --host ${MASTER_IP} \
    --rs-port 16021 --rs-info-port 16031
```

### Option B: Distributed Setup (HDFS Storage)

For production deployments across multiple nodes with shared HDFS storage:

> **Prerequisites:** HDFS cluster must be running (see Part 1.2).

**On the master node** (e.g., node1):

```bash
# Start ZooKeeper
python3 fw/hbase.py start --role zookeeper --host ${MASTER_IP}

# Start HBase Master with HDFS storage
python3 fw/hbase.py start --role master --zookeeper ${MASTER_IP}:2181 \
    --host ${MASTER_IP} --hdfs hdfs://${MASTER_IP}:9000
```

**On each worker node** (e.g., node2, node3, ...):

```bash
# Start RegionServer with HDFS storage
python3 fw/hbase.py start --role regionserver --name hbase-regionserver \
    --zookeeper ${MASTER_IP}:2181 --master-host ${MASTER_IP} \
    --hdfs hdfs://${MASTER_IP}:9000
```

> **Note:** When using HDFS storage (`--hdfs`), HBase stores data in `hdfs://<namenode>:9000/hbase` instead of local `/tmp/hbase-data`. This enables true distributed operation where all nodes share the same data.

**Verify cluster status:**

```bash
python3 fw/hbase.py shell --zookeeper ${MASTER_IP}:2181
# In HBase shell: status
# Expected: "1 active master, 0 backup masters, N servers" (N = number of RegionServers)
```

## 4.3 Run YCSB Benchmark

YCSB (Yahoo! Cloud Serving Benchmark) tests database performance with various workloads.

> **Note:** The `load` command automatically cleans up existing tables before loading, making it idempotent.

> **Important:** For distributed HBase clusters, run YCSB from the master node (where ZooKeeper and HBase Master are running). YCSB clients need to resolve HBase RegionServer hostnames correctly for data operations.

**Download YCSB:**

```bash
# Install Java for YCSB
sudo apt-get update && sudo apt-get install -y default-jre-headless

python3 bench/ycsb_hbase.py init
```

**Load test data:**

```bash
python3 bench/ycsb_hbase.py load --workload a --zookeeper ${MASTER_IP}:2181 \
    --record-count 10000
```

To manually clean up tables (optional):

```bash
python3 bench/ycsb_hbase.py cleanup --zookeeper ${MASTER_IP}:2181
```

**Run workloads:**

```bash
# Workload A: Update heavy (50% read, 50% update)
python3 bench/ycsb_hbase.py run --workload a --zookeeper ${MASTER_IP}:2181

# Workload B: Read heavy (95% read, 5% update)
python3 bench/ycsb_hbase.py run --workload b --zookeeper ${MASTER_IP}:2181

# Workload C: Read only (100% read)
python3 bench/ycsb_hbase.py run --workload c --zookeeper ${MASTER_IP}:2181

# Run all workloads
python3 bench/ycsb_hbase.py run-all --zookeeper ${MASTER_IP}:2181
```

**Available YCSB workloads:**

| Workload | Description |
|----------|-------------|
| A | Update heavy (50% read, 50% update) |
| B | Read heavy (95% read, 5% update) |
| C | Read only (100% read) |
| D | Read latest (95% read, 5% insert) |
| E | Short ranges (95% scan, 5% insert) |
| F | Read-modify-write (50% read, 50% RMW) |

## 4.4 HBase Management

```bash
# Check status
python3 fw/hbase.py status --role master
python3 fw/hbase.py status --role regionserver --name hbase-rs-1

# View logs
python3 fw/hbase.py logs --role master

# Interactive HBase shell
python3 fw/hbase.py shell --zookeeper ${MASTER_IP}:2181

# Stop nodes (order: regionservers, master, zookeeper)
python3 fw/hbase.py stop --role regionserver --name hbase-rs-2
python3 fw/hbase.py stop --role regionserver --name hbase-rs-1
python3 fw/hbase.py stop --role master
python3 fw/hbase.py stop --role zookeeper
```

---

# Part 5: Flink Benchmarks

Flink is a distributed stream processing framework for stateful computations.
This benchmark uses Flink SQL with built-in connectors for self-contained testing.

## 5.1 Prerequisites

The Flink benchmark uses built-in connectors and requires no external dependencies:
- **DataGen connector**: Generates synthetic source data
- **BlackHole connector**: Discards output for throughput testing

Only Docker is required.

## 5.2 Start Flink Cluster

```bash
# Pull Flink image
python3 fw/flink.py init

# Start JobManager (use port 8085 if 8081 is in use)
python3 fw/flink.py start --role jobmanager --host ${MASTER_IP} --webui-port 8085

# Start TaskManagers
python3 fw/flink.py start --role taskmanager --jobmanager ${MASTER_IP}:6123 \
    --name flink-taskmanager-1 --slots 4 --memory 4g

python3 fw/flink.py start --role taskmanager --jobmanager ${MASTER_IP}:6123 \
    --name flink-taskmanager-2 --slots 4 --memory 4g
```

## 5.3 Run Flink Benchmarks

> **Note:** Benchmarks automatically cancel previous jobs before running, making them idempotent.

**Run identity workload (baseline throughput):**

```bash
python3 bench/flink_bench.py run --workload identity \
    --flink-host ${MASTER_IP} --flink-port 8085
```

To manually cancel running jobs (optional):

```bash
python3 bench/flink_bench.py cleanup --flink-host ${MASTER_IP} --flink-port 8085
```

**Run wordcount workload (stateful aggregation):**

```bash
python3 bench/flink_bench.py run --workload wordcount \
    --flink-host ${MASTER_IP} --flink-port 8085
```

**Run all workloads:**

```bash
python3 bench/flink_bench.py run --workload all \
    --flink-host ${MASTER_IP} --flink-port 8085
```

**Adjust benchmark parameters:**

```bash
python3 bench/flink_bench.py run --workload identity \
    --flink-host ${MASTER_IP} --flink-port 8085 \
    --records 1000000 \    # Number of records to process
    --parallelism 8        # Job parallelism
```

**Available workloads:**

| Workload | Description |
|----------|-------------|
| identity | Pass-through (baseline throughput) |
| wordcount | Stateful word counting (GROUP BY) |
| window | Range-based aggregation (GROUP BY with SUM) |

**Example output:**

```
============================================================
BENCHMARK RESULTS: IDENTITY
============================================================

Job Status: FINISHED
Total Time: 15.85s

Performance Metrics:
  Records Processed: 100,000
  Processing Time:   10.25s
  Throughput:        9,753 records/sec

  SUCCESS: Processed 100,000 records in 10.25s
============================================================
```

## 5.4 Cluster Management

```bash
# Check Flink status
python3 fw/flink.py status --role jobmanager
python3 fw/flink.py status --role taskmanager --name flink-taskmanager-1

# View logs
python3 fw/flink.py logs --role jobmanager

# Cancel all running jobs
python3 bench/flink_bench.py cancel --flink-host ${MASTER_IP} --flink-port 8085

# Stop cluster (TaskManagers first, then JobManager)
python3 fw/flink.py stop --role taskmanager --name flink-taskmanager-2
python3 fw/flink.py stop --role taskmanager --name flink-taskmanager-1
python3 fw/flink.py stop --role jobmanager
```

---

# Reference

## HDFS Management

```bash
# Check status
python3 fw/hdfs.py status --role namenode
python3 fw/hdfs.py status --role datanode --name hdfs-datanode-1

# View logs
python3 fw/hdfs.py logs --role namenode

# Stop nodes
python3 fw/hdfs.py stop --role datanode --name hdfs-datanode-1
python3 fw/hdfs.py stop --role datanode --name hdfs-datanode-2
python3 fw/hdfs.py stop --role namenode

# HDFS commands (via new container)
python3 fw/hdfs.py cmd --namenode hdfs://${MASTER_IP}:9000 -- -ls /
python3 fw/hdfs.py cmd --namenode hdfs://${MASTER_IP}:9000 -- -mkdir /test
python3 fw/hdfs.py cmd --namenode hdfs://${MASTER_IP}:9000 -- -rm -r /path

# Execute commands in running container (for file operations)
python3 fw/hdfs.py exec --role namenode -- hdfs dfs -ls /
python3 fw/hdfs.py exec --role namenode -- bash -c "hdfs dfs -put /opt/hadoop/data/*.dat /path/"

# Interactive shell
python3 fw/hdfs.py shell --namenode hdfs://${MASTER_IP}:9000
```

## Benchmark Options

### TPC-DS Data Generation

```bash
python3 bench/tpcds_spark.py generate \
    --scale 1 \                       # Scale factor (1 = ~1GB, 10 = ~10GB, etc.)
    --output-dir /tmp/tpcds_sf1 \     # Local output directory
    --tpcds-kit /tmp/tpcds-kit        # Path to tpcds-kit (auto-cloned if missing)
```

### TPC-DS Query Execution (Spark)

```bash
python3 bench/tpcds_spark.py run \
    --master spark://${MASTER_IP}:7077 \
    --hdfs-base hdfs://${MASTER_IP}:9000/bench/tpcds \
    --scale 1 \                       # Must match generated data
    --executor-memory 2g \
    --executor-cores 2 \
    --shuffle-partitions 64 \
    --output hdfs://${MASTER_IP}:9000/results/q99  # Optional: save results
```

### TPC-DS Query Execution (Hive)

```bash
python3 bench/tpcds_hive.py run \
    --hiveserver2 ${MASTER_IP}:10000 \
    --hdfs-base hdfs://${MASTER_IP}:9000/bench/tpcds \
    --scale 1 \                       # Must match generated data
    --database default                # Hive database to use
```

---

# Cleanup

All benchmarks **automatically clean up** before running, making them idempotent. You can run any benchmark multiple times or after an interrupted run without manual intervention.

## Automatic Behavior

| Benchmark | Data Setup | Auto Cleanup |
|-----------|------------|--------------|
| TPC-DS (Spark/Hive) | Run `prepare` command first (cleans stale data, uploads fresh) | Stateless (Spark) / Drops tables (Hive) |
| YCSB (HBase) | N/A | Drops and recreates table before loading data |
| Flink SQL | N/A (uses DataGen connector) | Cancels any running jobs before starting |

## Manual Cleanup Commands

For manual cleanup (optional), each benchmark provides a `cleanup` command:

```bash
# Hive: Drop TPC-DS tables
python3 bench/tpcds_hive.py cleanup --hiveserver2 ${MASTER_IP}:10000

# HBase: Drop YCSB table
python3 bench/ycsb_hbase.py cleanup --zookeeper ${MASTER_IP}:2181

# Flink: Cancel running jobs
python3 bench/flink_bench.py cleanup --flink-host ${MASTER_IP} --flink-port 8085
```

## Full Cluster Cleanup

To completely reset all clusters and data directories:

```bash
# Stop all benchmark-related containers
docker stop flink-taskmanager-2 flink-taskmanager-1 flink-jobmanager 2>/dev/null
docker stop hive-server2 hive-metastore 2>/dev/null
docker stop hbase-rs-2 hbase-rs-1 hbase-master hbase-zookeeper 2>/dev/null
docker stop spark-worker-2 spark-worker-1 spark-master 2>/dev/null
docker stop hdfs-datanode-2 hdfs-datanode-1 hdfs-namenode 2>/dev/null

# Remove stopped containers
docker rm flink-taskmanager-2 flink-taskmanager-1 flink-jobmanager 2>/dev/null
docker rm hive-server2 hive-metastore 2>/dev/null
docker rm hbase-rs-2 hbase-rs-1 hbase-master hbase-zookeeper 2>/dev/null
docker rm spark-worker-2 spark-worker-1 spark-master 2>/dev/null
docker rm hdfs-datanode-2 hdfs-datanode-1 hdfs-namenode 2>/dev/null

# Remove data directories (WARNING: deletes all data)
rm -rf /tmp/hdfs-data-* /tmp/hive-data /tmp/hbase-data /tmp/zookeeper-data
```

## Quick Restart Scripts

### Restart HDFS Only

```bash
# Stop HDFS
python3 fw/hdfs.py stop --role datanode --name hdfs-datanode-2
python3 fw/hdfs.py stop --role datanode --name hdfs-datanode-1
python3 fw/hdfs.py stop --role namenode

# Clean data directories
rm -rf /tmp/hdfs-data-*

# Start HDFS
python3 fw/hdfs.py start --role namenode --host ${MASTER_IP} --data-dir /tmp/hdfs-data-nn
python3 fw/hdfs.py start --role datanode --namenode hdfs://${MASTER_IP}:9000 \
    --host ${MASTER_IP} --name hdfs-datanode-1 --data-dir /tmp/hdfs-data-dn1
python3 fw/hdfs.py start --role datanode --namenode hdfs://${MASTER_IP}:9000 \
    --host ${MASTER_IP} --name hdfs-datanode-2 \
    --datanode-port 9876 --datanode-http-port 9874 --datanode-ipc-port 9877 \
    --data-dir /tmp/hdfs-data-dn2
```

### Restart HBase Only (Single-Node)

```bash
# Stop HBase (order matters)
python3 fw/hbase.py stop --role regionserver --name hbase-rs-2
python3 fw/hbase.py stop --role regionserver --name hbase-rs-1
python3 fw/hbase.py stop --role master
python3 fw/hbase.py stop --role zookeeper

# Clean data directories
rm -rf /tmp/hbase-data /tmp/zookeeper-data

# Start HBase
python3 fw/hbase.py start --role zookeeper --host ${MASTER_IP}
python3 fw/hbase.py start --role master --zookeeper ${MASTER_IP}:2181 --host ${MASTER_IP}
sleep 10
python3 fw/hbase.py start --role regionserver --name hbase-rs-1 \
    --zookeeper ${MASTER_IP}:2181 --host ${MASTER_IP}
python3 fw/hbase.py start --role regionserver --name hbase-rs-2 \
    --zookeeper ${MASTER_IP}:2181 --host ${MASTER_IP} \
    --rs-port 16021 --rs-info-port 16031
```

### Restart HBase Only (Distributed with HDFS)

```bash
# On master node: Stop HBase components
python3 fw/hbase.py stop --role master
python3 fw/hbase.py stop --role zookeeper

# On worker nodes: Stop RegionServers
python3 fw/hbase.py stop --role regionserver --name hbase-regionserver

# Clean ZooKeeper data on master (HDFS data persists)
rm -rf /tmp/zookeeper-data

# On master node: Start HBase with HDFS
python3 fw/hbase.py start --role zookeeper --host ${MASTER_IP}
python3 fw/hbase.py start --role master --zookeeper ${MASTER_IP}:2181 \
    --host ${MASTER_IP} --hdfs hdfs://${MASTER_IP}:9000
sleep 10

# On worker nodes: Start RegionServers with HDFS
python3 fw/hbase.py start --role regionserver --name hbase-regionserver \
    --zookeeper ${MASTER_IP}:2181 --master-host ${MASTER_IP} \
    --hdfs hdfs://${MASTER_IP}:9000
```
