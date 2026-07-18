#!/bin/bash
# Provision the microbench disk image: bake bench dependencies and the
# host-shared 9p mounts. ~ossim/input and ~ossim/run are 9p shares from
# the host (bench tools RO, per-instance run directory RW). Both live in
# /etc/fstab as noauto entries so they can be mounted and unmounted
# directly by path (`mount /home/ossim/input`), while the actual
# mounting is driven from .bash_profile on autologin — an auto-mounted
# fstab entry lost the boot race against autologin in practice, leaving
# the run share unmounted when the autorun looked for run.sh.
# The bench tools themselves stay on the host and are mounted RO via the
# input_fsdev tag, so editing a bench does not require rebuilding the
# image.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    python3 python-is-python3 python3-numpy \
    fio sysbench stress-ng numactl util-linux jq

# Mount points in the ossim user's home, wired up in /etc/fstab so that
# mount/umount work directly on the paths. noauto: systemd must not race
# autologin for these; .bash_profile below mounts them explicitly.
install -d -o ossim -g ossim /home/ossim/input /home/ossim/run

cat <<'EOF' >> /etc/fstab
input_fsdev /home/ossim/input 9p trans=virtio,ro,cache=loose,noauto,nofail 0 0
run_fsdev /home/ossim/run 9p trans=virtio,rw,cache=none,access=any,msize=104857600,noauto,nofail 0 0
EOF

# Auto-run a host-provided ~/run/run.sh on serial-console
# autologin. Used by the automation runner: the host drops
# run.sh into the per-VM run directory before launching QEMU,
# and the guest auto-executes it once the `ossim` user is autologged in
# on ttyS0. No network needed (intentional — user-net would let chrony
# slew CLOCK_REALTIME and defeat the ossim sync invariant; see
# workloads/disks/rules.mk).
#
# Idempotent: the guard `[[ -f "$HOME/run/run.sh" ]]` skips the
# auto-run for ad-hoc / manual sessions where the host hasn't dropped a
# script. The auto-run replaces the interactive shell so the login
# session ends with the bench exit; on failure the guest stays logged in
# for debug.
install -o ossim -g ossim -m 0644 /dev/stdin /home/ossim/.bash_profile <<'EOF'
# Mount the host-shared 9p directories on autologin via their fstab
# entries (noauto — see install.sh for why systemd must not mount these
# at boot). Driving the mount from here gives the autorun below full
# control over the timing, and `sudo umount ~/input` / `sudo mount
# ~/input` keep working for ad-hoc sessions.
if ! findmnt -t 9p "$HOME/input" >/dev/null 2>&1; then
    sudo mount "$HOME/input" >/dev/null 2>&1 || true
fi
if ! findmnt -t 9p "$HOME/run" >/dev/null 2>&1; then
    sudo mount "$HOME/run" >/dev/null 2>&1 || true
fi

# Auto-run a host-provided bench launcher when the automation runner has
# dropped one. Otherwise drop into an interactive shell as usual.
#
# The bench script (and its python child) runs in this same login
# session via exec, so when the bench exits the agetty autologin
# respawns a fresh bash and re-reads .bash_profile. An env-var guard
# wouldn't survive that re-entry; use a tmpfs marker in /run so the
# guard is per-boot but stable across login sessions, preventing the
# bench from looping after a normal completion. Gone on guest reboot.
if [[ ! -e /run/ossim_autorun_done ]]; then
    for _i in 1 2 3 4 5 6 7 8 9 10; do
        [[ -f "$HOME/run/run.sh" ]] && break
        sleep 1
    done
    if [[ -f "$HOME/run/run.sh" ]]; then
        # /run is 755 root, so the ossim user can't write the marker
        # directly. Use sudo (NOPASSWD per /etc/sudoers.d/ossim via
        # cloud-init user-data) so the next agetty respawn sees the
        # marker and skips the autorun.
        sudo touch /run/ossim_autorun_done
        exec bash "$HOME/run/run.sh"
    fi
fi
EOF
