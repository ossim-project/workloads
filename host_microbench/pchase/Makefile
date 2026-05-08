CFLAGS ?= -O2 -Wall -Wextra -std=c11
TARGET := pchase

all: $(TARGET)

$(TARGET): main.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(TARGET)

.PHONY: all clean
