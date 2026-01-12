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

SUDO_ENV ?= LD_LIBRARY_PATH=$(LD_LIBRARY_PATH) PATH=$(PATH) PKG_CONFIG_PATH=$(PKG_CONFIG_PATH)
ifdef SUDO_PASS
SUDO ?= sh -c 'echo "$(SUDO_PASS)" | /usr/bin/sudo.ws -S $(SUDO_ENV) "$$@"' _
else
SUDO ?= sudo $(SUDO_ENV)
endif

include include.mk

$(eval $(call include_rules,$(d)docker/rules.mk))
$(eval $(call include_rules,$(d)disks/rules.mk))
