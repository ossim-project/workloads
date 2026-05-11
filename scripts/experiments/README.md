# Workshop-paper experiments

Microbenchmarks that validate the scheduling (S1) and memory-isolation (M1)
designs in the workshop paper. End-to-end Spark TPC-DS variants (S2, M2)
are deferred to the bigdata stack.

## Layout

- `../../host_microbench/` — bench scripts and native helper tools
  (`pchase`, `cpu_loop`) mounted **read-only** into guests via the
  `input_fsdev` 9p tag. Scripts there read `lib_results` for a uniform
  result-file shape.
- Per-VM writable output via the `output_fsdev` 9p tag, lands at
  `$OSSIM_OUT_DIR/workloads/disks/microbench/instance-N/output/` on the host.
- `experiment_lib.py` — shared helpers: `spawn_vm_tmux`, barrier
  release/clear, ready-marker poll, host-wall bracket, host-side noise.
- Experiment drivers: `exp_s1.py` (canonical), `exp_m1_mem_isolation.sh`.

## One-time host setup

```bash
cd ossim/workloads
make dimg-microbench           # 2 vCPU / 4 GiB Ubuntu w/ deps baked in
```

`build-microbench-tools` (compiling `pchase` and `cpu_loop` into
`host_microbench/`) runs automatically as a prerequisite of
`qemu-microbench-instance`, but you can also invoke it directly:

```bash
make build-microbench-tools
```

### Networking

Microbench (and test) instances launch with **no network** by default.
Reason: ossim virtualises the guest CLOCK_REALTIME progression via pvclock,
but a running NTP daemon (chrony / systemd-timesyncd) inside the guest
would reach external time servers and slew CLOCK_REALTIME back toward host
time, undoing the simulated-time alignment. Pass `USE_USER_NET=1` to opt in
when network is actually needed (debugging, ad-hoc package install):

```bash
make qemu-microbench-instance N=0 USE_USER_NET=1
```

## Verify the PV-clock path before running S1

The S1 framing assumes the guest's `clock_gettime(CLOCK_MONOTONIC)` resolves
through the ossim PV clocksource. Confirm this once per guest image, before
collecting paper data:

```bash
# In each VM:
python3 /input/verify_pvclock.py --output /out/pvclock.json --label vm-0
```

Expected: `clocksource=ossim_pvclock` (or whatever the PV clocksource is
named) and `vdso_active=true`. If `clocksource=tsc` or
`vdso_active=false`, fix that before trusting any S1 numbers.

## Result-file conventions

All `bench_*.py` scripts emit JSON via `lib_results.write_result`:

- `metadata`: uname, lscpu, vCPUs, mem, governor, clocksource, ossim mode +
  vtime epoch (from env), git commit, exp/vm labels.
- `mono_start`/`mono_end`: in-process CLOCK_MONOTONIC bracket.
- `started_at`/`finished_at`: in-process CLOCK_REALTIME bracket. Note: in a
  guest, REALTIME is currently anchored to host wallclock at boot
  (persistent-clock paravirt is pending) — use the mono pair for time
  reasoning.
- `samples` (cpu_loop only): `[{mono_ns, ticks}, ...]`, used by
  `analyze/skew.py` to compute spread/Jain/CV across VMs.

The host driver also writes a sidecar `*.host_bracket.json` with host-wall
timestamps around the guest run, so post-processing can compute both
`work / guest-second` and `work / host-second`.

## Exp S1: cost and robustness of ossim scheduling

The driver is `exp_s1.py`. Its built-in docs cover phases, metrics,
methodology, output layout, knobs, and the operator workflow:

```bash
./exp_s1.py help        # long-form experiment design doc
./exp_s1.py --help      # flag reference
```

For variance, re-run each phase 5–10 times (separate driver
invocations); each invocation lands in its own timestamped subdir under
`--out-dir`, so runs of the same phase don't collide.

## Exp M1: memory isolation under noisy neighbor

```bash
CONFIG=alone         MODE=latency ./exp_m1_mem_isolation.sh
CONFIG=colocated_off MODE=latency NOISY_PROFILE=bandwidth NOISY_WORKERS=4 \
    ./exp_m1_mem_isolation.sh
CONFIG=colocated_on  MODE=latency NOISY_PROFILE=bandwidth NOISY_WORKERS=4 \
    ./exp_m1_mem_isolation.sh
```

The isolation difference between `colocated_off` and `colocated_on` is
encoded in the cpusets the script pins each QEMU process to:

- `colocated_off`: victim and neighbor share `$NEIGHBOR_CPUSET_OFF`
  (default = `$VICTIM_CPUSET`, i.e. fully overlapping)
- `colocated_on`: victim on `$VICTIM_CPUSET`, neighbor on
  `$NEIGHBOR_CPUSET_ON` (default = disjoint)

For LLC/MBA/IRQ-steering policies that need root commands on the host,
point `POLICY_HOOK` at a script that `$CONFIG` is passed to as `$1`:

```bash
POLICY_HOOK=/path/to/setup_resctrl.sh CONFIG=colocated_on \
    ./exp_m1_mem_isolation.sh
```

`MODE=latency` runs the C `pchase` binary (random pointer-chase, cache-line
stride). `MODE=bandwidth` runs sysbench memory streaming.

## Pending

- Plotting helper under `host_microbench/analyze/` once the data shape
  stabilises.
- Serial-console driver to fully automate the in-VM commands.
- Ossim-native cell-isolation primitives (`ossimctl cell ...`); for now M1
  uses cpuset/NUMA/resctrl as the isolation substrate.
- Exp S2 (scheduling e2e) and Exp M2 (memory e2e) on the bigdata stack.
- Epoch sweep + heterogeneous CPU/I/O mix (Section 4 / extended-version
  material per the suggestions doc).
