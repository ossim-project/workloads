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
The default spin barrier stresses co-scheduling hardest; `-s` switches to a sleeping pthread barrier, which also exercises the cross-vCPU wake-up path.
Example: `smp_barrier -n 100000 -w 1000`.

`smp_pingpong/` measures cross-vCPU round-trip latency between two pinned threads.
The default spin mode bounces a shared atomic and shows raw co-run latency; `-f` sleeps in futex on every hop, adding the guest wake-up and the host scheduler's cross-vCPU kick path.
Example: `smp_pingpong -a 0 -b 1 -n 100000 -f`.

## Interpreting results

All latencies are reported in nanoseconds of guest time with `min/mean/p50/p90/p99/max` summaries; `-r <file>` on `timer_jitter` and `smp_pingpong` additionally dumps raw samples for offline analysis.
Sweeping the host-side `vtime_epoch` while running `smp_barrier` or `smp_pingpong` shows the skew-bound/parallelism trade-off directly.
