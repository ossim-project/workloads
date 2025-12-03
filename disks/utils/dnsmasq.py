#!/usr/bin/env python3
"""Set up dnsmasq as a DNS forwarder on bridge interfaces.

This allows QEMU guests to use the bridge gateway IP as their DNS server,
which forwards queries to whatever DNS the host is configured to use.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    return subprocess.run(cmd, check=check)


def get_host_dns_servers() -> list[str]:
    """Get the DNS servers configured on the host via systemd-resolved."""
    try:
        result = subprocess.run(
            ["resolvectl", "status"],
            capture_output=True,
            text=True,
            check=True,
        )
        servers = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("DNS Servers:"):
                # Extract servers from "DNS Servers: x.x.x.x y.y.y.y"
                parts = line.split(":", 1)[1].strip().split()
                servers.extend(parts)
            elif line.startswith("Current DNS Server:"):
                # Prefer the current DNS server
                server = line.split(":", 1)[1].strip()
                if server and server not in servers:
                    servers.insert(0, server)
        # Filter out link-local and localhost addresses
        servers = [s for s in servers if not s.startswith("127.") and not s.startswith("fe80")]
        return servers if servers else ["8.8.8.8", "8.8.4.4"]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to /etc/resolv.conf
        try:
            with open("/etc/resolv.conf") as f:
                servers = []
                for line in f:
                    if line.startswith("nameserver"):
                        server = line.split()[1]
                        if not server.startswith("127."):
                            servers.append(server)
                return servers if servers else ["8.8.8.8", "8.8.4.4"]
        except Exception:
            return ["8.8.8.8", "8.8.4.4"]


def setup(bridge_ifs: list[str], conf_dir: Path, pid_dir: Path) -> None:
    """Set up dnsmasq as a DNS forwarder on bridge interfaces."""
    conf_dir.mkdir(parents=True, exist_ok=True)
    pid_dir.mkdir(parents=True, exist_ok=True)

    # Get upstream DNS servers from host
    upstream_servers = get_host_dns_servers()
    print(f"Using upstream DNS servers: {upstream_servers}")

    # Build listen addresses from bridge IPs
    listen_addresses = []
    for bridge_if in bridge_ifs:
        try:
            result = subprocess.run(
                ["ip", "-4", "addr", "show", bridge_if],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                if "inet " in line:
                    # Extract IP from "inet 10.10.10.1/24 ..."
                    ip = line.strip().split()[1].split("/")[0]
                    listen_addresses.append(ip)
        except subprocess.CalledProcessError:
            print(f"Warning: Could not get IP for {bridge_if}", file=sys.stderr)

    if not listen_addresses:
        print("Error: No bridge IPs found", file=sys.stderr)
        sys.exit(1)

    print(f"Listening on: {listen_addresses}")

    # Generate dnsmasq config
    conf_file = conf_dir / "dnsmasq-bridges.conf"
    pid_file = pid_dir / "dnsmasq-bridges.pid"

    config_lines = [
        "# Auto-generated dnsmasq config for QEMU bridge DNS forwarding",
        "port=53",
        "bind-interfaces",
        "no-dhcp-interface=*",  # DNS only, no DHCP
        "no-hosts",  # Don't read /etc/hosts
        "no-resolv",  # Don't read /etc/resolv.conf
    ]

    for addr in listen_addresses:
        config_lines.append(f"listen-address={addr}")

    for server in upstream_servers:
        config_lines.append(f"server={server}")

    conf_file.write_text("\n".join(config_lines) + "\n")
    print(f"Config written to {conf_file}")

    # Stop any existing instance (but don't delete the config we just wrote)
    stop_dnsmasq(pid_dir)

    # Start dnsmasq
    run([
        "dnsmasq",
        f"--conf-file={conf_file}",
        f"--pid-file={pid_file}",
    ])
    print("dnsmasq started")


def stop_dnsmasq(pid_dir: Path) -> None:
    """Stop any running dnsmasq instance."""
    pid_file = pid_dir / "dnsmasq-bridges.pid"

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            run(["kill", str(pid)], check=False)
            print(f"Stopped dnsmasq (pid {pid})")
        except (ValueError, OSError) as e:
            print(f"Warning: Could not stop dnsmasq: {e}", file=sys.stderr)
        pid_file.unlink(missing_ok=True)


def cleanup(conf_dir: Path, pid_dir: Path) -> None:
    """Stop dnsmasq and clean up config files."""
    stop_dnsmasq(pid_dir)

    conf_file = conf_dir / "dnsmasq-bridges.conf"
    if conf_file.exists():
        conf_file.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manage dnsmasq DNS forwarder for QEMU bridges"
    )
    parser.add_argument(
        "action",
        choices=["setup", "cleanup"],
        help="Action to perform",
    )
    parser.add_argument(
        "--bridge-if",
        action="append",
        dest="bridge_ifs",
        help="Bridge interface(s) to listen on (can be specified multiple times)",
    )
    parser.add_argument(
        "--conf-dir",
        type=Path,
        default=Path("/tmp/ossim"),
        help="Directory for config files (default: /tmp/ossim)",
    )
    parser.add_argument(
        "--pid-dir",
        type=Path,
        default=Path("/tmp/ossim"),
        help="Directory for PID file (default: /tmp/ossim)",
    )

    args = parser.parse_args()

    if args.action == "setup":
        if not args.bridge_ifs:
            parser.error("--bridge-if is required for setup")
        setup(args.bridge_ifs, args.conf_dir, args.pid_dir)
    elif args.action == "cleanup":
        cleanup(args.conf_dir, args.pid_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
