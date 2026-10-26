CASE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ROOT := $(abspath $(CASE_DIR)/../../..)
OUT := $(ROOT)/ptmp/xs-bugcase/CASE_027
SIM := $(OUT)/grhsim
PYTHON ?= $(ROOT)/.venv/bin/python
RTL := $(ROOT)/wolvrix/tests/ingest/data/ingest_struct_array_fieldwise.sv
TOP := ingest_struct_array_partial_write
CXX := clang++
CXXFLAGS ?= -O2 -std=c++20 -fno-strict-aliasing -Wall

.PHONY: run build FORCE
run: $(OUT)/compare
	$(OUT)/compare

build: $(OUT)/compare

FORCE:

$(SIM)/.emitted: $(RTL) $(CASE_DIR)/Makefile FORCE
	mkdir -p $(OUT)
	printf '%s\n' '$(RTL)' > $(OUT)/filelist.f
	printf '' > $(OUT)/read_args.txt
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) $(ROOT)/scripts/wolvrix_xs_grhsim.py \
		$(OUT)/filelist.f $(TOP) $(OUT)/flat.json $(OUT)/ir.json $(OUT)/roundtrip.json \
		$(OUT)/read_args.txt warn --emit-cpp-dir $(SIM)
	touch $@

$(SIM)/libgrhsim_$(TOP).a: $(SIM)/.emitted
	$(MAKE) --no-print-directory -C $(SIM) CXX=$(CXX) CXXFLAGS='$(CXXFLAGS)' -j 2

$(OUT)/compare: $(SIM)/libgrhsim_$(TOP).a $(CASE_DIR)/tb.cpp
	$(CXX) $(CXXFLAGS) -I$(SIM) $(CASE_DIR)/tb.cpp $(SIM)/libgrhsim_$(TOP).a -o $@
