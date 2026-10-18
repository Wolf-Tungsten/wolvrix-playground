CASE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(CASE_DIR)/../../..)
OUT := $(ROOT)/ptmp/xs-bugcase/CASE_026
REF_DIR := $(OUT)/ref
GRHSIM_DIR := $(OUT)/grhsim
PYTHON ?= $(ROOT)/.venv/bin/python
VERILATOR ?= verilator
VERILATOR_ROOT ?= $(shell $(VERILATOR) -V 2>/dev/null | awk -F'= *' '/VERILATOR_ROOT/ {gsub(/^ +| +$$/, "", $$2); value=$$2} END {print value}')
CXX := clang++
CXXFLAGS ?= -O2 -std=c++20 -fno-strict-aliasing -Wall
RTL := $(CASE_DIR)/rtl/AheadBtbTargetCorrect.sv
TB := $(CASE_DIR)/tb.v
REF_LIB := $(REF_DIR)/VRef__ALL.a
GRHSIM_LIB := $(GRHSIM_DIR)/libgrhsim_xs_bugcase_tb.a
BIN := $(OUT)/compare
PIPELINE := $(ROOT)/scripts/wolvrix_xs_grhsim_ir.py

export CCACHE_DIR := $(OUT)/ccache

.PHONY: build run reproduce verify-extraction FORCE
build: $(BIN)

FORCE:

run: $(BIN)
	cd $(OUT) && $(BIN)

reproduce: $(BIN)
	cd $(OUT) && $(BIN) --expect-mismatch

verify-extraction: | $(OUT)
	sed -n '/^  wire        t1_positionEqualMask_0 =/,/^  wire        _GEN_21 =/{ /^  wire        _GEN_21 =/!p; }' \
		$(ROOT)/ptmp/xs/rtl/rtl/AheadBtb.sv > $(OUT)/original-cone.sv
	sed -n '/^  wire        t1_positionEqualMask_0 =/,/^  wire        _GEN_23 =/{ /^  wire        _GEN_23 =/!p; }' \
		$(RTL) > $(OUT)/extracted-cone.sv
	test -s $(OUT)/original-cone.sv
	diff -u $(OUT)/original-cone.sv $(OUT)/extracted-cone.sv

$(OUT):
	mkdir -p $(OUT) $(CCACHE_DIR)

$(REF_LIB): $(RTL) $(TB) | $(OUT)
	mkdir -p $(REF_DIR)
	$(VERILATOR) --cc --no-timing --threads 1 -Wall -Wno-fatal -Wno-DECLFILENAME \
		-Wno-UNUSEDSIGNAL $(RTL) $(TB) --top-module xs_bugcase_tb --prefix VRef -Mdir $(REF_DIR)
	$(MAKE) --no-print-directory -C $(REF_DIR) -f VRef.mk VRef__ALL.a -j 2

$(GRHSIM_DIR)/.emitted: $(RTL) $(TB) $(PIPELINE) $(CASE_DIR)/Makefile FORCE | $(OUT)
	printf '%s\n' '$(RTL)' '$(TB)' > $(OUT)/filelist.f
	printf '' > $(OUT)/read_args.txt
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) $(PIPELINE) \
		$(OUT)/filelist.f xs_bugcase_tb $(OUT)/flat_grh.json $(OUT)/grhsim_ir.json \
		$(OUT)/roundtrip.json $(OUT)/read_args.txt warn --emit-cpp-dir $(GRHSIM_DIR)
	touch $@

$(GRHSIM_LIB): $(GRHSIM_DIR)/.emitted
	$(MAKE) --no-print-directory -C $(GRHSIM_DIR) CXX=$(CXX) CXXFLAGS='$(CXXFLAGS)' -j 2

$(BIN): $(REF_LIB) $(GRHSIM_LIB) $(CASE_DIR)/tb.cpp
	test -f '$(VERILATOR_ROOT)/include/verilated.h'
	$(CXX) $(CXXFLAGS) -I$(REF_DIR) -I$(GRHSIM_DIR) \
		-I$(VERILATOR_ROOT)/include -I$(VERILATOR_ROOT)/include/vltstd \
		$(CASE_DIR)/tb.cpp $(REF_LIB) $(GRHSIM_LIB) \
		$(VERILATOR_ROOT)/include/verilated.cpp $(VERILATOR_ROOT)/include/verilated_threads.cpp \
		-o $(BIN) -pthread
