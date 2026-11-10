# TNO0009 独立配置与正式配对入口

## 可追踪的实验配置

本目录保留 [before-repcut.json](./configs/before-repcut.json) 和 [after-repcut.json](./configs/after-repcut.json)，内容与构建所用 artifact 配置相同。公共 `config/grhsim32.json` 不修改。after 使用新配置排除已被上游删除的两类 TL memory FIFO，原因见 [TNO0004](./TNO0004_upstream_rtl_schema_memory_20261110.md)。

在合并后的 checkout 重新构建时，显式传入 after 配置。例如在仓库根目录、node030 执行：

```bash
make xs_wolf_grhsim_repcut_perf_emu \
  XS_GRHSIM32_PERF_OUTPUT=build/xs/kunminghu-v3-reproduction \
  XS_GRHSIM32_PERF_ARGS='--xs-config DefaultConfig --runtime-cpus 0-31 --config pdocs/kunminghu_v3_grhsim_merge_20261110/configs/after-repcut.json --image build/artifacts/kunminghu-v3-grhsim-merge-20261110/inputs/coremark-2-iteration.bin --nemu build/artifacts/kunminghu-v3-grhsim-merge-20261110/inputs/riscv64-nemu-interpreter-so'
```

默认功能流程仍为 `xs_wolf_grhsim_repcut_emu`；对应使用 `XS_GRHSIM32_OUTPUT`、`XS_GRHSIM32_ARGS` 传入同一 after 配置，仅作 smoke，不能据其时间作性能结论。`run-only` 的 performance 模式必须与构建记录匹配。

before 的重建需要 `77ed568fc` 及其原 gitlinks 的独立 checkout，再传入 `--xs-source` 和 before 配置。不能用合并后的 Scala/harness 搭配旧 generated header 重编译旧模型。

## 正式测量调度

[paired-measurements.py](../../build/artifacts/kunminghu-v3-grhsim-merge-20261110/paired-measurements.py) 等待两侧标准 RepCut performance 流程输出通过的 result，然后持有构建锁，依次执行：

1. [grhsim_single_compare.py](../../scripts/grhsim_single_compare.py)：复用 [TNO0008](./TNO0008_native_trace_and_structure_gate_20261110.md) 的 trace 门，核对冻结依赖；重新 smoke/warmup，再跑 8 对 AB/BA。CPU96、NUMA1、单线程、ASLR disabled，trace/诊断关闭，跳过空闲准入。
2. [grhsim32_pair_compare.py](../../scripts/grhsim32_pair_compare.py)：要求两侧已完成 performance 构建，从各自 retained 版本取 binary，复制和 prefault 运行依赖；两侧分别 smoke/100k verify/warmup 后跑 8 对 AB/BA。CPU0–31、NUMA0、ASLR disabled、pinning enabled、codepages=auto，使用共同 Pipeline 的 LD_PRELOAD/timing 配置。

两个 runner 均逐次检查完整 DiffTest、确定的功能签名、映射 locality 和线程约束。工作负载及 REF 使用 `artifacts/inputs` 的冻结副本；不会随着 ready-to-run 子模块更新而变化。native/RepCut 正式运行串行，避免两个测量组互相干扰。

每次调用的完整 argv、运行日志、placement/locality 样本、Host time、外部 walltime、原始 pair、CSV、bootstrap CI 均保留。`paired-progress.json` 只表示流程状态；必须以最终 summary 和各样本 gate 通过为性能结果依据。

本记录形成时正式配对仍在等待 RepCut 构建结束。选择/migration 的内部计时只用于决定 retained 版本，不作为上游合并前后的正式结果。
