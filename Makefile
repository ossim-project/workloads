# Configurations
ifeq ($(OSSIM_OUT_DIR),)
	OUTPUT := out/
else
	OUTPUT := $(OSSIM_OUT_DIR)/workloads/
endif

ifeq ($(OSSIM_BUILD_DIR),)
	BUILD := build/
else
	BUILD := $(OSSIM_BUILD_DIR)/workloads/
endif

OSSIM_PREFIX ?= /usr/local/
PREFIX := $(OSSIM_PREFIX)

include include.mk

$(eval $(call include_rules,$(d)docker/rules.mk))
$(eval $(call include_rules,$(d)disks/rules.mk))
