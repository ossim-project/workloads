#!/bin/bash
# Provision the microbench disk image: bake bench dependencies and runtime
# 9p mount helpers. /input and /out are 9p shares from the host; instead of
# /etc/fstab we mount them explicitly from .bash_profile on autologin (see
# the autorun block below for why fstab was unreliable here).
# The bench scripts themselves stay on the host and are mounted RO via the
# input_fsdev tag, so editing a bench does not require rebuilding the image.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    python3 python-is-python3 python3-numpy \
    fio sysbench stress-ng numactl util-linux jq

mkdir -p /input /out

# Manual-mount helpers, used both by the autorun block below and for
# ad-hoc remounting (e.g. after umount).
cat <<'EOF' > /usr/local/bin/mount_input_fs.sh
#!/bin/bash
MNT_DIR=${1:-/input}
sudo mkdir -p "$MNT_DIR"
sudo mount -t 9p -o trans=virtio,ro,cache=loose input_fsdev "$MNT_DIR"
EOF
chmod +x /usr/local/bin/mount_input_fs.sh

cat <<'EOF' > /usr/local/bin/mount_output_fs.sh
#!/bin/bash
MNT_DIR=${1:-/out}
sudo mkdir -p "$MNT_DIR"
sudo mount -t 9p -o trans=virtio,rw,cache=none,access=any,msize=104857600 \
    output_fsdev "$MNT_DIR"
EOF
chmod +x /usr/local/bin/mount_output_fs.sh

# Auto-run a host-provided /out/start_bench.sh on serial-console autologin.
# Used by the run_exp.sh automation runner: the host drops start_bench.sh
# into the per-VM /out before launching QEMU, and the guest auto-executes
# it once the `ossim` user is autologged in on ttyS0. No network needed
# (intentional — user-net would let chrony slew CLOCK_REALTIME and defeat
# the ossim sync invariant; see workloads/disks/rules.mk).
#
# Idempotent: the guard `[[ -f /out/start_bench.sh ]]` skips the auto-run
# for ad-hoc / manual sessions where the host hasn't dropped a script.
# The auto-run replaces the interactive shell so the login session ends
# with the bench exit; on failure the guest stays logged in for debug.
install -o ossim -g ossim -m 0644 /dev/stdin /home/ossim/.bash_profile <<'EOF'
# Mount the host-shared 9p directories on autologin. We deliberately do
# NOT use /etc/fstab — the `nofail` fstab entries lost the boot race
# against autologin in practice, leaving /out unmounted and the autorun
# never finding start_bench.sh. Driving the mount from here gives the
# autorun full control over the timing and means we never race the
# initial check.
if ! findmnt -t 9p /input >/dev/null 2>&1; then
    /usr/local/bin/mount_input_fs.sh /input >/dev/null 2>&1 || true
fi
if ! findmnt -t 9p /out >/dev/null 2>&1; then
    /usr/local/bin/mount_output_fs.sh /out >/dev/null 2>&1 || true
fi

# Auto-run a host-provided bench launcher when the run_exp.sh runner has
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
        [[ -f /out/start_bench.sh ]] && break
        sleep 1
    done
    if [[ -f /out/start_bench.sh ]]; then
        # /run is 755 root, so the ossim user can't write the marker
        # directly. Use sudo (NOPASSWD per /etc/sudoers.d/ossim via
        # cloud-init user-data) so the next agetty respawn sees the
        # marker and skips the autorun.
        sudo touch /run/ossim_autorun_done
        exec bash /out/start_bench.sh
    fi
fi
EOF
