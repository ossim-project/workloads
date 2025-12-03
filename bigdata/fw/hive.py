#!/usr/bin/env python3
"""Set up Hive cluster nodes using official Apache Hive Docker images."""

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_IMAGE = "apache/hive:4.0.1"


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


def start_metastore(
    image: str,
    name: str,
    host: str,
    port: int,
    hdfs_url: str | None,
    data_dir: str,
    db_driver: str | None,
    db_url: str | None,
    db_user: str | None,
    db_password: str | None,
) -> None:
    """Start Hive Metastore service."""
    print("Starting Hive Metastore...")
    print(f"  Image: {image}")
    print(f"  Thrift URI: thrift://{host}:{port}")
    print(f"  Data dir: {data_dir}")

    # Create data directory for Derby metastore
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir])

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-v", f"{data_dir}:/opt/hive/data:rw",
        "-e", "SERVICE_NAME=metastore",
    ]

    if hdfs_url:
        print(f"  HDFS: {hdfs_url}")

    if db_driver and db_driver != "derby":
        print(f"  Database: {db_driver}")
        cmd.extend(["-e", f"DB_DRIVER={db_driver}"])

        service_opts = []
        if db_url:
            service_opts.append(f"-Djavax.jdo.option.ConnectionURL={db_url}")
        if db_user:
            service_opts.append(f"-Djavax.jdo.option.ConnectionUserName={db_user}")
        if db_password:
            service_opts.append(f"-Djavax.jdo.option.ConnectionPassword={db_password}")

        if service_opts:
            cmd.extend(["-e", f"SERVICE_OPTS={' '.join(service_opts)}"])
    else:
        print("  Database: derby (embedded)")
        # Use local data directory for Derby
        cmd.extend([
            "-e", "SERVICE_OPTS=-Djavax.jdo.option.ConnectionURL=jdbc:derby:/opt/hive/data/metastore_db;create=true",
        ])

    # Configure HDFS as warehouse location
    if hdfs_url:
        cmd.extend([
            "-e", f"HIVE_SITE_CONF_hive_metastore_warehouse_dir={hdfs_url}/user/hive/warehouse",
            "-e", f"CORE_SITE_CONF_fs_defaultFS={hdfs_url}",
        ])

    cmd.append(image)

    run(cmd)
    print(f"Metastore started. Container: {name}")


def start_hiveserver2(
    image: str,
    name: str,
    host: str,
    port: int,
    webui_port: int,
    metastore_uri: str | None,
    hdfs_url: str | None,
    data_dir: str,
) -> None:
    """Start HiveServer2 service."""
    print("Starting HiveServer2...")
    print(f"  Image: {image}")
    print(f"  JDBC URL: jdbc:hive2://{host}:{port}")
    print(f"  Web UI: http://{host}:{webui_port}")

    # Create data directory
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir])

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-v", f"{data_dir}:/opt/hive/data:rw",
        "-e", "SERVICE_NAME=hiveserver2",
        "-e", "HIVE_SITE_CONF_hive_server2_authentication=NONE",
    ]

    if hdfs_url:
        cmd.extend([
            "-e", f"HIVE_SITE_CONF_hive_metastore_warehouse_dir={hdfs_url}/user/hive/warehouse",
            "-e", f"CORE_SITE_CONF_fs_defaultFS={hdfs_url}",
        ])
        print(f"  HDFS: {hdfs_url}")

    if metastore_uri:
        cmd.extend([
            "-e", f"HIVE_SITE_CONF_hive_metastore_uris={metastore_uri}",
            "-e", "IS_RESUME=true",
        ])
        print(f"  Metastore: {metastore_uri}")
    else:
        # Standalone mode with embedded Derby metastore
        print("  Metastore: embedded (derby)")
        cmd.extend([
            "-e", "SERVICE_OPTS=-Djavax.jdo.option.ConnectionURL=jdbc:derby:/opt/hive/data/metastore_db;create=true",
        ])

    cmd.append(image)

    run(cmd)
    print(f"HiveServer2 started. Container: {name}")


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


def init(image: str) -> None:
    """Pull required Docker images."""
    print("Pulling required Docker images...")
    run(["docker", "pull", image])
    print("Init complete.")


def exec_cmd(name: str, cmd_args: list[str]) -> None:
    """Execute a command inside a running container."""
    run(["docker", "exec", name] + cmd_args)


def beeline_cmd(
    image: str,
    hiveserver2: str,
    beeline_args: list[str],
) -> None:
    """Run a beeline command."""
    # Parse host and port
    if ":" in hiveserver2:
        hs2_host, hs2_port = hiveserver2.rsplit(":", 1)
    else:
        hs2_host = hiveserver2
        hs2_port = "10000"

    jdbc_url = f"jdbc:hive2://{hs2_host}:{hs2_port}/default"

    # Build docker command
    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "host",
    ]

    # Check if -f is used with a local file and mount it
    processed_args = []
    i = 0
    while i < len(beeline_args):
        if beeline_args[i] == "-f" and i + 1 < len(beeline_args):
            local_path = beeline_args[i + 1]
            container_path = f"/app/{Path(local_path).name}"
            docker_cmd.extend(["-v", f"{local_path}:{container_path}:ro"])
            processed_args.extend(["-f", container_path])
            i += 2
        else:
            processed_args.append(beeline_args[i])
            i += 1

    docker_cmd.extend([
        "--entrypoint", "/opt/hive/bin/beeline",
        image,
        "-u", jdbc_url,
    ])
    docker_cmd.extend(processed_args)

    run(docker_cmd)


def shell(
    image: str,
    hiveserver2: str,
) -> None:
    """Start an interactive beeline shell."""
    # Parse host and port
    if ":" in hiveserver2:
        hs2_host, hs2_port = hiveserver2.rsplit(":", 1)
    else:
        hs2_host = hiveserver2
        hs2_port = "10000"

    jdbc_url = f"jdbc:hive2://{hs2_host}:{hs2_port}/default"

    print(f"Starting beeline shell (HiveServer2: {hiveserver2})...")
    run([
        "docker", "run", "--rm", "-it",
        "--network", "host",
        "--entrypoint", "/opt/hive/bin/beeline",
        image,
        "-u", jdbc_url,
    ])


def main() -> int:
    # Handle -- separator for cmd action
    extra_args: list[str] = []
    argv = sys.argv[1:]
    if "--" in argv:
        idx = argv.index("--")
        extra_args = argv[idx + 1:]
        argv = argv[:idx]

    parser = argparse.ArgumentParser(
        description="Set up Hive cluster nodes using Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pull required images
  %(prog)s init

  # Start metastore with embedded Derby (for testing)
  %(prog)s start --role metastore

  # Start metastore with HDFS warehouse
  %(prog)s start --role metastore --host 10.0.0.1 --hdfs hdfs://10.0.0.1:9000

  # Start metastore with PostgreSQL
  %(prog)s start --role metastore --db-driver postgres \\
      --db-url jdbc:postgresql://localhost:5432/metastore \\
      --db-user hive --db-password hive

  # Start HiveServer2 with embedded metastore
  %(prog)s start --role hiveserver2

  # Start HiveServer2 connecting to remote metastore
  %(prog)s start --role hiveserver2 --metastore thrift://10.0.0.1:9083 --hdfs hdfs://10.0.0.1:9000

  # Connect via beeline
  %(prog)s shell --hiveserver2 10.0.0.1:10000
  %(prog)s cmd --hiveserver2 10.0.0.1:10000 -- -e "SHOW DATABASES;"

  # Execute commands in running container
  %(prog)s exec --role hiveserver2 -- beeline -u jdbc:hive2://localhost:10000/default

  # Stop/status/logs
  %(prog)s stop --role metastore
  %(prog)s status --role hiveserver2
  %(prog)s logs --role metastore
""",
    )

    parser.add_argument(
        "action",
        choices=["init", "start", "stop", "status", "logs", "cmd", "shell", "exec"],
        help="Action to perform",
    )
    parser.add_argument(
        "--role",
        choices=["metastore", "hiveserver2"],
        help="Node role (required for start/stop/status/logs/exec)",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        help="Container name (default: hive-metastore or hive-server2)",
    )

    # Common options
    parser.add_argument(
        "--host",
        help="Host IP (default: auto-detect)",
    )
    parser.add_argument(
        "--hdfs",
        help="HDFS namenode URL for warehouse (e.g., hdfs://10.0.0.1:9000)",
    )
    parser.add_argument(
        "--data-dir",
        default="/tmp/hive-data",
        help="Local directory for Hive data (default: /tmp/hive-data)",
    )

    # Metastore options
    parser.add_argument(
        "--metastore-port",
        type=int,
        default=9083,
        help="Metastore thrift port (default: 9083)",
    )
    parser.add_argument(
        "--db-driver",
        choices=["postgres", "mysql", "derby"],
        help="Metastore database driver (default: derby)",
    )
    parser.add_argument(
        "--db-url",
        help="Metastore database JDBC URL",
    )
    parser.add_argument(
        "--db-user",
        help="Metastore database user",
    )
    parser.add_argument(
        "--db-password",
        help="Metastore database password",
    )

    # HiveServer2 options
    parser.add_argument(
        "--port",
        type=int,
        default=10000,
        help="HiveServer2 port (default: 10000)",
    )
    parser.add_argument(
        "--webui-port",
        type=int,
        default=10002,
        help="HiveServer2 Web UI port (default: 10002)",
    )
    parser.add_argument(
        "--metastore",
        help="Metastore URI for HiveServer2 (e.g., thrift://10.0.0.1:9083)",
    )

    # Client options
    parser.add_argument(
        "--hiveserver2",
        help="HiveServer2 host:port (required for cmd/shell, e.g., 10.0.0.1:10000)",
    )

    args = parser.parse_args(argv)

    # Handle init (no role required)
    if args.action == "init":
        init(args.image)
        return 0

    # Handle cmd and shell (no role required)
    if args.action == "cmd":
        if not args.hiveserver2:
            parser.error("--hiveserver2 is required for cmd")
        beeline_cmd(args.image, args.hiveserver2, extra_args)
        return 0

    if args.action == "shell":
        if not args.hiveserver2:
            parser.error("--hiveserver2 is required for shell")
        shell(args.image, args.hiveserver2)
        return 0

    # Require role for other actions
    if not args.role:
        parser.error("--role is required for start/stop/status/logs/exec")

    # Set default container name
    if not args.name:
        if args.role == "metastore":
            args.name = "hive-metastore"
        else:
            args.name = "hive-server2"

    # Handle exec action
    if args.action == "exec":
        exec_cmd(args.name, extra_args)
        return 0

    # Handle actions
    if args.action == "start":
        host = args.host or get_host_ip()

        if args.role == "metastore":
            start_metastore(
                args.image,
                args.name,
                host,
                args.metastore_port,
                args.hdfs,
                args.data_dir,
                args.db_driver,
                args.db_url,
                args.db_user,
                args.db_password,
            )
        else:
            start_hiveserver2(
                args.image,
                args.name,
                host,
                args.port,
                args.webui_port,
                args.metastore,
                args.hdfs,
                args.data_dir,
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
