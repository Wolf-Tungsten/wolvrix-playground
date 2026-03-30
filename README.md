# wolvrix-playground

## Quick Start

Initialize the Python virtual environment first, then load the playground environment:

```bash
source setup_pyvenv.sh

cp env.sh.template env.sh
source env.sh
```

If `env.sh` already exists, just run:

```bash
source setup_pyvenv.sh
source env.sh
```

Edit `env.sh` if needed:
- `TOOL_EXTENSION`: RISC-V toolchain bin path (OpenC910)
- `VERILATOR`: path to verilator (if not in PATH)
- `NOOP_HOME`: XiangShan root (defaults to `testcase/xiangshan`)

## Test Commands

Run from the playground root:

```bash
# Python bindings (required for wolvrix emit steps, built via scikit-build-core)
make py_install

# HDLBits
make run_hdlbits_test DUT=001
make run_all_hdlbits_tests

# OpenC910
make run_c910_test
make run_c910_ref_test

# XiangShan
make run_xs_diff -j

# XS bugcases (standalone)
make -C testcase/xs-bugcase/CASE_006 run

# XiangShan RepCut Verilator
make build_xs_repcut_verilator -j
make run_xs_repcut_verilator XS_EMU_THREADS=32 XS_REPCUT_STEP_TIMING=1 XS_SIM_MAX_CYCLE=30000
```

## Outputs

### HDLBits
- `build/hdlbits/<DUT>/`

### OpenC910
- Work dir: `testcase/openc910/smart_run/work/`
- Logs: `build/logs/c910/`

### XiangShan
- Build outputs: `build/xs/`
- Logs/waveforms: `build/logs/xs/`
- Generated-src/macros: `testcase/xiangshan/build/generated-src/`

### XS bugcases
- Outputs: `build/xs_bugcase/CASE_*/`
