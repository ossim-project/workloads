#!/bin/bash
set -euo pipefail

mkdir -p /input /output

cat <<'EOF' > /usr/local/bin/mount_input_fs.sh
#!/bin/bash
MNT_DIR=${1:-/input}
sudo mkdir -p "$MNT_DIR"
sudo mount -t 9p -o trans=virtio,ro,cache=loose input_fsdev "$MNT_DIR"
EOF
chmod +x /usr/local/bin/mount_input_fs.sh

cat <<'EOF' > /usr/local/bin/mount_output_fs.sh
#!/bin/bash
MNT_DIR=${1:-/output}
sudo mkdir -p "$MNT_DIR"
sudo mount -t 9p -o trans=virtio,rw,cache=none,access=any,msize=104857600 \
    output_fsdev "$MNT_DIR"
EOF
chmod +x /usr/local/bin/mount_output_fs.sh
