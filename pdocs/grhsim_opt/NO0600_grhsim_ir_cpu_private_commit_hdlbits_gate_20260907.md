# NO0600 GrhSIM IR CPU Private Commit HDLBits Gate

- 日期：2026-09-07
- 前置：[NO0598](./NO0598_grhsim_ir_cpu_private_scalar_commit_implementation_20260907.md)

## Full Regression

唯一写者标量 direct commit 实现通过完整 HDLBits ingest/IR/CPU/GrhTB 回归：

```sh
make --no-print-directory run_all_hdlbits_grhsim_ir_tests \
  SKIP_PY_INSTALL=1 WOLF_ENV_SOURCED=1 PYTHON="$PWD/.venv/bin/python" \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_ir_hdlbits_private_commit.log 2>&1
```

进程退出 0，162/162 用例完成；日志有 162 个 DUT 入口，最后一个为
`dut_162 passed all prediction and training scenarios`，无失败记录。
独立产物目录 `ptmp/hdlbits-grhsim-ir-tEJANI`，没有复用 gate57 的已生成模型。

本结果补充 NO0598 的 CPU/Verilator/独立记分板和非 E/真实 DPI 旧值观察测试。
它不替代完整 XiangShan 回归或性能证据。DPI、event 与 history 语义没有改变。

## Remaining Work

gate58 完整 O3 构建仍在运行，尚无真实 1k/10k/50k 性能或功能结果。gate57 的
50k 证据仅属于旧基线，不能转移到 gate58；规划的 5% 性能要求仍未完成。
