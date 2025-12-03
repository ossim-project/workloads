#!/usr/bin/env python3
import argparse
import subprocess
import sys


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command with sudo."""
    return subprocess.run(cmd, check=check)


def sysctl(key: str, value: str) -> None:
    """Set a sysctl value."""
    run(["sysctl", f"{key}={value}"])


def iptables(table: str, action: str, rule: list[str], check: bool = True) -> None:
    """Add or delete an iptables rule."""
    run(["iptables", "-t", table, action] + rule, check=check)


def setup(bridge_if: str, internet_if: str) -> None:
    """Set up NAT rules for a bridge interface."""
    # Enable IP forwarding
    sysctl("net.ipv4.ip_forward", "1")

    # Filter rules
    filter_rules = [
        ["FORWARD", "-i", bridge_if, "-o", internet_if, "-j", "ACCEPT"],
        [
            "FORWARD",
            "-i",
            internet_if,
            "-o",
            bridge_if,
            "-m",
            "state",
            "--state",
            "RELATED,ESTABLISHED",
            "-j",
            "ACCEPT",
        ],
    ]

    # NAT rules
    nat_rules = [
        ["POSTROUTING", "-o", internet_if, "-j", "MASQUERADE"],
    ]

    for rule in filter_rules:
        iptables("filter", "-I", rule)

    for rule in nat_rules:
        iptables("nat", "-I", rule)


def cleanup(bridge_if: str, internet_if: str) -> None:
    """Clean up NAT rules for a bridge interface."""
    # Filter rules
    filter_rules = [
        ["FORWARD", "-i", bridge_if, "-o", internet_if, "-j", "ACCEPT"],
        [
            "FORWARD",
            "-i",
            internet_if,
            "-o",
            bridge_if,
            "-m",
            "state",
            "--state",
            "RELATED,ESTABLISHED",
            "-j",
            "ACCEPT",
        ],
    ]

    # NAT rules
    nat_rules = [
        ["POSTROUTING", "-o", internet_if, "-j", "MASQUERADE"],
    ]

    for rule in filter_rules:
        iptables("filter", "-D", rule, check=False)

    for rule in nat_rules:
        iptables("nat", "-D", rule, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage NAT and IP forwarding rules")
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
        "--internet-if",
        required=True,
        help="Internet-facing interface name (e.g., eno1)",
    )

    args = parser.parse_args()

    if args.action == "setup":
        setup(args.bridge_if, args.internet_if)
    elif args.action == "cleanup":
        cleanup(args.bridge_if, args.internet_if)

    return 0


if __name__ == "__main__":
    sys.exit(main())
