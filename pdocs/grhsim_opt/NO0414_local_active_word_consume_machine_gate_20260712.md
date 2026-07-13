# NO0414 Local active-word consume machine gate

日期：2026-07-12

## 1. Generated-copy source gate

按 [NO0413](./NO0413_local_active_word_consume_probe_plan_20260712.md)，本轮只在
`build/xs_grhsim_no0357_direct_state_read_20260712` 的 production generated copy 上删除局部
`activeWordFlags` clear/restore，没有修改 emitter、production source/object 或运行仿真。

结构 parser 对 66 个 compute sources 的 `7,932` 个 active-word blocks 全量校验：

| Metric | Count |
| --- | ---: |
| payload 不写/取址 local active word，可直接转换 | `7,921` |
| 存在 local activation，保留旧协议 | `11` |
| 删除 per-bit local clear | `63,163` |
| 删除 final local-word restore | `7,921` |
| 未知 local LHS | `30`，全部位于上述 11 blocks |
| `&activeWordFlags` | `0` |

`7,853/7,932` 个 blocks 的 `dispatchMask` 为完整 `0xff`，其余 79 个是 batch 边界 partial
word。所有 source 都保留原始行号；重新生成前后 token 与首次删行版相同，batch58 non-debug object
SHA 也完全相同。

首次代表 batch 编译因 copy header 与 production PCH 中的原 header 被 Clang 视作两个文件而在
前端报 helper redefinition；该次没有生成机器样本。把 header/runtime/PCH 改成指向 production
文件的符号链接后，原命令通过。此修正只处理 PCH 文件身份，不改变 probe source。

## 2. Representative O3 gate

先编译 dispatch samples 最高的 `58/62/35/31/41/52` 六个 batch。六个 batch 的 static
instructions 全部下降，范围为 `-0.793% ~ -1.494%`。aggregate：

| Metric | Baseline | Immutable copy | Delta |
| --- | ---: | ---: | ---: |
| instructions | `1,305,677` | `1,292,704` | `-0.994%` |
| instruction bytes | `6,382,527` | `6,328,948` | `-0.840%` |
| branches | `38,103` | `37,060` | `-2.737%` |
| AND | `110,045` | `103,769` | `-5.703%` |
| memory operands | `514,169` | `509,695` | `-0.870%` |
| stack operands | `126,239` | `124,681` | `-1.234%` |

没有以更多 branch、memory 或 stack operands 换取 text 缩小，因此进入 66-batch gate。

## 3. Full 66-batch O3 gate

全量编译使用 16 jobs；当时系统 load 约 `101~113/384`，本轮没有 runtime/perf 采样。66 个
production objects 编译前后 SHA 全部不变，所有 candidate compile exit 0。每个 batch 的
instructions 都下降，范围为 `-0.367% ~ -4.249%`。

| Metric | Baseline | Immutable copy | Delta |
| --- | ---: | ---: | ---: |
| instructions | `14,599,944` | `14,460,047` | `-139,897 / -0.9582%` |
| instruction bytes | `71,457,066` | `70,781,169` | `-675,897 / -0.9459%` |
| branches | `560,285` | `551,042` | `-9,243 / -1.6497%` |
| MOV | `4,643,114` | `4,612,498` | `-30,616 / -0.6594%` |
| TEST | `619,295` | `598,290` | `-21,005 / -3.3918%` |
| AND | `1,107,433` | `1,043,678` | `-63,755 / -5.7570%` |
| OR | `1,740,300` | `1,726,188` | `-14,112 / -0.8109%` |
| memory operands | `5,885,543` | `5,839,228` | `-46,315 / -0.7869%` |
| stack operands | `1,491,878` | `1,470,552` | `-21,326 / -1.4295%` |

这通过 NO0413 的 aggregate static instructions `-0.5%` 门槛。

## 4. Existing-sample dynamic projection

为连接 NO0404 的 5,590 个 direct compute samples，使用保留原行号的 source 重新编译 66 个
`-gline-tables-only` objects。两组 exact `.text` gate 均为 `66/66`：

- NO0401 baseline debug vs production；
- immutable debug vs immutable non-debug。

单 source-line 的首次投影得到 `206.33` saved-sample equivalent，但不能采用：删除 local state 后，
Clang 把大量保留的 word-gate 指令从 word-gate 行迁移到相邻 bit-gate 行。静态 role 也明确显示这种
line-table redistribution：bit-gate `+13,933`，word-gate `-52,496`。

修正后按完整 active-word source block 聚合所有 dispatch 行，再用同 block 的 old/new machine
opcode 或总指令比例加权该 block 的既有 samples。局部回增不截断，直接作为负贡献进入净值：

| Projection | Saved-sample equivalent | Direct compute share |
| --- | ---: | ---: |
| same word + same opcode | `106.429` | `1.9039%` |
| same word + all dispatch instructions | `124.311` | `2.2238%` |

两种口径均超过预声明的 `56/5590 = 1%` 门槛。全部 dispatch line static instructions 从
`399,712` 降到 `299,288`，即 `-100,424/-25.12%`；因此收益不是只依赖 35 个直接落在
clear/restore 行上的 samples，而是 immutable dataflow 同时简化了 word/bit gate 的寄存器与控制流。

## 5. Decision and implementation scope

generated-copy machine gate 通过，进入默认关闭的 emitter probe。但工程实现不复刻“先生成再扫描
local writes”的实验 parser，而采用更小且可证明的完整 word 条件：

```text
compute phase && dispatchMask == 0xff
```

完整 word 覆盖 `7,853/7,932 = 99.00%` 的当前 SimTop compute blocks。activation emitter 只把同 word
且 bit index 大于 current bit 的 target 写入 local active byte；memory-row helper 也只接收
`localLaterMask`。因此一个完整 word 会在当前 block 内按顺序消费全部 local activation：

1. 保留入口 global clear、word gate 和八个 bit gates；
2. 删除八个 per-bit local clears；
3. 删除末尾 local-word restore；
4. partial word 继续使用旧协议，保留跨 batch later-bit activation；
5. commit phase 暂不改变。

该实现比 generated-copy probe 少优化 partial words，但避免为仅 79 个边界 blocks 引入新的 emitter
预分析。下一阶段先加 option、synthetic forward/backward/partial-word 测试和 fresh source/O3 复核，
通过后才运行 SimTop 10k/50k 功能与 fixed-ASLR old/new/old。

产物：

```text
build/logs/xs_perf/no0413/make_immutable_consume_probe.py
build/logs/xs_perf/no0413/compile_probe_objects.py
build/logs/xs_perf/no0413/compare_probe_objects.py
build/logs/xs_perf/no0413/analyze_dispatch_dynamic_impact.py
build/logs/xs_perf/no0413/immutable_consume_transform.tsv
build/logs/xs_perf/no0413/immutable_consume_object_{compare,summary}.tsv
build/logs/xs_perf/no0413/dispatch_{static_line_role,static_word_block,dynamic_impact_rows}*.tsv
build/logs/xs_perf/no0413/immutable_debug_text_identity.tsv
```
