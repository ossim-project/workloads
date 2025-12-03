# Configurations
ifeq ($(OSSIM_OUTPUT),)
	OUTPUT := out/
else
	OUTPUT := $(OSSIM_OUTPUT)/workloads/
endif

ifeq ($(OSSIM_BUILD),)
	BUILD := build/
else
	BUILD := $(OSSIM_BUILD)/workloads/
endif

OSSIM_PREFIX ?= /usr/local/
PREFIX := $(OSSIM_PREFIX)

include include.mk

$(eval $(call include_rules,$(d)docker/rules.mk))
$(eval $(call include_rules,$(d)disks/rules.mk))
