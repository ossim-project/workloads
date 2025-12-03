#!/usr/bin/env python3
"""Set up HDFS cluster nodes using Apache Hadoop Docker images."""

import argparse
import subprocess
import sys

DEFAULT_IMAGE = "apache/hadoop:3"
DEFAULT_NAMENODE_PORT = 9000
DEFAULT_WEBUI_PORT = 9870
DEFAULT_DATANODE_PORT = 9866
DEFAULT_DATANODE_HTTP_PORT = 9864
DEFAULT_DATANODE_IPC_PORT = 9867


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    print(f"+ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def clean_data_dir(data_dir: str) -> None:
    """Clean up data directory, handling docker-created files with root ownership."""
    import os
    if os.path.exists(data_dir):
        # Use docker to remove files (handles permission issues from docker-created files)
        print(f"Cleaning up existing data directory: {data_dir}")
        subprocess.run(
            ["docker", "run", "--rm", "-v", f"{data_dir}:/data", "alpine",
             "sh", "-c", "rm -rf /data/* /data/.*"],
            check=False,
            capture_output=True,
        )


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
    """Pull required Docker images."""
    print("Pulling required Docker images...")
    run(["docker", "pull", image])
    print("Init complete.")


def start_namenode(
    image: str,
    name: str,
    host: str,
    port: int,
    webui_port: int,
    data_dir: str,
) -> None:
    """Start an HDFS namenode."""
    print("Starting HDFS namenode...")
    print(f"  Image: {image}")
    print(f"  HDFS URL: hdfs://{host}:{port}")
    print(f"  Web UI: http://{host}:{webui_port}")
    print(f"  Data dir: {data_dir}")

    # Clean up existing data to avoid cluster ID conflicts
    clean_data_dir(data_dir)

    # Create data directory with proper permissions for hadoop user (UID 1000)
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir])

    # Hadoop configuration via environment variables
    # HADOOP_HOME is /opt/hadoop in the apache/hadoop image
    run([
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-v", f"{data_dir}:/opt/hadoop/data:rw",
        "-e", f"HADOOP_HOME=/opt/hadoop",
        "-e", "ENSURE_NAMENODE_DIR=/opt/hadoop/data/namenode",
        # Core-site.xml settings
        "-e", f"CORE-SITE.XML_fs.defaultFS=hdfs://{host}:{port}",
        # HDFS-site.xml settings
        "-e", f"HDFS-SITE.XML_dfs.namenode.rpc-address={host}:{port}",
        "-e", f"HDFS-SITE.XML_dfs.namenode.http-address={host}:{webui_port}",
        "-e", "HDFS-SITE.XML_dfs.namenode.name.dir=/opt/hadoop/data/namenode",
        "-e", "HDFS-SITE.XML_dfs.replication=1",
        "-e", "HDFS-SITE.XML_dfs.permissions.enabled=false",
        "-e", "HDFS-SITE.XML_dfs.webhdfs.enabled=true",
        "-e", "HDFS-SITE.XML_dfs.namenode.datanode.registration.ip-hostname-check=false",
        image,
        "hdfs", "namenode",
    ])

    print(f"Namenode started. Container: {name}")


def start_datanode(
    image: str,
    name: str,
    namenode_url: str,
    data_dir: str,
    host: str | None,
    datanode_port: int,
    datanode_http_port: int,
    datanode_ipc_port: int,
) -> None:
    """Start an HDFS datanode."""
    print("Starting HDFS datanode...")
    print(f"  Image: {image}")
    print(f"  Namenode: {namenode_url}")
    print(f"  Data dir: {data_dir}")
    print(f"  Ports: data={datanode_port}, http={datanode_http_port}, ipc={datanode_ipc_port}")

    # Clean up existing data to avoid cluster ID conflicts
    clean_data_dir(data_dir)

    # Create data directory with proper permissions for hadoop user
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir])

    # Extract namenode host from URL for add-host
    # URL format: hdfs://host:port
    namenode_host = namenode_url.replace("hdfs://", "").split(":")[0]
    local_host = host or get_host_ip()

    run([
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-v", f"{data_dir}:/opt/hadoop/data:rw",
        "-e", "HADOOP_HOME=/opt/hadoop",
        # Core-site.xml settings
        "-e", f"CORE-SITE.XML_fs.defaultFS={namenode_url}",
        # HDFS-site.xml settings
        "-e", "HDFS-SITE.XML_dfs.datanode.data.dir=/opt/hadoop/data/datanode",
        "-e", "HDFS-SITE.XML_dfs.replication=1",
        "-e", "HDFS-SITE.XML_dfs.permissions.enabled=false",
        "-e", f"HDFS-SITE.XML_dfs.datanode.hostname={local_host}",
        "-e", f"HDFS-SITE.XML_dfs.datanode.address={local_host}:{datanode_port}",
        "-e", f"HDFS-SITE.XML_dfs.datanode.http.address={local_host}:{datanode_http_port}",
        "-e", f"HDFS-SITE.XML_dfs.datanode.ipc.address={local_host}:{datanode_ipc_port}",
        image,
        "hdfs", "datanode",
    ])

    print(f"Datanode started. Container: {name}")


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


def logs(name: str) -> None:
    """Show container logs."""
    run(["docker", "logs", "-f", name])


def exec_cmd(name: str, cmd_args: list[str]) -> None:
    """Execute a command inside a running container."""
    run(["docker", "exec", name] + cmd_args)


def client_shell(
    image: str,
    namenode_url: str,
) -> None:
    """Start an interactive HDFS client shell."""
    print(f"Starting HDFS client shell (namenode: {namenode_url})...")

    run([
        "docker", "run", "--rm", "-it",
        "--network", "host",
        "-e", f"CORE-SITE.XML_fs.defaultFS={namenode_url}",
        "-e", "HDFS-SITE.XML_dfs.client.use.datanode.hostname=true",
        image,
        "bash",
    ])


def hdfs_cmd(
    image: str,
    namenode_url: str,
    hdfs_args: list[str],
) -> None:
    """Run an HDFS command."""
    run([
        "docker", "run", "--rm",
        "--network", "host",
        "-e", f"CORE-SITE.XML_fs.defaultFS={namenode_url}",
        "-e", "HDFS-SITE.XML_dfs.client.use.datanode.hostname=true",
        image,
        "hdfs", "dfs",
    ] + hdfs_args)


def main() -> int:
    # Handle -- separator for cmd action
    hdfs_cmd_args: list[str] = []
    argv = sys.argv[1:]
    if "--" in argv:
        idx = argv.index("--")
        hdfs_cmd_args = argv[idx + 1:]
        argv = argv[:idx]

    parser = argparse.ArgumentParser(
        description="Set up HDFS cluster nodes using Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pull required images
  %(prog)s init

  # Start namenode on this machine
  %(prog)s start --role namenode --host 10.0.0.1

  # Start datanode connecting to namenode
  %(prog)s start --role datanode --namenode hdfs://10.0.0.1:9000

  # Run HDFS commands (via new container)
  %(prog)s cmd --namenode hdfs://10.0.0.4:9000 -- -ls /
  %(prog)s cmd --namenode hdfs://10.0.0.4:9000 -- -mkdir /test

  # Execute commands in running container (for file access)
  %(prog)s exec --role namenode -- hdfs dfs -put /opt/hadoop/data/myfile.dat /bench/
  %(prog)s exec --role namenode -- ls /opt/hadoop/data

  # Start interactive shell
  %(prog)s shell --namenode hdfs://10.0.0.4:9000

  # Stop/status/logs
  %(prog)s stop --role namenode
  %(prog)s status --role datanode
  %(prog)s logs --role namenode
""",
    )

    parser.add_argument(
        "action",
        choices=["init", "start", "stop", "status", "logs", "cmd", "shell", "exec"],
        help="Action to perform",
    )
    parser.add_argument(
        "--role",
        choices=["namenode", "datanode"],
        help="Node role (required for start/stop/status/logs)",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        help="Container name (default: hdfs-<role>)",
    )

    # Namenode options
    parser.add_argument(
        "--host",
        help="Host IP (default: auto-detect)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_NAMENODE_PORT,
        help=f"Namenode RPC port (default: {DEFAULT_NAMENODE_PORT})",
    )
    parser.add_argument(
        "--webui-port",
        type=int,
        default=DEFAULT_WEBUI_PORT,
        help=f"Namenode Web UI port (default: {DEFAULT_WEBUI_PORT})",
    )
    parser.add_argument(
        "--data-dir",
        default="/tmp/hdfs-data",
        help="Local directory for HDFS data (default: /tmp/hdfs-data)",
    )

    # Datanode/client options
    parser.add_argument(
        "--namenode",
        help="Namenode URL (required for datanode/cmd/shell, e.g., hdfs://10.0.0.1:9000)",
    )
    parser.add_argument(
        "--datanode-port",
        type=int,
        default=DEFAULT_DATANODE_PORT,
        help=f"Datanode data transfer port (default: {DEFAULT_DATANODE_PORT})",
    )
    parser.add_argument(
        "--datanode-http-port",
        type=int,
        default=DEFAULT_DATANODE_HTTP_PORT,
        help=f"Datanode HTTP port (default: {DEFAULT_DATANODE_HTTP_PORT})",
    )
    parser.add_argument(
        "--datanode-ipc-port",
        type=int,
        default=DEFAULT_DATANODE_IPC_PORT,
        help=f"Datanode IPC port (default: {DEFAULT_DATANODE_IPC_PORT})",
    )

    args = parser.parse_args(argv)

    # Handle init (no role required)
    if args.action == "init":
        init(args.image)
        return 0

    # Handle cmd and shell (no role required)
    if args.action == "cmd":
        if not args.namenode:
            parser.error("--namenode is required for cmd")
        hdfs_cmd(args.image, args.namenode, hdfs_cmd_args)
        return 0

    if args.action == "shell":
        if not args.namenode:
            parser.error("--namenode is required for shell")
        client_shell(args.image, args.namenode)
        return 0

    # Require role for other actions
    if not args.role:
        parser.error("--role is required for start/stop/status/logs/exec")

    # Set default container name
    if not args.name:
        args.name = f"hdfs-{args.role}"

    # Handle exec action
    if args.action == "exec":
        exec_cmd(args.name, hdfs_cmd_args)
        return 0

    # Handle actions
    if args.action == "start":
        if args.role == "namenode":
            host = args.host or get_host_ip()
            start_namenode(
                args.image, args.name, host, args.port, args.webui_port, args.data_dir
            )
        else:
            if not args.namenode:
                parser.error("--namenode is required for datanode")
            start_datanode(
                args.image,
                args.name,
                args.namenode,
                args.data_dir,
                args.host,
                args.datanode_port,
                args.datanode_http_port,
                args.datanode_ipc_port,
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
