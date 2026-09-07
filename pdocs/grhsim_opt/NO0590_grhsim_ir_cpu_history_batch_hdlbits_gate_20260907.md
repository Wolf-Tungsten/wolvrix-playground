# NO0590 GrhSIM IR CPU History Batch HDLBits Gate

- 日期：2026-09-07
- 前置：[NO0588](./NO0588_grhsim_ir_cpu_history_batch_implementation_20260907.md)

## Full Regression

同 commit 函数的私有 history 批量暂存实现通过既有全量 Makefile 入口复核：

```sh
make --no-print-directory run_all_hdlbits_grhsim_ir_tests \
  SKIP_PY_INSTALL=1 WOLF_ENV_SOURCED=1 PYTHON="$PWD/.venv/bin/python" \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_ir_hdlbits_history_batch.log 2>&1
```

进程退出 0，162/162 用例完成。日志有 162 个 `Running GrhSIM DUT=` 入口，
最终 `dut_162 passed all prediction and training scenarios`，没有失败记录。
独立输出目录为 `ptmp/hdlbits-grhsim-ir-sGo6Dl`，未复用先前优化实验的模型。

本结果在 NO0588 的 CPU/Verilator/独立记分板及 history 反例测试之外，补充
实际 HDLBits ingest 到 IR/CPU 的全流程回归；不是全状态等价或完整 DPI 语义证明。
DPI 保持既有 compute 归属、可选 event、真实调用及 void call 不删除策略。

## Remaining Work

gate57 全模型 O3 构建仍在运行。批量暂存的实际 XiangShan 性能收益、IR 50k
及配套 legacy 性能比较尚未完成，不把小模型通过作为完整目标通过。
