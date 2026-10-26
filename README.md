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

make xs_grhsim_emu
make run_xs_grhsim_emu XS_SIM_MAX_CYCLE=100000

make -C testcase/xs-bugcase/CASE_006 run

```

The XiangShan flow requires `preserve-aggregate=all`. Mux1H/masked-OR recovery,
state-write normalization, dynamic-write recovery, aggregate alias elimination,
and direct aggregate row copies are enabled by default. The standard GrhSIM
build uses `-O3 -march=native -fno-strict-aliasing` without PGO; the resulting
emulator targets the build host's CPU.

Simulation now uses the same GRH design through conversion, optimization,
virtual partitioning and C++ emission. The independent GrhSIM IR and Python
model APIs have been removed. The active XiangShan route is `xs_grhsim_emu`
and `run_xs_grhsim_emu`. See the [simulation workflow](wolvrix/docs/grhsim.md)
and [current implementation](pdocs/grhsim.md)
for the six scheduling phases, passes, dialect operations and emitter layout.

## Output Locations

HDLBits:

- `build/hdlbits/<DUT>/`

OpenC910:

- work directory: `testcase/openc910/smart_run/work/`
- logs: `build/logs/c910/`

XiangShan:

- RTL, checkpoints, models and emulators: `ptmp/xs/`
- logs and waveforms: `ptmp/xs/logs/`
- generated sources and macros: `testcase/xiangshan/build/generated-src/`

XS bugcases:

- `build/xs_bugcase/CASE_*/`
