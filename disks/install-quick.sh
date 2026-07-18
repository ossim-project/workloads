#!/bin/bash
set -euo pipefail

QUICK_INIT=/usr/local/sbin/ossim-quick-init
cat > "$QUICK_INIT" <<'EOF'
#!/bin/bash
set +e

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

mountpoint -q /proc || mount -t proc proc /proc
mountpoint -q /sys || mount -t sysfs sysfs /sys
mountpoint -q /dev || mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts
mountpoint -q /dev/pts || mount -t devpts devpts /dev/pts

printf '\nossim quick shell: exit will respawn /bin/bash instead of killing init.\n\n' \
    >/dev/console

while true; do
    setsid /bin/bash -l </dev/console >/dev/console 2>&1
    printf '\n/bin/bash exited; respawning quick shell in 1s.\n\n' >/dev/console
    sleep 1
done
EOF
chmod +x "$QUICK_INIT"

GRUB_CFG_FILE=/etc/default/grub.d/99-ossim-quick.cfg
cat > "$GRUB_CFG_FILE" <<EOF
# Preserve the kernel command line assembled by /etc/default/grub and earlier
# grub.d snippets, then append the quick-boot init override.
GRUB_CMDLINE_LINUX="\${GRUB_CMDLINE_LINUX:+\$GRUB_CMDLINE_LINUX }init=$QUICK_INIT"
EOF

update-grub
