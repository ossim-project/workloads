#!/usr/bin/env python3
"""Set up MySQL server using official Docker image."""

import argparse
import subprocess
import sys

DEFAULT_IMAGE = "mysql:8.0"
DEFAULT_PORT = 3306
DEFAULT_ROOT_PASSWORD = "benchmark"
DEFAULT_DATABASE = "tpcc"


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


def init(image: str) -> None:
    """Pull MySQL Docker image."""
    print(f"Pulling MySQL image: {image}")
    run(["docker", "pull", image])
    print("Init complete.")


def start(
    image: str,
    name: str,
    host: str | None = None,
    port: int = DEFAULT_PORT,
    root_password: str = DEFAULT_ROOT_PASSWORD,
    database: str = DEFAULT_DATABASE,
    data_dir: str = "/tmp/mysql-data",
) -> None:
    """Start MySQL server."""
    host = host or get_host_ip()
    print("Starting MySQL server...")
    print(f"  Image: {image}")
    print(f"  Address: {host}:{port}")
    print(f"  Database: {database}")
    print(f"  Data dir: {data_dir}")

    # Create data directory
    run(["mkdir", "-p", data_dir])
    run(["chmod", "777", data_dir], check=False)

    run([
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-v", f"{data_dir}:/var/lib/mysql:rw",
        "-e", f"MYSQL_ROOT_PASSWORD={root_password}",
        "-e", f"MYSQL_DATABASE={database}",
        # Performance tuning for benchmarks
        "-e", "MYSQL_ROOT_HOST=%",
        image,
        "--port", str(port),
        "--bind-address", "0.0.0.0",
        # Optimizations for TPC-C
        "--innodb-buffer-pool-size=1G",
        "--innodb-log-file-size=256M",
        "--innodb-flush-log-at-trx-commit=2",
        "--innodb-flush-method=O_DIRECT",
        "--max-connections=200",
        # Use native password for compatibility with older clients (sysbench)
        "--default-authentication-plugin=mysql_native_password",
        # Enable local infile for bulk data loading (TPC-H)
        "--local-infile=1",
    ])

    print(f"MySQL started. Container: {name}")
    print(f"  Connect: mysql -h {host} -P {port} -u root -p{root_password}")


def stop(name: str) -> None:
    """Stop and remove MySQL container."""
    print(f"Stopping {name}...")
    run(["docker", "stop", name], check=False)
    run(["docker", "rm", name], check=False)
    print("Stopped.")


def status(name: str) -> None:
    """Check MySQL container status."""
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
    """Show MySQL container logs."""
    cmd = ["docker", "logs"]
    if follow:
        cmd.append("-f")
    cmd.append(name)
    run(cmd)


def cmd(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str | None,
    extra_args: list[str],
) -> int:
    """Run mysql client command."""
    mysql_cmd = [
        "docker", "run", "--rm", "-i",
        "--network", "host",
        "mysql:8.0",
        "mysql",
        "-h", host,
        "-P", str(port),
        "-u", user,
        f"-p{password}",
    ]
    if database:
        mysql_cmd.extend(["-D", database])
    mysql_cmd.extend(extra_args)

    result = run(mysql_cmd, check=False)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up MySQL server using Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize: pull Docker image
  %(prog)s init

  # Start MySQL server
  %(prog)s start
  %(prog)s start --host 10.0.0.1 --port 3306

  # Run mysql client
  %(prog)s cmd -- -e "SHOW DATABASES;"
  %(prog)s cmd --database tpcc -- -e "SHOW TABLES;"

  # Stop/status/logs
  %(prog)s stop
  %(prog)s status
  %(prog)s logs
""",
    )

    parser.add_argument(
        "action",
        choices=["init", "start", "stop", "status", "logs", "cmd"],
        help="Action to perform",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        default="mysql",
        help="Container name (default: mysql)",
    )
    parser.add_argument(
        "--host",
        help="Host IP (default: auto-detect)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"MySQL port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--root-password",
        default=DEFAULT_ROOT_PASSWORD,
        help=f"Root password (default: {DEFAULT_ROOT_PASSWORD})",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Database name (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--data-dir",
        default="/tmp/mysql-data",
        help="Data directory (default: /tmp/mysql-data)",
    )
    parser.add_argument(
        "--user",
        default="root",
        help="MySQL user for cmd (default: root)",
    )
    parser.add_argument(
        "extra_args",
        nargs="*",
        help="Extra arguments after -- for cmd action",
    )

    # Parse known args to handle -- separator
    args, extra = parser.parse_known_args()

    # Handle init
    if args.action == "init":
        init(args.image)
        return 0

    # Handle start
    if args.action == "start":
        start(
            args.image,
            args.name,
            args.host,
            args.port,
            args.root_password,
            args.database,
            args.data_dir,
        )
        return 0

    # Handle stop
    if args.action == "stop":
        stop(args.name)
        return 0

    # Handle status
    if args.action == "status":
        status(args.name)
        return 0

    # Handle logs
    if args.action == "logs":
        logs(args.name)
        return 0

    # Handle cmd
    if args.action == "cmd":
        host = args.host or get_host_ip()
        return cmd(
            host,
            args.port,
            args.user,
            args.root_password,
            args.database,
            extra,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
