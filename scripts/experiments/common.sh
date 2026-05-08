# Shared helpers for experiment driver scripts. Sourced, not executed.
# Assumes the caller has set WORKLOADS_ROOT to ossim/workloads/.

set -euo pipefail

: "${WORKLOADS_ROOT:?WORKLOADS_ROOT must be set to ossim/workloads}"
OUT_BASE="${OSSIM_OUT_DIR:-$WORKLOADS_ROOT/out}/workloads"
EXP_OUT_BASE="$OUT_BASE/exps"
HOST_MICROBENCH="$WORKLOADS_ROOT/host_microbench"

instance_output_dir() {
    local n="$1"
    echo "$OUT_BASE/disks/microbench/instance-$n/output"
}

# Spawn a `make qemu-microbench-instance N=$1` inside a tmux window. Optional
# 3rd arg sets QEMU_CPUSET (e.g. "0-3") to pin QEMU to a host CPU subset.
spawn_vm_tmux() {
    local session="$1"; local n="$2"; local cpuset="${3:-}"
    local window="vm-$n"
    local make_cmd="make qemu-microbench-instance N=$n"
    if [[ -n "$cpuset" ]]; then
        make_cmd+=" QEMU_CPUSET=$cpuset"
    fi
    if ! tmux has-session -t "$session" 2>/dev/null; then
        tmux new-session -d -s "$session" -n "$window" \
            "cd '$WORKLOADS_ROOT' && $make_cmd; bash"
    else
        tmux new-window -t "$session" -n "$window" \
            "cd '$WORKLOADS_ROOT' && $make_cmd; bash"
    fi
}

# Block until $1 (a result JSON path) appears.
wait_for_result() {
    local path="$1"; local timeout="${2:-1800}"
    local waited_ms=0
    local timeout_ms=$((timeout * 1000))
    while [[ ! -s "$path" ]]; do
        sleep 0.5
        waited_ms=$((waited_ms + 500))
        if (( waited_ms >= timeout_ms )); then
            echo "timed out waiting for $path" >&2
            return 1
        fi
    done
}

# Drop the barrier file into every instance's output directory so all VMs
# unblock at (effectively) the same host-wall time.
release_barrier() {
    local instances=("$@")
    for n in "${instances[@]}"; do
        local d; d="$(instance_output_dir "$n")"
        mkdir -p "$d"
        : > "$d/start"
    done
}

# Remove any stale barrier files before starting a phase.
clear_barriers() {
    local instances=("$@")
    for n in "${instances[@]}"; do
        rm -f "$(instance_output_dir "$n")/start"
    done
}

# Remove any stale per-instance result JSONs for a given filename so
# wait_for_result doesn't return immediately on leftover output from a
# previous run. Pass: clear_results <result_filename> <instance>...
clear_results() {
    local fname="$1"; shift
    for n in "$@"; do
        rm -f "$(instance_output_dir "$n")/$fname"
    done
}

# Host-wall sidecar bracket. Calls before+after the guest run; both invocations
# point at the same OUTPUT. See host_microbench/host_bracket.py.
host_bracket_start() {
    local output="$1"; local benchmark="$2"; local label="${3:-}"
    python3 "$HOST_MICROBENCH/host_bracket.py" --output "$output" \
        --phase start --benchmark "$benchmark" --label "$label"
}
host_bracket_end() {
    local output="$1"; local benchmark="$2"; local label="${3:-}"
    python3 "$HOST_MICROBENCH/host_bracket.py" --output "$output" \
        --phase end --benchmark "$benchmark" --label "$label"
}

# Pin a host-side stress-ng workload to a specific cpuset. Background it and
# echo the PID. The caller is responsible for killing it. Used for the
# perturbed-VM condition in S1.
start_host_noise() {
    local cpuset="$1"; local workers="${2:-2}"; local profile="${3:-cpu}"
    case "$profile" in
        cpu)       local flags=(--cpu "$workers" --cpu-method matrixprod) ;;
        memory)    local flags=(--stream "$workers") ;;
        cache)     local flags=(--cache "$workers" --cache-level 3) ;;
        *) echo "unknown noise profile: $profile" >&2; return 2 ;;
    esac
    local log=/tmp/ossim-host-noise.log
    taskset -c "$cpuset" stress-ng "${flags[@]}" --metrics-brief \
        > "$log" 2>&1 &
    local pid=$!
    # Verify it actually started — if stress-ng exits immediately (bad args,
    # missing binary, taskset failure), we want to know now, not after a
    # phantom "perturbed" run.
    sleep 0.3
    if ! kill -0 "$pid" 2>/dev/null; then
        {
            echo "start_host_noise: stress-ng died immediately."
            echo "  cmd: taskset -c $cpuset stress-ng ${flags[*]} --metrics-brief"
            echo "  log: $log"
            if [[ -s "$log" ]]; then
                echo "  --- log (first 40 lines) ---"
                head -n 40 "$log" | sed 's/^/  | /'
            else
                echo "  (log empty — likely 'command not found' or taskset error)"
            fi
            if ! command -v stress-ng >/dev/null 2>&1; then
                echo "  hint: stress-ng not on PATH; install with: sudo apt-get install stress-ng"
            fi
        } >&2
        return 1
    fi
    echo "$pid"
}

stop_host_noise() {
    local pid="$1"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
}
