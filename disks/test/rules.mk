TEST_DIMG_ISO_URL := https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
TEST_DIMG_CKSUM_URL := https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
TEST_DIMG_DISK_SIZE := 40G

TEST_VM_CPUS := 2
TEST_VM_MEMORY := 4G

test_dimg := $(call dimg_path,test)
DIMG_ALL += test

$(test_dimg): $(b)seed.raw $(d)install.sh $(base_hcl) $(PACKER)
	rm -rf $(@D)
	$(PACKER_RUN) build \
	-var "disk_size=$(TEST_DIMG_DISK_SIZE)" \
	-var "iso_url=$(TEST_DIMG_ISO_URL)" \
	-var "iso_cksum_url=$(TEST_DIMG_CKSUM_URL)" \
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

.PHONY: build-test-dimg
build-test-dimg:
	@rm -rf $(test_dimg)
	$(MAKE) $(test_dimg)

host_microbench_d := $(ROOT)/host_microbench

.PHONY: qemu-test
qemu-test:
	$(OSSIM_QEMU) -machine q35,accel=kvm -enable-ossim \
	-cpu host -smp $(TEST_VM_CPUS) -m $(TEST_VM_MEMORY) \
	-object memory-backend-memfd,id=mem0,size=$(TEST_VM_MEMORY),share=on \
	-numa node,memdev=mem0 \
	-drive file=$(test_dimg),media=disk,format=qcow2,if=virtio,index=0 \
    -fsdev local,id=input_fsdev,path=$(realpath $(host_microbench_d)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-boot c \
	-display none -serial mon:stdio

.PHONY: upstream-qemu-test
upstream-qemu-test:
	$(QEMU) -machine q35,accel=kvm \
	-cpu host -smp $(TEST_VM_CPUS) -m $(TEST_VM_MEMORY) \
	-object memory-backend-memfd,id=mem0,size=$(TEST_VM_MEMORY),share=on \
	-numa node,memdev=mem0 \
	-drive file=$(test_dimg),media=disk,format=qcow2,if=virtio,index=0 \
    -fsdev local,id=input_fsdev,path=$(realpath $(host_microbench_d)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-boot c \
	-display none -serial mon:stdio

