"""Shared helpers for experiment driver scripts.

Python translation of common.sh. Caller sets WORKLOADS_ROOT (or the module
detects it from the script location). Path layout matches the bash version
exactly so the two implementations can read/write the same on-disk state
during the transition.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# Path layout — must match common.sh.
# ---------------------------------------------------------------------------

def _detect_workloads_root() -> Path:
    env = os.environ.get("WORKLOADS_ROOT")
    if env:
        return Path(env).resolve()
    # scripts/experiments/experiment_lib.py -> parents[2] is workloads/.
    return Path(__file__).resolve().parents[2]


WORKLOADS_ROOT: Path = _detect_workloads_root()
os.environ.setdefault("WORKLOADS_ROOT", str(WORKLOADS_ROOT))

_OSSIM_OUT_DIR = os.environ.get("OSSIM_OUT_DIR")
OUT_BASE: Path = Path(_OSSIM_OUT_DIR or (WORKLOADS_ROOT / "out")) / "workloads"
EXP_OUT_BASE: Path = OUT_BASE / "exps"
HOST_MICROBENCH: Path = WORKLOADS_ROOT / "host_microbench"


def instance_output_dir(n: int | str) -> Path:
    return OUT_BASE / "disks" / "microbench" / f"instance-{n}" / "output"


# ---------------------------------------------------------------------------
# subprocess helpers
# ---------------------------------------------------------------------------

def run(
    cmd: Sequence[str | os.PathLike],
    *,
    check: bool = True,
    capture: bool = False,
    quiet_stderr: bool = False,
    cwd: os.PathLike | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Thin subprocess.run wrapper. Always passes the command as a list (no
    shell), prints the command before running for operator visibility."""
    str_cmd = [str(x) for x in cmd]
    print("+ " + " ".join(str_cmd), flush=True)
    stderr = subprocess.DEVNULL if quiet_stderr else None
    return subprocess.run(
        str_cmd,
        check=check,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else stderr,
    )


def run_ok(cmd: Sequence[str | os.PathLike], **kw) -> bool:
    """Best-effort run — returns True on exit 0, False otherwise. Mirrors the
    `cmd || true` pattern in the bash version."""
    try:
        run(cmd, check=True, **kw)
        return True
    except subprocess.CalledProcessError:
        return False


# ---------------------------------------------------------------------------
# tmux
# ---------------------------------------------------------------------------

def tmux_has_session(session: str) -> bool:
    return subprocess.run(
        ["tmux", "has-session", "-t", session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def tmux_kill_session(session: str) -> None:
    if tmux_has_session(session):
        run_ok(["tmux", "kill-session", "-t", session], quiet_stderr=True)


def spawn_vm_tmux(session: str, n: int | str, cpuset: str = "") -> None:
    """Spawn `make qemu-microbench-instance N=$1` inside a tmux window."""
    window = f"vm-{n}"
    make_cmd = f"make qemu-microbench-instance N={n}"
    if cpuset:
        make_cmd += f" QEMU_CPUSET={cpuset}"
    body = f"cd {shlex_quote(str(WORKLOADS_ROOT))} && {make_cmd}; bash"
    if not tmux_has_session(session):
        run(["tmux", "new-session", "-d", "-s", session, "-n", window, body])
    else:
        run(["tmux", "new-window", "-t", session, "-n", window, body])


# ---------------------------------------------------------------------------
# barrier / ready-marker / result polling
# ---------------------------------------------------------------------------

def _ready_marker(n) -> Path:
    return instance_output_dir(n) / f"ready_vm-{n}"


def _barrier_file(n) -> Path:
    return instance_output_dir(n) / "start"


def wait_for_result(path: os.PathLike, timeout_s: int = 1800) -> None:
    """Block until `path` exists and is non-empty."""
    p = Path(path)
    deadline = time.monotonic() + timeout_s
    while True:
        if p.is_file() and p.stat().st_size > 0:
            return
        if time.monotonic() >= deadline:
            print(f"timed out waiting for {p}", file=sys.stderr)
            raise TimeoutError(f"timed out waiting for {p}")
        time.sleep(0.5)


def release_barrier(instances: Iterable) -> None:
    for n in instances:
        d = instance_output_dir(n)
        d.mkdir(parents=True, exist_ok=True)
        _barrier_file(n).touch()


def clear_barriers(instances: Iterable) -> None:
    for n in instances:
        _barrier_file(n).unlink(missing_ok=True)


def clear_results(fname: str, instances: Iterable) -> None:
    for n in instances:
        (instance_output_dir(n) / fname).unlink(missing_ok=True)


def clear_ready_markers(instances: Iterable) -> None:
    for n in instances:
        _ready_marker(n).unlink(missing_ok=True)


def wait_for_all_ready(instances: Sequence, timeout_s: int = 600) -> None:
    """Poll ready_vm-N markers (set by run_in_vm.sh) until every guest has
    reached its barrier wait. Caller supplies the timeout."""
    seen: set = set()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        missing = []
        for n in instances:
            if _ready_marker(n).is_file():
                if n not in seen:
                    print(f"  vm-{n} ready", flush=True)
                    seen.add(n)
            else:
                missing.append(n)
        if not missing:
            return
        time.sleep(1)
    print(f"wait_for_all_ready: timed out after {timeout_s}s; missing:",
          file=sys.stderr)
    for n in instances:
        m = _ready_marker(n)
        if not m.is_file():
            print(f"  vm-{n} ({m})", file=sys.stderr)
    raise TimeoutError("wait_for_all_ready timed out")


# ---------------------------------------------------------------------------
# host_bracket.py wrappers
# ---------------------------------------------------------------------------

def _host_bracket(output: os.PathLike, benchmark: str, label: str,
                  phase: str, env: dict | None = None) -> None:
    cmd = [
        sys.executable, str(HOST_MICROBENCH / "host_bracket.py"),
        "--output", str(output),
        "--phase", phase,
        "--benchmark", benchmark,
        "--label", label,
    ]
    run(cmd, env=env)


def host_bracket_start(output, benchmark, label="", env=None):
    _host_bracket(output, benchmark, label, "start", env=env)


def host_bracket_end(output, benchmark, label="", env=None):
    _host_bracket(output, benchmark, label, "end", env=env)


# ---------------------------------------------------------------------------
# host-side noise (stress-ng) for the perturbed condition
# ---------------------------------------------------------------------------

_NOISE_LOG = Path("/tmp/ossim-host-noise.log")


def start_host_noise(cpuset: str, workers: int = 2,
                     profile: str = "cpu") -> int:
    """Pin a stress-ng workload to a host cpuset. Returns the pid; the caller
    is responsible for killing it via stop_host_noise(pid)."""
    if profile == "cpu":
        flags = ["--cpu", str(workers), "--cpu-method", "matrixprod"]
    elif profile == "memory":
        flags = ["--stream", str(workers)]
    elif profile == "cache":
        flags = ["--cache", str(workers), "--cache-level", "3"]
    else:
        raise ValueError(f"unknown noise profile: {profile}")

    cmd = ["taskset", "-c", cpuset, "stress-ng", *flags, "--metrics-brief"]
    log_fh = _NOISE_LOG.open("w")
    print("+ " + " ".join(cmd) + f"  (log: {_NOISE_LOG})", flush=True)
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT)

    # Give it a beat to either survive (taskset/stress-ng OK) or die (bad args
    # / missing binary). If it dies immediately, diagnose loudly.
    time.sleep(0.3)
    if proc.poll() is not None:
        log_fh.close()
        msg = [
            "start_host_noise: stress-ng died immediately.",
            f"  cmd: {' '.join(cmd)}",
            f"  log: {_NOISE_LOG}",
        ]
        if _NOISE_LOG.is_file() and _NOISE_LOG.stat().st_size > 0:
            msg.append("  --- log (first 40 lines) ---")
            with _NOISE_LOG.open() as fh:
                for line in fh.readlines()[:40]:
                    msg.append("  | " + line.rstrip())
        else:
            msg.append("  (log empty — likely 'command not found' or taskset error)")
        if shutil.which("stress-ng") is None:
            msg.append("  hint: stress-ng not on PATH; install with: sudo apt-get install stress-ng")
        for line in msg:
            print(line, file=sys.stderr)
        raise RuntimeError("stress-ng failed to start")
    return proc.pid


def stop_host_noise(pid: int | None) -> None:
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    # best-effort reap
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


# ---------------------------------------------------------------------------
# terminal log (tee)
# ---------------------------------------------------------------------------

def tee_stdio_to(log_path: Path) -> subprocess.Popen | None:
    """Duplicate this process's stdout+stderr to `log_path` while still
    writing to the terminal. Returns the tee subprocess; pass it to
    close_tee() at teardown.

    Uses an external `tee` subprocess so subprocess output (ossimctl,
    tmux, stress-ng) is captured too, not just Python `print()` calls.
    Falls back to None (no tee) if `tee` is unavailable.
    """
    if shutil.which("tee") is None:
        print(f"warning: `tee` not on PATH; skipping terminal.log",
              file=sys.stderr)
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Save the original stdout fd so tee's own writes still reach the
    # terminal — otherwise tee would write back into its own stdin.
    saved_stdout_fd = os.dup(1)
    tee = subprocess.Popen(
        ["tee", str(log_path)],
        stdin=subprocess.PIPE,
        stdout=saved_stdout_fd,
        stderr=saved_stdout_fd,
    )
    os.close(saved_stdout_fd)
    # Redirect this process's fds 1 and 2 to tee's stdin.
    os.dup2(tee.stdin.fileno(), 1)
    os.dup2(tee.stdin.fileno(), 2)
    # Reopen Python's high-level wrappers on the new fds so print() and
    # sys.stderr.write() also flow through tee.
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)
    return tee


def close_tee(tee: subprocess.Popen | None) -> None:
    if tee is None:
        return
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    try:
        tee.stdin.close()
    except Exception:
        pass
    try:
        tee.wait(timeout=5)
    except subprocess.TimeoutExpired:
        tee.kill()


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------

def shlex_quote(s: str) -> str:
    import shlex
    return shlex.quote(s)
