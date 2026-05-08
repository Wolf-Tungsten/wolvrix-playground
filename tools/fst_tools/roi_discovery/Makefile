ROOT := $(abspath ../../..)
WOLVRIX_DIR ?= $(ROOT)/wolvrix
BUILD_DIR ?= $(ROOT)/build/fst_roi_discovery

CC ?= clang
CXX ?= clang++

CPPFLAGS += -I$(CURDIR) -I$(WOLVRIX_DIR)/external/libfst/src \
	-DROI_DISCOVERY_TESTDATA_DIR=\"$(CURDIR)/testdata\"
CFLAGS ?= -O2 -Wall -Wextra -std=c11
CXXFLAGS ?= -O2 -Wall -Wextra -std=c++20
LDFLAGS ?=
LDLIBS ?= -lz

C_LIBFST_OBJS := \
	$(BUILD_DIR)/fastlz.o \
	$(BUILD_DIR)/fstapi.o \
	$(BUILD_DIR)/lz4.o

CXX_OBJS := \
	$(BUILD_DIR)/roi_discovery.o

CLI_OBJS := \
	$(BUILD_DIR)/main.o

TEST_OBJS := \
	$(BUILD_DIR)/test_roi_discovery.o

.PHONY: all test clean

all: $(BUILD_DIR)/fst_discover $(BUILD_DIR)/test_roi_discovery

test: $(BUILD_DIR)/fst_discover $(BUILD_DIR)/test_roi_discovery
	$(BUILD_DIR)/test_roi_discovery

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

$(BUILD_DIR)/roi_discovery.o: $(CURDIR)/roi_discovery.cpp $(CURDIR)/roi_discovery.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/main.o: $(CURDIR)/main.cpp $(CURDIR)/roi_discovery.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/test_roi_discovery.o: $(CURDIR)/test_roi_discovery.cpp $(CURDIR)/roi_discovery.hpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR)/fst_discover: $(C_LIBFST_OBJS) $(CXX_OBJS) $(CLI_OBJS)
	$(CXX) $(LDFLAGS) $^ -o $@ $(LDLIBS)

$(BUILD_DIR)/test_roi_discovery: $(C_LIBFST_OBJS) $(CXX_OBJS) $(TEST_OBJS)
	$(CXX) $(LDFLAGS) $^ -o $@ $(LDLIBS)