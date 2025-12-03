BIGDATA_BASE_DIMG_ISO_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
BIGDATA_BASE_DIME_ISO_CKSUM_URL="https://cloud-images.ubuntu.com/noble/current/SHA256SUMS"

bigdata_input_d := $(d)input

.PHONY: update-bigdata-input
update-bigdata-input:
	rm -rf $(bigdata_input_d)/workloads && mkdir -p $(bigdata_input_d)
	cp -r $(ROOT)/bigdata $(bigdata_input_d)/workloads

# >>> Base disk image
DIMG_ALL += bigdata/base
.PRECIOUS: $(call dimg_path,bigdata/base)
$(call dimg_path,bigdata/base): $(b)seed.raw $(d)install_base.sh $(base_hcl) $(PACKER)
	$(MAKE) update-bigdata-input
	rm -rf $(@D)
	$(PACKER_RUN) build \
	-var "disk_size=40G" \
	-var "iso_url=$(BIGDATA_BASE_DIMG_ISO_URL)" \
	-var "iso_cksum_url=$(BIGDATA_BASE_DIME_ISO_CKSUM_URL)" \
	-var "out_dir=$(@D)" \
	-var "out_name=$(@F)" \
	-var "cpus=$(IMAGE_BUILD_CPUS)" \
	-var "memory=$(IMAGE_BUILD_MEMORY)" \
	-var "seedimg=$(word 1,$^)" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "input_dir=$(bigdata_input_d)" \
	-var "install_script=$(word 2,$^)" \
	$(base_hcl)

$(b)seed.raw: $(d)user-data $(b)meta-data
	@mkdir -p $(@D)
	cloud-localds $@ $^

$(b)meta-data:
	@mkdir -p $(@D)
	tee $@ < /dev/null > /dev/null
# <<< Base disk image

$(eval $(call disk_extend_rule,bigdata/node0,bigdata/base,$(d)config_node0.sh,$(bigdata_input_d)))
$(eval $(call disk_run_rule,bigdata/node0,4,16G,$(word 1,$(QEMU_MAC_LIST)),$(bigdata_input_d)))

$(eval $(call disk_extend_rule,bigdata/node1,bigdata/base,$(d)config_node1.sh,$(bigdata_input_d)))
$(eval $(call disk_run_rule,bigdata/node1,4,16G,$(word 2,$(QEMU_MAC_LIST)),$(bigdata_input_d)))

$(eval $(call disk_extend_rule,bigdata/node2,bigdata/base,$(d)config_node2.sh,$(bigdata_input_d)))
$(eval $(call disk_run_rule,bigdata/node2,4,16G,$(word 3,$(QEMU_MAC_LIST)),$(bigdata_input_d)))
