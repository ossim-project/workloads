#!/usr/bin/env bash
# Fix host CPU frequency policy for Ossim experiments.
#
# Typical use before S1:
#   sudo ./fix_host_cpu_frequency.sh apply
#   ./fix_host_cpu_frequency.sh status
#
# Restore later:
#   sudo ./fix_host_cpu_frequency.sh restore
#
# The script snapshots each CPU's governor/min/max before applying changes.
# It prefers sysfs so it works without cpupower. Optional max/min pinning is
# conservative: by default we only set governor=performance.

set -euo pipefail

SNAPSHOT_DEFAULT="/tmp/ossim-cpufreq-snapshot.tsv"
SNAPSHOT_PATH="${OSSIM_CPUFREQ_SNAPSHOT:-$SNAPSHOT_DEFAULT}"
GOVERNOR="${OSSIM_CPU_GOVERNOR:-performance}"
PIN_MIN_TO_MAX="${OSSIM_PIN_MIN_TO_MAX:-0}"
CPUS="${OSSIM_CPUS:-}"
ORIGINAL_ARGS=("$@")

usage() {
    cat <<'EOF'
Usage: fix_host_cpu_frequency.sh <status|apply|restore|snapshot>

Commands:
  status     Print current governor/frequency policy per CPU.
  snapshot   Save current policy to snapshot file only.
  apply      Snapshot current policy, then set governor to performance.
  restore    Restore policy from snapshot file.

apply/restore auto re-exec through sudo when not already root.

Environment:
  OSSIM_CPUFREQ_SNAPSHOT  Snapshot path [default: /tmp/ossim-cpufreq-snapshot.tsv]
  OSSIM_CPU_GOVERNOR      Governor to apply [default: performance]
  OSSIM_CPUS              CPU list/range to touch, e.g. "0-7,12" [default: all online]
  OSSIM_PIN_MIN_TO_MAX    If 1, also set scaling_min_freq=scaling_max_freq.
                          Useful for stricter fixed-frequency experiments, but
                          may fail on some drivers/hardware.

Notes:
  - apply/restore usually need root; the script invokes sudo automatically.
  - This script does not disable turbo/boost. If needed, handle that separately
    and record it in experiment metadata.
EOF
}

need_root_for_write() {
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
        if command -v sudo >/dev/null 2>&1; then
            echo "re-executing with sudo..." >&2
            exec sudo \
                OSSIM_CPUFREQ_SNAPSHOT="$SNAPSHOT_PATH" \
                OSSIM_CPU_GOVERNOR="$GOVERNOR" \
                OSSIM_CPUS="$CPUS" \
                OSSIM_PIN_MIN_TO_MAX="$PIN_MIN_TO_MAX" \
                "$0" "${ORIGINAL_ARGS[@]}"
        fi
        echo "error: this command writes cpufreq sysfs and sudo is not available" >&2
        exit 1
    fi
}

expand_cpu_list() {
    local spec="$1"
    if [[ -z "$spec" ]]; then
        if [[ -r /sys/devices/system/cpu/online ]]; then
            spec="$(cat /sys/devices/system/cpu/online)"
        else
            ls -d /sys/devices/system/cpu/cpu[0-9]* | sed 's/.*cpu//' | paste -sd, -
            return
        fi
    fi

    python3 - "$spec" <<'PY'
import sys
out=[]
for part in sys.argv[1].split(','):
    part=part.strip()
    if not part:
        continue
    if '-' in part:
        a,b=map(int, part.split('-',1))
        out.extend(range(a,b+1))
    else:
        out.append(int(part))
print(' '.join(map(str, sorted(set(out)))))
PY
}

policy_dir_for_cpu() {
    local cpu="$1"
    local p="/sys/devices/system/cpu/cpu${cpu}/cpufreq"
    [[ -d "$p" ]] || return 1
    printf '%s\n' "$p"
}

read_file_or_blank() {
    local f="$1"
    [[ -r "$f" ]] && cat "$f" || true
}

write_if_exists() {
    local f="$1" v="$2"
    if [[ -e "$f" ]]; then
        printf '%s\n' "$v" > "$f"
    fi
}

status() {
    printf 'snapshot=%s\n' "$SNAPSHOT_PATH"
    printf 'cpu\tdriver\tgovernor\tcur_khz\tmin_khz\tmax_khz\tavailable_governors\n'
    for cpu in $(expand_cpu_list "$CPUS"); do
        p="$(policy_dir_for_cpu "$cpu" || true)"
        [[ -n "${p:-}" ]] || continue
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
            "$cpu" \
            "$(read_file_or_blank "$p/scaling_driver")" \
            "$(read_file_or_blank "$p/scaling_governor")" \
            "$(read_file_or_blank "$p/scaling_cur_freq")" \
            "$(read_file_or_blank "$p/scaling_min_freq")" \
            "$(read_file_or_blank "$p/scaling_max_freq")" \
            "$(read_file_or_blank "$p/scaling_available_governors")"
    done

    if [[ -r /sys/devices/system/cpu/cpufreq/boost ]]; then
        printf '\nboost=%s\n' "$(cat /sys/devices/system/cpu/cpufreq/boost)"
    elif [[ -r /sys/devices/system/cpu/intel_pstate/no_turbo ]]; then
        printf '\nintel_pstate.no_turbo=%s\n' "$(cat /sys/devices/system/cpu/intel_pstate/no_turbo)"
    fi
}

snapshot() {
    mkdir -p "$(dirname "$SNAPSHOT_PATH")"
    : > "$SNAPSHOT_PATH"
    printf '# cpu\tdriver\tgovernor\tmin_khz\tmax_khz\n' >> "$SNAPSHOT_PATH"
    for cpu in $(expand_cpu_list "$CPUS"); do
        p="$(policy_dir_for_cpu "$cpu" || true)"
        [[ -n "${p:-}" ]] || continue
        printf '%s\t%s\t%s\t%s\t%s\n' \
            "$cpu" \
            "$(read_file_or_blank "$p/scaling_driver")" \
            "$(read_file_or_blank "$p/scaling_governor")" \
            "$(read_file_or_blank "$p/scaling_min_freq")" \
            "$(read_file_or_blank "$p/scaling_max_freq")" \
            >> "$SNAPSHOT_PATH"
    done
    echo "saved snapshot: $SNAPSHOT_PATH"
}

apply_policy() {
    need_root_for_write
    snapshot
    for cpu in $(expand_cpu_list "$CPUS"); do
        p="$(policy_dir_for_cpu "$cpu" || true)"
        [[ -n "${p:-}" ]] || continue

        if [[ -r "$p/scaling_available_governors" ]] && ! grep -qw "$GOVERNOR" "$p/scaling_available_governors"; then
            echo "warn: cpu$cpu does not list governor '$GOVERNOR'; available: $(cat "$p/scaling_available_governors")" >&2
            continue
        fi

        write_if_exists "$p/scaling_governor" "$GOVERNOR"

        if [[ "$PIN_MIN_TO_MAX" == "1" ]]; then
            max="$(read_file_or_blank "$p/scaling_max_freq")"
            if [[ -n "$max" ]]; then
                write_if_exists "$p/scaling_min_freq" "$max"
            fi
        fi
    done
    echo "applied governor=$GOVERNOR pin_min_to_max=$PIN_MIN_TO_MAX cpus=${CPUS:-online}"
}

restore_policy() {
    need_root_for_write
    if [[ ! -r "$SNAPSHOT_PATH" ]]; then
        echo "error: snapshot not found/readable: $SNAPSHOT_PATH" >&2
        exit 1
    fi

    while IFS=$'\t' read -r cpu driver gov min max; do
        [[ -z "${cpu:-}" || "$cpu" == \#* ]] && continue
        p="$(policy_dir_for_cpu "$cpu" || true)"
        [[ -n "${p:-}" ]] || continue

        # Restore max before min in case the old min is above the current max.
        [[ -n "${max:-}" ]] && write_if_exists "$p/scaling_max_freq" "$max"
        [[ -n "${min:-}" ]] && write_if_exists "$p/scaling_min_freq" "$min"
        [[ -n "${gov:-}" ]] && write_if_exists "$p/scaling_governor" "$gov"
    done < "$SNAPSHOT_PATH"
    echo "restored from snapshot: $SNAPSHOT_PATH"
}

cmd="${1:-}"
case "$cmd" in
    status) status ;;
    snapshot) snapshot ;;
    apply) apply_policy ;;
    restore) restore_policy ;;
    -h|--help|help|'') usage ;;
    *) echo "unknown command: $cmd" >&2; usage >&2; exit 2 ;;
esac
