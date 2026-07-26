# AN00005 生成 CPP 代码级对比：60x 差距的分解（2k 口径）

- 记录日期：2026-07-25
- 关联：AN00004（fetch-bound）、AN00001（结构差距）、IN-20260725-05（2k 对齐目标）
- 材料：`grhsim_emit`（legacy）与 `grhsim-am/grhsim_emit`（AM baseline）生成代码直接对比
- 问题：结构指标（超节点/超边）基本同量级，为什么 2k 差 68.6x（AM 138,683 ms vs legacy 2,021 ms）？

## 1. 代码形态逐项对比

### 1.1 普通组合 op

legacy（sched batch 函数内联，每 op 3-5 条指令）：

```cpp
{
    const bool next_value = (read(state_logic_storage_, off) & read(...)) & value_bool_slots_[405472];
    value_bool_slots_[118029] = next_value;   // bool 值 1 字节槽位，窄值用 uint8/16/32 类型槽
}
```

AM（每 op ~5-8 条，外加边界机制）：

```cpp
values_[213935] = (resize_value(values_[213933], 1, false, 1) & resize_value(values_[213934], 1, false, 1)) & ((UINT64_C(1) << 1) - UINT64_C(1));
```

- legacy **按值宽度选存储类型**（bool→1B、窄值→uint8/16/32），AM **所有值统一 `uint64_t values_[]` 槽**——每值内存 8 倍于 1-bit bool，每周期遍历的状态体积差数倍，cache 行为完全不同；
- resize_value 是 header 内 constexpr（同宽时编译期折叠），所以 resize 主要是源码体积问题，不是运行时调用；但每 op 的 mask/cast 噪音仍比 legacy 多。

### 1.2 边界值 changed 检测（detector）

legacy（**内联**在定义它的 supernode 末尾，局部 bool）：

```cpp
const bool grhsim_changed_564863 = (value_bool_slots_[118029] != next_value);
grhsim_any_changed_0_0 |= grhsim_changed_564863;   // 局部累积器
```

AM（物化为独立调度指令 + 运行库调用）：

```cpp
set_changed_result(5638956, values_[213707] != values_[5638955]);  // 成员函数（跨 TU）
values_[5638955] = values_[213707];                                // 旧值回写，另一条指令
```

- AM 每条边界值 = 比较 + 跨 TU 调用（`set_changed_result` 内部还有 `if (event) mark_changed_result` 分支调用）+ 独立旧值回写指令；1.89M 个调用点；
- legacy = 两条内联指令，无调用，且 bool 槽 1 字节 vs AM 旧值槽 uint64 8 字节。

### 1.3 激活（activation fanout）

legacy（**分支消除的字节 OR**，多目标打包进同一字节掩码）：

```cpp
supernode_active_curr_[1390u] |= (-(uint8_t)grhsim_changed_564863) & UINT8_C(128);
```

AM（每个目标一次跨 TU 函数调用）：

```cpp
if (guard) { activate_forward(12345); activate_forward(12346); ... }
// 函数体：边界 throw + commit 判定分支 + 位图 OR + summary OR
```

- AM：50k 动态 15.5B 次调用、3.22M 静态调用点；legacy：每目标 ~1 条 x86 指令。

### 1.4 分派（dispatch）

legacy：8 个 supernode 共享 1 字节 flag，batch 函数内 `activeWordFlags & mask` 内联逐位测试、置位执行、原位清除——**零函数调用**。

AM：summary 字扫描 → active 字扫描 → `execute_block` 三级跨 TU switch（1.12B 次/50k）。

### 1.5 commit 阶段

legacy：state 写**融合在 eval 主循环**（register write 直接写 `state_logic_storage_`），无独立 commit 阶段。

AM：独立 commit 阶段 = 每周期全量扫描 ~497 commit block 的 pending/captured 位 + capture 机制 + commit event marks。**2k 占 ~27% 时间（40s/148s），动态量 1.29B event marks + 978M capture words（2k）；50k 为 31.59B + 25.71B**。

### 1.6 epoch 机制

AM 每 epoch 位图拷贝/清零 + dirty list 清理（2k epoch 4,072 次）；legacy round 机制轻量（flag 原位清除）。

## 2. 60x 的分解（2k，各因子相乘）

| 因子 | 量级 | 依据 |
| --- | --- | --- |
| 每指令动态成本（代码密度/形式） | 3-5x | 代码密度 legacy ~13B/op vs AM ~40B/instr（84MB vs 360MB）；typed 槽 vs 统一 uint64 槽 |
| 边界值机制（detector+activation） | 3-5x | 内联 bool 两条 vs 调用+回写+逐目标调用；且 AM 边界值多 2.7x（1.88M vs 704k） |
| commit 阶段 | ~1.4x（总账占比） | AM commit 占 27% 时间，legacy ≈ 0（融合） |
| 分派/epoch 固定成本 | 1.5-2x | 内联字节测试 vs 跨 TU switch + 位图维护 |
| 动态执行指令数 | 1-2x | 双方都是活动驱动求值，量级相近（AM 冗余 10:1 略高） |

乘积 ≈ 30-100x，覆盖实测 68.6x。**答案：不是单一瓶颈、不是超边数的指数效应，而是 4-5 个 2-5x 因子的乘积；每个因子都源于"AM 把 legacy 内联在求值流里的东西物化成了指令/调用/独立阶段"。**

## 3. 对候选池的映射（行动项）

1. **ST00005（commit 瘦身，P2）**：对应因子 3，最大单项（27% 时间），兼有体积收益；
2. **存储类型化/紧凑化（新候选方向）**：对应因子 1 的内存维度——窄值用窄槽（bool/uint8/32），减小每周期状态遍历体积；与 ST00009 局部化互补（ST00010 已覆盖局部化扩展）；
3. **detector/activation 物化减重（原 ST00003/04 的正确形态）**：不是内联（ST00003 已证回归），而是**减少物化数量与每点指令数**——多目标打包掩码（对齐 legacy `-changed & mask` 形态）、detector 融合进定义指令（消除独立回写指令）；
4. 分派扁平化（ST00004，parked）：因子 4，优先级最低。

## 4. 遗留验证

- 各因子的精确占比需要插桩/perf 分解（当前为代码形态 + 既有 profile 的推断组合）；
- commit 的 27% 与 detector/activation 的动态计数已有 ST00001 profile 硬数据；因子 1/4 的占比无直接测量。

## 更新 2026-07-26（ST00005 实测后的因子 3 修正）

ST00005 用 eval 作用域 sticky bitmap 替换 commit event 的 mark/capture/restore/clear 生命周期。2k 中已计数的 mark/clear 合计减少 1.728B 次，但三组同会话成对性能只改善约 1.06%，低于 2% 门槛；emu `.text` 还增加 0.887%，节点因此 pruned-no-gain 并回退实验代码。

这不推翻“commit 阶段占约 27%”的因子 3，只推翻其原子归因：主要成本不是 event 生命周期簿记，而是 483,654 次 commit block exec（约 80 us/次）中反复执行的 state-write/event-hit 脚手架。行动项从 ST00005 改为 ST00011：减少 218,588 个 commit 写槽的实际扫描/重算与发射体积；单独继续削 mark/clear 不再视为高收益方向。
