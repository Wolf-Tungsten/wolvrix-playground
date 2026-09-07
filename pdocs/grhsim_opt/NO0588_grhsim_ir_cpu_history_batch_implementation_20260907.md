# NO0588 GrhSIM IR CPU History Batch Implementation

- 日期：2026-09-07
- 前置：[NO0585](./NO0585_grhsim_ir_cpu_history_batch_design_20260907.md)

## Implemented Boundary

在 `cpu_emit.cpp` 内进行等价代码压缩，不修改 IR、mapping 或 task 执行条件。
实现比设计候选更窄：每批只能来自同一个 `DomainGatedCommit` 函数，其 history
shadow 写移动到该函数末尾，而不是跨函数移动到全局 publish 前。

每个候选必须同时满足：

- history 在完整 object-ref pool 中只被引用一次，且该次是本写口的 event history；
  被读取、共享、普通写入或其他 op 使用时一律回退。
- state 和 event 类型完全相同，为占一个字节的 2-state、1-bit logic。
- state 属于静止投影，且 fanout 恰好只有本域的 arm，没有其他 activation 目标。
- 同批对象字节连续，不跨越未入选 state 或 padding。

在连续区间中选择至多 8 字节的短事件 pattern，至少 4 个 history 才组成批次。
无法成批的采样保留原 `stage`。单 event 用 memset；多 event 的短栈上 pattern
通过 memcpy 重复写入原 shadow 缓冲，不使用按值返回的大数组或新 helper ABI。

## Why This Preserves Scheduling

guard 仍逐 op 读取各自 visible history，保留不同初值；普通 data/mask 写及优先级
不变。移动的只是互不别名、没有其他消费者/写者的 shadow 写，且不跨原 task。
event values 已由 compute 产生，commit 期间不修改。

批次复用 `cpu_stage_bytes` 和既有 pending/publish。整批 any-change 对应原逐历史
变化的 OR，所有历史的 projection/arm 目标相同，因此下一轮求值条件完全相同。
pending/dirty 使用本批首个 state 标识；其余历史没有其他引用或写站点，不会在本轮
独立暂存或依赖 dirty 标记。init 仍逐状态执行，publish 后每个历史字节均独立保留。

DPI/system task 不参与批次，保持 compute、可选 event、真实调用和既有历史采样路径。
本实现参考 legacy 的共享事件工作和原地写策略，但没有合并逻辑 history state。

## Verification

首轮全部既有 CPU 回归通过，24.66 秒。随后新增专门 fixture，经 JSON 独立加载
后发射并以 O0 ASan/UBSan 运行；其 16 个 event 采样有 12 个私有 history 合成两批，
其余四个采样因读取、共享或普通写口引用而回退。不同初值、重复 eval、四次 init
共 4624 样本通过，证明没有把同一时钟的不同旧值合成一个状态。

再次补充 state/event 类型一致性约束及 CDC 多事件 pattern 命中断言。最终
`make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` 退出 0，26.60 秒。
日志 `ptmp/grhsim_cpu_history_batch_pattern_test.log`，完整结果
`ptmp/grhsim_cpu_history_batch_pattern_test_details.log`。

原 cpu_chain 4136、scalar 4196、wide 3072、wide-state 2048、CDC 10756、双 RAM
9731 样本及 startup/init/calls 回归均保留并通过。ASan 的 LeakSanitizer 保持既有
禁用设置，没有宣称新的 leak 检查覆盖。

## Full-Model Follow-Up

`make py_install` 已退出 0；独立 gate57 通过原 Makefile 从相同 flat GRH 生成，
保持 `target-batch-count=0`。输出为 `ptmp/xs_emit_make_gate57`、
`ptmp/xs_ir_gate57.json`、`ptmp/xs_ir_gate57_roundtrip.json`；日志
`ptmp/grhsim_gate57_generation.log`。本节写入时仍在生成。

emitter 诊断报告候选/私有性回退/布局激活条件回退/批量覆盖数量、批次数、最大批次
及最大 pattern。需要以全模型实际覆盖、O3 编译和运行成本验证收益；不再仅凭 pending
数量下降宣布优化成功。IR 50k 和配套性能门禁仍未完成。
