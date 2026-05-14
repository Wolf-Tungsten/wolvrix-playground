SHELL := /bin/bash

PYTHON ?= python3
CXX = clang++
MILL ?= mill
GSIM_BIN ?= ../../reference/gsim/build/gsim/gsim
CACHE_DIR ?= .sandbox-cache
MILL_ENV := COURSIER_CACHE=$(abspath $(CACHE_DIR)/coursier) XDG_CACHE_HOME=$(abspath $(CACHE_DIR)/xdg) IVY_HOME=$(abspath $(CACHE_DIR)/ivy2) MILL_COURSIER_CACHE=$(abspath $(CACHE_DIR)/mill-coursier)

TOP := BigComb
BUILD_DIR ?= build
CHISEL_FIR_DIR := $(BUILD_DIR)/chisel-fir
CHISEL_SV_DIR := $(BUILD_DIR)/chisel-sv
GSIM_DIR := $(BUILD_DIR)/gsim
GRHSIM_DIR := $(BUILD_DIR)/grhsim
GSIM_MODEL_DIR := $(GSIM_DIR)/model
GRHSIM_MODEL_DIR := $(GRHSIM_DIR)/model
TB_DIR := $(BUILD_DIR)/tb

CHISEL_SRC := src/main/scala/$(TOP).scala
FIR := $(CHISEL_FIR_DIR)/$(TOP).fir
SV := $(CHISEL_SV_DIR)/$(TOP).sv
BENCH_TB_SRC := tb/big_comb_bench.cpp
BENCH_TB := $(TB_DIR)/big_comb_bench
BENCH_LOG := $(TB_DIR)/big_comb_bench.log
GSIM_GRAPH_STATS := $(GSIM_MODEL_DIR)/$(TOP)_0Final_Stats.json
GRHSIM_GRAPH_STATS := $(GRHSIM_MODEL_DIR)/activity_schedule_stats.json
GSIM_BUILD_STAMP := $(GSIM_DIR)/obj/.stamp

GSIM_FLAGS ?= --supernode-max-size=8 --cpp-max-size-KB=512
GSIM_CXXFLAGS ?= -O3 -std=c++17 -fbracket-depth=2048 -Wno-parentheses-equality -I$(abspath $(GSIM_MODEL_DIR))
GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE ?= 8
GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE ?= 768
GRHSIM_SCHED_BATCH_MAX_OPS ?= 2048
GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES ?= 8192
GRHSIM_SCHED_BATCH_TARGET_COUNT ?= 64
GRHSIM_EMIT_PARALLELISM ?= 4
GRHSIM_CXXFLAGS ?= -O3 -std=c++20
BENCH_CXXFLAGS ?= -O3 -std=c++20 -I$(abspath $(GSIM_MODEL_DIR)) -I$(abspath $(GRHSIM_MODEL_DIR))
BENCH_VECTORS ?= 100000
BENCH_VERIFY ?= 2048

.PHONY: all generate chisel-fir chisel-sv gsim grhsim bench run clean

all: bench

generate: $(FIR) $(SV)

$(FIR): $(CHISEL_SRC) build.mill
	@mkdir -p $(CHISEL_FIR_DIR)
	@mkdir -p $(CACHE_DIR)/coursier $(CACHE_DIR)/xdg $(CACHE_DIR)/ivy2 $(CACHE_DIR)/mill-coursier
	$(MILL_ENV) $(MILL) --no-daemon bigcomb.runMain bigcomb.BigCombMain --target chirrtl --target-dir $(CHISEL_FIR_DIR)
	test -f $@

$(SV): $(CHISEL_SRC) build.mill
	@mkdir -p $(CHISEL_SV_DIR)
	@mkdir -p $(CACHE_DIR)/coursier $(CACHE_DIR)/xdg $(CACHE_DIR)/ivy2 $(CACHE_DIR)/mill-coursier
	$(MILL_ENV) $(MILL) --no-daemon bigcomb.runMain bigcomb.BigCombMain --target systemverilog --target-dir $(CHISEL_SV_DIR) --split-verilog
	test -f $@

chisel-fir: $(FIR)

chisel-sv: $(SV)

$(GSIM_MODEL_DIR)/$(TOP)0.cpp $(GSIM_GRAPH_STATS) &: $(FIR) $(GSIM_BIN)
	@mkdir -p $(GSIM_MODEL_DIR)
	set -o pipefail; $(GSIM_BIN) $(GSIM_FLAGS) --dump-stats-json --dump-stages=Final --dir $(GSIM_MODEL_DIR) $(FIR) | tee $(GSIM_DIR)/gsim.log
	test -f $(GSIM_MODEL_DIR)/$(TOP)0.cpp
	test -f $(GSIM_GRAPH_STATS)

$(GSIM_BUILD_STAMP): $(GSIM_MODEL_DIR)/$(TOP)0.cpp
	@mkdir -p $(GSIM_DIR)/obj
	@for src in $(GSIM_MODEL_DIR)/*.cpp; do \
		obj="$(GSIM_DIR)/obj/$$(basename "$${src%.cpp}").o"; \
		echo "+ CXX $$src"; \
		$(CXX) $(GSIM_CXXFLAGS) -c "$$src" -o "$$obj" || exit $$?; \
	done
	@touch $@

gsim: $(GSIM_BUILD_STAMP)

$(GRHSIM_MODEL_DIR)/Makefile $(GRHSIM_GRAPH_STATS) &: $(SV) scripts/emit_grhsim.py
	@mkdir -p $(GRHSIM_MODEL_DIR)
	$(PYTHON) scripts/emit_grhsim.py --sv $(SV) --top $(TOP) --out $(GRHSIM_MODEL_DIR) --json $(GRHSIM_DIR)/$(TOP).json \
		--max-op-in-compute-supernode $(GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE) \
		--max-op-in-commit-supernode $(GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE) \
		--sched-batch-max-ops $(GRHSIM_SCHED_BATCH_MAX_OPS) \
		--sched-batch-max-estimated-lines $(GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES) \
		--sched-batch-target-count $(GRHSIM_SCHED_BATCH_TARGET_COUNT) \
		--emit-parallelism $(GRHSIM_EMIT_PARALLELISM)
	test -f $(GRHSIM_MODEL_DIR)/Makefile
	test -f $(GRHSIM_GRAPH_STATS)

grhsim: $(GRHSIM_MODEL_DIR)/Makefile
	$(MAKE) -C $(GRHSIM_MODEL_DIR) CXX=$(CXX) CXXFLAGS="$(GRHSIM_CXXFLAGS)"

$(BENCH_TB): $(BENCH_TB_SRC) $(GSIM_BUILD_STAMP) $(GRHSIM_MODEL_DIR)/libgrhsim_$(TOP).a
	@mkdir -p $(TB_DIR)
	$(CXX) $(BENCH_CXXFLAGS) \
		$(BENCH_TB_SRC) \
		$(GSIM_DIR)/obj/*.o \
		$(GRHSIM_MODEL_DIR)/libgrhsim_$(TOP).a \
		-o $@

$(GRHSIM_MODEL_DIR)/libgrhsim_$(TOP).a: $(GRHSIM_MODEL_DIR)/Makefile
	$(MAKE) -C $(GRHSIM_MODEL_DIR) CXX=$(CXX) CXXFLAGS="$(GRHSIM_CXXFLAGS)"

bench: $(BENCH_TB)
	@mkdir -p $(TB_DIR)
	set -o pipefail; $(BENCH_TB) --vectors $(BENCH_VECTORS) --verify $(BENCH_VERIFY) 2>&1 | tee $(BENCH_LOG)

run: bench

clean:
	rm -rf $(BUILD_DIR) out
