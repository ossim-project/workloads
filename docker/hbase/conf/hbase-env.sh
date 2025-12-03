#!/usr/bin/env bash
#
# HBase environment configuration for distributed mode
#

# Java home
export JAVA_HOME="${JAVA_HOME:-/opt/java/openjdk}"

# HBase memory settings
export HBASE_HEAPSIZE="${HBASE_HEAPSIZE:-1G}"
export HBASE_MASTER_OPTS="${HBASE_MASTER_OPTS:--Xms512m -Xmx1g}"
export HBASE_REGIONSERVER_OPTS="${HBASE_REGIONSERVER_OPTS:--Xms512m -Xmx1g}"

# Disable managing ZooKeeper (use external ZK for distributed mode)
export HBASE_MANAGES_ZK="${HBASE_MANAGES_ZK:-false}"

# PID directory
export HBASE_PID_DIR="${HBASE_PID_DIR:-/tmp/hbase-pids}"

# Log directory
export HBASE_LOG_DIR="${HBASE_LOG_DIR:-/opt/hbase/logs}"

# Disable SSH for local pseudo-distributed testing
export HBASE_SSH_OPTS="${HBASE_SSH_OPTS:--o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10}"

# Extra classpath
# export HBASE_CLASSPATH=""

# GC logging (optional)
# export HBASE_OPTS="$HBASE_OPTS -Xloggc:$HBASE_LOG_DIR/gc.log -XX:+PrintGCDetails"
