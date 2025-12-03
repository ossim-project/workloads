#!/usr/bin/env python3
"""Set up HBase cluster nodes using Docker images."""

import argparse
import socket
import subprocess
import sys

# HBase image from GitHub Container Registry
DEFAULT_IMAGE = "ghcr.io/ossim-project/hbase:latest"
DEFAULT_ZK_IMAGE = "zookeeper:3.9"


def resolve_hostname(host: str) -> str:
    """Resolve hostname to IP address for docker --add-host flag."""
    try:
        # Check if already an IP address
        socket.inet_aton(host)
        return host
    except socket.error:
        # Resolve hostname to IP
        try:
            return socket.gethostbyname(host)
        except socket.gaierror:
            # If resolution fails, return original (let docker handle error)
            return host


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
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


def init(image: str) -> None:
    """Pull HBase and ZooKeeper images."""
    print(f"Pulling HBase image: {image}")
    run(["docker", "pull", image])
    print(f"\nPulling ZooKeeper image: {DEFAULT_ZK_IMAGE}")
    run(["docker", "pull", DEFAULT_ZK_IMAGE])
    print("\nInit complete.")


def start_zookeeper(
    name: str,
    host: str | None = None,
    port: int = 2181,
    data_dir: str = "/tmp/zookeeper-data",
) -> None:
    """Start ZooKeeper for HBase."""
    host = host or get_host_ip()
    hostname = "zookeeper"
    print("Starting ZooKeeper...")
    print(f"  Image: {DEFAULT_ZK_IMAGE}")
    print(f"  Address: {host}:{port}")
    print(f"  Data dir: {data_dir}")

    # Create data directory (chmod may fail if owned by root from previous runs)
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir], check=False)

    run([
        "docker", "run", "-d",
        "--name", name,
        "--hostname", hostname,
        "--network", "host",
        "--add-host", f"{hostname}:{resolve_hostname(host)}",
        "-v", f"{data_dir}:/data:rw",
        "-e", f"ZOO_PORT={port}",
        "-e", "ZOO_4LW_COMMANDS_WHITELIST=*",
        "-e", "ZOO_ADMINSERVER_ENABLED=false",  # Disable admin server to avoid port conflicts
        DEFAULT_ZK_IMAGE,
    ])

    print(f"ZooKeeper started. Container: {name}")


def start_master(
    image: str,
    name: str,
    zookeeper: str,
    host: str | None = None,
    hdfs_url: str | None = None,
    data_dir: str = "/tmp/hbase-data",
) -> None:
    """Start HBase Master."""
    host = host or get_host_ip()
    hostname = name
    print("Starting HBase Master...")
    print(f"  Image: {image}")
    print(f"  Master UI: http://{host}:16010")
    print(f"  ZooKeeper: {zookeeper}")
    if hdfs_url:
        print(f"  HDFS: {hdfs_url}")
        print(f"  Root dir: {hdfs_url}/hbase")
    else:
        print(f"  Root dir: file:///data/hbase (local)")
    print(f"  Data dir: {data_dir}")

    # Parse ZooKeeper host and port
    if ":" in zookeeper:
        zk_host, zk_port = zookeeper.rsplit(":", 1)
    else:
        zk_host = zookeeper
        zk_port = "2181"

    # Create data directory (chmod may fail if owned by root from previous runs)
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir], check=False)

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--hostname", hostname,
        "--network", "host",
        "--add-host", f"{hostname}:{resolve_hostname(host)}",
        "--add-host", f"zookeeper:{resolve_hostname(zk_host)}",
        "-v", f"{data_dir}:/data/hbase:rw",
        "-e", f"HBASE_ZOOKEEPER_QUORUM={zk_host}",
        "-e", f"HBASE_ZOOKEEPER_PORT={zk_port}",
        "-e", f"HBASE_MASTER_HOSTNAME={host}",
    ]

    # Configure root directory (HDFS or local)
    if hdfs_url:
        cmd.extend([
            "-e", f"HBASE_ROOTDIR={hdfs_url}/hbase",
            "-e", f"CORE-SITE.XML_fs.defaultFS={hdfs_url}",
        ])
    else:
        cmd.extend(["-e", "HBASE_ROOTDIR=file:///data/hbase"])

    cmd.extend([image, "master"])
    run(cmd)

    print(f"HBase Master started. Container: {name}")


def start_regionserver(
    image: str,
    name: str,
    zookeeper: str,
    host: str | None = None,
    master_host: str | None = None,
    hdfs_url: str | None = None,
    port: int = 16020,
    info_port: int = 16030,
    data_dir: str = "/tmp/hbase-data",
) -> None:
    """Start HBase RegionServer."""
    host = host or get_host_ip()
    master_host = master_host or host
    hostname = name
    print("Starting HBase RegionServer...")
    print(f"  Image: {image}")
    print(f"  RegionServer UI: http://{host}:{info_port}")
    print(f"  ZooKeeper: {zookeeper}")
    print(f"  Master: {master_host}")
    if hdfs_url:
        print(f"  HDFS: {hdfs_url}")
    print(f"  Ports: rpc={port}, info={info_port}")
    print(f"  Data dir: {data_dir}")

    # Parse ZooKeeper host and port
    if ":" in zookeeper:
        zk_host, zk_port = zookeeper.rsplit(":", 1)
    else:
        zk_host = zookeeper
        zk_port = "2181"

    # Create data directory (shared with master, chmod may fail if owned by root)
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir], check=False)

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--hostname", hostname,
        "--network", "host",
        "--add-host", f"{hostname}:{resolve_hostname(host)}",
        "--add-host", f"zookeeper:{resolve_hostname(zk_host)}",
        "--add-host", f"hbase-master:{resolve_hostname(master_host)}",
        "-v", f"{data_dir}:/data/hbase:rw",
        "-e", f"HBASE_ZOOKEEPER_QUORUM={zk_host}",
        "-e", f"HBASE_ZOOKEEPER_PORT={zk_port}",
        "-e", f"HBASE_REGIONSERVER_HOSTNAME={host}",
    ]

    # Configure root directory (HDFS or local)
    if hdfs_url:
        cmd.extend([
            "-e", f"HBASE_ROOTDIR={hdfs_url}/hbase",
            "-e", f"CORE-SITE.XML_fs.defaultFS={hdfs_url}",
        ])
    else:
        cmd.extend(["-e", "HBASE_ROOTDIR=file:///data/hbase"])
    # Add port configuration if non-default
    if port != 16020:
        cmd.extend(["-e", f"HBASE_REGIONSERVER_PORT={port}"])
    if info_port != 16030:
        cmd.extend(["-e", f"HBASE_REGIONSERVER_INFO_PORT={info_port}"])

    cmd.extend([image, "regionserver"])
    run(cmd)

    print(f"HBase RegionServer started. Container: {name}")


def stop(name: str) -> None:
    """Stop and remove a container."""
    print(f"Stopping {name}...")
    run(["docker", "stop", name], check=False)
    run(["docker", "rm", name], check=False)
    print("Stopped.")


def status(name: str) -> None:
    """Check container status."""
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    )
    if name in result.stdout:
        print(f"{name} is running")
        run(["docker", "ps", "--filter", f"name={name}"])
    else:
        print(f"{name} is not running")


def logs(name: str, follow: bool = True) -> None:
    """Show container logs."""
    cmd = ["docker", "logs"]
    if follow:
        cmd.append("-f")
    cmd.append(name)
    run(cmd)


def shell(image: str, zookeeper: str) -> None:
    """Start interactive HBase shell."""
    # Parse ZooKeeper host
    if ":" in zookeeper:
        zk_host, zk_port = zookeeper.rsplit(":", 1)
    else:
        zk_host = zookeeper
        zk_port = "2181"

    print(f"Starting HBase shell (ZooKeeper: {zookeeper})...")
    run([
        "docker", "run", "--rm", "-it",
        "--network", "host",
        "--add-host", f"zookeeper:{resolve_hostname(zk_host)}",
        "-e", f"HBASE_ZOOKEEPER_QUORUM={zk_host}",
        "-e", f"HBASE_ZOOKEEPER_PORT={zk_port}",
        image,
        "shell",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up HBase cluster nodes using Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Build HBase image and pull dependencies
  %(prog)s init

  # Start distributed cluster:
  # 1. Start ZooKeeper
  %(prog)s start --role zookeeper --host <MASTER_IP>

  # 2. Start Master
  %(prog)s start --role master --zookeeper <MASTER_IP>:2181 --host <MASTER_IP>

  # 3. Start RegionServer(s)
  %(prog)s start --role regionserver --zookeeper <MASTER_IP>:2181 --name hbase-rs-1
  %(prog)s start --role regionserver --zookeeper <MASTER_IP>:2181 --name hbase-rs-2 \\
      --rs-port 16021 --rs-info-port 16031

  # Interactive HBase shell
  %(prog)s shell --zookeeper <MASTER_IP>:2181

  # Stop/status/logs
  %(prog)s stop --role master
  %(prog)s status --role regionserver --name hbase-rs-1
  %(prog)s logs --role zookeeper
""",
    )

    parser.add_argument(
        "action",
        choices=["init", "start", "stop", "status", "logs", "shell"],
        help="Action to perform",
    )
    parser.add_argument(
        "--role",
        choices=["master", "regionserver", "zookeeper"],
        help="Node role (required for start/stop/status/logs)",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        help="Container name (default: hbase-<role>)",
    )

    # Host option
    parser.add_argument(
        "--host",
        help="Host IP (default: auto-detect)",
    )

    # Distributed mode options
    parser.add_argument(
        "--zookeeper",
        default="localhost:2181",
        help="ZooKeeper host:port (default: localhost:2181)",
    )
    parser.add_argument(
        "--zk-port",
        type=int,
        default=2181,
        help="ZooKeeper port when starting ZK (default: 2181)",
    )

    # Master host (for regionserver)
    parser.add_argument(
        "--master-host",
        help="Master host IP for regionserver (default: same as host)",
    )

    # RegionServer port options
    parser.add_argument(
        "--rs-port",
        type=int,
        default=16020,
        help="RegionServer RPC port (default: 16020)",
    )
    parser.add_argument(
        "--rs-info-port",
        type=int,
        default=16030,
        help="RegionServer info/web port (default: 16030)",
    )

    # Data directory
    parser.add_argument(
        "--data-dir",
        default="/tmp/hbase-data",
        help="Data directory (default: /tmp/hbase-data)",
    )

    # HDFS option for distributed storage
    parser.add_argument(
        "--hdfs",
        help="HDFS namenode URL for distributed storage (e.g., hdfs://10.0.0.1:9000)",
    )

    args = parser.parse_args()

    # Handle init (no role required)
    if args.action == "init":
        init(args.image)
        return 0

    # Handle shell (no role required)
    if args.action == "shell":
        shell(args.image, args.zookeeper)
        return 0

    # Require role for other actions
    if not args.role:
        parser.error("--role is required for start/stop/status/logs")

    # Set default container name
    if not args.name:
        args.name = f"hbase-{args.role}"

    # Handle actions
    if args.action == "start":
        if args.role == "zookeeper":
            zk_data_dir = args.data_dir.replace("hbase", "zookeeper")
            start_zookeeper(args.name, args.host, args.zk_port, zk_data_dir)
        elif args.role == "master":
            start_master(
                args.image, args.name, args.zookeeper, args.host,
                args.hdfs, args.data_dir
            )
        elif args.role == "regionserver":
            start_regionserver(
                args.image, args.name, args.zookeeper, args.host,
                args.master_host, args.hdfs, args.rs_port, args.rs_info_port, args.data_dir
            )

    elif args.action == "stop":
        stop(args.name)

    elif args.action == "status":
        status(args.name)

    elif args.action == "logs":
        logs(args.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
