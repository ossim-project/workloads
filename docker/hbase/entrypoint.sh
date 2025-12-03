#!/bin/bash
#
# HBase Docker entrypoint script
# Supports: master, regionserver, shell, and custom commands
#

set -e

HBASE_HOME="${HBASE_HOME:-/opt/hbase}"

# Function to wait for ZooKeeper to be ready
wait_for_zookeeper() {
    local zk_host="${HBASE_ZOOKEEPER_QUORUM:-localhost}"
    local zk_port="${HBASE_ZOOKEEPER_PORT:-2181}"

    echo "Waiting for ZooKeeper at ${zk_host}:${zk_port}..."

    local max_attempts=30
    local attempt=1
    while [ $attempt -le $max_attempts ]; do
        if nc -z "$zk_host" "$zk_port" 2>/dev/null; then
            echo "ZooKeeper is ready!"
            return 0
        fi
        echo "Attempt $attempt/$max_attempts: ZooKeeper not ready, waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done

    echo "ERROR: ZooKeeper not available after $max_attempts attempts"
    return 1
}

# Function to update hbase-site.xml with environment variables
configure_hbase() {
    local config_file="${HBASE_HOME}/conf/hbase-site.xml"

    # Create a temporary file with substituted values
    if [ -n "$HBASE_ZOOKEEPER_QUORUM" ]; then
        sed -i "s|\${env.HBASE_ZOOKEEPER_QUORUM:-localhost}|${HBASE_ZOOKEEPER_QUORUM}|g" "$config_file"
    else
        sed -i "s|\${env.HBASE_ZOOKEEPER_QUORUM:-localhost}|localhost|g" "$config_file"
    fi

    if [ -n "$HBASE_ZOOKEEPER_PORT" ]; then
        sed -i "s|\${env.HBASE_ZOOKEEPER_PORT:-2181}|${HBASE_ZOOKEEPER_PORT}|g" "$config_file"
    else
        sed -i "s|\${env.HBASE_ZOOKEEPER_PORT:-2181}|2181|g" "$config_file"
    fi

    if [ -n "$HBASE_ROOTDIR" ]; then
        sed -i "s|\${env.HBASE_ROOTDIR:-file:///data/hbase}|${HBASE_ROOTDIR}|g" "$config_file"
    else
        sed -i "s|\${env.HBASE_ROOTDIR:-file:///data/hbase}|file:///data/hbase|g" "$config_file"
    fi

    # Clean up remaining env references
    sed -i 's/\${env\.[^}]*:-\([^}]*\)}/\1/g' "$config_file"
    sed -i 's/\${hbase\.rootdir}/file:\/\/\/data\/hbase/g' "$config_file"

    echo "HBase configuration updated:"
    echo "  ZooKeeper: ${HBASE_ZOOKEEPER_QUORUM:-localhost}:${HBASE_ZOOKEEPER_PORT:-2181}"
    echo "  Root dir: ${HBASE_ROOTDIR:-file:///data/hbase}"
}

# Function to start HBase Master
start_master() {
    echo "Starting HBase Master..."
    configure_hbase
    wait_for_zookeeper

    # Configure hostname for external access (use IP instead of container hostname)
    local config_file="${HBASE_HOME}/conf/hbase-site.xml"
    if [ -n "$HBASE_MASTER_HOSTNAME" ]; then
        echo "  Master hostname: $HBASE_MASTER_HOSTNAME"
        sed -i "s|</configuration>|<property><name>hbase.master.hostname</name><value>$HBASE_MASTER_HOSTNAME</value></property></configuration>|" "$config_file"
    fi

    # Start master in foreground
    exec "$HBASE_HOME/bin/hbase" master start
}

# Function to start HBase RegionServer
start_regionserver() {
    echo "Starting HBase RegionServer..."
    configure_hbase
    wait_for_zookeeper

    # Wait a bit for master to be ready
    echo "Waiting for HBase Master to be ready..."
    sleep 5

    # Set port options if specified via hbase-site.xml modifications
    local config_file="${HBASE_HOME}/conf/hbase-site.xml"
    if [ -n "$HBASE_REGIONSERVER_PORT" ]; then
        echo "  RegionServer port: $HBASE_REGIONSERVER_PORT"
        # Add regionserver port property before closing </configuration>
        sed -i "s|</configuration>|<property><name>hbase.regionserver.port</name><value>$HBASE_REGIONSERVER_PORT</value></property></configuration>|" "$config_file"
    fi
    if [ -n "$HBASE_REGIONSERVER_INFO_PORT" ]; then
        echo "  RegionServer info port: $HBASE_REGIONSERVER_INFO_PORT"
        # Add regionserver info port property before closing </configuration>
        sed -i "s|</configuration>|<property><name>hbase.regionserver.info.port</name><value>$HBASE_REGIONSERVER_INFO_PORT</value></property></configuration>|" "$config_file"
    fi
    # Configure hostname for external access (use IP instead of container hostname)
    if [ -n "$HBASE_REGIONSERVER_HOSTNAME" ]; then
        echo "  RegionServer hostname: $HBASE_REGIONSERVER_HOSTNAME"
        sed -i "s|</configuration>|<property><name>hbase.regionserver.hostname</name><value>$HBASE_REGIONSERVER_HOSTNAME</value></property></configuration>|" "$config_file"
    fi

    # Start regionserver in foreground
    exec "$HBASE_HOME/bin/hbase" regionserver start
}

# Function to start HBase shell
start_shell() {
    configure_hbase
    exec "$HBASE_HOME/bin/hbase" shell "$@"
}

# Main entrypoint
case "$1" in
    master)
        start_master
        ;;
    regionserver|rs)
        start_regionserver
        ;;
    shell)
        shift
        start_shell "$@"
        ;;
    help|--help|-h)
        echo "Usage: docker run <image> <command>"
        echo ""
        echo "Commands:"
        echo "  master        Start HBase Master"
        echo "  regionserver  Start HBase RegionServer"
        echo "  shell         Start HBase shell"
        echo "  help          Show this help message"
        echo ""
        echo "Environment variables:"
        echo "  HBASE_ZOOKEEPER_QUORUM  ZooKeeper host (default: localhost)"
        echo "  HBASE_ZOOKEEPER_PORT    ZooKeeper port (default: 2181)"
        echo "  HBASE_ROOTDIR           HBase root directory (default: file:///data/hbase)"
        echo "  HBASE_HEAPSIZE          JVM heap size (default: 1G)"
        ;;
    *)
        # Run any other command directly
        exec "$@"
        ;;
esac
