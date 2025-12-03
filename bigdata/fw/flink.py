#!/usr/bin/env python3
"""Set up Flink cluster nodes using official Apache Flink Docker images."""

import argparse
import subprocess
import sys

DEFAULT_IMAGE = "flink:1.18-java11"


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


def start_jobmanager(
    image: str,
    name: str,
    host: str,
    rpc_port: int,
    webui_port: int,
) -> None:
    """Start Flink JobManager."""
    print("Starting Flink JobManager...")
    print(f"  Image: {image}")
    print(f"  RPC Address: {host}:{rpc_port}")
    print(f"  Web UI: http://{host}:{webui_port}")

    flink_properties = (
        f"jobmanager.rpc.address: {host}\n"
        f"jobmanager.rpc.port: {rpc_port}\n"
        f"rest.address: {host}\n"
        f"rest.port: {webui_port}"
    )

    run([
        "docker", "run", "-d",
        "--name", name,
        "--hostname", "jobmanager",
        "--network", "host",
        "-e", f"FLINK_PROPERTIES={flink_properties}",
        image,
        "jobmanager",
    ])

    print(f"JobManager started. Container: {name}")


def start_taskmanager(
    image: str,
    name: str,
    jobmanager: str,
    slots: int,
    memory: str,
    local_ip: str,
) -> None:
    """Start Flink TaskManager."""
    print("Starting Flink TaskManager...")
    print(f"  Image: {image}")
    print(f"  JobManager: {jobmanager}")
    print(f"  Local IP: {local_ip}")
    print(f"  Task Slots: {slots}")
    print(f"  Memory: {memory}")

    # Parse jobmanager address
    if ":" in jobmanager:
        jm_host, jm_port = jobmanager.rsplit(":", 1)
    else:
        jm_host = jobmanager
        jm_port = "6123"

    flink_properties = (
        f"jobmanager.rpc.address: {jm_host}\n"
        f"jobmanager.rpc.port: {jm_port}\n"
        f"taskmanager.host: {local_ip}\n"
        f"taskmanager.numberOfTaskSlots: {slots}\n"
        f"taskmanager.memory.process.size: {memory}"
    )

    run([
        "docker", "run", "-d",
        "--name", name,
        "--network", "host",
        "-e", f"FLINK_PROPERTIES={flink_properties}",
        image,
        "taskmanager",
    ])

    print(f"TaskManager started. Container: {name}")


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


def submit(
    jar_path: str,
    jobmanager: str,
    parallelism: int,
    args: list[str] | None = None,
    class_name: str | None = None,
    container: str = "flink-jobmanager",
) -> subprocess.CompletedProcess:
    """Submit a Flink job JAR to the cluster.

    Args:
        jar_path: Path to the JAR file (will be copied to container)
        jobmanager: JobManager address (host:port)
        parallelism: Job parallelism
        args: Additional arguments to pass to the job
        class_name: Main class name (optional, if not in manifest)
        container: JobManager container name
    """
    from pathlib import Path
    import shutil
    import tempfile

    jar_file = Path(jar_path)
    if not jar_file.exists():
        print(f"Error: JAR file not found: {jar_path}")
        return subprocess.CompletedProcess([], 1)

    print(f"Submitting Flink job...")
    print(f"  JAR: {jar_path}")
    print(f"  JobManager: {jobmanager}")
    print(f"  Parallelism: {parallelism}")
    if class_name:
        print(f"  Class: {class_name}")

    # Copy JAR to container
    container_jar_path = f"/tmp/{jar_file.name}"
    run(["docker", "cp", str(jar_path), f"{container}:{container_jar_path}"])

    # Build flink run command
    flink_cmd = [
        "/opt/flink/bin/flink", "run",
        "-m", jobmanager,
        "-p", str(parallelism),
    ]
    if class_name:
        flink_cmd.extend(["-c", class_name])
    flink_cmd.append(container_jar_path)
    if args:
        flink_cmd.extend(args)

    # Execute in container
    result = run(["docker", "exec", container] + flink_cmd, check=False)

    if result.returncode == 0:
        print("Job submitted successfully")
    else:
        print(f"Job submission failed with exit code {result.returncode}")

    return result


def run_sql(
    sql: str,
    jobmanager: str,
    container: str = "flink-jobmanager",
) -> subprocess.CompletedProcess:
    """Run a Flink SQL statement.

    Args:
        sql: SQL statement to execute
        jobmanager: JobManager address (host:port)
        container: JobManager container name
    """
    print(f"Running Flink SQL...")
    print(f"  JobManager: {jobmanager}")
    print(f"  SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")

    # Use Flink SQL CLI
    result = run([
        "docker", "exec", container,
        "/opt/flink/bin/sql-client.sh",
        "-e", sql,
    ], check=False)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set up Flink cluster nodes using Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize: pull Docker image
  %(prog)s init

  # Start JobManager
  %(prog)s start --role jobmanager
  %(prog)s start --role jobmanager --host 10.0.0.1

  # Start TaskManager(s)
  %(prog)s start --role taskmanager --jobmanager 10.0.0.1:6123
  %(prog)s start --role taskmanager --jobmanager 10.0.0.1:6123 --slots 4 --memory 4g
  %(prog)s start --role taskmanager --jobmanager 10.0.0.1:6123 --name flink-tm-2
  %(prog)s start --role taskmanager --jobmanager 10.0.0.1:6123 --local-ip 10.0.0.2

  # Submit a job
  %(prog)s submit --jar /path/to/job.jar --jobmanager 10.0.0.1:6123
  %(prog)s submit --jar /path/to/job.jar --class com.example.MyJob --parallelism 8

  # Stop/status/logs
  %(prog)s stop --role jobmanager
  %(prog)s status --role taskmanager
  %(prog)s logs --role jobmanager
""",
    )

    parser.add_argument(
        "action",
        choices=["init", "start", "stop", "status", "logs", "submit"],
        help="Action to perform",
    )
    parser.add_argument(
        "--role",
        choices=["jobmanager", "taskmanager"],
        help="Node role (required for start/stop/status/logs)",
    )
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE,
        help=f"Docker image (default: {DEFAULT_IMAGE})",
    )
    parser.add_argument(
        "--name",
        help="Container name (default: flink-jobmanager or flink-taskmanager)",
    )

    # JobManager options
    parser.add_argument(
        "--host",
        help="JobManager host IP (default: auto-detect)",
    )
    parser.add_argument(
        "--rpc-port",
        type=int,
        default=6123,
        help="JobManager RPC port (default: 6123)",
    )
    parser.add_argument(
        "--webui-port",
        type=int,
        default=8081,
        help="JobManager Web UI port (default: 8081)",
    )

    # TaskManager options
    parser.add_argument(
        "--jobmanager",
        help="JobManager address (required for taskmanager, e.g., 10.0.0.1:6123)",
    )
    parser.add_argument(
        "--local-ip",
        help="TaskManager's local IP address (default: auto-detect)",
    )
    parser.add_argument(
        "--slots",
        type=int,
        default=2,
        help="Number of task slots (default: 2)",
    )
    parser.add_argument(
        "--memory",
        default="2g",
        help="TaskManager memory (default: 2g)",
    )

    # Submit options
    parser.add_argument(
        "--jar",
        help="JAR file path (required for submit)",
    )
    parser.add_argument(
        "--class",
        dest="class_name",
        help="Main class name for job submission",
    )
    parser.add_argument(
        "--parallelism",
        type=int,
        default=4,
        help="Job parallelism (default: 4)",
    )
    parser.add_argument(
        "--job-args",
        nargs="*",
        help="Additional arguments to pass to the job",
    )

    args = parser.parse_args()

    # Handle init (no role required)
    if args.action == "init":
        init(args.image)
        return 0

    # Handle submit (no role required)
    if args.action == "submit":
        if not args.jar:
            parser.error("--jar is required for submit")
        jobmanager = args.jobmanager or f"{get_host_ip()}:6123"
        result = submit(
            args.jar,
            jobmanager,
            args.parallelism,
            args.job_args,
            args.class_name,
        )
        return result.returncode

    # Require role for other actions
    if not args.role:
        parser.error("--role is required for start/stop/status/logs")

    # Set default container name
    if not args.name:
        args.name = f"flink-{args.role}"

    # Handle actions
    if args.action == "start":
        if args.role == "jobmanager":
            host = args.host or get_host_ip()
            start_jobmanager(args.image, args.name, host, args.rpc_port, args.webui_port)
        else:
            if not args.jobmanager:
                parser.error("--jobmanager is required for taskmanager")
            # Use provided local IP or auto-detect TaskManager's own IP
            local_ip = args.local_ip or get_host_ip()
            start_taskmanager(args.image, args.name, args.jobmanager, args.slots, args.memory, local_ip)

    elif args.action == "stop":
        stop(args.name)

    elif args.action == "status":
        status(args.name)

    elif args.action == "logs":
        logs(args.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())
