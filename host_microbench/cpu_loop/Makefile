CFLAGS ?= -O2 -Wall -Wextra -std=c11
TARGET := cpu_loop

all: $(TARGET)

$(TARGET): main.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
