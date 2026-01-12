MICROBENCH_DIMG_ISO_URL := https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
MICROBENCH_DIMG_CKSUM_URL := https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
MICROBENCH_DIMG_DISK_SIZE := 40G

MICROBENCH_VM_CPUS ?= 2
MICROBENCH_VM_CPU_PIN ?= 2,3
MICROBENCH_VM_MEM ?= 4G

MICROBENCH_VM_CPU_OPTS := -cpu host -smp $(MICROBENCH_VM_CPUS) -ossim-vcpu-pin $(MICROBENCH_VM_CPU_PIN)
MICROBENCH_VM_MEM_OPTS := -m $(MICROBENCH_VM_MEM) \
	-object memory-backend-memfd,id=mem0,size=$(MICROBENCH_VM_MEM),share=on \
	-numa node,memdev=mem0 \

microbench_dimg := $(call dimg_path,microbench)
DIMG_ALL += microbench

# Host-side directory containing the bench scripts that get mounted RO into
# every instance. Lives outside the disk image so we can iterate on a bench
# without rebuilding.
microbench_input_d := $(ROOT)/microbench

# Native helper binaries built into the input dir. Mounted RO into the VM,
# so they must exist on the host before launch.
microbench_native_tools := \
    $(microbench_input_d)/timer_jitter/timer_jitter \
    $(microbench_input_d)/smp_barrier/smp_barrier \
    $(microbench_input_d)/smp_pingpong/smp_pingpong

.PHONY: build-microbench-tools
build-microbench-tools:
	$(MAKE) -C $(microbench_input_d)

$(microbench_native_tools):
	$(MAKE) -C $(microbench_input_d)

# $(microbench_dimg) is the on-disk file target. It deliberately has NO
# build recipe — the only way to (re)build it is via the explicit
# `make dimg-microbench` target defined below. If anything (e.g. an
# instance overlay) depends on this file and it's missing, the recipe
# here fires and errors out loudly instead of silently rebuilding.
# Removing the upstream dep list (install.sh, seed.raw, base_hcl,
# PACKER) means an out-of-date install.sh never triggers an implicit
# rebuild — the operator must run `make dimg-microbench` explicitly.
$(microbench_dimg):
	@echo "ERROR: $@ does not exist." >&2
	@echo "       Run 'make dimg-microbench' to build the microbench disk image." >&2
	@exit 1

# Explicit user-facing entrypoint for (re)building the microbench disk
# image. This is where the real packer build lives. The static pattern
# rule in disks/rules.mk filters out 'microbench' so this explicit
# rule is the only definition of `dimg-microbench`.
.PHONY: dimg-microbench
dimg-microbench: $(b)seed.raw $(d)install.sh $(base_hcl) $(PACKER)
	rm -rf $(dir $(microbench_dimg))
	$(PACKER_RUN) build \
	-var "disk_size=$(MICROBENCH_DIMG_DISK_SIZE)" \
	-var "iso_url=$(MICROBENCH_DIMG_ISO_URL)" \
	-var "iso_cksum_url=$(MICROBENCH_DIMG_CKSUM_URL)" \
	-var "out_dir=$(dir $(microbench_dimg))" \
	-var "out_name=$(notdir $(microbench_dimg))" \
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

# >>> Quick variant: the microbench image overlaid with the shared
# quick-shell init override (disks/install-quick.sh) for fast interactive
# debugging of the bench guest. Follows the same explicit-build
# discipline as the main microbench image: the file target below only
# errors, and `make dimg-microbench-quick` is the real build.
microbench_quick_dimg := $(call dimg_path,microbench-quick)
DIMG_ALL += microbench-quick

microbench_quick_run := $(o)quick/run

$(microbench_quick_dimg):
	@echo "ERROR: $@ does not exist." >&2
	@echo "       Run 'make dimg-microbench-quick' to build the microbench-quick disk image." >&2
	@exit 1

.PHONY: dimg-microbench-quick
dimg-microbench-quick: $(microbench_dimg) $(quick_install_sh) $(extend_noinput_hcl) $(PACKER)
	rm -rf $(dir $(microbench_quick_dimg))
	$(PACKER_RUN) build \
	-var "base_img=$(word 1,$^)" \
	-var "disk_size=$(MICROBENCH_DIMG_DISK_SIZE)" \
	-var "cpus=$(IMAGE_BUILD_CPUS)" \
	-var "memory=$(IMAGE_BUILD_MEMORY)" \
	-var "out_dir=$(dir $(microbench_quick_dimg))" \
	-var "out_name=$(notdir $(microbench_quick_dimg))" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "install_script=$(word 2,$^)" \
	-var "use_backing_file=true" \
	$(extend_noinput_hcl)

.PHONY: qemu-microbench-quick
qemu-microbench-quick: $(microbench_quick_dimg) $(microbench_native_tools)
	@mkdir -p $(microbench_quick_run)
	$(OSSIM_QEMU) -name ossim-microbench-quick \
	-machine q35,accel=kvm -enable-ossim \
	$(MICROBENCH_VM_CPU_OPTS) \
	$(MICROBENCH_VM_MEM_OPTS) \
	-drive file=$(microbench_quick_dimg),media=disk,format=qcow2,if=virtio,index=0 \
	-fsdev local,id=input_fsdev,path=$$(realpath $(microbench_input_d)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-fsdev local,id=run_fsdev,path=$$(realpath $(microbench_quick_run)),security_model=mapped-xattr \
	-device virtio-9p-pci,fsdev=run_fsdev,mount_tag=run_fsdev \
	-boot c \
	-display none -serial mon:stdio
# <<< Quick variant

# >>> Multi-instance launching for experiments
# Usage:
#   make qemu-microbench-instance N=0
#   make qemu-microbench-instance N=1 [N=2 ...]
# Each instance gets its own qcow2 overlay over the shared $(microbench_dimg)
# backing file plus a writable host-shared output directory at
# $(microbench_inst_run).
N ?= 0
microbench_inst_d := $(o)instance-$(N)
microbench_inst_overlay := $(microbench_inst_d)/disk.qcow2
microbench_inst_run := $(microbench_inst_d)/run

# Per-instance overlay: depends on $(microbench_dimg) so the overlay
# gets regenerated automatically when the operator rebuilds the dimg
# (via `make dimg-microbench`). With the dimg target above refusing
# to build implicitly (no recipe), this dependency can never *trigger*
# an image rebuild — it just propagates new image content forward to
# the overlay when the dimg has actually been updated.
$(microbench_inst_overlay): $(microbench_dimg)
	@mkdir -p $(microbench_inst_d)
	$(QEMU_IMG) create -f qcow2 -F qcow2 -b $$(realpath --relative-to=$(@D) $<) $@

.PHONY: qemu-microbench-instance
qemu-microbench-instance: $(microbench_inst_overlay) $(microbench_native_tools)
	@mkdir -p $(microbench_inst_run)
	$(OSSIM_QEMU) -name ossim-microbench-$(N) \
	-machine q35,accel=kvm -enable-ossim \
	$(MICROBENCH_VM_CPU_OPTS) \
	$(MICROBENCH_VM_MEM_OPTS) \
	-drive file=$(microbench_inst_overlay),media=disk,format=qcow2,if=virtio,index=0 \
	-fsdev local,id=input_fsdev,path=$$(realpath $(microbench_input_d)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-fsdev local,id=run_fsdev,path=$$(realpath $(microbench_inst_run)),security_model=mapped-xattr \
	-device virtio-9p-pci,fsdev=run_fsdev,mount_tag=run_fsdev \
	-boot c \
	-display none -serial mon:stdio
# <<< Multi-instance launching for experiments
