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

make -C testcase/xs-bugcase/CASE_006 run

make build_xs_repcut_verilator -j
make run_xs_repcut_verilator XS_EMU_THREADS=32 XS_REPCUT_STEP_TIMING=1 XS_SIM_MAX_CYCLE=30000
```

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
