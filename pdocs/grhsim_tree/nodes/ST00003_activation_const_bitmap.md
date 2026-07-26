# ST00003 激活编译期常量位图化

- 父节点：ST00001
- 状态：pruned-regression（2026-07-25，2k 门控 +23.8%；fetch-bound 下内联增大体积）
- 代码状态：wolvrix @ `afcd5fd` + ST00002/ST00008 本地改动 + 本节点 `lib/grhsim/am/cpp_emitter.cpp` 改动（未提交）
- 创建日期：2026-07-25

## 假设

AM 的激活原语是跨 TU 函数调用（`activate_forward/backward`，3.22M 静态调用点、50k 动态 15.5B 次），每次调用 = 函数调用 + 边界 throw + commit 分支 + 位图 OR。AN00002 分解：per-block exec 固定开销 F≈1.56 µs 占 baseline compute 55%，activation 调用是 F 的主要成分。ST00002/ST00008 三次证明划分不是杠杆，runtime 由原语成本决定——本节点把激活原语拉平到 legacy 水平（legacy 为内联 `grhsim_or_active_u64` 一条 OR）。

## 改动

`wolvrix/lib/grhsim/am/cpp_emitter.cpp` 的 `ActForward/ActBackward` 指令发射：调用点直接内联 activate_* 函数体，word/bit/summary 索引全部折叠为编译期常量；commit/非 commit 目标由 emitter 用 `model.commitBlockBegin/End`（新增 `EmitState` 字段）静态判定，commit 变体原样保留 `capturedCommitWords_` 条件清除语义（forward 测 `pendingCommitWords_` 置 `pendingCommitWords_`，backward 测 `pendingCommitWords_` 置 `nextCommitWords_`，与运行时函数逐字一致）；profile 计数语义不变（每目标一次自增，`runtimeProfileEnabled_` 分支）。`activate_forward/backward` 运行时函数保留（其他路径仍在用）。

块函数与 activate_* 同为模型类成员，位图成员直接可访问，改动纯为代码生成文本替换，无算法风险。

## 测量

**2k 门控（2026-07-25，solo，`setarch -R` + `taskset -c 7`，profile OFF，-C 2000）**：

| 配置 | 2k 时间 | vs baseline（140,573 ms） | .text 体积 |
| --- | --- | --- | --- |
| baseline（调度完全一致：36,963 blocks、同 detector/activation 数） | 140,573 ms | 1.00x | 360 MB |
| ST00003（激活内联） | 174,025 ms | **+23.8% 回归** | 432 MB（+20%） |

功能 gate 通过（instrCnt=3 / cycleCnt=1,996 一致）。时间增幅与代码体积增幅几乎 1:1。

## 结论

**剪枝（pruned-regression）**。根因分析见 [AN00004](../analysis/AN00004_am_emu_fetch_bound_20260725.md)：**AM emu 是取指瓶颈（fetch-bound）**——360MB .text 下每次 block exec ~2.8 µs / ~21 ns/指令在所有实验中不变，瓶颈在 I-cache/I-TLB 而非调用开销；函数调用在该 regime 是代码压缩而非开销，内联（体积 +20%）必然回归。AN00002 的"原语成本"修正为"代码体积成本"。

实现附带教训：本次内联中误加的 per-target profile 分支（约 45MB）违反 ST00001"计数器不入调用点"的设计，是体积膨胀大头；ST00001 原设计（计数器在 runtime 函数体内）经复核仍正确。

**处理**：emitter 改动已回退（git checkout），生成代码恢复原状；AN00004 已落盘并改写候选池方向。

## 子节点候选

- **ST00009 发射体积压缩**（新 P1，详见 TREE.md）：首选子项 ST00006 死 detector 静态消除（1.82x 物化膨胀是体积主源）；次选指令发射文本瘦身（resize/掩码/事件判断共享例程化）。
- ST00004 预警：分派内联同样增大体积，动态收益预估 <2%，降级。
- 遗留验证：perf stat 直接测 I-cache miss；legacy 84MB 构成分析作为体积对标。
