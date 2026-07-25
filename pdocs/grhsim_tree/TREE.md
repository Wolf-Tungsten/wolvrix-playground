# 树索引

- **当前主干头**：`ST00001`
- **gsim 对照基准**（XiangShan CoreMark 50k）：31,932 ms（2026-07-25 重测，3 次中位数，离散 ~1.8%）
- **grhsim AM baseline**（ST00000）：4,191,014 ms（2026-07-25 重测，单次）

## 节点表

| 节点 | 父节点 | 动作 | 状态 | 50k 时间 | vs gsim | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| [ST00000](./nodes/ST00000_baseline.md) | - | baseline | trunk | 4,191,014 ms | 131.2x | 数据内联于节点文档 |
| [ST00001](./nodes/ST00001_am_runtime_profile_counters.md) | ST00000 | AM runtime profile 计数器 | trunk | -（工具节点，off 时零开销） | - | 数据内联于节点文档 |

## 候选动作池

依据见 [AN00001](./analysis/AN00001_am_vs_legacy_structure_gap_20260725.md)（静态结构）与 [ST00001](./nodes/ST00001_am_runtime_profile_counters.md) 50k 稳态 profile（动态计数）。
建议执行顺序即优先级顺序：ST00001 是归因工具（enabler），ST00002 是最大结构杠杆；ST00003/04 与 ST00002 有交互（块变大后 activation 点数自然下降），排在粗化之后。

| 优先级 | 节点 | 动作 | 路线 | 依据 | expected_gain | cost | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | ST00001 | AM runtime profile 计数器（补 `dump_runtime_profile`，per-phase/per-block 计时与激活计数） | 工具 | 生成代码中 `dump_runtime_profile` 原为空 stub，无法归因 | enabler | 低 | trunk |
| P1 | ST00002 | compute block 粗化对齐 legacy（128 硬上限 → 参数化 A/B（512/1024/无界 cost model），detector 密度随边界值下降） | IN-01 | 50k 稳态：2.79 µs/block exec、~21 ns/指令，per-block 固定开销主导（ST00001 profile） | 高 | 中 | open |
| P2 | ST00003 | 激活编译期常量位图化（`activate_forward/backward` 跨 TU 调用 → `word \|= const mask` 内联） | IN-01 | 50k：15.5B activation 调用（forward 14.0B / backward 1.5B） | 高 | 中 | open |
| P3 | ST00004 | block 分派扁平化（三级跨 TU switch + 边界检查 → 固定序直接调用/内联 flag 测试） | IN-01 | 50k：1.12B 次 `execute_block` 分派，legacy 零分派 | 中高 | 中 | open |
| P4 | ST00005 | commit 阶段瘦身（按需执行替代全量扫描 + capture/event 机制减重） | IN-01 | 50k：commit 占 25.7% 时间；capture 25.71B words、commit event marks 31.59B（17 倍于普通 changed） | 中高 | 中 | open |
| P5 | ST00006 | lowering 层死 detector / 冗余消除（静态可证无跨块观察的 changed 不物化） | IN-02 | 指令膨胀 1.82x，部分 detector 可能静态可消除 | 中 | 中 | open |

## 回顾记录

- （每 10 个节点追加一条：日期、覆盖节点范围、候选池调整、主干合并决定）
