# Ossim Example Workloads

## Install dependencies

```sh
bash scripts/install_deps.sh
```

## Set up host networking

>**Note:** The setup assumes that: subnets `10.10.10.0/24` and `10.10.11.0/24` are free, the Internet interface is `eno1`. Please refer to the *Host Networking Configurations* section of `disks/rules.mk` for related configurations. You likely need to configure them either by setting environment variables or by directly updating them in `disks/rules.mk`. The networking configurations for disk images (e.g., `disks/bigdata/input/netplan`) should be also updated accordingly.

```sh
make setup-bridges setup-nat setup-dns
```

## Build disk images

**For big data workloads:**
```sh
make dimg-bigdata/node0 dimg-bigdata/node1 dimg-bigdata/node2
```

**For database workloads:**
```sh
make dimg-database/server
```

## Run disk images

>**Note:** Refer to the Ossim main repository to build and install dependencies including ossimd, ossimctl, and QEMU with Ossim integration.

>**Note:** Some commands keep running in the foreground. You may need to some commands in different terminals to keep the process running.

We take big data workloads as an example here. 

**Start ossimd:**
```sh
# Inside the root of Ossim main repository
make run-ossimd
```

**Disable synchronization mode to speed up:**
```sh
ossimctl disable_sync
```

**Start all nodes (in different terminals):**
```sh
make qemu-bigdata/node0
```
```sh
make qemu-bidata/node1
```
```sh
make qemu-bigdata/node2
```

**Login to the nodes and mount the input virtio file system:**

You can login to those nodes according to the networking configurations with username `ossim` and password `ossim`.

**Mount the input virtio file system inside the nodes:**

```sh
sudo mount_input_fs.sh /mnt
```

The file system maps `disks/bigdata/input` on the host to the guests.

**Run benchmarks interactively:**

Follow the instructions in `bigdata/README.md` to run benchmarks.

>**Note:** `bigdata/` contains all utilities for running the example big data benchmarks. It is copied to `disks/bigdta/input/workloads` during the disk image build process. So, it is only available insdie the guest at `/mnt/workloads/`.

