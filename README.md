# wolvrix-playground

This repository is the development and integration workspace for Wolvrix.

It contains:

- the Wolvrix source tree itself
- test suites and fixtures
- helper scripts for HDLBits, OpenC910, and XiangShan flows

If you are new to the project, the easiest way to interact with Wolvrix is through its Python API. The current Python API is centered around a `Session` object. You read a design into the session, run passes against a design key, optionally store intermediate results under other keys, and finally emit or store files from that same session.

## Quick Start

```bash
cp env.sh.template env.sh
source env.sh
```

If `env.sh` already exists:

```bash
source env.sh
```

What `env.sh` does:

- bootstraps the local `.venv`
- installs `scikit-build-core`
- configures common tool paths used by the playground

Important environment variables:

- `TOOL_EXTENSION`: OpenC910 RISC-V toolchain path
- `VERILATOR`: Verilator path
- `NOOP_HOME`: XiangShan root, usually `testcase/xiangshan`

## Recommended Wolvrix Workflow

```python
import wolvrix

with wolvrix.Session() as sess:
    sess.set_log_level("info")
    sess.set_diagnostics_policy("error")

    sess.read_sv(
        "top.sv",
        out_design="design.main",
        slang_args=["--top", "top"],
    )

    sess.run_pass("xmr-resolve", design="design.main")
    sess.run_pass("simplify", design="design.main")
    sess.run_pass("stats", design="design.main", out_stats="stats.main")

    sess.store_json(design="design.main", output="build/main.json")
    sess.emit_sv(design="design.main", output="build/main.sv")
```

Why it works this way:

- `read_sv(...)` stores a design into the session under `design.main`
- `run_pass(...)` modifies that design in place
- `out_stats="stats.main"` stores an additional result in the same session
- `store_json(...)` and `emit_sv(...)` read the design back from the session and write files

Naming rules:

- use `out_design=...` when an action creates or loads a design
- use `design=...` for the design being operated on
- use `in_*` and `out_*` for session-based inputs and outputs

For the full user-facing API, see [wolvrix/README.md](wolvrix/README.md).

## Common Commands

Run these from the playground root:

```bash
make py_install

make run_hdlbits_test DUT=001
make run_all_hdlbits_tests

make run_c910_test
make run_c910_ref_test

make run_xs_diff -j

make xs_wolf_grhsim_emu
make xs_wolf_grhsim_emu PGO_WORKLOAD=testcase/xiangshan/ready-to-run/coremark-2-iteration.bin

make xs_wolf_grhsim_repcut_emu  # XiangShan Wolvrix GrhSIM RepCut, 32-thread functional emu
make xs_wolf_grhsim_repcut_perf_emu  # same pipeline with walltime/placement/migration
make xs_wolf_grhsim_repcut_critical_path  # optional RTL / batch diagnostic report

make -C testcase/xs-bugcase/CASE_006 run

make build_xs_repcut_verilator -j
make run_xs_repcut_verilator XS_EMU_THREADS=32 XS_REPCUT_STEP_TIMING=1 XS_SIM_MAX_CYCLE=30000
```

### XiangShan single-model GrhSIM

The `xs_wolf_grhsim_emu` target selects its defaults from `PGO_WORKLOAD`.

| Single-model build | Compute supernode limit | Registers per commit data block | Event regions, conditional mux, covered state views |
| --- | ---: | ---: | --- |
| Ordinary (`PGO_WORKLOAD` unset or empty) | 108 ops | Up to 4 | Off |
| PGO (`PGO_WORKLOAD` set to a training image) | 160 ops | Up to 16 | On, conditional mux threshold 16 ops |

Both modes use 108 operations for the compute node and split limits, a 16-byte limit per
commit data block, and `-O3 -march=native` for the generated model and DiffTest harness.
The resulting binary targets the CPU used for compilation.
Use `GRHSIM_MODEL_CXXFLAGS` and `EMU_OPTIMIZE` to override their respective compiler flags.
Use `WOLVRIX_XS_GRHSIM_MAX_OP_IN_COMPUTE_SUPERNODE` to override the supernode limit,
`WOLVRIX_GRHSIM_COMMIT_COMPARE_MAX_LANES` to select a block size, or
`WOLVRIX_GRHSIM_COMMIT_COMPARE_BLOCKS=0` to disable block comparisons.

PGO trains the model and harness with Clang for 100,000 cycles by default and publishes
`emu` and `grhsim.profdata` in `XS_GRHSIM_BUILD`. Set `PGO_MAX_CYCLE` to change the
training window and `LLVM_PROFDATA` to select the tool matching `CXX`.
For the original PGO baseline, set `WOLVRIX_XS_GRHSIM_PGO_GROUPS=0` alongside the
training image. With no individual overrides this selects 108 ops, disables the three
groups and disables commit block comparisons.

The XiangShan Wolvrix GrhSIM RepCut pipeline is documented in
[docs/grhsim32.md](docs/grhsim32.md). It builds from the current Verilog on the
local machine, runs eight initial solves, and publishes a functional emulator.
The optional `xs_wolf_grhsim_repcut_perf_emu` target uses the same pipeline with the explicit
walltime, placement, code-page, and automatic migration protocol.

## Output Locations

HDLBits:

- `build/hdlbits/<DUT>/`

OpenC910:

- work directory: `testcase/openc910/smart_run/work/`
- logs: `build/logs/c910/`

XiangShan:

- build outputs: `build/xs/`
- logs and waveforms: `build/logs/xs/`
- generated sources and macros: `testcase/xiangshan/build/generated-src/`

XS bugcases:

- `build/xs_bugcase/CASE_*/`
