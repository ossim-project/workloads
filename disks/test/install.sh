cat <<'EOF' > /usr/local/bin/mount_input_fs.sh
#!/bin/bash

MNT_DIR=${1:-/mnt}

sudo mount -t 9p -o trans=virtio,ro,cache=loose input_fsdev $MNT_DIR
EOF
chmod +x /usr/local/bin/mount_input_fs.sh
