MICROBENCH_DIMG_ISO_URL := https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
MICROBENCH_DIMG_CKSUM_URL := https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
MICROBENCH_DIMG_DISK_SIZE := 40G

MICROBENCH_VM_CPUS := 2
MICROBENCH_VM_MEMORY := 4G

microbench_dimg := $(call dimg_path,microbench)
DIMG_ALL += microbench

# Host-side directory containing the bench scripts that get mounted RO into
# every instance. Lives outside the disk image so we can iterate on a bench
# without rebuilding.
microbench_input_d := $(ROOT)/host_microbench

# Native helper binaries built into the input dir. Mounted RO into the VM,
# so they must exist on the host before launch.
microbench_native_tools := \
    $(microbench_input_d)/pchase/pchase \
    $(microbench_input_d)/cpu_loop/cpu_loop

.PHONY: build-microbench-tools
build-microbench-tools:
	$(MAKE) -C $(microbench_input_d)

$(microbench_native_tools):
	$(MAKE) -C $(microbench_input_d)

$(microbench_dimg): $(b)seed.raw $(d)install.sh $(base_hcl) $(PACKER)
	rm -rf $(@D)
	$(PACKER_RUN) build \
	-var "disk_size=$(MICROBENCH_DIMG_DISK_SIZE)" \
	-var "iso_url=$(MICROBENCH_DIMG_ISO_URL)" \
	-var "iso_cksum_url=$(MICROBENCH_DIMG_CKSUM_URL)" \
	-var "out_dir=$(@D)" \
	-var "out_name=$(@F)" \
	-var "cpus=$(IMAGE_BUILD_CPUS)" \
	-var "memory=$(IMAGE_BUILD_MEMORY)" \
	-var "seedimg=$(word 1,$^)" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "input_dir=$(microbench_input_d)" \
	-var "install_script=$(word 2,$^)" \
	$(base_hcl)

$(b)seed.raw: $(d)user-data $(b)meta-data
	@mkdir -p $(@D)
	cloud-localds $@ $^

$(b)meta-data:
	@mkdir -p $(@D)
	tee $@ < /dev/null > /dev/null

# >>> Multi-instance launching for experiments
# Usage:
#   make qemu-microbench-instance N=0
#   make qemu-microbench-instance N=1 [N=2 ...]
# Each instance gets its own qcow2 overlay over the shared $(microbench_dimg)
# backing file plus a writable host-shared output directory at
# $(microbench_inst_output).
N ?= 0
microbench_inst_d := $(o)instance-$(N)
microbench_inst_overlay := $(microbench_inst_d)/disk.qcow2
microbench_inst_output := $(microbench_inst_d)/output

# Optional host-CPU pinning. Pass e.g. QEMU_CPUSET=0-3 to confine the QEMU
# process (and all its threads) to host CPUs 0-3. Used by S1 to pin VMs to
# disjoint host CPU sets for the perturbed-noise condition.
QEMU_CPUSET ?=
QEMU_LAUNCHER := $(if $(QEMU_CPUSET),taskset -c $(QEMU_CPUSET),)

$(microbench_inst_overlay): $(microbench_dimg)
	@mkdir -p $(microbench_inst_d)
	$(QEMU_IMG) create -f qcow2 -F qcow2 -b $$(realpath --relative-to=$(@D) $<) $@

.PHONY: qemu-microbench-instance
qemu-microbench-instance: $(microbench_inst_overlay) $(microbench_native_tools)
	@mkdir -p $(microbench_inst_output)
	$(QEMU_LAUNCHER) $(OSSIM_QEMU) -name ossim-microbench-$(N) \
	-machine q35,accel=kvm -enable-ossim \
	-cpu host -smp $(MICROBENCH_VM_CPUS) -m $(MICROBENCH_VM_MEMORY) \
	-object memory-backend-memfd,id=mem0,size=$(MICROBENCH_VM_MEMORY),share=on \
	-numa node,memdev=mem0 \
	-drive file=$(microbench_inst_overlay),media=disk,format=qcow2,if=virtio,index=0 \
	$(QEMU_USER_NET_ARGS) \
	-fsdev local,id=input_fsdev,path=$$(realpath $(microbench_input_d)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-fsdev local,id=output_fsdev,path=$$(realpath $(microbench_inst_output)),security_model=mapped-xattr \
	-device virtio-9p-pci,fsdev=output_fsdev,mount_tag=output_fsdev \
	-boot c \
	-display none -serial mon:stdio
# <<< Multi-instance launching for experiments
