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
# The aggregate (preserve-aggregate=all) XiangShan RTL is the only supported
# source: scalarized RTL generation was removed from the root Makefile.
ROB_SOURCE_RTL ?= $(ROB_REPO)/build/xs/rtl/rtl
GSIM_BIN ?= ../../reference/gsim/build/gsim/gsim
ROB_FIXTURE := $(abspath rob)
ROB_WORK ?= $(ROB_REPO)/ptmp/xs-components-rob
ROB_GSIM := $(abspath $(GSIM_BIN))

.PHONY: rob-extract rob-ir rob-gsim-ir rob-grhsim rob-compare rob-cones rob-report
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

rob-grhsim:
	@test -f "$(ROB_WORK)/rtl.f"
	@mkdir -p "$(ROB_WORK)/grhsim"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) "$(ROB_REPO)/scripts/wolvrix_xs_grhsim.py" \
		"$(ROB_WORK)/rtl.f" Rob "$(ROB_WORK)/grhsim/flat_grh.json" \
		"$(ROB_WORK)/grhsim/final.json" "$(ROB_WORK)/grhsim/roundtrip.json" \
		"$(ROB_WORK)/read_args.txt" info --keep-origins \
		--pack-bit-registers-report "$(ROB_WORK)/grhsim/pack_members.tsv" \
		--dump-post-conversion-json "$(ROB_WORK)/grhsim/post_conversion.json" \
		--dump-pre-partition-json "$(ROB_WORK)/grhsim/pre_partition.json" \
		> "$(ROB_WORK)/grhsim.log" 2>&1

rob-ir: rob-extract
	$(MAKE) --no-print-directory -j2 rob-gsim-ir rob-grhsim

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
ROB_BENCH_CXXFLAGS ?= -O3 -std=c++20 -Wno-bit-int-extension
ROB_BENCH_VECTORS ?= 100000
ROB_BENCH_VERIFY ?= 2048
ROB_BENCH_REPEAT ?= 3
ROB_JOBS ?= 16

# Checkpoint reuse is explicit: an older work directory may contain a
# scalar-RTL checkpoint that must not override the aggregate fixture.
ROB_GRHSIM_FLAT_GRH ?= $(ROB_WORK)/emit_flat_grh.json
ROB_GRHSIM_RESUME ?=
# Extra flags appended to the grhsim emit invocation, e.g.
# ROB_GRHSIM_EXTRA_FLAGS=--no-pack-bit-registers for A/B arms.
ROB_GRHSIM_EXTRA_FLAGS ?=

# S8 A/B: original models/trace stay read-only; regenerate candidate from original SV.
ROB_ARRAY_CREATE_BASE ?= $(ROB_REPO)/ptmp/xs-components-rob
ROB_ARRAY_CREATE_WORK ?= $(ROB_REPO)/ptmp/xs-components-rob-array-create
ROB_ARRAY_CREATE_CPU ?= 0
ROB_ARRAY_CREATE_PERF ?= perf
.PHONY: rob-array-create-prepare rob-array-create-build rob-array-create-dump-build rob-array-create-run rob-array-create-ab rob-array-create-audit rob-array-create-profile rob-array-create-profile-record rob-array-create-profile-report
rob-array-create-prepare:
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/rob_array_create_ab.py prepare \
		--baseline "$(ROB_ARRAY_CREATE_BASE)" --work "$(ROB_ARRAY_CREATE_WORK)"

rob-array-create-build: rob-array-create-prepare
	$(MAKE) --no-print-directory -B "$(ROB_ARRAY_CREATE_WORK)/candidate/grhsim-model/Makefile" \
		ROB_WORK="$(ROB_ARRAY_CREATE_WORK)/candidate" ROB_GRHSIM_RESUME=
	$(MAKE) --no-print-directory rob-bench-build ROB_WORK="$(ROB_ARRAY_CREATE_WORK)/candidate"

rob-array-create-dump-build: $(ROB_ARRAY_CREATE_WORK)/baseline/dump_outputs $(ROB_ARRAY_CREATE_WORK)/candidate/dump_outputs
$(ROB_ARRAY_CREATE_WORK)/baseline/dump_outputs: scripts/rob_array_create_dump.cpp $(ROB_ARRAY_CREATE_BASE)/bench/rob_bench.cpp $(ROB_ARRAY_CREATE_BASE)/grhsim-model/libgrhsim_Rob.a
	$(CXX) $(ROB_BENCH_CXXFLAGS) -DROB_BENCH_SOURCE='"$(ROB_ARRAY_CREATE_BASE)/bench/rob_bench.cpp"' \
		-I"$(ROB_ARRAY_CREATE_BASE)/gsim-model" -I"$(ROB_ARRAY_CREATE_BASE)/grhsim-model" "$<" \
		$(ROB_ARRAY_CREATE_BASE)/gsim-obj/*.o "$(ROB_ARRAY_CREATE_BASE)/grhsim-model/libgrhsim_Rob.a" -o "$@"

$(ROB_ARRAY_CREATE_WORK)/candidate/dump_outputs: scripts/rob_array_create_dump.cpp $(ROB_ARRAY_CREATE_WORK)/candidate/bench/rob_bench.cpp $(ROB_ARRAY_CREATE_WORK)/candidate/grhsim-model/libgrhsim_Rob.a
	$(CXX) $(ROB_BENCH_CXXFLAGS) -DROB_BENCH_SOURCE='"$(ROB_ARRAY_CREATE_WORK)/candidate/bench/rob_bench.cpp"' \
		-I"$(ROB_ARRAY_CREATE_WORK)/candidate/gsim-model" -I"$(ROB_ARRAY_CREATE_WORK)/candidate/grhsim-model" "$<" \
		$(ROB_ARRAY_CREATE_WORK)/candidate/gsim-obj/*.o "$(ROB_ARRAY_CREATE_WORK)/candidate/grhsim-model/libgrhsim_Rob.a" -o "$@"

rob-array-create-ab: rob-array-create-build
	$(MAKE) --no-print-directory rob-array-create-run

rob-array-create-run: rob-array-create-dump-build
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/rob_array_create_ab.py run \
		--baseline "$(ROB_ARRAY_CREATE_BASE)" --work "$(ROB_ARRAY_CREATE_WORK)" --cpu "$(ROB_ARRAY_CREATE_CPU)" \
		--repeat $(ROB_BENCH_REPEAT)

rob-array-create-audit:
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/rob_array_create_ab.py audit \
		--baseline "$(ROB_ARRAY_CREATE_BASE)" --work "$(ROB_ARRAY_CREATE_WORK)"

# Diagnostic sampling is separate from the unprofiled, three-repeat A/B.
rob-array-create-profile:
	$(MAKE) --no-print-directory rob-array-create-profile-record
	$(MAKE) --no-print-directory rob-array-create-profile-report

rob-array-create-profile-record:
	@mkdir -p "$(ROB_ARRAY_CREATE_WORK)/profile"
	sha256sum "$(ROB_ARRAY_CREATE_WORK)/candidate/bench/rob_bench" \
		"$(ROB_ARRAY_CREATE_BASE)/trace/layout.json" > "$(ROB_ARRAY_CREATE_WORK)/profile/sources.sha256"
	$(ROB_ARRAY_CREATE_PERF) record -e cycles:u -F 997 -o "$(ROB_ARRAY_CREATE_WORK)/profile/perf.data" -- \
		taskset -c "$(ROB_ARRAY_CREATE_CPU)" stdbuf -oL -eL "$(ROB_ARRAY_CREATE_WORK)/candidate/bench/rob_bench" \
		--model grhsim --trace "$(ROB_ARRAY_CREATE_BASE)/trace/rob_trace.bin" --verify 0 --repeat 1 \
		> "$(ROB_ARRAY_CREATE_WORK)/profile/run.log" 2>&1

rob-array-create-profile-report:
	$(ROB_ARRAY_CREATE_PERF) report --stdio --no-children --sort symbol --show-nr-samples \
		--show-total-period --percent-limit 0 --header \
		-i "$(ROB_ARRAY_CREATE_WORK)/profile/perf.data" > "$(ROB_ARRAY_CREATE_WORK)/profile/report.txt" \
		2> "$(ROB_ARRAY_CREATE_WORK)/profile/report.stderr"
	$(ROB_ARRAY_CREATE_PERF) script -F ip,sym,symoff,period -i "$(ROB_ARRAY_CREATE_WORK)/profile/perf.data" \
		> "$(ROB_ARRAY_CREATE_WORK)/profile/samples.txt" 2> "$(ROB_ARRAY_CREATE_WORK)/profile/samples.stderr"

.PHONY: rob-gsim-model rob-grhsim-model rob-bench-build rob-bench

rob-bench-build: $(ROB_BENCH_DIR)/rob_bench

rob-gsim-model: $(ROB_GSIM_OBJ_DIR)/.stamp

$(ROB_GSIM_MODEL_DIR)/Rob.h: $(ROB_WORK)/Rob_resolved.fir $(ROB_GSIM)
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
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) "$(ROB_REPO)/scripts/wolvrix_xs_grhsim.py" \
		"$(ROB_WORK)/rtl.f" Rob "$(ROB_GRHSIM_FLAT_GRH)" \
		"$(ROB_WORK)/emit_grhsim.json" "$(ROB_WORK)/emit_roundtrip.json" \
		"$(ROB_WORK)/read_args.txt" info $(ROB_GRHSIM_RESUME) \
		$(ROB_GRHSIM_EXTRA_FLAGS) \
		--emit-cpp-dir "$(ROB_GRHSIM_MODEL_DIR)" \
		> "$(ROB_WORK)/grhsim_model_gen.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-grhsim-model] emit rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/grhsim_model_gen.log"; exit $$rc; fi
	@test -f "$(ROB_GRHSIM_MODEL_DIR)/Makefile"

$(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp: $(ROB_GRHSIM_MODEL_DIR)/Makefile
	@test -f "$@"

$(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a: $(ROB_GRHSIM_MODEL_DIR)/Makefile $(ROB_WORK)/.asserts-stripped
	@start=$$(date +%s); \
	$(MAKE) --no-print-directory -C "$(ROB_GRHSIM_MODEL_DIR)" -j$(ROB_JOBS) \
		CXX="$(CXX)" CXXFLAGS="$(ROB_GRHSIM_CXXFLAGS)" \
		> "$(ROB_WORK)/grhsim_model_build.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-grhsim-model] build rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -30 "$(ROB_WORK)/grhsim_model_build.log"; exit $$rc; fi

$(ROB_BENCH_DIR)/rob_bench.cpp: scripts/gen_rob_bench.py $(ROB_GSIM_MODEL_DIR)/.patched $(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp $(ROB_FIXTURE)/rtl/Rob.sv
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
# The tap observes the aggregate Rob ports of the preserve-aggregate=all RTL
# ($fwrite %0h of each whole packed port); the packer slices the per-leaf
# record bits out of the port tokens via layout.json's sv_port/sv_offset.
# ---------------------------------------------------------------------------
ROB_TRACE_DIR := $(ROB_WORK)/trace
ROB_TRACE_SV := $(ROB_TRACE_DIR)/rob_tap.sv
ROB_TRACE_MANIFEST := $(ROB_TRACE_DIR)/tap_ports.json
ROB_TRACE_LAYOUT := $(ROB_TRACE_DIR)/layout.json
ROB_TRACE_BUILD := $(ROB_TRACE_DIR)/verilator-aggregate-emu
ROB_TRACE_BIN := $(ROB_TRACE_DIR)/rob_trace.bin
ROB_TRACE_CYCLES ?= 100000
ROB_TRACE_IMAGE ?= $(ROB_REPO)/testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
ROB_TRACE_NEMU ?= $(ROB_REPO)/testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
ROB_XS_ROOT := $(ROB_REPO)/testcase/xiangshan
ROB_XS_RTL := $(ROB_SOURCE_RTL)
ROB_TRACE_JOBS ?= 32
ROB_TRACE_EMU_THREADS ?= 2
ROB_TRACE_CCACHE_DIR ?= $(ROB_TRACE_DIR)/ccache
ROB_BENCH_TRACE_FLAGS ?=
ROB_TRACE_OUTPUT_MASK ?= $(ROB_TRACE_DIR)/fst_output_mask.bin
ROB_BENCH_PREFIX ?=
ROB_PLAIN_REF_BUILD ?= $(ROB_REPO)/build/xs/ref
ROB_PLAIN_REF_FST := $(ROB_TRACE_DIR)/xs_ref_rob_coremark100k.fst
ROB_PLAIN_REF_LOG := $(ROB_TRACE_DIR)/xs_ref_rob_coremark100k.log
ROB_TRACE_CONSTANT_PREFIX ?= $(wildcard $(ROB_TRACE_DIR)/rob_trace_aggregate_failed_10322.bin)
ROB_FST_OBJ_DIR := $(ROB_TRACE_DIR)/fst-obj
ROB_FST_C_OBJS := $(addprefix $(ROB_FST_OBJ_DIR)/,fstapi.o fastlz.o lz4.o)

$(ROB_FST_OBJ_DIR)/%.o: $(ROB_REPO)/wolvrix/external/libfst/src/%.c
	@mkdir -p "$(ROB_FST_OBJ_DIR)"
	$(CC) -O2 -D_GNU_SOURCE -I"$(ROB_REPO)/wolvrix/external/libfst/src" -c "$<" -o "$@"

$(ROB_TRACE_DIR)/pack_rob_fst: scripts/pack_rob_fst.cpp $(ROB_FST_C_OBJS)
	$(CXX) -O2 -std=c++20 -Wall -Wextra -I"$(ROB_REPO)/wolvrix/external/libfst/src" \
		"$<" $(ROB_FST_C_OBJS) -lz -o "$@"

$(ROB_TRACE_DIR)/test_rob_fst_fixture: scripts/test_rob_fst_fixture.cpp $(ROB_FST_C_OBJS)
	$(CXX) -O2 -std=c++20 -I"$(ROB_REPO)/wolvrix/external/libfst/src" \
		"$<" $(ROB_FST_C_OBJS) -lz -o "$@"

.PHONY: rob-trace-plain-pack rob-trace-constant-check
rob-trace-plain-pack: rob-trace-plain-plan $(ROB_TRACE_DIR)/pack_rob_fst
	"$(ROB_TRACE_DIR)/pack_rob_fst" "$(ROB_PLAIN_REF_FST)" "$(ROB_TRACE_DIR)/fst_plan.tsv" \
		"$(ROB_TRACE_BIN)" "$(ROB_TRACE_DIR)/capture_summary.json" $(ROB_TRACE_CYCLES)
	sha256sum "$(ROB_TRACE_LAYOUT)" "$(ROB_TRACE_BIN)" "$(ROB_TRACE_DIR)/fst_output_mask.bin" \
		> "$(ROB_TRACE_DIR)/replay.sha256"
	sha256sum "$(ROB_PLAIN_REF_FST)" "$(ROB_TRACE_DIR)/fst_mapping.json" "$(ROB_TRACE_DIR)/fst_plan.tsv" \
		"$(ROB_PLAIN_REF_LOG)" "$(ROB_FIXTURE)/manifest.json" \
		$(if $(ROB_TRACE_CONSTANT_PREFIX),"$(ROB_TRACE_CONSTANT_PREFIX)") \
		"$(ROB_GSIM_MODEL_DIR)"/Rob*.cpp scripts/map_rob_fst.py scripts/pack_rob_fst.cpp \
		> "$(ROB_TRACE_DIR)/fst_sources.sha256"

rob-trace-constant-check:
	@test -f "$(ROB_TRACE_CONSTANT_PREFIX)" || { echo 'set ROB_TRACE_CONSTANT_PREFIX to a captured aggregate prefix'; exit 1; }
	$(MAKE) --no-print-directory rob-trace-plain-plan ROB_TRACE_CONSTANT_PREFIX="$(ROB_TRACE_CONSTANT_PREFIX)"

.PHONY: rob-trace-plain-wave rob-trace-plain-plan
rob-trace-plain-wave:
	@mkdir -p "$(ROB_TRACE_DIR)"
	@sha256sum "$(ROB_PLAIN_REF_BUILD)/emu" "$(ROB_TRACE_IMAGE)" "$(ROB_TRACE_NEMU)" \
		> "$(ROB_TRACE_DIR)/plain_reference_sources.sha256"
	source "$(ROB_REPO)/env.sh" && $(MAKE) --no-print-directory -C "$(ROB_REPO)" run_xs_ref_emu \
		XS_REF_BUILD="$(ROB_PLAIN_REF_BUILD)" XS_SIM_MAX_CYCLE=$(ROB_TRACE_CYCLES) \
		XS_LOG_DIR="$(ROB_TRACE_DIR)" XS_WAVEFORM_DIR="$(ROB_TRACE_DIR)" \
		XS_WAVEFORM=1 XS_WAVEFORM_FULL=1 XS_COMMIT_TRACE=1 \
		XS_PROGRESS_EVERY_CYCLES=10000 XS_LOG_BEGIN=0 XS_LOG_END=-1 \
		RUN_ID=rob_coremark100k

$(ROB_REPO)/build/fst_diff/fst_diff:
	source "$(ROB_REPO)/env.sh" && $(MAKE) --no-print-directory -C "$(ROB_REPO)" build_fst_diff

rob-trace-plain-plan: $(ROB_TRACE_LAYOUT) $(ROB_REPO)/build/fst_diff/fst_diff
	@sha256sum --check --status "$(ROB_TRACE_DIR)/plain_reference_sources.sha256"
	"$(ROB_REPO)/build/fst_diff/fst_diff" signals "$(ROB_PLAIN_REF_FST)" --filter '.rob.' \
		> "$(ROB_TRACE_DIR)/plain_rob_signals.tsv"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/map_rob_fst.py \
		--signals "$(ROB_TRACE_DIR)/plain_rob_signals.tsv" --layout "$(ROB_TRACE_LAYOUT)" \
		--pairing "$(ROB_WORK)/port_pairing.tsv" --gsim-dir "$(ROB_GSIM_MODEL_DIR)" \
		--mask "$(ROB_TRACE_DIR)/fst_output_mask.bin" \
		--reference-log "$(ROB_PLAIN_REF_LOG)" --cycles $(ROB_TRACE_CYCLES) \
		$(if $(ROB_TRACE_CONSTANT_PREFIX),--constant-check "$(ROB_TRACE_CONSTANT_PREFIX)") \
		--out "$(ROB_TRACE_DIR)/fst_plan.tsv" --audit "$(ROB_TRACE_DIR)/fst_mapping.json"

.PHONY: rob-test-scripts
rob-test-scripts: $(ROB_TRACE_DIR)/pack_rob_fst $(ROB_TRACE_DIR)/test_rob_fst_fixture
	@mkdir -p "$(ROB_REPO)/ptmp/rob-script-tests"
	ROB_FST_PACKER="$(ROB_TRACE_DIR)/pack_rob_fst" ROB_FST_FIXTURE="$(ROB_TRACE_DIR)/test_rob_fst_fixture" \
		PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) -m unittest discover -s scripts -p 'test_rob_trace.py' -v

# Verilator 5.051 rejects the aggregate RTL where a packed-struct field is
# named `until` (an SVA keyword): VecExcpDataMergeModule.sv and
# NfMappedElemIdx.sv. The ref emu therefore builds from a shadow copy of the
# RTL tree (symlinks; the two offending files are patched copies with the
# field renamed `until` -> `until_f`, a pure identifier rename that keeps the
# netlist bit-identical). Neither module is part of the Rob dependency
# closure, so the fixture and the standalone models are unaffected.
ROB_TRACE_RTL_SHADOW := $(ROB_TRACE_DIR)/rtl-shadow

$(ROB_TRACE_RTL_SHADOW)/.stamp: $(ROB_XS_RTL)/VecExcpDataMergeModule.sv $(ROB_XS_RTL)/NfMappedElemIdx.sv
	@rm -rf "$(ROB_TRACE_RTL_SHADOW)"
	@mkdir -p "$(ROB_TRACE_RTL_SHADOW)"
	@for f in "$(ROB_XS_RTL)"/*.sv "$(ROB_XS_RTL)"/*.v "$(ROB_XS_RTL)"/*.fir; do \
		ln -s "$$f" "$(ROB_TRACE_RTL_SHADOW)/$$(basename "$$f")"; \
	done
	@rm -f "$(ROB_TRACE_RTL_SHADOW)/VecExcpDataMergeModule.sv" "$(ROB_TRACE_RTL_SHADOW)/NfMappedElemIdx.sv"
	sed 's/\buntil\b/until_f/g' "$(ROB_XS_RTL)/VecExcpDataMergeModule.sv" > "$(ROB_TRACE_RTL_SHADOW)/VecExcpDataMergeModule.sv"
	sed 's/\buntil\b/until_f/g' "$(ROB_XS_RTL)/NfMappedElemIdx.sv" > "$(ROB_TRACE_RTL_SHADOW)/NfMappedElemIdx.sv"
	@touch $@

.PHONY: rob-trace-tap rob-trace-layout-check rob-trace-emu-build rob-trace-run rob-bench-trace rob-bench-proof

rob-trace-tap: $(ROB_TRACE_SV) $(ROB_TRACE_LAYOUT)

rob-trace-layout-check: rob-trace-tap
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/pack_rob_trace.py \
		--manifest "$(ROB_TRACE_MANIFEST)" --layout "$(ROB_TRACE_LAYOUT)" --check-layout

$(ROB_TRACE_SV): scripts/gen_rob_tap.py $(ROB_XS_RTL)/Rob.sv
	@mkdir -p "$(ROB_TRACE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/gen_rob_tap.py \
		--top Rob --sv "$(ROB_XS_RTL)/Rob.sv" \
		--out "$(ROB_TRACE_SV)" --manifest "$(ROB_TRACE_MANIFEST)"

$(ROB_TRACE_LAYOUT): scripts/gen_rob_bench.py $(ROB_GSIM_MODEL_DIR)/.patched $(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp $(ROB_FIXTURE)/rtl/Rob.sv
	@mkdir -p "$(ROB_TRACE_DIR)"
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/gen_rob_bench.py \
		--top Rob \
		--gsim-header "$(ROB_GSIM_MODEL_DIR)/Rob.h" \
		--grhsim-header "$(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp" \
		--sv "$(ROB_FIXTURE)/rtl/Rob.sv" \
		--layout-out "$@"

# Verilator whole-design ref emu with the RobTap bound in (mirrors the root
# Makefile xs_ref_emu recipe, plus SIM_VSRC carrying the tap). Built from
# the shadow RTL tree (see ROB_TRACE_RTL_SHADOW above).
rob-trace-emu-build: $(ROB_TRACE_SV) $(ROB_TRACE_RTL_SHADOW)/.stamp
	@mkdir -p "$(ROB_TRACE_BUILD)" "$(ROB_TRACE_CCACHE_DIR)"
	@start=$$(date +%s); \
	CCACHE_DIR="$(ROB_TRACE_CCACHE_DIR)" NOOP_HOME=$(ROB_XS_ROOT) $(MAKE) --no-print-directory -C "$(ROB_XS_ROOT)/difftest" emu \
		BUILD_DIR="$(ROB_TRACE_BUILD)" \
		GEN_CSRC_DIR="$(ROB_XS_ROOT)/build/generated-src" \
		GEN_VSRC_DIR="$(ROB_XS_ROOT)/build/generated-src" \
		RTL_DIR="$(ROB_TRACE_RTL_SHADOW)" \
		SIM_TOP_V="$(ROB_TRACE_RTL_SHADOW)/SimTop.sv" \
		NUM_CORES=1 \
		RTL_SUFFIX=sv \
		EMU_THREADS=$(ROB_TRACE_EMU_THREADS) \
		VM_BUILD_JOBS=$(ROB_TRACE_JOBS) \
		EMU_RANDOMIZE=0 \
		SIM_VFLAGS="+define+DIFFTEST -Wno-fatal" \
		WITH_CHISELDB=0 \
		WITH_CONSTANTIN=0 \
		SIM_VSRC="$$(find "$(ROB_XS_ROOT)/difftest/src/test/vsrc/common" -name '*.v' -or -name '*.sv' | tr '\n' ' ') $(ROB_TRACE_SV)" \
		> "$(ROB_TRACE_DIR)/emu_build.log" 2>&1; \
	rc=$$?; end=$$(date +%s); \
	echo "[rob-trace-emu-build] rc=$$rc elapsed_s=$$((end - start))"; \
	if [ $$rc -ne 0 ]; then tail -40 "$(ROB_TRACE_DIR)/emu_build.log"; exit $$rc; fi
	@sha256sum "$(ROB_TRACE_SV)" "$(ROB_XS_RTL)/Rob.sv" \
		"$(ROB_TRACE_BUILD)/emu" > "$(ROB_TRACE_DIR)/emu_build.sha256"

# Stream the text trace through a FIFO straight into the packed binary so the
# raw text (which is larger) never touches disk. The tap falls back to
# $fopen("rob_trace.txt") in the emu cwd because the difftest arg parser
# rejects unknown +plusargs, so the FIFO lives in the build dir under that
# fixed name.
rob-trace-run: rob-trace-layout-check
	@test -x "$(ROB_TRACE_BUILD)/emu" || { echo "run rob-trace-emu-build first"; exit 1; }
	@sha256sum --check --status "$(ROB_TRACE_DIR)/emu_build.sha256" || { echo "run rob-trace-emu-build for the current tap/RTL first"; exit 1; }
	@sha256sum "$(ROB_TRACE_IMAGE)" "$(ROB_TRACE_NEMU)" "$(ROB_FIXTURE)/manifest.json" \
		> "$(ROB_TRACE_DIR)/capture_sources.sha256"
	@rm -f "$(ROB_TRACE_BUILD)/rob_trace.txt" "$(ROB_TRACE_BIN).partial"
	@mkfifo "$(ROB_TRACE_BUILD)/rob_trace.txt"
	@start=$$(date +%s); \
	PYTHONDONTWRITEBYTECODE=1 $(ROB_PYTHON) scripts/pack_rob_trace.py \
		--manifest "$(ROB_TRACE_MANIFEST)" --layout "$(ROB_TRACE_LAYOUT)" \
		--in "$(ROB_TRACE_BUILD)/rob_trace.txt" --out "$(ROB_TRACE_BIN).partial" \
		--min-cycles $(ROB_TRACE_CYCLES) --summary "$(ROB_TRACE_DIR)/capture_summary.json" \
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
	test $$emu_rc -eq 0 -a $$pack_rc -eq 0 && mv "$(ROB_TRACE_BIN).partial" "$(ROB_TRACE_BIN)"
	@sha256sum "$(ROB_TRACE_LAYOUT)" "$(ROB_TRACE_BIN)" > "$(ROB_TRACE_DIR)/replay.sha256"

rob-bench-trace: $(ROB_BENCH_DIR)/rob_bench
	@test -f "$(ROB_TRACE_BIN)"
	@sha256sum --check --status "$(ROB_TRACE_DIR)/replay.sha256" || { echo "trace/layout changed; run rob-trace-run again"; exit 1; }
	@start=$$(date +%s); \
	set -o pipefail; $(ROB_BENCH_PREFIX) "$(ROB_BENCH_DIR)/rob_bench" \
		--trace "$(ROB_TRACE_BIN)" --verify $(ROB_BENCH_VERIFY) --repeat $(ROB_BENCH_REPEAT) \
		$(if $(ROB_TRACE_OUTPUT_MASK),--trace-mask "$(ROB_TRACE_OUTPUT_MASK)") \
		$(ROB_BENCH_TRACE_FLAGS) \
		2>&1 | tee "$(ROB_WORK)/bench_trace.log"; \
	rc=$${PIPESTATUS[0]}; end=$$(date +%s); \
	echo "[rob-bench-trace] run rc=$$rc elapsed_s=$$((end - start))" | tee -a "$(ROB_WORK)/bench_trace.log"; \
	exit $$rc
	$(MAKE) --no-print-directory rob-bench-proof

rob-bench-proof:
	sha256sum "$(ROB_BENCH_DIR)/rob_bench" "$(ROB_BENCH_DIR)/rob_bench.cpp" \
		"$(ROB_GSIM_MODEL_DIR)"/Rob*.cpp "$(ROB_GSIM_MODEL_DIR)/Rob.h" \
		"$(ROB_GRHSIM_MODEL_DIR)"/*.cpp "$(ROB_GRHSIM_MODEL_DIR)/grhsim_Rob.hpp" \
		"$(ROB_GRHSIM_MODEL_DIR)/libgrhsim_Rob.a" "$(ROB_GSIM)" \
		"$(ROB_WORK)/Rob_resolved.fir" "$(ROB_FIXTURE)/rtl/Rob.sv" \
		"$(ROB_FIXTURE)/manifest.json" scripts/gen_rob_bench.py "$(ROB_WORK)/bench_trace.log" \
		> "$(ROB_TRACE_DIR)/bench_trace_sources.sha256"
