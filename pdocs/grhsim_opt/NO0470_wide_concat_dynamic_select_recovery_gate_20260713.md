# NO0470 Wide concat dynamic-select recovery gate

日期：2026-07-13

## 1. Group closure

按 [NO0469](./NO0469_wide_concat_dynamic_select_recovery_plan_20260713.md) 从 generated source 反向恢复 113 个 sampled
accumulation rows。结果为 61/61 concat groups、113/113 source locations 与 machine offsets 全部连接成功；没有使用最近 comment
猜 group/consumer。

各 group 的 destination、operand declarations、accumulation、同 supernode non-accumulation uses 均闭合。113 samples 按
consumer 分类为：

| consumer | groups | samples | operand-count range |
| --- | ---: | ---: | ---: |
| dynamic wide shift | 5 | 28 | 1064--1064 |
| materialized/external | 15 | 28 | 6--1064 |
| single other consumer | 15 | 18 | 4--577 |
| dynamic slice | 9 | 17 | 69--4096 |
| other slice | 7 | 12 | 16--143 |
| multiple other consumers | 10 | 10 | 16--16 |

## 2. Existing bypass boundary

代表热点确实体现现有 matcher 的边界：

- 5 个 1064x1 concat groups 各自产生 1064-bit local，然后执行 `grhsim_lshr_words(..., dynamic_index, 1064)`；
- 512x1 local groups 随后执行 1-bit `grhsim_slice_words` dynamic select；
- 1024/4096-bit materialized groups也有 dynamic bit select，但 concat value 仍是 tracked/materialized storage；
- 143x6 等 groups 有多个 dynamic lane slice users。

部分 operand 已是 `kMemoryReadPort` 结果，部分是没有 `regToMem.intent`/`svPackedArray` 属性的规则 state refs，所以不会命中
current direct-storage bypass。但“未命中”本身不代表都可安全绕过：dynamic wide shift 仍产生完整宽结果，materialized/multi-user
group 也不能删除 concat。

## 3. Safe matcher gate

只有 27 个 local concat groups 是单一 consumer，共 57 samples/direct `0.854%`：

| local single-consumer class | samples |
| --- | ---: |
| dynamic wide shift | 28 |
| dynamic slice | 11 |
| other single consumer | 18 |

其中 dynamic shift 与 dynamic slice 的结果语义不同，不能合并成 indexed-lane matcher；真正 local dynamic-slice 上界只有
11 samples。把所有 local single-consumer 强行合并也只有 57，仍低于 67/direct `1%`。所有 dynamic/other slice 合计 29，
同样不过门槛。

## 4. Decision

NO0469 的第一项 source gate 已失败，没有同一安全 matcher class 覆盖至少 67 samples。因此：

- 不运行 GSim full crosscheck、post-transform 结构诊断或 generated-copy O3 probe；
- 不放宽 reg-to-mem intent/packed-array matcher；
- 不用 source regex 猜 `state_logic_storage_` stride 或 memory address mapping；
- 不把仍需完整宽结果的 dynamic shift 当作单-lane select；
- 保留 201,597 行 static concat accumulation 作为后续全局证据，但不据静态数量实现低覆盖改写。

下一步继续重排 comment/fused residual，优先检查 concat accumulation 之外的 repeated materialization 类，而不是逐个低覆盖
operation kind。
