DATABASE_DIMG_ISO_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
DATABASE_DIME_ISO_CKSUM_URL="https://cloud-images.ubuntu.com/noble/current/SHA256SUMS"

database_input_d := $(d)input

.PHONY: update-database-input
update-database-input:
	rm -rf $(database_input_d)/workloads && mkdir -p $(database_input_d)
	cp -r $(ROOT)/database $(database_input_d)/workloads
	chmod -R a+r $(database_input_d)/workloads

# >>> Base disk image
DIMG_ALL += database/base
.PRECIOUS: $(call dimg_path,database/base)
$(call dimg_path,database/base): $(b)seed.raw $(d)install_base.sh $(base_hcl) $(PACKER)
	$(MAKE) update-database-input
	rm -rf $(@D)
	$(PACKER_RUN) build \
	-var "disk_size=40G" \
	-var "iso_url=$(DATABASE_DIMG_ISO_URL)" \
	-var "iso_cksum_url=$(DATABASE_DIME_ISO_CKSUM_URL)" \
	-var "out_dir=$(@D)" \
	-var "out_name=$(@F)" \
	-var "cpus=$(IMAGE_BUILD_CPUS)" \
	-var "memory=$(IMAGE_BUILD_MEMORY)" \
	-var "seedimg=$(word 1,$^)" \
	-var "user_name=root" \
	-var "user_password=root" \
	-var "input_dir=$(database_input_d)" \
	-var "install_script=$(word 2,$^)" \
	$(base_hcl)

$(b)seed.raw: $(d)user-data $(b)meta-data
	@mkdir -p $(@D)
	cloud-localds $@ $^

$(b)meta-data:
	@mkdir -p $(@D)
	tee $@ < /dev/null > /dev/null
# <<< Base disk image

$(eval $(call disk_extend_rule,database/server,database/base,$(d)config_server.sh,$(database_input_d)))
$(eval $(call disk_run_rule,database/server,8,16G,$(word 1,$(QEMU_MAC_LIST)),$(database_input_d)))
