# NO0510 Batch 27 event-predicate codegen probe plan

日期：2026-07-13

## 1. Problem

[NO0503](./NO0503_simtop_pure_event_word_bypass_build_codegen_gate_20260713.md) 发现 production bypass 的 22 个 changed
objects 合计回退 `10,145` text bytes/`1,536` instructions，其中 batch 27 任意一个 wrapper 都会独立触发约
`+11.5 KiB/+1,789 instructions` 的巨型函数 codegen cliff。扣除 batch 27 后其余 21 batches 整体改善。

plain outer condition 直接读取 `event_edge_slots_[0]`，Clang 可在 wrapper body 内推导该字段为 posedge，并简化所有内部
event checks；该额外优化可能使巨型函数跨过另一个 vectorization/register-allocation/layout 阈值。本轮只验证这个编译期
相关性假设，不改 GRH eligibility 或运行语义。

## 2. Generated-copy variants

以 NO0357 batch 27 object 为 baseline、NO0501 production object 为 plain candidate，在 generated source 副本中只改变两个
outer predicates：

1. `volatile_ref`：将同一 event slot 绑定为 `const volatile` reference，再用于 outer equality；
2. `volatile_copy`：先写入 local volatile value，再读取 equality，作为更强但多一次 stack traffic 的 control；
3. `noinline_predicate`：通过 noinline equality helper 隐藏相关性，作为会增加 dynamic call 的诊断上界，不作为首选实现。

payload、entry tests、内部 event guards、active-word clear/restore 和 call order 全部保持不变。所有变体使用 candidate 的同一
PCH、Clang 21.1.5、C++20 `-O3` 独立编译。

## 3. Static gates

先只比较 batch 27 的 `.text`、instructions、memory forms、jumps 和 calls：

- variant 必须显著消除 plain 的 `+11,477/+1,783` cliff；
- 首选形态不得增加 dynamic function call；
- 若仍出现同级 cliff，停止该形态；
- 若 `volatile_ref` 将 batch 27 恢复到接近 baseline，则扩展到 22 个 production batches，要求 aggregate 四项不比 plain
  candidate 差，并重点检查 hot batches 35/58/21；
- generated-copy object 结果只决定是否值得实现，不能替代 synthetic 结构/功能和 fresh SimTop runtime。

## 4. Runtime boundary

本 probe 只依赖编译产物，不使用 compile wall time。NO0507 PMU 因 NO0509 记录的共享机负载暂缓；即使新形态静态更小，
也必须等功能门禁后与 plain candidate、NO0357 做 fixed-ASLR 相邻夹测，不能由静态指标宣布提速。
