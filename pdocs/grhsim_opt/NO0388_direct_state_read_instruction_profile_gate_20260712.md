# NO0388 Direct state-read instruction profile gate

日期：2026-07-12

## 1. 数据有效性

按 [NO0387](./NO0387_direct_state_read_instruction_profile_plan_20260712.md)，在 CPU188、NUMA1、`setarch -R` 下对
exact-entry direct 采集 CoreMark 50k `instructions:u` fixed-period profile。第一次 CPU188/380 quiet gate 为
`99.00%/98.67%`，在 perf 前拒绝；第二次 `100.00%/100.00%` 后启动。

```text
period:       25,000,000
call graph:   dwarf,8192
samples:      6,675
approx count: 166,875,000,000
stat count:   166,888,327,986
lost samples: 0
```

approx/stat 相差 `13,327,986` instructions，即 `0.533` 个 period，小于一个 period。direct/GSim sample ratio 为
`2.085286x`，direct/GSim stat ratio 为 `2.084264x`，相对误差 `0.0490%`，通过 `0.5%` 门禁。

运行以 exit 0 到达 guest cycles `50001`、`cycleCnt=49996`、`instrCnt=73580`、PC `0x80001312`，无 mismatch、
assertion、abort、fatal/error 或 `input_fullpass_blocked`。profile host time `82,757 ms` 只作完整性记录，不用于性能
比较。

## 2. 类别更新

沿用 [NO0349](./NO0349_fixed_aslr_latest_instruction_profile_codegen_compare_20260712.md) 的 leaf-symbol 分类：

| Class | NO0300 samples | Direct samples | Direct share | Delta |
| --- | ---: | ---: | ---: | ---: |
| Compute batches | 5,822 | 5,590 | 83.745% | -232 |
| Commit batches | 874 | 868 | 13.004% | -6 |
| `eval()` control | 24 | 16 | 0.240% | -8 |
| Generated helpers | 155 | 170 | 2.547% | +15 |
| Other/unresolved | 39 | 31 | 0.464% | -8 |
| Total | 6,914 | 6,675 | 100% | -239 |

compute 占总净减少的 `232/239 = 97.071%`。commit 近似不变，说明 direct state-read 的收益确实来自删除 compute
中的 read-slot compare/store/alias-OR，不是把相同工作转移到 commit；direct commit 只是因 compute 缩小而把相对占比
提高到 `13.00%`。

## 3. Compute8 因果闭环

最大变化高度集中：

```text
compute8 samples: 255 -> 44  (-211)
share of total sample reduction:   88.285%
share of compute sample reduction: 90.948%
```

这与 [NO0353](./NO0353_simtop_state_read_locality_gate_20260712.md) 的结构预测一致：batch8 覆盖全部 eligible
canonical visits 的主要部分，且该 batch 的 eligible coverage 为 `99.968%`。对应静态变化为：

| Compute8 metric | NO0300 | Direct | Delta |
| --- | ---: | ---: | ---: |
| Generated source lines | 350,724 | 216,890 | -38.159% |
| Generated source bytes | 32,064,015 | 18,030,051 | -43.769% |
| Function text bytes | 1,136,552 | 496,170 | -56.344% |
| Instruction samples | 255 | 44 | -82.745% |

direct annotate 的剩余 44 samples 中，约 3 个落在入口 activity guard，约 41 个落在真实 body；20 个采样点是整数
`div`，约占 45.4%。因此 compute8 的 state-read 扫描已基本清空，剩余主要是真实统计除法和其他逻辑，不应继续把
compute8 或全量 active scan 当作下一主线。

逐 batch 差值还包含 fixed-period skid 和不同 body layout 的量化噪声；除 compute8 的 211-sample 大信号外，不把
单个 `+/-10~25` sample 变化解释成精确收益或回退。

## 4. 更新后的 GSim excess 分解

按 25M period：

```text
GSim all subSteps         =  79.250B
Direct compute            = 139.750B
Direct commit             =  21.700B
Direct total              = 166.875B
```

以 direct/GSim profile 总差 `86.850B` 为分母：

| Component | Approx instructions | Share of direct excess |
| --- | ---: | ---: |
| Direct compute 超出全部 GSim subSteps | 60.500B | 69.660% |
| Direct commit | 21.700B | 24.986% |
| Control/helper/other residual | 4.650B | 5.354% |

compute 仍是第一目标，commit 是明确第二目标。精确 stat 口径下 direct 只关闭 baseline instruction excess 的
`6.455%`，仍为约 `2.084x` GSim instructions。

## 5. 新热点与代码形态

direct 的最大 compute hotspots 变为 `compute1=243`、`compute62=204` samples。两者没有单一 helper/call 热点：

- compute1 主要分散在 `mov/movzbl/or/cmp/setcc`；
- compute62 主要分散在 `lea/test/cmov/and`；
- direct generated source 中分别仍有 `107,121/73,469` 个 scalar value-slot 文本引用，以及
  `23,903/25,027` 个 state-storage-ref 文本引用；这些是静态引用次数，不是动态计数；
- 两个函数 text 仍为 `1,751,129/803,570` bytes，明显大于 GSim top subStep 的约 `0.18~0.57 MB` 范围。

GSim 的对应生成形态大量使用 subStep 内 typed locals、member fields 和 `$old` snapshots，不存在 GrhSIM 的通用
`value_*_slots_`。这把下一候选收敛到高频 supernode 内的 materialized scalar slot/ref 搬运，而不是 state-read、
表层 helper syntax 或单个 opcode。

不过不能直接重新开启全局 per-supernode storage-ref aliases：NO0151/NO0164 已观察到 source/text 膨胀和不稳定甚至
明显负收益；也不再调整 compute supernode size，NO0237 已证明 32/64/256 都慢于默认值。下一步先做只读诊断：统计
compute1/62 及全模型中“materialized scalar、在同一 supernode 只作 operand、重复读取、该 supernode 不写该 value”
的 typed-local cache 候选，并与动态 fire 连接。只有覆盖和理论 load reduction 足够大时才设计默认关闭的窄实现。

## 6. 产物

```text
build/logs/xs_perf/no0388/direct_exact_50k_instructions.{data,report,perf-script,folded,svg,png}
build/logs/xs_perf/no0388/direct_exact_50k_instructions_leaf_symbols.tsv
build/logs/xs_perf/no0388/category_summary.tsv
build/logs/xs_perf/no0388/batch_sample_deltas.tsv
build/logs/xs_perf/no0388/direct_compute{1,8,62}_instructions_annotate.report
```
