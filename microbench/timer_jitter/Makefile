CFLAGS ?= -O2 -Wall -Wextra -g

timer_jitter: timer_jitter.c ../common/bench.h
	$(CC) $(CFLAGS) -o $@ $<

.PHONY: clean
clean:
	rm -f timer_jitter
