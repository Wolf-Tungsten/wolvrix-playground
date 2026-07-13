# NO0435 Current commit machine/source attribution plan

日期：2026-07-13

## 1. Problem and input

[NO0434](./NO0434_full_active_word_exact_entry_runtime_gate_20260713.md) 已停止负收益的 compute dispatch
full-word consume。回到 [NO0388](./NO0388_direct_state_read_instruction_profile_gate_20260712.md) 的 latest direct
profile，GrhSIM commit 为 868 个 `instructions:u` samples，约 21.700B instructions，占 direct/GSim profile
excess 的 `24.986%`，但 NO0403-NO0414 只深挖了 compute，没有对这批 latest commit samples 做同口径归因。

868 个 samples 分布在 42 个 commit batches；头部为：

```text
commit115 = 253
commit105 = 163
commit87  =  85
```

commit115/105 合计 416 个，占 commit samples 的 `47.93%`。本轮先复用既有 50k profile，不重跑仿真、不修改
emitter，直接回答 current GrhSIM commit 相比 GSim 具体多做了什么。

## 2. Exact-code mapping gate

输入固定为 NO0388 的 25M-period、0-lost、fixed-ASLR exact-entry direct profile。NO0379 exact binary 只改变最终
显式链接/padding，函数体来自 NO0357 production objects；perf leaf frame 已给出 `eval_commit_batch_N()+offset`。

对 42 个 sampled commit translation units：

1. 使用 NO0357 同一 generated source、Clang/C++20/O3/PCH，只增加 line table；
2. 逐 object dump `.text`，要求 debug object 与 NO0357 production object SHA256 完全相同；
3. 要求 868/868 offsets 都落在对应 commit symbol 的真实 instruction boundary；
4. 用 `addr2line -i` 映射 generated source/runtime frames，并连接最近的 supernode、op kind 和 value/state name；
5. 任一 sampled object text 不同或 offset 丢失时，不对该批数据作 source 归因。

## 3. Mutually exclusive classes

按实际机器指令和 source context 互斥分类：

| Class | Meaning |
| --- | --- |
| entry dispatch | active-word/bit guard、batch/supernode 入口分发 |
| event/write guard | edge/event 条件和 write-port outer guard |
| data/mask preparation | next data、mask、index、masked merge 的必要计算/读取 |
| changed compare | state/next 比较和对应 branch |
| state writeback | scalar/wide/memory state store |
| reader activation | changed 后 reader active mask 更新与汇总 |
| memory-specific | memory address conflict、row/port selection 和 dynamic memory helper |
| runtime/other | 可识别 helper、控制流邻接仍不足或 unresolved |

同时输出 batch/opcode/operation/state-family 交叉表。source line 只作归属线索；若 sample 落在 inline helper line 0，沿用
NO0411/NO0412 的同 basic-block 严格邻接规则，不能跨 control transfer 猜测。

## 4. GSim cross-check and decision gate

对占比最高的 class 和 commit115/105 代表 state families，在 same-FIR GSim generated source 中检查对应成员写入、old
snapshot、changed/active 累积与 machine shape。`commit` 是 GrhSIM phase 名，不把 21.700B 全部当作 GSim 不存在的工作；
只有能找到语义对应项后，才区分共同 RTL payload 与 GrhSIM 增量框架。

进入 emitter probe 必须同时满足：

1. 可消除/可合并 class 覆盖至少 10% commit samples，即至少 87/868；
2. 机器级保守上界至少为 direct total instructions 的 1%，即约 1.669B 或 67 samples；
3. GSim 对照给出语义等价且更窄的生成形态，或 GrhSIM 内部存在可证明冗余；
4. 不重复已验证的全局 branchless、commit supernode cap、activation table 或 full-mask specialization。

若 dominant samples 是必要 data/state work，或候选低于门槛，则不改 emitter，转回 compute payload 粒度。本轮结果只形成
诊断 gate，不以 source 行数或单个热点函数尺寸代替动态证据。

## 5. Planned artifacts

```text
build/logs/xs_perf/no0435/commit_debug_objects/
build/logs/xs_perf/no0435/commit_text_identity_manifest.tsv
build/logs/xs_perf/no0435/commit_sample_rows.tsv
build/logs/xs_perf/no0435/commit_{class,batch,opcode,operation,state_family}_summary.tsv
build/logs/xs_perf/no0435/commit_attribution_summary.txt
```
