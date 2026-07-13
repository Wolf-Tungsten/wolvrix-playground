# NO0262 Multi-write true-merge plan

日期：2026-07-10

## 目标与边界

目标是恢复 [NO0260](./NO0260_phr_multi_write_scalarization_gap_20260710.md) 中 PHR 一类
scalarized register array 的多个 priority dynamic writes，生成真正的 `kMemory` 和有序
`kMemoryWritePort`，消除逐行 one-hot compute network。

本计划不改变 [NO0205](./NO0205_reg_to_mem_single_user_correct_mode_20260623.md) 的默认
intent discovery。shared-read 候选只能进入独立的 strict true-rewrite probe；任一证明失败
都原样保留 scalar IR，不打 `regToMem.intent.*` attrs。

## P0：IR 表示与 synthetic matcher

新增内部表示：

```text
PriorityWriteBranch {
  addr, data, mask, commonTerms, events, eventEdges, priority
}

MultiWriteFamily {
  ordered branches[], optional reset/fill
}
```

先用 4-row synthetic design 覆盖两个 dynamic addresses、明确 priority collision、reset 和
extra static read user。matcher 必须证明每一行的 nested mux/OR guard 可转置为同一组
`(addr_j == row, data_j)` branches。

## P1：独立 shared-read true candidate discovery

保留现有 `discoverIntentAnchors()` 不动，新增只服务 true merge 的 discovery：

- concat 仍必须只被目标 dynamic slice 使用；
- register-read 可以有 extra users；
- group 必须覆盖每个 register 的全部 read ports；
- 失败 candidate 不进入 `annotateGroup()`。

rewrite 时为每个原 register read 创建 constant-row `kMemoryReadPort` 并全局替换其 result；
目标 concat+slice 另用 dynamic-row `kMemoryReadPort` 替换。这样 extra users 仍读同一 memory
state，不保留 scalar mirror。

## P2：有序 multi-write rewrite

对每个 row 的 scalar write 同时分解 update guard 和 nested data mux，跨 row 对齐 branch：

1. 相同 priority 的所有 row 必须共享 addr/data/mask/common terms/event；
2. row-specific 条件只能是 `addr == row` 或已支持的 all-ones reduce form；
3. reset 必须可证明为统一 fill 或 packed per-row fill；
4. 同 cycle 地址冲突时，生成的 memory write顺序必须与原 nested mux priority 完全一致；
5. old writes、dead one-hot/mux cone 和 scalar declarations 仅在完整 rewrite 成功后删除。

## P3：结构 gate

在现有 pre-reg-to-mem checkpoint 上只跑 transform，要求：

- 当前 `409` 个 single-write true groups 和 `351` 个 intent groups 不减少；
- PHR `phr_0..531` 收敛为一个 memory group；
- PHR 28 个 dynamic writes 和 reset/fill 数量与 GSIM 结构对应；
- batch54 的 `Phr.sv` 13,489 个 LogicAnd 大幅下降；
- 不产生 shared-read intent attrs。

## P4：correctness 与 runtime gate

顺序：

1. `transform-reg-to-mem` CTest；
2. emitter/memory CTest；
3. 小型 multi-write harness，覆盖同地址 collision priority；
4. VtypeBuffer 200k no-regression；
5. fresh SimTop 10k difftest；
6. fresh SimTop 50k difftest；
7. load-aware old/new/old 50k 与 perf stat；
8. post-profile 验证 batch54/PHR sample 退热。

## 停止条件

以下任一情况发生即不进入完整 SimTop codegen：

- 无法从每行 nested mux 唯一恢复同一 priority branch 序列；
- multi-write collision 顺序无法通过 IR 显式保证；
- extra read replacement 需要 scalar/memory 双份 state；
- synthetic harness 在 reset、collision 或 event ordering 上不等价；
- PHR 静态 LogicAnd 没有明显下降。

该方向的预期收益不是由 `-Os` 压缩机器码，而是把 `532 * 约25` 条逐行判断恢复为约 28 条
动态索引写。实现应从 P0/P1 开始，不直接在完整 SimTop 上试错。
