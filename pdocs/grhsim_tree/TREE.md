# 树索引

- **当前主干头**：`ST00009`（2k 同会话 −4.9%，.text −7.1%；50k L2 豁免，ratio 待回填）
- **阶段目标（IN-20260725-05）**：AM 2k 对齐 legacy 2k（2,021 ms）前禁止 50k 测量。当前 AM 2k = **138,683 ms，差距 68.6x**（gsim 参照 1,607 ms，差距 86.3x）
- **gsim 对照基准**（XiangShan CoreMark 50k）：31,932 ms（2026-07-25 重测，3 次中位数，离散 ~1.8%）
- **grhsim AM baseline**（ST00000）：4,191,014 ms（2026-07-25 重测，单次）
- **2k 门控基准**（-C 2000，solo，`setarch -R` + `taskset -c 7`）：gsim 1,607 ms；legacy grhsim 2,021 ms（2026-07-25 补测）；AM baseline 140,573 ms（87.5x gsim / 69.5x legacy）——2026-07-25 起作为 L1 门控口径（README §4）

## 节点表

| 节点 | 父节点 | 动作 | 状态 | 50k 时间 | vs gsim | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| [ST00000](./nodes/ST00000_baseline.md) | - | baseline | trunk | 4,191,014 ms | 131.2x | 数据内联于节点文档 |
| [ST00001](./nodes/ST00001_am_runtime_profile_counters.md) | ST00000 | AM runtime profile 计数器 | trunk | -（工具节点，off 时零开销） | - | 数据内联于节点文档 |
| [ST00002](./nodes/ST00002_compute_block_coarsening.md) | ST00001 | compute block 粗化（128 → 512/1024 A/B） | pruned-regression | 2k 门控：+15.1% / +23.0% 回归（未跑 50k） | - | 数据内联于节点文档 |
| [ST00008](./nodes/ST00008_grhsim_am_activity_schedule.md) | ST00001 | grhsim-am-activity-schedule（coarsen+dp 块形成） | pruned-regression | 2k 门控：cap512 +17.5% / 浅 codp128 +5.7% / 深 codp128 +10.2%（未跑 50k） | - | 数据内联于节点文档 |
| [ST00003](./nodes/ST00003_activation_const_bitmap.md) | ST00001 | 激活编译期常量位图化 | pruned-regression | 2k 门控：+23.8%（.text +20%，fetch-bound） | - | 数据内联于节点文档 |
| [ST00009](./nodes/ST00009_emit_size_reduction.md) | ST00001 | 发射体积压缩（块内值局部化） | trunk | 2k：−4.9%（同会话交错中位数，L2 豁免）；.text −7.1% | - | 数据内联于节点文档 |
| [ST00005](./nodes/ST00005_commit_slimming.md) | ST00009 | commit event 生命周期 sticky 化 | pruned-no-gain | 2k：约 −1.06%（三组同会话成对复核，未跑 50k）；.text +0.887% | - | 数据内联于节点文档 |
| [ST00011](./nodes/ST00011_commit_write_scaffold.md) | ST00009 | commit 写槽脚手架瘦身 | pruned-no-gain | 2k：−0.64%/−0.74%（<2% 线）；.text 持平；代码已回退 | - | 数据内联于节点文档 |

## 候选动作池

依据见 [AN00001](./analysis/AN00001_am_vs_legacy_structure_gap_20260725.md)（静态结构）与 [ST00001](./nodes/ST00001_am_runtime_profile_counters.md) 50k 稳态 profile（动态计数）。
**2026-07-25 AN00002 复盘修正**（[AN00002](./analysis/AN00002_am_vs_legacy_coarsen_reflection_20260725.md)）：AM 未使用 legacy 的多轮迭代 coarsen（`ComputeNodeBuilder`，非 DP），但移植它不是出路——legacy 与 AM 粒度/执行语义相近却快 25x，差距在运行时原语成本（内联 bitmap OR/直接分派 vs 跨 TU 调用/三级 switch）。2k 分解：F≈1.56 µs/exec（占 baseline compute 55%）、m≈9.5 ns/指令。固定开销与冗余求值同为一阶项，ST00003/04 恢复高优先级。
**2026-07-25 ST00008 再确认**：coarsen+dp（静态 cut 目标）同粒度下也被 2k 门控证伪（边 -7.6% 但 block exec +11%）；每次 block exec 成本 ~2.8 µs 在所有块形成方案下不变——~~原语成本（ST00003/04）是当前唯一未被证伪的杠杆~~（已被 AN00004 修正）。
**2026-07-25 AN00004 范式修正**（[AN00004](./analysis/AN00004_am_emu_fetch_bound_20260725.md)）：ST00003 内联使 .text +20%、时间 +23.8%——**AM emu 是取指瓶颈（360MB vs legacy 84MB），代码体积才是硬通货，函数调用是压缩而非开销**。一切增大发射体积的优化（内联类）预警；主攻方向转为减少发射指令总量。
**2026-07-26 ST00005 归因修正**：commit event sticky 化让已计数 mark/clear 合计减少 1.728B 次，却只换来约 1.06% 的 2k 收益且 `.text` +0.887%，证明 event 生命周期不是 commit 的主成本。commit 热点重新定位到 483,654 次巨块执行及 218,588 个 state-write 槽的 event-hit 脚手架；后续改攻实际发射指令数，不再单独优化 mark/clear。

| 优先级 | 节点 | 动作 | 路线 | 依据 | expected_gain | cost | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0 | ST00001 | AM runtime profile 计数器（补 `dump_runtime_profile`，per-phase/per-block 计时与激活计数） | 工具 | 生成代码中 `dump_runtime_profile` 原为空 stub，无法归因 | enabler | 低 | trunk |
| P1 | ST00009 | 发射体积压缩（块内值局部化；死 detector 消除经审查放弃——物化无静态死项） | IN-01/IN-02 | 2k −4.9%（同会话交错）、.text −7.1%，首个正收益节点 | 高 | 中 | trunk |
| P2 | ST00011 | commit write guard/dispatch 稀疏化（避免巨块逐写槽 event-hit） | IN-01/ST00005 | 2k −0.64%/−0.74% <2% 线：脚手架非主体，commit 巨块主体是写体必要工作；机械瘦身方向关闭 | - | - | pruned-no-gain（代码已回退） |
| P1 | ST00010 | 局部化扩展（宽值 >64bit 局部化 + detector 旧值槽活性降级，ST00009 后续，覆盖率 27.2% → 目标 50%+） | IN-01 | ST00009 已证体积-时间传导（−7.1% → −4.9%）；commit 侧连续两轮 <1% 后，体积/存储方向回到主攻位 | 中 | 中 | open |
| P2 | ST00012 | 存储类型化（窄值窄槽：bool/uint8/uint32 类型槽替代统一 uint64 values_，对齐 legacy 存储形态） | AN00005 | AN00005 因子 1：legacy 每值 1-4B vs AM 8B，每周期状态遍历体积差数倍；与 ST00010 互补 | 高 | 高 | open |
| P3 | ST00010 | 局部化扩展（宽值 >64bit 局部化 + detector 旧值槽活性降级，ST00009 后续，覆盖率 27.2% → 目标 50%+） | IN-01 | ST00009 已证体积-时间传导（−7.1% → −4.9%） | 中 | 中 | open |
| P3 | ST00007 | 冗余求值消除 / guard 强化（块内条件执行或激活 guard 加强，使值未变的 block 不整体重算） | IN-01 | ST00002 归因：activation:changed ≈ 10:1；注意 guard 也会增体积，需以减指令总量为约束 | 中 | 中高 | open |
| P4 | ST00004 | block 分派扁平化（三级跨 TU switch + 边界检查 → 固定序直接调用/内联 flag 测试） | IN-01 | AN00004 预警：分派内联增大体积，动态收益预估 <2%；1.12B 次分派/50k | 低 | 中 | parked |
| - | ST00002 | compute block 粗化（128 → 512/1024） | IN-01 | 2k 门控回归 +15.1%/+23.0%；AN00002/AN00004：冗余求值淹没固定成本节省，粒度不改变取指总量 | - | - | pruned-regression |
| - | ST00003 | 激活编译期常量位图化 | IN-01/IN-04 | 2k 门控 +23.8%（.text +20%）；AN00004：fetch-bound 下内联必然回归 | - | - | pruned-regression |
| - | ST00008 | `grhsim-am-activity-schedule`：coarsen+dp 块形成 | IN-03（强制） | cap512 +17.5% / 浅 codp128 +5.7% / 深 codp128 +10.2%；coarsen 截断 bug 已修复（AN00003），静态 cut 是弱代理 | - | - | pruned-regression（工具链保留，默认 greedy） |
| - | ST00005 | commit event 生命周期 sticky 化 | IN-01 | mark/clear −1.728B，但 2k 仅约 −1.06%、.text +0.887%；主成本不是生命周期簿记 | - | - | pruned-no-gain（实验代码已回退） |

## 回顾记录

- **2026-07-25，首轮回顾（编号范围 ST00000–ST00009）**：主干 ST00000 → ST00001（profile 工具）→ ST00009（首个收益节点，2k −4.9% / .text −7.1%）。三次划分/块形成尝试（ST00002、ST00008 浅/深）与一次内联尝试（ST00003）全部 pruned-regression，换来两条范式级结论：① runtime 由共生激活与 per-exec 成本决定，静态 cut/粒度是弱代理（AN00002/AN00003）；② AM emu 是 fetch-bound，代码体积是硬通货，函数调用是压缩而非开销（AN00004）。候选池已按此重构：主攻发射体积（ST00009 trunk、ST00010 后续）与 commit 机制（当时为 ST00005），分派/内联类 parked。测量协议升级：L1 2k 门控 + emit 级对比必须同会话交错（跨会话漂移 ~3.7%）。expected_gain 重估：体积类每 −7% 约对应 −5% 时间；50k ratio 仍待回填（131.2x 基准未变）。
- **2026-07-26，ST00005 收口**：commit event 生命周期减重功能正确但未过 2k 收益线，pruned-no-gain，主干仍为 ST00009。负结果把 commit 后续方向收窄为“减少巨块内实际写槽脚手架”（ST00011），而非继续削 L1 热 mark/clear。
