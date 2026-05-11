#!/bin/bash
# In-VM convenience: mount, wait on barrier, run a bench script.
#
# Designed to be the single line an operator pastes into each VM's tmux
# pane. The host driver creates /out/start once all VMs are up.
#
# Required env:
#   BENCH      path to bench script under /input (e.g. /input/bench_cpu.py)
#   OUTPUT     output JSON path (e.g. /out/cpu_<label>.json)
#   VM_LABEL   identifier for this VM (e.g. vm-0, victim, neighbor)
# Optional env:
#   BARRIER    barrier file path (default /out/start)
#   ARGS       extra args appended to the bench invocation
#   OSSIM_MODE annotation written into the result JSON metadata
#
# Example:
#   BENCH=/input/bench_cpu.py OUTPUT=/out/cpu_clean.json VM_LABEL=vm-0 \
#     ARGS="--mode loop --time 30" /input/run_in_vm.sh

set -euo pipefail

: "${BENCH:?BENCH must be set}"
: "${OUTPUT:?OUTPUT must be set}"
: "${VM_LABEL:?VM_LABEL must be set}"
BARRIER="${BARRIER:-/out/start}"
ARGS="${ARGS:-}"

# /input and /out are auto-mounted via fstab at boot. Re-mount manually
# only if something has unmounted them since.
if ! mountpoint -q /input 2>/dev/null; then
    sudo /usr/local/bin/mount_input_fs.sh /input
fi
if ! mountpoint -q /out 2>/dev/null; then
    sudo /usr/local/bin/mount_output_fs.sh /out
fi

echo "[$VM_LABEL] waiting on barrier $BARRIER ..."
# Ready marker: signals the host driver (run_exp.sh / exp_s1.sh
# automation) that this guest has reached the barrier-wait state and
# is safe to release. Marker is per-VM so the driver can wait for all
# guests deterministically before calling `ossimctl enable-sync` and
# releasing the barrier. The marker lives next to the barrier in /out,
# so the host sees it via the shared 9p mount.
: > "$(dirname "$BARRIER")/ready_$VM_LABEL"

# Sleep at 1Hz, not 10Hz: tight `sleep 0.1` polling has been observed to
# trigger '*** stack smashing detected ***' inside the guest under ossim
# sync (suspected ossim nanosleep / clock-source interaction). 1s is more
# than fast enough — barrier release is a one-shot event.
while [[ ! -f "$BARRIER" ]]; do sleep 1; done
echo "[$VM_LABEL] barrier hit; starting bench"

export VM_LABEL OSSIM_MODE OSSIM_VTIME_EPOCH_NS EXP_LABEL
exec python3 "$BENCH" --output "$OUTPUT" --label "$VM_LABEL" $ARGS

# # Pin the bench to guest CPU 0. With ossim sync, ossim_absorbed_ns is
# # per-vCPU, so each pvclock page sees a different system_time bias. If the
# # bench thread migrates between guest vCPUs, the vDSO reads from a
# # different page and CLOCK_MONOTONIC can ratchet forward to the
# # less-absorbed (more wall-tracking) value, locking in an inflated reading
# # for the rest of the run. Pinning eliminates that source of variance.
# exec taskset -c 0 python3 "$BENCH" --output "$OUTPUT" --label "$VM_LABEL" $ARGS