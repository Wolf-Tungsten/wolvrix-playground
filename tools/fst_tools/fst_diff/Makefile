ROOT := $(abspath ../../..)
WOLVRIX_DIR ?= $(ROOT)/wolvrix
BUILD_DIR ?= $(ROOT)/build/fst_diff

CC ?= clang
CXX ?= clang++

CPPFLAGS += -I$(WOLVRIX_DIR)/external/libfst/src -D_GNU_SOURCE
CFLAGS ?= -O2 -Wall -Wextra -std=c11
CXXFLAGS ?= -O2 -Wall -Wextra -std=c++20
LDFLAGS ?=
LDLIBS ?= -lz

C_LIBFST_OBJS := \
	$(BUILD_DIR)/fastlz.o \
	$(BUILD_DIR)/fstapi.o \
	$(BUILD_DIR)/lz4.o

.PHONY: all clean

all: $(BUILD_DIR)/fst_diff

clean:
	rm -rf $(BUILD_DIR)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/fastlz.o: $(WOLVRIX_DIR)/external/libfst/src/fastlz.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/fstapi.o: $(WOLVRIX_DIR)/external/libfst/src/fstapi.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/lz4.o: $(WOLVRIX_DIR)/external/libfst/src/lz4.c | $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/main.o: main.cpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/fst_diff: $(BUILD_DIR)/main.o $(C_LIBFST_OBJS)
	$(CXX) $(LDFLAGS) $^ $(LDLIBS) -o $@
