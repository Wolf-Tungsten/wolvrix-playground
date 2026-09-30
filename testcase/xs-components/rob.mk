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
ROB_SOURCE_RTL ?= $(ROB_REPO)/build/xs/rtl/rtl
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
		--reg-to-mem-row-constant-fill --reg-to-mem-or-write-merge \
		--reg-to-mem-report "$(ROB_WORK)/grhsim/reg_to_mem.tsv" \
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
		--reg-to-mem-row-constant-fill --reg-to-mem-or-write-merge \
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

# ---------------------------------------------------------------------------
# Trace-driven benchmark: replay the Rob I/O trace captured from the full
# XiangShan design (Verilator ref emu) through both standalone models.
# ---------------------------------------------------------------------------
ROB_TRACE_DIR := $(ROB_WORK)/trace
ROB_TRACE_SV := $(ROB_TRACE_DIR)/rob_tap.sv
ROB_TRACE_MANIFEST := $(ROB_TRACE_DIR)/tap_ports.json
ROB_TRACE_LAYOUT := $(ROB_TRACE_DIR)/layout.json
ROB_TRACE_BUILD := $(ROB_TRACE_DIR)/verilator-ref-emu
ROB_TRACE_BIN := $(ROB_TRACE_DIR)/rob_trace.bin
ROB_TRACE_CYCLES ?= 100000
ROB_TRACE_IMAGE ?= $(ROB_REPO)/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
ROB_TRACE_NEMU ?= $(ROB_REPO)/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
ROB_XS_ROOT := $(ROB_REPO)/testcase/xiangshan
ROB_XS_RTL := $(ROB_REPO)/build/xs/rtl/rtl
ROB_TRACE_JOBS ?= 32
ROB_TRACE_EMU_THREADS ?= 2

.PHONY: rob-trace-tap rob-trace-emu-build rob-trace-run rob-bench-trace

rob-trace-tap: $(ROB_TRACE_SV) $(ROB_TRACE_LAYOUT)

$(ROB_TRACE_SV): scripts/gen_rob_tap.py $(ROB_XS_RTL)/Rob.sv
	@mkdir -p "$(ROB_TRACE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/gen_rob_tap.py \
		--top Rob --sv "$(ROB_XS_RTL)/Rob.sv" \
		--out "$(ROB_TRACE_SV)" --manifest "$(ROB_TRACE_MANIFEST)"

$(ROB_TRACE_LAYOUT): scripts/gen_rob_bench.py $(ROB_GSIM_MODEL_DIR)/.patched $(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp
	@mkdir -p "$(ROB_TRACE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/gen_rob_bench.py \
		--top Rob \
		--gsim-header "$(ROB_GSIM_MODEL_DIR)/Rob.h" \
		--grhsim-header "$(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp" \
		--sv "$(ROB_FIXTURE)/rtl/Rob.sv" \
		--layout-out "$@"

# Verilator whole-design ref emu with the RobTap bound in (mirrors the root
# Makefile xs_ref_emu recipe, plus SIM_VSRC carrying the tap).
rob-trace-emu-build: $(ROB_TRACE_SV)
	@mkdir -p "$(ROB_TRACE_BUILD)"
	@start=$$(date +%s); \
	NOOP_HOME=$(ROB_XS_ROOT) $(MAKE) --no-print-directory -C "$(ROB_XS_ROOT)/difftest" emu \
		BUILD_DIR="$(ROB_TRACE_BUILD)" \
		GEN_CSRC_DIR="$(ROB_XS_ROOT)/build/generated-src" \
		GEN_VSRC_DIR="$(ROB_XS_ROOT)/build/generated-src" \
		RTL_DIR="$(ROB_XS_RTL)" \
		SIM_TOP_V="$(ROB_XS_RTL)/SimTop.sv" \
		NUM_CORES=1 \
		RTL_SUFFIX=sv \
		EMU_THREADS=$(ROB_TRACE_EMU_THREADS) \
		VM_BUILD_JOBS=$(ROB_TRACE_JOBS) \
		EMU_RANDOMIZE=0 \
		SIM_VFLAGS="+define+DIFFTEST" \
		WITH_CHISELDB=0 \
		WITH_CONSTANTIN=0 \
		SIM_VSRC="$$(find "$(ROB_XS_ROOT)/difftest/src/test/vsrc/common" -name '*.v' -or -name '*.sv' | tr '\n' ' ') $(ROB_TRACE_SV)" \
		> "$(ROB_TRACE_DIR)/emu_build.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-trace-emu-build] rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -40 "$(ROB_TRACE_DIR)/emu_build.log"; exit $$rc; fi

# Stream the text trace through a FIFO straight into the packed binary so the
# raw text (which is larger) never touches disk. The tap falls back to
# $fopen("rob_trace.txt") in the emu cwd because the difftest arg parser
# rejects unknown +plusargs, so the FIFO lives in the build dir under that
# fixed name.
rob-trace-run: $(ROB_TRACE_LAYOUT)
	@test -x "$(ROB_TRACE_BUILD)/emu" || { echo "run rob-trace-emu-build first"; exit 1; }
	@rm -f "$(ROB_TRACE_BUILD)/rob_trace.txt" "$(ROB_TRACE_BIN)"
	@mkfifo "$(ROB_TRACE_BUILD)/rob_trace.txt"
	@start=$$(date +%s); \
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/pack_rob_trace.py \
		--manifest "$(ROB_TRACE_MANIFEST)" --layout "$(ROB_TRACE_LAYOUT)" \
		--in "$(ROB_TRACE_BUILD)/rob_trace.txt" --out "$(ROB_TRACE_BIN)" \
		> "$(ROB_TRACE_DIR)/pack.log" 2>&1 & \
	pack_pid=$$!; \
	cd "$(ROB_TRACE_BUILD)" && \
		./emu -i "$(ROB_TRACE_IMAGE)" --diff "$(ROB_TRACE_NEMU)" -b 0 -e 0 \
		-C $(ROB_TRACE_CYCLES) \
		> "$(ROB_TRACE_DIR)/emu_run.log" 2>&1; \
	emu_rc=$$?; \
	for i in $$(seq 1 30); do kill -0 $$pack_pid 2>/dev/null || break; sleep 1; done; \
	if kill -0 $$pack_pid 2>/dev/null; then \
		echo "[rob-trace-run] packer stuck after emu exit; killing"; \
		kill $$pack_pid 2>/dev/null; \
	fi; \
	wait $$pack_pid; pack_rc=$$?; end=$$(date +%s); \
	rm -f "$(ROB_TRACE_BUILD)/rob_trace.txt"; \
	echo "[rob-trace-run] emu_rc=$$emu_rc pack_rc=$$pack_rc elapsed_s=$$((end - start))"; \
	if [ $$emu_rc -ne 0 ]; then tail -30 "$(ROB_TRACE_DIR)/emu_run.log"; fi; \
	if [ $$pack_rc -ne 0 ]; then tail -30 "$(ROB_TRACE_DIR)/pack.log"; fi; \
	test $$emu_rc -eq 0 -a $$pack_rc -eq 0

rob-bench-trace: $(ROB_BENCH_DIR)/rob_bench
	@test -f "$(ROB_TRACE_BIN)"
	@start=$$(date +%s); \
	set -o pipefail; "$(ROB_BENCH_DIR)/rob_bench" \
		--trace "$(ROB_TRACE_BIN)" --verify $(ROB_BENCH_VERIFY) --repeat $(ROB_BENCH_REPEAT) \
		2>&1 | tee "$(ROB_WORK)/bench_trace.log"; \
	rc=$${PIPESTATUS[0]}; end=$$(date +%s); \
	echo "[rob-bench-trace] run rc=$$rc elapsed_s=$$((end - start))" | tee -a "$(ROB_WORK)/bench_trace.log"; \
	exit $$rc

.PHONY: rob-trace-phase-probe
rob-trace-phase-probe: $(ROB_WORK)/probe_trace_phase
	@test -f "$(ROB_TRACE_BIN)"
	"$(ROB_WORK)/probe_trace_phase" "$(ROB_TRACE_BIN)" "$(ROB_TRACE_DIR)/trace_phase.csv" \
		2>&1 | tee "$(ROB_TRACE_DIR)/trace_phase.log"

$(ROB_WORK)/probe_trace_phase: $(ROB_WORK)/probe_trace_phase.cpp $(ROB_BENCH_DIR)/rob_bench_lib.o $(ROB_GSIM_OBJ_DIR)/.stamp $(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a
	$(CXX) $(ROB_BENCH_CXXFLAGS) -I"$(ROB_GSIM_MODEL_DIR)" -I"$(ROB_GRHSIM_MODEL_DIR)" \
		"$<" "$(ROB_BENCH_DIR)/rob_bench_lib.o" $(ROB_GSIM_OBJ_DIR)/*.o \
		"$(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a" -o $@
