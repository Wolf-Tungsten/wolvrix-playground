SHELL := /bin/bash
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

FST_ROI_DISCOVERY_GOALS := build_fst_roi_discovery test_fst_roi_discovery clean_fst_roi_discovery
FST_DIFF_GOALS := build_fst_diff clean_fst_diff
VRT_GOALS := run_vrt_selftest clean_vrt_selftest vrt_inbox
ifneq ($(filter $(FST_ROI_DISCOVERY_GOALS) $(FST_DIFF_GOALS) $(VRT_GOALS),$(MAKECMDGOALS)),)
SKIP_WOLF_ENV_CHECK := 1
endif

WOLVRIX_DIR ?= $(CURDIR)/wolvrix
PYTHON ?= python3
ifeq ($(origin CC), default)
CC := clang
endif
ifeq ($(origin CC), undefined)
CC := clang
endif
ifeq ($(origin CXX), default)
CXX := clang++
endif
ifeq ($(origin CXX), undefined)
CXX := clang++
endif
export CC
export CXX

# Check env.sh must exist and has been sourced
ENV_FILE := $(CURDIR)/env.sh
ifeq ($(SKIP_WOLF_ENV_CHECK),)
ifeq (,$(wildcard $(ENV_FILE)))
    $(error env.sh not found. Please run: cp $(CURDIR)/env.sh.template $(CURDIR)/env.sh && source $(CURDIR)/env.sh)
endif

ifeq ($(WOLF_ENV_SOURCED),)
    $(error env.sh exists but not sourced. Please run: source $(CURDIR)/env.sh)
endif
endif

# Auto-load environment from env.sh
export TOOL_EXTENSION := $(or $(TOOL_EXTENSION),$(shell grep '^export TOOL_EXTENSION=' $(ENV_FILE) 2>/dev/null | cut -d'"' -f2))
export VERILATOR := $(or $(VERILATOR),$(shell grep '^export VERILATOR=' $(ENV_FILE) 2>/dev/null | cut -d'"' -f2))

DUT ?=
CASE ?=
LOG_ONLY_SIM ?= 0

BUILD_DIR ?= build
WOLVRIX_BUILD_DIR ?= $(WOLVRIX_DIR)/build
FST_ROI_DISCOVERY_DIR := $(REPO_ROOT)/tools/fst_tools/roi_discovery
CMAKE ?= cmake
WOLVRIX_APP := $(WOLVRIX_BUILD_DIR)/bin/wolvrix
PIP ?= $(PYTHON) -m pip
RUN_ID ?= $(shell date +%Y%m%d_%H%M%S)

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

WOLVRIX_GRHSIM_WAVEFORM ?= 0
WOLVRIX_GRHSIM_PERF ?= 0
export WOLVRIX_GRHSIM_PERF
# Per-supernode rdtscp timing probes in generated model code (module-level time
# attribution, see pdocs/grhsim.md section 6). Default off: zero
# generated-code and compile-time impact.
WOLVRIX_GRHSIM_SN_TIMING ?= 0
export WOLVRIX_GRHSIM_SN_TIMING

HDLBITS_ROOT := $(CURDIR)/testcase/hdlbits
HDLBITS_WOLVRIX_SCRIPT := $(CURDIR)/scripts/wolvrix_hdlbits_emit.py
HDLBITS_GRHSIM_SCRIPT := $(CURDIR)/scripts/wolvrix_hdlbits_grhsim.py

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
XS_HIER_JSON_SCRIPT := $(CURDIR)/grh-ir-visualize/tools/export_xiangshan_hier_json.py
XS_GRHSIM_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_grhsim.py
REF_GSIM_ROOT ?= $(CURDIR)/reference/gsim
REF_GSIM_BIN ?= $(REF_GSIM_ROOT)/build/gsim/gsim

XS_SIM_MAX_CYCLE ?= 0
XS_WAVEFORM ?= 0
XS_WAVEFORM_FULL ?= 0
XS_COMMIT_TRACE ?= 0
XS_PROGRESS_EVERY_CYCLES ?= 0
XS_LOG_BEGIN ?= 0
XS_LOG_END ?= $(if $(filter 1,$(XS_WAVEFORM_FULL)),-1,0)
XS_RAM_TRACE ?= 0
XS_NUM_CORES ?= 1
XS_EMU_THREADS ?= 2
XS_VM_BUILD_JOBS ?= $(shell nproc)
XS_SIM_TOP ?= SimTop
XS_RTL_SUFFIX ?= sv
# XiangShan RTL generation preserves aggregates; prebuilt references have their
# own build provenance and can use plain RTL.
XS_PRESERVE_AGGREGATE ?= all
ifneq ($(XS_PRESERVE_AGGREGATE),all)
$(error XiangShan requires preserve-aggregate=all; scalar RTL generation was removed)
endif
# mill 0.12.15 (testcase/xiangshan/.mill-version) needs JDK 17 and the repo-root
# mill launcher on PATH; empty XS_JAVA_HOME = rely on the ambient environment.
XS_JAVA_HOME ?= $(firstword $(wildcard /usr/lib/jvm/java-17-openjdk-amd64))
ifneq ($(strip $(XS_JAVA_HOME)),)
XS_MILL_ENV := JAVA_HOME="$(XS_JAVA_HOME)" PATH="$(XS_JAVA_HOME)/bin:$(CURDIR):$$PATH"
else
XS_MILL_ENV := PATH="$(CURDIR):$$PATH"
endif
XS_WITH_CHISELDB ?= 0
XS_WITH_CONSTANTIN ?= 0
XS_ZERO_INIT ?= 0
XS_EMU_CPU ?= 2
ifeq ($(XS_ZERO_INIT),1)
XS_ZERO_INIT_DEFINES := RANDOMIZE_REG_INIT RANDOMIZE_MEM_INIT RANDOMIZE_DELAY=0 RANDOM=32'h0
else
XS_ZERO_INIT_DEFINES :=
endif
XS_ZERO_INIT_SIM_DEFINES := $(subst 32'h0,32\'h0,$(XS_ZERO_INIT_DEFINES))
XS_SIM_VFLAGS ?= +define+DIFFTEST $(foreach d,$(XS_ZERO_INIT_SIM_DEFINES),+define+$(d))
XS_EMU_PREFIX ?= taskset -c $(XS_EMU_CPU) $(shell if command -v stdbuf >/dev/null 2>&1; then echo "stdbuf -oL -eL"; fi)
# Reference-difftest CLI args shared by the gsim/grhsim run targets; override
# (e.g. XS_EMU_DIFF_ARGS=--no-diff) only for diagnostic no-difftest runs.
XS_EMU_DIFF_ARGS ?= --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so
XS_RAM_TRACE_ARGS := $(if $(filter 1,$(XS_RAM_TRACE)),+trace_difftest_ram,)
XS_LOG_DIR ?= $(REPO_ROOT)/ptmp/xs/logs
XS_WAVEFORM_DIR ?= $(XS_LOG_DIR)
XS_LOG_DIR_ABS = $(abspath $(XS_LOG_DIR))
XS_WAVEFORM_DIR_ABS = $(abspath $(XS_WAVEFORM_DIR))
XS_WAVEFORM_PATH_ABS = $(if $(XS_WAVEFORM_PATH),$(if $(filter /%,$(XS_WAVEFORM_PATH)),$(XS_WAVEFORM_PATH),$(abspath $(XS_WAVEFORM_PATH))),)

XS_WORK_BASE ?= $(REPO_ROOT)/ptmp/xs
XS_RTL_BUILD ?= $(XS_WORK_BASE)/rtl
XS_REF_BUILD ?= $(XS_WORK_BASE)/ref
XS_GSIM_BUILD ?= $(XS_WORK_BASE)/gsim
XS_GSIM_PGO_BUILD ?= $(XS_WORK_BASE)/gsim-pgo
XS_GRHSIM_BUILD ?= $(XS_WORK_BASE)/grhsim
XS_RTL_DIR := $(XS_RTL_BUILD)/rtl
XS_VSRC_DIR ?= $(XS_ROOT)/difftest/src/test/vsrc/common
XS_GRHSIM_FILELIST ?= $(XS_GRHSIM_BUILD)/xs_grhsim.f
XS_GRHSIM_HIER_JSON ?= $(XS_GRHSIM_BUILD)/xs_grhsim_hier.json
XS_GRHSIM_HIER_JSON_ROUNDTRIP ?= 1
XS_GRHSIM_HIER_JSON_SKIP_SAFE_PASSES ?= 0
XS_GRHSIM_ROUNDTRIP_VERIFY ?= 1
XS_GRHSIM_FLAT_GRH_JSON ?= $(XS_GRHSIM_BUILD)/xiangshan_flat_grh.json
XS_GRHSIM_JSON ?= $(XS_GRHSIM_BUILD)/xiangshan_grhsim.json
XS_GRHSIM_ROUNDTRIP_JSON ?= $(XS_GRHSIM_BUILD)/xiangshan_grhsim_roundtrip.json
XS_GRHSIM_MEM_MIN_BYTES ?=
XS_GRHSIM_RESUME_FROM_FLAT_GRH_JSON ?= 0
XS_GRHSIM_KEEP_ORIGINS ?= 1
XS_GRHSIM_EMIT_CPP_DIR ?= $(XS_GRHSIM_BUILD)/model
XS_GRHSIM_OVERWRITE_CPP ?= 1
XS_GRHSIM_READABLE_NAMES ?= 1
XS_GRHSIM_SOURCE_COMMENTS ?= 1
XS_GRHSIM_READABLE_DUMP ?= 1
XS_GRHSIM_READABLE_FRAMES ?= 1
# Activate readers once per enabled memory write group.
XS_GRHSIM_MEM_WRITE_ACTIVATE ?= on-write
XS_GRHSIM_MEM_ENABLE_BITMAP ?= on
# Function and translation-unit budgets apply only inside the emitter.
XS_GRHSIM_MAX_FUNCTION_LINES ?= 1024
XS_GRHSIM_MAX_TU_BYTES ?= 1048576
XS_GRHSIM_MAX_OUTPUT_FILE_BYTES ?= 4294967296
XS_GRHSIM_CLONE_SHARED_COMPUTE ?= 1
XS_GRHSIM_CLONE_SHARED_COMPUTE_MAX_CLONES ?= 250000
# B6 per-partition simplify (M5d-5); disable only for pipeline debugging.
XS_GRHSIM_PHASE_SIMPLIFY ?= 1
# B7 mask/array reduction recovery (aggregate CoreMark 100k: -2.96% Host time).
XS_GRHSIM_MASKED_OR ?= 1
XS_GRHSIM_MASKED_OR_MIN_TERMS ?= 16
XS_GRHSIM_MASKED_OR_REPORT ?=
XS_GRHSIM_PACK_BIT_REGISTERS ?= 1
XS_GRHSIM_PACK_BIT_REGISTERS_REPORT ?=
XS_SIM_DEFINES ?= DIFFTEST
XS_SIM_DEFINES += $(XS_ZERO_INIT_DEFINES)
XS_ROOT_ABS := $(abspath $(XS_ROOT))
XS_NOOP_HOME ?= $(XS_ROOT_ABS)
XS_RTL_BUILD_ABS := $(abspath $(XS_RTL_BUILD))
XS_REF_BUILD_ABS := $(abspath $(XS_REF_BUILD))
XS_GSIM_BUILD_ABS := $(abspath $(XS_GSIM_BUILD))
XS_GSIM_PGO_BUILD_ABS := $(abspath $(XS_GSIM_PGO_BUILD))
XS_GSIM_RTPROF_BUILD ?= $(XS_WORK_BASE)/gsim-rtprof
XS_GSIM_RTPROF_BUILD_ABS := $(abspath $(XS_GSIM_RTPROF_BUILD))
XS_GRHSIM_BUILD_ABS := $(abspath $(XS_GRHSIM_BUILD))
XS_RTL_DIR_ABS := $(abspath $(XS_RTL_DIR))
XS_VSRC_DIR_ABS := $(abspath $(XS_VSRC_DIR))
XS_GRHSIM_FILELIST_ABS := $(abspath $(XS_GRHSIM_FILELIST))
XS_GRHSIM_HIER_JSON_ABS := $(abspath $(XS_GRHSIM_HIER_JSON))
XS_GRHSIM_FLAT_GRH_JSON_ABS := $(abspath $(XS_GRHSIM_FLAT_GRH_JSON))
XS_GRHSIM_JSON_ABS := $(abspath $(XS_GRHSIM_JSON))
XS_GRHSIM_ROUNDTRIP_JSON_ABS := $(abspath $(XS_GRHSIM_ROUNDTRIP_JSON))
XS_SIM_TOP_V := $(XS_RTL_DIR_ABS)/$(XS_SIM_TOP).$(XS_RTL_SUFFIX)
XS_SIM_TOP_FIR := $(XS_RTL_DIR_ABS)/$(XS_SIM_TOP).fir
XS_GSIM_SUPERNODE_MAX_SIZE ?= 15
XS_DIFFTEST_GEN_DIR ?= $(XS_ROOT)/build/generated-src
XS_DIFFTEST_GEN_DIR_ABS := $(abspath $(XS_DIFFTEST_GEN_DIR))
XS_GRHSIM_INCLUDE_DIRS ?= $(XS_RTL_DIR_ABS) $(XS_VSRC_DIR_ABS) $(XS_DIFFTEST_GEN_DIR_ABS)
XS_GRHSIM_INCLUDE_FLAGS := $(foreach d,$(XS_GRHSIM_INCLUDE_DIRS),-I $(d))
XS_GRHSIM_DEFINE_FLAGS := $(foreach d,$(XS_SIM_DEFINES),-D "$(d)")
XS_DIFFTEST_MACROS := $(XS_ROOT)/build/generated-src/DifftestMacros.svh
XS_DIFFTEST_GSIM_EXTMODULE := $(XS_ROOT)/build/generated-src/difftest-extmodule.cpp
XS_GSIM_BIN ?= $(REF_GSIM_BIN)

# HDLBits paths
HDLBITS_DUT_SRC := $(HDLBITS_ROOT)/dut/dut_$(DUT).v
HDLBITS_TB_SRC := $(HDLBITS_ROOT)/tb/tb_$(DUT).cpp
HDLBITS_GRHTB_SRC := $(HDLBITS_ROOT)/grhtb/grhtb_$(DUT).cpp
HDLBITS_OUT_DIR := $(BUILD_DIR)/hdlbits/$(DUT)
HDLBITS_EMITTED_DUT := $(HDLBITS_OUT_DIR)/dut_$(DUT).v
HDLBITS_EMITTED_JSON := $(HDLBITS_OUT_DIR)/dut_$(DUT).json
HDLBITS_GRHSIM_BUILD_DIR := $(BUILD_DIR)/hdlbits-grhsim
HDLBITS_SIM_BIN_NAME := sim_$(DUT)
HDLBITS_SIM_BIN := $(HDLBITS_OUT_DIR)/$(HDLBITS_SIM_BIN_NAME)
HDLBITS_VERILATOR_PREFIX := Vdut_$(DUT)
HDLBITS_TB_SOURCES := $(wildcard $(HDLBITS_ROOT)/tb/tb_*.cpp)
HDLBITS_DUTS := $(sort $(patsubst tb_%,%,$(basename $(notdir $(HDLBITS_TB_SOURCES)))))
HDLBITS_GRHTB_SOURCES := $(wildcard $(HDLBITS_ROOT)/grhtb/grhtb_*.cpp)
HDLBITS_GRHSIM_DUTS := $(sort $(patsubst grhtb_%,%,$(basename $(notdir $(HDLBITS_GRHTB_SOURCES)))))

.PHONY: all build init_submodule check_id build_fst_roi_discovery test_fst_roi_discovery clean_fst_roi_discovery run_hdlbits_test run_all_hdlbits_tests run_c910_test run_c910_ref_test \
	run_hdlbits_grhsim run_all_hdlbits_grhsim_tests xs_rtl xs_gsim_rtl xs_grhsim_filelist xs_grhsim_hier_json xs_grhsim xs_ref_emu xs_gsim_emu \
	run_xs_ref_emu run_xs_gsim_emu \
	xs_gsim_emu_pgo xs_gsim_emu_rtprof xs_gsim_export_precoarsen \
	xs_grhsim_emu xs_grhsim_build_emu xs_grhsim_emu_pgo xs_grhsim_build_emu_pgo \
	clean

all: build

init_submodule:
	@git submodule update --init --recursive wolvrix testcase/hdlbits testcase/openc910
	@git submodule update --init testcase/xiangshan
	@git submodule update --init reference/gsim
	@$(MAKE) --no-print-directory -C testcase/xiangshan init

check_id:
	@if [[ ! "$(DUT)" =~ ^[0-9]{3}$$ ]]; then \
		echo "DUT must be a three-digit number (e.g. DUT=001)"; \
		exit 1; \
	fi
	@test -f $(HDLBITS_DUT_SRC) || { echo "Missing DUT source: $(HDLBITS_DUT_SRC)"; exit 1; }
	@test -f $(HDLBITS_TB_SRC) || { echo "Missing testbench: $(HDLBITS_TB_SRC)"; exit 1; }

check_grhsim_id:
	@if [[ ! "$(DUT)" =~ ^[0-9]{3}$$ ]]; then \
		echo "DUT must be a three-digit number (e.g. DUT=001)"; \
		exit 1; \
	fi
	@test -f $(HDLBITS_DUT_SRC) || { echo "Missing DUT source: $(HDLBITS_DUT_SRC)"; exit 1; }
	@test -f $(HDLBITS_GRHTB_SRC) || { echo "Missing GrhSIM testbench: $(HDLBITS_GRHTB_SRC)"; exit 1; }

build:
	env -u MAKE_TERMOUT $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR) \
		-DCMAKE_BUILD_TYPE=Release \
		-DCMAKE_C_COMPILER=$(CC) \
		-DCMAKE_CXX_COMPILER=$(CXX)
	$(CMAKE) --build $(WOLVRIX_BUILD_DIR)

build_fst_roi_discovery:
	@$(MAKE) --no-print-directory -C $(FST_ROI_DISCOVERY_DIR) all

test_fst_roi_discovery:
	@$(MAKE) --no-print-directory -C $(FST_ROI_DISCOVERY_DIR) test

clean_fst_roi_discovery:
	@$(MAKE) --no-print-directory -C $(FST_ROI_DISCOVERY_DIR) clean

FST_DIFF_DIR := $(REPO_ROOT)/tools/fst_tools/fst_diff

build_fst_diff:
	@$(MAKE) --no-print-directory -C $(FST_DIFF_DIR) all

clean_fst_diff:
	@$(MAKE) --no-print-directory -C $(FST_DIFF_DIR) clean

$(WOLVRIX_APP): build

.PHONY: test_wolvrix
test_wolvrix: build
	mkdir -p $(CURDIR)/ptmp/ctest_tmp $(CURDIR)/ptmp/ctest_ccache
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) --output-on-failure

REMOVE_GRHSIM_IR_BASELINE ?= $(CURDIR)/ptmp/remove-grhsim-ir/r0-20261024
.PHONY: capture_remove_grhsim_ir_baseline replay_remove_grhsim_ir_baseline supplement_remove_grhsim_ir_baseline replay_remove_grhsim_ir_fixtures
capture_remove_grhsim_ir_baseline:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py capture --output "$(REMOVE_GRHSIM_IR_BASELINE)"

replay_remove_grhsim_ir_baseline:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py replay --output "$(REMOVE_GRHSIM_IR_BASELINE)"

supplement_remove_grhsim_ir_baseline:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py supplement --output "$(REMOVE_GRHSIM_IR_BASELINE)"

replay_remove_grhsim_ir_fixtures:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py fixtures --output "$(REMOVE_GRHSIM_IR_BASELINE)"

REMOVE_GRHSIM_IR_OBSERVATIONS ?= $(CURDIR)/ptmp/remove-grhsim-ir/r0-observations-v2
.PHONY: replay_remove_grhsim_ir_observations
replay_remove_grhsim_ir_observations:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_observations.py prepare --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_OBSERVATIONS)"
	$(MAKE) -f scripts/remove_grhsim_ir_observations.mk OBSERVATION_DIR="$(REMOVE_GRHSIM_IR_OBSERVATIONS)"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_observations.py collect --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_OBSERVATIONS)"

.PHONY: test_remove_grhsim_ir_foundation
test_remove_grhsim_ir_foundation:
	mkdir -p $(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CURDIR)/ptmp/remove-grhsim-ir/ccache
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grh-sim-foundation-tests grhsim-dialect-tests -j 4
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(grh-sim-foundation-tests|grhsim-dialect-tests)$$' --output-on-failure

.PHONY: test_grh_to_grhsim
test_grh_to_grhsim:
	mkdir -p $(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CURDIR)/ptmp/remove-grhsim-ir/ccache
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grh-to-grhsim-tests grh-sim-foundation-tests grhsim-dialect-tests -j 4
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(grh-to-grhsim-tests|grh-sim-foundation-tests|grhsim-dialect-tests)$$' --output-on-failure

.PHONY: test_grh_type_boundaries
test_grh_type_boundaries:
	mkdir -p $(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CURDIR)/ptmp/remove-grhsim-ir/ccache
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grh-sim-foundation-tests transform-hier-flatten transform-instance-inline -j 4
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(grh-sim-foundation-tests|transform-hier-flatten|transform-instance-inline)$$' --output-on-failure

.PHONY: test_grhsim_transforms
test_grhsim_transforms:
	mkdir -p $(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CURDIR)/ptmp/remove-grhsim-ir/ccache
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-transform-tests grh-to-grhsim-tests grh-sim-foundation-tests grhsim-dialect-tests -j 4
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(grhsim-transform-tests|grh-to-grhsim-tests|grh-sim-foundation-tests|grhsim-dialect-tests)$$' --output-on-failure

REMOVE_GRHSIM_IR_SIMPLIFY_MODEL ?= $(REMOVE_GRHSIM_IR_ROB)/flat.json
REMOVE_GRHSIM_IR_SIMPLIFY_PROBE ?= $(CURDIR)/ptmp/remove-grhsim-ir/simplify-probe
.PHONY: probe_remove_grhsim_ir_simplify
probe_remove_grhsim_ir_simplify:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/probe_remove_grhsim_ir_simplify.py --model "$(REMOVE_GRHSIM_IR_SIMPLIFY_MODEL)" --output "$(REMOVE_GRHSIM_IR_SIMPLIFY_PROBE)"
REMOVE_GRHSIM_IR_PASS_BENCH ?= $(CURDIR)/ptmp/remove-grhsim-ir/pass-bench
REMOVE_GRHSIM_BENCH_PASSES ?= grhsim-simplify
REMOVE_GRHSIM_BENCH_ROUNDS ?= 8
.PHONY: bench_remove_grhsim_ir_passes profile_remove_grhsim_ir_passes
bench_remove_grhsim_ir_passes:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/bench_remove_grhsim_ir_passes.py --model "$(REMOVE_GRHSIM_IR_SIMPLIFY_MODEL)" \
		--report "$(REMOVE_GRHSIM_IR_PASS_BENCH)/timings.json" --rounds "$(REMOVE_GRHSIM_BENCH_ROUNDS)" --passes $(REMOVE_GRHSIM_BENCH_PASSES)
profile_remove_grhsim_ir_passes:
	@mkdir -p "$(REMOVE_GRHSIM_IR_PASS_BENCH)"
	perf record -e cpu-clock:u -F 49 --call-graph dwarf,4096 --switch-output=60s -o "$(REMOVE_GRHSIM_IR_PASS_BENCH)/perf.data" \
		$(MAKE) --no-print-directory bench_remove_grhsim_ir_passes
	@for sample in "$(REMOVE_GRHSIM_IR_PASS_BENCH)"/perf.data*; do \
		perf report --stdio --no-children -i "$$sample" > "$$sample.txt"; \
	done
REMOVE_GRHSIM_IR_SINK_PROBE ?= $(CURDIR)/ptmp/remove-grhsim-ir/sink-probe.json
.PHONY: probe_remove_grhsim_ir_sink
probe_remove_grhsim_ir_sink:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/probe_remove_grhsim_ir_sink.py --model "$(REMOVE_GRHSIM_IR_ROB_CHECKPOINT)" --report "$(REMOVE_GRHSIM_IR_SINK_PROBE)"

.PHONY: debug_grhsim_transforms
debug_grhsim_transforms:
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp gdb -q -batch -ex 'catch throw' -ex run -ex bt --args $(WOLVRIX_BUILD_DIR)/bin/grhsim-transform-tests

.PHONY: test_grhsim_virtual_partitions test_grhsim_sink_schedule
test_grhsim_virtual_partitions test_grhsim_sink_schedule:
	mkdir -p $(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CURDIR)/ptmp/remove-grhsim-ir/ccache
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-virtual-partition-tests grhsim-sink-schedule-tests grhsim-transform-tests -j 4
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(grhsim-virtual-partition-tests|grhsim-sink-schedule-tests|grhsim-transform-tests)$$' --output-on-failure

.PHONY: test_ingest_expression_width
GRHSIM_CPU_ST_CPP_JOBS ?= 4
GRHSIM_CPU_ST_CPP_CASES ?= run
.PHONY: generate_grhsim_cpu_st_cpp test_grhsim_cpu_st_cpp run_grhsim_cpu_st_cpp
.PHONY: test_grhsim_readable_store
test_grhsim_readable_store:
	mkdir -p $(CURDIR)/ptmp/grhsim-readable/build-tmp $(CURDIR)/ptmp/grhsim-readable/ccache
	TMPDIR=$(CURDIR)/ptmp/grhsim-readable/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/grhsim-readable/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/grhsim-readable/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/grhsim-readable/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target store-text store-json store-load-origin-attrs -j 4
	TMPDIR=$(CURDIR)/ptmp/grhsim-readable/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/grhsim-readable/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(store-text|store-json|store-load-origin-attrs)$$' --output-on-failure

.PHONY: test_grhsim_readable_python
test_grhsim_readable_python:
	mkdir -p $(CURDIR)/ptmp/grhsim-readable/build-tmp $(CURDIR)/ptmp/grhsim-readable/ccache $(CURDIR)/ptmp/grhsim-readable/pip-cache
	@if [ "$(SKIP_PY_INSTALL)" != "1" ]; then \
		TMPDIR=$(CURDIR)/ptmp/grhsim-readable/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/grhsim-readable/ccache PIP_CACHE_DIR=$(CURDIR)/ptmp/grhsim-readable/pip-cache $(MAKE) --no-print-directory py_install; \
	fi
	PYTHONDONTWRITEBYTECODE=1 GRHSIM_READABLE_TEST_WORK=$(CURDIR)/ptmp/grhsim-readable/python $(PYTHON) -m unittest discover -s scripts -p test_grhsim_readable.py
	TMPDIR=$(CURDIR)/ptmp/grhsim-readable/build-tmp $(MAKE) -C $(CURDIR)/ptmp/grhsim-readable/python -j 4 run

.PHONY: test_grhsim_readable_cpp
test_grhsim_readable_cpp: generate_grhsim_cpu_st_cpp
	mkdir -p $(CURDIR)/ptmp/grhsim-readable/build-tmp
	TMPDIR=$(CURDIR)/ptmp/grhsim-readable/build-tmp $(MAKE) -C $(WOLVRIX_BUILD_DIR)/artifacts/grhsim-cpu-st-cpp -j 4 \
		readable-emission-b16 readable-emission-b16-explicit readable-emission-b16-off readable-emission-b16-frames readable-emission-b16-compact \
		readable-emission-b1024 readable-emission-b1024-explicit readable-emission-b1024-off readable-emission-b1024-frames readable-emission-b1024-compact \
		phases-b16-tu4096 phases-b1024-tu1048576 chunk-control-b16 chunk-control-b1024 \
		effects-b16 effects-b1024 init-b16 init-b1024 waveform-b16 waveform-b1024 \
		sink-private-b16 sink-private-b1024 snapshot-identity-b16 snapshot-identity-b1024 large-store-construction

.PHONY: inspect_grhsim_readable_model
GRHSIM_READABLE_MODEL ?= $(CURDIR)/ptmp/grhsim-readable/xiangshan/model
inspect_grhsim_readable_model:
	@test -s "$(GRHSIM_READABLE_MODEL)/grhsim.txt"
	jq -e '{top, readable_names, source_comments, readable_frames, function_count: (.functions | length), source_count: (.sources | length), largest_function: ([.functions[].lines] | max)}' "$(GRHSIM_READABLE_MODEL)/manifest.json"
	jq --stream empty "$(GRHSIM_READABLE_MODEL)/code-map.json"
	@echo "Readable model JSON validated with bounded memory."

generate_grhsim_cpu_st_cpp:
	mkdir -p $(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CURDIR)/ptmp/remove-grhsim-ir/ccache
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-cpu-st-cpp-tests -j 4
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp CCACHE_DIR=$(CURDIR)/ptmp/remove-grhsim-ir/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^grhsim-cpu-st-cpp-tests$$' --output-on-failure
test_grhsim_cpu_st_cpp: generate_grhsim_cpu_st_cpp
	$(MAKE) --no-print-directory run_grhsim_cpu_st_cpp
run_grhsim_cpu_st_cpp:
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(MAKE) -C $(WOLVRIX_BUILD_DIR)/artifacts/grhsim-cpu-st-cpp -j $(GRHSIM_CPU_ST_CPP_JOBS) $(GRHSIM_CPU_ST_CPP_CASES)

REMOVE_GRHSIM_IR_COMPARISON ?= $(CURDIR)/ptmp/remove-grhsim-ir/r5-observations-single-call
REMOVE_GRHSIM_IR_EFFECT_POLICY ?= single-original-call-source-order
REMOVE_GRHSIM_IR_COMPARE_ARGS = --frozen "$(REMOVE_GRHSIM_IR_OBSERVATIONS)" --models "$(WOLVRIX_BUILD_DIR)/artifacts/grhsim-cpu-st-cpp/observations" --output "$(REMOVE_GRHSIM_IR_COMPARISON)" --effect-policy "$(REMOVE_GRHSIM_IR_EFFECT_POLICY)"
.PHONY: compare_remove_grhsim_ir
compare_remove_grhsim_ir: generate_grhsim_cpu_st_cpp
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/compare_remove_grhsim_ir.py prepare $(REMOVE_GRHSIM_IR_COMPARE_ARGS)
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(MAKE) -j 4 -f scripts/remove_grhsim_ir_observations.mk OBSERVATION_DIR="$(REMOVE_GRHSIM_IR_COMPARISON)" OBSERVATION_LIBRARY=libgrhsim_top.a
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/compare_remove_grhsim_ir.py collect $(REMOVE_GRHSIM_IR_COMPARE_ARGS)

REMOVE_GRHSIM_IR_ROB ?= $(CURDIR)/ptmp/remove-grhsim-ir/r6-rob
REMOVE_GRHSIM_IR_ROB_GSIM_HEADERS ?= $(CURDIR)/ptmp/xs-components-rob/gsim-model
.PHONY: generate_remove_grhsim_ir_rob compare_remove_grhsim_ir_rob
.PHONY: prepare_remove_grhsim_ir_rob
prepare_remove_grhsim_ir_rob:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_rob.py prepare --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_ROB)"
REMOVE_GRHSIM_IR_XS_FRESH ?= $(CURDIR)/ptmp/remove-grhsim-ir/xs-fresh
REMOVE_GRHSIM_IR_FROZEN_BINDING ?= $(CURDIR)/ptmp/remove-grhsim-ir/frozen-binding
REMOVE_GRHSIM_IR_FROZEN_COMPILER ?= $(CURDIR)/ptmp/remove-grhsim-ir/frozen-compiler
.PHONY: build_remove_grhsim_ir_frozen_compiler
build_remove_grhsim_ir_frozen_compiler:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py compiler-inputs --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)"
	$(MAKE) --no-print-directory -j 4 -f scripts/remove_grhsim_ir_frozen_binding.mk BINDING_DIR="$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)" REPO_ROOT="$(CURDIR)" REBUILD_FROZEN_COMPILER=1
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/python" LD_LIBRARY_PATH="$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/python/wolvrix" $(PYTHON) -S -c 'import pathlib, wolvrix; expected = pathlib.Path("$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/python/wolvrix").resolve(); assert pathlib.Path(wolvrix.__file__).resolve().parent == expected; s = wolvrix.Session(); print(wolvrix.__file__); print(len(wolvrix.list_grhsim_passes())); s.close()'
.PHONY: build_remove_grhsim_ir_frozen_binding
build_remove_grhsim_ir_frozen_binding:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py binding-inputs --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_FROZEN_BINDING)"
	$(MAKE) --no-print-directory -j 4 -f scripts/remove_grhsim_ir_frozen_binding.mk BINDING_DIR="$(REMOVE_GRHSIM_IR_FROZEN_BINDING)" REPO_ROOT="$(CURDIR)"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(REMOVE_GRHSIM_IR_FROZEN_BINDING)/python" LD_LIBRARY_PATH="$(REMOVE_GRHSIM_IR_FROZEN_BINDING)/python/wolvrix" $(PYTHON) -S -c 'import pathlib, wolvrix; expected = pathlib.Path("$(REMOVE_GRHSIM_IR_FROZEN_BINDING)/python/wolvrix").resolve(); assert pathlib.Path(wolvrix.__file__).resolve().parent == expected; s = wolvrix.Session(); print(wolvrix.__file__); print(len(wolvrix.list_grhsim_passes())); s.close()'
.PHONY: prepare_remove_grhsim_ir_xs_inputs generate_remove_grhsim_ir_xs
prepare_remove_grhsim_ir_xs_inputs:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_baseline.py xs-inputs --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_XS_FRESH)"
generate_remove_grhsim_ir_xs: check_remove_grhsim_ir_options prepare_remove_grhsim_ir_xs_inputs $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/wolvrix_xs_grhsim.py \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/rtl.f" SimTop "$(REMOVE_GRHSIM_IR_XS_FRESH)/flat.json" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/graph.json" "$(REMOVE_GRHSIM_IR_XS_FRESH)/roundtrip.json" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/read_args.txt" info --emit-cpp-dir "$(REMOVE_GRHSIM_IR_XS_FRESH)/model" \
		> "$(REMOVE_GRHSIM_IR_XS_FRESH)/generation.log" 2>&1
.PHONY: build_remove_grhsim_ir_xs_from_sv
build_remove_grhsim_ir_xs_from_sv: check_xs_aggregate_rtl generate_remove_grhsim_ir_xs
	$(MAKE) --no-print-directory xs_grhsim_build_emu \
		XS_GRHSIM_BUILD="$(REMOVE_GRHSIM_IR_XS_FRESH)" \
		XS_GRHSIM_EMIT_CPP_DIR="$(REMOVE_GRHSIM_IR_XS_FRESH)/model"
.PHONY: generate_remove_grhsim_ir_xs_frozen
generate_remove_grhsim_ir_xs_frozen: build_remove_grhsim_ir_frozen_compiler prepare_remove_grhsim_ir_xs_inputs
	@test ! -e "$(REMOVE_GRHSIM_IR_XS_FRESH)/model" || { echo "[FAIL] frozen generation needs a new candidate directory"; exit 1; }
	@test -n "$(firstword $(wildcard $(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/source/scripts/wolvrix_xs_grhsim*.py))" || { echo "[FAIL] frozen compiler has no XS GrhSIM driver"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/python" LD_LIBRARY_PATH="$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/python/wolvrix" $(PYTHON) -S "$(firstword $(wildcard $(REMOVE_GRHSIM_IR_FROZEN_COMPILER)/source/scripts/wolvrix_xs_grhsim*.py))" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/rtl.f" SimTop "$(REMOVE_GRHSIM_IR_XS_FRESH)/flat.json" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/graph.json" "$(REMOVE_GRHSIM_IR_XS_FRESH)/roundtrip.json" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/read_args.txt" info --emit-cpp-dir "$(REMOVE_GRHSIM_IR_XS_FRESH)/model" \
		> "$(REMOVE_GRHSIM_IR_XS_FRESH)/generation.log" 2>&1
REMOVE_GRHSIM_IR_RESOURCE_TARGET ?= generate_remove_grhsim_ir_xs
REMOVE_GRHSIM_IR_CANDIDATE_LIB ?= $(CURDIR)/ptmp/remove-grhsim-ir/compile-candidate-lib
REMOVE_GRHSIM_IR_CANDIDATE_PYTHON ?= $(CURDIR)/ptmp/remove-grhsim-ir/compile-candidate-python
.PHONY: stage_remove_grhsim_ir_candidate_lib stage_remove_grhsim_ir_candidate_python
stage_remove_grhsim_ir_candidate_lib:
	@test ! -e "$(REMOVE_GRHSIM_IR_CANDIDATE_LIB)" || { echo "Candidate library directory must be new"; exit 1; }
	@mkdir -p "$(REMOVE_GRHSIM_IR_CANDIDATE_LIB)"
	cp "$(WOLVRIX_BUILD_DIR)/libwolvrix-lib.so" "$(REMOVE_GRHSIM_IR_CANDIDATE_LIB)/libwolvrix-lib.so"
stage_remove_grhsim_ir_candidate_python:
	@test ! -e "$(REMOVE_GRHSIM_IR_CANDIDATE_PYTHON)" || { echo "Candidate Python directory must be new"; exit 1; }
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR) \
		-DSKBUILD_PLATLIB_DIR=lib -DPython_EXECUTABLE="$(PYTHON)"
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target wolvrix_python -j 8
	@mkdir -p "$(REMOVE_GRHSIM_IR_CANDIDATE_PYTHON)"
	cp -a "$(WOLVRIX_BUILD_DIR)/python/wolvrix" "$(REMOVE_GRHSIM_IR_CANDIDATE_PYTHON)/wolvrix"
	cp "$(WOLVRIX_BUILD_DIR)/libwolvrix-lib.so" "$(REMOVE_GRHSIM_IR_CANDIDATE_PYTHON)/wolvrix/libwolvrix-lib.so"
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(REMOVE_GRHSIM_IR_CANDIDATE_PYTHON)" LD_LIBRARY_PATH="$(REMOVE_GRHSIM_IR_CANDIDATE_PYTHON)/wolvrix" $(PYTHON) -S -c 'import wolvrix; print(wolvrix.__file__); s = wolvrix.Session(); s.close()'
.PHONY: debug_remove_grhsim_ir_xs_frozen
debug_remove_grhsim_ir_xs_frozen: build_remove_grhsim_ir_frozen_binding prepare_remove_grhsim_ir_xs_inputs
	@test -n "$(firstword $(wildcard $(REMOVE_GRHSIM_IR_FROZEN_BINDING)/source/scripts/wolvrix_xs_grhsim*.py))" || { echo "[FAIL] frozen binding has no XS GrhSIM driver"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(REMOVE_GRHSIM_IR_FROZEN_BINDING)/python" LD_LIBRARY_PATH="$(REMOVE_GRHSIM_IR_FROZEN_BINDING)/python/wolvrix" gdb -q -batch -ex run -ex 'bt 24' --args $(PYTHON) -S "$(firstword $(wildcard $(REMOVE_GRHSIM_IR_FROZEN_BINDING)/source/scripts/wolvrix_xs_grhsim*.py))" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/rtl.f" SimTop "$(REMOVE_GRHSIM_IR_XS_FRESH)/flat.json" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/graph.json" "$(REMOVE_GRHSIM_IR_XS_FRESH)/roundtrip.json" \
		"$(REMOVE_GRHSIM_IR_XS_FRESH)/read_args.txt" info --emit-cpp-dir "$(REMOVE_GRHSIM_IR_XS_FRESH)/model" \
		> "$(REMOVE_GRHSIM_IR_XS_FRESH)/gdb.log" 2>&1
REMOVE_GRHSIM_IR_RESOURCE_OUTPUT ?= $(CURDIR)/ptmp/remove-grhsim-ir/resources
.PHONY: measure_remove_grhsim_ir_resources test_remove_grhsim_ir_resources
measure_remove_grhsim_ir_resources:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/measure_remove_grhsim_ir_resources.py \
		--target "$(REMOVE_GRHSIM_IR_RESOURCE_TARGET)" --flow "$(REMOVE_GRHSIM_IR_XS_FRESH)" \
		--output "$(REMOVE_GRHSIM_IR_RESOURCE_OUTPUT)" --jobs "$(if $(VM_BUILD_JOBS),$(VM_BUILD_JOBS),4)" \
		$(if $(filter generate_remove_grhsim_ir_xs_frozen,$(REMOVE_GRHSIM_IR_RESOURCE_TARGET)),--frozen-binding "$(REMOVE_GRHSIM_IR_FROZEN_COMPILER)",)
test_remove_grhsim_ir_resources:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_remove_grhsim_ir_resources.py
generate_remove_grhsim_ir_rob: check_remove_grhsim_ir_options $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_rob.py prepare --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_ROB)"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/wolvrix_xs_grhsim.py \
		"$(REMOVE_GRHSIM_IR_ROB)/rtl.f" Rob "$(REMOVE_GRHSIM_IR_ROB)/flat.json" \
		"$(REMOVE_GRHSIM_IR_ROB)/graph.json" "$(REMOVE_GRHSIM_IR_ROB)/roundtrip.json" \
		"$(REMOVE_GRHSIM_IR_ROB)/read_args.txt" info --emit-cpp-dir "$(REMOVE_GRHSIM_IR_ROB)/model" \
		> "$(REMOVE_GRHSIM_IR_ROB)/generation.log" 2>&1
compare_remove_grhsim_ir_rob: generate_remove_grhsim_ir_rob
	$(MAKE) run_remove_grhsim_ir_rob
REMOVE_GRHSIM_IR_ROB_CHECKPOINT ?= $(CURDIR)/ptmp/remove-grhsim-ir/r6-rob-supernodes/roundtrip.json
.PHONY: reemit_remove_grhsim_ir_rob
reemit_remove_grhsim_ir_rob: check_remove_grhsim_ir_options $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_rob.py prepare --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_ROB)"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/reemit_grhsim.py --model "$(REMOVE_GRHSIM_IR_ROB_CHECKPOINT)" --flow "$(REMOVE_GRHSIM_IR_ROB)" --overwrite
	$(MAKE) run_remove_grhsim_ir_rob
.PHONY: build_remove_grhsim_ir_rob run_remove_grhsim_ir_rob
build_remove_grhsim_ir_rob:
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(MAKE) -j 4 -C "$(REMOVE_GRHSIM_IR_ROB)/model" CXX=clang++ CXXFLAGS='-std=c++20 -O3 -fno-strict-aliasing'
	clang++ -std=c++20 -O3 -fno-strict-aliasing -ffunction-sections -fdata-sections -Wl,--gc-sections -MMD -MF "$(REMOVE_GRHSIM_IR_ROB)/dump_outputs.d" \
		-I"$(REMOVE_GRHSIM_IR_ROB_GSIM_HEADERS)" -I"$(REMOVE_GRHSIM_IR_ROB)/model" \
		-DROB_BENCH_SOURCE='"$(REMOVE_GRHSIM_IR_ROB)/bench/rob_bench.cpp"' testcase/xs-components/scripts/rob_array_create_dump.cpp \
		"$(REMOVE_GRHSIM_IR_ROB)/model/libgrhsim_Rob.a" -o "$(REMOVE_GRHSIM_IR_ROB)/dump_outputs"
run_remove_grhsim_ir_rob: build_remove_grhsim_ir_rob
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_rob.py compare --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_ROB)"
.PHONY: compare_remove_grhsim_ir_rob_prefix
compare_remove_grhsim_ir_rob_prefix:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_rob.py compare-prefix --baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_ROB)"

.PHONY: build_remove_grhsim_ir_rob_runtime profile_remove_grhsim_ir_rob
REMOVE_GRHSIM_IR_ROB_PROFILE_CYCLES ?= 2000
REMOVE_GRHSIM_IR_ROB_PROFILE_MODEL ?= $(REMOVE_GRHSIM_IR_ROB)/model
REMOVE_GRHSIM_IR_ROB_PROFILE_BENCH ?= $(REMOVE_GRHSIM_IR_ROB)/bench/rob_bench.cpp
build_remove_grhsim_ir_rob_runtime:
	mkdir -p "$(REMOVE_GRHSIM_IR_ROB)"
	clang++ -std=c++20 -O3 -fno-strict-aliasing -ffunction-sections -fdata-sections -Wl,--gc-sections \
		-I"$(REMOVE_GRHSIM_IR_ROB_GSIM_HEADERS)" -I"$(REMOVE_GRHSIM_IR_ROB_PROFILE_MODEL)" \
		$(if $(filter 1,$(REMOVE_GRHSIM_IR_ROB_EXECUTION_COUNTERS)),-DROB_EXECUTION_COUNTS,) \
		-DROB_BENCH_SOURCE='"$(REMOVE_GRHSIM_IR_ROB_PROFILE_BENCH)"' scripts/probe_remove_grhsim_ir_rob_runtime.cpp \
		"$(REMOVE_GRHSIM_IR_ROB_PROFILE_MODEL)/libgrhsim_Rob.a" -o "$(REMOVE_GRHSIM_IR_ROB)/runtime_probe"
.PHONY: inspect_remove_grhsim_ir_rob_execution
inspect_remove_grhsim_ir_rob_execution: build_remove_grhsim_ir_rob_runtime
	@test "$(REMOVE_GRHSIM_IR_ROB_EXECUTION_COUNTERS)" = 1 || { echo '[FAIL] set REMOVE_GRHSIM_IR_ROB_EXECUTION_COUNTERS=1'; exit 1; }
	WOLVRIX_GRHSIM_EXECUTION_COUNTS="$(REMOVE_GRHSIM_IR_ROB)/execution1.tsv" "$(REMOVE_GRHSIM_IR_ROB)/runtime_probe" \
		"$(REMOVE_GRHSIM_IR_BASELINE)/frozen/ptmp/xs-components-rob/trace/rob_trace.bin" "$(REMOVE_GRHSIM_IR_ROB_PROFILE_CYCLES)" > "$(REMOVE_GRHSIM_IR_ROB)/execution1.log"
	WOLVRIX_GRHSIM_EXECUTION_COUNTS="$(REMOVE_GRHSIM_IR_ROB)/execution2.tsv" "$(REMOVE_GRHSIM_IR_ROB)/runtime_probe" \
		"$(REMOVE_GRHSIM_IR_BASELINE)/frozen/ptmp/xs-components-rob/trace/rob_trace.bin" "$(REMOVE_GRHSIM_IR_ROB_PROFILE_CYCLES)" > "$(REMOVE_GRHSIM_IR_ROB)/execution2.log"
	cmp "$(REMOVE_GRHSIM_IR_ROB)/execution1.tsv" "$(REMOVE_GRHSIM_IR_ROB)/execution2.tsv"
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_execution_counts.py --model-dir "$(REMOVE_GRHSIM_IR_ROB_PROFILE_MODEL)" \
		--run1 "$(REMOVE_GRHSIM_IR_ROB)/execution1.tsv" --run2 "$(REMOVE_GRHSIM_IR_ROB)/execution2.tsv" --report "$(REMOVE_GRHSIM_IR_ROB)/execution-summary.json"
profile_remove_grhsim_ir_rob: build_remove_grhsim_ir_rob_runtime
	perf record -F 199 -g -o "$(REMOVE_GRHSIM_IR_ROB)/runtime.perf.data" -- "$(REMOVE_GRHSIM_IR_ROB)/runtime_probe" \
		"$(REMOVE_GRHSIM_IR_BASELINE)/frozen/ptmp/xs-components-rob/trace/rob_trace.bin" "$(REMOVE_GRHSIM_IR_ROB_PROFILE_CYCLES)"
	perf report --stdio --no-children --sort symbol --percent-limit 0.5 -i "$(REMOVE_GRHSIM_IR_ROB)/runtime.perf.data" > "$(REMOVE_GRHSIM_IR_ROB)/runtime.perf.txt"
	perf report --stdio --no-children --sort symbol --percent-limit 0 -i "$(REMOVE_GRHSIM_IR_ROB)/runtime.perf.data" > "$(REMOVE_GRHSIM_IR_ROB)/runtime.perf-all.txt"

.PHONY: compare_remove_grhsim_ir_rob_runtime
REMOVE_GRHSIM_IR_ROB_OLD_RUNTIME ?= $(CURDIR)/ptmp/remove-grhsim-ir/r6-rob-frozen-runtime/runtime_probe
compare_remove_grhsim_ir_rob_runtime: build_remove_grhsim_ir_rob_runtime
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/remove_grhsim_ir_rob.py runtime-screen \
		--baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --output "$(REMOVE_GRHSIM_IR_ROB)" \
		--old-runtime "$(REMOVE_GRHSIM_IR_ROB_OLD_RUNTIME)" --cycles "$(REMOVE_GRHSIM_IR_ROB_PROFILE_CYCLES)"

.PHONY: debug_remove_grhsim_ir_rob
REMOVE_GRHSIM_IR_ROB_PROBE_OPT ?= 3
.PHONY: probe_remove_grhsim_ir_constructor
probe_remove_grhsim_ir_constructor:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/probe_remove_grhsim_ir_storage.py \
		--header "$(REMOVE_GRHSIM_IR_ROB)/model/grhsim_Rob.hpp" --output "$(CURDIR)/ptmp/remove-grhsim-ir/constructor-probe" --synthetic
	$(MAKE) -k -j 2 -C "$(CURDIR)/ptmp/remove-grhsim-ir/constructor-probe" CXX=clang++ OPT=$(REMOVE_GRHSIM_IR_ROB_PROBE_OPT)
.PHONY: probe_remove_grhsim_ir_storage
probe_remove_grhsim_ir_storage:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/probe_remove_grhsim_ir_storage.py \
		--header "$(REMOVE_GRHSIM_IR_ROB)/model/grhsim_Rob.hpp" --output "$(REMOVE_GRHSIM_IR_ROB)/storage-probe"
	clang++ -std=c++20 -O$(REMOVE_GRHSIM_IR_ROB_PROBE_OPT) "$(REMOVE_GRHSIM_IR_ROB)/storage-probe/probe.cpp" \
		-o "$(REMOVE_GRHSIM_IR_ROB)/storage-probe/probe"
	"$(REMOVE_GRHSIM_IR_ROB)/storage-probe/probe"
.PHONY: probe_remove_grhsim_ir_rob_init
probe_remove_grhsim_ir_rob_init:
	printf '%s\n' '#include "grhsim_Rob.hpp"' '#include <memory>' \
		'extern "C" void xs_assert_v2(const char*, std::int64_t) {}' \
		'int main() { auto model=std::make_unique<GrhSIM_Rob>(); std::cerr << "bytes=" << sizeof(*model) << " constructed\n"; model->init(); std::cerr << "init passed\n"; }' \
		> "$(REMOVE_GRHSIM_IR_ROB)/init_probe.cpp"
	clang++ -std=c++20 -O$(REMOVE_GRHSIM_IR_ROB_PROBE_OPT) -fno-strict-aliasing -I"$(REMOVE_GRHSIM_IR_ROB)/model" \
		"$(REMOVE_GRHSIM_IR_ROB)/init_probe.cpp" "$(REMOVE_GRHSIM_IR_ROB)/model/libgrhsim_Rob.a" \
		-o "$(REMOVE_GRHSIM_IR_ROB)/init_probe_o$(REMOVE_GRHSIM_IR_ROB_PROBE_OPT)"
	"$(REMOVE_GRHSIM_IR_ROB)/init_probe_o$(REMOVE_GRHSIM_IR_ROB_PROBE_OPT)"

debug_remove_grhsim_ir_rob:
	gdb -q -batch $(if $(REMOVE_GRHSIM_IR_ROB_GDB_SCRIPT),-x "$(REMOVE_GRHSIM_IR_ROB_GDB_SCRIPT)",-ex run -ex 'bt 20' -ex 'info registers rdi rax rbx rsp rip' -ex 'x/12i $$pc-24') --args "$(REMOVE_GRHSIM_IR_ROB)/dump_outputs" \
		"$(REMOVE_GRHSIM_IR_BASELINE)/frozen/ptmp/xs-components-rob/trace/rob_trace.bin" \
		"$(REMOVE_GRHSIM_IR_ROB)/debug_outputs.bin"

.PHONY: test_grhsim_flow
GRHSIM_FLOW_TEST_WORK ?= $(CURDIR)/ptmp/remove-grhsim-ir/r6-flow-tests
test_grhsim_flow: $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)
	PYTHONDONTWRITEBYTECODE=1 GRHSIM_FLOW_TEST_WORK="$(GRHSIM_FLOW_TEST_WORK)" $(PYTHON) -m unittest discover -s scripts -p test_grhsim_flow.py
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(MAKE) -C "$(GRHSIM_FLOW_TEST_WORK)" -j 4 run

# Check even explicitly empty/zero settings: retired controls must never be
# mistaken for accepted options. The exact historical names live in the
# shared Python entry-point guard; this Makefile only rejects stale command-line
# variables by namespace, so the production route contains no legacy aliases.
_GRHSIM_REEMIT_ALLOWED := \
	GRHSIM_REEMIT_MODEL GRHSIM_REEMIT_FLOW GRHSIM_REEMIT_MAX_FUNCTION_LINES \
	GRHSIM_REEMIT_MAX_TU_BYTES GRHSIM_REEMIT_MAX_OUTPUT_FILE_BYTES GRHSIM_REEMIT_MEM_WRITE_ACTIVATE \
	GRHSIM_REEMIT_EXECUTION_COUNTERS GRHSIM_REEMIT_OVERWRITE \
	GRHSIM_REEMIT_MEM_ENABLE_BITMAP GRHSIM_REEMIT_PACK_BIT_REGISTERS \
	GRHSIM_REEMIT_MASKED_OR GRHSIM_REEMIT_MASKED_OR_MIN_TERMS \
	GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE GRHSIM_REEMIT_SEGMENT_PENALTY \
	GRHSIM_REEMIT_SINK_GUARD_MIN_SIZE GRHSIM_REEMIT_SEMANTIC_NODES \
	GRHSIM_REEMIT_MAX_NODE_WORK GRHSIM_REEMIT_MASKED_OR_MIN_TERMS
.PHONY: check_remove_grhsim_ir_options test_remove_grhsim_ir_tooling
REMOVE_GRHSIM_IR_AUDIT_REPORT ?= $(CURDIR)/ptmp/remove-grhsim-ir/production-audit.json
.PHONY: check_remove_grhsim_ir
check_remove_grhsim_ir: check_remove_grhsim_ir_options
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/check_remove_grhsim_ir.py --build "$(WOLVRIX_BUILD_DIR)" \
		--report "$(REMOVE_GRHSIM_IR_AUDIT_REPORT)" $(if $(strip $(REMOVE_GRHSIM_IR_AUDIT_MODEL)),--model-dir "$(REMOVE_GRHSIM_IR_AUDIT_MODEL)",)
check_remove_grhsim_ir_options:
	$(foreach option,$(.VARIABLES),$(if $(filter XS_WOLF_%,$(option)),$(error Retired GrhSIM option $(option); use the XS_GRHSIM_* interface),))
	$(foreach option,$(.VARIABLES),$(if $(findstring GRHSIM_IR,$(option)),$(if $(filter XS_%,$(option)),$(error Retired GrhSIM option $(option); see pdocs/grhsim.md),)))
	$(foreach option,$(filter GRHSIM_REEMIT_%,$(.VARIABLES)),$(if $(filter $(option),$(_GRHSIM_REEMIT_ALLOWED)),,$(error Retired GrhSIM option $(option); see pdocs/grhsim.md)))
	@:
test_remove_grhsim_ir_tooling:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_remove_grhsim_ir_tooling.py

.PHONY: test_grhsim_provenance
test_grhsim_provenance:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_provenance.py

.PHONY: test_grhsim_grh_reader
test_grhsim_grh_reader:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_grh_reader.py

.PHONY: test_grhsim_execution_counts inspect_remove_grhsim_ir_execution
test_grhsim_execution_counts: generate_grhsim_cpu_st_cpp
	TMPDIR=$(CURDIR)/ptmp/remove-grhsim-ir/build-tmp $(MAKE) -C $(WOLVRIX_BUILD_DIR)/artifacts/grhsim-cpu-st-cpp -j 2 execution-counts-b16 execution-counts-b1024
	PYTHONDONTWRITEBYTECODE=1 WOLVRIX_TEST_BUILD_DIR="$(WOLVRIX_BUILD_DIR)" $(PYTHON) -m unittest discover -s scripts -p test_grhsim_execution_counts.py

REMOVE_GRHSIM_IR_EXECUTION_REPORT ?= $(CURDIR)/ptmp/remove-grhsim-ir/native-execution.json
inspect_remove_grhsim_ir_execution:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_execution_counts.py \
		--model-dir "$(REMOVE_GRHSIM_IR_EXECUTION_MODEL)" --run1 "$(REMOVE_GRHSIM_IR_EXECUTION_RUN1)" \
		--run2 "$(REMOVE_GRHSIM_IR_EXECUTION_RUN2)" --report "$(REMOVE_GRHSIM_IR_EXECUTION_REPORT)" \
		$(if $(strip $(REMOVE_GRHSIM_IR_GRAPH)),--graph "$(REMOVE_GRHSIM_IR_GRAPH)",)

.PHONY: inspect_remove_grhsim_ir_graph
REMOVE_GRHSIM_IR_GRAPH_REPORT ?= $(CURDIR)/ptmp/remove-grhsim-ir/graph-census.json
inspect_remove_grhsim_ir_graph:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_grh_reader.py --model "$(REMOVE_GRHSIM_IR_GRAPH)" \
		--report "$(REMOVE_GRHSIM_IR_GRAPH_REPORT)" $(if $(strip $(REMOVE_GRHSIM_IR_GRAPH_TOP)),--top "$(REMOVE_GRHSIM_IR_GRAPH_TOP)",)

.PHONY: inspect_remove_grhsim_ir_families
REMOVE_GRHSIM_IR_FAMILY_REPORT ?= $(CURDIR)/ptmp/remove-grhsim-ir/native-families
inspect_remove_grhsim_ir_families:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_declared_pack_census.py \
		--post-conversion-json "$(REMOVE_GRHSIM_IR_GRAPH)" --out-dir "$(REMOVE_GRHSIM_IR_FAMILY_REPORT)" \
		$(if $(strip $(REMOVE_GRHSIM_IR_FAMILY_FINAL)),--final-json "$(REMOVE_GRHSIM_IR_FAMILY_FINAL)",) \
		$(if $(strip $(REMOVE_GRHSIM_IR_EXECUTION_MODEL)),--native-model-dir "$(REMOVE_GRHSIM_IR_EXECUTION_MODEL)" --run1 "$(REMOVE_GRHSIM_IR_EXECUTION_RUN1)" --run2 "$(REMOVE_GRHSIM_IR_EXECUTION_RUN2)",) \
		$(if $(strip $(REMOVE_GRHSIM_IR_PACK_REPORT)),--pack-members "$(REMOVE_GRHSIM_IR_PACK_REPORT)",)

.PHONY: inspect_remove_grhsim_ir_pairs
REMOVE_GRHSIM_IR_PAIR_REPORT ?= $(CURDIR)/ptmp/remove-grhsim-ir/native-pairs
inspect_remove_grhsim_ir_pairs:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_paired_cone_diff.py $(if $(strip $(REMOVE_GRHSIM_IR_EXECUTION_MODEL)),--native,--static-only) \
		--grhsim-final "$(REMOVE_GRHSIM_IR_GRAPH)" --gsim-json "$(REMOVE_GRHSIM_IR_GSIM)" \
		--gsim-sha256 "$(REMOVE_GRHSIM_IR_GSIM_SHA256)" --out-dir "$(REMOVE_GRHSIM_IR_PAIR_REPORT)" \
		$(if $(strip $(REMOVE_GRHSIM_IR_EXECUTION_MODEL)),--model-dir "$(REMOVE_GRHSIM_IR_EXECUTION_MODEL)" --run1 "$(REMOVE_GRHSIM_IR_EXECUTION_RUN1)" --run2 "$(REMOVE_GRHSIM_IR_EXECUTION_RUN2)",)

test_ingest_expression_width:
	mkdir -p $(CURDIR)/ptmp/ingest_width_tmp $(CURDIR)/ptmp/ingest_width_ccache
	TMPDIR=$(CURDIR)/ptmp/ingest_width_tmp CCACHE_DIR=$(CURDIR)/ptmp/ingest_width_ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/ingest_width_tmp CCACHE_DIR=$(CURDIR)/ptmp/ingest_width_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target ingest-expression-width -j 2
	TMPDIR=$(CURDIR)/ptmp/ingest_width_tmp CCACHE_DIR=$(CURDIR)/ptmp/ingest_width_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^ingest-expression-width$$' --output-on-failure

.PHONY: test_ingest_struct_array_write
test_ingest_struct_array_write:
	mkdir -p $(CURDIR)/ptmp/ingest_struct_tmp $(CURDIR)/ptmp/ingest_struct_ccache
	TMPDIR=$(CURDIR)/ptmp/ingest_struct_tmp CCACHE_DIR=$(CURDIR)/ptmp/ingest_struct_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target ingest-struct-array-fieldwise -j 2
	TMPDIR=$(CURDIR)/ptmp/ingest_struct_tmp CCACHE_DIR=$(CURDIR)/ptmp/ingest_struct_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^ingest-struct-array-fieldwise$$' --output-on-failure

.PHONY: test_grh_register_write
test_grh_register_write:
	mkdir -p $(CURDIR)/ptmp/register_write_tmp $(CURDIR)/ptmp/register_write_ccache
	TMPDIR=$(CURDIR)/ptmp/register_write_tmp CCACHE_DIR=$(CURDIR)/ptmp/register_write_ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/register_write_tmp CCACHE_DIR=$(CURDIR)/ptmp/register_write_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target transform-mux-tree-fold -j 2
	TMPDIR=$(CURDIR)/ptmp/register_write_tmp CCACHE_DIR=$(CURDIR)/ptmp/register_write_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^transform-mux-tree-fold$$' --output-on-failure

.PHONY: probe_rob_register_write
probe_rob_register_write:
	mkdir -p $(CURDIR)/ptmp/register_write_tmp $(CURDIR)/ptmp/register_write_ccache
	@if [ "$(SKIP_PY_INSTALL)" != "1" ]; then \
		TMPDIR=$(CURDIR)/ptmp/register_write_tmp PIP_CACHE_DIR=$(CURDIR)/ptmp/register_write_tmp/pip-cache \
		CCACHE_DIR=$(CURDIR)/ptmp/register_write_ccache CMAKE_BUILD_PARALLEL_LEVEL=2 $(MAKE) --no-print-directory py_install; \
	fi
	TMPDIR=$(CURDIR)/ptmp/register_write_tmp PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/probe_rob_register_write.py $(ROB_REGISTER_WRITE_ARGS)

.PHONY: test_array_create
test_array_create:
	mkdir -p $(CURDIR)/ptmp/array-create-tests/tmp $(CURDIR)/ptmp/array-create-tests/ccache
	TMPDIR=$(CURDIR)/ptmp/array-create-tests/tmp CCACHE_DIR=$(CURDIR)/ptmp/array-create-tests/ccache $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/array-create-tests/tmp CCACHE_DIR=$(CURDIR)/ptmp/array-create-tests/ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target array-create-tests transform-verify -j 2
	TMPDIR=$(CURDIR)/ptmp/array-create-tests/tmp CCACHE_DIR=$(CURDIR)/ptmp/array-create-tests/ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(array-create-tests|transform-verify)$$' --output-on-failure

.PHONY: test_grhsim_masked_or
test_grhsim_masked_or: test_grhsim_transforms test_grhsim_cpu_st_cpp

.PHONY: bench_grhsim_masked_or
GRHSIM_MASKED_OR_BENCH_FLAGS ?= -std=c++20 -O3 -DNDEBUG
GRHSIM_MASKED_OR_BENCH_SEED ?= 20261016
bench_grhsim_masked_or: ptmp/masked-or-bench/bench
	@set -o pipefail; ./$< $(GRHSIM_MASKED_OR_BENCH_SEED) | tee ptmp/masked-or-bench/results.tsv

ptmp/masked-or-bench/bench: scripts/grhsim_masked_or_bench.cpp Makefile
	@mkdir -p ptmp/masked-or-bench ptmp/cpu_emit_test_tmp
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp $(CXX) $(GRHSIM_MASKED_OR_BENCH_FLAGS) $< -o $@

.PHONY: test_grhsim_simplify
test_grhsim_simplify: test_grhsim_transforms

.PHONY: test_grhsim_whole_opt
test_grhsim_whole_opt: test_grhsim_transforms

.PHONY: test_grhsim_select_state_stores
test_grhsim_select_state_stores: test_grhsim_sink_schedule

.PHONY: test_grhsim_split_phases
test_grhsim_split_phases: test_grhsim_virtual_partitions

.PHONY: test_transform_simplify
test_transform_simplify:
	mkdir -p $(CURDIR)/ptmp/ctest_tmp $(CURDIR)/ptmp/ctest_ccache
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target transform-simplify -j 2
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^transform-simplify$$' --output-on-failure

.PHONY: test_transform_shape_mapping
test_transform_shape_mapping:
	mkdir -p $(CURDIR)/ptmp/ctest_tmp $(CURDIR)/ptmp/ctest_ccache
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target transform-hier-flatten transform-instance-inline transform-redundant-elim -j 2
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^transform-(hier-flatten|instance-inline|redundant-elim)$$' --output-on-failure

.PHONY: test_transform_comb_loop_elim
test_transform_comb_loop_elim:
	mkdir -p $(CURDIR)/ptmp/ctest_tmp $(CURDIR)/ptmp/ctest_ccache
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target transform-comb-loop-elim -j 2
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^transform-comb-loop-elim$$' --output-on-failure

.PHONY: test_transform_memory_read_retime
test_transform_memory_read_retime:
	mkdir -p $(CURDIR)/ptmp/ctest_tmp $(CURDIR)/ptmp/ctest_ccache
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target transform-memory-read-retime -j 2
	TMPDIR=$(CURDIR)/ptmp/ctest_tmp CCACHE_DIR=$(CURDIR)/ptmp/ctest_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^transform-memory-read-retime$$' --output-on-failure

.PHONY: test_grhsim_event_lowering
test_grhsim_event_lowering: test_grh_to_grhsim test_grhsim_virtual_partitions

.PHONY: test_grhsim_cpu_phases
test_grhsim_cpu_phases: test_grhsim_sink_schedule test_grhsim_cpu_st_cpp

.PHONY: test_grhsim_cpu_stores
test_grhsim_cpu_stores: test_grhsim_sink_schedule test_grhsim_cpu_st_cpp

.PHONY: test_grhsim_cpu_phase_emit
.PHONY: test_array_create_cpu
test_array_create_cpu: test_grhsim_cpu_st_cpp

test_grhsim_cpu_phase_emit: test_grhsim_cpu_st_cpp

.PHONY: analyze_grhsim_cpu_profile
analyze_grhsim_cpu_profile:
	$(PYTHON) $(CURDIR)/scripts/grhsim_cpu_profile.py --profile "$(GRHSIM_CPU_PROFILE)" --binary "$(GRHSIM_CPU_PROFILE_BINARY)" --model "$(GRHSIM_CPU_PROFILE_MODEL)" --expected-samples "$(GRHSIM_CPU_PROFILE_SAMPLES)" $(if $(GRHSIM_CPU_PROFILE_TOP),--top "$(GRHSIM_CPU_PROFILE_TOP)",) $(if $(GRHSIM_CPU_PROFILE_JSON),--output-json "$(GRHSIM_CPU_PROFILE_JSON)",)

.PHONY: test_grhsim_cpu_profile
test_grhsim_cpu_profile:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_cpu_profile.py

.PHONY: analyze_grhsim_pc_costs
analyze_grhsim_pc_costs:
	@test -n "$(GRHSIM_PC_SUMMARY)" -a -n "$(GRHSIM_PC_BINARY)" -a -n "$(GRHSIM_PC_OUTPUT)" || { echo "Set GRHSIM_PC_SUMMARY, GRHSIM_PC_BINARY and GRHSIM_PC_OUTPUT"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_pc_costs.py \
		--summary "$(GRHSIM_PC_SUMMARY)" --binary "$(GRHSIM_PC_BINARY)" \
		--output "$(GRHSIM_PC_OUTPUT)" $(if $(GRHSIM_PC_PROFILE),--profile "$(GRHSIM_PC_PROFILE)",) \
		$(if $(GRHSIM_PC_TOP),--top "$(GRHSIM_PC_TOP)",) \
		$(if $(GRHSIM_PC_FOCUS_SYMBOL),--focus-symbol '$(GRHSIM_PC_FOCUS_SYMBOL)',) \
		$(if $(GRHSIM_PC_CONSTANT_REPORT),--constant-report "$(GRHSIM_PC_CONSTANT_REPORT)",) \
		$(if $(filter 1,$(GRHSIM_PC_SKIP_DISASSEMBLY)),--skip-disassembly,) \
		$(if $(filter 1,$(GRHSIM_PC_CONSTANT_CONTROL_SCAN)),--constant-control-scan,)

.PHONY: test_grhsim_module_attribution
test_grhsim_module_attribution:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_module_attribution.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_module_attribution.py --selftest

.PHONY: profile_grhsim_ir
profile_grhsim_ir:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/profile_grhsim_ir.py --flow "$(GRHSIM_IR_PROFILE_FLOW)" --output "$(GRHSIM_IR_PROFILE_OUTPUT)" --baseline-seconds "$(GRHSIM_IR_PROFILE_BASELINE_SECONDS)" --expected-endpoint "$(GRHSIM_BENCH_EXPECTED_ENDPOINT)"

.PHONY: reemit_grhsim
GRHSIM_REEMIT_MAX_FUNCTION_LINES ?= 1024
GRHSIM_REEMIT_MAX_TU_BYTES ?= 1048576
GRHSIM_REEMIT_MAX_OUTPUT_FILE_BYTES ?= 4294967296
GRHSIM_REEMIT_MASKED_OR_MIN_TERMS ?= 16
GRHSIM_REEMIT_MEM_WRITE_ACTIVATE ?= on-write
reemit_grhsim: check_remove_grhsim_ir_options $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/reemit_grhsim.py \
		--model "$(GRHSIM_REEMIT_MODEL)" --flow "$(GRHSIM_REEMIT_FLOW)" \
		--max-function-lines "$(GRHSIM_REEMIT_MAX_FUNCTION_LINES)" --max-tu-bytes "$(GRHSIM_REEMIT_MAX_TU_BYTES)" \
		--max-output-file-bytes "$(GRHSIM_REEMIT_MAX_OUTPUT_FILE_BYTES)" \
		--mem-write-activate "$(GRHSIM_REEMIT_MEM_WRITE_ACTIVATE)" \
		$(if $(filter 1,$(GRHSIM_REEMIT_EXECUTION_COUNTERS)),--execution-counters,) \
		$(if $(filter 1,$(GRHSIM_REEMIT_OVERWRITE)),--overwrite,) \
		$(if $(strip $(GRHSIM_REEMIT_MEM_ENABLE_BITMAP)),--mem-enable-bitmap "$(GRHSIM_REEMIT_MEM_ENABLE_BITMAP)",) \
		$(if $(filter 1,$(GRHSIM_REEMIT_PACK_BIT_REGISTERS)),--pack-bit-registers,) \
		$(if $(filter 0,$(GRHSIM_REEMIT_PACK_BIT_REGISTERS)),--no-pack-bit-registers,) \
		$(if $(filter 1,$(GRHSIM_REEMIT_MASKED_OR)),--recover-masked-or --masked-or-min-terms $(GRHSIM_REEMIT_MASKED_OR_MIN_TERMS),) \
		$(if $(filter 0,$(GRHSIM_REEMIT_MASKED_OR)),--no-recover-masked-or,) \
		$(if $(strip $(GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE)),--max-op-in-compute-supernode $(GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE),) \
		$(if $(strip $(GRHSIM_REEMIT_SEGMENT_PENALTY)),--segment-penalty $(GRHSIM_REEMIT_SEGMENT_PENALTY),) \
		$(if $(strip $(GRHSIM_REEMIT_SINK_GUARD_MIN_SIZE)),--sink-enable-guard-min-size $(GRHSIM_REEMIT_SINK_GUARD_MIN_SIZE),) \
		$(if $(filter 1,$(GRHSIM_REEMIT_SEMANTIC_NODES)),--semantic-nodes,) \
		$(if $(strip $(GRHSIM_REEMIT_MAX_NODE_WORK)),--max-node-work $(GRHSIM_REEMIT_MAX_NODE_WORK),)

.PHONY: grhsim_tu_trace
# Diagnostic: compile ONE generated model TU with -ftime-trace to locate the
# -O3 hot pass. GRHSIM_TRACE_TU = path to grhsim_SimTop_tuN.cpp; artifacts
# (object + trace json) land in ptmp/grhsim-tu-trace/.
grhsim_tu_trace:
	@test -n "$(GRHSIM_TRACE_TU)" && test -f "$(GRHSIM_TRACE_TU)" || { echo "[FAIL] set GRHSIM_TRACE_TU=<model dir>/grhsim_SimTop_tuN.cpp"; exit 1; }
	@mkdir -p ptmp/grhsim-tu-trace
	cd "$(dir $(GRHSIM_TRACE_TU))" && $${CXX:-clang++} -std=c++20 -O3 $(GRHSIM_TRACE_FLAGS) -ftime-trace -c "$(notdir $(GRHSIM_TRACE_TU))" -o "$(CURDIR)/ptmp/grhsim-tu-trace/$(notdir $(GRHSIM_TRACE_TU)).o"
	@mv "$(CURDIR)/ptmp/grhsim-tu-trace/$(notdir $(GRHSIM_TRACE_TU)).json" "$(CURDIR)/ptmp/grhsim-tu-trace/$(notdir $(GRHSIM_TRACE_TU) .cpp).json" 2>/dev/null || true
	@ls -la ptmp/grhsim-tu-trace/

GRHSIM_BENCH_CPU ?= 2
GRHSIM_BENCH_PAIRS ?= 3
GRHSIM_BENCH_MAKE_TARGET ?= run_xs_grhsim_emu
GRHSIM_BENCH_BUILD_VAR ?= XS_GRHSIM_BUILD
GRHSIM_BENCH_EMU_RELPATH ?= emu/emu
GRHSIM_BENCH_EXPECTED_ENDPOINT ?= 238535,99996,100001,0x80000cde
GRHSIM_BENCH_PERF_STAT ?= 0
.PHONY: benchmark_grhsim_ir
benchmark_grhsim_ir:
	$(PYTHON) scripts/benchmark_grhsim_ir.py --old "$(GRHSIM_BENCH_OLD)" --new "$(GRHSIM_BENCH_NEW)" \
		--output "$(GRHSIM_BENCH_OUTPUT)" --cpu "$(GRHSIM_BENCH_CPU)" \
		--pairs "$(GRHSIM_BENCH_PAIRS)" --baseline-seconds "$(GRHSIM_BENCH_BASELINE_SECONDS)" \
		--make-target "$(GRHSIM_BENCH_MAKE_TARGET)" --build-var "$(GRHSIM_BENCH_BUILD_VAR)" \
		--emu-relpath "$(GRHSIM_BENCH_EMU_RELPATH)" --expected-endpoint "$(GRHSIM_BENCH_EXPECTED_ENDPOINT)" \
		$(if $(filter 1,$(GRHSIM_BENCH_PERF_STAT)),--perf-stat,)

.PHONY: test_benchmark_grhsim_ir
test_benchmark_grhsim_ir:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_benchmark_grhsim_ir.py

REMOVE_GRHSIM_BENCH_OLD ?= $(CURDIR)/ptmp/remove-grhsim-ir/xs-frozen-runtime
REMOVE_GRHSIM_BENCH_SOURCE_FLOW ?= $(CURDIR)/ptmp/remove-grhsim-ir/xs-sink-run
REMOVE_GRHSIM_BENCH_NEW ?= $(CURDIR)/ptmp/remove-grhsim-ir/xs-sink-run-runtime
REMOVE_GRHSIM_BENCH_OUTPUT ?= $(CURDIR)/ptmp/remove-grhsim-ir/r6-xs-runtime-ab
# Timeout sizing only, not an observed old/new performance baseline.
REMOVE_GRHSIM_BENCH_TIMEOUT_REFERENCE_SECONDS ?= 3600
.PHONY: prepare_remove_grhsim_ir_runtime_baseline prepare_remove_grhsim_ir_runtime_candidate benchmark_remove_grhsim_ir_runtime
prepare_remove_grhsim_ir_runtime_baseline:
	mkdir -p "$(REMOVE_GRHSIM_BENCH_OLD)/emu"
	@if [ -e "$(REMOVE_GRHSIM_BENCH_OLD)/emu/emu" ]; then \
		cmp -s "$(REMOVE_GRHSIM_IR_BASELINE)/frozen/ptmp/xs/grhsim-ir/emu/grhsim-compile/emu" "$(REMOVE_GRHSIM_BENCH_OLD)/emu/emu" || { echo "[FAIL] isolated baseline differs from frozen executable"; exit 1; }; \
	else \
		cp --reflink=auto "$(REMOVE_GRHSIM_IR_BASELINE)/frozen/ptmp/xs/grhsim-ir/emu/grhsim-compile/emu" "$(REMOVE_GRHSIM_BENCH_OLD)/emu/emu"; \
	fi
prepare_remove_grhsim_ir_runtime_candidate:
	mkdir -p "$(REMOVE_GRHSIM_BENCH_NEW)/emu"
	@if [ -e "$(REMOVE_GRHSIM_BENCH_NEW)/emu/emu" ]; then \
		cmp -s "$(REMOVE_GRHSIM_BENCH_SOURCE_FLOW)/emu/emu" "$(REMOVE_GRHSIM_BENCH_NEW)/emu/emu" || { echo "[FAIL] isolated candidate differs from source executable"; exit 1; }; \
	else \
		cp --reflink=auto "$(REMOVE_GRHSIM_BENCH_SOURCE_FLOW)/emu/emu" "$(REMOVE_GRHSIM_BENCH_NEW)/emu/emu"; \
	fi
	@test -e "$(REMOVE_GRHSIM_BENCH_NEW)/model" || ln -s "$(abspath $(REMOVE_GRHSIM_BENCH_SOURCE_FLOW))/model" "$(REMOVE_GRHSIM_BENCH_NEW)/model"
	@test -e "$(REMOVE_GRHSIM_BENCH_NEW)/generation-identity.json" || ln -s "$(abspath $(REMOVE_GRHSIM_BENCH_SOURCE_FLOW))/generation-identity.json" "$(REMOVE_GRHSIM_BENCH_NEW)/generation-identity.json"
benchmark_remove_grhsim_ir_runtime: prepare_remove_grhsim_ir_runtime_baseline prepare_remove_grhsim_ir_runtime_candidate
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/benchmark_grhsim_ir.py \
		--old "$(REMOVE_GRHSIM_BENCH_OLD)" --new "$(REMOVE_GRHSIM_BENCH_NEW)" \
		--output "$(REMOVE_GRHSIM_BENCH_OUTPUT)" --cpu "$(GRHSIM_BENCH_CPU)" --pairs 3 \
		--baseline-seconds "$(REMOVE_GRHSIM_BENCH_TIMEOUT_REFERENCE_SECONDS)" \
		--migration-baseline "$(REMOVE_GRHSIM_IR_BASELINE)" --no-evict-page-cache \
		--expected-endpoint "$(GRHSIM_BENCH_EXPECTED_ENDPOINT)"

.PHONY: profile_remove_grhsim_ir_xs_prefix analyze_remove_grhsim_ir_xs_prefix
REMOVE_GRHSIM_IR_XS_PROFILE_CYCLES ?= 10000
REMOVE_GRHSIM_IR_XS_PROFILE_CPU ?= 2
profile_remove_grhsim_ir_xs_prefix: prepare_remove_grhsim_ir_runtime_candidate
	$(MAKE) --no-print-directory run_xs_grhsim_emu XS_GRHSIM_BUILD="$(REMOVE_GRHSIM_BENCH_NEW)" \
		XS_LOG_DIR="$(REMOVE_GRHSIM_BENCH_NEW)/logs" RUN_ID=prefix-profile XS_SIM_MAX_CYCLE="$(REMOVE_GRHSIM_IR_XS_PROFILE_CYCLES)" \
		XS_WAVEFORM=0 XS_WAVEFORM_PATH= XS_COMMIT_TRACE=0 XS_RAM_TRACE=0 XS_PROGRESS_EVERY_CYCLES=0 \
		XS_EMU_PREFIX='perf record -F 199 -g -o "$(REMOVE_GRHSIM_BENCH_NEW)/prefix.perf.data" -- taskset -c "$(REMOVE_GRHSIM_IR_XS_PROFILE_CPU)"'
	$(MAKE) --no-print-directory analyze_remove_grhsim_ir_xs_prefix
analyze_remove_grhsim_ir_xs_prefix:
	perf report --stdio --no-children -g none --show-nr-samples --show-total-period --sort symbol --percent-limit 0 \
		-i "$(REMOVE_GRHSIM_BENCH_NEW)/prefix.perf.data" > "$(REMOVE_GRHSIM_BENCH_NEW)/prefix.perf-all.txt"

# Temporary phase attribution against an existing model archive; no graph re-emission.
REMOVE_GRHSIM_IR_PHASE_PROBE ?= $(CURDIR)/ptmp/remove-grhsim-ir/runtime-diagnosis/phases
.PHONY: prepare_remove_grhsim_ir_phase_probe
prepare_remove_grhsim_ir_phase_probe:
	$(PYTHON) ptmp/remove-grhsim-ir/runtime-diagnosis/prepare.py \
		--source "$(REMOVE_GRHSIM_BENCH_SOURCE_FLOW)/model" --output "$(REMOVE_GRHSIM_IR_PHASE_PROBE)"

.PHONY: test_xs_workflow
test_xs_workflow:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_xs_workflow.py

# ---------------------------------------------------------------------------
# Sim-model refactor M0: golden baseline capture and diff harness.
# capture_sim_refactor_baseline records per-eval port traces for every HDLBits
# DUT with the current (pre-refactor) IR CPU backend, runs each testbench
# twice and requires byte-identical traces, then builds the coverage manifest.
# check_sim_refactor_baseline re-runs the traced testbenches with the current
# build and diffs each run against the stored golden (first divergence wins).
# ---------------------------------------------------------------------------
SIM_REFACTOR_BASELINE_DIR ?= $(CURDIR)/ptmp/sim-refactor-baseline
SIM_REFACTOR_CAPTURE_DUTS ?= $(HDLBITS_GRHSIM_DUTS)
SIM_REFACTOR_CHECK_DUTS ?= $(patsubst dut_%.trace,%,$(notdir $(wildcard $(SIM_REFACTOR_BASELINE_DIR)/hdlbits/dut_*.trace)))
.PHONY: capture_sim_refactor_baseline
capture_sim_refactor_baseline: py_install
	@mkdir -p $(SIM_REFACTOR_BASELINE_DIR)/hdlbits $(SIM_REFACTOR_BASELINE_DIR)/work/hdlbits
	@fail=""; \
	for dut in $(SIM_REFACTOR_CAPTURE_DUTS); do \
		echo "==== Golden capture DUT=$$dut ===="; \
		$(MAKE) --no-print-directory -C $(HDLBITS_ROOT) run_grhtb_trace \
			DUT=$$dut PYTHON=$(PYTHON) \
			BUILD_DIR=$(SIM_REFACTOR_BASELINE_DIR)/work/hdlbits \
			GRHSIM_SCRIPT=$(HDLBITS_GRHSIM_SCRIPT) \
			GOLDEN_DIR=$(SIM_REFACTOR_BASELINE_DIR)/hdlbits || fail="$$fail $$dut"; \
	done; \
	echo "$$fail" > $(SIM_REFACTOR_BASELINE_DIR)/work/failed_duts.txt; \
	if [ -n "$$fail" ]; then echo "[CAPTURE] FAILED DUTs (pre-existing, excluded from golden):$$fail"; fi
	$(PYTHON) scripts/build_sim_refactor_manifest.py \
		--golden-dir $(SIM_REFACTOR_BASELINE_DIR)/hdlbits \
		--work-dir $(SIM_REFACTOR_BASELINE_DIR)/work/hdlbits \
		--failed-list $(SIM_REFACTOR_BASELINE_DIR)/work/failed_duts.txt \
		--output $(SIM_REFACTOR_BASELINE_DIR)/hdlbits/MANIFEST.json
	@fail="$$(cat $(SIM_REFACTOR_BASELINE_DIR)/work/failed_duts.txt)"; \
	if [ -n "$$fail" ]; then echo "[CAPTURE] baseline incomplete, failed DUTs:$$fail"; exit 1; fi

.PHONY: check_sim_refactor_baseline
check_sim_refactor_baseline: py_install
	@test -n "$(SIM_REFACTOR_CHECK_DUTS)" || { echo "[FAIL] no golden traces under $(SIM_REFACTOR_BASELINE_DIR)/hdlbits"; exit 1; }
	@for dut in $(SIM_REFACTOR_CHECK_DUTS); do \
		$(MAKE) --no-print-directory -C $(HDLBITS_ROOT) run_grhtb_trace_check \
			DUT=$$dut PYTHON=$(PYTHON) \
			BUILD_DIR=$(SIM_REFACTOR_BASELINE_DIR)/work/hdlbits \
			GRHSIM_SCRIPT=$(HDLBITS_GRHSIM_SCRIPT) \
			GOLDEN_DIR=$(SIM_REFACTOR_BASELINE_DIR)/hdlbits || exit $$?; \
	done
	@echo "[BASELINE] all checked DUTs match golden ($(words $(SIM_REFACTOR_CHECK_DUTS)) DUTs)"

.PHONY: test_sim_refactor_trace
test_sim_refactor_trace:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_ir_trace_diff.py

# Native work/cost comparison between the GrhSIM-IR emu and the gsim emu on the
# 100k CoreMark caliber (perf stat 3+3, icache/TLB group, no-difftest net work,
# perf record symbol attribution). All runs are perf-instrumented diagnostics;
# their Host times are recorded but never mixed into performance baselines.
GRHSIM_NATIVE_IR_FLOW ?=
GRHSIM_NATIVE_GSIM_BUILD ?= $(XS_GSIM_PGO_BUILD)
GRHSIM_NATIVE_OUTPUT ?=
GRHSIM_NATIVE_PAIRS ?= 3
GRHSIM_NATIVE_IR_BASELINE_SECONDS ?= 55.864333
GRHSIM_NATIVE_GSIM_BASELINE_SECONDS ?= 27.376
.PHONY: analyze_grhsim_native_work
analyze_grhsim_native_work:
	@test -n "$(GRHSIM_NATIVE_IR_FLOW)" || { echo "[FAIL] set GRHSIM_NATIVE_IR_FLOW=<grhsim-ir flow dir>"; exit 1; }
	@test -n "$(GRHSIM_NATIVE_OUTPUT)" || { echo "[FAIL] set GRHSIM_NATIVE_OUTPUT=<new dir under ptmp>"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_native_work_compare.py \
		--ir-flow "$(GRHSIM_NATIVE_IR_FLOW)" --gsim-build "$(GRHSIM_NATIVE_GSIM_BUILD)" \
		--output "$(GRHSIM_NATIVE_OUTPUT)" --pairs "$(GRHSIM_NATIVE_PAIRS)" \
		--ir-baseline-seconds "$(GRHSIM_NATIVE_IR_BASELINE_SECONDS)" \
		--gsim-baseline-seconds "$(GRHSIM_NATIVE_GSIM_BASELINE_SECONDS)" \
		$(if $(GRHSIM_NATIVE_PASSES),--passes "$(GRHSIM_NATIVE_PASSES)",)

.PHONY: test_grhsim_native_work_compare
test_grhsim_native_work_compare:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_native_work_compare.py

# gsim native runtime-profile calibers + two-sided dynOps factor decomposition
# (NO00008). Requires a gsim-rtprof build (make xs_gsim_emu_rtprof). Runs the
# diagnostic emu twice through run_xs_gsim_emu with EMU_RUNTIME_PROFILE injected
# via XS_EMU_PREFIX; counts are deterministic and must be bit-identical.
GSIM_RTPROF_IR_DYN_LOG ?=
GSIM_RTPROF_OUTPUT ?=
GSIM_RTPROF_RUNS ?= 2
GSIM_RTPROF_CUTOFF ?= 300
.PHONY: analyze_gsim_runtime_profile
analyze_gsim_runtime_profile:
	@test -n "$(GSIM_RTPROF_IR_DYN_LOG)" || { echo "[FAIL] set GSIM_RTPROF_IR_DYN_LOG=<archived grhsim-dyn emu log>"; exit 1; }
	@test -n "$(GSIM_RTPROF_OUTPUT)" || { echo "[FAIL] set GSIM_RTPROF_OUTPUT=<new dir under ptmp>"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/gsim_runtime_profile_compare.py \
		--gsim-build "$(XS_GSIM_RTPROF_BUILD)" \
		--anchor-model "$(XS_GSIM_PGO_BUILD)/gsim-compile/model" \
		--ir-dyn-log "$(GSIM_RTPROF_IR_DYN_LOG)" \
		--output "$(GSIM_RTPROF_OUTPUT)" \
		--runs "$(GSIM_RTPROF_RUNS)" --cutoff "$(GSIM_RTPROF_CUTOFF)"

.PHONY: test_gsim_runtime_profile_compare
test_gsim_runtime_profile_compare:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_gsim_runtime_profile_compare.py

# NO00012 per-value change-rate profile + monitored-set activation economics +
# wide-value cost baseline (diagnostic). Consumes the two diagnostic run logs
# from the dyn+vchg build (ptmp/no00012_vchg_profile_20260925/dyn_flow.sh),
# the mapped checkpoint, and the generated model dir of the diagnostic build.
GRHSIM_VCHG_MODEL ?=
GRHSIM_VCHG_RUN1 ?=
GRHSIM_VCHG_RUN2 ?=
GRHSIM_VCHG_GEN_MODEL ?=
GRHSIM_VCHG_OUTPUT ?=
.PHONY: analyze_grhsim_vchg_profile
analyze_grhsim_vchg_profile:
	@test -n "$(GRHSIM_VCHG_MODEL)" || { echo "[FAIL] set GRHSIM_VCHG_MODEL=<mapped checkpoint json>"; exit 1; }
	@test -n "$(GRHSIM_VCHG_RUN1)" || { echo "[FAIL] set GRHSIM_VCHG_RUN1=<run1 emu log>"; exit 1; }
	@test -n "$(GRHSIM_VCHG_RUN2)" || { echo "[FAIL] set GRHSIM_VCHG_RUN2=<run2 emu log>"; exit 1; }
	@test -n "$(GRHSIM_VCHG_GEN_MODEL)" || { echo "[FAIL] set GRHSIM_VCHG_GEN_MODEL=<generated model dir>"; exit 1; }
	@test -n "$(GRHSIM_VCHG_OUTPUT)" || { echo "[FAIL] set GRHSIM_VCHG_OUTPUT=<new dir under ptmp>"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_vchg_profile.py \
		--model "$(GRHSIM_VCHG_MODEL)" \
		--run1 "$(GRHSIM_VCHG_RUN1)" --run2 "$(GRHSIM_VCHG_RUN2)" \
		--gen-model "$(GRHSIM_VCHG_GEN_MODEL)" \
		--output "$(GRHSIM_VCHG_OUTPUT)"

.PHONY: test_grhsim_vchg_profile
test_grhsim_vchg_profile:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_vchg_profile.py

.PHONY: analyze_grhsim_localization
analyze_grhsim_localization:
	@$(PYTHON) scripts/grhsim_localization_stats.py --flow "$(GRHSIM_LOCALIZATION_FLOW)" \
		--state-suffix '$(GRHSIM_LOCALIZATION_STATE_SUFFIX)' $(if $(filter 1,$(GRHSIM_LOCALIZATION_DEAD_CONES)),--dead-cones-only,)

# Codegen probe: compile one emitted model translation unit into an analysis
# directory. Pass the retained model PCH to match its production header setup.
GRHSIM_PROBE_MODEL ?= $(XS_GRHSIM_BUILD_ABS)/model
GRHSIM_PROBE_MODE ?= asm
GRHSIM_PROBE_CXXFLAGS ?= -std=c++20 -O3 -march=native -fno-strict-aliasing -DWOLVRIX_GRHSIM_PERF=0 -DWOLVRIX_GRHSIM_SN_TIMING=0
GRHSIM_PROBE_PCH ?=
.PHONY: probe_grhsim_ir_codegen
probe_grhsim_ir_codegen:
	@test -n "$(GRHSIM_PROBE_SRC)" || { echo "[FAIL] set GRHSIM_PROBE_SRC=<model cpp>"; exit 1; }
	@test -n "$(GRHSIM_PROBE_OUT)" || { echo "[FAIL] set GRHSIM_PROBE_OUT=<output dir>"; exit 1; }
	@mkdir -p "$(GRHSIM_PROBE_OUT)"
	@out="$(GRHSIM_PROBE_OUT)/$$(basename "$(GRHSIM_PROBE_SRC)" .cpp).$(if $(filter asm,$(GRHSIM_PROBE_MODE)),s,o)"; \
	echo "[PROBE] $(CXX) $(GRHSIM_PROBE_CXXFLAGS) $(if $(GRHSIM_PROBE_PCH),-include-pch $(GRHSIM_PROBE_PCH),) -I$(GRHSIM_PROBE_MODEL) $(GRHSIM_PROBE_SRC) -> $$out"; \
	if [ "$(GRHSIM_PROBE_MODE)" = "asm" ]; then \
		$(CXX) $(GRHSIM_PROBE_CXXFLAGS) $(if $(GRHSIM_PROBE_PCH),-include-pch "$(GRHSIM_PROBE_PCH)",) -I"$(GRHSIM_PROBE_MODEL)" -S "$(GRHSIM_PROBE_SRC)" -o "$$out"; \
	else \
		$(CXX) $(GRHSIM_PROBE_CXXFLAGS) $(if $(GRHSIM_PROBE_PCH),-include-pch "$(GRHSIM_PROBE_PCH)",) -I"$(GRHSIM_PROBE_MODEL)" -c "$(GRHSIM_PROBE_SRC)" -o "$$out"; \
	fi

.PHONY: analyze_grhsim_predicates
analyze_grhsim_predicates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_predicate_stats.py --model "$(GRHSIM_PREDICATE_MODEL)" $(if $(GRHSIM_PREDICATE_REFERENCE),--reference "$(GRHSIM_PREDICATE_REFERENCE)",)

.PHONY: analyze_grhsim_state_reads
analyze_grhsim_state_reads:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_state_read_stats.py --model "$(GRHSIM_STATE_READ_MODEL)" $(if $(GRHSIM_STATE_READ_REFERENCE),--reference "$(GRHSIM_STATE_READ_REFERENCE)",) $(if $(filter 1,$(GRHSIM_STATE_READ_NOTIFY)),--notify,) $(if $(filter 1,$(GRHSIM_STATE_READ_PROJECTED_ONLY)),--projected-only,) $(if $(filter 1,$(GRHSIM_STATE_READ_FEEDBACK)),--feedback,) $(if $(filter 1,$(GRHSIM_STATE_READ_PACK)),--pack-states,) $(if $(filter 1,$(GRHSIM_STATE_READ_SUMMARY)),--summary-only,)

.PHONY: analyze_grhsim_cpu_code
analyze_grhsim_cpu_code:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_cpu_code_stats.py --old "$(GRHSIM_CPU_CODE_OLD)" --new "$(GRHSIM_CPU_CODE_NEW)" $(if $(filter 1,$(GRHSIM_CPU_CODE_PHASE_ONLY)),--phase-only,)

.PHONY: analyze_grhsim_compute_storage
analyze_grhsim_compute_storage:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_compute_storage_stats.py --model "$(GRHSIM_COMPUTE_STORAGE_MODEL)" $(if $(GRHSIM_COMPUTE_STORAGE_REFERENCE),--reference "$(GRHSIM_COMPUTE_STORAGE_REFERENCE)",)

.PHONY: analyze_grhsim_mux_fusion
analyze_grhsim_mux_fusion:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_mux_fusion_stats.py --model "$(GRHSIM_MUX_FUSION_MODEL)" $(if $(GRHSIM_MUX_FUSION_REFERENCE),--reference "$(GRHSIM_MUX_FUSION_REFERENCE)",)

.PHONY: analyze_grhsim_op_mix
analyze_grhsim_op_mix:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_op_mix_stats.py --model "$(GRHSIM_OP_MIX_MODEL)" $(if $(GRHSIM_OP_MIX_TOP),--top "$(GRHSIM_OP_MIX_TOP)",)

.PHONY: analyze_grhsim_dynamic
analyze_grhsim_dynamic:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_dynamic_stats.py --log "$(GRHSIM_DYNAMIC_LOG)" --model "$(GRHSIM_DYNAMIC_MODEL)"

.PHONY: analyze_grhsim_cone_guard
analyze_grhsim_cone_guard:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_cone_guard_census.py --model "$(GRHSIM_CONE_MODEL)" $(if $(GRHSIM_CONE_DYNLOG),--dynlog "$(GRHSIM_CONE_DYNLOG)",) $(if $(GRHSIM_CONE_SAMPLES),--samples "$(GRHSIM_CONE_SAMPLES)",) $(if $(GRHSIM_CONE_OUT),--out "$(GRHSIM_CONE_OUT)",)

.PHONY: analyze_grhsim_migration_census
analyze_grhsim_migration_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_migration_census.py --model "$(GRHSIM_MIGRATION_MODEL)" $(if $(GRHSIM_MIGRATION_RUN),--run "$(GRHSIM_MIGRATION_RUN)",) --output "$(GRHSIM_MIGRATION_OUTPUT)" $(if $(GRHSIM_MIGRATION_CYCLES),--cycles "$(GRHSIM_MIGRATION_CYCLES)",)

.PHONY: test_grhsim_migration_census
test_grhsim_migration_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_migration_census.py

.PHONY: analyze_grhsim_migration
analyze_grhsim_migration:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_migration_gates.py \
		--old-model "$(GRHSIM_MIGRATION_OLD_MODEL)" --new-model "$(GRHSIM_MIGRATION_NEW_MODEL)" \
		$(if $(GRHSIM_MIGRATION_BASELINE_RUN),--baseline-run "$(GRHSIM_MIGRATION_BASELINE_RUN)",) \
		$(if $(GRHSIM_MIGRATION_RUN1),--run1 "$(GRHSIM_MIGRATION_RUN1)",) \
		$(if $(GRHSIM_MIGRATION_RUN2),--run2 "$(GRHSIM_MIGRATION_RUN2)",) \
		$(if $(GRHSIM_MIGRATION_SHRINK_MIN),--shrink-min "$(GRHSIM_MIGRATION_SHRINK_MIN)",) \
		--output "$(GRHSIM_MIGRATION_OUTPUT)"

.PHONY: test_grhsim_migration_gates
test_grhsim_migration_gates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_migration_gates.py

.PHONY: analyze_grhsim_demonitor_census
analyze_grhsim_demonitor_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_demonitor_census.py --model "$(GRHSIM_DEMONITOR_MODEL)" $(if $(GRHSIM_DEMONITOR_RUN),--run "$(GRHSIM_DEMONITOR_RUN)",) --output "$(GRHSIM_DEMONITOR_OUTPUT)" $(if $(GRHSIM_DEMONITOR_CYCLES),--cycles "$(GRHSIM_DEMONITOR_CYCLES)",)

.PHONY: test_grhsim_demonitor_census
test_grhsim_demonitor_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_demonitor_census.py

.PHONY: analyze_grhsim_demonitor
analyze_grhsim_demonitor:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_demonitor_gates.py \
		--old-model "$(GRHSIM_DEMONITOR_OLD_MODEL)" --new-model "$(GRHSIM_DEMONITOR_NEW_MODEL)" \
		$(if $(GRHSIM_DEMONITOR_BASELINE_RUN),--baseline-run "$(GRHSIM_DEMONITOR_BASELINE_RUN)",) \
		$(if $(GRHSIM_DEMONITOR_RUN1),--run1 "$(GRHSIM_DEMONITOR_RUN1)",) \
		$(if $(GRHSIM_DEMONITOR_RUN2),--run2 "$(GRHSIM_DEMONITOR_RUN2)",) \
		$(if $(GRHSIM_DEMONITOR_SHRINK_FRAC),--shrink-frac "$(GRHSIM_DEMONITOR_SHRINK_FRAC)",) \
		--output "$(GRHSIM_DEMONITOR_OUTPUT)"

.PHONY: test_grhsim_demonitor_gates
test_grhsim_demonitor_gates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_demonitor_gates.py

.PHONY: analyze_grhsim_edgecomplete_census
analyze_grhsim_edgecomplete_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_edgecomplete_census.py --model "$(GRHSIM_EDGECOMPLETE_MODEL)" $(if $(GRHSIM_EDGECOMPLETE_RUN),--run "$(GRHSIM_EDGECOMPLETE_RUN)",) --output "$(GRHSIM_EDGECOMPLETE_OUTPUT)" $(if $(GRHSIM_EDGECOMPLETE_PROFILE),--profile-output "$(GRHSIM_EDGECOMPLETE_PROFILE)",) $(if $(GRHSIM_EDGECOMPLETE_CYCLES),--cycles "$(GRHSIM_EDGECOMPLETE_CYCLES)",)

.PHONY: test_grhsim_edgecomplete_census
test_grhsim_edgecomplete_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_edgecomplete_census.py

.PHONY: analyze_grhsim_edgecomplete
analyze_grhsim_edgecomplete:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_edgecomplete_gates.py \
		$(if $(filter 1,$(GRHSIM_CHECKPOINT_ALLOW_SOURCE_RENUMBER)),--allow-grh-source-renumber,) \
		--old-model "$(GRHSIM_EDGECOMPLETE_OLD_MODEL)" --new-model "$(GRHSIM_EDGECOMPLETE_NEW_MODEL)" \
		--baseline-run "$(GRHSIM_EDGECOMPLETE_BASELINE_RUN)" \
		$(if $(GRHSIM_EDGECOMPLETE_RUN1),--run1 "$(GRHSIM_EDGECOMPLETE_RUN1)",) \
		$(if $(GRHSIM_EDGECOMPLETE_RUN2),--run2 "$(GRHSIM_EDGECOMPLETE_RUN2)",) \
		--output "$(GRHSIM_EDGECOMPLETE_OUTPUT)"

.PHONY: test_grhsim_edgecomplete_gates
test_grhsim_edgecomplete_gates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_edgecomplete_gates.py

.PHONY: analyze_grhsim_migrate_ec_census
analyze_grhsim_migrate_ec_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_migrate_ec_census.py --model "$(GRHSIM_MIGRATE_EC_MODEL)" $(if $(GRHSIM_MIGRATE_EC_RUN),--run "$(GRHSIM_MIGRATE_EC_RUN)",) --output "$(GRHSIM_MIGRATE_EC_OUTPUT)" $(if $(GRHSIM_MIGRATE_EC_PROFILE),--profile-output "$(GRHSIM_MIGRATE_EC_PROFILE)",) $(if $(GRHSIM_MIGRATE_EC_CYCLES),--cycles "$(GRHSIM_MIGRATE_EC_CYCLES)",)

.PHONY: test_grhsim_migrate_ec_census
test_grhsim_migrate_ec_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_migrate_ec_census.py

.PHONY: analyze_grhsim_migrate_ec
analyze_grhsim_migrate_ec:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_migrate_ec_gates.py \
		$(if $(filter 1,$(GRHSIM_CHECKPOINT_ALLOW_SOURCE_RENUMBER)),--allow-grh-source-renumber,) \
		--old-model "$(GRHSIM_MIGRATE_EC_OLD_MODEL)" --new-model "$(GRHSIM_MIGRATE_EC_NEW_MODEL)" \
		--baseline-run "$(GRHSIM_MIGRATE_EC_BASELINE_RUN)" \
		$(if $(GRHSIM_MIGRATE_EC_RUN1),--run1 "$(GRHSIM_MIGRATE_EC_RUN1)",) \
		$(if $(GRHSIM_MIGRATE_EC_RUN2),--run2 "$(GRHSIM_MIGRATE_EC_RUN2)",) \
		$(if $(GRHSIM_MIGRATE_EC_CENSUS),--census "$(GRHSIM_MIGRATE_EC_CENSUS)",) \
		--output "$(GRHSIM_MIGRATE_EC_OUTPUT)"

.PHONY: test_grhsim_migrate_ec_gates
test_grhsim_migrate_ec_gates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_migrate_ec_gates.py

.PHONY: test_grhsim_checkpoint_identity
test_grhsim_checkpoint_identity:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_checkpoint_identity.py

.PHONY: analyze_grhsim_residue_fold_census
analyze_grhsim_residue_fold_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_residue_fold_census.py --model "$(GRHSIM_RESIDUE_MODEL)" $(if $(GRHSIM_RESIDUE_RUN),--run "$(GRHSIM_RESIDUE_RUN)",) --output "$(GRHSIM_RESIDUE_OUTPUT)" $(if $(GRHSIM_RESIDUE_CYCLES),--cycles "$(GRHSIM_RESIDUE_CYCLES)",)

.PHONY: test_grhsim_residue_fold_census
test_grhsim_residue_fold_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_residue_fold_census.py

.PHONY: analyze_grhsim_residue_fold
analyze_grhsim_residue_fold:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_residue_fold_gates.py \
		--old-model "$(GRHSIM_RESIDUE_OLD_MODEL)" --new-model "$(GRHSIM_RESIDUE_NEW_MODEL)" \
		$(if $(GRHSIM_RESIDUE_BASELINE_RUN),--baseline-run "$(GRHSIM_RESIDUE_BASELINE_RUN)",) \
		$(if $(GRHSIM_RESIDUE_RUN1),--run1 "$(GRHSIM_RESIDUE_RUN1)",) \
		$(if $(GRHSIM_RESIDUE_RUN2),--run2 "$(GRHSIM_RESIDUE_RUN2)",) \
		$(if $(GRHSIM_RESIDUE_CENSUS_SELECTED),--census-selected "$(GRHSIM_RESIDUE_CENSUS_SELECTED)",) \
		$(if $(GRHSIM_RESIDUE_NEUTRAL_DIR),--neutral-dir "$(GRHSIM_RESIDUE_NEUTRAL_DIR)",) \
		$(if $(GRHSIM_RESIDUE_NEUTRAL_REF),--neutral-ref "$(GRHSIM_RESIDUE_NEUTRAL_REF)",) \
		$(foreach log,$(GRHSIM_RESIDUE_HDLBITS_LOGS),--hdlbits-log "$(log)") \
		$(if $(GRHSIM_RESIDUE_EXPECTED_DYNAMIC),--expected-dynamic "$(GRHSIM_RESIDUE_EXPECTED_DYNAMIC)",) \
		--output "$(GRHSIM_RESIDUE_OUTPUT)"

.PHONY: test_grhsim_residue_fold_gates
test_grhsim_residue_fold_gates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_residue_fold_gates.py

.PHONY: analyze_grhsim_kind_cost_census
analyze_grhsim_kind_cost_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_kind_cost_census.py --model "$(GRHSIM_KINDCOST_MODEL)" --run "$(GRHSIM_KINDCOST_RUN)" --emu "$(GRHSIM_KINDCOST_EMU)" --output "$(GRHSIM_KINDCOST_OUTPUT)" $(if $(GRHSIM_KINDCOST_CYCLES),--cycles "$(GRHSIM_KINDCOST_CYCLES)",)

.PHONY: test_grhsim_kind_cost_census
test_grhsim_kind_cost_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_kind_cost_census.py

GRHSIM_MODCMP_ROOT ?= ptmp/no00020_gsim_module_compare_20260926
GRHSIM_MODCMP_GSIM ?= $(GRHSIM_MODCMP_ROOT)/gsim-export/SimTop_PreCoarsen.json
GRHSIM_MODCMP_GRHSIM_PRE ?= $(GRHSIM_MODCMP_ROOT)/flow/grhsim_pre_partition.json
GRHSIM_MODCMP_GRHSIM_FINAL ?= $(GRHSIM_MODCMP_ROOT)/flow/xiangshan_grhsim_ir.json
GRHSIM_MODCMP_GRHSIM_FULL ?= $(GRHSIM_MODCMP_ROOT)/flow/xiangshan_grhsim_ir_full.json
GRHSIM_MODCMP_GRHSIM_ARCHIVE ?= ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json
GRHSIM_MODCMP_OUTPUT ?= $(GRHSIM_MODCMP_ROOT)/analysis

.PHONY: analyze_grhsim_gsim_module_compare
analyze_grhsim_gsim_module_compare:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_gsim_module_compare.py \
		--gsim-json "$(GRHSIM_MODCMP_GSIM)" \
		--grhsim-pre "$(GRHSIM_MODCMP_GRHSIM_PRE)" \
		--grhsim-final "$(GRHSIM_MODCMP_GRHSIM_FINAL)" \
		--grhsim-full "$(GRHSIM_MODCMP_GRHSIM_FULL)" \
		--grhsim-archive "$(GRHSIM_MODCMP_GRHSIM_ARCHIVE)" \
		--out-dir "$(GRHSIM_MODCMP_OUTPUT)" $(if $(GRHSIM_MODCMP_TOP_N),--top-n "$(GRHSIM_MODCMP_TOP_N)",) $(if $(GRHSIM_MODCMP_G2REF),--g2-reference "$(GRHSIM_MODCMP_G2REF)",)

.PHONY: test_grhsim_gsim_module_compare
test_grhsim_gsim_module_compare:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_gsim_module_compare.py

GRHSIM_BUCKET_ROOT ?= ptmp/no00021_bucket_dyn_price_20260927
GRHSIM_BUCKET_MODEL ?= ptmp/no00019_migrate_ec_20260926/flow/xiangshan_grhsim_ir.json
GRHSIM_BUCKET_RUN ?= ptmp/no00019_migrate_ec_20260926/run1/logs/xs_grhsim_no00019_migrateec_run1_20260926.log
GRHSIM_BUCKET_OUTPUT ?= $(GRHSIM_BUCKET_ROOT)/analysis
GRHSIM_BUCKET_EXPECT_OPS ?= {"(reg-to-mem)": 409314, "(packed)": 271174, "(events)": 63336}
GRHSIM_BUCKET_EXPECT_WR ?= 20799649516

.PHONY: analyze_grhsim_bucket_dyn_price
analyze_grhsim_bucket_dyn_price:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_bucket_dyn_price.py \
		--model "$(GRHSIM_BUCKET_MODEL)" \
		--run "$(GRHSIM_BUCKET_RUN)" \
		--output "$(GRHSIM_BUCKET_OUTPUT)" \
		--expect-ops '$(GRHSIM_BUCKET_EXPECT_OPS)' \
		--expect-vchg-wr "$(GRHSIM_BUCKET_EXPECT_WR)" $(if $(GRHSIM_BUCKET_CYCLES),--cycles "$(GRHSIM_BUCKET_CYCLES)",)

.PHONY: test_grhsim_bucket_dyn_price
test_grhsim_bucket_dyn_price:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_bucket_dyn_price.py

GRHSIM_GCONE_ROOT ?= ptmp/no00022_writenet_factor_20260927
GRHSIM_GCONE_MODEL ?= ptmp/no00019_migrate_ec_20260926/flow/xiangshan_grhsim_ir.json
GRHSIM_GCONE_RUN ?= ptmp/no00019_migrate_ec_20260926/run1/logs/xs_grhsim_no00019_migrateec_run1_20260926.log
GRHSIM_GCONE_OUTPUT ?= $(GRHSIM_GCONE_ROOT)/gcone
GRHSIM_GCONE_EXPECT_FAMILIES ?= {"fpRat/arch_table": 34, "fpRat/difftest_table": 32, "vecRat/arch_table": 47, "vecRat/difftest_table": 31}

.PHONY: analyze_grhsim_rat_gcone
analyze_grhsim_rat_gcone:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_rat_gcone_census.py \
		--model "$(GRHSIM_GCONE_MODEL)" \
		--run "$(GRHSIM_GCONE_RUN)" \
		--output "$(GRHSIM_GCONE_OUTPUT)/run1" \
		--expect-families '$(GRHSIM_GCONE_EXPECT_FAMILIES)' $(if $(GRHSIM_GCONE_CYCLES),--cycles "$(GRHSIM_GCONE_CYCLES)",) \
		$(if $(GRHSIM_GCONE_EXPECT_MEMORIES),--expect-memories '$(GRHSIM_GCONE_EXPECT_MEMORIES)',)
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_rat_gcone_census.py \
		--model "$(GRHSIM_GCONE_MODEL)" \
		--run "$(GRHSIM_GCONE_RUN)" \
		--output "$(GRHSIM_GCONE_OUTPUT)/run2" \
		--expect-families '$(GRHSIM_GCONE_EXPECT_FAMILIES)' $(if $(GRHSIM_GCONE_CYCLES),--cycles "$(GRHSIM_GCONE_CYCLES)",) \
		$(if $(GRHSIM_GCONE_EXPECT_MEMORIES),--expect-memories '$(GRHSIM_GCONE_EXPECT_MEMORIES)',)
	diff "$(GRHSIM_GCONE_OUTPUT)/run1/summary.json" "$(GRHSIM_GCONE_OUTPUT)/run2/summary.json"
	diff "$(GRHSIM_GCONE_OUTPUT)/run1/summary.md" "$(GRHSIM_GCONE_OUTPUT)/run2/summary.md"

.PHONY: test_grhsim_rat_gcone
test_grhsim_rat_gcone:
	@mkdir -p "$(REPO_ROOT)/ptmp/grhsim-rat-gcone-tests"
	TMPDIR="$(REPO_ROOT)/ptmp/grhsim-rat-gcone-tests" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_rat_gcone_census.py

GRHSIM_RESIDUAL_ROOT ?= ptmp/no00023_residual_write_cones_20260927
GRHSIM_RESIDUAL_PARENT ?= ptmp/no00022_writenet_factor_20260927
GRHSIM_RESIDUAL_RUN ?= $(GRHSIM_RESIDUAL_PARENT)/run1/run.log
GRHSIM_RESIDUAL_OUTPUT ?= $(GRHSIM_RESIDUAL_ROOT)/analysis/run1

.PHONY: analyze_grhsim_residual_write_cones test_grhsim_residual_write_cones
analyze_grhsim_residual_write_cones:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_residual_write_cones.py \
		--pre "$(GRHSIM_RESIDUAL_ROOT)/flow/pre_partition.json" \
		--final "$(GRHSIM_RESIDUAL_ROOT)/flow/xiangshan_grhsim_ir.json" \
		--archive "$(GRHSIM_RESIDUAL_PARENT)/flow/xiangshan_grhsim_ir.json" \
		--dynamic-model "$(GRHSIM_RESIDUAL_PARENT)/flow-dyn2/xiangshan_grhsim_ir.json" \
		--gsim "$(GRHSIM_MODCMP_GSIM)" --run "$(GRHSIM_RESIDUAL_RUN)" \
		--output "$(GRHSIM_RESIDUAL_OUTPUT)"

test_grhsim_residual_write_cones:
	@mkdir -p "$(REPO_ROOT)/ptmp/grhsim-residual-write-tests"
	TMPDIR="$(REPO_ROOT)/ptmp/grhsim-residual-write-tests" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_residual_write_cones.py

.PHONY: inspect_grhsim_residual_write_cones
inspect_grhsim_residual_write_cones:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_residual_write_cones.py \
		--gsim "$(GRHSIM_MODCMP_GSIM)" --inspect-report "$(GRHSIM_RESIDUAL_OUTPUT)/summary.json" \
		--output "$(GRHSIM_RESIDUAL_ROOT)/details"

GRHSIM_ICLASS_DISASM ?= ptmp/no00018_iclass_20260926/disasm_full.txt

GRHSIM_BIT_UPDATE_ROOT ?= ptmp/no00025_bit_update_census_20260927
GRHSIM_BIT_UPDATE_PARENT ?= ptmp/no00024_or_write_recovery_20260927/flow
GRHSIM_BIT_UPDATE_OUTPUT ?= $(GRHSIM_BIT_UPDATE_ROOT)/analysis/run1
.PHONY: analyze_grhsim_bit_updates test_grhsim_bit_updates
analyze_grhsim_bit_updates:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_bit_update_census.py \
		--pre "$(GRHSIM_BIT_UPDATE_ROOT)/flow/pre_partition.json" \
		--final "$(GRHSIM_BIT_UPDATE_ROOT)/flow/xiangshan_grhsim_ir.json" \
		--parent "$(GRHSIM_BIT_UPDATE_PARENT)/xiangshan_grhsim_ir.json" \
		--dynamic "$(GRHSIM_BIT_UPDATE_ROOT)/dynamic/xiangshan_grhsim_ir.json" \
		--run1 "$(GRHSIM_BIT_UPDATE_ROOT)/dynamic-run1.log" \
		--run2 "$(GRHSIM_BIT_UPDATE_ROOT)/dynamic-run2.log" \
		--gsim "$(GRHSIM_MODCMP_GSIM)" --output "$(GRHSIM_BIT_UPDATE_OUTPUT)"

test_grhsim_bit_updates:
	@mkdir -p "$(REPO_ROOT)/ptmp/grhsim-bit-update-tests"
	TMPDIR="$(REPO_ROOT)/ptmp/grhsim-bit-update-tests" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_bit_update_census.py

GRHSIM_DECLARED_PACK_ROOT ?= ptmp/no00026_declared_pack_census_20260928
GRHSIM_DECLARED_PACK_POST_LOWER ?= $(GRHSIM_DECLARED_PACK_ROOT)/flow/post_lower.json
GRHSIM_DECLARED_PACK_FINAL ?= $(GRHSIM_DECLARED_PACK_ROOT)/dynamic/xiangshan_grhsim_ir.json
GRHSIM_DECLARED_PACK_MEMBERS ?= $(GRHSIM_DECLARED_PACK_ROOT)/flow/pack_members.tsv
GRHSIM_DECLARED_PACK_REG2MEM ?= ptmp/declsym_baseline_20260928/flow/reg_to_mem.tsv
GRHSIM_DECLARED_PACK_RUN1 ?= $(GRHSIM_DECLARED_PACK_ROOT)/dynamic-run1.log
GRHSIM_DECLARED_PACK_RUN2 ?= $(GRHSIM_DECLARED_PACK_ROOT)/dynamic-run2.log
GRHSIM_DECLARED_PACK_TOP_N ?= 25
GRHSIM_DECLARED_PACK_SAMPLE_VERIFY ?= 0
GRHSIM_DECLARED_PACK_SAMPLE_SEED ?= 20260928
GRHSIM_DECLARED_PACK_OUTPUT ?= $(GRHSIM_DECLARED_PACK_ROOT)/analysis/run1

.PHONY: analyze_grhsim_declared_pack_census test_grhsim_declared_pack_census
analyze_grhsim_declared_pack_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_declared_pack_census.py \
		--post-lower-json "$(GRHSIM_DECLARED_PACK_POST_LOWER)" \
		--final-json "$(GRHSIM_DECLARED_PACK_FINAL)" \
		--pack-members "$(GRHSIM_DECLARED_PACK_MEMBERS)" \
		--reg-to-mem "$(GRHSIM_DECLARED_PACK_REG2MEM)" \
		--run1 "$(GRHSIM_DECLARED_PACK_RUN1)" \
		--run2 "$(GRHSIM_DECLARED_PACK_RUN2)" \
		--top-n "$(GRHSIM_DECLARED_PACK_TOP_N)" \
		--sample-verify "$(GRHSIM_DECLARED_PACK_SAMPLE_VERIFY)" \
		--sample-seed "$(GRHSIM_DECLARED_PACK_SAMPLE_SEED)" \
		--out-dir "$(GRHSIM_DECLARED_PACK_OUTPUT)"

test_grhsim_declared_pack_census:
	@mkdir -p "$(REPO_ROOT)/ptmp/grhsim-declared-pack-tests"
	TMPDIR="$(REPO_ROOT)/ptmp/grhsim-declared-pack-tests" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_declared_pack_census.py

GRHSIM_PAIRED_ROOT ?= ptmp/no00027_paired_cone_diff_20260928
GRHSIM_PAIRED_BASE ?= ptmp/declsym_baseline_20260928/flow
GRHSIM_PAIRED_DYNAMIC ?= ptmp/no00026_declared_pack_census_20260928
GRHSIM_PAIRED_OUTPUT ?= $(GRHSIM_PAIRED_ROOT)/analysis/run1
GRHSIM_PAIRED_REFERENCE ?=

.PHONY: analyze_grhsim_paired_cone_diff test_grhsim_paired_cone_diff
analyze_grhsim_paired_cone_diff:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_paired_cone_diff.py \
		--gsim-json ptmp/no00020_gsim_module_compare_20260926/gsim-export/SimTop_PreCoarsen.json \
		--gsim-sha256 abed2a4e4ca6553b275ea2b21012f0cb7ec20ef18bc8c2b3e5345f4f0c2c2411 \
		--grhsim-pre "$(GRHSIM_PAIRED_BASE)/pre_partition.json" \
		--grhsim-final "$(GRHSIM_PAIRED_BASE)/xiangshan_grhsim_ir.json" \
		--grhsim-dynamic "$(GRHSIM_PAIRED_DYNAMIC)/dynamic/xiangshan_grhsim_ir.json" \
		--model-dir "$(GRHSIM_PAIRED_DYNAMIC)/dynamic/model" \
		--run1 "$(GRHSIM_PAIRED_DYNAMIC)/dynamic-run1.log" \
		--run2 "$(GRHSIM_PAIRED_DYNAMIC)/dynamic-run2.log" \
		--sample-verify 100 --sample-seed 20260928 --out-dir "$(GRHSIM_PAIRED_OUTPUT)" \
		$(if $(GRHSIM_PAIRED_REFERENCE),--g2-reference "$(GRHSIM_PAIRED_REFERENCE)",)

test_grhsim_paired_cone_diff:
	@mkdir -p "$(REPO_ROOT)/ptmp/grhsim-paired-cone-tests"
	TMPDIR="$(REPO_ROOT)/ptmp/grhsim-paired-cone-tests" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_paired_cone_diff.py

GRHSIM_UNPAIRED_MODEL ?= $(GRHSIM_PAIRED_BASE)/xiangshan_grhsim_ir.json
GRHSIM_UNPAIRED_GSIM ?= $(GRHSIM_MODCMP_GSIM)
GRHSIM_UNPAIRED_REFERENCE ?= $(GRHSIM_PAIRED_ROOT)/analysis/run7
GRHSIM_UNPAIRED_OUTPUT ?= ptmp/grhsim_unpaired_registers_20260928

.PHONY: export_grhsim_unpaired_registers
export_grhsim_unpaired_registers:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_unpaired_registers.py \
		--model "$(GRHSIM_UNPAIRED_MODEL)" --gsim "$(GRHSIM_UNPAIRED_GSIM)" \
		--reference "$(GRHSIM_UNPAIRED_REFERENCE)" --output "$(GRHSIM_UNPAIRED_OUTPUT)"

GRHSIM_GUARDED_BASE ?= ptmp/declsym_baseline_20260928/flow
GRHSIM_GUARDED_DYNAMIC ?= ptmp/no00026_declared_pack_census_20260928
GRHSIM_GUARDED_OUTPUT ?= ptmp/no00028_guarded_write_census_20260928/analysis/run1
GRHSIM_GUARDED_REFERENCE ?=
GRHSIM_GUARDED_PRODUCTION ?= ptmp/no00028_guarded_write_census_20260928/flow

.PHONY: analyze_grhsim_guarded_writes test_grhsim_guarded_writes verify_grhsim_guarded_production
analyze_grhsim_guarded_writes:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_guarded_write_census.py \
		--pre "$(GRHSIM_GUARDED_BASE)/pre_partition.json" \
		--final "$(GRHSIM_GUARDED_BASE)/xiangshan_grhsim_ir.json" \
		--dynamic "$(GRHSIM_GUARDED_DYNAMIC)/dynamic/xiangshan_grhsim_ir.json" \
		--model-dir "$(GRHSIM_GUARDED_DYNAMIC)/dynamic/model" \
		--run1 "$(GRHSIM_GUARDED_DYNAMIC)/dynamic-run1.log" \
		--run2 "$(GRHSIM_GUARDED_DYNAMIC)/dynamic-run2.log" \
		--output "$(GRHSIM_GUARDED_OUTPUT)" \
		$(if $(GRHSIM_GUARDED_REFERENCE),--reference "$(GRHSIM_GUARDED_REFERENCE)",)

test_grhsim_guarded_writes:
	@mkdir -p "$(REPO_ROOT)/ptmp/grhsim-guarded-write-tests"
	TMPDIR="$(REPO_ROOT)/ptmp/grhsim-guarded-write-tests" PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_guarded_write_census.py

verify_grhsim_guarded_production:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_guarded_write_census.py \
		--verify-production "$(GRHSIM_GUARDED_PRODUCTION)" --baseline "$(GRHSIM_GUARDED_BASE)"

GRHSIM_ICLASS_EMU ?= ptmp/no00015_edge_complete_20260925/flow/emu/emu
GRHSIM_ICLASS_PERF_ROOT ?= ptmp/no00018_iclass_20260926
GRHSIM_ICLASS_MODEL ?= ptmp/no00015_edge_complete_20260925/flow/xiangshan_grhsim_ir.json
GRHSIM_ICLASS_RUN ?= ptmp/no00015_edge_complete_20260925/run1/logs/xs_grhsim_no00015_edgecomplete_run1_20260926.log
GRHSIM_ICLASS_PHASE ?= ptmp/no00018_iclass_20260926/phase_ref.csv
GRHSIM_ICLASS_OUTPUT ?= ptmp/no00018_iclass_20260926/analysis

.PHONY: analyze_grhsim_dyn_iclass
analyze_grhsim_dyn_iclass:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_dyn_iclass_profile.py --disasm "$(GRHSIM_ICLASS_DISASM)" --emu "$(GRHSIM_ICLASS_EMU)" \
		--perf "$(GRHSIM_ICLASS_PERF_ROOT)/perf1/perf.data" \
		--perf "$(GRHSIM_ICLASS_PERF_ROOT)/perf2/perf.data" \
		--perf "$(GRHSIM_ICLASS_PERF_ROOT)/perf3/perf.data" \
		--perf "$(GRHSIM_ICLASS_PERF_ROOT)/perf4/perf.data" \
		--perf "$(GRHSIM_ICLASS_PERF_ROOT)/perf5/perf.data" \
		$(if $(GRHSIM_ICLASS_MODEL),--model "$(GRHSIM_ICLASS_MODEL)",) \
		$(if $(GRHSIM_ICLASS_RUN),--run "$(GRHSIM_ICLASS_RUN)",) \
		$(if $(GRHSIM_ICLASS_PHASE),--phase-csv "$(GRHSIM_ICLASS_PHASE)",) \
		--output "$(GRHSIM_ICLASS_OUTPUT)" $(if $(GRHSIM_ICLASS_CYCLES),--cycles "$(GRHSIM_ICLASS_CYCLES)",)

.PHONY: test_grhsim_dyn_iclass
test_grhsim_dyn_iclass:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_dyn_iclass_profile.py

.PHONY: analyze_grhsim_topocut
analyze_grhsim_topocut:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_topocut_stats.py --model "$(GRHSIM_TOPOCUT_MODEL)"

.PHONY: analyze_grhsim_boundary_layout
analyze_grhsim_boundary_layout:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_boundary_layout_stats.py --model "$(GRHSIM_BOUNDARY_LAYOUT_MODEL)"

.PHONY: analyze_grhsim_change_implication
analyze_grhsim_change_implication:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_change_implication_stats.py --model "$(GRHSIM_CHANGE_IMPLICATION_MODEL)"

.PHONY: analyze_grhsim_slice_chains
analyze_grhsim_slice_chains:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_slice_chain_stats.py --model "$(GRHSIM_SLICE_CHAIN_MODEL)"

.PHONY: analyze_grhsim_algebra_residue
analyze_grhsim_algebra_residue:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_algebra_residue_stats.py --model "$(GRHSIM_ALGEBRA_MODEL)"

# Module-level simulation-time attribution (pdocs/grhsim.md section 6):
# supernode origin manifest + purity stats, then NNLS-calibrated module attribution.
GRHSIM_ORIGIN_MODEL ?= $(XS_GRHSIM_JSON_ABS)
GRHSIM_ORIGIN_EMIT_MANIFEST ?= $(XS_GRHSIM_EMIT_CPP_DIR)/manifest.json
GRHSIM_ORIGIN_MANIFEST ?= ptmp/grhsim-attribution/supernode_origin_manifest.json
GRHSIM_ORIGIN_REPORT ?= ptmp/grhsim-attribution/supernode_origin_report.md
GRHSIM_SN_TIMING_TSV ?= ptmp/grhsim-attribution/sn_timing.tsv
GRHSIM_ATTRIBUTION_TSV ?= ptmp/grhsim-attribution/module_attribution.tsv
GRHSIM_ATTRIBUTION_REPORT ?= ptmp/grhsim-attribution/module_attribution.md
.PHONY: analyze_grhsim_supernode_origins analyze_grhsim_module_attribution
analyze_grhsim_supernode_origins:
	@mkdir -p $(dir $(GRHSIM_ORIGIN_MANIFEST))
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_supernode_origin_stats.py --model "$(GRHSIM_ORIGIN_MODEL)" \
		--emit-manifest "$(GRHSIM_ORIGIN_EMIT_MANIFEST)" \
		--manifest "$(GRHSIM_ORIGIN_MANIFEST)" --report "$(GRHSIM_ORIGIN_REPORT)"
analyze_grhsim_module_attribution:
	@mkdir -p $(dir $(GRHSIM_ATTRIBUTION_TSV))
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_module_attribution.py \
		--manifest "$(GRHSIM_ORIGIN_MANIFEST)" --timing "$(GRHSIM_SN_TIMING_TSV)" \
		--out-tsv "$(GRHSIM_ATTRIBUTION_TSV)" --report "$(GRHSIM_ATTRIBUTION_REPORT)"

# End-to-end module-level attribution pipeline (pdocs/grhsim.md section 6):
#   model+emu (SN_TIMING=1) -> instrumented difftest run (sn_timing TSV)
#   -> origin manifest + purity report -> NNLS module attribution.
# Heavy stages are skippable when their artifacts already exist:
#   make run_grhsim_module_attribution                # full pipeline from current model
#   make run_grhsim_module_attribution SKIP_EMU_BUILD=1 SKIP_EMU_RUN=1  # re-join only
#   make run_grhsim_module_attribution GRHSIM_ORIGIN_MODEL=<other.json> # analyze a checkpoint
GRHSIM_ATTRIBUTION_EMU_PREFIX ?= EMU_RUNTIME_PROFILE=1 WOLVRIX_GRHSIM_SN_PROFILE=$(CURDIR)/$(GRHSIM_SN_TIMING_TSV) taskset -c $(if $(GRHSIM_BENCH_CPU),$(GRHSIM_BENCH_CPU),2)
.PHONY: run_grhsim_module_attribution grhsim_attribution_emu grhsim_attribution_run
run_grhsim_module_attribution:
	@$(MAKE) --no-print-directory grhsim_attribution_emu
	@$(MAKE) --no-print-directory grhsim_attribution_run
	@$(MAKE) --no-print-directory analyze_grhsim_supernode_origins
	@$(MAKE) --no-print-directory analyze_grhsim_module_attribution
	@echo "[DONE] module attribution: $(GRHSIM_ATTRIBUTION_REPORT)"

# Build the instrumented emu (per-supernode rdtscp probes). Skip with SKIP_EMU_BUILD=1.
grhsim_attribution_emu:
ifneq ($(SKIP_EMU_BUILD),1)
	@$(MAKE) --no-print-directory xs_grhsim_build_emu WOLVRIX_GRHSIM_SN_TIMING=1
else
	@echo "[SKIP] emu build (SKIP_EMU_BUILD=1)"
endif

# Run the instrumented emu under difftest, dumping the per-supernode timing TSV.
# Skip with SKIP_EMU_RUN=1 (reuse an existing $(GRHSIM_SN_TIMING_TSV)).
grhsim_attribution_run:
ifneq ($(SKIP_EMU_RUN),1)
	@mkdir -p $(dir $(GRHSIM_SN_TIMING_TSV))
	@$(MAKE) --no-print-directory run_xs_grhsim_emu XS_EMU_PREFIX="$(GRHSIM_ATTRIBUTION_EMU_PREFIX)"
	@test -s "$(GRHSIM_SN_TIMING_TSV)" || { echo "[FAIL] timing TSV not produced: $(GRHSIM_SN_TIMING_TSV) (model built with WOLVRIX_GRHSIM_SN_TIMING=1?)"; exit 1; }
else
	@echo "[SKIP] emu run (SKIP_EMU_RUN=1)"
endif

GRHSIM_BOOL_CHAIN_MODEL ?= $(XS_GRHSIM_BUILD_ABS)/model
GRHSIM_BOOL_CHAIN_OUTPUT ?= ptmp/grhsim-bool-chains.json
GRHSIM_BOOL_CHAIN_CSV ?= ptmp/grhsim-bool-chains-ge16.csv
.PHONY: analyze_grhsim_bool_chains test_grhsim_bool_chains
analyze_grhsim_bool_chains:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_bool_chain_stats.py --model-dir "$(GRHSIM_BOOL_CHAIN_MODEL)" --output "$(GRHSIM_BOOL_CHAIN_OUTPUT)" --long-csv "$(GRHSIM_BOOL_CHAIN_CSV)"

test_grhsim_bool_chains:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_bool_chain_stats.py

XS_MUX1H_CENSUS_OUTPUT ?= ptmp/mux1h-census
XS_MUX1H_CENSUS_FIR ?= $(XS_SIM_TOP_FIR)
.PHONY: analyze_xs_mux1h test_xs_mux1h_census
analyze_xs_mux1h:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/xiangshan_mux1h_census.py --fir "$(XS_MUX1H_CENSUS_FIR)" --output "$(XS_MUX1H_CENSUS_OUTPUT)"

test_xs_mux1h_census:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_xiangshan_mux1h_census.py

GRHSIM_MASKED_OR_COVERAGE_MODEL ?=
GRHSIM_MASKED_OR_COVERAGE_REPORT ?=
.PHONY: analyze_grhsim_masked_or_coverage
analyze_grhsim_masked_or_coverage:
	@test -f "$(GRHSIM_MASKED_OR_COVERAGE_MODEL)" && test -f "$(GRHSIM_MASKED_OR_COVERAGE_REPORT)" || { echo "Set GRHSIM_MASKED_OR_COVERAGE_MODEL to the IR before recovery and GRHSIM_MASKED_OR_COVERAGE_REPORT to its matching report"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_masked_or_coverage.py --model "$(GRHSIM_MASKED_OR_COVERAGE_MODEL)" --report "$(GRHSIM_MASKED_OR_COVERAGE_REPORT)" --output "$(XS_MUX1H_CENSUS_OUTPUT)"

.PHONY: analyze_grhsim_used_bits
analyze_grhsim_used_bits:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_used_bits_stats.py --model "$(GRHSIM_USED_BITS_MODEL)"

.PHONY: analyze_grhsim_priority_cond
analyze_grhsim_priority_cond:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_guard_absorb_stats.py --model "$(GRHSIM_GUARD_ABSORB_MODEL)"

.PHONY: analyze_grhsim_cone_replicate
analyze_grhsim_cone_replicate:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_cone_replicate_stats.py --model "$(GRHSIM_CONE_REPLICATE_MODEL)"

.PHONY: analyze_grhsim_task_read_cache
analyze_grhsim_task_read_cache:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_task_read_cache_stats.py --model "$(GRHSIM_TASK_CACHE_MODEL)" $(if $(GRHSIM_TASK_CACHE_LOG),--log "$(GRHSIM_TASK_CACHE_LOG)",)

.PHONY: analyze_grhsim_lane_fusion
analyze_grhsim_lane_fusion:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_lane_fusion_stats.py --model "$(GRHSIM_LANE_FUSION_MODEL)"

.PHONY: analyze_grhsim_lut_cones
analyze_grhsim_lut_cones:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_lut_cone_stats.py --model "$(GRHSIM_LUT_CONE_MODEL)" $(if $(GRHSIM_LUT_CONE_MAX_INPUTS),--max-inputs "$(GRHSIM_LUT_CONE_MAX_INPUTS)",) $(if $(GRHSIM_LUT_CONE_MIN_OPS),--min-ops "$(GRHSIM_LUT_CONE_MIN_OPS)",) $(if $(GRHSIM_LUT_CONE_RATIO),--ratio "$(GRHSIM_LUT_CONE_RATIO)",) $(if $(GRHSIM_LUT_CONE_MIN_CROSSING),--min-crossing "$(GRHSIM_LUT_CONE_MIN_CROSSING)",) $(if $(filter 1,$(GRHSIM_LUT_CONE_SELECT)),--select,) $(if $(filter 1,$(GRHSIM_LUT_CONE_CROSS)),--cross,) $(if $(filter 1,$(GRHSIM_LUT_CONE_TABLES)),--tables,) $(if $(filter 1,$(GRHSIM_LUT_CONE_GROUP)),--group,) $(if $(filter 1,$(GRHSIM_LUT_CONE_CONCAT_SINKS)),--concat-sinks,) $(if $(filter 1,$(GRHSIM_LUT_CONE_PROFIT_GATE)),--profit-gate,) $(if $(filter 1,$(GRHSIM_LUT_CONE_WIDE_CONES)),--wide-cones,)

.PHONY: analyze_grhsim_commit_history
analyze_grhsim_commit_history:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_commit_history_stats.py --model "$(GRHSIM_COMMIT_HISTORY_MODEL)"

.PHONY: analyze_grhsim_commit_cluster
analyze_grhsim_commit_cluster:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_commit_cluster_stats.py --model "$(GRHSIM_COMMIT_CLUSTER_MODEL)" $(if $(GRHSIM_COMMIT_CLUSTER_TOP),--top "$(GRHSIM_COMMIT_CLUSTER_TOP)",)

.PHONY: analyze_grhsim_compute_hotspots
analyze_grhsim_compute_hotspots:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_compute_hotspots.py --profile "$(GRHSIM_HOT_PROFILE)" --binary "$(GRHSIM_HOT_BINARY)" --model "$(GRHSIM_HOT_MODEL)" --expected-samples "$(GRHSIM_HOT_SAMPLES)" $(if $(GRHSIM_HOT_TOP),--top "$(GRHSIM_HOT_TOP)",) $(if $(GRHSIM_HOT_NATIVE_CACHE),--native-cache "$(GRHSIM_HOT_NATIVE_CACHE)",) $(if $(GRHSIM_HOT_REFERENCE_DIR),--reference-dir "$(GRHSIM_HOT_REFERENCE_DIR)",)

.PHONY: analyze_grhsim_compute_branches
analyze_grhsim_compute_branches:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_compute_branch_classes.py --model-dir "$(GRHSIM_BRANCH_MODEL_DIR)" $(if $(GRHSIM_BRANCH_BINARY),--binary "$(GRHSIM_BRANCH_BINARY)",) $(if $(GRHSIM_BRANCH_NATIVE_CACHE),--native-cache "$(GRHSIM_BRANCH_NATIVE_CACHE)",) $(if $(GRHSIM_BRANCH_FOCUS),--focus-tasks "$(GRHSIM_BRANCH_FOCUS)",)

.PHONY: analyze_grhsim_task_similarity
analyze_grhsim_task_similarity:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_task_similarity.py --model-dir "$(GRHSIM_SIM_MODEL_DIR)" --binary "$(GRHSIM_SIM_BINARY)" $(if $(GRHSIM_SIM_NATIVE_CACHE),--native-cache "$(GRHSIM_SIM_NATIVE_CACHE)",) $(if $(GRHSIM_SIM_HOT_TASKS),--hot-tasks "$(GRHSIM_SIM_HOT_TASKS)",)

.PHONY: analyze_grhsim_replicate
analyze_grhsim_replicate:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_replicate_stats.py --model "$(GRHSIM_REPLICATE_MODEL)"

.PHONY: analyze_grhsim_scalar_staging
.PHONY: analyze_grhsim_history_sharing
analyze_grhsim_history_sharing:
	$(PYTHON) $(CURDIR)/scripts/grhsim_history_sharing_stats.py "$(GRHSIM_HISTORY_BASELINE)" "$(GRHSIM_HISTORY_CANDIDATE)"

analyze_grhsim_scalar_staging:
	@test -n "$(GRHSIM_STAGE_MODEL)" || { echo "Set GRHSIM_STAGE_MODEL to the generated model .cpp"; exit 1; }
	$(PYTHON) $(CURDIR)/scripts/grhsim_scalar_stage_stats.py --model "$(GRHSIM_STAGE_MODEL)"

.PHONY: analyze_grhsim_activity_guards
analyze_grhsim_activity_guards:
	@test -n "$(GRHSIM_ACTIVITY_MODEL)" || { echo "Set GRHSIM_ACTIVITY_MODEL to the generated model .cpp"; exit 1; }
	$(PYTHON) $(CURDIR)/scripts/grhsim_activity_guard_stats.py --model "$(GRHSIM_ACTIVITY_MODEL)"

# Stage-07 7c: the reg-to-mem pass, its test/analysis targets
# (test_grhsim_reg_to_mem*, inspect/analyze/rewrite/summarize_grhsim_reg_to_mem,
# measure_grhsim_reg_to_mem_build, benchmark_grhsim_reg_to_mem) and the
# companion scripts (scripts/benchmark_grhsim_reg_to_mem.py,
# scripts/test_grhsim_reg_to_mem_rtl.py) are retired — preserve-aggregate RTL
# carries the array structure the pass used to recover. The rationale and the
# negative-result knowledge stay in wolvrix/docs/history/grhsim-ir/passes/reg-to-mem.md
# and git history. Current state splitting is described in pdocs/grhsim.md.

.PHONY: py_install
py_install:
	@echo "[PY] Installing wolvrix into the current Python environment via scikit-build-core"
	@PIP_DISABLE_PIP_VERSION_CHECK=1 $(PIP) install --no-build-isolation $(PIP_CONFIG_SETTINGS) -e $(WOLVRIX_DIR)

.PHONY: run_xs_bugcase_grhsim
XS_BUGCASE_GRHSIM_WORK ?= $(REPO_ROOT)/ptmp/xs-bugcase-grhsim
run_xs_bugcase_grhsim: check_remove_grhsim_ir_options $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)
	@mkdir -p "$(XS_BUGCASE_GRHSIM_WORK)/ccache"
	@set +e; passed=0; failed=0; \
	  export CCACHE_DIR="$(XS_BUGCASE_GRHSIM_WORK)/ccache"; \
	  summary="$(XS_BUGCASE_GRHSIM_WORK)/summary.txt"; \
	  : > "$$summary"; \
	  for index in $$(seq 1 27); do \
	    case_tag=$$(printf 'CASE_%03d' "$$index"); \
	    target=run; if [ "$$index" -le 5 ]; then target=run_grhsim; fi; \
	    log="$(XS_BUGCASE_GRHSIM_WORK)/$${case_tag}.log"; \
	    echo "[RUN] $$case_tag $$target"; \
	    if $(MAKE) --no-print-directory -C "$(REPO_ROOT)/testcase/xs-bugcase/$$case_tag" "$$target" OUT_DIR_BASE="$(XS_BUGCASE_GRHSIM_WORK)/$$case_tag" OUT="$(XS_BUGCASE_GRHSIM_WORK)/$$case_tag" >"$$log" 2>&1; then \
	      echo "PASS $$case_tag" | tee -a "$$summary"; passed=$$((passed + 1)); \
	    else \
	      echo "FAIL $$case_tag ($$log)" | tee -a "$$summary"; failed=$$((failed + 1)); \
	    fi; \
	  done; \
	  echo "Result: $$passed/27 passed, $$failed failed" | tee -a "$$summary"; \
	  test "$$failed" -eq 0

$(HDLBITS_EMITTED_DUT) $(HDLBITS_EMITTED_JSON): $(HDLBITS_DUT_SRC) $(HDLBITS_WOLVRIX_SCRIPT) check_id
	@mkdir -p $(HDLBITS_OUT_DIR)
	$(PYTHON) $(HDLBITS_WOLVRIX_SCRIPT) $(DUT) $(HDLBITS_OUT_DIR)

$(HDLBITS_SIM_BIN): $(HDLBITS_EMITTED_DUT) $(HDLBITS_TB_SRC) check_id
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

run_hdlbits_grhsim: check_remove_grhsim_ir_options
ifneq ($(strip $(DUT)),)
  ifeq ($(DUT),$(filter $(DUT),$(HDLBITS_GRHSIM_DUTS)))
	@if [ "$(SKIP_PY_INSTALL)" != "1" ]; then \
		$(MAKE) --no-print-directory py_install; \
	fi
	@$(MAKE) --no-print-directory -C $(HDLBITS_ROOT) run_grhtb \
		DUT=$(DUT) \
		PYTHON=$(PYTHON) \
		BUILD_DIR=$(abspath $(HDLBITS_GRHSIM_BUILD_DIR)) \
		GRHSIM_SCRIPT=$(HDLBITS_GRHSIM_SCRIPT) \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM) \
		WOLVRIX_GRHSIM_PERF=$(WOLVRIX_GRHSIM_PERF) \
		WOLVRIX_GRHSIM_SN_TIMING=$(WOLVRIX_GRHSIM_SN_TIMING)
  else
	$(error DUT=$(DUT) not found in grhtb; available: $(HDLBITS_GRHSIM_DUTS))
  endif
else
	@echo "DUT not set; running all available GrhSIM DUTs: $(HDLBITS_GRHSIM_DUTS)"
	@$(MAKE) --no-print-directory run_all_hdlbits_grhsim_tests
endif

run_all_hdlbits_grhsim_tests:
	@if [ "$(SKIP_PY_INSTALL)" != "1" ]; then $(MAKE) --no-print-directory py_install; fi
	@for dut in $(HDLBITS_GRHSIM_DUTS); do \
		echo "==== Running GrhSIM DUT=$$dut ===="; \
		$(MAKE) --no-print-directory run_hdlbits_grhsim DUT=$$dut SKIP_PY_INSTALL=1 || exit $$?; \
	done

HDLBITS_GRHSIM_REPORT_DIR ?= $(CURDIR)/ptmp/hdlbits-grhsim-full/$(RUN_ID)
.PHONY: run_all_hdlbits_grhsim_tests_report
run_all_hdlbits_grhsim_tests_report:
	@if [ "$(SKIP_PY_INSTALL)" != "1" ]; then $(MAKE) --no-print-directory py_install; fi
	@mkdir -p "$(HDLBITS_GRHSIM_REPORT_DIR)"
	@passed=0; failed=0; failed_duts=""; \
	for dut in $(HDLBITS_GRHSIM_DUTS); do \
		printf '[HDLBITS] DUT=%s ' "$$dut"; \
		if $(MAKE) --no-print-directory run_hdlbits_grhsim DUT="$$dut" SKIP_PY_INSTALL=1 \
			> "$(HDLBITS_GRHSIM_REPORT_DIR)/dut_$$dut.log" 2>&1; then \
			passed=$$((passed + 1)); echo PASS; \
		else \
			failed=$$((failed + 1)); failed_duts="$$failed_duts $$dut"; echo FAIL; \
		fi; \
	done; \
	printf 'passed=%s failed=%s total=%s\nfailed_duts=%s\n' \
		"$$passed" "$$failed" "$$((passed + failed))" "$${failed_duts# }" \
		| tee "$(HDLBITS_GRHSIM_REPORT_DIR)/summary.txt"; \
	echo "[HDLBITS] Logs: $(HDLBITS_GRHSIM_REPORT_DIR)"; \
	test "$$failed" -eq 0

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
	@echo "[CMD] $(XS_MILL_ENV) $(MAKE) -C $(XS_ROOT) sim-verilog BUILD_DIR=$(XS_RTL_BUILD_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) PRESERVE_AGGREGATE=all" | tee -a "$(LOG_FILE)"
	$(XS_MILL_ENV) NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT) sim-verilog \
		BUILD_DIR=$(XS_RTL_BUILD_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		PRESERVE_AGGREGATE=all

.PHONY: check_xs_aggregate_rtl
check_xs_aggregate_rtl: $(XS_SIM_TOP_V)
	@rg -q -- '--preserve-aggregate=all([[:space:]"]|$$)' "$(XS_RTL_BUILD_ABS)/time.log" && \
		rg -q 'Exit status: 0' "$(XS_RTL_BUILD_ABS)/time.log" || { \
			echo "[FAIL] RTL lacks a successful preserve-aggregate=all generation record; run make clean_xs_rtl xs_rtl"; exit 1; }
	@echo "[CONFIG] XiangShan RTL: preserve-aggregate=all ($(XS_RTL_DIR_ABS))"

xs_rtl: check_xs_aggregate_rtl

xs_gsim_rtl:
	@echo "[RUN] Generating XiangShan GSIM sim-verilog into $(XS_RTL_BUILD_ABS)..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@mkdir -p "$(XS_ROOT)/build"
	@$(eval LOG_FILE := $(XS_LOG_DIR_ABS)/xs_gsim_simverilog_$(RUN_ID).log)
	@echo "[LOG] Recording GSIM sim-verilog command to: $(LOG_FILE)"
	@printf '' > "$(LOG_FILE)"
	@FORCE_FLAG="$(if $(wildcard $(XS_DIFFTEST_GSIM_EXTMODULE)),,-B)"; \
		echo "[CMD] $(XS_MILL_ENV) $(MAKE) $$FORCE_FLAG -C $(XS_ROOT) sim-verilog BUILD_DIR=$(XS_RTL_BUILD_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) PRESERVE_AGGREGATE=all GSIM=1" | tee -a "$(LOG_FILE)"; \
		$(XS_MILL_ENV) NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $$FORCE_FLAG -C "$(XS_ROOT)" sim-verilog \
			BUILD_DIR="$(XS_RTL_BUILD_ABS)" \
			NUM_CORES="$(XS_NUM_CORES)" \
			RTL_SUFFIX="$(XS_RTL_SUFFIX)" \
			PRESERVE_AGGREGATE=all \
			GSIM=1
	@if [ ! -f "$(XS_DIFFTEST_GSIM_EXTMODULE)" ]; then \
		echo "[FAIL] xs gsim sim-verilog: missing generated extmodule $(XS_DIFFTEST_GSIM_EXTMODULE)"; \
		exit 1; \
	fi

$(XS_GRHSIM_FILELIST_ABS): $(XS_SIM_TOP_V) | check_xs_aggregate_rtl
	@mkdir -p "$(dir $@)"
	@{ \
		find "$(XS_RTL_DIR_ABS)" -type f -name "*.sv" -o -type f -name "*.v"; \
		find "$(XS_VSRC_DIR_ABS)" -type f -name "*.sv" -o -type f -name "*.v"; \
	} | LC_ALL=C sort > "$@"

xs_grhsim_filelist: $(XS_GRHSIM_FILELIST_ABS)

XS_GRHSIM_DEPS := $(if $(filter 1,$(SKIP_PY_INSTALL)),,py_install)

xs_grhsim_hier_json: $(XS_GRHSIM_FILELIST_ABS) $(XS_GRHSIM_DEPS)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@mkdir -p "$(XS_GRHSIM_BUILD_ABS)"
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(RUN_ID))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_grhsim_hier_json_$(RUN_ID).log)
	@$(eval XS_READ_ARGS_FILE := $(XS_GRHSIM_BUILD_ABS)/wolvrix_read_args.txt)
	@echo "[LOG] Capturing hierarchical GrhSIM JSON output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_READ_ARGS_FILE)"
	@printf "%s\n" $(XS_GRHSIM_INCLUDE_FLAGS) $(XS_GRHSIM_DEFINE_FLAGS) >> "$(XS_READ_ARGS_FILE)"
	@{ \
		echo "[CMD] $(PYTHON) $(XS_HIER_JSON_SCRIPT) $(XS_GRHSIM_FILELIST_ABS) $(XS_SIM_TOP) $(XS_GRHSIM_HIER_JSON_ABS) $(XS_READ_ARGS_FILE) $(if $(filter 1,$(XS_GRHSIM_HIER_JSON_ROUNDTRIP)),--roundtrip,) $(if $(filter 1,$(XS_GRHSIM_HIER_JSON_SKIP_SAFE_PASSES)),--skip-safe-passes,) --log-level $(WOLF_LOG)"; \
		$(PYTHON) $(XS_HIER_JSON_SCRIPT) \
			$(XS_GRHSIM_FILELIST_ABS) \
			$(XS_SIM_TOP) \
			$(XS_GRHSIM_HIER_JSON_ABS) \
			$(XS_READ_ARGS_FILE) \
			$(if $(filter 1,$(XS_GRHSIM_HIER_JSON_ROUNDTRIP)),--roundtrip,) \
			$(if $(filter 1,$(XS_GRHSIM_HIER_JSON_SKIP_SAFE_PASSES)),--skip-safe-passes,) \
			--log-level $(WOLF_LOG); \
	} 2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"

# Pass only deviations from the Python flow's production defaults.
XS_GRHSIM_FLAGS = \
	$(if $(filter 1,$(XS_GRHSIM_RESUME_FROM_FLAT_GRH_JSON)),--resume-from-flat-grh,) \
	$(if $(filter 1,$(XS_GRHSIM_ROUNDTRIP_VERIFY)),,--no-roundtrip-verify) \
	$(if $(filter 0,$(XS_GRHSIM_KEEP_ORIGINS)),--no-keep-origins,) \
	$(if $(strip $(XS_GRHSIM_MEM_MIN_BYTES)),--mem-min-bytes $(XS_GRHSIM_MEM_MIN_BYTES),) \
	$(if $(filter 0,$(XS_GRHSIM_CLONE_SHARED_COMPUTE)),--no-clone-shared-compute,) \
	$(if $(filter-out 250000,$(XS_GRHSIM_CLONE_SHARED_COMPUTE_MAX_CLONES)),--clone-shared-compute-max-clones $(XS_GRHSIM_CLONE_SHARED_COMPUTE_MAX_CLONES),) \
	$(if $(filter 0,$(XS_GRHSIM_PHASE_SIMPLIFY)),--no-phase-simplify,) \
	$(if $(filter 0,$(XS_GRHSIM_MASKED_OR)),--no-recover-masked-or,) \
	$(if $(filter-out 16,$(XS_GRHSIM_MASKED_OR_MIN_TERMS)),--masked-or-min-terms $(XS_GRHSIM_MASKED_OR_MIN_TERMS),) \
	$(if $(strip $(XS_GRHSIM_MASKED_OR_REPORT)),--masked-or-report "$(abspath $(XS_GRHSIM_MASKED_OR_REPORT))",) \
	$(if $(filter 0,$(XS_GRHSIM_PACK_BIT_REGISTERS)),--no-pack-bit-registers,) \
	$(if $(strip $(XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE)),--max-op-in-compute-supernode $(XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE),) \
	--max-function-lines $(XS_GRHSIM_MAX_FUNCTION_LINES) --max-tu-bytes $(XS_GRHSIM_MAX_TU_BYTES) \
	$(if $(filter-out 4294967296,$(XS_GRHSIM_MAX_OUTPUT_FILE_BYTES)),--max-output-file-bytes $(XS_GRHSIM_MAX_OUTPUT_FILE_BYTES),) \
	$(if $(strip $(XS_GRHSIM_EMIT_CPP_DIR)),--emit-cpp-dir "$(abspath $(XS_GRHSIM_EMIT_CPP_DIR))",) \
	$(if $(filter 0,$(XS_GRHSIM_OVERWRITE_CPP)),--no-overwrite-emit-cpp,) \
	$(if $(filter 0,$(XS_GRHSIM_READABLE_NAMES)),--no-readable-names,) \
	$(if $(filter 0,$(XS_GRHSIM_SOURCE_COMMENTS)),--no-source-comments,) \
	$(if $(filter 0,$(XS_GRHSIM_READABLE_DUMP)),--no-readable-dump,) \
	$(if $(filter 0,$(XS_GRHSIM_READABLE_FRAMES)),--no-readable-frames,) \
	$(if $(filter-out on-write,$(XS_GRHSIM_MEM_WRITE_ACTIVATE)),--mem-write-activate "$(XS_GRHSIM_MEM_WRITE_ACTIVATE)",) \
	$(if $(filter-out on,$(XS_GRHSIM_MEM_ENABLE_BITMAP)),--mem-enable-bitmap "$(XS_GRHSIM_MEM_ENABLE_BITMAP)",) \
	$(if $(filter 1,$(WOLVRIX_GRHSIM_WAVEFORM)),--emit-waveform,) \
	$(if $(strip $(XS_GRHSIM_DUMP_POST_CONVERSION_JSON)),--dump-post-conversion-json "$(abspath $(XS_GRHSIM_DUMP_POST_CONVERSION_JSON))",) \
	$(if $(strip $(XS_GRHSIM_DUMP_PRE_SIMPLIFY_JSON)),--dump-pre-simplify-json "$(abspath $(XS_GRHSIM_DUMP_PRE_SIMPLIFY_JSON))",) \
	$(if $(strip $(XS_GRHSIM_DUMP_PRE_PARTITION_JSON)),--dump-pre-partition-json "$(abspath $(XS_GRHSIM_DUMP_PRE_PARTITION_JSON))",) \
	$(if $(strip $(XS_GRHSIM_PACK_BIT_REGISTERS_REPORT)),--pack-bit-registers-report "$(abspath $(XS_GRHSIM_PACK_BIT_REGISTERS_REPORT))",)

xs_grhsim: check_remove_grhsim_ir_options $(XS_GRHSIM_FILELIST_ABS) $(XS_GRHSIM_DEPS)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@mkdir -p "$(XS_GRHSIM_BUILD_ABS)" "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(RUN_ID))
	@$(eval XS_GRHSIM_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_grhsim_$(RUN_ID).log)
	@$(eval XS_GRHSIM_READ_ARGS_FILE := $(XS_GRHSIM_BUILD_ABS)/wolvrix_read_args.txt)
	@printf '' > "$(XS_GRHSIM_LOG_FILE)"
	@printf '' > "$(XS_GRHSIM_READ_ARGS_FILE)"
	@printf "%s\n" $(XS_GRHSIM_INCLUDE_FLAGS) $(XS_GRHSIM_DEFINE_FLAGS) >> "$(XS_GRHSIM_READ_ARGS_FILE)"
	@echo "[LOG] Capturing GrhSIM checkpoint output to: $(XS_GRHSIM_LOG_FILE)"
	@set -o pipefail; { \
		set -- $(PYTHON) "$(XS_GRHSIM_SCRIPT)" \
			"$(XS_GRHSIM_FILELIST_ABS)" \
			"$(XS_SIM_TOP)" \
			"$(XS_GRHSIM_FLAT_GRH_JSON_ABS)" \
			"$(XS_GRHSIM_JSON_ABS)" \
			"$(XS_GRHSIM_ROUNDTRIP_JSON_ABS)" \
			"$(XS_GRHSIM_READ_ARGS_FILE)" \
			"$(WOLF_LOG)" \
			$(XS_GRHSIM_FLAGS); \
		printf '[CMD]'; printf ' %q' "$$@"; printf '\n'; \
		"$$@"; \
	} 2>&1 | tee -a "$(XS_GRHSIM_LOG_FILE)"; \
	status=$$?; \
	echo "[EXIT] xs_grhsim $$status" | tee -a "$(XS_GRHSIM_LOG_FILE)"; \
	exit $$status


.PHONY: clean_xs_grhsim clean_xs_rtl clean_xs_retired xs_grhsim_reemit xs_grhsim_emu xs_grhsim_build_emu
clean_xs_retired:
	@echo "[CLEAN] Retired scalar XiangShan RTL/models and legacy wolf/repcut outputs"
	@rm -rf -- "$(REPO_ROOT)/build/xs/rtl" "$(REPO_ROOT)/build/xs/grhsim" \
		"$(REPO_ROOT)/build/xs/wolf" \
		"$(REPO_ROOT)/build/xs/repcut" "$(REPO_ROOT)/ptmp/grhsim-active8" \
		"$(REPO_ROOT)/ptmp/grhsim-active8-verify" "$(REPO_ROOT)/ptmp/xs/wolf"

clean_xs_grhsim:
	@case "$(XS_GRHSIM_BUILD_ABS)" in \
		"$(REPO_ROOT)/ptmp/"?*|"$(REPO_ROOT)/build/"?*) ;; \
		*) echo "[FAIL] Refusing to clean outside repository build/ptmp directories"; exit 1 ;; \
	esac
	@echo "[CLEAN] $(XS_GRHSIM_BUILD_ABS)"
	@rm -rf -- "$(XS_GRHSIM_BUILD_ABS)"

clean_xs_rtl:
	@case "$(XS_RTL_BUILD_ABS)" in \
		"$(REPO_ROOT)/ptmp/"?*|"$(REPO_ROOT)/build/"?*) ;; \
		*) echo "[FAIL] Refusing to clean outside repository build/ptmp directories"; exit 1 ;; \
	esac
	@echo "[CLEAN] $(XS_RTL_BUILD_ABS)"
	@rm -rf -- "$(XS_RTL_BUILD_ABS)"

xs_grhsim_reemit: check_remove_grhsim_ir_options check_xs_aggregate_rtl
	@$(PYTHON) scripts/reemit_grhsim.py \
		--model "$(XS_GRHSIM_JSON_ABS)" --flow "$(XS_GRHSIM_BUILD_ABS)" \
		--overwrite --mem-write-activate "$(XS_GRHSIM_MEM_WRITE_ACTIVATE)" \
		--mem-enable-bitmap "$(XS_GRHSIM_MEM_ENABLE_BITMAP)" \
		--max-function-lines "$(XS_GRHSIM_MAX_FUNCTION_LINES)" --max-tu-bytes "$(XS_GRHSIM_MAX_TU_BYTES)" \
		$(if $(filter 1,$(WOLVRIX_GRHSIM_WAVEFORM)),--emit-waveform,)

xs_grhsim_emu: xs_grhsim
	@$(MAKE) --no-print-directory xs_grhsim_build_emu

# Match the accepted aggregate benchmarks on the build host without extra flags.
xs_grhsim_build_emu: check_xs_aggregate_rtl
	@test -n "$(XS_GRHSIM_EMIT_CPP_DIR)" && test -f "$(XS_GRHSIM_EMIT_CPP_DIR)/Makefile" || { echo "[FAIL] Generate the GrhSIM C++ model before build-only emu"; exit 1; }
	@echo "[RUN] Building XiangShan emu with the GrhSIM generated model..."
	@NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_BUILD_ABS)/emu \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		VM_BUILD_JOBS=$(if $(VM_BUILD_JOBS),$(VM_BUILD_JOBS),$(XS_VM_BUILD_JOBS)) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(abspath $(XS_GRHSIM_EMIT_CPP_DIR)) \
		GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -march=native -fno-strict-aliasing -DWOLVRIX_GRHSIM_PERF=$(WOLVRIX_GRHSIM_PERF) -DWOLVRIX_GRHSIM_SN_TIMING=$(WOLVRIX_GRHSIM_SN_TIMING)" \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)

# Compiler PGO for the GrhSIM emu: three-phase build (instrument, train on the
# production workload with difftest on, profile-use rebuild). Emitted sources are
# untouched; only compile/link flags change. The emu toolchain is clang (difftest
# default), so the flags use LLVM IR PGO: phase 2 writes raw profiles under
# XS_GRHSIM_PGO_DIR, llvm-profdata merges them, phase 3 consumes the
# merged .profdata. The PGO dir is wiped on every build, keeping the flow
# self-contained.
XS_GRHSIM_PGO_JOBS ?= $(if $(VM_BUILD_JOBS),$(VM_BUILD_JOBS),$(XS_VM_BUILD_JOBS))
XS_GRHSIM_PGO_DIR ?= $(XS_GRHSIM_BUILD_ABS)/pgo
LLVM_PROFDATA ?= llvm-profdata

.PHONY: xs_grhsim_emu_pgo xs_grhsim_build_emu_pgo
xs_grhsim_emu_pgo: xs_grhsim
	@$(MAKE) --no-print-directory xs_grhsim_build_emu_pgo

xs_grhsim_build_emu_pgo: check_xs_aggregate_rtl
	@test -n "$(XS_GRHSIM_EMIT_CPP_DIR)" && test -f "$(XS_GRHSIM_EMIT_CPP_DIR)/Makefile" || { echo "[FAIL] Generate the GrhSIM C++ model before PGO emu build"; exit 1; }
	@command -v "$(LLVM_PROFDATA)" >/dev/null || { echo "[FAIL] llvm-profdata not found (set LLVM_PROFDATA)"; exit 1; }
	@echo "[RUN] PGO phase 1/3: instrumented emu build (model + harness)"
	@rm -rf "$(XS_GRHSIM_PGO_DIR)" && mkdir -p "$(XS_GRHSIM_PGO_DIR)"
	@rm -f "$(XS_GRHSIM_EMIT_CPP_DIR)"/*.o "$(XS_GRHSIM_EMIT_CPP_DIR)"/libgrhsim_*.a
	@if [ -d "$(XS_GRHSIM_BUILD_ABS)/emu/grhsim-compile" ]; then \
		find "$(XS_GRHSIM_BUILD_ABS)/emu/grhsim-compile" -name '*.o' -delete; \
		rm -f "$(XS_GRHSIM_BUILD_ABS)/emu/grhsim-compile/emu"; \
	fi
	@NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_BUILD_ABS)/emu \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		VM_BUILD_JOBS=$(XS_GRHSIM_PGO_JOBS) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(abspath $(XS_GRHSIM_EMIT_CPP_DIR)) \
		GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -fprofile-generate" \
		PGO_CFLAGS="-fprofile-generate" \
		PGO_LDFLAGS="-fprofile-generate" \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)
	@echo "[RUN] PGO phase 2/3: training run (difftest on, production run flags)"
	@cd "$(XS_GRHSIM_BUILD_ABS)/emu" && LLVM_PROFILE_FILE="$(XS_GRHSIM_PGO_DIR)/train-%p.profraw" \
		EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
		-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
		--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
		-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
		$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),)
	@echo "[RUN] PGO phase 2/3: merge profiles with $(LLVM_PROFDATA)"
	@"$(LLVM_PROFDATA)" merge -output="$(XS_GRHSIM_PGO_DIR)/code.profdata" "$(XS_GRHSIM_PGO_DIR)"/*.profraw
	@echo "[RUN] PGO phase 3/3: profile-use rebuild"
	@rm -f "$(XS_GRHSIM_EMIT_CPP_DIR)"/*.o "$(XS_GRHSIM_EMIT_CPP_DIR)"/libgrhsim_*.a
	@find "$(XS_GRHSIM_BUILD_ABS)/emu/grhsim-compile" -name '*.o' -delete
	@rm -f "$(XS_GRHSIM_BUILD_ABS)/emu/grhsim-compile/emu"
	@NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_BUILD_ABS)/emu \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		VM_BUILD_JOBS=$(XS_GRHSIM_PGO_JOBS) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(abspath $(XS_GRHSIM_EMIT_CPP_DIR)) \
		GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -fprofile-use=$(XS_GRHSIM_PGO_DIR)/code.profdata" \
		PGO_CFLAGS="-fprofile-use=$(XS_GRHSIM_PGO_DIR)/code.profdata" \
		PGO_LDFLAGS="-fprofile-use=$(XS_GRHSIM_PGO_DIR)/code.profdata" \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)

xs_ref_emu: check_xs_aggregate_rtl
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

xs_gsim_emu: xs_gsim_rtl
	@if [ ! -x "$(XS_GSIM_BIN)" ] && [ -f "$(REF_GSIM_ROOT)/Makefile" ]; then \
		echo "[RUN] Building reference gsim..."; \
		$(MAKE) --no-print-directory -C "$(REF_GSIM_ROOT)" build-gsim; \
	fi
	@echo "[RUN] Building XiangShan gsim emu..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_gsim_build_$(RUN_ID).log)
	@echo "[LOG] Capturing build output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $(if $(strip $(XS_VM_BUILD_JOBS)),-j $(XS_VM_BUILD_JOBS),) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_GSIM_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_RTL_DIR_ABS) SIM_TOP_V=$(XS_SIM_TOP_V) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=$(XS_EMU_THREADS) VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) GSIM=1 GSIM_BIN=$(XS_GSIM_BIN)" | tee -a "$(XS_BUILD_LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $(if $(strip $(XS_VM_BUILD_JOBS)),-j $(XS_VM_BUILD_JOBS),) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GSIM_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_RTL_DIR_ABS) \
		SIM_TOP_V=$(XS_SIM_TOP_V) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=$(XS_EMU_THREADS) \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		GSIM=1 \
		GSIM_BIN="$(XS_GSIM_BIN)" \
		2>&1 | tee "$(XS_BUILD_LOG_FILE)"

# Compiler PGO for the gsim emu, through the difftest gsim.mk three-phase flow
# (instrumented build -> training run on the production workload with difftest
# on -> profile-use rebuild). The toolchain is clang (gsim.mk GSIM_CXX), so the
# flow is LLVM IR PGO; PGO_BOLT=0 keeps the technique matched with the GrhSIM
# emu PGO build (llvm-bolt stays an orthogonal lever on both sides). The build
# goes to XS_GSIM_PGO_BUILD so the archived non-PGO emu under XS_GSIM_BUILD
# stays intact for A/B. Run it with: run_xs_gsim_emu XS_GSIM_BUILD=build/xs/gsim-pgo
xs_gsim_emu_pgo: xs_gsim_rtl
	@if [ ! -x "$(XS_GSIM_BIN)" ] && [ -f "$(REF_GSIM_ROOT)/Makefile" ]; then \
		echo "[RUN] Building reference gsim..."; \
		$(MAKE) --no-print-directory -C "$(REF_GSIM_ROOT)" build-gsim; \
	fi
	@echo "[RUN] Building XiangShan gsim emu with compiler PGO (instrument, train, profile-use)..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_gsim_pgo_build_$(RUN_ID).log)
	@echo "[LOG] Capturing build output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $(if $(strip $(XS_VM_BUILD_JOBS)),-j $(XS_VM_BUILD_JOBS),) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_GSIM_PGO_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_RTL_DIR_ABS) SIM_TOP_V=$(XS_SIM_TOP_V) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=$(XS_EMU_THREADS) VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) GSIM=1 GSIM_BIN=$(XS_GSIM_BIN) PGO_WORKLOAD=$(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin PGO_MAX_CYCLE=$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),$(XS_SIM_MAX_CYCLE),100000) PGO_EMU_ARGS=\"--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(XS_RAM_TRACE_ARGS)\" PGO_BOLT=0 LLVM_PROFDATA=$(LLVM_PROFDATA)" | tee -a "$(XS_BUILD_LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $(if $(strip $(XS_VM_BUILD_JOBS)),-j $(XS_VM_BUILD_JOBS),) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GSIM_PGO_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_RTL_DIR_ABS) \
		SIM_TOP_V=$(XS_SIM_TOP_V) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=$(XS_EMU_THREADS) \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		GSIM=1 \
		GSIM_BIN="$(XS_GSIM_BIN)" \
		PGO_WORKLOAD="$(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin" \
		PGO_MAX_CYCLE=$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),$(XS_SIM_MAX_CYCLE),100000) \
		PGO_EMU_ARGS="--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(XS_RAM_TRACE_ARGS)" \
		PGO_BOLT=0 \
		LLVM_PROFDATA="$(LLVM_PROFDATA)" \
		2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"
	@if [ ! -x "$(XS_GSIM_PGO_BUILD_ABS)/emu" ]; then \
		echo "[FAIL] xs gsim pgo: emu build did not produce executable $(XS_GSIM_PGO_BUILD_ABS)/emu"; \
		exit 1; \
	fi

# Diagnostic gsim emu with the in-tree runtime profile feature enabled
# (GSIM_EMIT_RUNTIME_PROFILE=1: supernode activation / node / enode counters and
# the per-supernode fire-count TSV). Pure command-line variable injection into
# the difftest gsim.mk flow; the anchored gsim/gsim-pgo builds stay untouched.
# Run it with: run_xs_gsim_emu XS_GSIM_BUILD=build/xs/gsim-rtprof \
#   XS_EMU_PREFIX="EMU_RUNTIME_PROFILE=1 GSIM_SUPERNODE_TSV=<fire.tsv> taskset -c 2 ..."
xs_gsim_emu_rtprof: xs_gsim_rtl
	@if [ ! -x "$(XS_GSIM_BIN)" ] && [ -f "$(REF_GSIM_ROOT)/Makefile" ]; then \
		echo "[RUN] Building reference gsim..."; \
		$(MAKE) --no-print-directory -C "$(REF_GSIM_ROOT)" build-gsim; \
	fi
	@echo "[RUN] Building XiangShan gsim emu with runtime profile counters..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_gsim_rtprof_build_$(RUN_ID).log)
	@echo "[LOG] Capturing build output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $(if $(strip $(XS_VM_BUILD_JOBS)),-j $(XS_VM_BUILD_JOBS),) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_GSIM_RTPROF_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) RTL_DIR=$(XS_RTL_DIR_ABS) SIM_TOP_V=$(XS_SIM_TOP_V) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) EMU_THREADS=$(XS_EMU_THREADS) VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) EMU_RANDOMIZE=0 WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) GSIM=1 GSIM_BIN=$(XS_GSIM_BIN) GSIM_EMIT_RUNTIME_PROFILE=1" | tee -a "$(XS_BUILD_LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $(if $(strip $(XS_VM_BUILD_JOBS)),-j $(XS_VM_BUILD_JOBS),) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GSIM_RTPROF_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		GEN_VSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		RTL_DIR=$(XS_RTL_DIR_ABS) \
		SIM_TOP_V=$(XS_SIM_TOP_V) \
		NUM_CORES=$(XS_NUM_CORES) \
		RTL_SUFFIX=$(XS_RTL_SUFFIX) \
		EMU_THREADS=$(XS_EMU_THREADS) \
		VM_BUILD_JOBS=$(XS_VM_BUILD_JOBS) \
		EMU_RANDOMIZE=0 \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		GSIM=1 \
		GSIM_BIN="$(XS_GSIM_BIN)" \
		GSIM_EMIT_RUNTIME_PROFILE=1 \
		2>&1 | tee "$(XS_BUILD_LOG_FILE)"
	@if [ ! -x "$(XS_GSIM_RTPROF_BUILD_ABS)/emu" ]; then \
		echo "[FAIL] xs gsim rtprof: emu build did not produce executable $(XS_GSIM_RTPROF_BUILD_ABS)/emu"; \
		exit 1; \
	fi

# Diagnostic export of the un-partitioned (PreCoarsen) gsim graph for the
# XiangShan design (NO00020): full graph JSON including assignTree ENode
# detail, plus the strict executable-GRH projection. Read-only export: it
# neither rebuilds gsim nor touches the anchored emu builds.
XS_GSIM_EXPORT_DIR ?= $(CURDIR)/ptmp/gsim_precoarsen_export
# xiangshan-gsim-coremark-stub stubs ext modules with initial-event side
# effects (e.g. PrintCommitIDModule) that full-fidelity export rejects.
XS_GSIM_EXPORT_GRH_PROFILE ?= xiangshan-gsim-coremark-stub
.PHONY: xs_gsim_export_precoarsen
xs_gsim_export_precoarsen:
	@if [ ! -x "$(XS_GSIM_BIN)" ] && [ -f "$(REF_GSIM_ROOT)/Makefile" ]; then \
		echo "[RUN] Building reference gsim..."; \
		$(MAKE) --no-print-directory -C "$(REF_GSIM_ROOT)" build-gsim; \
	fi
	@test -f "$(XS_SIM_TOP_FIR)" || { echo "[FAIL] missing $(XS_SIM_TOP_FIR); run make xs_gsim_rtl first"; exit 1; }
	@mkdir -p "$(XS_GSIM_EXPORT_DIR)" "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_GSIM_EXPORT_LOG := $(XS_LOG_DIR_ABS)/xs_gsim_export_precoarsen_$(RUN_ID).log)
	@echo "[LOG] Capturing gsim PreCoarsen export to: $(XS_GSIM_EXPORT_LOG)"
	@set -o pipefail; { \
		echo "[CMD] $(XS_GSIM_BIN) --supernode-max-size=$(XS_GSIM_SUPERNODE_MAX_SIZE) --cpp-max-size-KB=8192 --sep-mod=__DOT__ --sep-aggr=__DOT__ --dump-json --dump-assign-tree --dump-stages=PreCoarsen --stop-after-stage=PreCoarsen --export-executable-grh=$(XS_GSIM_EXPORT_DIR)/executable_grh.json --export-precoarsen-grh=$(XS_GSIM_EXPORT_DIR)/precoarsen_grh.json --dir $(XS_GSIM_EXPORT_DIR) $(XS_SIM_TOP_FIR)"; \
		$(XS_GSIM_BIN) \
			--supernode-max-size=$(XS_GSIM_SUPERNODE_MAX_SIZE) \
			--cpp-max-size-KB=8192 \
			--sep-mod=__DOT__ \
			--sep-aggr=__DOT__ \
			--dump-json --dump-assign-tree \
			--dump-stages=PreCoarsen \
			--stop-after-stage=PreCoarsen \
			--export-executable-grh="$(XS_GSIM_EXPORT_DIR)/executable_grh.json" \
			--executable-grh-profile="$(XS_GSIM_EXPORT_GRH_PROFILE)" \
			--export-precoarsen-grh="$(XS_GSIM_EXPORT_DIR)/precoarsen_grh.json" \
			--dir "$(XS_GSIM_EXPORT_DIR)" \
			"$(XS_SIM_TOP_FIR)"; \
	} 2>&1 | tee "$(XS_GSIM_EXPORT_LOG)"

run_xs_ref_emu:
	@test -x "$(XS_REF_BUILD_ABS)/emu" || { echo "[FAIL] Build the Verilator reference emu before running"; exit 1; }
	@set -o pipefail; \
	RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	mkdir -p "$$LOG_DIR"; \
	REF_LOG="$$LOG_DIR/xs_ref_$${RUN_ID}.log"; \
	REF_WAVEFORM="$(XS_WAVEFORM_DIR_ABS)/xs_ref_$${RUN_ID}.fst"; \
	printf '' > "$$REF_LOG"; \
	echo "[RUN] xs ref emu"; \
		echo "[CONFIG] Prebuilt Verilator reference: $(XS_REF_BUILD_ABS)/emu (uses its compiled RTL)"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL) XS_COMMIT_TRACE=$(XS_COMMIT_TRACE) XS_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) XS_LOG_BEGIN=$(XS_LOG_BEGIN) XS_LOG_END=$(XS_LOG_END)"; \
		echo "[LOG] ref : $$REF_LOG"; \
		if [ "$(XS_WAVEFORM)" = "1" ]; then \
			echo "[WAVEFORM] ref : $$REF_WAVEFORM"; \
		fi; \
		echo "[CMD] cd $(XS_REF_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) $(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$REF_WAVEFORM,)"; \
		cd $(XS_REF_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
			-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
			--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
			-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) \
			$(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$REF_WAVEFORM,) \
			2>&1 | tee "$$REF_LOG"

run_xs_gsim_emu: check_xs_aggregate_rtl
	@if [ "$(XS_WAVEFORM)" != "0" ] || [ -n "$(XS_WAVEFORM_PATH)" ]; then \
		echo "[FAIL] xs gsim: waveform is unsupported in the current gsim simulator path"; \
		exit 1; \
	fi
	@RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	mkdir -p "$$LOG_DIR"; \
	GSIM_LOG="$$LOG_DIR/xs_gsim_$${RUN_ID}.log"; \
	printf '' > "$$GSIM_LOG"; \
	echo "[RUN] xs gsim emu"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_COMMIT_TRACE=$(XS_COMMIT_TRACE) XS_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) XS_LOG_BEGIN=$(XS_LOG_BEGIN) XS_LOG_END=$(XS_LOG_END)"; \
		echo "[LOG] gsim: $$GSIM_LOG"; \
		echo "[CMD] cd $(XS_GSIM_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin $(XS_EMU_DIFF_ARGS) -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,)"; \
		cd $(XS_GSIM_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
			-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
			$(XS_EMU_DIFF_ARGS) \
			-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) \
			2>&1 | tee "$$GSIM_LOG"

.PHONY: run_xs_grhsim_emu
run_xs_grhsim_emu: check_xs_aggregate_rtl
	@test -x "$(XS_GRHSIM_BUILD_ABS)/emu/emu" || { echo "[FAIL] Build the GrhSIM emu before running"; exit 1; }
	@if { [ "$(XS_WAVEFORM)" != "0" ] || [ -n "$(XS_WAVEFORM_PATH)" ]; } && [ "$(WOLVRIX_GRHSIM_WAVEFORM)" != "1" ]; then \
		echo "[FAIL] xs grhsim: runtime waveform requested, but model was emitted without waveform support; rebuild with WOLVRIX_GRHSIM_WAVEFORM=1"; \
		exit 1; \
	fi
	@set -o pipefail; \
	RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	GRHSIM_LOG="$$LOG_DIR/xs_grhsim_$${RUN_ID}.log"; \
	GRHSIM_WAVEFORM="$(if $(XS_WAVEFORM_PATH_ABS),$(XS_WAVEFORM_PATH_ABS),$(XS_WAVEFORM_DIR_ABS)/xs_grhsim_$${RUN_ID}.fst)"; \
	mkdir -p "$$LOG_DIR" "$$(dirname "$$GRHSIM_WAVEFORM")"; \
	printf '' > "$$GRHSIM_LOG"; \
		echo "[RUN] xs grhsim emu"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL) XS_COMMIT_TRACE=$(XS_COMMIT_TRACE) XS_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) XS_LOG_BEGIN=$(XS_LOG_BEGIN) XS_LOG_END=$(XS_LOG_END) XS_WAVEFORM_PATH=$(if $(XS_WAVEFORM_PATH_ABS),$(XS_WAVEFORM_PATH_ABS),)"; \
		echo "[LOG] grhsim: $$GRHSIM_LOG"; \
		if [ "$(XS_WAVEFORM)" = "1" ] || [ -n "$(XS_WAVEFORM_PATH)" ]; then \
			echo "[WAVEFORM] grhsim: $$GRHSIM_WAVEFORM"; \
		fi; \
		echo "[CMD] cd $(XS_GRHSIM_BUILD_ABS)/emu && EMU_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin $(XS_EMU_DIFF_ARGS) -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$GRHSIM_WAVEFORM,)"; \
		cd $(XS_GRHSIM_BUILD_ABS)/emu && EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
			-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
			$(XS_EMU_DIFF_ARGS) \
			-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$GRHSIM_WAVEFORM,) \
		2>&1 | tee "$$GRHSIM_LOG"

clean:
	@rm -rf build
	@rm -rf $(C910_WORK_DIR)
	@rm -rf $(XS_ROOT)/build


# ---- VRT workflow 自测试 ----
# 在 ptmp/vrt-selftest 下搭建模拟 git 仓库，用 mock CLI 验证调度脚本，不触碰真实仓库
VRT_SELFTEST_DIR := $(REPO_ROOT)/ptmp/vrt-selftest

run_vrt_selftest:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) $(REPO_ROOT)/vrt/workflow/tests/selftest.py

# VRT_INBOX / VRT_INBOX_ACTOR are environment variables; user text goes via stdin.
VRT_INBOX_ACTION ?= show
vrt_inbox:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) $(REPO_ROOT)/vrt/workflow/runner_inbox.py $(VRT_INBOX_ACTION)

clean_vrt_selftest:
	rm -rf $(VRT_SELFTEST_DIR)

.PHONY: run_vrt_selftest clean_vrt_selftest vrt_inbox

# ---- grhsim-perf-opt goal protocol (separate from legacy benchmark gates) ----
GRHSIM_SEARCH_BUILD ?=
GRHSIM_SEARCH_OLD ?=
GRHSIM_SEARCH_NEW ?=
GRHSIM_SEARCH_OUTPUT ?=
GRHSIM_SEARCH_THRESHOLD ?= 10
GRHSIM_SEARCH_MAX_NEW_HOST_MS ?=
GRHSIM_SEARCH_JOBS ?= 32
GRHSIM_SEARCH_CPU ?= 2
GRHSIM_SEARCH_MAKE_ARGS ?=

.PHONY: grhsim_perf_search_build grhsim_perf_search_bench test_grhsim_perf_search
grhsim_perf_search_build:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_perf_search.py build \
		--output "$(GRHSIM_SEARCH_BUILD)" --jobs "$(GRHSIM_SEARCH_JOBS)" \
		--rtl "$(XS_RTL_DIR_ABS)" $(GRHSIM_SEARCH_MAKE_ARGS)

grhsim_perf_search_bench:
	@PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_perf_search.py benchmark \
		--old "$(GRHSIM_SEARCH_OLD)" --new "$(GRHSIM_SEARCH_NEW)" \
		--output "$(GRHSIM_SEARCH_OUTPUT)" --threshold "$(GRHSIM_SEARCH_THRESHOLD)" \
		--cpu "$(GRHSIM_SEARCH_CPU)" --rtl "$(XS_RTL_DIR_ABS)" \
		$(if $(strip $(GRHSIM_SEARCH_MAX_NEW_HOST_MS)),--max-new-host-ms "$(GRHSIM_SEARCH_MAX_NEW_HOST_MS)")

test_grhsim_perf_search:
	@mkdir -p ptmp/grhsim-perf-search-tests
	@set -o pipefail; PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover \
		-s scripts -p test_grhsim_perf_search.py -v \
		2>&1 | tee ptmp/grhsim-perf-search-tests/unittest.log

GRHSIM_NONSINK_MODEL ?=
GRHSIM_NONSINK_OUTPUT ?=
.PHONY: analyze_grhsim_nonsink_publications
analyze_grhsim_nonsink_publications:
	@test -n "$(GRHSIM_NONSINK_MODEL)" -a -n "$(GRHSIM_NONSINK_OUTPUT)" || { echo "Set GRHSIM_NONSINK_MODEL and GRHSIM_NONSINK_OUTPUT"; exit 1; }
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_nonsink_publication_stats.py \
		--model "$(GRHSIM_NONSINK_MODEL)" --output "$(GRHSIM_NONSINK_OUTPUT)"

GRHSIM_LAZY_SELECT_MODEL ?= ptmp/grhsim-perf-opt/NO00002-v1/model
GRHSIM_LAZY_SELECT_PROFILE ?= ptmp/grhsim-perf-opt/NO00003-baseline-profile/summary.json
GRHSIM_LAZY_SELECT_OUTPUT ?= ptmp/grhsim-perf-opt/NO00004-lazy-analysis/summary.json
GRHSIM_LAZY_SELECT_ARGS ?=
.PHONY: analyze_grhsim_lazy_select
analyze_grhsim_lazy_select:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/grhsim_lazy_select_stats.py \
		--model "$(GRHSIM_LAZY_SELECT_MODEL)" --profile "$(GRHSIM_LAZY_SELECT_PROFILE)" \
		--output "$(GRHSIM_LAZY_SELECT_OUTPUT)" $(GRHSIM_LAZY_SELECT_ARGS)

# Lossless storage for IR snapshots of failed, retired performance candidates.
# Keep the active NO00002 baseline and every binary/source/log unchanged.
GRHSIM_FAILED_IR_NODE ?=
.PHONY: archive_grhsim_perf_failed_ir restore_grhsim_perf_failed_ir
archive_grhsim_perf_failed_ir:
	@case "$(GRHSIM_FAILED_IR_NODE)" in NO00003|NO00004) ;; *) echo "Select a retired NO00003 or NO00004 node"; exit 1;; esac
	@rg -q '^\| 当前阶段 \| 失败' "pdocs/grhsim-perf-opt/$(GRHSIM_FAILED_IR_NODE).md"
	@set -euo pipefail; task_dir="$(CURDIR)/ptmp/grhsim-perf-opt/$(GRHSIM_FAILED_IR_NODE)-v1"; \
	for snapshot in xiangshan_flat_grh.json xiangshan_grhsim.json; do \
		task_file="$$task_dir/$$snapshot"; \
		if [ -f "$$task_file" ]; then sha256sum "$$task_file" > "$$task_file.archive.sha256"; fi; \
		test -s "$$task_file.archive.sha256"; \
		if [ ! -f "$$task_file.zst" ]; then zstd -q -T4 -3 --check --keep "$$task_file"; fi; \
		task_expected=$$(cut -d ' ' -f 1 "$$task_file.archive.sha256"); \
		task_actual=$$(zstd -q -d -c "$$task_file.zst" | sha256sum | cut -d ' ' -f 1); \
		test "$$task_actual" = "$$task_expected"; \
		if [ -f "$$task_file" ]; then rm -- "$$task_file"; fi; \
		printf 'Archived and verified %s\n' "$$snapshot"; \
	done

restore_grhsim_perf_failed_ir:
	@case "$(GRHSIM_FAILED_IR_NODE)" in NO00003|NO00004) ;; *) echo "Select a retired NO00003 or NO00004 node"; exit 1;; esac
	@set -euo pipefail; task_dir="$(CURDIR)/ptmp/grhsim-perf-opt/$(GRHSIM_FAILED_IR_NODE)-v1"; \
	for snapshot in xiangshan_flat_grh.json xiangshan_grhsim.json; do \
		task_file="$$task_dir/$$snapshot"; \
		if [ ! -f "$$task_file" ]; then zstd -q -d --keep "$$task_file.zst"; fi; \
		sha256sum --check "$$task_file.archive.sha256"; \
	done
