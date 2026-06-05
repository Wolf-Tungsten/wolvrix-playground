SHELL := /bin/bash

PYTHON ?= python3
CXX = clang++
MILL ?= mill
GSIM_BIN ?= ../../reference/gsim/build/gsim/gsim
OBJDUMP ?= objdump
CACHE_DIR ?= .sandbox-cache
MILL_ENV := COURSIER_CACHE=$(abspath $(CACHE_DIR)/coursier) XDG_CACHE_HOME=$(abspath $(CACHE_DIR)/xdg) IVY_HOME=$(abspath $(CACHE_DIR)/ivy2) MILL_COURSIER_CACHE=$(abspath $(CACHE_DIR)/mill-coursier)

CASES := XsBranchAluSmall XsVectorMaskMedium XsAgeMatrixMedium XsPlruLarge XsStoreMergeLarge XsIcacheReplacerLarge XsIcacheReplRegsLarge XsIcacheReplRegsCatLarge XsStoreQueueBanksLarge XsLoadQueueReplayLarge XsPlruBankedXLarge XsFreeListAllocLarge XsRobBankScanLarge XsIssueBusyMaskLarge XsWbArbiterLarge XsFusionDecodeLarge XsTlbPermLarge XsDcacheMetaSelectLarge XsVecMergeBufferLarge XsPrefetchStrideLarge XsLoadQueueRawLarge XsCsrTrapPriorityLarge
KIND_XsBranchAluSmall := branch-alu
KIND_XsVectorMaskMedium := vector-mask
KIND_XsAgeMatrixMedium := scheduler-age
KIND_XsPlruLarge := replacement
KIND_XsStoreMergeLarge := store-merge
KIND_XsIcacheReplacerLarge := icache-replacer
KIND_XsIcacheReplRegsLarge := icache-repl-regs
KIND_XsIcacheReplRegsCatLarge := icache-repl-regs
KIND_XsStoreQueueBanksLarge := store-queue-banks
KIND_XsLoadQueueReplayLarge := load-queue-replay
KIND_XsPlruBankedXLarge := replacement-banked
KIND_XsFreeListAllocLarge := freelist-alloc
KIND_XsRobBankScanLarge := rob-bank-scan
KIND_XsIssueBusyMaskLarge := issue-busy-mask
KIND_XsWbArbiterLarge := writeback-arbiter
KIND_XsFusionDecodeLarge := fusion-decode
KIND_XsTlbPermLarge := tlb-permission
KIND_XsDcacheMetaSelectLarge := dcache-meta
KIND_XsVecMergeBufferLarge := vector-merge-buffer
KIND_XsPrefetchStrideLarge := prefetch-stride
KIND_XsLoadQueueRawLarge := load-queue-raw
KIND_XsCsrTrapPriorityLarge := csr-trap-priority
SCALE_XsBranchAluSmall := small
SCALE_XsVectorMaskMedium := medium
SCALE_XsAgeMatrixMedium := medium
SCALE_XsPlruLarge := large
SCALE_XsStoreMergeLarge := large
SCALE_XsIcacheReplacerLarge := large
SCALE_XsIcacheReplRegsLarge := large
SCALE_XsIcacheReplRegsCatLarge := large
SCALE_XsStoreQueueBanksLarge := large
SCALE_XsLoadQueueReplayLarge := large
SCALE_XsPlruBankedXLarge := xlarge
SCALE_XsFreeListAllocLarge := large
SCALE_XsRobBankScanLarge := large
SCALE_XsIssueBusyMaskLarge := large
SCALE_XsWbArbiterLarge := large
SCALE_XsFusionDecodeLarge := large
SCALE_XsTlbPermLarge := large
SCALE_XsDcacheMetaSelectLarge := large
SCALE_XsVecMergeBufferLarge := large
SCALE_XsPrefetchStrideLarge := large
SCALE_XsLoadQueueRawLarge := large
SCALE_XsCsrTrapPriorityLarge := large

CASE ?= XsBranchAluSmall
KIND := $(KIND_$(CASE))
SCALE := $(SCALE_$(CASE))
BUILD_DIR ?= build
CASE_BUILD := $(BUILD_DIR)/$(CASE)
FIR_DIR := $(CASE_BUILD)/chisel-fir
SV_DIR := $(CASE_BUILD)/chisel-sv
GSIM_DIR := $(CASE_BUILD)/gsim
GRHSIM_DIR := $(CASE_BUILD)/grhsim
GSIM_MODEL_DIR := $(GSIM_DIR)/model
GRHSIM_MODEL_DIR := $(GRHSIM_DIR)/model
TB_DIR := $(CASE_BUILD)/tb
STATS_DIR := $(CASE_BUILD)/stats
MATRIX_DIR := $(BUILD_DIR)/matrix

FIR := $(FIR_DIR)/$(CASE).fir
SV := $(SV_DIR)/$(CASE).sv
GSIM_GRAPH_STATS := $(GSIM_MODEL_DIR)/$(CASE)_0Final_Stats.json
GRHSIM_GRAPH_STATS := $(GRHSIM_MODEL_DIR)/activity_schedule_stats.json
GSIM_BUILD_STAMP := $(GSIM_DIR)/obj/.stamp
GRHSIM_LIB := $(GRHSIM_MODEL_DIR)/libgrhsim_$(CASE).a
BENCH_TB := $(TB_DIR)/$(CASE)_bench
BENCH_LOG := $(TB_DIR)/$(CASE)_bench.log
GSIM_PORT_WIDTHS_HEADER := $(TB_DIR)/gsim_port_widths.hpp
MODEL_STATS_JSON := $(STATS_DIR)/model_stats.json

GSIM_FLAGS ?= --supernode-max-size=8 --cpp-max-size-KB=512
GSIM_CXXFLAGS ?= -O3 -std=c++17 -fbracket-depth=2048 -Wno-parentheses-equality -I$(abspath $(GSIM_MODEL_DIR))
GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE ?= 128
GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE ?= 768
GRHSIM_SCHED_BATCH_MAX_OPS ?= 2048
GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES ?= 8192
GRHSIM_SCHED_BATCH_TARGET_COUNT ?= 64
GRHSIM_EMIT_PARALLELISM ?= 4
GRHSIM_CXXFLAGS ?= -O3 -std=c++20
BENCH_CXXFLAGS ?= -O3 -std=c++20 -I$(abspath $(GSIM_MODEL_DIR)) -I$(abspath $(GRHSIM_MODEL_DIR))
BENCH_VECTORS ?= 100000
BENCH_VERIFY ?= 2048
BENCH_REPEAT ?= 1

.PHONY: all generate chisel-fir chisel-sv gsim grhsim bench stats stat one matrix clean list

all: matrix

list:
	@printf '%s\n' $(CASES)

generate: $(FIR) $(SV)

SCALA_SRCS := $(shell find src/main/scala -name '*.scala' | sort)

$(FIR): $(SCALA_SRCS) build.mill
	@mkdir -p $(FIR_DIR) $(CACHE_DIR)/coursier $(CACHE_DIR)/xdg $(CACHE_DIR)/ivy2 $(CACHE_DIR)/mill-coursier
	$(MILL_ENV) $(MILL) --no-daemon xscomponents.runMain xscomponents.XsComponentsMain --top-name $(CASE) --target chirrtl --target-dir $(FIR_DIR)
	test -f $@

$(SV): $(SCALA_SRCS) build.mill
	@mkdir -p $(SV_DIR) $(CACHE_DIR)/coursier $(CACHE_DIR)/xdg $(CACHE_DIR)/ivy2 $(CACHE_DIR)/mill-coursier
	$(MILL_ENV) $(MILL) --no-daemon xscomponents.runMain xscomponents.XsComponentsMain --top-name $(CASE) --target systemverilog --target-dir $(SV_DIR) --split-verilog
	test -f $@

chisel-fir: $(FIR)

chisel-sv: $(SV)

$(GSIM_MODEL_DIR)/$(CASE)0.cpp $(GSIM_MODEL_DIR)/$(CASE).h $(GSIM_GRAPH_STATS) &: $(FIR) $(GSIM_BIN)
	@mkdir -p $(GSIM_MODEL_DIR)
	set -o pipefail; $(GSIM_BIN) $(GSIM_FLAGS) --dump-stats-json --dump-stages=Final --dir $(GSIM_MODEL_DIR) $(FIR) | tee $(GSIM_DIR)/gsim.log
	test -f $(GSIM_MODEL_DIR)/$(CASE)0.cpp
	test -f $(GSIM_MODEL_DIR)/$(CASE).h
	test -f $(GSIM_GRAPH_STATS)

$(GSIM_BUILD_STAMP): $(GSIM_MODEL_DIR)/$(CASE)0.cpp
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
	$(PYTHON) scripts/emit_grhsim.py --sv $(SV) --top $(CASE) --out $(GRHSIM_MODEL_DIR) --json $(GRHSIM_DIR)/$(CASE).json \
		--max-op-in-compute-supernode $(GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE) \
		--max-op-in-commit-supernode $(GRHSIM_MAX_OP_IN_COMMIT_SUPERNODE) \
		--sched-batch-max-ops $(GRHSIM_SCHED_BATCH_MAX_OPS) \
		--sched-batch-max-estimated-lines $(GRHSIM_SCHED_BATCH_MAX_ESTIMATED_LINES) \
		--sched-batch-target-count $(GRHSIM_SCHED_BATCH_TARGET_COUNT) \
		--emit-parallelism $(GRHSIM_EMIT_PARALLELISM)
	test -f $(GRHSIM_MODEL_DIR)/Makefile
	test -f $(GRHSIM_GRAPH_STATS)

$(GRHSIM_LIB): $(GRHSIM_MODEL_DIR)/Makefile
	$(MAKE) -C $(GRHSIM_MODEL_DIR) CXX=$(CXX) CXXFLAGS="$(GRHSIM_CXXFLAGS)"

grhsim: $(GRHSIM_LIB)

$(GSIM_PORT_WIDTHS_HEADER): $(GSIM_MODEL_DIR)/$(CASE).h scripts/gsim_port_widths.py
	@mkdir -p $(TB_DIR)
	$(PYTHON) scripts/gsim_port_widths.py --header $(GSIM_MODEL_DIR)/$(CASE).h --out $@

$(BENCH_TB): tb/xs_component_bench.cpp tb/xs_component_bench.hpp $(GSIM_PORT_WIDTHS_HEADER) $(GSIM_BUILD_STAMP) $(GRHSIM_LIB)
	@mkdir -p $(TB_DIR)
	$(CXX) $(BENCH_CXXFLAGS) -I$(abspath tb) \
		-include $(abspath $(GSIM_PORT_WIDTHS_HEADER)) \
		-DTOP_NAME=\"$(CASE)\" \
		-DGSIM_CLASS=S$(CASE) \
		-DGRHSIM_CLASS=GrhSIM_$(CASE) \
		-DTOP_HEADER=\"$(CASE).h\" \
		-DGRHSIM_HEADER=\"grhsim_$(CASE).hpp\" \
		tb/xs_component_bench.cpp \
		$(GSIM_DIR)/obj/*.o \
		$(GRHSIM_LIB) \
		-o $@

bench: $(BENCH_TB)
	@mkdir -p $(TB_DIR)
	set -o pipefail; $(BENCH_TB) --vectors $(BENCH_VECTORS) --verify $(BENCH_VERIFY) --repeat $(BENCH_REPEAT) 2>&1 | tee $(BENCH_LOG)

$(STATS_DIR)/gsim.json: $(GSIM_BUILD_STAMP) scripts/objdump_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/objdump_stats.py --label gsim --out $@ --objdump $(OBJDUMP) $(GSIM_DIR)/obj/*.o

$(STATS_DIR)/grhsim.json: $(GRHSIM_LIB) scripts/objdump_stats.py
	@mkdir -p $(STATS_DIR)
	$(PYTHON) scripts/objdump_stats.py --label grhsim --out $@ --objdump $(OBJDUMP) $(GRHSIM_MODEL_DIR)/*.o

stats: $(STATS_DIR)/gsim.json $(STATS_DIR)/grhsim.json

$(MODEL_STATS_JSON): bench stats scripts/model_stats.py
	$(PYTHON) scripts/model_stats.py \
		--case $(CASE) --kind $(KIND) --scale $(SCALE) \
		--gsim-graph-stats $(GSIM_GRAPH_STATS) \
		--grhsim-graph-stats $(GRHSIM_GRAPH_STATS) \
		--gsim-instruction-stats $(STATS_DIR)/gsim.json \
		--grhsim-instruction-stats $(STATS_DIR)/grhsim.json \
		--bench-log $(BENCH_LOG) \
		--out $@

stat: $(MODEL_STATS_JSON)

one: stat

matrix:
	@mkdir -p $(MATRIX_DIR)
	@for case in $(CASES); do \
		echo "== xs-component $$case =="; \
		$(MAKE) CASE=$$case one || exit $$?; \
	done
	$(PYTHON) scripts/collect_matrix.py --out $(MATRIX_DIR)/results.csv $(foreach c,$(CASES),$(BUILD_DIR)/$(c)/stats/model_stats.json)

clean:
	rm -rf $(BUILD_DIR) out
