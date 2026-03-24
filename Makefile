SHELL := /bin/bash

WOLVRIX_DIR ?= $(CURDIR)/wolvrix
PYTHON ?= python3

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
WOLVRIX_PYTHON_DIR ?= $(WOLVRIX_BUILD_DIR)/python
CMAKE ?= cmake
WOLVRIX_APP := $(WOLVRIX_BUILD_DIR)/bin/wolvrix
RUN_ID ?= $(shell date +%Y%m%d_%H%M%S)
export PYTHONPATH := $(WOLVRIX_PYTHON_DIR)$(if $(PYTHONPATH),:$(PYTHONPATH),)

# Verilator path (can be overridden via environment or env.sh)
VERILATOR ?= $(or $(shell echo $$VERILATOR),verilator)
VERILATOR_FLAGS ?= -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNDRIVEN \
	-Wno-SYNCASYNCNET

ifeq ($(origin WOLF_LOG), undefined)
WOLF_LOG := info
endif
WOLF_TIMER ?= 0

ifneq ($(strip $(WOLF_TIMER)),0)
WOLF_LOG := debug
endif

HDLBITS_ROOT := $(CURDIR)/testcase/hdlbits
HDLBITS_WOLVRIX_SCRIPT := $(CURDIR)/scripts/wolvrix_hdlbits_emit.py

# OpenC910 paths / options
C910_ROOT := $(CURDIR)/testcase/openc910
C910_SMART_RUN_DIR := $(C910_ROOT)/smart_run
C910_WORK_DIR ?= $(C910_SMART_RUN_DIR)/work
C910_SMART_CODE_BASE ?= $(abspath $(C910_ROOT)/C910_RTL_FACTORY)
C910_SMART_ENV ?= $(C910_SMART_RUN_DIR)/env.sh
C910_SMART_SIM ?= verilator
C910_SMART_CASE ?= coremark
C910_SIM_MAX_CYCLE ?= 0
C910_WAVEFORM ?= 0
C910_LOG_DIR := $(BUILD_DIR)/logs/c910
C910_WAVEFORM_DIR ?= $(C910_LOG_DIR)
C910_LOG_DIR_ABS = $(abspath $(C910_LOG_DIR))
C910_WAVEFORM_DIR_ABS = $(abspath $(C910_WAVEFORM_DIR))
C910_WAVEFORM_PATH_ABS = $(if $(C910_WAVEFORM_PATH),$(if $(filter /%,$(C910_WAVEFORM_PATH)),$(C910_WAVEFORM_PATH),$(abspath $(C910_WAVEFORM_PATH))),)

# XiangShan paths / options
XS_ROOT := $(CURDIR)/testcase/xiangshan
XS_WOLVRIX_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_emit.py
XS_WOLVRIX_REPCUT_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_repcut.py

XS_SIM_MAX_CYCLE ?= 0
XS_WAVEFORM ?= 0
XS_WAVEFORM_FULL ?= 0
XS_RAM_TRACE ?= 0
XS_REPCUT_STEP_TIMING ?= 0
XS_NUM_CORES ?= 1
XS_EMU_THREADS ?= 2
XS_VM_BUILD_JOBS ?= $(shell nproc)
XS_SIM_TOP ?= SimTop
XS_RTL_SUFFIX ?= sv
XS_WITH_CHISELDB ?= 0
XS_WITH_CONSTANTIN ?= 0
XS_ZERO_INIT ?= 0
ifeq ($(XS_ZERO_INIT),1)
XS_ZERO_INIT_DEFINES := RANDOMIZE_REG_INIT RANDOMIZE_MEM_INIT RANDOMIZE_DELAY=0 RANDOM=32'h0
else
XS_ZERO_INIT_DEFINES :=
endif
XS_ZERO_INIT_SIM_DEFINES := $(subst 32'h0,32\'h0,$(XS_ZERO_INIT_DEFINES))
XS_SIM_VFLAGS ?= +define+DIFFTEST $(foreach d,$(XS_ZERO_INIT_SIM_DEFINES),+define+$(d))
XS_EMU_PREFIX ?= $(shell if command -v stdbuf >/dev/null 2>&1; then echo "stdbuf -oL -eL"; fi)
XS_RAM_TRACE_ARGS := $(if $(filter 1,$(XS_RAM_TRACE)),+trace_difftest_ram,)
XS_LOG_DIR := $(BUILD_DIR)/logs/xs
XS_WAVEFORM_DIR ?= $(XS_LOG_DIR)
XS_LOG_DIR_ABS = $(abspath $(XS_LOG_DIR))
XS_WAVEFORM_DIR_ABS = $(abspath $(XS_WAVEFORM_DIR))

XS_WORK_BASE ?= $(BUILD_DIR)/xs
XS_RTL_BUILD ?= $(XS_WORK_BASE)/rtl
XS_REF_BUILD ?= $(XS_WORK_BASE)/ref
XS_WOLF_BUILD ?= $(XS_WORK_BASE)/wolf
XS_REPCUT_BUILD ?= $(XS_WORK_BASE)/repcut
XS_RTL_DIR := $(XS_RTL_BUILD)/rtl
XS_VSRC_DIR ?= $(XS_ROOT)/difftest/src/test/vsrc/common
XS_WOLF_EMIT_DIR ?= $(XS_WOLF_BUILD)/wolf_emit
XS_WOLF_EMIT ?= $(XS_WOLF_EMIT_DIR)/wolf_emit.sv
XS_WOLF_FILELIST ?= $(XS_WOLF_EMIT_DIR)/xs_wolf.f
XS_SIM_DEFINES ?= DIFFTEST
XS_SIM_DEFINES += $(XS_ZERO_INIT_DEFINES)
XS_ROOT_ABS := $(abspath $(XS_ROOT))
XS_NOOP_HOME ?= $(XS_ROOT_ABS)
XS_RTL_BUILD_ABS := $(abspath $(XS_RTL_BUILD))
XS_REF_BUILD_ABS := $(abspath $(XS_REF_BUILD))
XS_WOLF_BUILD_ABS := $(abspath $(XS_WOLF_BUILD))
XS_RTL_DIR_ABS := $(abspath $(XS_RTL_DIR))
XS_VSRC_DIR_ABS := $(abspath $(XS_VSRC_DIR))
XS_WOLF_EMIT_DIR_ABS := $(abspath $(XS_WOLF_EMIT_DIR))
XS_WOLF_EMIT_ABS := $(abspath $(XS_WOLF_EMIT))
XS_WOLF_FILELIST_ABS := $(abspath $(XS_WOLF_FILELIST))
XS_SIM_TOP_V := $(XS_RTL_DIR_ABS)/$(XS_SIM_TOP).$(XS_RTL_SUFFIX)
XS_WOLF_JSON ?= $(XS_WOLF_EMIT_DIR_ABS)/xs_wolf.json
XS_WOLF_REPCUT_JSON ?= $(XS_REPCUT_BUILD)/xs_wolf_repcut.json
XS_WOLF_REPCUT_EMIT_DIR ?= $(XS_WOLF_REPCUT_JSON:.json=)
XS_WOLF_REPCUT_EMIT ?= $(XS_WOLF_REPCUT_EMIT_DIR)/$(XS_SIM_TOP).sv
XS_REPCUT_PACKAGE_ROOT ?= $(XS_REPCUT_BUILD)/package
XS_WOLF_REPCUT_PACKAGE_DIR ?= $(XS_REPCUT_PACKAGE_ROOT)/xs_wolf_repcut_partitioned
XS_REPCUT_WORK_DIR ?= $(XS_REPCUT_BUILD)/work
XS_REPCUT_EMU_BUILD ?= $(XS_REPCUT_BUILD)/partitioned-emu
XS_REPCUT_LEGACY_EMU_DIR ?= $(XS_REPCUT_BUILD)/emu
XS_REPCUT_WORK_DIR_ABS := $(abspath $(XS_REPCUT_WORK_DIR))
XS_REPCUT_BUILD_ABS := $(abspath $(XS_REPCUT_BUILD))
XS_REPCUT_EMU_BUILD_ABS := $(abspath $(XS_REPCUT_EMU_BUILD))
XS_REPCUT_LEGACY_EMU_DIR_ABS := $(abspath $(XS_REPCUT_LEGACY_EMU_DIR))
XS_WOLF_REPCUT_EMIT_DIR_ABS := $(abspath $(XS_WOLF_REPCUT_EMIT_DIR))
XS_WOLF_REPCUT_EMIT_ABS := $(abspath $(XS_WOLF_REPCUT_EMIT))
XS_WOLF_REPCUT_PACKAGE_DIR_ABS := $(abspath $(XS_WOLF_REPCUT_PACKAGE_DIR))
XS_JSON_ROUNDTRIP ?= 0
XS_REPCUT_LOG_DIR ?= $(BUILD_DIR)/logs/xs-repcut
XS_REPCUT_LOG_DIR_ABS := $(abspath $(XS_REPCUT_LOG_DIR))

XS_DIFFTEST_GEN_DIR ?= $(XS_ROOT)/build/generated-src
XS_DIFFTEST_GEN_DIR_ABS := $(abspath $(XS_DIFFTEST_GEN_DIR))
XS_WOLF_INCLUDE_DIRS ?= $(XS_RTL_DIR_ABS) $(XS_VSRC_DIR_ABS) $(XS_DIFFTEST_GEN_DIR_ABS)
XS_WOLF_INCLUDE_FLAGS := $(foreach d,$(XS_WOLF_INCLUDE_DIRS),-I $(d))
XS_WOLF_DEFINE_FLAGS := $(foreach d,$(XS_SIM_DEFINES),-D "$(d)")
XS_DIFFTEST_MACROS := $(XS_ROOT)/build/generated-src/DifftestMacros.svh

# HDLBits paths
HDLBITS_DUT_SRC := $(HDLBITS_ROOT)/dut/dut_$(DUT).v
HDLBITS_TB_SRC := $(HDLBITS_ROOT)/tb/tb_$(DUT).cpp
HDLBITS_OUT_DIR := $(BUILD_DIR)/hdlbits/$(DUT)
HDLBITS_EMITTED_DUT := $(HDLBITS_OUT_DIR)/dut_$(DUT).v
HDLBITS_EMITTED_JSON := $(HDLBITS_OUT_DIR)/dut_$(DUT).json
HDLBITS_SIM_BIN_NAME := sim_$(DUT)
HDLBITS_SIM_BIN := $(HDLBITS_OUT_DIR)/$(HDLBITS_SIM_BIN_NAME)
HDLBITS_VERILATOR_PREFIX := Vdut_$(DUT)
HDLBITS_TB_SOURCES := $(wildcard $(HDLBITS_ROOT)/tb/tb_*.cpp)
HDLBITS_DUTS := $(sort $(patsubst tb_%,%,$(basename $(notdir $(HDLBITS_TB_SOURCES)))))

.PHONY: all build check-id run_hdlbits_test run_all_hdlbits_tests run_c910_test run_c910_ref_test \
	xs_rtl xs_wolf_filelist xs_wolf_emit xs_ref_emu xs_wolf_emu run_xs_json_test \
	run_xs_repcut run_xs_repcut_partitioned_smoke build_xs_repcut_verilator run_xs_repcut_verilator xs_diff_clean run_xs_ref_emu run_xs_wolf_emu run_xs_diff clean

all: build

check-id:
	@if [[ ! "$(DUT)" =~ ^[0-9]{3}$$ ]]; then \
		echo "DUT must be a three-digit number (e.g. DUT=001)"; \
		exit 1; \
	fi
	@test -f $(HDLBITS_DUT_SRC) || { echo "Missing DUT source: $(HDLBITS_DUT_SRC)"; exit 1; }
	@test -f $(HDLBITS_TB_SRC) || { echo "Missing testbench: $(HDLBITS_TB_SRC)"; exit 1; }

build:
	env -u MAKE_TERMOUT $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR) -DCMAKE_BUILD_TYPE=Release
	$(CMAKE) --build $(WOLVRIX_BUILD_DIR)

$(WOLVRIX_APP): build

.PHONY: py_install
py_install: build
	@if [ -f "$(WOLVRIX_PYTHON_DIR)/wolvrix/_wolvrix.so" ]; then \
		echo "[PY] Reusing build-tree wolvrix via PYTHONPATH=$(WOLVRIX_PYTHON_DIR)"; \
	else \
		echo "[PY] Installing editable wolvrix package"; \
		$(PYTHON) -m pip install -e $(WOLVRIX_DIR); \
	fi

$(HDLBITS_EMITTED_DUT) $(HDLBITS_EMITTED_JSON): $(HDLBITS_DUT_SRC) $(HDLBITS_WOLVRIX_SCRIPT) check-id
	@mkdir -p $(HDLBITS_OUT_DIR)
	$(PYTHON) $(HDLBITS_WOLVRIX_SCRIPT) $(DUT) $(HDLBITS_OUT_DIR)

$(HDLBITS_SIM_BIN): $(HDLBITS_EMITTED_DUT) $(HDLBITS_TB_SRC) check-id
	@mkdir -p $(HDLBITS_OUT_DIR)
	$(VERILATOR) $(VERILATOR_FLAGS) --cc $(HDLBITS_EMITTED_DUT) --exe $(HDLBITS_TB_SRC) \
		--top-module top_module --prefix $(HDLBITS_VERILATOR_PREFIX) -Mdir $(HDLBITS_OUT_DIR) -o $(HDLBITS_SIM_BIN_NAME)
	CCACHE_DISABLE=1 $(MAKE) -C $(HDLBITS_OUT_DIR) -f $(HDLBITS_VERILATOR_PREFIX).mk $(HDLBITS_SIM_BIN_NAME)

run_hdlbits_test:
ifneq ($(strip $(DUT)),)
  ifeq ($(DUT),$(filter $(DUT),$(HDLBITS_DUTS)))
	@if [ "$(SKIP_PY_INSTALL)" != "1" ]; then \
		$(MAKE) --no-print-directory py_install; \
	fi
	@$(MAKE) --no-print-directory $(HDLBITS_SIM_BIN)
	@echo "[RUN] ./$(HDLBITS_SIM_BIN)"
	@cd $(HDLBITS_OUT_DIR) && ./$(HDLBITS_SIM_BIN_NAME)
  else
	$(error DUT=$(DUT) not found; available: $(HDLBITS_DUTS))
  endif
else
	@echo "DUT not set; running all available DUTs: $(HDLBITS_DUTS)"
	@$(MAKE) --no-print-directory run_all_hdlbits_tests
endif

run_all_hdlbits_tests:
	@$(MAKE) --no-print-directory py_install
	@for dut in $(HDLBITS_DUTS); do \
		echo "==== Running DUT=$$dut ===="; \
		$(MAKE) --no-print-directory run_hdlbits_test DUT=$$dut SKIP_PY_INSTALL=1 || exit $$?; \
	done

ifneq ($(strip $(SKIP_WOLF_BUILD)),1)
RUN_C910_TEST_DEPS := py_install
endif

run_c910_test: $(RUN_C910_TEST_DEPS)
	@CASE_NAME="$(if $(CASE),$(CASE),$(C910_SMART_CASE))"; \
	LOG_FILE="$(if $(LOG_FILE),$(LOG_FILE),$(C910_LOG_DIR)/c910_$${CASE_NAME}_$(shell date +%Y%m%d_%H%M%S).log)"; \
	WAVEFORM_FILE="$(if $(C910_WAVEFORM_PATH_ABS),$(C910_WAVEFORM_PATH_ABS),$(C910_WAVEFORM_DIR_ABS)/c910_$${CASE_NAME}_$(shell date +%Y%m%d_%H%M%S).fst)"; \
	WAVEFORM_DIR="$$(dirname "$$WAVEFORM_FILE")"; \
	mkdir -p "$(C910_LOG_DIR_ABS)" "$$WAVEFORM_DIR"; \
	if [ -z "$(TOOL_EXTENSION)" ] && [ -f "$(C910_SMART_ENV)" ]; then \
		. "$(C910_SMART_ENV)"; \
	fi; \
	echo "[RUN] smart_run CASE=$$CASE_NAME SIM=$(C910_SMART_SIM)"; \
	echo "[RUN] C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM)"; \
	echo "[LOG] Capturing output to: $$LOG_FILE"; \
	if [ "$(C910_WAVEFORM)" = "1" ]; then \
		echo "[WAVEFORM] Will save FST to: $$WAVEFORM_FILE"; \
	fi; \
	if [ "$(LOG_ONLY_SIM)" != "0" ]; then \
		C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) C910_WAVEFORM_PATH="$$WAVEFORM_FILE" \
		$(MAKE) --no-print-directory -C $(C910_SMART_RUN_DIR) runcase \
			CASE=$$CASE_NAME SIM=$(C910_SMART_SIM) \
			C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) \
			BUILD_DIR="$(abspath $(C910_WORK_DIR))" \
			CODE_BASE_PATH="$${CODE_BASE_PATH:-$(C910_SMART_CODE_BASE)}" \
			TOOL_EXTENSION="$$TOOL_EXTENSION" \
			VERILATOR="$(VERILATOR)" \
			PYTHON="$(PYTHON)" 2>&1 | \
			tee >(awk 'f{print} index($$0,"obj_dir/Vsim_top"){f=1; next}' > "$$LOG_FILE"); \
	else \
		C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) C910_WAVEFORM_PATH="$$WAVEFORM_FILE" \
		$(MAKE) --no-print-directory -C $(C910_SMART_RUN_DIR) runcase \
			CASE=$$CASE_NAME SIM=$(C910_SMART_SIM) \
			C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=$(C910_WAVEFORM) \
			BUILD_DIR="$(abspath $(C910_WORK_DIR))" \
			CODE_BASE_PATH="$${CODE_BASE_PATH:-$(C910_SMART_CODE_BASE)}" \
			TOOL_EXTENSION="$$TOOL_EXTENSION" \
			VERILATOR="$(VERILATOR)" \
			PYTHON="$(PYTHON)" 2>&1 | tee "$$LOG_FILE"; \
	fi

run_c910_ref_test:
	@CASE_NAME="$(if $(CASE),$(CASE),$(C910_SMART_CASE))"; \
	LOG_FILE="$(if $(LOG_FILE),$(LOG_FILE),$(C910_LOG_DIR)/c910_ref_$${CASE_NAME}_$(shell date +%Y%m%d_%H%M%S).log)"; \
	WAVEFORM_FILE="$(if $(C910_WAVEFORM_PATH_ABS),$(C910_WAVEFORM_PATH_ABS),$(C910_WAVEFORM_DIR_ABS)/c910_ref_$${CASE_NAME}_$(shell date +%Y%m%d_%H%M%S).fst)"; \
	WAVEFORM_DIR="$$(dirname "$$WAVEFORM_FILE")"; \
	mkdir -p "$(C910_LOG_DIR_ABS)" "$$WAVEFORM_DIR"; \
	if [ -z "$(TOOL_EXTENSION)" ] && [ -f "$(C910_SMART_ENV)" ]; then \
		. "$(C910_SMART_ENV)"; \
	fi; \
	echo "[RUN] smart_run CASE=$$CASE_NAME SIM=verilator_ref"; \
	echo "[RUN] C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=1"; \
	echo "[LOG] Capturing output to: $$LOG_FILE"; \
	echo "[WAVEFORM] Will save FST to: $$WAVEFORM_FILE"; \
	if [ "$(LOG_ONLY_SIM)" != "0" ]; then \
		C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=1 C910_WAVEFORM_PATH="$$WAVEFORM_FILE" \
		$(MAKE) --no-print-directory -C $(C910_SMART_RUN_DIR) runcase \
			CASE=$$CASE_NAME SIM=verilator_ref \
			C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=1 \
			BUILD_DIR="$(abspath $(C910_WORK_DIR))" \
			CODE_BASE_PATH="$${CODE_BASE_PATH:-$(C910_SMART_CODE_BASE)}" \
			TOOL_EXTENSION="$$TOOL_EXTENSION" \
			VERILATOR="$(VERILATOR)" \
			PYTHON="$(PYTHON)" 2>&1 | \
			tee >(awk 'f{print} index($$0,"obj_dir/Vsim_top"){f=1; next}' > "$$LOG_FILE"); \
	else \
		C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=1 C910_WAVEFORM_PATH="$$WAVEFORM_FILE" \
		$(MAKE) --no-print-directory -C $(C910_SMART_RUN_DIR) runcase \
			CASE=$$CASE_NAME SIM=verilator_ref \
			C910_SIM_MAX_CYCLE=$(C910_SIM_MAX_CYCLE) C910_WAVEFORM=1 \
			BUILD_DIR="$(abspath $(C910_WORK_DIR))" \
			CODE_BASE_PATH="$${CODE_BASE_PATH:-$(C910_SMART_CODE_BASE)}" \
			TOOL_EXTENSION="$$TOOL_EXTENSION" \
			VERILATOR="$(VERILATOR)" \
			PYTHON="$(PYTHON)" 2>&1 | tee "$$LOG_FILE"; \
	fi

# XiangShan: generate sim-verilog
$(XS_SIM_TOP_V):
	@echo "[RUN] Generating XiangShan sim-verilog into $(XS_RTL_BUILD_ABS)..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@mkdir -p "$(XS_ROOT)/build"
	@$(eval LOG_FILE := $(XS_LOG_DIR_ABS)/xs_simverilog_$(RUN_ID).log)
	@echo "[LOG] Recording sim-verilog command to: $(LOG_FILE)"
	@printf '' > "$(LOG_FILE)"
	@echo "[CMD] $(MAKE) -C $(XS_ROOT) sim-verilog BUILD_DIR=$(XS_RTL_BUILD_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX)" | tee -a "$(LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT) sim-verilog \
		BUILD_DIR=$(XS_RTL_BUILD_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX)

xs_rtl: $(XS_SIM_TOP_V)

$(XS_WOLF_FILELIST_ABS): $(XS_SIM_TOP_V)
	@mkdir -p "$(dir $@)"
	@{ \
		find "$(XS_RTL_DIR_ABS)" -type f -name "*.sv" -o -type f -name "*.v"; \
		find "$(XS_VSRC_DIR_ABS)" -type f -name "*.sv" -o -type f -name "*.v"; \
	} | LC_ALL=C sort > "$@"

xs_wolf_filelist: $(XS_WOLF_FILELIST_ABS)

XS_WOLF_DEPS := py_install

xs_wolf_emit: $(XS_WOLF_FILELIST_ABS) $(XS_WOLF_DEPS)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@mkdir -p "$(XS_WOLF_REPCUT_EMIT_DIR_ABS)"
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(RUN_ID))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_wolf_build_$(RUN_ID).log)
	@$(eval XS_READ_ARGS_FILE := $(XS_WOLF_EMIT_DIR_ABS)/wolvrix_read_args.txt)
	@echo "[LOG] Capturing wolf emit output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_READ_ARGS_FILE)"
	@printf "%s\n" $(XS_WOLF_INCLUDE_FLAGS) $(XS_WOLF_DEFINE_FLAGS) >> "$(XS_READ_ARGS_FILE)"
	@{ \
		echo "[CMD] $(PYTHON) $(XS_WOLVRIX_SCRIPT) $(XS_WOLF_FILELIST_ABS) $(XS_SIM_TOP) $(XS_WOLF_EMIT_ABS) $(XS_WOLF_JSON) $(XS_READ_ARGS_FILE) $(WOLF_LOG)"; \
		$(PYTHON) $(XS_WOLVRIX_SCRIPT) \
			$(XS_WOLF_FILELIST_ABS) \
			$(XS_SIM_TOP) \
			$(XS_WOLF_EMIT_ABS) \
			$(XS_WOLF_JSON) \
			$(XS_READ_ARGS_FILE) \
			$(WOLF_LOG); \
	} 2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"

run_xs_repcut: py_install
	@if [ ! -f "$(XS_WOLF_JSON)" ]; then \
		echo "[FAIL] xs repcut: missing json $(XS_WOLF_JSON)"; \
		exit 1; \
	fi
	@if [ -d "$(XS_REPCUT_LEGACY_EMU_DIR_ABS)" ]; then \
		echo "[CLEAN] Removing stale legacy repcut emu dir: $(XS_REPCUT_LEGACY_EMU_DIR_ABS)"; \
		rm -rf "$(XS_REPCUT_LEGACY_EMU_DIR_ABS)"; \
	fi
	@mkdir -p "$(XS_WOLF_REPCUT_EMIT_DIR_ABS)"
	@mkdir -p "$(XS_REPCUT_BUILD_ABS)"
	@mkdir -p "$(XS_REPCUT_WORK_DIR_ABS)"
	@mkdir -p "$(XS_REPCUT_LOG_DIR_ABS)"
	@$(eval XS_REPCUT_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_repcut_$(RUN_ID).log)
	@echo "[RUN] xs repcut strip-debug"
	@echo "[LOG] repcut: $(XS_REPCUT_LOG_FILE)"
	@echo "[CMD] $(PYTHON) $(XS_WOLVRIX_REPCUT_SCRIPT) $(XS_WOLF_JSON) $(XS_WOLF_REPCUT_JSON) $(XS_REPCUT_WORK_DIR_ABS) $(WOLF_LOG)"
	@set -o pipefail; $(PYTHON) $(XS_WOLVRIX_REPCUT_SCRIPT) \
		$(XS_WOLF_JSON) \
		$(XS_WOLF_REPCUT_JSON) \
		$(XS_REPCUT_WORK_DIR_ABS) \
		$(WOLF_LOG) \
		2>&1 | tee "$(XS_REPCUT_LOG_FILE)"
	@if [ ! -f "$(XS_WOLF_REPCUT_EMIT_ABS)" ]; then \
		echo "[FAIL] xs repcut: missing emitted top sv $(XS_WOLF_REPCUT_EMIT_ABS)"; \
		exit 1; \
	fi
	@$(eval XS_REPCUT_BUILD_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_repcut_build_$(RUN_ID).log)
	@echo "[RUN] Building XiangShan repcut emu..."
	@echo "[LOG] repcut build: $(XS_REPCUT_BUILD_LOG_FILE)"
	@printf '' > "$(XS_REPCUT_BUILD_LOG_FILE)"
	@echo "[CLEAN] Removing stale verilator-compile: $(XS_REPCUT_BUILD_ABS)/verilator-compile" | tee -a "$(XS_REPCUT_BUILD_LOG_FILE)"
	@rm -rf "$(XS_REPCUT_BUILD_ABS)/verilator-compile"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_REPCUT_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_WOLF_REPCUT_EMIT_DIR_ABS) SIM_TOP_V=$(XS_WOLF_REPCUT_EMIT_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=$(XS_EMU_THREADS) VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 SIM_VFLAGS=\"$(XS_SIM_VFLAGS)\" WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) SIM_VSRC= $(if $(filter 1,$(XS_WAVEFORM)),EMU_TRACE=fst,)" | tee -a "$(XS_REPCUT_BUILD_LOG_FILE)"
	@set -o pipefail; NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_REPCUT_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_WOLF_REPCUT_EMIT_DIR_ABS) \
		SIM_TOP_V=$(XS_WOLF_REPCUT_EMIT_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=$(XS_EMU_THREADS) \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		SIM_VFLAGS="$(XS_SIM_VFLAGS)" \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		SIM_VSRC= \
		$(if $(filter 1,$(XS_WAVEFORM)),EMU_TRACE=fst,) \
		2>&1 | tee -a "$(XS_REPCUT_BUILD_LOG_FILE)"
	@if [ ! -x "$(XS_REPCUT_BUILD_ABS)/emu" ]; then \
		echo "[FAIL] xs repcut: emu build did not produce executable $(XS_REPCUT_BUILD_ABS)/emu"; \
		exit 1; \
	fi
	@RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
		REPCUT_RUN_LOG="$(XS_REPCUT_LOG_DIR_ABS)/xs_repcut_$${RUN_ID}.log"; \
		REPCUT_WAVEFORM="$(XS_WAVEFORM_DIR_ABS)/xs_repcut_$${RUN_ID}.fst"; \
		printf '' > "$$REPCUT_RUN_LOG"; \
		echo "[RUN] xs repcut emu"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL)"; \
		echo "[LOG] repcut run: $$REPCUT_RUN_LOG"; \
		if [ "$(XS_WAVEFORM)" = "1" ]; then \
			echo "[WAVEFORM] repcut: $$REPCUT_WAVEFORM"; \
		fi; \
		echo "[CMD] cd $(XS_REPCUT_BUILD_ABS) && $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b 0 $(if $(filter 1,$(XS_WAVEFORM_FULL)),-e -1,-e 0) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$REPCUT_WAVEFORM,)"; \
		set -o pipefail; cd "$(XS_REPCUT_BUILD_ABS)" && $(XS_EMU_PREFIX) ./emu \
			-i "$(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin" \
			--diff "$(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so" \
			-b 0 $(if $(filter 1,$(XS_WAVEFORM_FULL)),-e -1,-e 0) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$REPCUT_WAVEFORM,) \
			2>&1 | tee "$$REPCUT_RUN_LOG"

run_xs_repcut_partitioned_smoke: py_install
	@if [ ! -f "$(XS_WOLF_JSON)" ]; then \
		echo "[FAIL] xs repcut partitioned: missing json $(XS_WOLF_JSON)"; \
		exit 1; \
	fi
	@mkdir -p "$(XS_WOLF_REPCUT_EMIT_DIR_ABS)"
	@mkdir -p "$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)"
	@mkdir -p "$(XS_REPCUT_BUILD_ABS)"
	@mkdir -p "$(XS_REPCUT_WORK_DIR_ABS)"
	@mkdir -p "$(XS_REPCUT_EMU_BUILD_ABS)"
	@mkdir -p "$(XS_REPCUT_LOG_DIR_ABS)"
	@$(eval XS_REPCUT_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_repcut_partitioned_$(RUN_ID).log)
	@echo "[RUN] xs repcut partitioned package"
	@echo "[LOG] repcut partitioned: $(XS_REPCUT_LOG_FILE)"
	@echo "[CMD] $(PYTHON) $(XS_WOLVRIX_REPCUT_SCRIPT) $(XS_WOLF_JSON) $(XS_WOLF_REPCUT_JSON) $(XS_REPCUT_WORK_DIR_ABS) $(WOLF_LOG) $(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)"
	@set -o pipefail; $(PYTHON) $(XS_WOLVRIX_REPCUT_SCRIPT) \
		$(XS_WOLF_JSON) \
		$(XS_WOLF_REPCUT_JSON) \
		$(XS_REPCUT_WORK_DIR_ABS) \
		$(WOLF_LOG) \
		$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS) \
		2>&1 | tee "$(XS_REPCUT_LOG_FILE)"
	@$(eval XS_REPCUT_PACKAGE_BUILD_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_repcut_partitioned_build_$(RUN_ID).log)
	@echo "[RUN] Building repcut partitioned smoke package..."
	@echo "[LOG] repcut partitioned build: $(XS_REPCUT_PACKAGE_BUILD_LOG_FILE)"
	@printf '' > "$(XS_REPCUT_PACKAGE_BUILD_LOG_FILE)"
	@echo "[CMD] $(MAKE) -C $(XS_WOLF_REPCUT_PACKAGE_DIR_ABS) -j$$(nproc)" | tee -a "$(XS_REPCUT_PACKAGE_BUILD_LOG_FILE)"
	@set -o pipefail; $(MAKE) -C "$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)" -j"$$(nproc)" \
		2>&1 | tee -a "$(XS_REPCUT_PACKAGE_BUILD_LOG_FILE)"
	@if [ ! -x "$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)/build/partitioned-smoke" ]; then \
		echo "[FAIL] xs repcut partitioned: missing smoke binary $(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)/build/partitioned-smoke"; \
		exit 1; \
	fi
	@$(eval XS_REPCUT_PACKAGE_RUN_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_repcut_partitioned_run_$(RUN_ID).log)
	@echo "[RUN] repcut partitioned smoke binary"
	@echo "[LOG] repcut partitioned run: $(XS_REPCUT_PACKAGE_RUN_LOG_FILE)"
	@printf '' > "$(XS_REPCUT_PACKAGE_RUN_LOG_FILE)"
	@echo "[CMD] $(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)/build/partitioned-smoke" | tee -a "$(XS_REPCUT_PACKAGE_RUN_LOG_FILE)"
	@set -o pipefail; "$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)/build/partitioned-smoke" \
		2>&1 | tee -a "$(XS_REPCUT_PACKAGE_RUN_LOG_FILE)"

build_xs_repcut_verilator:
	@echo "[RUN] Rebuilding Wolvrix for XiangShan repcut emu..."
	env -u MAKE_TERMOUT $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR) -DCMAKE_BUILD_TYPE=Release
	$(CMAKE) --build $(WOLVRIX_BUILD_DIR) --clean-first
	@if [ -f "$(WOLVRIX_PYTHON_DIR)/wolvrix/_wolvrix.so" ]; then \
		echo "[PY] Reusing build-tree wolvrix via PYTHONPATH=$(WOLVRIX_PYTHON_DIR)"; \
	else \
		echo "[PY] Installing editable wolvrix package"; \
		$(PYTHON) -m pip install -e $(WOLVRIX_DIR); \
	fi
	@if [ "$(XS_WAVEFORM)" != "0" ] || [ "$(XS_WAVEFORM_FULL)" != "0" ]; then \
		echo "[FAIL] xs verilator repcut: waveform is not supported in partitioned backend yet"; \
		exit 1; \
	fi
	@if [ ! -f "$(XS_WOLF_JSON)" ]; then \
		echo "[FAIL] xs verilator repcut: missing json $(XS_WOLF_JSON)"; \
		exit 1; \
	fi
	@mkdir -p "$(XS_REPCUT_LOG_DIR_ABS)"
	@echo "[CLEAN] Removing stale repcut package/work/emu build dirs"
	@rm -rf "$(XS_WOLF_REPCUT_EMIT_DIR_ABS)" \
		"$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)" \
		"$(XS_REPCUT_WORK_DIR_ABS)" \
		"$(XS_REPCUT_EMU_BUILD_ABS)"
	@mkdir -p "$(XS_WOLF_REPCUT_EMIT_DIR_ABS)"
	@mkdir -p "$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)"
	@mkdir -p "$(XS_REPCUT_BUILD_ABS)"
	@mkdir -p "$(XS_REPCUT_WORK_DIR_ABS)"
	@mkdir -p "$(XS_REPCUT_EMU_BUILD_ABS)"
	@$(eval XS_REPCUT_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_verilator_repcut_$(RUN_ID).log)
	@echo "[RUN] xs verilator repcut package"
	@echo "[LOG] xs verilator repcut: $(XS_REPCUT_LOG_FILE)"
	@echo "[CMD] $(PYTHON) $(XS_WOLVRIX_REPCUT_SCRIPT) $(XS_WOLF_JSON) $(XS_WOLF_REPCUT_JSON) $(XS_REPCUT_WORK_DIR_ABS) $(WOLF_LOG) $(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)"
	@set -o pipefail; $(PYTHON) $(XS_WOLVRIX_REPCUT_SCRIPT) \
		$(XS_WOLF_JSON) \
		$(XS_WOLF_REPCUT_JSON) \
		$(XS_REPCUT_WORK_DIR_ABS) \
		$(WOLF_LOG) \
		$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS) \
		2>&1 | tee "$(XS_REPCUT_LOG_FILE)"
	@$(eval XS_REPCUT_BUILD_LOG_FILE := $(XS_REPCUT_LOG_DIR_ABS)/xs_verilator_repcut_build_$(RUN_ID).log)
	@echo "[RUN] Building XiangShan repcut verilator emu..."
	@echo "[LOG] xs verilator repcut build: $(XS_REPCUT_BUILD_LOG_FILE)"
	@printf '' > "$(XS_REPCUT_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_REPCUT_EMU_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_WOLF_REPCUT_EMIT_DIR_ABS) SIM_TOP_V=$(XS_WOLF_REPCUT_EMIT_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=0 VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 SIM_VFLAGS=\"$(XS_SIM_VFLAGS)\" WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) WOLVRIX_PARTITIONED_PACKAGE_DIR=$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)" | tee -a "$(XS_REPCUT_BUILD_LOG_FILE)"
	@set -o pipefail; NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_REPCUT_EMU_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_WOLF_REPCUT_EMIT_DIR_ABS) \
		SIM_TOP_V=$(XS_WOLF_REPCUT_EMIT_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=0 \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		SIM_VFLAGS="$(XS_SIM_VFLAGS)" \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		WOLVRIX_PARTITIONED_PACKAGE_DIR=$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS) \
		2>&1 | tee -a "$(XS_REPCUT_BUILD_LOG_FILE)"
	@if [ ! -x "$(XS_REPCUT_EMU_BUILD_ABS)/emu" ]; then \
		echo "[FAIL] xs verilator repcut: emu build did not produce executable $(XS_REPCUT_EMU_BUILD_ABS)/emu"; \
		exit 1; \
	fi

run_xs_repcut_verilator:
	@if [ ! -x "$(XS_REPCUT_EMU_BUILD_ABS)/emu" ]; then \
		echo "[FAIL] xs verilator repcut: missing emu $(XS_REPCUT_EMU_BUILD_ABS)/emu; run 'make build_xs_repcut_verilator' first"; \
		exit 1; \
	fi
	@mkdir -p "$(XS_REPCUT_LOG_DIR_ABS)"
	@RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
		REPCUT_RUN_LOG="$(XS_REPCUT_LOG_DIR_ABS)/xs_verilator_repcut_$${RUN_ID}.log"; \
		REPCUT_TIMING_JSONL="$(XS_REPCUT_LOG_DIR_ABS)/xs_verilator_repcut_$${RUN_ID}.timing.jsonl"; \
		printf '' > "$$REPCUT_RUN_LOG"; \
		echo "[RUN] xs verilator repcut emu"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_EMU_THREADS=$(XS_EMU_THREADS) XS_REPCUT_STEP_TIMING=$(XS_REPCUT_STEP_TIMING)"; \
		echo "[LOG] xs verilator repcut run: $$REPCUT_RUN_LOG"; \
		echo "[LOG] xs verilator repcut timing: $$REPCUT_TIMING_JSONL"; \
		echo "[CMD] cd $(XS_REPCUT_EMU_BUILD_ABS) && XS_EMU_THREADS=$(XS_EMU_THREADS) XS_REPCUT_STEP_TIMING=$(XS_REPCUT_STEP_TIMING) WOLVI_REPCUT_TIMING_JSONL=$$REPCUT_TIMING_JSONL $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b 0 -e 0 $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS)"; \
		set -o pipefail; cd "$(XS_REPCUT_EMU_BUILD_ABS)" && XS_EMU_THREADS="$(XS_EMU_THREADS)" XS_REPCUT_STEP_TIMING="$(XS_REPCUT_STEP_TIMING)" WOLVI_REPCUT_TIMING_JSONL="$$REPCUT_TIMING_JSONL" $(XS_EMU_PREFIX) ./emu \
			-i "$(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin" \
			--diff "$(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so" \
			-b 0 \
			-e 0 \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			2>&1 | tee "$$REPCUT_RUN_LOG"

xs_ref_emu: $(XS_SIM_TOP_V)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@echo "[RUN] Building XiangShan ref emu..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_ref_build_$(RUN_ID).log)
	@echo "[LOG] Capturing build output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_REF_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_RTL_DIR_ABS) SIM_TOP_V=$(XS_SIM_TOP_V) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=$(XS_EMU_THREADS) VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 SIM_VFLAGS=\"$(XS_SIM_VFLAGS)\" WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) $(if $(filter 1,$(XS_WAVEFORM)),EMU_TRACE=fst,)" | tee -a "$(XS_BUILD_LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_REF_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_RTL_DIR_ABS) \
		SIM_TOP_V=$(XS_SIM_TOP_V) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=$(XS_EMU_THREADS) \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		SIM_VFLAGS="$(XS_SIM_VFLAGS)" \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		$(if $(filter 1,$(XS_WAVEFORM)),EMU_TRACE=fst,) \
		2>&1 | tee "$(XS_BUILD_LOG_FILE)"

xs_wolf_emu: xs_wolf_emit
	@echo "[RUN] Building XiangShan wolf emu..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_wolf_build_$(RUN_ID).log)
	@echo "[LOG] Capturing build output to: $(XS_BUILD_LOG_FILE)"
	@printf '' >> "$(XS_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_WOLF_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_WOLF_EMIT_DIR_ABS) SIM_TOP_V=$(XS_WOLF_EMIT_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=$(XS_EMU_THREADS) VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 SIM_VFLAGS=\"$(XS_SIM_VFLAGS)\" WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) SIM_VSRC= $(if $(filter 1,$(XS_WAVEFORM)),EMU_TRACE=fst,)" | tee -a "$(XS_BUILD_LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_WOLF_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_WOLF_EMIT_DIR_ABS) \
		SIM_TOP_V=$(XS_WOLF_EMIT_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=$(XS_EMU_THREADS) \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		SIM_VFLAGS="$(XS_SIM_VFLAGS)" \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		SIM_VSRC= \
		$(if $(filter 1,$(XS_WAVEFORM)),EMU_TRACE=fst,) \
		2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"

xs_diff_clean:
	rm -rf "$(XS_REF_BUILD_ABS)/verilator-compile" \
		"$(XS_WOLF_BUILD_ABS)/verilator-compile" \
		"$(XS_WOLF_EMIT_DIR_ABS)" \
		"$(XS_WOLF_REPCUT_PACKAGE_DIR_ABS)" \
		"$(XS_REPCUT_EMU_BUILD_ABS)" \
		"$(XS_REPCUT_LEGACY_EMU_DIR_ABS)" \
		"$(XS_REPCUT_WORK_DIR_ABS)"

run_xs_ref_emu:
	@RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	mkdir -p "$$LOG_DIR"; \
	REF_LOG="$$LOG_DIR/xs_ref_$${RUN_ID}.log"; \
	REF_WAVEFORM="$(XS_WAVEFORM_DIR_ABS)/xs_ref_$${RUN_ID}.fst"; \
	printf '' > "$$REF_LOG"; \
	echo "[RUN] xs ref emu"; \
	echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL)"; \
	echo "[LOG] ref : $$REF_LOG"; \
	if [ "$(XS_WAVEFORM)" = "1" ]; then \
		echo "[WAVEFORM] ref : $$REF_WAVEFORM"; \
	fi; \
	echo "[CMD] cd $(XS_REF_BUILD_ABS) && $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b 0 $(if $(filter 1,$(XS_WAVEFORM_FULL)),-e -1,-e 0) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$REF_WAVEFORM,)"; \
	cd $(XS_REF_BUILD_ABS) && $(XS_EMU_PREFIX) ./emu \
		-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
		--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
		-b 0 $(if $(filter 1,$(XS_WAVEFORM_FULL)),-e -1,-e 0) \
		$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
		$(XS_RAM_TRACE_ARGS) \
		$(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
		$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$REF_WAVEFORM,) \
		2>&1 | tee "$$REF_LOG"

run_xs_wolf_emu:
	@RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	mkdir -p "$$LOG_DIR"; \
	WOLF_LOG="$$LOG_DIR/xs_wolf_$${RUN_ID}.log"; \
	WOLF_WAVEFORM="$(XS_WAVEFORM_DIR_ABS)/xs_wolf_$${RUN_ID}.fst"; \
	printf '' > "$$WOLF_LOG"; \
	echo "[RUN] xs wolf emu"; \
	echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL)"; \
	echo "[LOG] wolf: $$WOLF_LOG"; \
	if [ "$(XS_WAVEFORM)" = "1" ]; then \
		echo "[WAVEFORM] wolf: $$WOLF_WAVEFORM"; \
	fi; \
	echo "[CMD] cd $(XS_WOLF_BUILD_ABS) && $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b 0 $(if $(filter 1,$(XS_WAVEFORM_FULL)),-e -1,-e 0) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$WOLF_WAVEFORM,)"; \
	cd $(XS_WOLF_BUILD_ABS) && $(XS_EMU_PREFIX) ./emu \
		-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
		--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
		-b 0 $(if $(filter 1,$(XS_WAVEFORM_FULL)),-e -1,-e 0) \
		$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
		$(XS_RAM_TRACE_ARGS) \
		$(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
		$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$WOLF_WAVEFORM,) \
		2>&1 | tee "$$WOLF_LOG"

run_xs_json_test:
	@RUN_ID="$$(date +%Y%m%d_%H%M%S)"; \
	$(MAKE) --no-print-directory xs_wolf_emu RUN_ID=$$RUN_ID XS_JSON_ROUNDTRIP=1; \
	$(MAKE) --no-print-directory run_xs_wolf_emu RUN_ID=$$RUN_ID

run_xs_diff:
	@$(MAKE) --no-print-directory xs_diff_clean
	@$(MAKE) --no-print-directory xs_ref_emu xs_wolf_emu
	@RUN_ID="$$(date +%Y%m%d_%H%M%S)"; \
	echo "[RUN] parallel xs diff"; \
	{ start=$$(date +%s); \
	  $(MAKE) --no-print-directory run_xs_wolf_emu RUN_ID=$$RUN_ID; \
	  wolf_status=$$?; \
	  end=$$(date +%s); \
	  wolf_log="$(XS_LOG_DIR_ABS)/xs_wolf_$${RUN_ID}.log"; \
	  mkdir -p "$(XS_LOG_DIR_ABS)"; \
	  echo "[TIME] xs wolf emu: $$((end-start))s" | tee -a "$$wolf_log"; \
	  exit $$wolf_status; } & wolf_pid=$$!; \
	{ start=$$(date +%s); \
	  $(MAKE) --no-print-directory run_xs_ref_emu RUN_ID=$$RUN_ID; \
	  ref_status=$$?; \
	  end=$$(date +%s); \
	  ref_log="$(XS_LOG_DIR_ABS)/xs_ref_$${RUN_ID}.log"; \
	  mkdir -p "$(XS_LOG_DIR_ABS)"; \
	  echo "[TIME] xs ref emu: $$((end-start))s" | tee -a "$$ref_log"; \
	  exit $$ref_status; } & ref_pid=$$!; \
	wait $$wolf_pid; wolf_status=$$?; \
	wait $$ref_pid; ref_status=$$?; \
	if [ $$wolf_status -ne 0 ] || [ $$ref_status -ne 0 ]; then \
		echo "[FAIL] xs diff: wolf=$$wolf_status ref=$$ref_status"; \
		exit 1; \
	fi

clean:
	@rm -rf build
	@rm -rf $(C910_WORK_DIR)
	@rm -rf $(XS_ROOT)/build
