#!/bin/bash
# Exp S1: cost and robustness of ossim scheduling.
#
# Replaces the older S1a (overhead) and S1b (overcommit fairness) with the
# merged design from microbenchmark-suggestions.md (addendum):
#
#   physical                bare-metal baseline
#   clean.noossim           1+ VMs, ossim disabled, no host noise
#   clean.ossim             1+ VMs, ossim sync enabled, no host noise
#   perturbed.noossim       2 VMs pinned to disjoint host CPUs; host stress-ng
#                           pinned to VM-0's CPUs only; ossim disabled
#   perturbed.ossim         same, ossim sync enabled
#
# Headline metric: events / guest-virtual-second across VMs (skew-invariant
# under ossim) and events / host-second (slows down the perturbed VM under
# ossim, by design). Per-VM samples enable Jain/CV/spread via analyze/skew.py.
#
# CONFIG envvars:
#   PHASE        physical | clean.noossim | clean.ossim
#                | perturbed.noossim | perturbed.ossim
#   N_VMS        clean phases: number of VMs (default 2)
#   VM0_CPUSET   host CPUs for VM 0 (default "0-1")
#   VM1_CPUSET   host CPUs for VM 1 (default "2-3")
#   NOISE_CPUSET CPUs for host stress-ng (default = VM0_CPUSET)
#   NOISE_WORKERS host stress-ng worker count (default = vCPUs in NOISE_CPUSET)
#   TIME_S       guest-monotonic bench duration (default 30)
#   SAMPLE_MS    cpu_loop sampling interval (default 100)
#   INNER        cpu_loop inner-loop trip count per tick (default 100000)
#   SESSION      tmux session name

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORKLOADS_ROOT="$(cd "$HERE/../.." && pwd)"
export WORKLOADS_ROOT
# shellcheck source=common.sh
source "$HERE/common.sh"

PHASE="${PHASE:-clean.ossim}"
N_VMS="${N_VMS:-2}"
VM0_CPUSET="${VM0_CPUSET:-0-1}"
VM1_CPUSET="${VM1_CPUSET:-2-3}"
NOISE_CPUSET="${NOISE_CPUSET:-$VM0_CPUSET}"
NOISE_PROFILE="${NOISE_PROFILE:-cpu}"
NOISE_WORKERS="${NOISE_WORKERS:-2}"
TIME_S="${TIME_S:-10}"
SAMPLE_MS="${SAMPLE_MS:-100}"
INNER="${INNER:-100000}"
SESSION="${SESSION:-ossim-s1-${PHASE//./_}}"

phase_label() { echo "${PHASE//./_}"; }
exp_phase_dir() { echo "$EXP_OUT_BASE/exp_s1/$(phase_label)"; }

# --------------------------------------------------------------------------
# physical: bare-metal baseline. No VM, no ossim involved.
# --------------------------------------------------------------------------
if [[ "$PHASE" == "physical" ]]; then
    out="$(exp_phase_dir)/cpu_host.json"
    bracket="$(exp_phase_dir)/cpu_host.host_bracket.json"
    mkdir -p "$(dirname "$out")"
    echo "Exp S1 [physical]: cpu_loop on bare metal, time=${TIME_S}s"

    EXP_LABEL="$(phase_label)" VM_LABEL="host" \
        python3 "$HOST_MICROBENCH/host_bracket.py" \
            --output "$bracket" --phase start --benchmark cpu_loop --label host
    EXP_LABEL="$(phase_label)" VM_LABEL="host" \
        python3 "$HOST_MICROBENCH/bench_cpu.py" \
            --output "$out" --mode loop \
            --time "$TIME_S" --sample-ms "$SAMPLE_MS" --inner "$INNER" \
            --label host
    EXP_LABEL="$(phase_label)" VM_LABEL="host" \
        python3 "$HOST_MICROBENCH/host_bracket.py" \
            --output "$bracket" --phase end --benchmark cpu_loop --label host
    echo "Result: $out"
    echo "Bracket: $bracket"
    exit 0
fi

# --------------------------------------------------------------------------
# VM phases: spawn N VMs, run cpu_loop in each via barrier-coordinated start.
# --------------------------------------------------------------------------
case "$PHASE" in
    clean.noossim|clean.ossim)
        instances=()
        for ((n=0; n<N_VMS; n++)); do instances+=("$n"); done
        ;;
    perturbed.noossim|perturbed.ossim)
        instances=(0 1)
        N_VMS=2
        ;;
    *) echo "unknown PHASE=$PHASE" >&2; exit 2 ;;
esac

is_ossim=0
[[ "$PHASE" == *.ossim ]] && is_ossim=1
is_perturbed=0
[[ "$PHASE" == perturbed.* ]] && is_perturbed=1

# Set the base ossim mode BEFORE launching guests so vtasks register
# correctly during boot. Always disable first so the ossim subsystem is
# reset (any leftover state from a previous run goes away). enable-sync is
# intentionally NOT done here: with sync on, guest boot slows down
# significantly; the operator-facing message below reminds to enable it
# after VMs finish booting.
echo "Resetting ossim..."
# Best-effort: disable may fail if ossim was never enabled in this session
# (Connection failed). The intent is just to clear any leftover state.
ossimctl disable || true
if (( is_ossim )); then
    echo "Configuring ossim: enable (sync deferred until after VM boot)"
    ossimctl enable
fi

clear_barriers "${instances[@]}"
# Drop stale result JSONs from any previous run of the same phase, otherwise
# wait_for_result would return immediately on leftover data and the phase
# would record garbage.
clear_results "cpu_$(phase_label).json" "${instances[@]}"

phase_lbl="$(phase_label)"
ossim_mode_str="$([[ $is_ossim -eq 1 ]] && echo "sync" || echo "disabled")"
declare -A vm_cpusets=()
for n in "${instances[@]}"; do
    case "$n" in
        0) cpuset="$VM0_CPUSET" ;;
        1) cpuset="$VM1_CPUSET" ;;
        *) cpuset="" ;;
    esac
    vm_cpusets[$n]="$cpuset"
    spawn_vm_tmux "$SESSION" "$n" "$cpuset"

    # Drop a per-instance start_bench.sh into the instance's output dir
    # (which appears in the guest at /out). Each script bakes in HOST_CPUSET
    # so the per-VM host pinning lands in metadata.host_cpuset, and the
    # operator only has to type a short single-line command.
    out_dir="$(instance_output_dir "$n")"
    mkdir -p "$out_dir"
    cat > "$out_dir/start_bench.sh" <<EOS
#!/bin/bash
# Auto-generated by exp_s1.sh for VM $n in phase $phase_lbl.
exec env \\
    BENCH=/input/bench_cpu.py \\
    OUTPUT=/out/cpu_${phase_lbl}.json \\
    VM_LABEL=vm-$n \\
    OSSIM_MODE=$ossim_mode_str \\
    EXP_LABEL=$phase_lbl \\
    HOST_CPUSET="$cpuset" \\
    ARGS="--mode loop --time $TIME_S --sample-ms $SAMPLE_MS --inner $INNER" \\
    /input/run_in_vm.sh
EOS
    chmod +x "$out_dir/start_bench.sh"
done

phase_dir="$(exp_phase_dir)"
mkdir -p "$phase_dir"
bracket="$phase_dir/cpu_loop.host_bracket.json"

cat <<EOF

tmux session: $SESSION  (attach with: tmux attach -t $SESSION)

Wait for the VMs to finish booting, then:
$( (( is_ossim )) && echo "  - On the host:  ossimctl enable-sync" )
  - In each VM (windows vm-N):
      
      export N=[node ID, e.g. 0]
      bash /out/start_bench.sh

    (per-VM env, including HOST_CPUSET, is baked into that script)

Once all VMs print "[vm-N] waiting on barrier", press Enter here to release.
EOF
read -r _

# Host-wall start before barrier release. Export EXP_LABEL/VM_LABEL/OSSIM_MODE
# so collect_metadata() in lib_results.py picks them up — without this the
# bracket file's metadata block is empty. HOST_CPUSET on the host bracket is
# a comma-joined summary of per-VM pinning (each VM's own cpuset is recorded
# in its own result JSON via /out/start_bench.sh).
host_pinning_summary=""
for n in "${instances[@]}"; do
    [[ -n "$host_pinning_summary" ]] && host_pinning_summary+=","
    host_pinning_summary+="vm-$n=${vm_cpusets[$n]}"
done
export EXP_LABEL="$(phase_label)"
export VM_LABEL="host"
export OSSIM_MODE="$([[ $is_ossim -eq 1 ]] && echo "sync" || echo "disabled")"
export HOST_CPUSET="$host_pinning_summary"
host_bracket_start "$bracket" cpu_loop "$(phase_label)"

# Optional host-side noise pinned to one VM's cpuset
noise_pid=""
if (( is_perturbed )); then
    echo "Starting host stress-ng on cpus $NOISE_CPUSET (workers=$NOISE_WORKERS, profile=$NOISE_PROFILE)..."
    noise_pid="$(start_host_noise "$NOISE_CPUSET" "$NOISE_WORKERS" "$NOISE_PROFILE")"
    echo "  noise pid=$noise_pid"
fi

release_barrier "${instances[@]}"
echo "Barrier released; waiting for results..."

result_paths=()
for n in "${instances[@]}"; do
    p="$(instance_output_dir "$n")/cpu_$(phase_label).json"
    result_paths+=("$p")
    wait_for_result "$p"
    echo "  vm-$n -> $p"
done

stop_host_noise "$noise_pid"
host_bracket_end "$bracket" cpu_loop "$(phase_label)"

# Aggregate per-VM results into the phase directory and run skew analysis
collected=()
for n in "${instances[@]}"; do
    src="$(instance_output_dir "$n")/cpu_$(phase_label).json"
    dst="$phase_dir/cpu_vm-$n.json"
    cp "$src" "$dst"
    collected+=("$dst")
done

if (( ${#collected[@]} >= 2 )); then
    python3 "$HOST_MICROBENCH/analyze/skew.py" "${collected[@]}" \
        --out "$phase_dir/skew_summary.json"
fi

echo
echo "Phase done."
echo "  per-VM:  $phase_dir/cpu_vm-*.json"
echo "  bracket: $bracket"
[[ ${#collected[@]} -ge 2 ]] && echo "  skew:    $phase_dir/skew_summary.json"
