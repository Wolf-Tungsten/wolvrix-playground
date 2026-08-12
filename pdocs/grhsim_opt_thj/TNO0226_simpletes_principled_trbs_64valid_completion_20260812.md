# TNO0226：SimpleTES 原则化 TRBS 64-valid 探索完成总结

日期：2026-08-12

## 1. 本轮范围与最终结论

本轮沿用原则化 TRBS native default 作为研究基线，使用 GPT-5.6 Sol max、THJ Codex config/auth，在 node032 上从
已有 `32/32 valid` checkpoint 单调扩容到 `max_generations=128`、`max_valid_evaluations=64`。研究实例的 lineage
为：

```text
SimpleTES/checkpoints/grhsim_simtop_50k/
  principled_trbs_gpt56sol_max_fresh2_20260803_030316/
  2026-08-03/instance-44cd457d/
```

最终以 `db_state_032217` 为准，达到 `64/64 valid` 后自然停止。最佳候选为
`297a70325057463d96eb062bf71234cc`（gen72，chain2），在 fixed-ASLR、空闲 CCD、每个 order 内固定单 CCD 的
ABBA+BAAB、NUMA、
PMU、进程 affinity、功能签名和 `50k` workload 门禁全部通过的情况下得到：

| 指标 | control | candidate | 变化 |
| --- | ---: | ---: | ---: |
| SimTop 50k Host walltime | `48,074.00 ms` | `43,300.00 ms` | 减少 `4,774.00 ms`，改善 `9.930524%` |
| score |  |  | `1.1102540415704387` |
| control spread |  |  | `197 ms` |
| candidate spread |  |  | `68 ms` |

这是本轮最终 headline；它不是把 initial same-code canary 的噪声当成收益。initial control 仅为
`47,772.00 -> 47,676.00 ms`（`96 ms/0.200955%`），只用于校验机器窗口，不能解释后续约 `9.93%`。

## 2. 最佳候选的 order 细节

最佳候选的正式样本全部通过 `pre_gate`、continuous monitor、fixed-ASLR personality、单 CPU affinity、NUMA
locality、PMU schedule、CPU migration 和功能日志检查。每个 order 的四个样本固定在同一个 CCD 内；ABBA 使用
`node0:56-63,248-255`（CPU56），BAAB 使用另一组独立的 `node0:88-95,280-287`（CPU88）。也就是说，两个
order 不是把 workload 在同一 CCD 上交错执行，而是分别使用独立空闲 CCD；每个 sample 还使用 fresh staged
NUMA-first-touched artifact，避免把前一个 order 的 resident pages 当作后一个 order 的隐含热身。

| order | 样本顺序（ms） | control mean | candidate mean | improvement |
| --- | --- | ---: | ---: | ---: |
| ABBA | `control 48066 / cand 43277 / cand 43311 / control 48119` | `48092.50` | `43294.00` | `9.977647%` |
| BAAB | `cand 43340 / control 48154 / control 47957 / cand 43272` | `48055.50` | `43306.00` | `9.883364%` |
| pooled | 上述 8 个样本 | `48074.00` | `43300.00` | `9.930524%` |

ABBA 与 BAAB 的 improvement gap 为 `0.094283 percentage points`，低于既定 `0.25 pp` 门槛；两边方向一致，
所以该结果是有效的 endpoint，而不是单一 order 的偶然优势。样本的二进制页审计也提供了本次 baseline-repin
修复的直接回归证据：control 为 `22,260 PT_LOAD / 20,825 resident-local / min 20,000`，candidate 为
`20,401 PT_LOAD / 18,965 resident-local / 旧 gate 若 repin 会错误要求 20,000`；新 fixed coverage gate 要求
`18,330`，两者均严格 `local_ratio=1.0`。

最佳样本 PMU 的 control→candidate 变化为：

| event | control mean | candidate mean | 相对变化 |
| --- | ---: | ---: | ---: |
| `cycles:u` | `176,302,759,099.0` | `158,798,582,686.75` | `-9.928476%` |
| `instructions:u` | `160,743,795,708.5` | `149,144,920,870.0` | `-7.215753%` |
| frontend no-ops | `765,351,267,670.0` | `704,098,914,513.5` | `-8.003169%` |
| frontend cmask no-dispatch | `97,117,611,616.0` | `88,562,505,296.0` | `-8.809016%` |
| backend stalls | `78,649,326,258.25` | `57,198,797,962.0` | `-27.273632%` |

这些计数是最佳 patch 的配套证据，不替代 walltime headline，也不单独证明某一个编译器机制的因果贡献。

## 3. 搜索账目与基础设施状态

最终 `metadata.json` 的绝对状态：

| 项目 | 数值 |
| --- | ---: |
| generation attempts | `83` |
| completed evaluations | `74`（含 initial control） |
| generated valid candidates | `64/64` |
| generation failures | `0` |
| generation cancellations | `1`（达到 valid 上限后的正常 stop cleanup） |
| evaluator failures/rejects | `0` |
| best score | `1.1102540415704387` |
| best node | `297a70325057463d96eb062bf71234cc` |

64 个 generated candidate 中 `46` 个 pooled walltime 正向、`18` 个负向；valid candidate 改善百分比中位数为
`6.276637%`。这个分布包含同一 chain 上的连续 refinement，不能把每个样本视为独立统计试验，但它说明收益并非只
来自一个 isolated candidate。没有 eval infrastructure reject；最终唯一的 generation cancellation 是达到 `64/64`
后的收尾行为。

本轮曾遇到两类会阻塞探索的基础设施问题：

1. node032 缺少匹配的 `clang-scan-deps-19`，导致 fresh candidate build 连续 retry；scanner 恢复后搜索继续推进。
2. c333 的 `19,877` 页 candidate 被旧固定 `20,000` 页门禁误杀；`414ad80` 按 control ELF footprint 临时缩放门槛，
   使 c333 首次完成正式 50k，并取得 `48,120.25 -> 44,186.75 ms`（`3,933.50 ms/8.174313%`）。

之后的最终阶段没有 eval reject，说明 scanner 与 NUMA gate 修复都发挥了作用；本次后续提交 `869a11a` 又消除了
“未来 repin control 使 gate 再次漂移”的剩余风险。

## 4. 收益路线演进

搜索是在原则化 TRBS baseline 上继续做 default-path、zero-option 的通用 emitter 探索，主要路线如下：

| 阶段/候选 | control -> candidate walltime | 绝对收益 | 解释 |
| --- | --- | ---: | --- |
| initial same-code canary | `47,772.00 -> 47,676.00 ms` | `96 ms/0.200955%` | 机器噪声基线 |
| 先前 32-valid typed persistent-state best | `47,656.125 -> 44,625.625 ms` | `3,030.500 ms/6.359099%` | typed persistent-state seed（见 [TNO0218](./TNO0218_simpletes_principled_trbs_second_fresh_completion_20260804.md)） |
| c333 field-sensitive/native-bool state | `48,120.25 -> 44,186.75 ms` | `3,933.50 ms/8.174313%` | 让 persistent non-memory state 变成按 kind/wide bucket 的直接 typed fields |
| 本轮最终 best `297a...` | `48,074.00 -> 43,300.00 ms` | `4,774.00 ms/9.930524%` | 在上述 state layout 上将 materialized `kBool` value bucket 也变为真正 `bool` |

邻近高分候选也值得记录，但尚未构成独立保留结论：

| candidate | gen | walltime | 改善 |
| --- | ---: | --- | ---: |
| `846174d1...` | 76 | `47,819.75 -> 43,105.50 ms` | `4,714.25 ms/9.858374%` |
| `9d32b51c...` | 79 | `48,030.50 -> 43,299.25 ms` | `4,731.25 ms/9.850512%` |

`846174d1...` 基本重复了最佳的 typed state + native bool value 路线；`9d32b51c...` 进一步尝试 `char8_t`
作为 owning `u8` storage，仍取得高分但略低于最佳。它们说明同一表示/布局 family 有连续收益信号，不能说明
`char8_t` 本身已经被单独消融证明。

## 5. 最佳 patch 机制与证据边界

最佳候选是 `default-path`、`enable_options=[]`、仅修改 `lib/emit/grhsim_cpp.cpp` 的一文件 patch，基于
Wolvrix `d3ed9dea975b`（parent `52ba7d9edcd7`）。核心改动：

1. 保留按 scalar kind / wide word count 分桶的 field-sensitive persistent state，并为每个 state 使用 bucket-local
   `logicSlotIndex`；原 byte `slotIndex` 继续承担既有排序/alias metadata。
2. 对 materialized combinational values，只把 `kBool` bucket 从 `std::uint8_t` owning objects 改为
   `std::array<bool, N>`，reset 也使用 `bool{}`。
3. state-shadow、memory-write staging、reg-to-memory storage、schedule、events、guards、activation 和
   expression lowering 不变；没有 SimTop 名字、端口或 workload 特判。

这解释了为什么“改变状态存储”可能影响别名分析、依赖链和代码布局：它不是抽象语义改变，而是让生成的 C++
对象拥有更窄的真实类型边界和更直接的成员地址表达式，编译器因此可能消除 byte↔bool normalization、收紧
依赖/别名推断、改变 field/函数布局并减少 backend stalls。最佳样本的 PMU 与 walltime 同向，但这些是机制证据，
不是单独的因果证明；最终仍以 SimTop 50k walltime 为准。

候选 patch 尚未落入 Wolvrix，也尚未默认开启。当前研究结果只完成“发现与验证”；正式 landing 仍应先做独立
消融（state buckets、native bool value、direct member layout 等），再跑 fresh build、功能回归与每个 order 内固定 CCD
的正式 50k。

## 6. 可复现身份与后续继续能力

| 对象 | 值 |
| --- | --- |
| final checkpoint | `db_state_032217` |
| best node | `297a70325057463d96eb062bf71234cc` |
| best program/code SHA-256 | `151ec5cabe2ff88d0efd989d061abaffe5a9aa411c3d8339b096ee04bf473278` |
| best patch SHA-256（patch 字符串） | `d7ec315534865641cd3a3cc2f76ca70cbf77c3c6191ce0688135ca3016a45325` |
| final `nodes.json` SHA-256 | `9d6083212829d6f6d58adaf585c04edffe2554fb592bffcf9470619914fe303d` |
| final `metadata.json` SHA-256 | `d44feffe58abb5b7106ff0aa4f2cb66d1f0cce6813eaab290e1cb5a86e1dc97b` |
| final score CSV SHA-256 | `2a62c7cc5234f8723eb1dd17a4121b182194ac9d5d1f7cfc5122028abbb62093` |
| live SimpleTES code | `869a11a` |

SimpleTES live checkout 已保留可继续 research 所需的 evaluator、schema、Codex continuation 和 checkpoint 兼容能力；
本轮结束后没有启动新实例。若后续以最新 best 为 baseline，应显式生成新的 post-best empty-control/repin
checkpoint，并使用固定 coverage runtime；不要把旧 candidate binary 伪装成 control，也不要把本轮高分直接当作
Wolvrix 默认。
