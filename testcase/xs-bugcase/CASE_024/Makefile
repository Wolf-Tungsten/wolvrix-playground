ROOT := $(abspath ../../..)

CASE_ID := 024
CASE_TAG := CASE_$(CASE_ID)

DUT_TOP := ICacheWayLookup
TB_TOP := xs_bugcase_tb

CASE_DIR := $(CURDIR)
FILELIST := $(CASE_DIR)/filelist.f
TB_V := $(CASE_DIR)/tb.v
TB_CPP := $(CASE_DIR)/tb.cpp

OUT_DIR_BASE := $(ROOT)/build/xs_bugcase/$(CASE_TAG)
REF_DIR := $(OUT_DIR_BASE)/ref
GRHSIM_DIR := $(OUT_DIR_BASE)/grhsim

export CCACHE_DIR := $(OUT_DIR_BASE)/ccache

PYTHON ?= python3
WOLVRIX_PY ?= $(PYTHON)
PIP ?= $(PYTHON) -m pip
WOLVRIX_XS_GRHSIM_SCRIPT := $(ROOT)/scripts/wolvrix_xs_grhsim.py
GRHSIM_JSON := $(GRHSIM_DIR)/grh.json
GRHSIM_READ_ARGS := $(GRHSIM_DIR)/wolvrix_read_args.txt
GRHSIM_LOG ?= info

VERILATOR ?= $(or $(shell echo $$VERILATOR),verilator)
VERILATOR_ROOT := $(or $(shell echo $$VERILATOR_ROOT),$(shell $(VERILATOR) -V 2>/dev/null | awk -F'= *' '/VERILATOR_ROOT/ {gsub(/^ +| +$$/, "", $$2); value=$$2} END {print value}'))

BASE_FLAGS := --no-timing -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL \
	-Wno-UNDRIVEN -Wno-SYNCASYNCNET -Wno-PINCONNECTEMPTY -Wno-ASSIGNDLY -Wno-MULTIDRIVEN \
	-Wno-WIDTH -Wno-SELRANGE

SIM_DEFINES ?= DIFFTEST RANDOMIZE_REG_INIT RANDOMIZE_MEM_INIT RANDOMIZE_DELAY=0 RANDOM=32'h0
SIM_VFLAGS ?= $(foreach d,$(SIM_DEFINES),+define+$(d))
SIM_VFLAGS := $(subst 32'h0,32\'h0,$(SIM_VFLAGS))
EXTRA_VFLAGS ?=
REF_FLAGS := $(BASE_FLAGS) $(SIM_VFLAGS) $(EXTRA_VFLAGS)

REF_PREFIX := VRef
REF_LIB := $(REF_DIR)/$(REF_PREFIX)__ALL.a
GRHSIM_LIB := $(GRHSIM_DIR)/libgrhsim_$(TB_TOP).a
GRHSIM_HDR := $(GRHSIM_DIR)/grhsim_$(TB_TOP).hpp

BIN := $(OUT_DIR_BASE)/sim_$(CASE_TAG)

CXX := clang++
CXXFLAGS ?= -O2 -std=c++20 -Wall
LDLIBS ?= -pthread

.PHONY: run build_ref build_grhsim clean install_wolvrix

install_wolvrix:
	@PIP_DISABLE_PIP_VERSION_CHECK=1 $(PIP) install --no-build-isolation $(PIP_CONFIG_SETTINGS) -e $(ROOT)/wolvrix

run: clean $(BIN)
	@echo "[RUN] ./$(BIN)"
	@mkdir -p $(OUT_DIR_BASE)
	@cd $(OUT_DIR_BASE) && ./$(notdir $(BIN))

$(REF_LIB): $(TB_V) $(FILELIST)
	@if ! command -v $(VERILATOR) >/dev/null 2>&1; then \
		echo "[$(CASE_TAG)] verilator not found in PATH"; \
		exit 1; \
	fi
	@mkdir -p $(CCACHE_DIR)
	@mkdir -p $(REF_DIR)
	@$(VERILATOR) $(REF_FLAGS) --cc $(TB_V) -f $(FILELIST) \
		--top-module $(TB_TOP) --prefix $(REF_PREFIX) -Mdir $(REF_DIR)
	@$(MAKE) -C $(REF_DIR) -f $(REF_PREFIX).mk $(REF_PREFIX)__ALL.a

$(GRHSIM_LIB): $(TB_V) $(FILELIST)
	@mkdir -p $(CCACHE_DIR)
	@mkdir -p $(GRHSIM_DIR)
	@printf "%s\n" "$(TB_V)" > $(GRHSIM_READ_ARGS)
	@$(WOLVRIX_PY) $(WOLVRIX_XS_GRHSIM_SCRIPT) $(FILELIST) $(TB_TOP) $(GRHSIM_DIR) $(GRHSIM_JSON) $(GRHSIM_READ_ARGS) $(GRHSIM_LOG)
	@test -f $(GRHSIM_HDR)
	@$(MAKE) -C $(GRHSIM_DIR) CXX=$(CXX) CXXFLAGS="$(CXXFLAGS)"
	@test -f $(GRHSIM_LIB)

$(BIN): $(REF_LIB) $(GRHSIM_LIB) $(TB_CPP)
	@if [ -z "$(VERILATOR_ROOT)" ]; then \
		echo "[$(CASE_TAG)] VERILATOR_ROOT not found; set VERILATOR_ROOT=/path/to/verilator"; \
		exit 1; \
	fi
	@mkdir -p $(OUT_DIR_BASE)
	@$(CXX) $(CXXFLAGS) -I$(REF_DIR) -I$(GRHSIM_DIR) \
		-I$(VERILATOR_ROOT)/include -I$(VERILATOR_ROOT)/include/vltstd \
		$(TB_CPP) $(REF_LIB) $(GRHSIM_LIB) \
		$(VERILATOR_ROOT)/include/verilated.cpp \
		$(VERILATOR_ROOT)/include/verilated_dpi.cpp \
		$(VERILATOR_ROOT)/include/verilated_threads.cpp \
		-o $(BIN) $(LDLIBS)

clean:
	@rm -rf $(OUT_DIR_BASE)
