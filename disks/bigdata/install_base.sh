#!/bin/bash
# Base image setup for big data workloads using Docker
set -euxo pipefail

# ---------- Configuration ----------
USER_NAME=ossim

# Mount input directory from host
mount -t 9p -o trans=virtio,ro,cache=loose input_fsdev /mnt
install -m 755 /mnt/scripts/*.sh /usr/local/bin/

# ---------- Create non-root user with root privileges ----------
echo "Creating $USER_NAME user..."
useradd -m -s /bin/bash $USER_NAME
echo "$USER_NAME:$USER_NAME" | chpasswd
usermod -aG sudo $USER_NAME
# Allow passwordless sudo
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USER_NAME
chmod 440 /etc/sudoers.d/$USER_NAME

# ---------- SSH key setup for root user ----------
ROOT_SSH_DIR=/root/.ssh
mkdir -p $ROOT_SSH_DIR
ssh-keygen -t rsa -b 4096 -f $ROOT_SSH_DIR/id_rsa -N "" -C "root@ossim"
cat $ROOT_SSH_DIR/id_rsa.pub >> $ROOT_SSH_DIR/authorized_keys
chmod 700 $ROOT_SSH_DIR
chmod 600 $ROOT_SSH_DIR/id_rsa $ROOT_SSH_DIR/authorized_keys
chmod 644 $ROOT_SSH_DIR/id_rsa.pub

# ---------- SSH key setup for non-root user ----------
USER_SSH_DIR=/home/$USER_NAME/.ssh
mkdir -p $USER_SSH_DIR
ssh-keygen -t rsa -b 4096 -f $USER_SSH_DIR/id_rsa -N "" -C "$USER_NAME@ossim"
cat $USER_SSH_DIR/id_rsa.pub >> $USER_SSH_DIR/authorized_keys
chmod 700 $USER_SSH_DIR
chmod 600 $USER_SSH_DIR/id_rsa $USER_SSH_DIR/authorized_keys
chmod 644 $USER_SSH_DIR/id_rsa.pub
chown -R $USER_NAME:$USER_NAME $USER_SSH_DIR

# ---------- GRUB configuration ----------
GRUB_CFG_FILE=/etc/default/grub.d/50-cloudimg-settings.cfg
echo 'GRUB_DISABLE_OS_PROBER=true' >> $GRUB_CFG_FILE
echo 'GRUB_HIDDEN_TIMEOUT=0' >> $GRUB_CFG_FILE
echo 'GRUB_TIMEOUT=0' >> $GRUB_CFG_FILE
update-grub

# ---------- Install system dependencies ----------
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get install -y \
  qemu-guest-agent \
  sudo \
  curl \
  ca-certificates

# ---------- Install dependencies for big data frameworks ----------
pushd /mnt/workloads

echo "Running setup_deps.sh..."
bash fw/install_deps.sh

# Add user to docker group
usermod -aG docker $USER_NAME

# ---------- Pull Docker images for each framework ----------
echo "Initializing big data docker images..."

# Run init command for each framework
python3 fw/hdfs.py init
python3 fw/spark.py init
python3 fw/hive.py init
python3 fw/hbase.py init
python3 fw/flink.py init

popd

# ---------- Cleanup ----------
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "Base image setup complete!"
