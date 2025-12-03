set -euxo pipefail

HOSTNAME=server

grow_disk.sh

mount_input_fs.sh /mnt
pushd /mnt

hostnamectl set-hostname $HOSTNAME

install -m 600 netplan/${HOSTNAME}.yaml /etc/netplan/99-netplan-config.yaml
netplan apply
