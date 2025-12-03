set -euxo pipefail

HOSTNAME=node1

grow_disk.sh

mount_input_fs.sh /mnt
pushd /mnt

hostnamectl set-hostname $HOSTNAME

install -m 600 netplan/${HOSTNAME}.yaml /etc/netplan/99-netplan-config.yaml
netplan apply
