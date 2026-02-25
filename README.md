# wolvrix-playground

## Test Environment (optional)

Copy and source the environment file:

```bash
cp env.sh.template env.sh
source env.sh
```

Edit `env.sh` if you need:
- `TOOL_EXTENSION`: RISC-V toolchain bin path (OpenC910)
- `VERILATOR`: path to verilator (if not in PATH)
- `NOOP_HOME`: XiangShan root (defaults to `testcase/xiangshan`)

## Test Commands

Run from the playground root:

```bash
# HDLBits
make run_hdlbits_test DUT=001
make run_all_hdlbits_tests

# OpenC910
make run_c910_test

# XiangShan
make xs_rtl
make xs_wolf_emit
make xs_ref_emu
make run_xs_diff
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
