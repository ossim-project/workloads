DEV_DIMG_ISO_URL := https://cloud-images.ubuntu.com/questing/current/questing-server-cloudimg-amd64.img
DEV_DIMG_CKSUM_URL := https://cloud-images.ubuntu.com/questing/current/SHA256SUMS
DEV_DIMG_DISK_SIZE := 100G

DEV_VM_CPUS := 32
DEV_VM_MEMORY := 64G
DEV_VM_SSH_FORWARD_PORT := 12222
DEV_VM_CODE_SERVER_PORT := 8080
DEV_VM_CODE_SERVER_FORWARD_PORT := 8082
DEV_VM_VIRTIOFS_SOCK := /tmp/ossim_dev_virtiofs.sock

DEV_VM_MOUNT_DIR ?= $(abspath ../$(ROOT))

dev_dimg := $(call dimg_path,dev)
DIMG_ALL += dev

$(dev_dimg): $(b)seed.raw $(d)install.sh $(base_hcl) $(PACKER)
	rm -rf $(@D)
	$(PACKER_RUN) build \
	-var "disk_size=$(DEV_DIMG_DISK_SIZE)" \
	-var "iso_url=$(DEV_DIMG_ISO_URL)" \
	-var "iso_cksum_url=$(DEV_DIMG_CKSUM_URL)" \
	-var "out_dir=$(@D)" \
	-var "out_name=$(@F)" \
	-var "cpus=$(IMAGE_BUILD_CPUS)" \
	-var "memory=$(IMAGE_BUILD_MEMORY)" \
	-var "seedimg=$(word 1,$^)" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "input_dir=$(ROOT)" \
	-var "install_script=$(word 2,$^)" \
	$(base_hcl)

$(b)seed.raw: $(d)user-data $(b)meta-data
	@mkdir -p $(@D)
	cloud-localds $@ $^

$(b)meta-data:
	@mkdir -p $(@D)
	tee $@ < /dev/null > /dev/null

# Run make dev-dimg manually before running this
.PHONY: qemu-dev
qemu-dev: $(DEV_VM_VIRTIOFS_SOCK)
	$(QEMU) -machine q35,accel=kvm -cpu host -smp $(DEV_VM_CPUS) -m $(DEV_VM_MEMORY) \
	-object memory-backend-memfd,id=mem0,size=$(DEV_VM_MEMORY),share=on \
	-numa node,memdev=mem0 \
	-drive file=$(dev_dimg),media=disk,format=qcow2,if=virtio,index=0 \
	-netdev user,id=user-net,hostfwd=tcp::$(DEV_VM_SSH_FORWARD_PORT)-:22,hostfwd=tcp::$(DEV_VM_CODE_SERVER_FORWARD_PORT)-:${DEV_VM_CODE_SERVER_PORT} \
	-device virtio-net-pci,netdev=user-net \
	-chardev socket,id=char0,path=$(DEV_VM_VIRTIOFS_SOCK) \
	-device vhost-user-fs-pci,chardev=char0,tag=share_fsdev \
	-boot c \
	-display none -serial mon:stdio

.PHONY: dev-virtiofs
dev-virtiofs:
	rm -f $(DEV_VM_VIRTIOFS_SOCK)
	/usr/libexec/virtiofsd \
		--socket-path=$(DEV_VM_VIRTIOFS_SOCK) \
		--shared-dir $(DEV_VM_MOUNT_DIR) \
		--cache always \
		--sandbox none \
		--log-level debug

