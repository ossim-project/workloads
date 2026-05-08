"""Shared helpers for emitting structured microbenchmark JSON output.

Captures everything needed to make a result self-describing: clock identity,
host/guest identity, vCPU/memory shape, ossim mode + epoch, git commit, and
host-vs-guest timestamps. The driver records its own host-wall bracket
separately via write_host_bracket().
"""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


def now_ns() -> tuple[int, int]:
    """(CLOCK_REALTIME ns, CLOCK_MONOTONIC ns).

    Inside an ossim guest, CLOCK_REALTIME is currently anchored to host wall-
    clock at boot (persistent-clock paravirtualization is pending), so the
    realtime value is offset from simulation time by a fixed amount. Use
    mono_* fields for any time-progression reasoning.
    """
    return (
        time.clock_gettime_ns(time.CLOCK_REALTIME),
        time.clock_gettime_ns(time.CLOCK_MONOTONIC),
    )


def _read(path: str, default: str = "") -> str:
    try:
        return Path(path).read_text().strip()
    except (FileNotFoundError, PermissionError, OSError):
        return default


def _try(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False,
                              timeout=5).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def collect_metadata() -> dict[str, Any]:
    """Snapshot the runtime environment.

    Cheap to call (sub-millisecond) so we just embed it in every result file.
    Anything missing is recorded as the empty string rather than absent — the
    schema is fixed so post-processing doesn't need defensive .get() chains.
    """
    cpuset = _read("/proc/self/status").splitlines()
    cpus_allowed = ""
    for line in cpuset:
        if line.startswith("Cpus_allowed_list:"):
            cpus_allowed = line.split(":", 1)[1].strip()
            break

    meminfo = _read("/proc/meminfo").splitlines()
    mem_total_kb = 0
    for line in meminfo:
        if line.startswith("MemTotal:"):
            mem_total_kb = int(line.split()[1])
            break

    cpuinfo = _read("/proc/cpuinfo")
    model = ""
    for line in cpuinfo.splitlines():
        if line.startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break

    governor = _read(
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", default="")
    clocksource = _read(
        "/sys/devices/system/clocksource/clocksource0/current_clocksource",
        default="")
    available_clocksources = _read(
        "/sys/devices/system/clocksource/clocksource0/available_clocksource",
        default="")

    return {
        "hostname": socket.gethostname(),
        "uname": platform.uname()._asdict(),
        "cpu_model": model,
        "online_cpus": os.cpu_count() or 0,
        "cpus_allowed": cpus_allowed,
        "mem_total_kb": mem_total_kb,
        "scaling_governor": governor,
        "clocksource": clocksource,
        "available_clocksources": available_clocksources,
        "ossim_mode": os.environ.get("OSSIM_MODE", ""),
        "ossim_vtime_epoch_ns": os.environ.get("OSSIM_VTIME_EPOCH_NS", ""),
        "git_commit": os.environ.get("BENCH_GIT_COMMIT", ""),
        "exp_label": os.environ.get("EXP_LABEL", ""),
        "vm_label": os.environ.get("VM_LABEL", ""),
        # Host-side QEMU pinning for this VM (set by the experiment driver).
        # Inside the guest, `cpus_allowed` describes the *guest's* CPUs; this
        # field records which *host* CPUs QEMU was taskset-pinned to.
        "host_cpuset": os.environ.get("HOST_CPUSET", ""),
    }


def write_result(
    output: Path,
    benchmark: str,
    args: dict[str, Any],
    started_at: int,
    mono_start: int,
    finished_at: int,
    mono_end: int,
    result: dict[str, Any],
    samples: list[dict[str, Any]] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "benchmark": benchmark,
        "schema": 2,
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": finished_at,
        "mono_start": mono_start,
        "mono_end": mono_end,
        "args": args,
        "metadata": collect_metadata(),
        "result": result,
    }
    if samples is not None:
        payload["samples"] = samples
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))


def write_host_bracket(
    output: Path,
    benchmark: str,
    args: dict[str, Any],
    started_at: int,
    mono_start: int,
    finished_at: int,
    mono_end: int,
) -> None:
    """Sidecar emitted by the host-side driver around a guest run.

    The guest-side `mono_*` reflects guest/virtual time; this file records the
    same bracket as observed on the host, so post-processing can compute both
    events/guest-second and events/host-second.
    """
    payload = {
        "benchmark": benchmark,
        "schema": 2,
        "kind": "host_bracket",
        "started_at": started_at,
        "finished_at": finished_at,
        "mono_start": mono_start,
        "mono_end": mono_end,
        "args": args,
        "metadata": collect_metadata(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2))
