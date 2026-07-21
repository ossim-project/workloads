CFLAGS ?= -O2 -Wall -Wextra -g

simple_compute: simple_compute.c ../common/bench.h
	$(CC) $(CFLAGS) -o $@ $< -lpthread

.PHONY: clean
clean:
	rm -f simple_compute
