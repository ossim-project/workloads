# >>> Host networking configurations
INTERNET_IF ?= eno1
MANAGEMENT_BRIDGE ?= br-ossim0
MANAGEMENT_BRIDGE_CIDR ?= 10.10.10.1/24
PROVIDER_BRIDGE ?= br-ossim1
PROVIDER_BRIDGE_CIDR := 10.10.11.1/24
DEFAULT_BRIDGE ?= $(MANAGEMENT_BRIDGE)

QEMU_MAC_LIST := \
	52:54:00:11:11:01 \
	52:54:00:11:11:02 \
	52:54:00:11:11:03 \
	52:54:00:11:11:04 \
	52:54:00:11:11:05 \
	52:54:00:11:11:06
# <<< Host networking configurations

PACKER_VERSION := 1.11.2
PACKER_ZIP := $(b)packer.zip
PACKER_ZIP_URL := https://releases.hashicorp.com/packer/$(PACKER_VERSION)/packer_$(PACKER_VERSION)_linux_amd64.zip

PACKER := $(b)packer
PACKER_RUN := PACKER_PLUGIN_PATH=$(b).packer_plugins/ PACKER_CACHE_DIR=$(b).packer_cache/ $(PACKER)

IMAGE_BUILD_CPUS := $(shell echo $$((`nproc` / 4 * 3)))
IMAGE_BUILD_MEMORY := $(shell echo $$((`free -m | awk '/^Mem:/ {print $$4}'` / 4 * 3)))

OSSIM_QEMU := $(PREFIX)bin/qemu-system-x86_64
QEMU := /bin/qemu-system-x86_64
VIRT_COPY_OUT := virt-copy-out
QEMU_IMG := qemu-img

DIMG_O := $(o)

base_hcl := $(d)base.pkr.hcl
extend_hcl := $(d)extend.pkr.hcl
extend_noinput_hcl := $(d)extend_noinput.pkr.hcl

%disk.raw: %disk.qcow2
	$(QEMU_IMG) convert -f qcow2 -O raw $< $@ 

$(PACKER): $(PACKER_ZIP)
	mkdir -p $(@D)
	unzip -o -d $(@D) $<
	$(PACKER_RUN) plugins install github.com/hashicorp/qemu
	touch $@

$(PACKER_ZIP):
	mkdir -p $(@D)
	wget -O $@ $(PACKER_ZIP_URL)

define dimg_path
$(DIMG_O)/$(1)/disk.qcow2
endef

define disk_extend_rule
$(eval dst_disk := $(1))
$(eval src_disk := $(2))
$(eval install_script := $(3))
$(eval input_dir := $(4))

DIMG_ALL += $(dst_disk)
$(call dimg_path,$(dst_disk)): $(call dimg_path,$(src_disk)) $(install_script) $(extend_hcl) $(PACKER)
	$(MAKE) update-bigdata-input
	rm -rf $$(@D)
	$$(PACKER_RUN) build \
	-var "base_img=$$(word 1,$$^)" \
	-var "disk_size=40G" \
	-var "cpus=$$(IMAGE_BUILD_CPUS)" \
	-var "memory=$$(IMAGE_BUILD_MEMORY)" \
	-var "out_dir=$$(@D)" \
	-var "out_name=$$(@F)" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "install_script=$$(word 2,$$^)" \
	-var "input_dir=$(input_dir)" \
	-var "use_backing_file=true" \
	$$(extend_hcl)
endef

define disk_back_rule
$(eval dst_disk := $(1))
$(eval src_disk := $(2))
$(eval back := $(3))

DIMG_ALL += $(dst_disk)
$(call dimg_path,$(dst_disk)): $(call dimg_path,$(src_disk))
	@rm -rf $$@ && mkdir -p $$(@D)
	$(QEMU_IMG) create -f qcow2 -F qcow2 -b $$(realpath --relative-to=$$(@D) $$<) $$@
endef

define disk_flatten_rule
$(eval dst_disk := $(1))
$(eval src_disk := $(2))

DIMG_ALL += $(dst_disk)
$(call dimg_path,$(dst_disk)): $(call dimg_path,$(src_disk))
	@rm -rf $$@ && mkdir -p $$(@D)
	$(QEMU_IMG) convert -O qcow2 $$< $$@
endef

define disk_run_rule
$(eval disk := $(1))
$(eval cores := $(2))
$(eval memory := $(3))
$(eval mac := $(4))
$(eval input_dir := $(5))

.PHONY: qemu-$(disk)
qemu-$(disk): $(call dimg_path,$(disk))
	sudo -i $(OSSIM_QEMU) \
	-machine q35,accel=kvm -enable-ossim \
	-cpu host -smp $(cores) -m $(memory) \
	-drive file=$$<,media=disk,format=qcow2,if=virtio,index=0 \
	-netdev bridge,id=net-management,br=$$(DEFAULT_BRIDGE) \
	-device virtio-net-pci,netdev=net-management,mac=$(mac) \
    -fsdev local,id=input_fsdev,path=$(realpath $(input_dir)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-boot c \
	-display none -serial mon:stdio
endef

DIMG_ALL :=

$(eval $(call include_rules,$(d)utils/rules.mk))
$(eval $(call include_rules,$(d)bigdata/rules.mk))
$(eval $(call include_rules,$(d)database/rules.mk))
$(eval $(call include_rules,$(d)dev/rules.mk))
$(eval $(call include_rules,$(d)test/rules.mk))

.PRECIOUS: $(foreach dimg,$(DIMG_ALL),$(call dimg_path,$(dimg)))

.PHONY: $(addprefix dimg-,$(DIMG_ALL)) $(addprefix rebuild-dimg-,$(DIMG_ALL))

$(addprefix dimg-,$(DIMG_ALL)): dimg-%: $(DIMG_O)/%/disk.qcow2

$(addprefix rebuild-dimg-,$(DIMG_ALL)): rebuild-dimg-%:
	rm -rf $(call dimg_path,$*)
	$(MAKE) dimg-$*
	
