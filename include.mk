# Output directory 
OUTPUT ?= out/
# Build directory 
BUILD ?= build/
# Prefix
PREFIX ?= /usr/local/

OUTPUT := $(if $(filter %/,$(OUTPUT)),$(OUTPUT),$(OUTPUT)/)
BUILD := $(if $(filter %/,$(BUILD)),$(BUILD),$(BUILD)/)
PREFIX := $(if $(filter %/,$(PREFIX)),$(PREFIX),$(PREFIX)/)

ROOT := ./

d := $(ROOT)
o := $(OUTPUT)
b := $(BUILD)

current_makefile := $(firstword $(MAKEFILE_LIST))
makefile_stack := $(current_makefile)

define update_current_makefile
	$(eval current_makefile := $(firstword $(makefile_stack)))
	$(eval d := $(dir $(current_makefile)))
	$(eval o := $(subst /.,,$(OUTPUT)$(d)))
	$(eval b := $(subst /.,,$(BUILD)$(d)))
endef

define include_rules
	$(eval makefile_stack := $(1) $(makefile_stack))
	$(eval $(call update_current_makefile))
	$(eval include $(1))
	$(eval makefile_stack := $(wordlist 2, $(words $(makefile_stack)),$(makefile_stack)))
	$(eval $(call update_current_makefile))
endef
