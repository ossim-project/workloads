#!/usr/bin/env python3
"""Exp S1: cost and robustness of ossim scheduling.

Run `./exp_s1.py help` for the full experiment design doc, including phase
catalogue, metrics, methodology, output layout, and operator workflow.
Run `./exp_s1.py --help` for the flag and env-var reference.
"""

from __future__ import annotations

EXPERIMENT_DOC = """\
=========================================================================
 Exp S1 — Cost and robustness of ossim scheduling
=========================================================================

GOAL
  Measure (a) the *cost* of ossim sync — how much wall-clock slowdown
  ossim's virtual-time coordination imposes when the host is otherwise
  unperturbed, and (b) the *robustness* of that coordination — whether
  per-VM progress stays skew-invariant in virtual time when a noisy
  neighbor competes for the same host CPUs.

PHASES
  physical            Bare-metal baseline: cpu_loop on the host directly.
                      No VM, no ossim. Calibrates the events/second floor.

  clean.noossim       N VMs (default 2), each running cpu_loop. ossim is
                      disabled; the host is otherwise idle. Measures the
                      cost of virtualization alone.

  clean.ossim         Same N VMs and same workload, but with ossim sync
                      enabled. The delta vs clean.noossim is the cost
                      attributable to ossim's virtual-time coordination.

  perturbed.noossim   Two VMs pinned to disjoint host CPU sets. A host
                      stress-ng workload is pinned to VM-0's CPUs only,
                      creating an asymmetric contention pattern. ossim is
                      disabled, so VM-0 gets slower events/host-second and
                      events/guest-second equally — the lack of
                      coordination is visible in both metrics.

  perturbed.ossim     Same, with ossim sync enabled. Under ossim, VM-0's
                      virtual-time progress should stay in step with
                      VM-1's despite the noise, even though its
                      wall-clock throughput is lower. The headline result
                      is the skew narrowing in events/guest-virtual-second
                      vs perturbed.noossim.

METRICS
  Unit: an *event* (also "tick") is one trip through cpu_loop's inner
  loop, sized by INNER (default 100_000 multiplications). Each VM samples
  (mono_ns, cumulative_ticks) every SAMPLE_MS (default 100ms) and writes
  the series to its result JSON. The host-side bracket file timestamps
  the host wall-clock start/end of the run window.

  Per-VM metrics (computed from samples + bracket):

    events / guest-virtual-second
      Total events divided by (last_mono_ns - first_mono_ns).
      Under ossim sync the guest's monotonic clock advances in virtual
      time, so this is *virtual-time throughput*. It should be equal
      across VMs in any phase that runs ossim sync correctly, regardless
      of host-side perturbation. This is the headline robustness number.

    events / host-second
      Total events divided by (host_bracket.end - host_bracket.start).
      Always reflects raw wall-clock throughput. Under ossim the
      perturbed VM's value drops *by design* — ossim slows the fast
      VM(s) so all VMs make equal virtual-time progress. This is the
      headline cost number when paired against `physical`.

  Aggregated across VMs (analyze/skew.py, N_VMS >= 2):

    spread_ticks
      max(cumulative_ticks) - min(cumulative_ticks) across VMs at each
      sampled timestamp. Reported as max_spread_ticks (worst across the
      run), final_spread_ticks (at the last sample), and
      steady_state.max_spread_ticks (worst after the startup transient).
      Lower is more synchronized.

    jain_index
      Jain's fairness over per-VM tick rates: (sum x_i)^2 / (n * sum x_i^2).
      1.0 means perfect equality across VMs; 1/n means one VM has all
      the work. Reported as final_jain_index and steady_state.min_jain_index.

    cv
      Coefficient of variation (stddev / mean) of per-VM tick rates at
      each sample. 0.0 = perfect equality; grows with divergence.
      Reported as final_cv and steady_state.max_cv.

  Interpretation by phase:

    physical              Single value, calibration baseline only.
    clean.noossim         All metrics should be near-equal across VMs
                          (no contention, no ossim).
    clean.ossim           events / guest-virtual-second within ~1% across
                          VMs; events / host-second slightly below
                          clean.noossim by the ossim-coordination cost.
    perturbed.noossim     events / guest-virtual-second AND
                          events / host-second both diverge (VM-0 lower).
                          jain < 1, cv > 0, spread grows over time.
    perturbed.ossim       events / guest-virtual-second stays equal
                          across VMs (final_jain ~1.0, final_cv ~0,
                          steady_state.max_spread_ticks bounded by
                          VTIME_EPOCH_NS); events / host-second diverges
                          *by design*.

METHODOLOGY
  1. Spawn each VM as a tmux window running `make qemu-microbench-instance
     N=<i>`. The autorun execs /out/start_bench.sh on autologin.
  2. start_bench.sh in each guest runs run_in_vm.sh, which drops a
     ready_vm-N marker into the shared /out directory and blocks on the
     barrier file /out/start.
  3. The host driver polls for all ready_vm-N markers (or, with
     --wait-interactive, prompts the operator). Once every VM is ready,
     it (a) calls `ossimctl enable-sync` if the phase is *.ossim, (b)
     starts the host stress-ng noise if the phase is perturbed.*, then
     (c) releases the barrier by touching /out/start.
  4. Each VM's cpu_loop writes a JSON result; the driver collects them
     into the phase directory and runs skew analysis.
  5. A host-side time bracket frames the entire VM-run window with
     host-wall timestamps for cross-VM alignment.

OUTPUT LAYOUT
  Each run lands in a fresh timestamped subdirectory under --out-dir
  (default: current working directory):

    <out-dir>/<phase_label>_<YYYY-MM-DD_HH-MM-SS>/
      cpu_vm-<n>.json              per-VM cpu_loop results
      cpu_loop.host_bracket.json   host-wall start/end markers
      skew_summary.json            Jain/CV/spread (N_VMS >= 2)
      terminal.log                 full driver stdout/stderr capture

  Two runs of the same phase never collide; each gets its own dir
  identified by the host-wall clock at invocation time.

KNOBS
  See `./exp_s1.py --help` for the full flag reference. Common ones:
    --phase                         which phase to run (required)
    --out-dir                       output base dir (default: cwd)
    --n-vms                         VM count for clean phases (default 2)
    --vm-cpuset                     host cpuset for one VM; repeat the
                                    flag once per VM in order. Each
                                    value may contain commas (e.g.,
                                    --vm-cpuset 1-2,4-5 pins one VM to
                                    CPUs 1,2,4,5). Default:
                                    --vm-cpuset 0-1 --vm-cpuset 2-3.
                                    VMs beyond the list get no pinning.
    --noise-cpuset / --noise-workers
      / --noise-profile             host stress-ng config (perturbed.*)
    --time-s                        bench duration in guest seconds
    --vtime-epoch-ns                ossim sync epoch granularity (ns)
    --wait-interactive              fall back to manual Enter prompt
                                    instead of auto-polling ready markers
    --barrier-ready-timeout-s       seconds to wait for guests to reach
                                    the barrier (default 600)

OPERATOR WORKFLOW
  Typical sequence (each phase fresh):
    1. ./exp_s1.py --phase physical            # baseline
    2. ./exp_s1.py --phase clean.noossim       # virtualization cost
    3. ./exp_s1.py --phase clean.ossim         # ossim cost (delta vs 2)
    4. ./exp_s1.py --phase perturbed.noossim   # noise impact, no ossim
    5. ./exp_s1.py --phase perturbed.ossim     # noise impact, with ossim

  Compare clean.ossim vs clean.noossim for the cost story; compare
  perturbed.ossim vs perturbed.noossim for the robustness story.

  Pass --out-dir to land all phases under a single parent so they're
  easy to diff/aggregate later.

  For *.ossim phases the ossim kernel module must be loaded first:
    modprobe ossim

REQUIREMENTS
  - tmux
  - qemu (driven via `make qemu-microbench-instance`)
  - ossimctl on PATH (for *.ossim phases)
  - stress-ng on PATH (for perturbed.* phases)
  - Python 3.8+
"""

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

import experiment_lib as lib


PHASES = (
    "physical",
    "clean.noossim",
    "clean.ossim",
    "perturbed.noossim",
    "perturbed.ossim",
)


def phase_label(phase: str) -> str:
    return phase.replace(".", "_")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--phase", choices=PHASES, required=True,
                   help="phase to run (required; see `./exp_s1.py help` for "
                        "what each phase tests)")
    p.add_argument("--n-vms", type=int, default=2,
                   help="VM count for clean phases (default: 2)")
    p.add_argument("--vm-cpuset", dest="vm_cpusets",
                   action="append", default=None,
                   metavar="CPUSET",
                   help="host cpuset for one VM; pass once per VM in order "
                        "(e.g., --vm-cpuset 0-1 --vm-cpuset 2-3). Each "
                        "value may contain commas, so '1-2,4-5' is a "
                        "single VM pinned to CPUs 1,2,4,5. VMs beyond the "
                        "supplied list get no pinning. "
                        "Default if omitted: --vm-cpuset 0-1 --vm-cpuset 2-3.")
    p.add_argument("--noise-cpuset", default=None,
                   help="CPUs for host stress-ng (default: first --vm-cpusets entry)")
    p.add_argument("--noise-profile", default="cpu",
                   choices=("cpu", "memory", "cache"),
                   help="stress-ng profile (default: cpu)")
    p.add_argument("--noise-workers", type=int, default=2,
                   help="stress-ng worker count (default: 2)")
    p.add_argument("--time-s", type=int, default=10,
                   help="bench duration in guest-monotonic seconds (default: 10)")
    p.add_argument("--sample-ms", type=int, default=100,
                   help="cpu_loop sampling interval ms (default: 100)")
    p.add_argument("--inner", type=int, default=100_000,
                   help="cpu_loop inner trip count per tick (default: 100000)")
    p.add_argument("--vtime-epoch-ns", type=int, default=10_000_000,
                   help="vtime epoch for ossimctl enable-sync, ns (default: 10000000)")
    p.add_argument("--session", default=None,
                   help="tmux session name (default derived from phase)")
    p.add_argument("--wait-interactive", action="store_true",
                   help="prompt for Enter once VMs reach the barrier instead "
                        "of auto-polling ready markers")
    p.add_argument("--barrier-ready-timeout-s", type=int, default=60,
                   help="seconds to wait for guests to reach the barrier "
                        "(default:60)")
    p.add_argument("--out-dir", type=Path, default=Path.cwd()/'out',
                   help="output base directory; results land in "
                        "<out-dir>/<phase_label>_<timestamp>/ "
                        "(default: <pwd>/out/)")
    args = p.parse_args()
    if args.vm_cpusets is None:
        args.vm_cpusets = ["0-1", "2-3"]
    if args.noise_cpuset is None:
        args.noise_cpuset = args.vm_cpusets[0] if args.vm_cpusets else ""
    if args.session is None:
        args.session = f"ossim-s1-{args.phase.replace('.', '_')}"
    # Per-run timestamped output dir. Format: 2026-06-09_03-25-48 (local
    # time; filesystem-safe; second precision).
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    args.phase_dir = args.out_dir / f"{phase_label(args.phase)}_{ts}"
    return args


# ---------------------------------------------------------------------------
# physical phase: bare-metal baseline, no VM, no ossim.
# ---------------------------------------------------------------------------

def run_physical(args) -> None:
    args.phase_dir.mkdir(parents=True, exist_ok=True)
    out = args.phase_dir / "cpu_host.json"
    bracket = args.phase_dir / "cpu_host.host_bracket.json"
    print(f"Exp S1 [physical]: cpu_loop on bare metal, time={args.time_s}s")
    print(f"Output dir: {args.phase_dir}")

    env = os.environ.copy()
    env.update({"EXP_LABEL": phase_label(args.phase), "VM_LABEL": "host"})

    lib.host_bracket_start(bracket, "cpu_loop", label="host", env=env)
    lib.run(
        [sys.executable, str(lib.HOST_MICROBENCH / "bench_cpu.py"),
         "--output", str(out), "--mode", "loop",
         "--time", str(args.time_s),
         "--sample-ms", str(args.sample_ms),
         "--inner", str(args.inner),
         "--label", "host"],
        env=env,
    )
    lib.host_bracket_end(bracket, "cpu_loop", label="host", env=env)
    print(f"Result: {out}")
    print(f"Bracket: {bracket}")


# ---------------------------------------------------------------------------
# VM phases
# ---------------------------------------------------------------------------

def write_start_bench(args, n: int, cpuset: str) -> None:
    """Drop a per-instance start_bench.sh into the guest's /out mount."""
    phase_lbl = phase_label(args.phase)
    ossim_mode = "sync" if args.phase.endswith(".ossim") else "disabled"
    out_dir = lib.instance_output_dir(n)
    out_dir.mkdir(parents=True, exist_ok=True)
    script = f"""#!/bin/bash
# Auto-generated by exp_s1.py for VM {n} in phase {phase_lbl}.
exec env \\
    BENCH=/input/bench_cpu.py \\
    OUTPUT=/out/cpu_{phase_lbl}.json \\
    VM_LABEL=vm-{n} \\
    OSSIM_MODE={ossim_mode} \\
    EXP_LABEL={phase_lbl} \\
    HOST_CPUSET="{cpuset}" \\
    ARGS="--mode loop --time {args.time_s} --sample-ms {args.sample_ms} --inner {args.inner}" \\
    /input/run_in_vm.sh
"""
    target = out_dir / "start_bench.sh"
    target.write_text(script)
    target.chmod(0o755)


def run_vm_phase(args) -> None:
    phase = args.phase
    is_ossim = phase.endswith(".ossim")
    is_perturbed = phase.startswith("perturbed.")

    if phase.startswith("clean."):
        instances = list(range(args.n_vms))
    else:  # perturbed.*
        instances = [0, 1]

    vm_cpusets = {
        n: (args.vm_cpusets[n] if n < len(args.vm_cpusets) else "")
        for n in instances
    }

    # ----- pre-spawn cleanup (matches the bash defensive setup) -----
    ossim_present = Path("/dev/ossim").exists()
    if ossim_present:
        print("Resetting ossim...")
        # best-effort: clears leftover state from a prior session
        lib.run_ok(["ossimctl", "disable"], quiet_stderr=True)
    if is_ossim:
        if not ossim_present:
            print(f"PHASE={phase} requires the ossim kernel module, but "
                  f"/dev/ossim is missing.", file=sys.stderr)
            print("Load the module (e.g., 'modprobe ossim') and rerun.",
                  file=sys.stderr)
            sys.exit(1)
        print("Configuring ossim: enable (sync deferred until after VM boot)")
        lib.run(["ossimctl", "enable"])

    # Kill any stale same-named tmux session so spawn_vm_tmux starts fresh.
    if lib.tmux_has_session(args.session):
        print(f"Killing stale tmux session {args.session}...")
        lib.tmux_kill_session(args.session)

    lib.clear_barriers(instances)
    lib.clear_ready_markers(instances)
    lib.clear_results(f"cpu_{phase_label(phase)}.json", instances)

    # ----- spawn VMs + drop per-instance start_bench.sh -----
    for n in instances:
        lib.spawn_vm_tmux(args.session, n, vm_cpusets[n])
        write_start_bench(args, n, vm_cpusets[n])

    phase_dir = args.phase_dir
    phase_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {phase_dir}")
    bracket = phase_dir / "cpu_loop.host_bracket.json"

    noise_pid: int | None = None
    try:
        print()
        print(f"tmux session: {args.session}  "
              f"(attach with: tmux attach -t {args.session})")
        print()
        print("The image's autorun execs /out/start_bench.sh on autologin, so each VM")
        print("should reach the barrier wait on its own once boot finishes — no manual")
        print("'bash /out/start_bench.sh' needed.")
        print()

        if args.wait_interactive:
            print("--wait-interactive: press Enter once every VM prints "
                  "'[vm-N] waiting on barrier ...'.")
            if is_ossim:
                print("I will then call 'ossimctl enable-sync' and release the barrier.")
            else:
                print("I will release the barrier.")
            input()
        else:
            timeout = args.barrier_ready_timeout_s
            print(f"Waiting for all VMs to reach the barrier (timeout {timeout}s; "
                  "pass --wait-interactive for the old manual prompt)...")
            lib.wait_for_all_ready(instances, timeout_s=timeout)
            print("All VMs ready.")

        if is_ossim:
            print(f"Enabling ossim sync (vtime_epoch={args.vtime_epoch_ns}ns)...")
            lib.run(["ossimctl", "enable-sync", str(args.vtime_epoch_ns)])
            time.sleep(1)

        # Host-wall start bracket
        host_pinning_summary = ",".join(
            f"vm-{n}={vm_cpusets[n]}" for n in instances
        )
        bracket_env = os.environ.copy()
        bracket_env.update({
            "EXP_LABEL": phase_label(phase),
            "VM_LABEL": "host",
            "OSSIM_MODE": "sync" if is_ossim else "disabled",
            "HOST_CPUSET": host_pinning_summary,
        })
        lib.host_bracket_start(bracket, "cpu_loop",
                               label=phase_label(phase), env=bracket_env)

        if is_perturbed:
            print(f"Starting host stress-ng on cpus {args.noise_cpuset} "
                  f"(workers={args.noise_workers}, profile={args.noise_profile})...")
            noise_pid = lib.start_host_noise(
                args.noise_cpuset, args.noise_workers, args.noise_profile,
            )
            print(f"  noise pid={noise_pid}")

        lib.release_barrier(instances)
        print("Barrier released; waiting for results...")

        for n in instances:
            p = lib.instance_output_dir(n) / f"cpu_{phase_label(phase)}.json"
            lib.wait_for_result(p)
            print(f"  vm-{n} -> {p}")

        lib.host_bracket_end(bracket, "cpu_loop",
                             label=phase_label(phase), env=bracket_env)

        # Aggregate per-VM results into the phase directory
        collected = []
        for n in instances:
            src = lib.instance_output_dir(n) / f"cpu_{phase_label(phase)}.json"
            dst = phase_dir / f"cpu_vm-{n}.json"
            shutil.copyfile(src, dst)
            collected.append(dst)

        if len(collected) >= 2:
            lib.run(
                [sys.executable, str(lib.HOST_MICROBENCH / "analyze" / "skew.py"),
                 *[str(c) for c in collected],
                 "--out", str(phase_dir / "skew_summary.json")],
            )

        print()
        print("Phase done.")
        print(f"  per-VM:  {phase_dir}/cpu_vm-*.json")
        print(f"  bracket: {bracket}")
        if len(collected) >= 2:
            print(f"  skew:    {phase_dir / 'skew_summary.json'}")

    finally:
        # Cleanup runs on success, exception, and Ctrl+C alike — addresses the
        # bash version's gap where these were inline at the bottom.
        lib.stop_host_noise(noise_pid)
        lib.tmux_kill_session(args.session)
        if is_ossim and Path("/dev/ossim").exists():
            print("Disabling ossim sync...")
            lib.run_ok(["ossimctl", "disable-sync"], quiet_stderr=True)
        if Path("/dev/ossim").exists():
            lib.run_ok(["ossimctl", "disable"], quiet_stderr=True)


def main() -> int:
    # `./exp_s1.py help` prints the long-form experiment design doc.
    # Standard --help / -h still shows the flag reference.
    if len(sys.argv) >= 2 and sys.argv[1] in ("help", "doc", "design"):
        print(EXPERIMENT_DOC)
        return 0
    args = parse_args()
    # Set up the per-run output dir and a tee of stdout/stderr into
    # terminal.log inside it, so the whole run leaves a self-contained
    # log next to its result JSONs.
    args.phase_dir.mkdir(parents=True, exist_ok=True)
    tee = lib.tee_stdio_to(args.phase_dir / "terminal.log")
    try:
        if args.phase == "physical":
            run_physical(args)
        else:
            run_vm_phase(args)
        return 0
    finally:
        lib.close_tee(tee)


if __name__ == "__main__":
    sys.exit(main())
