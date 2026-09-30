ROOT := $(abspath ../../..)

CASE_ID := 004
CASE_TAG := CASE_$(CASE_ID)

DUT_TOP := ExprCastBug
TB_TOP := xs_bugcase_tb

CASE_DIR := $(CURDIR)
FILELIST := $(CASE_DIR)/filelist.f
TB_V := $(CASE_DIR)/tb.v
TB_CPP := $(CASE_DIR)/tb.cpp

OUT_DIR_BASE := $(ROOT)/build/xs_bugcase/$(CASE_TAG)
REF_DIR := $(OUT_DIR_BASE)/ref
GRHSIM_DIR := $(OUT_DIR_BASE)/grhsim
WOLF_DIR := $(OUT_DIR_BASE)/wolf
export CCACHE_DIR := $(OUT_DIR_BASE)/ccache

PYTHON ?= python3
WOLVRIX_PY ?= $(PYTHON)
PIP ?= $(PYTHON) -m pip
WOLVRIX_XS_GRHSIM_SCRIPT := $(ROOT)/scripts/wolvrix_xs_grhsim_ir.py
GRHSIM_LOG ?= info
WOLVRIX_XS_SCRIPT := $(ROOT)/scripts/wolvrix_xs_emit.py
WOLF_SV := $(WOLF_DIR)/wolf_emit.sv
WOLF_JSON := $(WOLF_DIR)/grh.json
WOLF_READ_ARGS := $(WOLF_DIR)/wolvrix_read_args.txt
WOLF_LOG ?= info

VERILATOR ?= $(or $(shell echo $$VERILATOR),verilator)
VERILATOR_COVERAGE ?= verilator_coverage
VERILATOR_ROOT := $(or $(shell echo $$VERILATOR_ROOT),$(shell $(VERILATOR) -V 2>/dev/null | awk -F'= *' '/VERILATOR_ROOT/ {gsub(/^ +| +$$/, "", $$2); value=$$2} END {print value}'))
VERILATOR_COV_SRC = $(if $(filter 1,$(COVERAGE)),$(VERILATOR_ROOT)/include/verilated_cov.cpp,)

COVERAGE ?= 0
COV_MIN ?= 90
COV_DATA := $(OUT_DIR_BASE)/coverage.dat
COV_INFO := $(OUT_DIR_BASE)/coverage.info
COV_CHECK := $(CASE_DIR)/coverage_check.py

BASE_FLAGS := --no-timing -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL \
	-Wno-UNDRIVEN -Wno-SYNCASYNCNET -Wno-PINCONNECTEMPTY -Wno-ASSIGNDLY -Wno-MULTIDRIVEN
REF_FLAGS := $(BASE_FLAGS) $(if $(filter 1,$(COVERAGE)),--coverage,)
REF_PREFIX := VRef
WOLF_PREFIX := VWolf
REF_LIB := $(REF_DIR)/$(REF_PREFIX)__ALL.a
WOLF_LIB := $(WOLF_DIR)/$(WOLF_PREFIX)__ALL.a
GRHSIM_LIB := $(GRHSIM_DIR)/libgrhsim_$(TB_TOP).a
GRHSIM_HDR := $(GRHSIM_DIR)/grhsim_$(TB_TOP).hpp

BIN := $(OUT_DIR_BASE)/sim_$(CASE_TAG)_grhsim
SV_BIN := $(OUT_DIR_BASE)/sim_$(CASE_TAG)
GRHSIM_TB_CPP := $(CASE_DIR)/grhsim_tb.cpp

CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall
GRHSIM_CXX := clang++
GRHSIM_CXXFLAGS ?= -O2 -std=c++20 -Wall
LDLIBS ?= -pthread

.PHONY: run run_grhsim build_ref build_wolf build_grhsim grhsim_force clean install_wolvrix

install_wolvrix:
	@PIP_DISABLE_PIP_VERSION_CHECK=1 $(PIP) install --no-build-isolation $(PIP_CONFIG_SETTINGS) -e $(ROOT)/wolvrix

build_ref: $(REF_LIB)

build_grhsim: $(GRHSIM_LIB)

run_grhsim: $(BIN)
	@if [ "$(COVERAGE)" = "1" ] && ! command -v $(VERILATOR_COVERAGE) >/dev/null 2>&1; then \
		echo "[$(CASE_TAG)] verilator_coverage not found in PATH"; exit 1; \
	fi
	@echo "[RUN] ./$(BIN)"
	@mkdir -p $(OUT_DIR_BASE)
	@cd $(OUT_DIR_BASE) && VERILATOR_COV_FILE=$(COV_DATA) ./$(notdir $(BIN))
	@if [ "$(COVERAGE)" = "1" ]; then \
		$(VERILATOR_COVERAGE) --write-info $(COV_INFO) $(COV_DATA); \
		python3 $(COV_CHECK) $(COV_INFO) $(COV_MIN); \
	fi

run: $(SV_BIN)
	@if [ "$(COVERAGE)" = "1" ] && ! command -v $(VERILATOR_COVERAGE) >/dev/null 2>&1; then \
		echo "[$(CASE_TAG)] verilator_coverage not found in PATH"; exit 1; \
	fi
	@echo "[RUN] ./$(SV_BIN)"
	@cd $(OUT_DIR_BASE) && VERILATOR_COV_FILE=$(COV_DATA) ./$(notdir $(SV_BIN))
	@if [ "$(COVERAGE)" = "1" ]; then \
		$(VERILATOR_COVERAGE) --write-info $(COV_INFO) $(COV_DATA); \
		python3 $(COV_CHECK) $(COV_INFO) $(COV_MIN); \
	fi

build_wolf: $(WOLF_LIB)

$(WOLF_SV): $(FILELIST)
	@mkdir -p $(WOLF_DIR)
	@printf "" > $(WOLF_READ_ARGS)
	@$(WOLVRIX_PY) $(WOLVRIX_XS_SCRIPT) $(FILELIST) $(DUT_TOP) $(WOLF_SV) $(WOLF_JSON) $(WOLF_READ_ARGS) $(WOLF_LOG)

$(REF_LIB): $(TB_V) $(FILELIST)
	@if ! command -v $(VERILATOR) >/dev/null 2>&1; then \
		echo "[$(CASE_TAG)] verilator not found in PATH"; \
		exit 1; \
	fi
	@mkdir -p $(REF_DIR) $(CCACHE_DIR)
	@$(VERILATOR) $(REF_FLAGS) --cc $(TB_V) -f $(FILELIST) \
		--top-module $(TB_TOP) --prefix $(REF_PREFIX) -Mdir $(REF_DIR)
	@$(MAKE) -C $(REF_DIR) -f $(REF_PREFIX).mk $(REF_PREFIX)__ALL.a

$(WOLF_LIB): $(TB_V) $(WOLF_SV)
	@mkdir -p $(WOLF_DIR)
	@$(VERILATOR) $(BASE_FLAGS) --cc $(TB_V) $(WOLF_SV) \
		--top-module $(TB_TOP) --prefix $(WOLF_PREFIX) -Mdir $(WOLF_DIR)
	@$(MAKE) -C $(WOLF_DIR) -f $(WOLF_PREFIX).mk $(WOLF_PREFIX)__ALL.a

$(GRHSIM_LIB): grhsim_force $(TB_V) $(FILELIST)
	@rm -rf "$(GRHSIM_DIR)" && mkdir -p "$(GRHSIM_DIR)"
	@printf "%s\n" "$(TB_V)" > $(OUT_DIR_BASE)/wolvrix_read_args.txt
	@$(WOLVRIX_PY) $(WOLVRIX_XS_GRHSIM_SCRIPT) $(FILELIST) $(TB_TOP) $(OUT_DIR_BASE)/flat_grh.json $(OUT_DIR_BASE)/grhsim_ir.json $(OUT_DIR_BASE)/grhsim_ir_roundtrip.json $(OUT_DIR_BASE)/wolvrix_read_args.txt $(GRHSIM_LOG) --emit-cpp-dir "$(GRHSIM_DIR)"
	@test -f $(GRHSIM_HDR)
	@$(MAKE) -C $(GRHSIM_DIR) CXX=$(GRHSIM_CXX) CXXFLAGS="$(GRHSIM_CXXFLAGS)"
	@test -f $(GRHSIM_LIB)

$(BIN): $(REF_LIB) $(GRHSIM_LIB) $(GRHSIM_TB_CPP)
	@if [ -z "$(VERILATOR_ROOT)" ]; then \
		echo "[$(CASE_TAG)] VERILATOR_ROOT not found; set VERILATOR_ROOT=/path/to/verilator"; \
		exit 1; \
	fi
	@mkdir -p $(OUT_DIR_BASE)
	@$(GRHSIM_CXX) $(GRHSIM_CXXFLAGS) -I$(REF_DIR) -I$(GRHSIM_DIR) \
		-I$(VERILATOR_ROOT)/include -I$(VERILATOR_ROOT)/include/vltstd \
		$(GRHSIM_TB_CPP) $(REF_LIB) $(GRHSIM_LIB) \
		$(VERILATOR_ROOT)/include/verilated.cpp \
		$(VERILATOR_ROOT)/include/verilated_dpi.cpp \
		$(VERILATOR_ROOT)/include/verilated_threads.cpp \
		$(VERILATOR_COV_SRC) \
		-o $(BIN) $(LDLIBS)

$(SV_BIN): $(REF_LIB) $(WOLF_LIB) $(TB_CPP)
	@$(CXX) $(CXXFLAGS) -I$(REF_DIR) -I$(WOLF_DIR) \
		-I$(VERILATOR_ROOT)/include -I$(VERILATOR_ROOT)/include/vltstd \
		$(TB_CPP) $(REF_LIB) $(WOLF_LIB) \
		$(VERILATOR_ROOT)/include/verilated.cpp \
		$(VERILATOR_ROOT)/include/verilated_threads.cpp \
		$(VERILATOR_COV_SRC) \
		-o $(SV_BIN) $(LDLIBS)

clean:
	@rm -rf $(OUT_DIR_BASE)
