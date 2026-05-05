SHELL := /bin/bash

PYTHON ?= python3
CXX = clang++
MILL ?= mill
GSIM_BIN ?= ../../reference/gsim/build/gsim/gsim
OBJDUMP ?= objdump

TOP := XsComponents
BUILD_DIR ?= build
CHISEL_FIR_DIR := $(BUILD_DIR)/chisel-fir
CHISEL_SV_DIR := $(BUILD_DIR)/chisel-sv
GSIM_DIR := $(BUILD_DIR)/gsim
GRHSIM_DIR := $(BUILD_DIR)/grhsim
GSIM_MODEL_DIR := $(GSIM_DIR)/model
GRHSIM_MODEL_DIR := $(GRHSIM_DIR)/model
STATS_DIR := $(BUILD_DIR)/stats
TB_DIR := $(BUILD_DIR)/tb

CHISEL_SRC := src/main/scala/$(TOP).scala
FIR := $(CHISEL_FIR_DIR)/$(TOP).fir
SV := $(CHISEL_SV_DIR)/$(TOP).sv
COSIM_TB_SRC := tb/xs_components_cosim_tb.cpp
COSIM_TB := $(TB_DIR)/xs_components_cosim_tb
COSIM_LOG := $(TB_DIR)/xs_components_cosim.log
GSIM_GRAPH_STATS := $(GSIM_MODEL_DIR)/$(TOP)_0Final_Stats.json
GRHSIM_GRAPH_STATS := $(GRHSIM_MODEL_DIR)/activity_schedule_stats.json
MODEL_STATS_JSON := $(STATS_DIR)/model_stats.json

GSIM_FLAGS ?= --supernode-max-size=8 --cpp-max-size-KB=512
GSIM_CXXFLAGS ?= -O3 -std=c++17 -fbracket-depth=2048 -Wno-parentheses-equality -I$(abspath $(GSIM_MODEL_DIR))
GRHSIM_SUPERNODE_MAX_SIZE ?= 8
GRHSIM_MAX_SINK_SUPERNODE_OP ?= 768
GRHSIM_SCHED_BATCH_MAX_OPS ?= 2048
GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES ?= 8192
GRHSIM_SCHED_BATCH_TARGET_COUNT ?= 64
GRHSIM_EMIT_PARALLELISM ?= 4
GRHSIM_CXXFLAGS ?= -O3 -std=c++20
COSIM_CYCLES ?= 256
COSIM_TRACE ?= 1
COSIM_TB_CXXFLAGS ?= -O2 -std=c++20 -I$(abspath $(GSIM_MODEL_DIR)) -I$(abspath $(GRHSIM_MODEL_DIR))

.PHONY: all generate gsim grhsim stats stat compare cosim run clean
.PHONY: chisel-sv chisel-fir

all: compare cosim

generate: $(FIR) $(SV)

$(FIR): $(CHISEL_SRC) build.mill
	@mkdir -p $(CHISEL_FIR_DIR)
	$(MILL) --no-daemon xscomponents.runMain xscomponents.XsComponentsMain --target chirrtl --target-dir $(CHISEL_FIR_DIR)
	test -f $@

$(SV): $(CHISEL_SRC) build.mill
	@mkdir -p $(CHISEL_SV_DIR)
	$(MILL) --no-daemon xscomponents.runMain xscomponents.XsComponentsMain --target systemverilog --target-dir $(BUILD_DIR)/chisel-sv --split-verilog
	test -f $@

chisel-sv: $(SV)

chisel-fir: $(FIR)

$(GSIM_MODEL_DIR)/$(TOP)0.cpp $(GSIM_GRAPH_STATS) &: $(FIR) $(GSIM_BIN)
	@mkdir -p $(GSIM_MODEL_DIR)
	set -o pipefail; $(GSIM_BIN) $(GSIM_FLAGS) --dump-stats-json --dump-stages=Final --dir $(GSIM_MODEL_DIR) $(FIR) | tee $(GSIM_DIR)/gsim.log
	test -f $(GSIM_MODEL_DIR)/$(TOP)0.cpp
	test -f $(GSIM_GRAPH_STATS)

gsim: $(GSIM_MODEL_DIR)/$(TOP)0.cpp
	@mkdir -p $(GSIM_DIR)/obj
	@for src in $(GSIM_MODEL_DIR)/*.cpp; do \
		obj="$(GSIM_DIR)/obj/$$(basename "$${src%.cpp}").o"; \
		echo "+ CXX $$src"; \
		$(CXX) $(GSIM_CXXFLAGS) -c "$$src" -o "$$obj" || exit $$?; \
	done

$(GRHSIM_MODEL_DIR)/Makefile $(GRHSIM_GRAPH_STATS) &: $(SV) scripts/emit_grhsim.py
	@mkdir -p $(GRHSIM_MODEL_DIR)
	$(PYTHON) scripts/emit_grhsim.py --sv $(SV) --top $(TOP) --out $(GRHSIM_MODEL_DIR) --json $(GRHSIM_DIR)/$(TOP).json \
		--max-compute-node-in-compute-supernode $(GRHSIM_SUPERNODE_MAX_SIZE) \
		--max-op-in-commit-supernode $(GRHSIM_MAX_SINK_SUPERNODE_OP) \
		--sched-batch-max-ops $(GRHSIM_SCHED_BATCH_MAX_OPS) \
		--sched-batch-max-estimated-lines $(GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES) \
		--sched-batch-target-count $(GRHSIM_SCHED_BATCH_TARGET_COUNT) \
		--emit-parallelism $(GRHSIM_EMIT_PARALLELISM)
	test -f $(GRHSIM_MODEL_DIR)/Makefile
	test -f $(GRHSIM_GRAPH_STATS)

grhsim: $(GRHSIM_MODEL_DIR)/Makefile
	$(MAKE) -C $(GRHSIM_MODEL_DIR) CXX=$(CXX) CXXFLAGS="$(GRHSIM_CXXFLAGS)"

$(STATS_DIR)/gsim.json: gsim scripts/objdump_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/objdump_stats.py --label gsim --out $@ --objdump $(OBJDUMP) $(GSIM_DIR)/obj/*.o

$(STATS_DIR)/grhsim.json: grhsim scripts/objdump_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/objdump_stats.py --label grhsim --out $@ --objdump $(OBJDUMP) $(GRHSIM_MODEL_DIR)/*.o

stats: $(STATS_DIR)/gsim.json $(STATS_DIR)/grhsim.json

$(MODEL_STATS_JSON): $(GSIM_GRAPH_STATS) $(GRHSIM_GRAPH_STATS) $(STATS_DIR)/gsim.json $(STATS_DIR)/grhsim.json scripts/model_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/model_stats.py \
		--gsim-graph-stats $(GSIM_GRAPH_STATS) \
		--grhsim-graph-stats $(GRHSIM_GRAPH_STATS) \
		--gsim-instruction-stats $(STATS_DIR)/gsim.json \
		--grhsim-instruction-stats $(STATS_DIR)/grhsim.json \
		--gsim-objects $(GSIM_DIR)/obj/*.o \
		--grhsim-objects $(GRHSIM_MODEL_DIR)/*.o \
		--objdump $(OBJDUMP) \
		--out $@

stat: $(MODEL_STATS_JSON)

compare: stats scripts/compare_stats.py
	$(PYTHON) scripts/compare_stats.py --gsim $(STATS_DIR)/gsim.json --grhsim $(STATS_DIR)/grhsim.json --out $(STATS_DIR)/compare.json

$(COSIM_TB): $(COSIM_TB_SRC) gsim grhsim
	@mkdir -p $(TB_DIR)
	$(CXX) $(COSIM_TB_CXXFLAGS) \
		$(COSIM_TB_SRC) \
		$(GSIM_DIR)/obj/*.o \
		$(GRHSIM_MODEL_DIR)/libgrhsim_$(TOP).a \
		-o $@

cosim: $(COSIM_TB)
	@mkdir -p $(TB_DIR)
	set -o pipefail; $(COSIM_TB) --cycles $(COSIM_CYCLES) $(if $(filter 0,$(COSIM_TRACE)),--quiet,) 2>&1 | tee $(COSIM_LOG)

run: cosim

clean:
	rm -rf $(BUILD_DIR)
