ROOT := $(abspath ../../..)

CASE_ID := 006
CASE_TAG := CASE_$(CASE_ID)

DUT_TOP := Mem1R1WHelperCase006
TB_TOP := xs_bugcase_tb

CASE_DIR := $(CURDIR)
FILELIST := $(CASE_DIR)/filelist.f
TB_V := $(CASE_DIR)/tb.v
TB_CPP := $(CASE_DIR)/tb.cpp

OUT_DIR_BASE := $(ROOT)/build/xs_bugcase/$(CASE_TAG)
REF_DIR := $(OUT_DIR_BASE)/ref
WOLF_DIR := $(OUT_DIR_BASE)/wolf

PYTHON ?= python3
WOLVRIX_PYBIND := $(ROOT)/wolvrix/app/pybind
WOLVRIX_PY ?= PYTHONPATH=$(WOLVRIX_PYBIND)$(if $(PYTHONPATH),:$(PYTHONPATH),) $(PYTHON)
WOLVRIX_XS_SCRIPT := $(ROOT)/scripts/wolvrix_xs_emit.py
WOLF_SV := $(WOLF_DIR)/wolf_emit.sv
WOLF_JSON := $(WOLF_DIR)/grh.json
WOLF_READ_ARGS := $(WOLF_DIR)/wolvrix_read_args.txt
WOLF_LOG ?= warn

VERILATOR ?= $(or $(shell echo $$VERILATOR),verilator)
VERILATOR_COVERAGE ?= verilator_coverage
VERILATOR_ROOT ?= $(shell $(VERILATOR) -V 2>/dev/null | awk -F'= *' '/^VERILATOR_ROOT/ {print $$2}')
VERILATOR_COV_SRC = $(if $(filter 1,$(COVERAGE)),$(VERILATOR_ROOT)/include/verilated_cov.cpp,)
VERILATOR_TRACE_SRC = $(if $(filter 1,$(TRACE)),$(VERILATOR_ROOT)/include/verilated_fst_c.cpp,)

COVERAGE ?= 0

BASE_FLAGS := --no-timing -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL \
	-Wno-UNDRIVEN -Wno-SYNCASYNCNET -Wno-PINCONNECTEMPTY -Wno-ASSIGNDLY -Wno-MULTIDRIVEN

SIM_DEFINES ?= DIFFTEST RANDOMIZE_REG_INIT RANDOMIZE_MEM_INIT RANDOMIZE_DELAY=0 RANDOM=32'h0
SIM_VFLAGS ?= $(foreach d,$(SIM_DEFINES),+define+$(d))
SIM_VFLAGS := $(subst 32'h0,32\'h0,$(SIM_VFLAGS))
EXTRA_VFLAGS ?=

TRACE_FLAGS := $(if $(filter 1,$(TRACE)),--trace-fst --trace-structs,)
REF_FLAGS := $(BASE_FLAGS) $(if $(filter 1,$(COVERAGE)),--coverage,) $(SIM_VFLAGS) $(EXTRA_VFLAGS) $(TRACE_FLAGS)
WOLF_FLAGS := $(BASE_FLAGS) $(SIM_VFLAGS) $(EXTRA_VFLAGS) $(TRACE_FLAGS)
WOLF_DEFINE_FLAGS := $(foreach d,$(SIM_DEFINES),-D "$(d)")

REF_PREFIX := VRef
WOLF_PREFIX := VWolf
REF_LIB := $(REF_DIR)/$(REF_PREFIX)__ALL.a
WOLF_LIB := $(WOLF_DIR)/$(WOLF_PREFIX)__ALL.a

BIN := $(OUT_DIR_BASE)/sim_$(CASE_TAG)

CXX ?= g++
CXXFLAGS ?= -O2 -std=c++17 -Wall
TB_CXXFLAGS := $(if $(filter 1,$(TRACE)),-DTRACE,)
LDLIBS ?= -pthread
TRACE_LDLIBS := $(if $(filter 1,$(TRACE)),-lz,)

.PHONY: run build_ref build_wolf clean

run: clean $(BIN)
	@echo "[RUN] ./$(BIN)"
	@mkdir -p $(OUT_DIR_BASE)
	@cd $(OUT_DIR_BASE) && ./$(notdir $(BIN))

$(WOLF_SV): $(FILELIST)
	@mkdir -p $(WOLF_DIR)
	@printf "" > $(WOLF_READ_ARGS)
	@$(WOLVRIX_PY) $(WOLVRIX_XS_SCRIPT) $(FILELIST) $(DUT_TOP) $(WOLF_SV) $(WOLF_JSON) $(WOLF_READ_ARGS) $(WOLF_LOG)
$(REF_LIB): $(TB_V) $(FILELIST)
	@if ! command -v $(VERILATOR) >/dev/null 2>&1; then \
		echo "[$(CASE_TAG)] verilator not found in PATH"; \
		exit 1; \
	fi
	@mkdir -p $(REF_DIR)
	@$(VERILATOR) $(REF_FLAGS) --cc $(TB_V) -f $(FILELIST) \
		--top-module $(TB_TOP) --prefix $(REF_PREFIX) -Mdir $(REF_DIR)
	@$(MAKE) -C $(REF_DIR) -f $(REF_PREFIX).mk $(REF_PREFIX)__ALL.a

$(WOLF_LIB): $(TB_V) $(WOLF_SV)
	@if ! command -v $(VERILATOR) >/dev/null 2>&1; then \
		echo "[$(CASE_TAG)] verilator not found in PATH"; \
		exit 1; \
	fi
	@mkdir -p $(WOLF_DIR)
	@$(VERILATOR) $(WOLF_FLAGS) --cc $(TB_V) $(WOLF_SV) \
		--top-module $(TB_TOP) --prefix $(WOLF_PREFIX) -Mdir $(WOLF_DIR)
	@$(MAKE) -C $(WOLF_DIR) -f $(WOLF_PREFIX).mk $(WOLF_PREFIX)__ALL.a

$(BIN): $(REF_LIB) $(WOLF_LIB) $(TB_CPP)
	@if [ -z "$(VERILATOR_ROOT)" ]; then \
		echo "[$(CASE_TAG)] VERILATOR_ROOT not found; set VERILATOR_ROOT=/path/to/verilator"; \
		exit 1; \
	fi
	@mkdir -p $(OUT_DIR_BASE)
	@$(CXX) $(CXXFLAGS) $(TB_CXXFLAGS) -I$(REF_DIR) -I$(WOLF_DIR) \
		-I$(VERILATOR_ROOT)/include -I$(VERILATOR_ROOT)/include/vltstd \
		$(TB_CPP) $(REF_LIB) $(WOLF_LIB) \
		$(VERILATOR_ROOT)/include/verilated.cpp \
		$(VERILATOR_ROOT)/include/verilated_dpi.cpp \
		$(VERILATOR_ROOT)/include/verilated_threads.cpp \
		$(VERILATOR_TRACE_SRC) \
		$(VERILATOR_COV_SRC) \
		-o $(BIN) $(LDLIBS) $(TRACE_LDLIBS)

clean:
	@rm -rf $(OUT_DIR_BASE)
