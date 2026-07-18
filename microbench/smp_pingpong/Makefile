CFLAGS ?= -O2 -Wall -Wextra -g
LDLIBS := -lpthread

smp_pingpong: smp_pingpong.c ../common/bench.h
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)

.PHONY: clean
clean:
	rm -f smp_pingpong
