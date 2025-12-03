bridge_script := $(d)bridge.py
nat_script := $(d)nat.py
dnsmasq_script := $(d)dnsmasq.py

dnsmasq_conf_dir := $(o)/dnsmasq

.PHONY: setup-bridges cleanup-bridges setup-nat cleanup-nat setup-dns cleanup-dns

setup-bridges:
	sudo python3 $(bridge_script) setup \
		--bridge-if $(MANAGEMENT_BRIDGE) \
		--bridge-cidr $(MANAGEMENT_BRIDGE_CIDR) \
		--prefix $(PREFIX)
	sudo python3 $(bridge_script) setup \
		--bridge-if $(PROVIDER_BRIDGE) \
		--bridge-cidr $(PROVIDER_BRIDGE_CIDR) \
		--prefix $(PREFIX)
	sudo modprobe br_netfilter || true
	sudo sysctl -w net.bridge.bridge-nf-call-iptables=0 || true
	sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0 || true
	sudo sysctl -w net.bridge.bridge-nf-call-arptables=0 || true

cleanup-bridges:
	sudo python3 $(bridge_script) cleanup --bridge-if $(MANAGEMENT_BRIDGE)
	sudo python3 $(bridge_script) cleanup --bridge-if $(PROVIDER_BRIDGE)

setup-nat:
	sudo python3 $(nat_script) setup \
		--bridge-if $(MANAGEMENT_BRIDGE) \
		--internet-if $(INTERNET_IF)
	sudo python3 $(nat_script) setup \
		--bridge-if $(PROVIDER_BRIDGE) \
		--internet-if $(INTERNET_IF)

cleanup-nat:
	sudo python3 $(nat_script) cleanup \
		--bridge-if $(MANAGEMENT_BRIDGE) \
		--internet-if $(INTERNET_IF)
	sudo python3 $(nat_script) cleanup \
		--bridge-if $(PROVIDER_BRIDGE) \
		--internet-if $(INTERNET_IF)

setup-dns:
	sudo python3 $(dnsmasq_script) setup \
		--bridge-if $(MANAGEMENT_BRIDGE) \
		--bridge-if $(PROVIDER_BRIDGE) \
		--conf-dir $(dnsmasq_conf_dir) \
		--pid-dir $(dnsmasq_conf_dir)

cleanup-dns:
	sudo python3 $(dnsmasq_script) cleanup \
		--conf-dir $(dnsmasq_conf_dir) \
		--pid-dir $(dnsmasq_conf_dir)
