# ST00001 AM runtime profile 计数器

- 父节点：ST00000
- 状态：trunk
- 代码状态：wolvrix @ `e7d0828` + `lib/grhsim/am/cpp_emitter.cpp` 本地改动（未提交）
- 创建日期：2026-07-25

## 假设

AM emitter 的 `dump_runtime_profile` 是空 stub（生成代码中无任何计数），emu 完全缺乏运行时归因能力。补上 per-phase 计时 + per-block 执行/激活计数后，后续每个优化节点都能用数据定位热点，而不是只看 50k 总时长。这是 enabler 节点，不追求自身性能收益。

## 改动

文件：`wolvrix/lib/grhsim/am/cpp_emitter.cpp`（emitter 侧改动，计数器随生成代码产生）。

设计要点：

- **复用既有管线**：emu 已支持 `EMU_RUNTIME_PROFILE=1` 环境变量 → `set_runtime_profile_enabled` → `dump_runtime_profile()`（`testcase/xiangshan/difftest/src/test/csrc/emu/emu.cpp:101-361`），此前 AM 的 dump 是空 stub。本次只补计数与报告，不改 host。
- **全部计数器走运行时开关**（`runtimeProfileEnabled_`），关闭时每个埋点仅多一个完美预测的 not-taken 分支，零调用点膨胀（计数都在 runtime 函数体内，不在 3.2M 个静态调用点上）。
- 计数器（16 个标量 + 1 个 per-block 数组，见生成代码 `profile*` 成员）：
  - 结构：eval 调用数、epoch 总数、compute/commit block 执行数（含 per-block 数组，300KB）、commit group 执行数；
  - 事件：activate_forward/backward 调用数、changed mark 数（含 commit event）、clear 数；
  - commit：capture block 数、capture word 数；
  - 计时：eval 总时长、compute 阶段（`execute_active_blocks`）、commit 阶段（capture + events + group），`std::chrono::steady_clock`，关闭时通过 `?:` 短路掉 vDSO 调用。
- `dump_runtime_profile()` 输出：上述计数 + 时间分解（compute/commit/other 占比）+ exec count top-32 block 排行（标注 commit block）。

验证方式：reuse post-stats 重 emit + 重建 emu，2k 功能 gate 带 `EMU_RUNTIME_PROFILE=1` 检查报告输出。

## 测量

验证（2026-07-25）：

- **功能 gate**：2k coremark rc=0，instrCnt=3 / cycleCnt=1996，与改动前同口径 2k 参考运行逐字一致。
- **关闭时零开销**：profile OFF 2k = 140,573 ms vs 改动前同口径 140,574 ms，无差别。
- **开启时开销**：profile ON 2k = 141,224 ms，+0.46%。
- **单元测试**：`ctest -R "grhsim|am"` 10/10 通过（含 grhsim-am-end-to-end、emit-grhsim-cpp）。
- **报告输出**（2k，boot 阶段，仅作功能示例）：eval 4102 次、epoch 4072、block exec 35.5M、activation forward 505M / backward 30M、commit event marks 1.29B、时间分解 compute 71.0% / commit 28.2% / other 0.8%、top block 均匀（单块最高 0.023%）。
- 50k 稳态 profile（2026-07-25，setarch -R + taskset -c 7，EMU_RUNTIME_PROFILE=1）：
  - 功能：instrCnt=73,580 / IPC=1.471718，与 baseline 一致；profile ON 50k = 4,216,497 ms，相对 ST00000 baseline（4,191,014 ms）+0.61%。
  - 结构：eval 100,102 次、epoch 100,552（~1.0045/eval）；block exec 1.124B（compute 1.110B / commit 13.85M），commit group 150,654 次。
  - 事件：activation forward 14.01B / backward 1.46B；changed marks 1.88B + **commit event marks 31.59B（17 倍于普通 changed）**；clears 22.97B；commit capture 13.85M 块 / **25.71B words**。
  - 时间：compute 73.5% / commit 25.7% / other 0.7%。
  - top block 依旧均匀（单块最高 0.0178%），稳态确认密度型开销。
  - 推算：~11,200 block exec/eval（37,461 块中约 30% 每周期触发）；compute 阶段 2.79 µs/block exec（~132 指令/块 → ~21 ns/指令，远高于正常 1-2 ns，per-block 固定开销主导）。

## 结论

**接受（trunk）**。enabler 目标达成：AM emu 现在具备运行时归因能力，关闭时零开销（50k 开启仅 +0.61%），正确性不变。

50k 稳态确认三个结构性结论：

1. **密度型开销**：top block 占比均匀（≤0.018%），无单点热点；compute 阶段 ~2.79 µs/block exec（~21 ns/指令），per-block 固定开销（分派、detector、activation）主导，支持 ST00002 粗化方向。
2. **每周期 ~30% block 触发**（~11,200/37,461 per eval），活动率远高于 legacy 设计的稀疏度假设。
3. **commit 侧超预期地热**：commit 占 25.7% 时间，capture 25.71B words + commit event marks 31.59B（17 倍于普通 changed），ST00005 优先级应上调。

## 子节点候选

- ST00002（block 粗化）：50k 稳态证实 per-block 固定开销主导（2.79 µs/block exec、~21 ns/指令），粗化直接削减 block exec 次数、detector 与 activation 密度；expected_gain 维持"高"。
- ST00005（commit 侧）：稳态数据显示 commit 占 25.7% 时间，capture 25.71B words + commit event marks 31.59B，比 AN00001 静态估计更热；建议提升优先级，并将"commit event/capture 机制瘦身"纳入该节点范围。
- 观察项：每周期 ~30% block 触发，若后续节点证实大量触发是冗余求值（值未变的 block 重复执行），可新增"求值去重/guard 强化"候选。
