# NO0585 GrhSIM IR CPU History Batch Design

- 日期：2026-09-07
- 依据：[NO0579](./NO0579_grhsim_ir_cpu_gate55_phase_profile_20260907.md)、
  [NO0584](./NO0584_grhsim_ir_cpu_unchanged_state_runtime_rejection_20260907.md)
- 状态：后续实现候选，本记录不声称已实现或已获性能收益。

## Evidence and Direction

legacy 的 `grhsim_cpp.cpp::registerEventSamples` 按 event ValueId 去重
`eventEdgeFieldByValue`，重复写口共享事件槽。当前 IR 按 op/event 位置保留显式
history state，每次 G 无条件采样；gate55 1k 累计登记约 17.5 亿 pending。
逐写口增加“不变”检查已在 gate56 实测劣化并撤回，不能继续重复这一方向。

下一候选是发射形态的批量暂存：保留全部独立 history state/初值/旧值，在同一
commit phase 内把可证明互不干扰的采样合成为较少的批量 shadow 写和 pending
记录。它不直接照搬 legacy 的共享状态槽，也不在 ingest 抹除 DPI event。

## Required Eligibility

仅从已完成的 CPU mapping、对象布局和实际 IR refs 推导候选，禁止隐式更改执行条件：

- 首版仅处理 commit 域内的 event histories；DPI/system task 的采样保留原路径。
- history 只能有一个事件采样写站点，且不能另被 state read、普通 write 或其他
  op 引用。共享历史、多写者和其他外部用途全部回退。
- 每批采样必须具有相同域执行条件；域未被 arm 时不能采样。不得按“都用 clock”
  合并不同异步 reset / 多事件集合，也不改变 general-domain 行为。
- 批内全部 state 的 projection 和实际 fanout 激活目标一致；发布 any-change
  的 OR 才能替代逐 state 发布。否则回退或拆批。
- 只覆盖真实连续的、类型合法的 history 字节，不跨入寄存器、memory、padding 或
  其他域状态。历史初值可以不同，仍逐对象初始化并使用原值判断当前边沿。
- 多事件写口常形成重复事件值序列，可用小 pattern 的指针/输出缓冲填充循环描述；
  不能为了压缩强行假定所有 history 都采样同一个 bit。

候选实施前需量化可合并的 history 数、连续范围/重复 pattern 数和回退原因。
若需要新的运行时决策，必须物化进 mapping 并覆盖 verifier/JSON fresh-load；
若仅作 emitter 内的等价代码压缩，须明确证明没有改变 task 执行和状态可见性。

## Semantic Proof Obligation

各写口的 guard 仍读本轮 visible history，数据更新和 mask 优先级不变。
批量采样只能移动互不别名的 shadow 写，必须在既有 publish 之前完成，不能提前更新
visible history。event values 来自 compute 已完成的值，commit 期间不可变化。

批内最终任一 history 变化时，原逐 state 路径与批量路径必须产生完全相同的
projection/下一轮 arm/compute fanout。不能仅以“时钟看起来相同”替代这些条件。
dirty 标记、重复采样及 publish 清理也需要保持一致，避免遗留跨轮状态。

## Required Gates

- 不同 history 初值、单/多事件、相反边沿、派生事件、域未 arm、重复 eval。
- 共享 history、history 被读取/普通写入等反例必须回退；不能静默接受不安全批次。
- masked 多写口和同拍写回原值回归继续通过。
- 三个多时钟 DUT 的 Verilator/记分板对照及 JSON fresh-load；162 个 HDLBits。
- 相同 IR/batch/O3 的独立新输出构建，先量化代码体积和 1k 阶段成本，再做真实
  10k/50k NEMU 功能和配套 50k 性能检查。

此设计不豁免 50k 目标，也不把采样计数下降等同于性能通过。
