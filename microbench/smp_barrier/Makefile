CFLAGS ?= -O2 -Wall -Wextra -g
LDLIBS := -lpthread

smp_barrier: smp_barrier.c ../common/bench.h
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

.PHONY: clean
clean:
	rm -f smp_barrier
