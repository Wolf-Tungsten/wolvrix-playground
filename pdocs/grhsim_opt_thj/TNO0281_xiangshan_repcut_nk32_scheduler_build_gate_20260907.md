# TNO0281: XiangShan RepCut N=K=32 scheduler build gate

日期：2026-09-07

状态：`NO-OP REPRODUCTION PASS; EXPERIMENTAL RUNTIME BUILD PASS; PERFORMANCE PENDING`。

前置计划：[TNO0280](./TNO0280_xiangshan_repcut_nk32_four_stage_experiment_plan_20260907.md)。

## 1. 隔离范围与实现

实验产物位于 `build/repcut_nk32_opt_20260907/`，不修改生产 emitter 或冻结模型。
`runtime/generate_variant.py` 以冻结 common/header 的 SHA 为输入门，生成独立目录
`runtime/generated-v1/`。Sim class header 保持逐字节一致，新增状态放在 common TU
的 registry，每个 host step 查询一次，worker 回调不查 registry。

三种显式模式通过 `WOLVI_REPCUT_RUNTIME_MODE` 选择：

- `legacy`：保留原每阶段逐 worker 派发/等待。
- `pipeline-workers`：32 个常驻后台 worker，一次派发完成 eval、全体 eval barrier、
  update、完成通知；host 不执行 partition。
- `pipeline-host`：31 个后台 worker，host 执行 lane 0，计算参与者仍为 32。

后两者要求 N=K=32、可见 CPU 恰好 32、early phase 为空，非法配置拒绝。
仍使用 C++17 condition_variable，不使用忙等；本次测的是该具体实现，而非所有
可能的 barrier 实现。保留 eval 完成后才能更新、全部更新完成后才能下一 step 的语义。
异常路径取消并 join workers，再向 host 抛出，避免计时析构与未结束 worker 竞争。

`WOLVI_REPCUT_WORKER_PARTS` 为 worker lane 到 partition 的排列；默认连续编号。
日志输出实际 mode、worker/host CPU、正逆映射、push/pull 标记与线程数。
辅助 Verilator pool 预期仍为 31 个休眠线程，不能把它们误算成计算 worker。

## 2. 构建身份门

`build_wrapper.py` 解析冻结 compile.stdout 的完整 argv，保留原对象/库链接顺序，
仅替换指定封装对象；原 1422 个模型对象和 47 个外层对象逐项 SHA/Clang marker 审计，
链接前后复核所有复用输入。32 个模型 archive 不重新生成。

保持 Clang 21.1.5、C++17 及原封装编译选项，特别是原封装未指定 `-O`，本轮不顺带
加优化级别。header ABI 不一致或未声明的封装源变化会拒绝构建。

| 构建 | 仅重编 | ELF SHA-256 | 结果 |
| --- | --- | --- | --- |
| `builds/control-v1` | 未改动的 common | `b5803a654b2f63057f71337ae02137089e8d28177c2b0e41918fefdc6c778b55` | 与冻结 ELF 逐字节一致 |
| `builds/runtime-v1` | 实验 common | `1f57c1e00d6e8339ba0b6eade021cfd463f21baa39b0f6fd64d3949a4de20e94` | 构建/对象审计通过 |

构建在 node029 完成，分别约 13.635 s / 7.630 s。精确 argv、输入 SHA、源文件 SHA、
编译日志、链接日志及 manifest 均保存在各自 build 目录。只重编封装能逐字节复现旧 ELF，
因此后续无需用旧路径与新工具链混合构建作为对照。

## 3. 已完成与待完成验证

运行时 mock 覆盖 1/8/32 lane，每种 worker/host 模式 300 steps、输出签名、严格阶段
边界，以及初始化/eval/update 异常和取消；C++17 原优化级别构建执行通过。
生成器 5 项测试通过。这里的 1/8 lane 是调度器单元测试，不是放宽真实模型 N=K=32 门。

真实模型尚待功能与性能 gate。首个配对使用同一个 `runtime-v1` ELF 的 legacy 与
pipeline-workers 模式，配置冻结于 `specs/stage1_dispatch.json`，控制新增日志/registry
封装影响。随后独立测试 host 参与，不能将两种变化只合成一个结果。

node030 短资源扫描候选为 NUMA0 `0-23,88-95`，monitor 191；四个 CCD 均连续三个
3 s 窗口通过。扫描证据 `mapping/scans/node030_numa0_initial.json`。正式启动前仍执行
逐样本 admission，不把这次短扫视作后续长期占用许可。
