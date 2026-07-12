QUICK_VM_CPUS ?= $(TEST_VM_CPUS)
QUICK_VM_MEMORY ?= $(TEST_VM_MEMORY)

quick_dimg := $(call dimg_path,quick)
DIMG_ALL += quick

$(quick_dimg): $(test_dimg) $(d)install.sh $(extend_noinput_hcl) $(PACKER)
	rm -rf $(@D)
	$(PACKER_RUN) build \
	-var "base_img=$(word 1,$^)" \
	-var "disk_size=$(TEST_DIMG_DISK_SIZE)" \
	-var "cpus=$(IMAGE_BUILD_CPUS)" \
	-var "memory=$(IMAGE_BUILD_MEMORY)" \
	-var "out_dir=$(@D)" \
	-var "out_name=$(@F)" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "install_script=$(word 2,$^)" \
	-var "use_backing_file=true" \
	$(extend_noinput_hcl)

.PHONY: qemu-quick
qemu-quick:
	$(OSSIM_QEMU) -machine q35,accel=kvm -enable-ossim \
	-cpu host -smp $(QUICK_VM_CPUS) -m $(QUICK_VM_MEMORY) \
	-object memory-backend-memfd,id=mem0,size=$(QUICK_VM_MEMORY),share=on \
	-numa node,memdev=mem0 \
	-drive file=$(quick_dimg),media=disk,format=qcow2,if=virtio,index=0 \
	-fsdev local,id=input_fsdev,path=$(realpath $(host_microbench_d)),security_model=none,readonly=on \
	-device virtio-9p-pci,fsdev=input_fsdev,mount_tag=input_fsdev \
	-boot c \
	-display none -serial mon:stdio
