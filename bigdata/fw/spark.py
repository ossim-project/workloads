#!/usr/bin/env python3
"""Set up Spark cluster nodes using official Apache Spark Docker images."""

import argparse
import subprocess
import sys

DEFAULT_IMAGE = "spark:3.5.3-scala2.12-java17-python3-ubuntu"


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
    """Pull required Docker images."""
    print("Pulling required Docker images...")
    run(["docker", "pull", image])
    print("Init complete.")


def start_master(
    image: str,
    name: str,
    host: str,
    port: int,
    webui_port: int,
) -> None:
    """Start a Spark master node."""
    print("Starting Spark master...")
    print(f"  Image: {image}")
    print(f"  Master URL: spark://{host}:{port}")
    print(f"  Web UI: http://{host}:{webui_port}")

    run([
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-e", f"SPARK_MASTER_HOST={host}",
        "-e", f"SPARK_MASTER_PORT={port}",
        "-e", f"SPARK_MASTER_WEBUI_PORT={webui_port}",
        "-e", f"SPARK_LOCAL_IP={host}",
        image,
        "/opt/spark/bin/spark-class",
        "org.apache.spark.deploy.master.Master",
    ])

    print(f"Master started. Container: {name}")


def start_worker(
    image: str,
    name: str,
    master_url: str,
    cores: int,
    memory: str,
    local_ip: str = None,
) -> None:
    """Start a Spark worker node."""
    print("Starting Spark worker...")
    print(f"  Image: {image}")
    print(f"  Master: {master_url}")
    print(f"  Cores: {cores}")
    print(f"  Memory: {memory}")

    cmd = [
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-e", f"SPARK_WORKER_CORES={cores}",
        "-e", f"SPARK_WORKER_MEMORY={memory}",
    ]
    if local_ip:
        cmd.extend(["-e", f"SPARK_LOCAL_IP={local_ip}"])
    cmd.extend([
        image,
        "/opt/spark/bin/spark-class",
        "org.apache.spark.deploy.worker.Worker",
        master_url,
    ])
    run(cmd)

    print(f"Worker started. Container: {name}")


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


def submit(
    image: str,
    master: str,
    script_path: str,
    executor_memory: str,
    executor_cores: int,
) -> None:
    """Submit a PySpark script to the cluster."""
    print("Submitting Spark application...")
    print(f"  Master: {master}")
    print(f"  Script: {script_path}")

    run([
        "docker", "run", "--rm",
        "--network", "host",
        "-v", f"{script_path}:/app/script.py:ro",
        image,
        "/opt/spark/bin/spark-submit",
        "--master", master,
        "--executor-memory", executor_memory,
        "--executor-cores", str(executor_cores),
        "/app/script.py",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up Spark cluster nodes using Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Pull required images
  %(prog)s init

  # Start master on this machine
  %(prog)s start --role master

  # Start master with specific IP
  %(prog)s start --role master --host 10.0.0.1

  # Start worker connecting to master
  %(prog)s start --role worker --master spark://10.0.0.1:7077

  # Start worker with custom resources
  %(prog)s start --role worker --master spark://10.0.0.1:7077 --cores 4 --memory 4g

  # Submit a PySpark script
  %(prog)s submit --master spark://10.0.0.1:7077 --script /path/to/script.py

  # Stop/status/logs
  %(prog)s stop --role master
  %(prog)s status --role worker
  %(prog)s logs --role master
""",
    )

    parser.add_argument(
        "action",
        choices=["init", "start", "stop", "status", "logs", "submit"],
        help="Action to perform",
    )
    parser.add_argument(
        "--role",
        choices=["master", "worker"],
        help="Node role (required for start/stop/status/logs)",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        help="Container name (default: spark-<role>)",
    )

    # Master options
    parser.add_argument(
        "--host",
        help="Master host IP (default: auto-detect)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7077,
        help="Master port (default: 7077)",
    )
    parser.add_argument(
        "--webui-port",
        type=int,
        default=8080,
        help="Master Web UI port (default: 8080)",
    )

    # Worker options
    parser.add_argument(
        "--master",
        help="Master URL (required for worker, e.g., spark://10.0.0.1:7077)",
    )
    parser.add_argument(
        "--local-ip",
        help="Worker's local IP address (default: auto-detect)",
    )
    parser.add_argument(
        "--cores",
        type=int,
        default=1,
        help="Worker cores (default: 1)",
    )
    parser.add_argument(
        "--memory",
        default="1g",
        help="Worker memory (default: 1g)",
    )

    # Submit options
    parser.add_argument(
        "--script",
        help="PySpark script path (required for submit)",
    )
    parser.add_argument(
        "--executor-memory",
        default="1g",
        help="Executor memory for submit (default: 1g)",
    )
    parser.add_argument(
        "--executor-cores",
        type=int,
        default=1,
        help="Executor cores for submit (default: 1)",
    )

    args = parser.parse_args()

    # Handle init (no role required)
    if args.action == "init":
        init(args.image)
        return 0

    # Handle submit (no role required)
    if args.action == "submit":
        if not args.master:
            parser.error("--master is required for submit")
        if not args.script:
            parser.error("--script is required for submit")
        submit(args.image, args.master, args.script, args.executor_memory, args.executor_cores)
        return 0

    # Require role for other actions
    if not args.role:
        parser.error("--role is required for start/stop/status/logs")

    # Set default container name
    if not args.name:
        args.name = f"spark-{args.role}"

    # Handle actions
    if args.action == "start":
        if args.role == "master":
            host = args.host or get_host_ip()
            start_master(args.image, args.name, host, args.port, args.webui_port)
        else:
            if not args.master:
                parser.error("--master is required for worker")
            # Use provided local IP or auto-detect worker's own IP
            local_ip = args.local_ip or get_host_ip()
            start_worker(args.image, args.name, args.master, args.cores, args.memory, local_ip)

    elif args.action == "stop":
        stop(args.name)

    elif args.action == "status":
        status(args.name)

    elif args.action == "logs":
        logs(args.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
