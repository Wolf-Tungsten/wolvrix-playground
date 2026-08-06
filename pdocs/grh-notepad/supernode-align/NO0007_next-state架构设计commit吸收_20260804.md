# NO0007 next-state 架构设计：commit 吸收（P1 寄存器/锁存器）

> **注意：本方案已于 2026-08-04 终止并整体回滚（见 [NO0009](NO0009_next-state方案终止与整体回滚_20260804.md)），原因是链逻辑导致纯组合节点过度激活、仿真性能严重恶化。本文保留作为设计记录。**

日期：2026-08-04
前置：[NO0006](NO0006_图形级杠杆量化与可达性终审_20260804.md)；用户于 2026-08-04 选定方向 2（commit 架构吸收）。

## 1. 目标与原理

把 commit 侧跨块 value（182,810，占 gsim 总量 98%）从根上消除，等价于 gsim 的 `$NEXT` 机制：

- gsim：reg_dst 在任意超节点计算 `name$NEXT`（普通 value 节点，随 coarsen 并入生产者超节点），周期末引擎统一 NEXT→state；该更新边是 cycle boundary，不进 def_use 图（`topoProjExport.cpp` 头注释）。
- AM 现状：state 写指令（RegisterWrite/LatchWrite/MemoryWrite/MemoryFill/MemoryWriteLanes）全部隔离在 commit 块，其 cond/mask/nextValue/addr 操作数由 compute 生产 → 必然跨块。

**收益分布（sequential 划分上实测）**：reg.write 163,896（89.7%）、mem.write 13,676、mem.write_lanes 5,763、latch.write 401、mem.fill 14。P1 只处理 register/latch（164,297，90%），memory 类留 P2。

## 2. 设计（P1）

核心观察：无需新 opcode。把每个 state target 的写链重写为**普通 compute 逻辑 + 一条平凡的 RegisterWrite 拷贝指令**：

对每个 target T 的有序写组 W1..Wn（现有 per-target ordered-effect group）：

```
prev = T                       // state 变量；compute 块读它天然是 read-old
for Wi in W1..Wn:
    fired_i = U(cond_i) && (ev_i0 || ev_i1 || ...)   // LatchWrite: fired_i = U(cond_i)
    rmw_i   = (prev & ~mask_i) | (nextValue_i & mask_i)
    next_i  = fired_i ? rmw_i : prev                  // mux
    prev    = next_i
det   = (next_n != T)          // 变化检测（普通 xor/or-reduce，等价 ST00013）
copy: RegisterWrite(cond=true, mask=all1, nextValue=next_n, target=T, events=[det])
```

- **链逻辑**（fired/rmw/mux/det）是普通 compute 指令：可随 coarsen 并入生产者所在 compute 块，原"生产者→commit"跨块消除。
- **拷贝指令**是唯一剩下的 commit 写（每 target 一条）：`T = next_n`，fire 条件 = det（next 变了才写，天然等价 ST00013 的写点判变）。
- **next_n → copy 的边是 cycle boundary**（同 gsim 的 NEXT→state 约定）：导出层标记为 `cycle_boundary` 边类（新 edge kind），主指标不计；另保留"计入"口径便于对照。
- **激活**：链逻辑的消费是普通 compute use → 走既有 def→use 激活边（`production_activity_schedule.cpp:1533` 的"commit 内 use 不激活"不再适用这些 use）；copy 的 state 写仍走既有 commit→state-reader 激活边（类型③，机制不变，copy 本身就是 RegisterWrite）。
- **read-old**：链逻辑在 compute 块读 T，必在任何 commit 之前 → 旧值。`preCommitValue` 快照机制（`lowering.cpp:1409-1442`）对 register/latch 写操作数**退役**（memory 类 P2 前保留）。

## 3. 语义不变式（必须保持，逐条有论证）

1. **read-old**：compute 扫描期间任何 state 读见旧值——链逻辑读 T 在 compute 块，copy 写 T 在 commit 段，不变。
2. **同 target 多写优先级**：原 ordered-effect group 的顺序（explicit priority 或 lowering 序）= 链中 prev 传递顺序；最后一条 fired 写生效，链语义逐字等价。
3. **reader 下一 round 才见新值**（grhsim-am.md:379-385）：copy 仍在 commit 段执行，类型③激活边不变。
4. **判变/act.b 时机**：det 在 compute 块算出（next_n != T），copy 以 det 为 event；copy 改变 T → act.b 走既有 commit 判变路径（copy 写点判变/块尾 changed.any）。ST00010-13 对 copy 仍成立（它就是一条 RegisterWrite）。
5. **latch level-sensitive**：fired=cond 不带 event，链语义直接表达"最后一个 cond 为真的写生效，否则保持"。
6. **"AM dependency requires a state commit before pre-commit work"**：链逻辑不依赖 copy（prev 从 state 与链内传递，不经 copy），不会产生 commit→compute 边。
7. **eval() 返回时 state 为最终提交值**（host 约定）：copy 在 commit 段照常执行。

## 4. 改动清单

| 层 | 改动 |
|---|---|
| lowering（或独立 pre-schedule pass） | 写组 → 链逻辑 + copy；标记 copy（label 前缀 `__am_next_commit__`）；register/latch 的 preCommitValue 快照退役 |
| scheduler | **零改动**（链逻辑是普通 compute atom；copy 是 commit atom，分类/分桶/激活机制原样） |
| emitter | **零改动**（全部复用现有指令形态） |
| interpreter | 零改动（按新图执行即可，语义等价） |
| validate | 零到少量（新图仍是合法现有指令；copy 的 mask=all1/cond=const-true 合法） |
| 导出/测量 | `exportInstructionGraphJsonl` 跳过 copy 的 nextValue 读（或导出为 `cycle_boundary` kind）；`scripts/supernode_align_metrics.py` 与 harness scorer 按 kind 过滤 |
| 文档 | grhsim-am.md / grhsim-am-pipeline.md 增补 next-state 章节 |

## 5. 预期收益与成本

- 消除：reg/latch 写操作数跨块 164,297 中的绝大部分（链逻辑随 Out1 并入生产者；残留 = 操作数本身 fanout≥2 未合并的部分）。
- 总量预估：744,513 → ~590k（比值 ~3.2x），叠加 replication（-17%）→ ~2.6x；后续图形级 pass 继续。
- 成本：指令数增加（每写 ~5-8 条链逻辑，香山 ~16 万写 → 估 +80-100 万指令，+25-30%；与 ir-scale 的 op 数成果有张力，已由用户确认方向）；commit 块数从 481 降到 ~target 桶数（更少更小）。
- 风险：T 的链跨块时 prev 传递值仍跨（链被切时）；宽 mask RMW 的 op 数膨胀；det 的全宽比较成本。

## 6. 实施与门控

1. 实现 lowering/pass 重写 + 导出 cycle_boundary + 测量过滤。
2. 指标：lower-json 重跑 + supernode_align_metrics（报告含/不含 cycle_boundary 两口径）。
3. 门控：香山 AM 全流水 + 50k difftest（NO_ZSTD_COMPRESSION=1 重建 emu）。
4. hdlbits grhsim 套件 + ctest 回归。
5. 达标复盘后视情况启动 P2（memory 写，预期再消 ~19.5k）与 replication 生产化。
