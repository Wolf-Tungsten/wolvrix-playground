SHELL := /bin/bash

WOLVRIX_DIR ?= $(CURDIR)/wolvrix

# Check env.sh must exist and has been sourced
ENV_FILE := $(CURDIR)/env.sh
ifeq (,$(wildcard $(ENV_FILE)))
    $(error env.sh not found. Please run: cp $(CURDIR)/env.sh.template $(CURDIR)/env.sh && source $(CURDIR)/env.sh)
endif

ifeq ($(WOLF_ENV_SOURCED),)
    $(error env.sh exists but not sourced. Please run: source $(CURDIR)/env.sh)
endif

# Auto-load environment from env.sh
export TOOL_EXTENSION := $(or $(TOOL_EXTENSION),$(shell grep '^export TOOL_EXTENSION=' $(ENV_FILE) 2>/dev/null | cut -d'"' -f2))
export VERILATOR := $(or $(VERILATOR),$(shell grep '^export VERILATOR=' $(ENV_FILE) 2>/dev/null | cut -d'"' -f2))

DUT ?=

BUILD_DIR ?= build
WOLVRIX_BUILD_DIR ?= $(WOLVRIX_DIR)/build
CMAKE ?= cmake
WOLVRIX_APP := $(WOLVRIX_BUILD_DIR)/bin/wolvrix

# Verilator path (can be overridden via environment or env.sh)
VERILATOR ?= $(or $(shell echo $$VERILATOR),verilator)
VERILATOR_FLAGS ?= -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNDRIVEN \
	-Wno-SYNCASYNCNET

SINGLE_THREAD ?= 0
ifeq ($(origin WOLF_LOG), undefined)
WOLF_LOG := info
WOLF_LOG_DEFAULT := 1
else
WOLF_LOG_DEFAULT := 0
endif
WOLF_TIMER ?= 0
WOLF_TIMEOUT ?= 600
WOLF_EMIT_FLAGS ?=

ifneq ($(strip $(WOLF_TIMER)),0)
WOLF_LOG := debug
endif
ifneq ($(strip $(SINGLE_THREAD)),0)
WOLF_EMIT_FLAGS += --single-thread
endif
ifneq ($(strip $(WOLF_LOG)),)
WOLF_EMIT_FLAGS += --log $(WOLF_LOG)
endif
ifneq ($(strip $(WOLF_TIMER)),0)
WOLF_EMIT_FLAGS += --profile-timer
endif
ifneq ($(strip $(WOLF_TIMEOUT)),)
WOLF_EMIT_FLAGS += --timeout $(WOLF_TIMEOUT)
endif

HDLBITS_ROOT := $(CURDIR)/testcase/hdlbits
HDLBITS_WOLVRIX_SCRIPT := $(CURDIR)/scripts/wolvrix_emit.tcl

# HDLBits paths
DUT_SRC := $(HDLBITS_ROOT)/dut/dut_$(DUT).v
TB_SRC := $(HDLBITS_ROOT)/tb/tb_$(DUT).cpp
OUT_DIR := $(BUILD_DIR)/hdlbits/$(DUT)
EMITTED_DUT := $(OUT_DIR)/dut_$(DUT).v
EMITTED_JSON := $(OUT_DIR)/dut_$(DUT).json
SIM_BIN_NAME := sim_$(DUT)
SIM_BIN := $(OUT_DIR)/$(SIM_BIN_NAME)
VERILATOR_PREFIX := Vdut_$(DUT)
TB_SOURCES := $(wildcard $(HDLBITS_ROOT)/tb/tb_*.cpp)
HDLBITS_DUTS := $(sort $(patsubst tb_%,%,$(basename $(notdir $(TB_SOURCES)))))

.PHONY: all build check-id run_hdlbits_test run_all_hdlbits_tests

all: build

check-id:
	@if [[ ! "$(DUT)" =~ ^[0-9]{3}$$ ]]; then \
		echo "DUT must be a three-digit number (e.g. DUT=001)"; \
		exit 1; \
	fi
	@test -f $(DUT_SRC) || { echo "Missing DUT source: $(DUT_SRC)"; exit 1; }
	@test -f $(TB_SRC) || { echo "Missing testbench: $(TB_SRC)"; exit 1; }

build:
	env -u MAKE_TERMOUT $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR) -DCMAKE_BUILD_TYPE=Release
	$(CMAKE) --build $(WOLVRIX_BUILD_DIR)

$(WOLVRIX_APP): build

$(EMITTED_DUT) $(EMITTED_JSON): $(DUT_SRC) $(WOLVRIX_APP) $(HDLBITS_WOLVRIX_SCRIPT) check-id
	@mkdir -p $(OUT_DIR)
	WOLVRIX_SOURCES=$(DUT_SRC) \
	WOLVRIX_TOP=top_module \
	WOLVRIX_SV_OUT=$(EMITTED_DUT) \
	WOLVRIX_JSON_OUT=$(EMITTED_JSON) \
	WOLVRIX_STORE_JSON=1 \
	WOLVRIX_LOG_LEVEL=$(WOLF_LOG) \
	$(WOLVRIX_APP) -f $(HDLBITS_WOLVRIX_SCRIPT)

$(SIM_BIN): $(EMITTED_DUT) $(TB_SRC) check-id
	@mkdir -p $(OUT_DIR)
	$(VERILATOR) $(VERILATOR_FLAGS) --cc $(EMITTED_DUT) --exe $(TB_SRC) \
		--top-module top_module --prefix $(VERILATOR_PREFIX) -Mdir $(OUT_DIR) -o $(SIM_BIN_NAME)
	CCACHE_DISABLE=1 $(MAKE) -C $(OUT_DIR) -f $(VERILATOR_PREFIX).mk $(SIM_BIN_NAME)

run_hdlbits_test:
ifneq ($(strip $(DUT)),)
  ifeq ($(DUT),$(filter $(DUT),$(HDLBITS_DUTS)))
	@$(MAKE) --no-print-directory $(SIM_BIN)
	@echo "[RUN] ./$(SIM_BIN)"
	@cd $(OUT_DIR) && ./$(SIM_BIN_NAME)
  else
	$(error DUT=$(DUT) not found; available: $(HDLBITS_DUTS))
  endif
else
	@echo "DUT not set; running all available DUTs: $(HDLBITS_DUTS)"
	@$(MAKE) --no-print-directory run_all_hdlbits_tests
endif

run_all_hdlbits_tests: $(WOLVRIX_APP)
	@for dut in $(HDLBITS_DUTS); do \
		echo "==== Running DUT=$$dut ===="; \
		$(MAKE) --no-print-directory run_hdlbits_test DUT=$$dut || exit $$?; \
	done
