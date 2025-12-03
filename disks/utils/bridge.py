#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command with sudo."""
    return subprocess.run(cmd, check=check)


def setup(bridge_if: str, bridge_cidr: str, prefix: str) -> None:
    """Set up a bridge interface."""
    # Remove existing bridge if present
    run(["ip", "link", "del", bridge_if], check=False)

    # Create and configure bridge
    run(["ip", "link", "add", "name", bridge_if, "type", "bridge"])
    run(["ip", "addr", "add", bridge_cidr, "brd", "+", "dev", bridge_if])
    run(["ip", "link", "set", bridge_if, "up"])

    # Configure QEMU bridge permissions
    qemu_conf_dir = os.path.join(prefix, "etc/qemu")
    run(["mkdir", "-p", qemu_conf_dir])

    bridge_conf = os.path.join(qemu_conf_dir, "bridge.conf")
    with subprocess.Popen(
        ["sudo", "tee", "-a", bridge_conf],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
    ) as proc:
        proc.communicate(f"allow {bridge_if}\n".encode())


def cleanup(bridge_if: str) -> None:
    """Clean up a bridge interface."""
    run(["ip", "route", "flush", "dev", bridge_if], check=False)
    run(["ip", "link", "del", bridge_if], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Linux bridge interfaces")
    parser.add_argument(
        "action",
        choices=["setup", "cleanup"],
        help="Action to perform",
    )
    parser.add_argument(
        "--bridge-if",
        required=True,
        help="Bridge interface name (e.g., br-ossim0)",
    )
    parser.add_argument(
        "--bridge-cidr",
        help="Bridge CIDR address (e.g., 10.10.10.1/24), required for setup",
    )
    parser.add_argument(
        "--prefix",
        default="install/",
        help="Ossim prefix directory (default: install/)",
    )

    args = parser.parse_args()

    if args.action == "setup":
        if not args.bridge_cidr:
            parser.error("--bridge-cidr is required for setup")
        setup(args.bridge_if, args.bridge_cidr, args.prefix)
    elif args.action == "cleanup":
        cleanup(args.bridge_if)

    return 0


if __name__ == "__main__":
    sys.exit(main())
