# NO0580 GrhSIM IR CPU Unchanged State Staging

- 日期：2026-09-07
- 依据：[NO0579](./NO0579_grhsim_ir_cpu_gate55_phase_profile_20260907.md)

## Implementation

`cpu_emit.cpp` 新增生成侧 `cpu_store<T>`：先比较本轮有效值，只有发生变化才调用
现有 `cpu_stage` 登记并写入 shadow。本轮有效值在 dirty 时取 shadow，否则取
visible object；不能始终与 visible 比较，否则“先写新值、再写回原值”会误跳过后写。

- event history 采样通过此路径保留真实时序，但不再把未变化采样登记进 pending。
- 标量 reg/latch masked write 先从当前 shadow/visible 值计算合并结果，再执行
  `cpu_store`。同一 state 多次 masked/full write 的顺序不变。
- wide state 和 array 写暂存 ABI 不改；不增加宽值按值返回 helper 或大临时对象。
- 变化后的发布、projection、fanout 和域 arm 仍沿现有路径处理；最终写回原值的
  pending 由 publish 比较后不激活下游。
- `cpu_store` 加入实际生成成员名称冲突检查，不扩大为前缀禁用。
- DPI 保留 compute、可选 event 和实际调用，仅共享的 history 采样避免无效入队；
  不重分 phase、不抹除 event、不删除 void call。

参考 legacy 的 `emitWritePortBody`：其标量更新比较合并值后才写入并激活 reader。
IR 路线此处仍保留 NBA shadow/publish，未直接移植 visible-state 提前写入行为。

## Focused Verification

通过既有 `make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1`，退出 0，CTest 20.37 秒。
日志 `ptmp/grhsim_cpu_noop_state_test.log`，完整细节
`ptmp/grhsim_cpu_noop_state_test_details.log`。

- cpu_chain 新增同拍 full write 后写回零的 `cancelled` 状态，检查覆盖顺序。
- 新增 32 次输入和时钟均不变的重复 eval。
- cpu_chain/Verilator 4136 样本通过；scalar 4196、wide 3072、wide-state 2048
  样本通过，均保留 UBSan 检查。
- 原 startup、array init 和 384-sample 外部调用/系统任务回归通过；startup/calls
  保留既有 ASan/UBSan 配置，未新增或宣称 LeakSanitizer 覆盖。
- 七个真实保留成员名的拒绝检查通过，包括新增的 `cpu_store`。

## XiangShan Follow-Up

`make py_install` 已退出 0，随后通过既有 `make xs_wolf_grhsim_ir` 从同一 flat GRH
生成独立 gate56，使用与 gate55 相同的 `target-batch-count=0`，输出
`ptmp/xs_emit_make_gate56`、`ptmp/xs_ir_gate56.json` 和
`ptmp/xs_ir_gate56_roundtrip.json`。生成日志为 `ptmp/grhsim_gate56_generation.log`。
本节写入时 fresh generation 正在执行；性能收益尚未测得，不以小测试替代完整模型。

## Generation Completion

gate56 fresh generation、独立 session 加载和 stable round-trip 后续全部退出 0，
总计 86382 ms。已通过原 `xs_wolf_grhsim_ir_build_emu` 目标以 8-way O3 启动全模型
构建，日志 `ptmp/grhsim_gate56_full_o3_build.log`；未改变 batch 配置或降低优化级别。
新增加的多时钟 DUT 回归另见
[NO0581](./NO0581_grhsim_ir_cpu_multiclock_extended_gate_20260907.md)。

## Identical IR Check

`cmp -s ptmp/xs_ir_gate55.json ptmp/xs_ir_gate56.json` 退出 0，两次约 679 MiB 的完整
IR checkpoint 逐字节一致，包括 CPU mapping。运行对照没有混入 lowering、partition、
layout 或 schedule 改动。HDLBits 全量复跑也已退出 0，162/162，通过结果另归档于
[NO0582](./NO0582_grhsim_ir_cpu_unchanged_state_hdlbits_gate_20260907.md)。

## Runtime Rejection and Revert

后续完整 O3 实测 gate56 的 1k 耗时 68502 ms，劣于 gate55 的 57958 ms，不能接受为
默认性能优化。该实现已完整撤回，新增回归保留且在恢复版本上通过；历史测试和
入队计数证据不删除。详细数据、撤回范围及独立 gate55 harness 选择见
[NO0584](./NO0584_grhsim_ir_cpu_unchanged_state_runtime_rejection_20260907.md)。
