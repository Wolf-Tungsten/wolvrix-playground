# NO0582 GrhSIM IR CPU Unchanged State HDLBits Gate

- 日期：2026-09-07
- 前置：[NO0580](./NO0580_grhsim_ir_cpu_unchanged_state_staging_20260907.md)

## Full Recheck

安装包含不变状态入队修复的 Python 包后，通过原有 Makefile 完整重跑 IR HDLBits：

```sh
make --no-print-directory run_all_hdlbits_grhsim_ir_tests \
  SKIP_PY_INSTALL=1 WOLF_ENV_SOURCED=1 PYTHON="$PWD/.venv/bin/python" \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_ir_hdlbits_noop_state.log 2>&1
```

进程终态退出 0，162 个 `[RUN] DUT=` 记录，最后是
`dut_162 passed all prediction and training scenarios`。本次新产物目录为
`ptmp/hdlbits-grhsim-ir-ExFf6s`，未复用前次 GrhTB 可执行文件。

覆盖全部 162 个既有 GrhTB 的实际 GRH→IR→C++ O3 编译和运行断言，不是全量
Verilator 波形覆盖证明。多时钟独立 Verilator/记分板 gate 另见
[NO0581](./NO0581_grhsim_ir_cpu_multiclock_extended_gate_20260907.md)。

本复跑与 gate56 构建并行，不使用其耗时作性能比较。XiangShan 10k/50k 及 50k
性能要求仍未完成。
