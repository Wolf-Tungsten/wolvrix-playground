# Clean 32-thread GrhSIM build

From the repository root:

```bash
git submodule update --init --recursive
make xs_grhsim
```

`make build_xs_repcut_grhsim` invokes the same default pipeline. No `env.sh`,
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
7. Run final NEMU functional tests and walltime measurements, then profile the
   completed emulator. Select migration sources and destinations automatically,
   subject to the existing communication budgets.
8. If a migration candidate exists, generate it and compare fresh AB/BA samples.
   Accept it only when both eight-pair rounds improve walltime with at least six
   wins per round. Otherwise retain the initial assignment.

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

Generation and compilation use all online CPUs permitted by the kernel; they
do not inherit an SSH shell's narrower affinity mask. Runtime selects 32 CPUs on
the local machine, preferring one NUMA domain and separate physical cores. The
host participates in the 32 lanes, with 31 background workers and all-spin
waiting. CPU numbers, NUMA node, and hostname are not fixed. Code THP is attempted
automatically, with normal pages available on kernels that cannot collapse them.
ASLR is disabled when permitted. Final run records include the actual lane
configuration and code-page coverage.

## Outputs and reruns

The default output is `build/xs/grhsim32/`:

- `emu`: executable launcher with the 32-thread runtime and default workload.
- `emu.bin`: link to the compiled ELF.
- `result.json`: selected seed, retained assignment, final timings and migration decision.
- `initial/runs/summary.json`: initial emulator's final functional/walltime samples.
- `migration/`: automatic proposals, scores and the acceptance result.
- `logs/`: dependency, RTL and generation logs.

```bash
make run_xs_repcut_grhsim   # measure the last built emulator again
make grhsim32_plan         # print the default stages without executing them
```

`make xs_grhsim` starts a clean build and replaces only this pipeline's output.
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
