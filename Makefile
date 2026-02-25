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
CASE ?=
LOG_ONLY_SIM ?= 0

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

# OpenC910 paths / options
C910_ROOT := $(CURDIR)/testcase/openc910
C910_SMART_RUN_DIR := $(C910_ROOT)/smart_run
C910_WORK_DIR ?= $(C910_SMART_RUN_DIR)/work
C910_SMART_CODE_BASE ?= $(abspath $(C910_ROOT)/C910_RTL_FACTORY)
SMART_ENV ?= $(C910_SMART_RUN_DIR)/env.sh
SMART_SIM ?= verilator
SMART_CASE ?= coremark
C910_SIM_MAX_CYCLE ?= 0
C910_WAVEFORM ?= 0
C910_LOG_DIR := $(BUILD_DIR)/logs/c910
C910_WAVEFORM_DIR ?= $(C910_LOG_DIR)
C910_LOG_DIR_ABS = $(abspath $(C910_LOG_DIR))
C910_WAVEFORM_DIR_ABS = $(abspath $(C910_WAVEFORM_DIR))
C910_WAVEFORM_PATH_ABS = $(if $(C910_WAVEFORM_PATH),$(if $(filter /%,$(C910_WAVEFORM_PATH)),$(C910_WAVEFORM_PATH),$(abspath $(C910_WAVEFORM_PATH))),)

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

.PHONY: all build check-id run_hdlbits_test run_all_hdlbits_tests run_c910_test clean

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

ifneq ($(strip $(SKIP_WOLF_BUILD)),1)
RUN_C910_TEST_DEPS := build
endif

run_c910_test: $(RUN_C910_TEST_DEPS)
	@CASE_NAME="$(if $(CASE),$(CASE),$(SMART_CASE))"; \
	LOG_FILE="$(if $(LOG_FILE),$(LOG_FILE),$(C910_LOG_DIR)/c910_$${CASE_NAME}_$(shell date +%Y%m%d_%H%M%S).log)"; \
	WAVEFORM_FILE="$(if $(C910_WAVEFORM_PATH_ABS),$(C910_WAVEFORM_PATH_ABS),$(C910_WAVEFORM_DIR_ABS)/c910_$${CASE_NAME}_$(shell date +%Y%m%d_%H%M%S).fst)"; \
	WAVEFORM_DIR="$$(dirname "$$WAVEFORM_FILE")"; \
	mkdir -p "$(C910_LOG_DIR_ABS)" "$$WAVEFORM_DIR"; \
	if [ -z "$(TOOL_EXTENSION)" ] && [ -f "$(SMART_ENV)" ]; then \
		. "$(SMART_ENV)"; \
	fi; \
	echo "[RUN] smart_run CASE=$$CASE_NAME SIM=$(SMART_SIM)"; \
	echo "[RUN] C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM)"; \
	echo "[LOG] Capturing output to: $$LOG_FILE"; \
	if [ "$(C910_WAVEFORM)" = "1" ]; then \
		echo "[WAVEFORM] Will save FST to: $$WAVEFORM_FILE"; \
	fi; \
	if [ "$(LOG_ONLY_SIM)" != "0" ]; then \
		C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) C910_WAVEFORM_PATH="$$WAVEFORM_FILE" \
		$(MAKE) --no-print-directory -C $(C910_SMART_RUN_DIR) runcase \
			CASE=$$CASE_NAME SIM=$(SMART_SIM) \
			C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) \
			BUILD_DIR="$(abspath $(C910_WORK_DIR))" \
			CODE_BASE_PATH="$${CODE_BASE_PATH:-$(C910_SMART_CODE_BASE)}" \
			TOOL_EXTENSION="$$TOOL_EXTENSION" \
			VERILATOR="$(VERILATOR)" \
			WOLVRIX_BIN="$(WOLVRIX_APP)" 2>&1 | \
			tee >(awk 'f{print} index($$0,"obj_dir/Vsim_top"){f=1; next}' > "$$LOG_FILE"); \
	else \
		C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) C910_WAVEFORM_PATH="$$WAVEFORM_FILE" \
		$(MAKE) --no-print-directory -C $(C910_SMART_RUN_DIR) runcase \
			CASE=$$CASE_NAME SIM=$(SMART_SIM) \
			C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) \
			BUILD_DIR="$(abspath $(C910_WORK_DIR))" \
			CODE_BASE_PATH="$${CODE_BASE_PATH:-$(C910_SMART_CODE_BASE)}" \
			TOOL_EXTENSION="$$TOOL_EXTENSION" \
			VERILATOR="$(VERILATOR)" \
			WOLVRIX_BIN="$(WOLVRIX_APP)" 2>&1 | tee "$$LOG_FILE"; \
	fi

clean:
	@rm -rf build
	@rm -rf $(C910_WORK_DIR)
