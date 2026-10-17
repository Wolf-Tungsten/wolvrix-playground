# Exact Rob extraction from the generated XiangShan design.
SHELL := /bin/bash
# The gsim model needs clang >= 19 for C++ _BitInt (mirrors the root Makefile).
ifeq ($(origin CXX),default)
CXX := clang++
endif
ifeq ($(origin CXX),undefined)
CXX := clang++
endif
ROB_REPO := $(abspath ../..)
ROB_PYTHON ?= $(ROB_REPO)/.venv/bin/python
ROB_SOURCE_RTL ?= $(ROB_REPO)/ptmp/xs/rtl/rtl
ROB_FIXTURE := $(abspath rob)
ROB_WORK ?= $(ROB_REPO)/ptmp/xs-components-rob
ROB_GSIM := $(abspath $(GSIM_BIN))

.PHONY: rob-extract rob-ir rob-gsim-ir rob-grhsim-ir rob-compare rob-cones rob-report
rob-extract:
	@mkdir -p "$(ROB_WORK)"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/extract_rob.py \
		--source "$(ROB_SOURCE_RTL)" --output "$(ROB_FIXTURE)" --work "$(ROB_WORK)" \
		> "$(ROB_WORK)/extract.log" 2>&1

rob-gsim-ir:
	@test -f "$(ROB_FIXTURE)/Rob.fir"
	@mkdir -p "$(ROB_WORK)/gsim"
	"$(ROB_GSIM)" --supernode-max-size=15 --cpp-max-size-KB=8192 \
		--sep-mod=__DOT__ --sep-aggr=__DOT__ --dump-json --dump-assign-tree \
		--dump-stages=InferAllWidth,PreCoarsen --stop-after-stage=PreCoarsen \
		--dir "$(ROB_WORK)/gsim" "$(ROB_WORK)/Rob_resolved.fir" \
		> "$(ROB_WORK)/gsim.log" 2>&1

rob-grhsim-ir:
	@test -f "$(ROB_WORK)/rtl.f"
	@mkdir -p "$(ROB_WORK)/grhsim"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) "$(ROB_REPO)/scripts/wolvrix_xs_grhsim_ir.py" \
		"$(ROB_WORK)/rtl.f" Rob "$(ROB_WORK)/grhsim/flat_grh.json" \
		"$(ROB_WORK)/grhsim/final.json" "$(ROB_WORK)/grhsim/roundtrip.json" \
		"$(ROB_WORK)/read_args.txt" info --keep-origins \
		--pack-bit-registers-report "$(ROB_WORK)/grhsim/pack_members.tsv" \
		--dump-post-lower-json "$(ROB_WORK)/grhsim/post_lower.json" \
		--dump-pre-partition-json "$(ROB_WORK)/grhsim/pre_partition.json" \
		> "$(ROB_WORK)/grhsim.log" 2>&1

rob-ir: rob-extract
	$(MAKE) --no-print-directory -j2 rob-gsim-ir rob-grhsim-ir

rob-compare:
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/compare_rob.py \
		--fixture "$(ROB_FIXTURE)" --work "$(ROB_WORK)" \
		> "$(ROB_WORK)/compare.log" 2>&1

rob-cones:
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/compare_rob.py \
		--fixture "$(ROB_FIXTURE)" --work "$(ROB_WORK)" --cones-only \
		> "$(ROB_WORK)/cones.log" 2>&1

rob-report:
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/compare_rob.py \
		--fixture "$(ROB_FIXTURE)" --work "$(ROB_WORK)" --report-only \
		> "$(ROB_WORK)/report.log" 2>&1

# ---------------------------------------------------------------------------
# Runtime benchmark: gsim vs GrhSIM C++ models of the extracted Rob module.
# ---------------------------------------------------------------------------
ROB_GSIM_MODEL_DIR := $(ROB_WORK)/gsim-model
ROB_GSIM_OBJ_DIR := $(ROB_WORK)/gsim-obj
ROB_GRHSIM_MODEL_DIR := $(ROB_WORK)/grhsim-model
ROB_BENCH_DIR := $(ROB_WORK)/bench
ROB_GSIM_FLAGS ?= --supernode-max-size=15 --cpp-max-size-KB=8192 --sep-mod=__DOT__ --sep-aggr=__DOT__
# -DNDEBUG disables the C assert()s that gsim emits for the DUT's own
# verification assertions: unconstrained random stimulus violates them by
# construction, and the grhsim side stubs the same assertions out already.
ROB_GSIM_CXXFLAGS ?= -O3 -std=c++17 -fbracket-depth=2048 -Wno-parentheses-equality -DNDEBUG
ROB_GRHSIM_CXXFLAGS ?= -O3 -std=c++20
ROB_BENCH_CXXFLAGS ?= -O3 -std=c++20 -Wno-bitint-extension
ROB_BENCH_VECTORS ?= 100000
ROB_BENCH_VERIFY ?= 2048
ROB_BENCH_REPEAT ?= 3
ROB_JOBS ?= 16

# Reuse the flat GRH checkpoint from rob-grhsim-ir when present to skip the
# ~90s SV ingest + GRH pipeline; semantic switches below only affect passes
# after the checkpoint.
ROB_GRHSIM_FLAT_GRH := $(ROB_WORK)/emit_flat_grh.json
ROB_GRHSIM_RESUME :=
ifneq ($(wildcard $(ROB_WORK)/grhsim/flat_grh.json),)
ROB_GRHSIM_FLAT_GRH := $(ROB_WORK)/grhsim/flat_grh.json
ROB_GRHSIM_RESUME := --resume-from-flat-grh
endif
# Extra flags appended to the grhsim-ir emit invocation, e.g.
# ROB_GRHSIM_EXTRA_FLAGS=--no-pack-bit-registers for A/B arms.
ROB_GRHSIM_EXTRA_FLAGS ?=

.PHONY: rob-gsim-model rob-grhsim-model rob-bench

rob-gsim-model: $(ROB_GSIM_OBJ_DIR)/.stamp

$(ROB_GSIM_MODEL_DIR)/Rob.h: $(ROB_WORK)/Rob_resolved.fir
	@mkdir -p "$(ROB_GSIM_MODEL_DIR)"
	@start=$$(date +%s); \
	"$(ROB_GSIM)" $(ROB_GSIM_FLAGS) --dump-stats-json --dump-stages=Final \
		--dir "$(ROB_GSIM_MODEL_DIR)" "$(ROB_WORK)/Rob_resolved.fir" \
		> "$(ROB_WORK)/gsim_model_gen.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-gsim-model] codegen rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/gsim_model_gen.log"; exit $$rc; fi
	@test -f "$(ROB_GSIM_MODEL_DIR)/Rob.h"

# gsim emits scalar bodies for top-level array-port accessors (they do not
# compile); rewrite them into pointer-based per-element forms in place.
$(ROB_GSIM_MODEL_DIR)/.patched: $(ROB_GSIM_MODEL_DIR)/Rob.h scripts/fix_gsim_array_ports.py
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/fix_gsim_array_ports.py \
		--top Rob --dir "$(ROB_GSIM_MODEL_DIR)"
	@touch $@

# Neuter assertion reporting (predicates kept) in both generated models so
# illegal random stimulus does not drown the benchmark in report I/O.
$(ROB_WORK)/.asserts-stripped: $(ROB_GSIM_MODEL_DIR)/.patched $(ROB_GRHSIM_MODEL_DIR)/Makefile scripts/strip_rob_asserts.py
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/strip_rob_asserts.py \
		--gsim-dir "$(ROB_GSIM_MODEL_DIR)" --grhsim-dir "$(ROB_GRHSIM_MODEL_DIR)"
	@touch $@

$(ROB_GSIM_OBJ_DIR)/.stamp: $(ROB_GSIM_MODEL_DIR)/.patched $(ROB_WORK)/.asserts-stripped
	@mkdir -p "$(ROB_GSIM_OBJ_DIR)"
	@start=$$(date +%s); \
	ls "$(ROB_GSIM_MODEL_DIR)"/*.cpp | xargs -P $(ROB_JOBS) -I{} sh -c \
		'src="{}"; obj="$(ROB_GSIM_OBJ_DIR)/$$(basename "$${src%.cpp}").o"; \
		 echo "+ CXX $$src"; $(CXX) $(ROB_GSIM_CXXFLAGS) -I"$(ROB_GSIM_MODEL_DIR)" -c "$$src" -o "$$obj"' \
		> "$(ROB_WORK)/gsim_model_build.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-gsim-model] compile rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/gsim_model_build.log"; exit $$rc; fi
	@touch $@

rob-grhsim-model: $(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a

$(ROB_GRHSIM_MODEL_DIR)/Makefile: $(ROB_WORK)/rtl.f $(ROB_WORK)/read_args.txt
	@mkdir -p "$(ROB_GRHSIM_MODEL_DIR)"
	@start=$$(date +%s); \
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) "$(ROB_REPO)/scripts/wolvrix_xs_grhsim_ir.py" \
		"$(ROB_WORK)/rtl.f" Rob "$(ROB_GRHSIM_FLAT_GRH)" \
		"$(ROB_WORK)/emit_grhsim.json" "$(ROB_WORK)/emit_roundtrip.json" \
		"$(ROB_WORK)/read_args.txt" info --no-keep-origins $(ROB_GRHSIM_RESUME) \
		$(ROB_GRHSIM_EXTRA_FLAGS) \
		--emit-cpp-dir "$(ROB_GRHSIM_MODEL_DIR)" \
		> "$(ROB_WORK)/grhsim_model_gen.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-grhsim-model] emit rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/grhsim_model_gen.log"; exit $$rc; fi
	@test -f "$(ROB_GRHSIM_MODEL_DIR)/Makefile"

$(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a: $(ROB_GRHSIM_MODEL_DIR)/Makefile $(ROB_WORK)/.asserts-stripped
	@start=$$(date +%s); \
	$(MAKE) --no-print-directory -C "$(ROB_GRHSIM_MODEL_DIR)" -j$(ROB_JOBS) \
		CXX="$(CXX)" CXXFLAGS="$(ROB_GRHSIM_CXXFLAGS)" \
		> "$(ROB_WORK)/grhsim_model_build.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-grhsim-model] build rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/grhsim_model_build.log"; exit $$rc; fi

$(ROB_BENCH_DIR)/rob_bench.cpp: scripts/gen_rob_bench.py $(ROB_GSIM_MODEL_DIR)/.patched $(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp
	@mkdir -p "$(ROB_BENCH_DIR)"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/gen_rob_bench.py \
		--top Rob \
		--gsim-header "$(ROB_GSIM_MODEL_DIR)/Rob.h" \
		--grhsim-header "$(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp" \
		--sv "$(ROB_FIXTURE)/rtl/Rob.sv" \
		--out "$@" \
		--pairing "$(ROB_WORK)/port_pairing.tsv"

$(ROB_BENCH_DIR)/rob_bench: $(ROB_BENCH_DIR)/rob_bench.cpp $(ROB_GSIM_OBJ_DIR)/.stamp $(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a
	@start=$$(date +%s); \
	$(CXX) $(ROB_BENCH_CXXFLAGS) -I"$(ROB_GSIM_MODEL_DIR)" -I"$(ROB_GRHSIM_MODEL_DIR)" \
		"$(ROB_BENCH_DIR)/rob_bench.cpp" $(ROB_GSIM_OBJ_DIR)/*.o \
		"$(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a" -o $@ \
		> "$(ROB_WORK)/bench_build.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-bench] tb build rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/bench_build.log"; exit $$rc; fi

rob-bench: $(ROB_BENCH_DIR)/rob_bench
	@start=$$(date +%s); \
	set -o pipefail; "$(ROB_BENCH_DIR)/rob_bench" \
		--vectors $(ROB_BENCH_VECTORS) --verify $(ROB_BENCH_VERIFY) --repeat $(ROB_BENCH_REPEAT) \
		2>&1 | tee "$(ROB_WORK)/bench.log"; \
	rc=$${PIPESTATUS[0]}; end=$$(date +%s); \
	echo "[rob-bench] run rc=$$rc elapsed_s=$$((end - start))" | tee -a "$(ROB_WORK)/bench.log"; \
	exit $$rc

# Driver functions shared by analysis probes (probe_phase, ...).
$(ROB_BENCH_DIR)/rob_bench_lib.o: $(ROB_BENCH_DIR)/rob_bench.cpp
	$(CXX) $(ROB_BENCH_CXXFLAGS) -I"$(ROB_GSIM_MODEL_DIR)" -I"$(ROB_GRHSIM_MODEL_DIR)" \
		-DROB_BENCH_NO_MAIN -c "$<" -o $@

.PHONY: rob-phase-probe
rob-phase-probe: $(ROB_WORK)/probe_phase
	"$(ROB_WORK)/probe_phase" 20000

$(ROB_WORK)/probe_phase: $(ROB_WORK)/probe_phase.cpp $(ROB_BENCH_DIR)/rob_bench_lib.o $(ROB_GSIM_OBJ_DIR)/.stamp $(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a
	$(CXX) $(ROB_BENCH_CXXFLAGS) -I"$(ROB_GSIM_MODEL_DIR)" -I"$(ROB_GRHSIM_MODEL_DIR)" \
		"$<" "$(ROB_BENCH_DIR)/rob_bench_lib.o" $(ROB_GSIM_OBJ_DIR)/*.o \
		"$(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a" -o $@

# Full-system trace targets using scalarized Rob ports have been retired.
