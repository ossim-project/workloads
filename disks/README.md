# Ossim Workloads

This directory contains disk images and configurations for running various workloads in QEMU VMs.

## Network Configuration

QEMU VMs require host network setup for bridged networking and internet access. The setup consists of three components:

1. **Linux bridges** - Virtual switches connecting VMs to the host
2. **NAT** - Network address translation for internet access
3. **DNS** - DNS forwarding via dnsmasq

### Prerequisites

Install dnsmasq on the host:

```bash
sudo apt install dnsmasq
```

### Network Topology

```
Internet
    |
[eno1] (or your internet interface)
    |
  (NAT)
    |
[br-ossim0] 10.10.10.1/24  (management network)
    |
  VMs: 10.10.10.100, 10.10.10.101, ...

[br-ossim1] 10.10.11.1/24  (provider network)
```

### Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `INTERNET_IF` | `eno1` | Host interface with internet access |
| `MANAGEMENT_BRIDGE` | `br-ossim0` | Management network bridge |
| `MANAGEMENT_BRIDGE_CIDR` | `10.10.10.1/24` | Management bridge IP |
| `PROVIDER_BRIDGE` | `br-ossim1` | Provider network bridge |
| `PROVIDER_BRIDGE_CIDR` | `10.10.11.1/24` | Provider bridge IP |

## QEMU Escape Character

The QEMU monitor escape character is automatically configured based on the environment:

| Environment | `QEMU_ECHR` | Key Sequence |
|-------------|-------------|--------------|
| Bare metal  | `0x01`      | Ctrl+A       |
| Inside QEMU | `0x14`      | Ctrl+T       |

This avoids conflicts when running nested QEMU (QEMU inside QEMU). On bare metal, the standard Ctrl+A escape works. When already inside a QEMU VM, Ctrl+T is used instead so it doesn't interfere with the outer QEMU's escape sequence.

To override manually:

```bash
make QEMU_ECHR=0x14 qemu-test
```

### Setup Commands

Run all commands from the `workloads/` directory:

```bash
# 1. Create Linux bridges
make -C .. setup-bridges

# 2. Set up NAT for internet access (specify your internet interface)
make -C .. INTERNET_IF=eno1 setup-nat

# 3. Start DNS forwarder (forwards to host's configured DNS)
make -C .. setup-dns
```

### Cleanup Commands

```bash
make -C .. cleanup-dns
make -C .. cleanup-nat
make -C .. cleanup-bridges
```

### What Each Command Does

#### `setup-bridges`
- Creates `br-ossim0` and `br-ossim1` Linux bridge interfaces
- Assigns IP addresses to bridges (gateway IPs for VMs)
- Configures QEMU bridge permissions
- Disables bridge netfilter to avoid iptables interference

#### `setup-nat`
- Enables IP forwarding (`net.ipv4.ip_forward=1`)
- Adds iptables FORWARD rules for bridge-to-internet traffic
- Adds MASQUERADE rule for NAT

#### `setup-dns`
- Starts dnsmasq listening on bridge IPs (10.10.10.1, 10.10.11.1)
- Auto-detects and forwards to the host's configured DNS servers
- VMs use the gateway IP as their DNS server

### Why dnsmasq Instead of Public DNS (8.8.8.8)?

Many corporate and campus networks block outbound DNS traffic (port 53) to external servers like `8.8.8.8`, requiring queries to go through their internal DNS. The dnsmasq forwarder solves this by auto-detecting and forwarding to the host's configured DNS servers, making VM images portable across different network environments without modification.

### VM Network Configuration

VMs should be configured with:
- **IP**: Static IP in the bridge subnet (e.g., `10.10.10.100/24`)
- **Gateway**: Bridge IP (e.g., `10.10.10.1`)
- **DNS**: Bridge IP (e.g., `10.10.10.1`)

Example netplan configuration (`/etc/netplan/*.yaml`):

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp0s2:
      dhcp4: false
      addresses:
        - 10.10.10.100/24
      nameservers:
        addresses:
          - 10.10.10.1
      routes:
        - to: default
          via: 10.10.10.1
```

### Troubleshooting

#### VMs can ping gateway but not internet
- Verify NAT is set up: `sudo iptables -t nat -L POSTROUTING -n -v`
- Check IP forwarding: `cat /proc/sys/net/ipv4/ip_forward` (should be `1`)
- Re-run: `make INTERNET_IF=<your-interface> setup-nat`

#### DNS not working
- Check dnsmasq is running: `ps aux | grep dnsmasq`
- Test directly: `dig @10.10.10.1 google.com` (from VM)
- Re-run: `make setup-dns`

#### Port 53 blocked (external DNS like 8.8.8.8 doesn't work)
- Some networks block external DNS. Use the bridge DNS forwarder instead.
- Ensure VMs use `10.10.10.1` as DNS, not `8.8.8.8`
