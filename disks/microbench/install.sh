#!/bin/bash
# Provision the microbench disk image: bake bench dependencies, runtime 9p
# mount helpers, and fstab entries so /input and /out come up at boot.
# The bench scripts themselves stay on the host and are mounted RO via the
# input_fsdev tag, so editing a bench does not require rebuilding the image.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    python3 python-is-python3 python3-numpy \
    fio sysbench stress-ng numactl util-linux jq

mkdir -p /input /out

# Auto-mount the host-shared 9p directories at boot. `nofail` lets the
# guest still boot if the QEMU was launched without one of the fsdevs.
cat <<'EOF' >> /etc/fstab
# ossim microbench: read-only host_microbench/ directory
input_fsdev  /input  9p  ro,trans=virtio,cache=loose,nofail  0  0
# ossim microbench: per-instance writable output directory
output_fsdev /out    9p  rw,trans=virtio,cache=none,access=any,msize=104857600,nofail  0  0
EOF

# Manual-mount helpers, kept for ad-hoc use (e.g. remounting after umount).
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
