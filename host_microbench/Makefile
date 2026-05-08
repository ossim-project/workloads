# Build the C helper binaries that the bench scripts call into. These live
# in this directory (mounted read-only into each microbench VM via 9p), so
# they must be built on the host before any experiment is launched.
#
# disks/microbench/rules.mk pulls this in as a prerequisite of
# qemu-microbench-instance, so most users won't invoke it directly.

SUBDIRS := pchase cpu_loop

.PHONY: all clean $(SUBDIRS)

all: $(SUBDIRS)

$(SUBDIRS):
	$(MAKE) -C $@

clean:
	for d in $(SUBDIRS); do $(MAKE) -C $$d clean; done
