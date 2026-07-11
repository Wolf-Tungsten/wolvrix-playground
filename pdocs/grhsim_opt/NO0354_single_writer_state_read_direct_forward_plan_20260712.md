# NO0354 Single-writer state-read direct-forward plan

日期：2026-07-12

## 1. Objective

根据 [NO0353](./NO0353_simtop_state_read_locality_gate_20260712.md)，实现默认关闭的
single-writer scalar register-read direct forwarding，消除：

```text
state write
  -> state-read source supernode activation
  -> persistent read slot compare/store and alias OR
  -> downstream compute activation
```

目标形态与 GSim 一致：state commit 确认 visible state 真正变化后，直接激活 eligible read 的 downstream compute
consumers；consumer 表达式直接读取 state storage。不得按 `timer`、`logEndpoint` 或 SimTop 名称特判。

## 2. Existing runtime semantics

生成器当前已经具备所需的两项基础语义：

- register commit 先计算最终 masked value，只在 visible state old/new 不同时调用 reader activation；
- commit 设置 `supernode_active_curr_` 和 `commit_activated_readers_`，`eval()` 随即进入下一轮 compute，active bits
  不会在 commit 与该轮 compute 之间清零。

首次 `eval()` 会激活全部 compute supernodes。因此 direct consumer 在初始化时会直接读取初始化后的 state；后续 state
变化则由 commit frontier 激活。无需新增跨 cycle shadow 或第二套调度循环。

## 3. Eligibility

新增 emit attribute / environment 开关：

```text
direct_single_writer_state_reads=1
WOLVRIX_GRHSIM_DIRECT_SINGLE_WRITER_STATE_READS=1
```

默认值为 `0`。每个候选必须满足：

- op 是单结果 `kRegisterReadPort`，目标是非 reg-to-mem、非 wide scalar logic register；
- register 在整个 graph 中恰好有一个 register write port；
- result 已 materialized、需要 tracked change，且有非空 compute boundary fanout；
- result 不是 output/inout、waveform、event、packed-array lane 或 reg-to-mem bypass；
- 所有 graph users 都是已调度的 compute supernodes，均不在 read source supernode；
- user supernode active-ID 集合与 boundary fanout 精确相同，不存在 commit 或 unscheduled user。

同一 source supernode 中共享 materialized slot/change predicate 的 alias group 必须整组 eligible；只要一个 member 不满足，
整组保留原路径，避免跳过 canonical read 后非候选 alias 仍引用旧 slot。

## 4. Activation rewrite

为每个 state 从现有 reader-head 集合构造新 frontier：

1. eligible read 的 boundary consumer active IDs 加入 state frontier；
2. 只有当某个 state 在某 source supernode 中的全部 reads 都被直连时，才从 frontier 移除该 source active ID；
3. 若存在 local、protected、wide、multi-writer 或其他 non-eligible read，保留 source active ID；
4. 最后排序去重，继续复用现有 scalar direct-commit、range/table compression 和普通 write emission。

这允许 mixed supernode 逐 read 优化。以 NO0353 的 supernode 7804 为例，boundary-only reads 可跳过，而
`NSamples`/`Sum` 的两个同-supernode local reads 和尾部 `kDiv` 保留；该 supernode 不再因 `timer` 或其他已直连
histogram state 变化而被整体唤醒。

## 5. Code generation

- `resolvedScheduleValueExpr()` 对 direct read result 优先返回对应 state storage 引用；
- read source supernode 遇到 direct result 时不生成 slot compare/store、changed predicate、alias OR 或 boundary activation；
- 第一阶段保留已分配但不再使用的 value slot，先缩小语义改动；功能和性能门禁通过后再单独回收 storage；
- line estimator 与 runtime-profile static source-op 计数同步跳过 direct reads；
- emitter 输出默认关闭的结构统计，报告 eligible rows/groups、移除的 source heads 和新增的 direct consumer heads。

## 6. Synthetic gates

新增独立 generated-model case，至少覆盖：

- single-writer scalar register 的初始化值直接可见；
- changed write 激活 downstream，no-change write 不产生错误传播；
- mixed supernode 中 direct read 与保留计算共存；
- repeated reads / same-state alias group 整组直连；
- 同状态存在 local user 时保留 source head；
- multi-writer state 明确保留原 materialized read path；
- output/event/protected read 不被直连。

结构断言必须确认 generated C++ 中存在 direct marker，eligible read 不再生成 slot compare，multi-writer/protected read
仍保留。随后编译并运行 harness，最后执行完整 `emit-grhsim-cpp` CTest。

## 7. SimTop gates

synthetic 通过并提交后，才从 NO0300 checkpoint fresh emit SimTop：

1. 对照 NO0353 的 `75,830` rows / `1.1395B` canonical visits 上界，报告 emitter 实际 eligible 数；
2. 检查 supernode 7804 的 104 个 boundary materializations 是否消失、local `kDiv` 是否保留；
3. 编译 emu，先做 100-cycle、10k、50k CoreMark/NEMU difftest 功能门禁；
4. 功能正确后检查机器负载，以 fixed CPU/NUMA/ASLR 做 NO0300/new/NO0300 夹测；若负载偏高，必须同窗重跑
   baseline，不使用历史单点时间；
5. 同时报告 guest cycles、host cycles、instructions 和 backend stalls，判断是否真正缩小 NO0344 的 GSim gap。

任何功能差异先停在最小 synthetic/短 SimTop 复现，不以放宽 difftest 或隐藏 `input_fullpass_blocked` 掩盖问题。
