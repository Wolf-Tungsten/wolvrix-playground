SHELL := /bin/bash
REPO_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

FST_ROI_DISCOVERY_GOALS := build_fst_roi_discovery test_fst_roi_discovery clean_fst_roi_discovery
VRT_GOALS := run_vrt_selftest clean_vrt_selftest vrt_inbox
ifneq ($(filter $(FST_ROI_DISCOVERY_GOALS) $(VRT_GOALS),$(MAKECMDGOALS)),)
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
XS_WOLVRIX_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_emit.py
XS_WOLVRIX_HIER_JSON_SCRIPT := $(CURDIR)/grh-ir-visualize/tools/export_xiangshan_hier_json.py
XS_WOLVRIX_GRHSIM_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_grhsim.py
XS_WOLVRIX_GRHSIM_IR_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_grhsim_ir.py
XS_WOLVRIX_REPCUT_SCRIPT := $(CURDIR)/scripts/wolvrix_xs_repcut.py
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
XS_REPCUT_STEP_TIMING ?= 0
XS_NUM_CORES ?= 1
XS_EMU_THREADS ?= 2
XS_VM_BUILD_JOBS ?= $(shell nproc)
XS_SIM_TOP ?= SimTop
XS_RTL_SUFFIX ?= sv
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
XS_RAM_TRACE_ARGS := $(if $(filter 1,$(XS_RAM_TRACE)),+trace_difftest_ram,)
XS_LOG_DIR := $(BUILD_DIR)/logs/xs
XS_WAVEFORM_DIR ?= $(XS_LOG_DIR)
XS_LOG_DIR_ABS = $(abspath $(XS_LOG_DIR))
XS_WAVEFORM_DIR_ABS = $(abspath $(XS_WAVEFORM_DIR))
XS_WAVEFORM_PATH_ABS = $(if $(XS_WAVEFORM_PATH),$(if $(filter /%,$(XS_WAVEFORM_PATH)),$(XS_WAVEFORM_PATH),$(abspath $(XS_WAVEFORM_PATH))),)

XS_WORK_BASE ?= $(BUILD_DIR)/xs
XS_RTL_BUILD ?= $(XS_WORK_BASE)/rtl
XS_REF_BUILD ?= $(XS_WORK_BASE)/ref
XS_GSIM_BUILD ?= $(XS_WORK_BASE)/gsim
XS_GSIM_PGO_BUILD ?= $(XS_WORK_BASE)/gsim-pgo
XS_WOLF_BUILD ?= $(XS_WORK_BASE)/wolf
XS_GRHSIM_BUILD ?= $(XS_WORK_BASE)/grhsim
XS_GRHSIM_IR_BUILD ?= $(XS_WORK_BASE)/grhsim-ir
XS_REPCUT_BUILD ?= $(XS_WORK_BASE)/repcut
XS_RTL_DIR := $(XS_RTL_BUILD)/rtl
XS_VSRC_DIR ?= $(XS_ROOT)/difftest/src/test/vsrc/common
XS_WOLF_EMIT_DIR ?= $(XS_WOLF_BUILD)/wolf_emit
XS_WOLF_EMIT ?= $(XS_WOLF_EMIT_DIR)/wolf_emit.sv
XS_WOLF_FILELIST ?= $(XS_WOLF_EMIT_DIR)/xs_wolf.f
XS_WOLF_HIER_JSON ?= $(XS_WOLF_EMIT_DIR)/xs_wolf_hier.json
XS_WOLF_HIER_JSON_ROUNDTRIP ?= 1
XS_WOLF_HIER_JSON_SKIP_SAFE_PASSES ?= 0
XS_WOLF_GRHSIM_EMIT_DIR ?= $(XS_GRHSIM_BUILD)/grhsim_emit
XS_WOLF_GRHSIM_ENABLE_STATS ?= 0
XS_WOLF_GRHSIM_POST_STATS_JSON ?= $(XS_GRHSIM_BUILD)/wolvrix_xs_post_stats.json
XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON ?= $(XS_GRHSIM_BUILD)/wolvrix_xs_pre_reg_to_mem.json
XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON ?= 0
XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON ?= $(if $(filter 1,$(XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON)),0,$(if $(wildcard $(XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON)),1,0))
XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON ?= $(XS_GRHSIM_IR_BUILD)/xiangshan_flat_grh.json
XS_WOLF_GRHSIM_IR_JSON ?= $(XS_GRHSIM_IR_BUILD)/xiangshan_grhsim_ir.json
XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON ?= $(XS_GRHSIM_IR_BUILD)/xiangshan_grhsim_ir_roundtrip.json
XS_WOLF_GRHSIM_IR_REG_TO_MEM ?= 1
XS_WOLF_GRHSIM_IR_REG_TO_MEM_REPORT ?= $(XS_GRHSIM_IR_BUILD)/reg_to_mem.tsv
XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON ?= 0
XS_WOLF_GRHSIM_IR_KEEP_ORIGINS ?= 1
XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR ?=
# Batch count 0 keeps one emit function per compute supernode (the schedule
# every accepted xiangshan run was validated with). The pass default (64)
# merges supernodes into giant tasks, which makes text-level shape/block
# sharing much less effective.
XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT ?= 0
# Text-level sharing (shape-twin / branch-block noinline folding) is opt-in:
# it trades runtime for compile time, so the validated default keeps tasks
# fully inlined. Set to 1 to re-enable for compile-time pressure or A/B.
XS_WOLF_GRHSIM_IR_SHAPE_TWIN_SHARE ?=
XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_SHARE ?=
XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_HOTNESS ?=
XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_GROWTH_BUDGET ?= 1.0
# Falling-edge eval elision in the emitted CPU model is on by default; set to 1
# to emit without it (the emitted model also honors GRHSIM_IR_DISABLE_FP_ELISION).
XS_WOLF_GRHSIM_IR_DISABLE_FP_ELISION ?=
XS_WOLF_GRHSIM_IR_CLONE_SHARED_COMPUTE ?= 1
XS_WOLF_GRHSIM_IR_CLONE_SHARED_COMPUTE_MAX_CLONES ?= 250000
XS_WOLF_GRHSIM_IR_BITWISE_PREDICATES ?= 1
XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS ?= 1
XS_SIM_DEFINES ?= DIFFTEST
XS_SIM_DEFINES += $(XS_ZERO_INIT_DEFINES)
XS_ROOT_ABS := $(abspath $(XS_ROOT))
XS_NOOP_HOME ?= $(XS_ROOT_ABS)
XS_RTL_BUILD_ABS := $(abspath $(XS_RTL_BUILD))
XS_REF_BUILD_ABS := $(abspath $(XS_REF_BUILD))
XS_GSIM_BUILD_ABS := $(abspath $(XS_GSIM_BUILD))
XS_GSIM_PGO_BUILD_ABS := $(abspath $(XS_GSIM_PGO_BUILD))
XS_WOLF_BUILD_ABS := $(abspath $(XS_WOLF_BUILD))
XS_GRHSIM_BUILD_ABS := $(abspath $(XS_GRHSIM_BUILD))
XS_GRHSIM_IR_BUILD_ABS := $(abspath $(XS_GRHSIM_IR_BUILD))
XS_RTL_DIR_ABS := $(abspath $(XS_RTL_DIR))
XS_VSRC_DIR_ABS := $(abspath $(XS_VSRC_DIR))
XS_WOLF_EMIT_DIR_ABS := $(abspath $(XS_WOLF_EMIT_DIR))
XS_WOLF_EMIT_ABS := $(abspath $(XS_WOLF_EMIT))
XS_WOLF_FILELIST_ABS := $(abspath $(XS_WOLF_FILELIST))
XS_WOLF_HIER_JSON_ABS := $(abspath $(XS_WOLF_HIER_JSON))
XS_WOLF_GRHSIM_EMIT_DIR_ABS := $(abspath $(XS_WOLF_GRHSIM_EMIT_DIR))
XS_WOLF_GRHSIM_POST_STATS_JSON_ABS := $(abspath $(XS_WOLF_GRHSIM_POST_STATS_JSON))
XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON_ABS := $(abspath $(XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON))
XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON_ABS := $(abspath $(XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON))
XS_WOLF_GRHSIM_IR_JSON_ABS := $(abspath $(XS_WOLF_GRHSIM_IR_JSON))
XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON_ABS := $(abspath $(XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON))
XS_SIM_TOP_V := $(XS_RTL_DIR_ABS)/$(XS_SIM_TOP).$(XS_RTL_SUFFIX)
XS_SIM_TOP_FIR := $(XS_RTL_DIR_ABS)/$(XS_SIM_TOP).fir
XS_WOLF_JSON ?= $(XS_WOLF_EMIT_DIR_ABS)/xs_wolf.json
XS_WOLF_GRHSIM_JSON ?= $(XS_WOLF_GRHSIM_EMIT_DIR_ABS)/xs_wolf_grhsim.json
XS_GSIM_SUPERNODE_MAX_SIZE ?= 15
# Keep the default GrhSIM scheduling knobs aligned with full-XiangShan plain coarsen.
XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE ?= 108
XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE ?= 4096
XS_WOLF_GRHSIM_SCHED_BATCH_MAX_OPS ?= 2048
XS_WOLF_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES ?= 8192
XS_WOLF_GRHSIM_SCHED_BATCH_TARGET_COUNT ?= 64
XS_WOLF_GRHSIM_SCHED_BATCHES_PER_CPP ?= 1
XS_WOLF_GRHSIM_EMIT_PARALLELISM ?= 4
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
HDLBITS_GRHSIM_BACKEND ?= legacy
HDLBITS_SIM_BIN_NAME := sim_$(DUT)
HDLBITS_SIM_BIN := $(HDLBITS_OUT_DIR)/$(HDLBITS_SIM_BIN_NAME)
HDLBITS_VERILATOR_PREFIX := Vdut_$(DUT)
HDLBITS_TB_SOURCES := $(wildcard $(HDLBITS_ROOT)/tb/tb_*.cpp)
HDLBITS_DUTS := $(sort $(patsubst tb_%,%,$(basename $(notdir $(HDLBITS_TB_SOURCES)))))
HDLBITS_GRHTB_SOURCES := $(wildcard $(HDLBITS_ROOT)/grhtb/grhtb_*.cpp)
HDLBITS_GRHSIM_DUTS := $(sort $(patsubst grhtb_%,%,$(basename $(notdir $(HDLBITS_GRHTB_SOURCES)))))

.PHONY: all build init_submodule check_id build_fst_roi_discovery test_fst_roi_discovery clean_fst_roi_discovery run_hdlbits_test run_all_hdlbits_tests run_c910_test run_c910_ref_test \
	run_hdlbits_grhsim run_all_hdlbits_grhsim_tests xs_rtl xs_gsim_rtl xs_wolf_filelist xs_wolf_emit xs_wolf_hier_json xs_wolf_grhsim_emit xs_wolf_grhsim_ir xs_ref_emu xs_gsim_emu xs_wolf_emu xs_wolf_grhsim_emu run_xs_json_test \
	run_xs_repcut run_xs_repcut_partitioned_smoke build_xs_repcut_verilator run_xs_repcut_verilator xs_diff_clean run_xs_ref_emu run_xs_gsim_emu run_xs_wolf_emu run_xs_wolf_grhsim_emu run_xs_diff \
	xs_gsim_emu_pgo \
	xs_wolf_grhsim_ir_emu xs_wolf_grhsim_ir_build_emu xs_wolf_grhsim_ir_emu_pgo xs_wolf_grhsim_ir_build_emu_pgo \
	xs_no0076_stats clean

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

$(WOLVRIX_APP): build

.PHONY: test_grhsim_cpu_emit
test_grhsim_cpu_emit:
	mkdir -p $(CURDIR)/ptmp/cpu_emit_test_tmp $(CURDIR)/ptmp/cpu_emit_ccache
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-cpu-emit-tests -j 2
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache WOLVRIX_CPU_EMIT_TEST_OUTPUT=$(CURDIR)/ptmp/cpu_emit_tests ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^grhsim-cpu-emit-tests$$' --output-on-failure

.PHONY: test_grhsim_cpu_schedule
test_grhsim_cpu_schedule:
	mkdir -p $(CURDIR)/ptmp/cpu_emit_test_tmp $(CURDIR)/ptmp/cpu_emit_ccache
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-cpu-schedule-tests -j 2
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^grhsim-cpu-schedule-tests$$' --output-on-failure

.PHONY: test_grhsim_cpu_mapping
test_grhsim_cpu_mapping:
	mkdir -p $(CURDIR)/ptmp/cpu_emit_test_tmp $(CURDIR)/ptmp/cpu_emit_ccache
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-ir-tests grhsim-cpu-mapping-tests -j 2
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^(grhsim-ir-tests|grhsim-cpu-mapping-tests)$$' --output-on-failure

.PHONY: audit_grhsim_cpu_emit
.PHONY: analyze_grhsim_cpu_profile
analyze_grhsim_cpu_profile:
	$(PYTHON) $(CURDIR)/scripts/grhsim_cpu_profile.py --profile "$(GRHSIM_CPU_PROFILE)" --binary "$(GRHSIM_CPU_PROFILE_BINARY)" --model "$(GRHSIM_CPU_PROFILE_MODEL)" --expected-samples "$(GRHSIM_CPU_PROFILE_SAMPLES)" $(if $(GRHSIM_CPU_PROFILE_TOP),--top "$(GRHSIM_CPU_PROFILE_TOP)",)

.PHONY: test_grhsim_cpu_profile
test_grhsim_cpu_profile:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_grhsim_cpu_profile.py

.PHONY: profile_grhsim_ir
profile_grhsim_ir:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/profile_grhsim_ir.py --flow "$(GRHSIM_IR_PROFILE_FLOW)" --output "$(GRHSIM_IR_PROFILE_OUTPUT)" --baseline-seconds "$(GRHSIM_IR_PROFILE_BASELINE_SECONDS)"

.PHONY: reemit_grhsim_ir
GRHSIM_REEMIT_CPU_TARGET_BATCH_COUNT ?= 0
GRHSIM_REEMIT_BRANCH_SHAPE_HOTNESS ?=
GRHSIM_REEMIT_BRANCH_SHAPE_GROWTH_BUDGET ?= 1.0
reemit_grhsim_ir: py_install
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/reemit_grhsim_ir.py --model "$(GRHSIM_REEMIT_MODEL)" --flow "$(GRHSIM_REEMIT_FLOW)" --cpu-target-batch-count "$(GRHSIM_REEMIT_CPU_TARGET_BATCH_COUNT)" $(if $(filter 1,$(GRHSIM_REEMIT_PACK_BIT_REGISTERS)),--pack-bit-registers,) $(if $(filter 1,$(GRHSIM_REEMIT_REMAP)),--remap,) $(if $(filter 1,$(GRHSIM_REEMIT_BITWISE_MUXES)),--bitwise-muxes,) $(if $(filter 1,$(GRHSIM_REEMIT_MUX_CHAIN_FOLD)),--mux-chain-fold,) $(if $(filter 1,$(GRHSIM_REEMIT_USED_BITS)),--used-bits,) $(if $(filter 1,$(GRHSIM_REEMIT_CANONICALIZE_COMPUTE)),--canonicalize-compute,) $(if $(filter 1,$(GRHSIM_REEMIT_DYNAMIC_STATS)),--dynamic-stats,) $(if $(filter 1,$(GRHSIM_REEMIT_COMMIT_COMPACT_WALK)),--commit-compact-walk,) $(if $(filter 1,$(GRHSIM_REEMIT_COMMIT_MEM_WALK)),--commit-mem-walk,) $(if $(filter 1,$(GRHSIM_REEMIT_SHAPE_TWIN_SHARE)),--shape-twin-share,) $(if $(filter 1,$(GRHSIM_REEMIT_BRANCH_SHAPE_SHARE)),--branch-shape-share,) $(if $(strip $(GRHSIM_REEMIT_BRANCH_SHAPE_HOTNESS)),--branch-shape-hotness "$(GRHSIM_REEMIT_BRANCH_SHAPE_HOTNESS)" --branch-shape-growth-budget "$(GRHSIM_REEMIT_BRANCH_SHAPE_GROWTH_BUDGET)",) $(if $(strip $(GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE)),--max-op-in-compute-supernode $(GRHSIM_REEMIT_MAX_OP_IN_COMPUTE_SUPERNODE),)

GRHSIM_IR_BENCH_CPU ?= 2
GRHSIM_IR_BENCH_PAIRS ?= 3
GRHSIM_IR_BENCH_MAKE_TARGET ?= run_xs_wolf_grhsim_ir_emu
GRHSIM_IR_BENCH_BUILD_VAR ?= XS_GRHSIM_IR_BUILD
GRHSIM_IR_BENCH_EMU_RELPATH ?= emu/emu
GRHSIM_IR_BENCH_EXPECTED_ENDPOINT ?= 240349,99996,100001,0x80000c0c
.PHONY: benchmark_grhsim_ir
benchmark_grhsim_ir:
	$(PYTHON) scripts/benchmark_grhsim_ir.py --old "$(GRHSIM_IR_BENCH_OLD)" --new "$(GRHSIM_IR_BENCH_NEW)" \
		--output "$(GRHSIM_IR_BENCH_OUTPUT)" --cpu "$(GRHSIM_IR_BENCH_CPU)" \
		--pairs "$(GRHSIM_IR_BENCH_PAIRS)" --baseline-seconds "$(GRHSIM_IR_BENCH_BASELINE_SECONDS)" \
		--make-target "$(GRHSIM_IR_BENCH_MAKE_TARGET)" --build-var "$(GRHSIM_IR_BENCH_BUILD_VAR)" \
		--emu-relpath "$(GRHSIM_IR_BENCH_EMU_RELPATH)" --expected-endpoint "$(GRHSIM_IR_BENCH_EXPECTED_ENDPOINT)"

.PHONY: test_benchmark_grhsim_ir
test_benchmark_grhsim_ir:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts -p test_benchmark_grhsim_ir.py

.PHONY: analyze_grhsim_localization
analyze_grhsim_localization:
	@$(PYTHON) scripts/grhsim_localization_stats.py --flow "$(GRHSIM_LOCALIZATION_FLOW)" \
		--state-suffix '$(GRHSIM_LOCALIZATION_STATE_SUFFIX)' $(if $(filter 1,$(GRHSIM_LOCALIZATION_DEAD_CONES)),--dead-cones-only,)

# Codegen probe: compile one emitted model translation unit with the production
# compiler/flags into an analysis output directory (assembly or object), for
# micro-experiments on generated-code shape. Never links into an emu.
GRHSIM_PROBE_MODEL ?= $(XS_GRHSIM_IR_BUILD_ABS)/model
GRHSIM_PROBE_MODE ?= asm
.PHONY: probe_grhsim_ir_codegen
probe_grhsim_ir_codegen:
	@test -n "$(GRHSIM_PROBE_SRC)" || { echo "[FAIL] set GRHSIM_PROBE_SRC=<model cpp>"; exit 1; }
	@test -n "$(GRHSIM_PROBE_OUT)" || { echo "[FAIL] set GRHSIM_PROBE_OUT=<output dir>"; exit 1; }
	@mkdir -p "$(GRHSIM_PROBE_OUT)"
	@out="$(GRHSIM_PROBE_OUT)/$$(basename "$(GRHSIM_PROBE_SRC)" .cpp).$(if $(filter asm,$(GRHSIM_PROBE_MODE)),s,o)"; \
	echo "[PROBE] $(CXX) -std=c++20 -O3 -I$(GRHSIM_PROBE_MODEL) $(GRHSIM_PROBE_SRC) -> $$out"; \
	if [ "$(GRHSIM_PROBE_MODE)" = "asm" ]; then \
		$(CXX) -std=c++20 -O3 -I"$(GRHSIM_PROBE_MODEL)" -S "$(GRHSIM_PROBE_SRC)" -o "$$out"; \
	else \
		$(CXX) -std=c++20 -O3 -I"$(GRHSIM_PROBE_MODEL)" -c "$(GRHSIM_PROBE_SRC)" -o "$$out"; \
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

.PHONY: test_grhsim_reg_to_mem inspect_grhsim_reg_to_mem
test_grhsim_reg_to_mem:
	mkdir -p $(CURDIR)/ptmp/cpu_emit_test_tmp $(CURDIR)/ptmp/cpu_emit_ccache
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp $(CMAKE) -S $(WOLVRIX_DIR) -B $(WOLVRIX_BUILD_DIR)
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-reg-to-mem-tests -j 2
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp ctest --test-dir $(WOLVRIX_BUILD_DIR) -R '^grhsim-reg-to-mem-tests$$' --output-on-failure

inspect_grhsim_reg_to_mem: test_grhsim_reg_to_mem
	$(WOLVRIX_BUILD_DIR)/bin/grhsim-reg-to-mem-tests --inspect "$(GRHSIM_AUDIT_MODEL)" "$(GRHSIM_AUDIT_PATTERN)"

.PHONY: analyze_grhsim_reg_to_mem
analyze_grhsim_reg_to_mem: test_grhsim_reg_to_mem
	$(WOLVRIX_BUILD_DIR)/bin/grhsim-reg-to-mem-tests --analyze "$(GRHSIM_AUDIT_MODEL)" "$(GRHSIM_REG_TO_MEM_REPORT)"

.PHONY: rewrite_grhsim_reg_to_mem
rewrite_grhsim_reg_to_mem: test_grhsim_reg_to_mem
	$(WOLVRIX_BUILD_DIR)/bin/grhsim-reg-to-mem-tests --rewrite "$(GRHSIM_AUDIT_MODEL)" "$(GRHSIM_REG_TO_MEM_REPORT)"

.PHONY: summarize_grhsim_reg_to_mem
summarize_grhsim_reg_to_mem: test_grhsim_reg_to_mem
	$(WOLVRIX_BUILD_DIR)/bin/grhsim-reg-to-mem-tests --summarize "$(GRHSIM_AUDIT_MODEL)" > "$(GRHSIM_REG_TO_MEM_REPORT)"

.PHONY: test_grhsim_reg_to_mem_generated
test_grhsim_reg_to_mem_generated: test_grhsim_reg_to_mem
	$(WOLVRIX_BUILD_DIR)/bin/grhsim-reg-to-mem-tests --emit-checks "$(CURDIR)/ptmp/reg_to_mem/generated_checks"
	@for shape in writes reads windows shifted_windows edge_window overlap multi_bit_window multi_bit_shift; do \
		TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp $(MAKE) --no-print-directory -C "$(CURDIR)/ptmp/reg_to_mem/generated_checks/$$shape" \
		-f "$(WOLVRIX_DIR)/tests/grhsim/data/reg_to_mem_generated.mk" -j 2 check \
		CXX="$(CXX)" CXXFLAGS='-std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all' || exit $$?; \
	done

.PHONY: test_grhsim_reg_to_mem_rtl
test_grhsim_reg_to_mem_rtl:
	@mkdir -p "$(CURDIR)/ptmp/reg_to_mem"
	@set -e; rtm_dir=$$(mktemp -d "$(CURDIR)/ptmp/reg_to_mem/rtl.XXXXXX"); \
	$(PYTHON) scripts/test_grhsim_reg_to_mem_rtl.py "$(WOLVRIX_DIR)/tests/grhsim/data/reg_to_mem_tables.sv" "$$rtm_dir"; \
	$(MAKE) --no-print-directory -C "$$rtm_dir/model" -j 2 CXX="$(CXX)" CXXFLAGS='-std=c++20 -O1 -fsanitize=undefined -fno-sanitize-recover=all'; \
	CCACHE_DIR="$(CURDIR)/ptmp/cpu_emit_ccache" $(VERILATOR) --cc --exe --build -j 2 --top-module reg_to_mem_tables --Mdir "$$rtm_dir/verilator" \
	-Wno-fatal --x-initial 0 --x-assign 0 "$(WOLVRIX_DIR)/tests/grhsim/data/reg_to_mem_tables.sv" \
	"$(WOLVRIX_DIR)/tests/grhsim/data/reg_to_mem_tables_main.cpp" \
	-CFLAGS "-std=c++20 -O1 -I$$rtm_dir/model -fsanitize=undefined -fno-sanitize-recover=all" \
	-LDFLAGS "$$rtm_dir/model/libgrhsim_reg_to_mem_tables.a -fsanitize=undefined"; \
	"$$rtm_dir/verilator/Vreg_to_mem_tables"

GRHSIM_REG_TO_MEM_BENCH_CPU ?= 2
GRHSIM_REG_TO_MEM_BENCH_REPETITIONS ?= 2
GRHSIM_REG_TO_MEM_BENCH_OUTPUT ?= $(CURDIR)/ptmp/reg_to_mem/benchmark
GRHSIM_REG_TO_MEM_BENCH_ENABLED ?= $(CURDIR)/ptmp/reg_to_mem/xs_final
GRHSIM_REG_TO_MEM_BENCH_DISABLED ?= $(CURDIR)/ptmp/reg_to_mem/xs_off
GRHSIM_REG_TO_MEM_BUILD_METRICS ?= $(CURDIR)/ptmp/reg_to_mem/build_metrics
.PHONY: measure_grhsim_reg_to_mem_build
measure_grhsim_reg_to_mem_build:
	@test ! -e "$(GRHSIM_REG_TO_MEM_BUILD_METRICS)" || { echo "[FAIL] build metrics directory already exists"; exit 1; }
	@mkdir -p "$(GRHSIM_REG_TO_MEM_BUILD_METRICS)"
	@set -e; for mode in disabled enabled; do \
		source_dir="$(GRHSIM_REG_TO_MEM_BENCH_DISABLED)/model"; \
		if [ "$$mode" = enabled ]; then source_dir="$(GRHSIM_REG_TO_MEM_BENCH_ENABLED)/model"; fi; \
		destination="$(GRHSIM_REG_TO_MEM_BUILD_METRICS)/$$mode"; \
		mkdir -p "$$destination"; \
		cp "$$source_dir"/*.cpp "$$source_dir"/*.hpp "$$source_dir/Makefile" "$$destination/"; \
		echo "[BUILD METRICS] $$mode start"; \
		/usr/bin/time -v -o "$$destination/time.txt" $(MAKE) --no-print-directory -C "$$destination" -j 4 CXX="$(CXX)" \
			> "$$destination/build.log" 2>&1; \
		echo "[BUILD METRICS] $$mode done"; \
	done
.PHONY: benchmark_grhsim_reg_to_mem
benchmark_grhsim_reg_to_mem:
	@test -x "$(GRHSIM_REG_TO_MEM_BENCH_ENABLED)/emu/emu" && test -x "$(GRHSIM_REG_TO_MEM_BENCH_DISABLED)/emu/emu"
	$(PYTHON) scripts/benchmark_grhsim_reg_to_mem.py --enabled "$(GRHSIM_REG_TO_MEM_BENCH_ENABLED)" \
	--disabled "$(GRHSIM_REG_TO_MEM_BENCH_DISABLED)" --output "$(GRHSIM_REG_TO_MEM_BENCH_OUTPUT)" \
	--cpu "$(GRHSIM_REG_TO_MEM_BENCH_CPU)" --repetitions "$(GRHSIM_REG_TO_MEM_BENCH_REPETITIONS)"

audit_grhsim_cpu_emit:
	@test -n "$(GRHSIM_AUDIT_MODEL)" && test -f "$(GRHSIM_AUDIT_MODEL)"
	mkdir -p $(CURDIR)/ptmp/cpu_emit_test_tmp $(CURDIR)/ptmp/cpu_emit_ccache
	TMPDIR=$(CURDIR)/ptmp/cpu_emit_test_tmp CCACHE_DIR=$(CURDIR)/ptmp/cpu_emit_ccache $(CMAKE) --build $(WOLVRIX_BUILD_DIR) --target grhsim-cpu-emit-tests -j 2
	$(WOLVRIX_BUILD_DIR)/bin/grhsim-cpu-emit-tests --audit "$(GRHSIM_AUDIT_MODEL)"

.PHONY: py_install
py_install:
	@echo "[PY] Installing wolvrix into the current Python environment via scikit-build-core"
	@PIP_DISABLE_PIP_VERSION_CHECK=1 $(PIP) install --no-build-isolation $(PIP_CONFIG_SETTINGS) -e $(WOLVRIX_DIR)

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

run_hdlbits_grhsim:
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
		GRHSIM_BACKEND=$(HDLBITS_GRHSIM_BACKEND) \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM) \
		WOLVRIX_GRHSIM_PERF=$(WOLVRIX_GRHSIM_PERF)
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

.PHONY: run_hdlbits_grhsim_ir run_all_hdlbits_grhsim_ir_tests
run_hdlbits_grhsim_ir run_all_hdlbits_grhsim_ir_tests:
	@mkdir -p "$(CURDIR)/ptmp"
	@IR_BUILD_DIR="$$(mktemp -d "$(CURDIR)/ptmp/hdlbits-grhsim-ir-XXXXXX")"; \
	echo "[IR] HDLBits artifacts: $$IR_BUILD_DIR"; \
	$(MAKE) --no-print-directory $(if $(filter run_hdlbits_grhsim_ir,$@),run_hdlbits_grhsim,run_all_hdlbits_grhsim_tests) \
		HDLBITS_GRHSIM_BUILD_DIR="$$IR_BUILD_DIR" HDLBITS_GRHSIM_BACKEND=ir

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

xs_gsim_rtl:
	@echo "[RUN] Generating XiangShan GSIM sim-verilog into $(XS_RTL_BUILD_ABS)..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@mkdir -p "$(XS_ROOT)/build"
	@$(eval LOG_FILE := $(XS_LOG_DIR_ABS)/xs_gsim_simverilog_$(RUN_ID).log)
	@echo "[LOG] Recording GSIM sim-verilog command to: $(LOG_FILE)"
	@printf '' > "$(LOG_FILE)"
	@FORCE_FLAG="$(if $(wildcard $(XS_DIFFTEST_GSIM_EXTMODULE)),,-B)"; \
		echo "[CMD] $(MAKE) $$FORCE_FLAG -C $(XS_ROOT) sim-verilog BUILD_DIR=$(XS_RTL_BUILD_ABS) NUM_CORES=$(XS_NUM_CORES) RTL_SUFFIX=$(XS_RTL_SUFFIX) GSIM=1" | tee -a "$(LOG_FILE)"; \
		NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) $$FORCE_FLAG -C "$(XS_ROOT)" sim-verilog \
			BUILD_DIR="$(XS_RTL_BUILD_ABS)" \
			NUM_CORES="$(XS_NUM_CORES)" \
			RTL_SUFFIX="$(XS_RTL_SUFFIX)" \
			GSIM=1
	@if [ ! -f "$(XS_DIFFTEST_GSIM_EXTMODULE)" ]; then \
		echo "[FAIL] xs gsim sim-verilog: missing generated extmodule $(XS_DIFFTEST_GSIM_EXTMODULE)"; \
		exit 1; \
	fi

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

xs_wolf_hier_json: $(XS_WOLF_FILELIST_ABS) $(XS_WOLF_DEPS)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@mkdir -p "$(XS_WOLF_EMIT_DIR_ABS)"
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(RUN_ID))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_wolf_hier_json_$(RUN_ID).log)
	@$(eval XS_READ_ARGS_FILE := $(XS_WOLF_EMIT_DIR_ABS)/wolvrix_read_args.txt)
	@echo "[LOG] Capturing hierarchical wolf json output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_READ_ARGS_FILE)"
	@printf "%s\n" $(XS_WOLF_INCLUDE_FLAGS) $(XS_WOLF_DEFINE_FLAGS) >> "$(XS_READ_ARGS_FILE)"
	@{ \
		echo "[CMD] $(PYTHON) $(XS_WOLVRIX_HIER_JSON_SCRIPT) $(XS_WOLF_FILELIST_ABS) $(XS_SIM_TOP) $(XS_WOLF_HIER_JSON_ABS) $(XS_READ_ARGS_FILE) $(if $(filter 1,$(XS_WOLF_HIER_JSON_ROUNDTRIP)),--roundtrip,) $(if $(filter 1,$(XS_WOLF_HIER_JSON_SKIP_SAFE_PASSES)),--skip-safe-passes,) --log-level $(WOLF_LOG)"; \
		$(PYTHON) $(XS_WOLVRIX_HIER_JSON_SCRIPT) \
			$(XS_WOLF_FILELIST_ABS) \
			$(XS_SIM_TOP) \
			$(XS_WOLF_HIER_JSON_ABS) \
			$(XS_READ_ARGS_FILE) \
			$(if $(filter 1,$(XS_WOLF_HIER_JSON_ROUNDTRIP)),--roundtrip,) \
			$(if $(filter 1,$(XS_WOLF_HIER_JSON_SKIP_SAFE_PASSES)),--skip-safe-passes,) \
			--log-level $(WOLF_LOG); \
	} 2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"

xs_wolf_grhsim_emit: $(XS_WOLF_FILELIST_ABS) $(XS_WOLF_DEPS)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@rm -rf "$(XS_WOLF_GRHSIM_EMIT_DIR_ABS)"
	@mkdir -p "$(XS_WOLF_GRHSIM_EMIT_DIR_ABS)"
	@mkdir -p "$(dir $(XS_WOLF_GRHSIM_POST_STATS_JSON_ABS))"
	@mkdir -p "$(dir $(XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON_ABS))"
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(RUN_ID))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_wolf_grhsim_build_$(RUN_ID).log)
	@$(eval XS_READ_ARGS_FILE := $(XS_WOLF_GRHSIM_EMIT_DIR_ABS)/wolvrix_read_args.txt)
	@echo "[LOG] Capturing wolf grhsim emit output to: $(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_BUILD_LOG_FILE)"
	@printf '' > "$(XS_READ_ARGS_FILE)"
	@printf "%s\n" $(XS_WOLF_INCLUDE_FLAGS) $(XS_WOLF_DEFINE_FLAGS) >> "$(XS_READ_ARGS_FILE)"
	@set -o pipefail; { \
		echo "[CMD] WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON=$(XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON) WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON=$(XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON_ABS) WOLVRIX_XS_GRHSIM_ENABLE_STATS=$(XS_WOLF_GRHSIM_ENABLE_STATS) WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON=$(XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON) WOLVRIX_XS_GRHSIM_POST_STATS_JSON=$(XS_WOLF_GRHSIM_POST_STATS_JSON_ABS) WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=$(XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE) WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE=$(XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE) WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT=$(XS_WOLF_GRHSIM_SCHED_BATCH_TARGET_COUNT) WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM=$(XS_WOLF_GRHSIM_EMIT_PARALLELISM) $(PYTHON) $(XS_WOLVRIX_GRHSIM_SCRIPT) $(XS_WOLF_FILELIST_ABS) $(XS_SIM_TOP) $(XS_WOLF_GRHSIM_EMIT_DIR_ABS) $(XS_WOLF_GRHSIM_JSON) $(XS_READ_ARGS_FILE) $(WOLF_LOG) --waveform $(if $(filter 1,$(WOLVRIX_GRHSIM_WAVEFORM)),declared-symbols,off) --perf $(if $(filter 1,$(WOLVRIX_GRHSIM_PERF)),eval,off)"; \
		WOLVRIX_XS_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON="$(XS_WOLF_GRHSIM_RESUME_FROM_PRE_REG_TO_MEM_JSON)" \
		WOLVRIX_XS_GRHSIM_PRE_REG_TO_MEM_JSON="$(XS_WOLF_GRHSIM_PRE_REG_TO_MEM_JSON_ABS)" \
		WOLVRIX_XS_GRHSIM_ENABLE_STATS="$(XS_WOLF_GRHSIM_ENABLE_STATS)" \
		WOLVRIX_XS_GRHSIM_RESUME_FROM_STATS_JSON="$(XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON)" \
		WOLVRIX_XS_GRHSIM_POST_STATS_JSON="$(XS_WOLF_GRHSIM_POST_STATS_JSON_ABS)" \
		WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE="$(XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE)" \
		WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE="$(XS_WOLF_GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE)" \
		WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_OPS="$(XS_WOLF_GRHSIM_SCHED_BATCH_MAX_OPS)" \
		WOLVRIX_XS_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES="$(XS_WOLF_GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES)" \
		WOLVRIX_XS_GRHSIM_SCHED_BATCH_TARGET_COUNT="$(XS_WOLF_GRHSIM_SCHED_BATCH_TARGET_COUNT)" \
		WOLVRIX_XS_GRHSIM_SCHED_BATCHES_PER_CPP="$(XS_WOLF_GRHSIM_SCHED_BATCHES_PER_CPP)" \
		WOLVRIX_XS_GRHSIM_EMIT_PARALLELISM="$(XS_WOLF_GRHSIM_EMIT_PARALLELISM)" \
		$(PYTHON) $(XS_WOLVRIX_GRHSIM_SCRIPT) \
			$(XS_WOLF_FILELIST_ABS) \
			$(XS_SIM_TOP) \
			$(XS_WOLF_GRHSIM_EMIT_DIR_ABS) \
			$(XS_WOLF_GRHSIM_JSON) \
			$(XS_READ_ARGS_FILE) \
			$(WOLF_LOG) \
			--waveform $(if $(filter 1,$(WOLVRIX_GRHSIM_WAVEFORM)),declared-symbols,off) \
			--perf $(if $(filter 1,$(WOLVRIX_GRHSIM_PERF)),eval,off); \
	} 2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"; \
	status=$$?; \
	echo "[EXIT] xs_wolf_grhsim_emit $$status" | tee -a "$(XS_BUILD_LOG_FILE)"; \
	exit $$status

xs_wolf_grhsim_ir: $(XS_WOLF_FILELIST_ABS) $(XS_WOLF_DEPS)
	@if [ ! -f "$(XS_DIFFTEST_MACROS)" ]; then \
		$(MAKE) --no-print-directory -B xs_rtl; \
	fi
	@mkdir -p "$(XS_GRHSIM_IR_BUILD_ABS)" "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(RUN_ID))
	@$(eval XS_GRHSIM_IR_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_wolf_grhsim_ir_$(RUN_ID).log)
	@$(eval XS_GRHSIM_IR_READ_ARGS_FILE := $(XS_GRHSIM_IR_BUILD_ABS)/wolvrix_read_args.txt)
	@printf '' > "$(XS_GRHSIM_IR_LOG_FILE)"
	@printf '' > "$(XS_GRHSIM_IR_READ_ARGS_FILE)"
	@printf "%s\n" $(XS_WOLF_INCLUDE_FLAGS) $(XS_WOLF_DEFINE_FLAGS) >> "$(XS_GRHSIM_IR_READ_ARGS_FILE)"
	@echo "[LOG] Capturing GrhSIM IR checkpoint output to: $(XS_GRHSIM_IR_LOG_FILE)"
	@set -o pipefail; { \
		echo "[CMD] $(PYTHON) $(XS_WOLVRIX_GRHSIM_IR_SCRIPT) $(XS_WOLF_FILELIST_ABS) $(XS_SIM_TOP) $(XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON_ABS) $(XS_WOLF_GRHSIM_IR_JSON_ABS) $(XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON_ABS) $(XS_GRHSIM_IR_READ_ARGS_FILE) $(WOLF_LOG) $(if $(strip $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)),--emit-cpp-dir $(abspath $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)),) $(if $(strip $(XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT)),--cpu-target-batch-count $(XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT),)"; \
		$(PYTHON) $(XS_WOLVRIX_GRHSIM_IR_SCRIPT) \
			"$(XS_WOLF_FILELIST_ABS)" \
			"$(XS_SIM_TOP)" \
			"$(XS_WOLF_GRHSIM_IR_FLAT_GRH_JSON_ABS)" \
			"$(XS_WOLF_GRHSIM_IR_JSON_ABS)" \
			"$(XS_WOLF_GRHSIM_IR_ROUNDTRIP_JSON_ABS)" \
			"$(XS_GRHSIM_IR_READ_ARGS_FILE)" \
			"$(WOLF_LOG)" \
			$(if $(filter 1,$(XS_WOLF_GRHSIM_IR_RESUME_FROM_FLAT_GRH_JSON)),--resume-from-flat-grh,) \
			$(if $(filter 1,$(XS_WOLF_GRHSIM_IR_KEEP_ORIGINS)),--keep-origins,) \
			$(if $(filter 0,$(XS_WOLF_GRHSIM_IR_REG_TO_MEM)),--disable-reg-to-mem,) \
			$(if $(filter 0,$(XS_WOLF_GRHSIM_IR_CLONE_SHARED_COMPUTE)),--no-clone-shared-compute,--clone-shared-compute --clone-shared-compute-max-clones $(XS_WOLF_GRHSIM_IR_CLONE_SHARED_COMPUTE_MAX_CLONES)) \
			$(if $(filter 0,$(XS_WOLF_GRHSIM_IR_BITWISE_PREDICATES)),--no-bitwise-predicates,--bitwise-predicates) \
			$(if $(filter 0,$(XS_WOLF_GRHSIM_IR_PACK_BIT_REGISTERS)),--no-pack-bit-registers,--pack-bit-registers) \
			$(if $(strip $(XS_WOLF_GRHSIM_IR_MAX_OP_IN_COMPUTE_SUPERNODE)),--max-op-in-compute-supernode $(XS_WOLF_GRHSIM_IR_MAX_OP_IN_COMPUTE_SUPERNODE),) \
			--reg-to-mem-report "$(XS_WOLF_GRHSIM_IR_REG_TO_MEM_REPORT)" \
			$(if $(strip $(XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT)),--cpu-target-batch-count $(XS_WOLF_GRHSIM_IR_CPU_TARGET_BATCH_COUNT),) \
			$(if $(strip $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)),--emit-cpp-dir "$(abspath $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR))",) \
			$(if $(filter 1,$(XS_WOLF_GRHSIM_IR_SHAPE_TWIN_SHARE)),--shape-twin-share,) \
			$(if $(filter 1,$(XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_SHARE)),--branch-shape-share,) \
			$(if $(strip $(XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_HOTNESS)),--branch-shape-hotness "$(abspath $(XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_HOTNESS))" --branch-shape-growth-budget "$(XS_WOLF_GRHSIM_IR_BRANCH_SHAPE_GROWTH_BUDGET)",) \
			$(if $(strip $(XS_WOLF_GRHSIM_IR_DISABLE_FP_ELISION)),--disable-falling-edge-elision,); \
	} 2>&1 | tee -a "$(XS_GRHSIM_IR_LOG_FILE)"; \
	status=$$?; \
	echo "[EXIT] xs_wolf_grhsim_ir $$status" | tee -a "$(XS_GRHSIM_IR_LOG_FILE)"; \
	exit $$status


.PHONY: xs_wolf_grhsim_ir_emu xs_wolf_grhsim_ir_build_emu
xs_wolf_grhsim_ir_emu: xs_wolf_grhsim_ir
	@$(MAKE) --no-print-directory xs_wolf_grhsim_ir_build_emu

xs_wolf_grhsim_ir_build_emu:
	@test -n "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)" && test -f "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)/Makefile" || { echo "[FAIL] Generate the GrhSIM IR C++ model before build-only emu"; exit 1; }
	@echo "[RUN] Building XiangShan emu with the GrhSIM IR generated model..."
	@NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_IR_BUILD_ABS)/emu \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		VM_BUILD_JOBS=$(if $(VM_BUILD_JOBS),$(VM_BUILD_JOBS),$(XS_VM_BUILD_JOBS)) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(abspath $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)) \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)

# Compiler PGO for the GrhSIM IR emu: three-phase build (instrument, train on the
# production workload with difftest on, profile-use rebuild). Emitted sources are
# untouched; only compile/link flags change. The emu toolchain is clang (difftest
# default), so the flags use LLVM IR PGO: phase 2 writes raw profiles under
# XS_WOLF_GRHSIM_IR_PGO_DIR, llvm-profdata merges them, phase 3 consumes the
# merged .profdata. The PGO dir is wiped on every build, keeping the flow
# self-contained.
XS_WOLF_GRHSIM_IR_PGO_JOBS ?= $(if $(VM_BUILD_JOBS),$(VM_BUILD_JOBS),$(XS_VM_BUILD_JOBS))
XS_WOLF_GRHSIM_IR_PGO_DIR ?= $(XS_GRHSIM_IR_BUILD_ABS)/pgo
LLVM_PROFDATA ?= llvm-profdata

.PHONY: xs_wolf_grhsim_ir_emu_pgo xs_wolf_grhsim_ir_build_emu_pgo
xs_wolf_grhsim_ir_emu_pgo: xs_wolf_grhsim_ir
	@$(MAKE) --no-print-directory xs_wolf_grhsim_ir_build_emu_pgo

xs_wolf_grhsim_ir_build_emu_pgo:
	@test -n "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)" && test -f "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)/Makefile" || { echo "[FAIL] Generate the GrhSIM IR C++ model before PGO emu build"; exit 1; }
	@command -v "$(LLVM_PROFDATA)" >/dev/null || { echo "[FAIL] llvm-profdata not found (set LLVM_PROFDATA)"; exit 1; }
	@echo "[RUN] PGO phase 1/3: instrumented emu build (model + harness)"
	@rm -rf "$(XS_WOLF_GRHSIM_IR_PGO_DIR)" && mkdir -p "$(XS_WOLF_GRHSIM_IR_PGO_DIR)"
	@rm -f "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)"/*.o "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)"/libgrhsim_*.a
	@if [ -d "$(XS_GRHSIM_IR_BUILD_ABS)/emu/grhsim-compile" ]; then \
		find "$(XS_GRHSIM_IR_BUILD_ABS)/emu/grhsim-compile" -name '*.o' -delete; \
		rm -f "$(XS_GRHSIM_IR_BUILD_ABS)/emu/grhsim-compile/emu"; \
	fi
	@NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_IR_BUILD_ABS)/emu \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		VM_BUILD_JOBS=$(XS_WOLF_GRHSIM_IR_PGO_JOBS) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(abspath $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)) \
		GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -fprofile-generate" \
		PGO_CFLAGS="-fprofile-generate" \
		PGO_LDFLAGS="-fprofile-generate" \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)
	@echo "[RUN] PGO phase 2/3: training run (difftest on, production run flags)"
	@cd "$(XS_GRHSIM_IR_BUILD_ABS)/emu" && LLVM_PROFILE_FILE="$(XS_WOLF_GRHSIM_IR_PGO_DIR)/train-%p.profraw" \
		EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
		-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
		--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
		-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
		$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),)
	@echo "[RUN] PGO phase 2/3: merge profiles with $(LLVM_PROFDATA)"
	@"$(LLVM_PROFDATA)" merge -output="$(XS_WOLF_GRHSIM_IR_PGO_DIR)/code.profdata" "$(XS_WOLF_GRHSIM_IR_PGO_DIR)"/*.profraw
	@echo "[RUN] PGO phase 3/3: profile-use rebuild"
	@rm -f "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)"/*.o "$(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)"/libgrhsim_*.a
	@find "$(XS_GRHSIM_IR_BUILD_ABS)/emu/grhsim-compile" -name '*.o' -delete
	@rm -f "$(XS_GRHSIM_IR_BUILD_ABS)/emu/grhsim-compile/emu"
	@NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_IR_BUILD_ABS)/emu \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		VM_BUILD_JOBS=$(XS_WOLF_GRHSIM_IR_PGO_JOBS) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(abspath $(XS_WOLF_GRHSIM_IR_EMIT_CPP_DIR)) \
		GRHSIM_MODEL_CXXFLAGS="-std=c++20 -O3 -fprofile-use=$(XS_WOLF_GRHSIM_IR_PGO_DIR)/code.profdata" \
		PGO_CFLAGS="-fprofile-use=$(XS_WOLF_GRHSIM_IR_PGO_DIR)/code.profdata" \
		PGO_LDFLAGS="-fprofile-use=$(XS_WOLF_GRHSIM_IR_PGO_DIR)/code.profdata" \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)

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
	@echo "[RUN] xs repcut"
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
	@echo "[RUN] Installing Wolvrix for XiangShan repcut emu via scikit-build-core..."
	@$(MAKE) --no-print-directory py_install
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
# flow is LLVM IR PGO; PGO_BOLT=0 keeps the technique matched with the GrhSIM IR
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

xs_wolf_grhsim_emu: xs_wolf_grhsim_emit
	@echo "[RUN] Building XiangShan wolf grhsim emu..."
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@$(eval XS_BUILD_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_wolf_grhsim_build_$(RUN_ID).log)
	@echo "[LOG] Capturing build output to: $(XS_BUILD_LOG_FILE)"
	@printf '' >> "$(XS_BUILD_LOG_FILE)"
	@echo "[CMD] NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu BUILD_DIR=$(XS_GRHSIM_BUILD_ABS) GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) NUM_CORES=$(XS_NUM_CORES) WITH_CHISELDB=$(XS_WITH_CHISELDB) WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) GRHSIM=1 GRHSIM_MODEL_DIR=$(XS_WOLF_GRHSIM_EMIT_DIR_ABS) WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM)" | tee -a "$(XS_BUILD_LOG_FILE)"
	NOOP_HOME=$(XS_NOOP_HOME) $(MAKE) -C $(XS_ROOT)/difftest emu \
		BUILD_DIR=$(XS_GRHSIM_BUILD_ABS) \
		GEN_CSRC_DIR=$(XS_DIFFTEST_GEN_DIR_ABS) \
		NUM_CORES=$(XS_NUM_CORES) \
		WITH_CHISELDB=$(XS_WITH_CHISELDB) \
		WITH_CONSTANTIN=$(XS_WITH_CONSTANTIN) \
		GRHSIM=1 \
		GRHSIM_MODEL_DIR=$(XS_WOLF_GRHSIM_EMIT_DIR_ABS) \
		WOLVRIX_GRHSIM_WAVEFORM=$(WOLVRIX_GRHSIM_WAVEFORM) \
		2>&1 | tee -a "$(XS_BUILD_LOG_FILE)"

xs_diff_clean:
	rm -rf "$(XS_REF_BUILD_ABS)/verilator-compile" \
		"$(XS_GSIM_BUILD_ABS)/gsim-compile" \
		"$(XS_WOLF_BUILD_ABS)/verilator-compile" \
		"$(XS_GRHSIM_BUILD_ABS)/grhsim-compile" \
		"$(XS_WOLF_EMIT_DIR_ABS)" \
		"$(XS_WOLF_GRHSIM_EMIT_DIR_ABS)" \
		"$(XS_WOLF_GRHSIM_POST_STATS_JSON_ABS)" \
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

run_xs_gsim_emu:
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
		echo "[CMD] cd $(XS_GSIM_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,)"; \
		cd $(XS_GSIM_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
			-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
			--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
			-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) \
			2>&1 | tee "$$GSIM_LOG"

xs_no0076_stats:
	@$(eval RUN_ID := $(if $(RUN_ID),$(RUN_ID),$(shell date +%Y%m%d_%H%M%S)))
	@echo "[RUN] NO0076 fixed-parameter stats chain"
	@$(MAKE) --no-print-directory xs_gsim_rtl RUN_ID="$(RUN_ID)"
	@$(MAKE) --no-print-directory xs_wolf_grhsim_emit \
		RUN_ID="$(RUN_ID)" \
		XS_WOLF_GRHSIM_ENABLE_STATS=1 \
		XS_WOLF_GRHSIM_RESUME_FROM_STATS_JSON=0 \
		XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE=$(XS_WOLF_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE)
	@if [ ! -x "$(XS_GSIM_BIN)" ] && [ -f "$(REF_GSIM_ROOT)/Makefile" ]; then \
		echo "[RUN] Building reference gsim..."; \
		$(MAKE) --no-print-directory -C "$(REF_GSIM_ROOT)" build-gsim; \
	fi
	@mkdir -p "$(XS_LOG_DIR_ABS)"
	@$(eval XS_NO0076_LOG_FILE := $(XS_LOG_DIR_ABS)/xs_no0076_stats_$(RUN_ID).log)
	@echo "[LOG] Capturing NO0076 stats output to: $(XS_NO0076_LOG_FILE)"
	@printf '' > "$(XS_NO0076_LOG_FILE)"
	@echo "[RUN] Regenerating gsim stats json" | tee -a "$(XS_NO0076_LOG_FILE)"
	@echo "[CMD] $(XS_GSIM_BIN) --supernode-max-size=$(XS_GSIM_SUPERNODE_MAX_SIZE) --cpp-max-size-KB=8192 --sep-mod=__DOT__ --sep-aggr=__DOT__ --dump-stats-json --dump-stages=Final --dir $(XS_GSIM_BUILD_ABS)/gsim-compile/model $(XS_SIM_TOP_FIR)" | tee -a "$(XS_NO0076_LOG_FILE)"
	@set -o pipefail; $(XS_GSIM_BIN) \
		--supernode-max-size=$(XS_GSIM_SUPERNODE_MAX_SIZE) \
		--cpp-max-size-KB=8192 \
		--sep-mod=__DOT__ \
		--sep-aggr=__DOT__ \
		--dump-stats-json \
		--dump-stages=Final \
		--dir "$(XS_GSIM_BUILD_ABS)/gsim-compile/model" \
		"$(XS_SIM_TOP_FIR)" \
		2>&1 | tee -a "$(XS_NO0076_LOG_FILE)"
	@echo "[RUN] Summarizing NO0076 aligned stats" | tee -a "$(XS_NO0076_LOG_FILE)"
	@echo "[CMD] $(PYTHON) $(CURDIR)/scripts/xs_no0076_stats.py --gsim-stats $(XS_GSIM_BUILD_ABS)/gsim-compile/model/$(XS_SIM_TOP)_supernode_stats.json --grhsim-supernode-stats $(XS_WOLF_GRHSIM_EMIT_DIR_ABS)/activity_schedule_supernode_stats.json --grhsim-post-summary $(XS_WOLF_GRHSIM_EMIT_DIR_ABS)/wolvrix_xs_post_stats_summary.json --grhsim-post-stats $(XS_WOLF_GRHSIM_POST_STATS_JSON_ABS) --grhsim-log $(XS_LOG_DIR_ABS)/xs_wolf_grhsim_build_$(RUN_ID).log --top $(XS_SIM_TOP) --out $(XS_GRHSIM_BUILD_ABS)/no0076_stats_summary.json" | tee -a "$(XS_NO0076_LOG_FILE)"
	@$(PYTHON) $(CURDIR)/scripts/xs_no0076_stats.py \
		--gsim-stats "$(XS_GSIM_BUILD_ABS)/gsim-compile/model/$(XS_SIM_TOP)_supernode_stats.json" \
		--grhsim-supernode-stats "$(XS_WOLF_GRHSIM_EMIT_DIR_ABS)/activity_schedule_supernode_stats.json" \
		--grhsim-post-summary "$(XS_WOLF_GRHSIM_EMIT_DIR_ABS)/wolvrix_xs_post_stats_summary.json" \
		--grhsim-post-stats "$(XS_WOLF_GRHSIM_POST_STATS_JSON_ABS)" \
		--grhsim-log "$(XS_LOG_DIR_ABS)/xs_wolf_grhsim_build_$(RUN_ID).log" \
		--top "$(XS_SIM_TOP)" \
		--out "$(XS_GRHSIM_BUILD_ABS)/no0076_stats_summary.json" \
		| tee -a "$(XS_NO0076_LOG_FILE)"

run_xs_wolf_emu:
	@RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	mkdir -p "$$LOG_DIR"; \
	WOLF_LOG="$$LOG_DIR/xs_wolf_$${RUN_ID}.log"; \
	WOLF_WAVEFORM="$(XS_WAVEFORM_DIR_ABS)/xs_wolf_$${RUN_ID}.fst"; \
	printf '' > "$$WOLF_LOG"; \
	echo "[RUN] xs wolf emu"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL) XS_COMMIT_TRACE=$(XS_COMMIT_TRACE) XS_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) XS_LOG_BEGIN=$(XS_LOG_BEGIN) XS_LOG_END=$(XS_LOG_END)"; \
		echo "[LOG] wolf: $$WOLF_LOG"; \
		if [ "$(XS_WAVEFORM)" = "1" ]; then \
			echo "[WAVEFORM] wolf: $$WOLF_WAVEFORM"; \
		fi; \
		echo "[CMD] cd $(XS_WOLF_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) $(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$WOLF_WAVEFORM,)"; \
		cd $(XS_WOLF_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
			-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
			--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
			-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) \
			$(if $(filter 1,$(XS_WAVEFORM)),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$WOLF_WAVEFORM,) \
			2>&1 | tee "$$WOLF_LOG"

.PHONY: run_xs_wolf_grhsim_ir_emu
run_xs_wolf_grhsim_ir_emu:
	@test -x "$(XS_GRHSIM_IR_BUILD_ABS)/emu/emu" || { echo "[FAIL] Build the GrhSIM IR emu before running"; exit 1; }
	@$(MAKE) --no-print-directory run_xs_wolf_grhsim_emu XS_GRHSIM_BUILD="$(XS_GRHSIM_IR_BUILD_ABS)/emu"

run_xs_wolf_grhsim_emu:
	@if { [ "$(XS_WAVEFORM)" != "0" ] || [ -n "$(XS_WAVEFORM_PATH)" ]; } && [ "$(WOLVRIX_GRHSIM_WAVEFORM)" != "1" ]; then \
		echo "[FAIL] xs wolf grhsim: runtime waveform requested, but model was emitted without waveform support; rebuild with WOLVRIX_GRHSIM_WAVEFORM=1"; \
		exit 1; \
	fi
	@set -o pipefail; \
	RUN_ID="$(if $(RUN_ID),$(RUN_ID),$$(date +%Y%m%d_%H%M%S))"; \
	LOG_DIR="$(XS_LOG_DIR_ABS)"; \
	GRHSIM_LOG="$$LOG_DIR/xs_wolf_grhsim_$${RUN_ID}.log"; \
	GRHSIM_WAVEFORM="$(if $(XS_WAVEFORM_PATH_ABS),$(XS_WAVEFORM_PATH_ABS),$(XS_WAVEFORM_DIR_ABS)/xs_wolf_grhsim_$${RUN_ID}.fst)"; \
	mkdir -p "$$LOG_DIR" "$$(dirname "$$GRHSIM_WAVEFORM")"; \
	printf '' > "$$GRHSIM_LOG"; \
	echo "[RUN] xs wolf grhsim emu"; \
		echo "[RUN] XS_SIM_MAX_CYCLE=$(XS_SIM_MAX_CYCLE) XS_WAVEFORM=$(XS_WAVEFORM) XS_WAVEFORM_FULL=$(XS_WAVEFORM_FULL) XS_COMMIT_TRACE=$(XS_COMMIT_TRACE) XS_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) XS_LOG_BEGIN=$(XS_LOG_BEGIN) XS_LOG_END=$(XS_LOG_END) XS_WAVEFORM_PATH=$(if $(XS_WAVEFORM_PATH_ABS),$(XS_WAVEFORM_PATH_ABS),)"; \
		echo "[LOG] wolf grhsim: $$GRHSIM_LOG"; \
		if [ "$(XS_WAVEFORM)" = "1" ] || [ -n "$(XS_WAVEFORM_PATH)" ]; then \
			echo "[WAVEFORM] wolf grhsim: $$GRHSIM_WAVEFORM"; \
		fi; \
		echo "[CMD] cd $(XS_GRHSIM_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES=$(XS_PROGRESS_EVERY_CYCLES) $(XS_EMU_PREFIX) ./emu -i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin --diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so -b $(XS_LOG_BEGIN) -e $(XS_LOG_END) $(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) $(XS_RAM_TRACE_ARGS) $(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) $(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$GRHSIM_WAVEFORM,)"; \
		cd $(XS_GRHSIM_BUILD_ABS) && EMU_PROGRESS_EVERY_CYCLES="$(XS_PROGRESS_EVERY_CYCLES)" $(XS_EMU_PREFIX) ./emu \
			-i $(XS_ROOT_ABS)/ready-to-run/coremark-2-iteration.bin \
			--diff $(XS_ROOT_ABS)/ready-to-run/riscv64-nemu-interpreter-so \
			-b $(XS_LOG_BEGIN) -e $(XS_LOG_END) \
			$(if $(filter-out 0,$(XS_SIM_MAX_CYCLE)),-C $(XS_SIM_MAX_CYCLE),) \
			$(XS_RAM_TRACE_ARGS) \
			$(if $(filter 1,$(XS_COMMIT_TRACE)),--dump-commit-trace,) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),$(if $(filter 1,$(XS_WAVEFORM_FULL)),--dump-wave-full,--dump-wave),) \
			$(if $(filter 1,$(XS_WAVEFORM))$(XS_WAVEFORM_PATH),--wave-path $$GRHSIM_WAVEFORM,) \
		2>&1 | tee "$$GRHSIM_LOG"

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
