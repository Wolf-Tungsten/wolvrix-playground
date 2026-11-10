# XiangShan Wolvrix GrhSIM RepCut build

From the repository root:

```bash
git submodule update --init --recursive
make xs_wolf_grhsim_repcut_emu
```

`make xs_grhsim` and `make build_xs_repcut_grhsim` remain compatibility aliases
for the default pipeline. No `env.sh`,
optimization environment variables, previous experiment outputs, partition labels,
or historical regression executable are required.

## Prerequisites

Use an x86-64 Linux machine with at least 32 available logical CPUs and enough RAM
for the XiangShan design. The full model needs tens of GB during individual
generation stages; 128 GB or more is recommended. Install Python 3.10+, CMake
3.26+, Git, Make, a C++20 compiler, binutils, Boost Program Options development
files, zlib and Zstandard development files. For example, on Ubuntu:

```bash
sudo apt install build-essential clang cmake git python3 libboost-program-options-dev zlib1g-dev libzstd-dev
```

The first build needs network access to fetch submodules and build dependencies.
The native tools prefer the system GCC. Generated model code uses `CXX` when set,
otherwise Clang if installed, then GCC. Model compilation uses
`-std=c++20 -O3 -march=native -pthread` with 64-byte executable section alignment;
it does not add `-fno-slp-vectorize`. Build on the machine where the emulator will run.

The default command invokes XiangShan's `sim-verilog` target in this build's
output directory, even when `build/xs/rtl/rtl/SimTop.sv` already exists. It does
not silently reuse that older RTL. This needs the JDK / Scala / mill prerequisites described in
[XiangShan's README](../testcase/xiangshan/README.md). The selected XiangShan
submodule supplies the CoreMark image and NEMU shared library used at the end.

## Default pipeline

1. Build the current Wolvrix sources and native pipeline tools. Fetch and build
   the pinned Mt-KaHyPar multi-constraint sources with the checked-in fallback patch.
2. Generate Verilog from the current XiangShan sources, then lower it into a new flat graph.
3. Run mem-to-reg according to the checked-in workload configuration.
4. Compute a new six-dimensional weighted hypergraph from the current graph and
   backend lowering. Automatically isolate oversized indivisible ASCs.
5. Solve eight independent initial assignments, seeds 0–7, in parallel. Select
   the feasible assignment with the lowest full-graph km1; seed breaks ties.
6. Replay that assignment, apply memory-write-coalesce and reg-to-mem, emit the
   complete GrhSIM preset, and compile/link the 32-thread emulator.
7. Run one functional smoke test against the completed emulator.
8. Publish the initial assignment as the user-facing `emu` launcher.

All design intermediates are generated afresh on each build. The pipeline
does not hash or compare intermediate inputs against prior records, and does not
run an execution-plan validation phase.
Ordinary compiler/dependency caches are separate from design outputs.

The complete settings are in [config/grhsim32.json](../config/grhsim32.json).
This configuration retains the current controlled memory stage: the same three
XiangShan memories and `row_limit=2`, applied anew to the current Verilog. It is
not a structural memory-selection experiment. No source/destination partition
numbers or old assignments occur in the configuration. The source graph and
all six load dimensions are recomputed, rather than imported from a historical HGR.

The default build and launcher inherit the caller's CPU placement. They do not
invoke `taskset`, `numactl`, or `setarch`, and the generated package does not pin
worker threads or enable code-page remapping unless the caller explicitly sets
those controls. The default flow performs no walltime search or post-run
repartition; `migration/result.json` records that migration is disabled.

## Performance exploration pipeline

The same `scripts/grhsim32.py` pipeline has an explicit measurement mode for
later performance exploration. It keeps the current 32-thread GrhSIM protocol:
it broadens build affinity, selects a 32-CPU runtime placement, uses
`taskset`/NUMA/ASLR controls when available, enables code-page handling, runs
walltime samples, profiles the initial package, and evaluates automatic
repartition candidates with AB/BA comparisons.

Use a separate output directory so the exploration artifacts do not replace the
user build:

```bash
make xs_wolf_grhsim_repcut_perf_emu
make run_xs_wolf_grhsim_repcut_perf_emu  # repeat the measurement protocol
make xs_wolf_grhsim_repcut_perf_plan     # print its stages without executing them
```

These Make targets pass `--performance` to the same Python entry point used by
`make xs_wolf_grhsim_repcut_emu`; they are not a second implementation. The default output is
`build/xs/grhsim32/`, while the performance output is
`build/xs/grhsim32-perf/`. The direct equivalent is:

```bash
python3 scripts/grhsim32.py --clean --performance \
  --output build/xs/grhsim32-perf
```

## Outputs and reruns

The default output is `build/xs/grhsim32/`:

- `emu`: executable launcher with the 32-thread runtime and default workload.
- `emu.bin`: link to the compiled ELF.
- `result.json`: selected seed, retained assignment, final timings and migration decision.
- `initial/runs/summary.json`: the default functional smoke result, or the
  performance-mode walltime samples.
- `migration/`: disabled metadata in the default build; automatic proposals,
  scores and the acceptance result in performance mode.
- `logs/`: dependency, RTL and generation logs.

The performance target uses the same layout under
`build/xs/grhsim32-perf/`, with walltime samples and automatic migration
artifacts populated.

```bash
make run_xs_wolf_grhsim_repcut_emu       # rerun the default functional smoke test
make xs_wolf_grhsim_repcut_plan          # print default stages without executing them
make run_xs_wolf_grhsim_repcut_perf_emu  # rerun the performance exploration output
make xs_wolf_grhsim_repcut_perf_plan     # print performance exploration stages
```

`make xs_wolf_grhsim_repcut_emu` starts a clean build and replaces only this pipeline's output.
The shorter `xs_grhsim`, `run_xs_repcut_grhsim`, and related names remain as
compatibility aliases.
The previous manual GrhSIM entry remains available as
`make build_xs_repcut_grhsim_legacy`; Verilator targets retain their existing behavior.

For a different Verilog input or build location, the Python entry accepts normal
input paths without requiring optimization flags. An explicit `--rtl` or
`--filelist` uses those supplied inputs instead of invoking the RTL generator:

```bash
python3 scripts/grhsim32.py --clean --rtl /path/to/rtl --generated /path/to/generated-src
```

Changing the workload's memory names or top module requires a corresponding
configuration. A different machine using the same XiangShan input uses the
default configuration without editing it.

## Optional RTL critical-path report

After a successful clean build, `make xs_wolf_grhsim_repcut_critical_path` creates an
independent diagnostic package and an interactive RTL/batch report. It leaves
the default build and production executable alone. See the
[critical-path analysis and AST rewrite guide](../wolvrix/docs/emit/grhsim-critical-path.md)
for sampling, source-mapping limits, page-mode control and validation commands.
