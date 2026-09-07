# NO0597 GrhSIM IR CPU Private Scalar Commit Design

- 日期：2026-09-07
- 依据：[NO0596](./NO0596_grhsim_ir_cpu_gate57_phase_profile_20260907.md)
- 状态：实现前设计；尚无性能收益结论。

## Candidate

legacy `grhsim_cpp.cpp::emitWritePortBody` 直接更新可见状态，只有实际变化才激活
读者。新 IR 必须保留每次 G 的旧状态读取与最终 E 比较，不能对所有写口直接照搬。
本候选仅对无中途观察者的唯一写者标量消除 shadow/pending，其他状态完全回退。

资格必须从完整 IR refs 推导，同时满足：

- 状态是 2-state logic，宽度 1..64，不是 array、宽值、string 或 real。
- 全模型恰有一个 regWrite/latchWrite 写站点；多写者无论是否同域均回退。
- 除该写口的首个目标 ref 外，其他 refs 只能来自 compute 的 state.read。
- 不得作为任意 event history、DPI/system ref 或其他 commit 读取对象。
- 检查完整 object-ref pool 的引用数量与已归类引用一致，未归类引用保守回退。

不改变 phase、task 顺序、域条件、事件检测、history 采样、mask 或输入表达式。
普通非候选写口与 history batching 继续走原 shadow/pending/publish。

## Equivalence Argument

compute 在 commit 开始前已完成，state.read 的结果保存在原 value slots 中。
候选状态在 commit 中只有自己的 masked 写会读取它，没有其他观察者或写者，
因此该写站点看到的仍是本次 G 的旧值；计算得到的值就是 G 的最终状态。

物理对象字节可以在该写站点更新，因为直到下一次 compute 都无人再观察它。
这不是允许一般 commit 读到新值，也不扩大既有跨域可见性。由实际变化触发的
active bits 可在 commit 内置位，因为本轮 compute 已结束；arm 必须写 next-arm，
不能唤醒本轮后面的 commit 域。延续条件单独累积 projected-state 的变化，在
原 publish 返回时与其他 pending 的最终变化合并。

对于非 E 状态，更新仍发生，但不得因此增加 G 轮次；既有 roundSeeds 保证后续
求值读取新状态。非 E 与 E 的资格不混淆。init 必须清除延续标志。

唯一写者条件保证不会出现本轮先改变又写回原值，因此提前记录 any-change 与
轮末比较等价。多写者和普通写口写 history 的反例保留原延迟发布。

## Runtime Shape

调用方以引用读取目标，计算同一 masked/normalized 标量；值变化时原地写回。
一个小型 out-of-line helper 复用既有 state target 表，累积 projection 并更新
compute flags/next-arms，避免在每个写口复制长 fanout 语句。无大数组返回或分配。

这是 emitter 内可证明的状态存储优化，不新增调度条件或改 mapping；新增的
延续布尔量是原 pending 发布结果的临时归约，不是新的域激活机制。

## Required Verification

- cpu_chain 的唯一写者、latch、派生时钟、双边沿与异步 reset 继续通过。
- 多 masked 写口与写回原值必须回退；普通写口写 history 必须回退。
- 单独验证非 E 更新不增加轮次，DPI 观察仍遵循每次 G 的旧状态；重复 eval/init。
- 标量 signed/unsigned、零/部分/全 mask、memory/宽值原路径和三个多时钟 DUT。
- 全套 CPU、JSON fresh-load、HDLBits 162/162，再用独立新 gate 的完整模型量化
  覆盖、编译与运行成本。若退化则撤回，不重试 NO0584 已拒绝的 cpu_store。
- 实际 10k/50k 与性能门禁仍必须重验，不能把代码缩短或 pending 下降作为收益。
