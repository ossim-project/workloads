# Ossim guest microbenchmarks

These benchmarks run inside a guest and measure scheduling behavior in guest time (`CLOCK_MONOTONIC`), which advances in virtual time under ossim sync scheduling.
Every tool prints a single JSON object on stdout so the host-side harness can parse results from the serial log or from a file in the shared `/out` directory.
The directory is mounted read-only into microbench VMs via the `input_fsdev` 9p share (see `workloads/disks/microbench/rules.mk`), so tools must be built on the host first with `make`.

## Tools

`timer_jitter/` measures periodic timer wake-up latency.
It arms an absolute `CLOCK_MONOTONIC` timer at a fixed period and reports the distribution of wake-up lateness relative to each deadline.
Under ossim, the distribution should match an idle dedicated machine regardless of host-side contention.
Example: `timer_jitter -p 1000 -n 10000 -c 0`.

`smp_barrier/` measures cross-vCPU barrier throughput with one thread pinned to each guest CPU.
Barrier rounds per guest-second degrade directly with vCPU time skew, making this an end-to-end probe of how tightly the vCPUs of a VM co-run.
The default spin barrier stresses co-scheduling hardest; `-s` switches to a sleeping pthread barrier, which also exercises the cross-vCPU wake-up path. Use `-a` to select the first CPU in the consecutive CPU range.
Example: `smp_barrier -a 0 -t 2 -n 100000 -w 1000`.

`smp_pingpong/` measures cross-vCPU round-trip latency between two pinned threads.
The default spin mode bounces a shared atomic and shows raw co-run latency; `-f` sleeps in futex on every hop, adding the guest wake-up and the host scheduler's cross-vCPU kick path.
Example: `smp_pingpong -a 0 -b 1 -n 100000 -f`.

`simple_compute/` measures independent per-vCPU compute throughput.
It starts N threads together, pins them to consecutive guest CPUs, and runs one xorshift64 dependency chain per thread without synchronization or shared-memory communication in the measured region. Per-thread rates expose asymmetric execution, while aggregate throughput provides a control for generic sync accounting overhead.
Example: `simple_compute -a 0 -t 2 -n 10000000`.

## Known sync-transition limitation

For now, perform at most one `async -> sync` transition in an OSSIM session before collecting sync results. Repeated `enable_sync` / `disable_sync` cycles are a known deferred issue and can leave guest vtime/pvclock in a pathological freeze-and-jump state. Restart or fully reset the OSSIM session before another sync experiment; do not use repeated transitions as benchmark setup until the transition path is fixed.

## Interpreting results

All latencies are reported in nanoseconds of guest time with `min/mean/p50/p90/p99/max` summaries. Each result also records the `CLOCK_MONOTONIC` clock, CPU placement, and counts of zero and extreme samples (`>10us`, `>1ms`, `>10ms`, `>100ms`, and `>1s`). `timer_jitter` additionally records its warm-up count.

`-r <file>` on the three latency/synchronization benchmarks dumps raw samples in temporal collection order for correlating outliers with trace events. Statistics are computed from a private sorted copy and do not reorder the raw stream.
Sweeping the host-side `vtime_epoch` while running `smp_barrier` or `smp_pingpong` shows the skew-bound/parallelism trade-off directly.
