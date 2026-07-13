# NO0394 Scalar read-locality baseline-fire proxy gate

日期：2026-07-12

## 1. Join validity

按 [NO0393](./NO0393_scalar_read_locality_baseline_fire_proxy_plan_20260712.md)，把 NO0392 的 1,773,611-row static
TSV 与 NO0311 NO0300 CoreMark50k fire 连接。verifier 硬门禁全部通过：

```text
fire rows                  63,726
compute / commit keys      63,241 / 485
static-row supernodes      59,013
missing fire keys               0
```

static rows/touches/candidate rows/candidate touches/saved 分别精确复现 emitter summary 的
`1,773,611 / 2,851,771 / 377,895 / 1,386,865 / 1,008,970`。分析脚本读取 202 MB TSV 用时 9.05 s，exit 0。

这里使用的是 baseline fire proxy，不是 direct runtime fire；以下所有 weighted 数值都保留这一限定。

## 2. Global proxy upper bound

```text
all weighted scalar touches          30,619,211,863
candidate weighted touches           14,557,258,243   47.543%
weighted saved upper bound           10,049,584,698   32.821% of all touches
saved / candidate touches                              69.035%
```

`10.050B` 是源级 slot-load 上界，不等于 host instructions。即使按一个 source load 对应一条 instruction 的最乐观
假设，它也只相当于 NO0388 direct compute `139.750B` instructions 的约 `7.19%`，或 direct/GSim compute excess
`60.500B` 的约 `16.61%`；编译器 CSE、寄存器分配和 direct fire 变化都可能进一步缩小实际收益。

## 3. Touch thresholds

| Minimum touches | Rows | Proxy saved | Share of all proxy saved |
| ---: | ---: | ---: | ---: |
| 2 | 377,895 | 10,049,584,698 | 100% |
| 3 | 145,424 | 6,994,870,997 | 69.604% |
| 4 | 91,621 | 5,746,790,543 | 57.184% |
| 8 | 28,677 | 3,453,641,717 | 34.366% |

如果后续实现，threshold 3/4 可能用较少 locals 保留过半理论 saved；但本篇不选择阈值。

## 4. Compute1 / compute62 split

NO0388 的两个最大 instruction hotspots 表现完全不同：

| Batch | Rows | Candidate rows | Weighted touches | Proxy saved | Saved/touches |
| --- | ---: | ---: | ---: | ---: | ---: |
| compute1 | 10,555 | 0 | 287,938,072 | 0 | 0% |
| compute62 | 33,506 | 15,426 | 1,737,186,792 | 727,590,232 | 41.883% |

因此 compute1 虽有大量 scalar slot 文本引用，但每个 slot 只读一次或在同 supernode 写回；typed read-only local copy
不能解释或改善该热点。compute62 是正候选，贡献全局 proxy saved 的 `7.240%`。

## 5. Concentration

候选较分散：

```text
candidate batches        57 / 66 compute batches
top 1 batch share         7.240%
top 10 batch share       36.728%
top 20 batch share       56.836%
top 40 batch share       85.878%
top 1 supernode share     0.186%
top 1 canonical value     3.192%
```

top canonical values 主要是 1-bit generic intermediates、reset、ROB enqueue/resolve valid，以及少量 u32/u64 value；
不是一个可单独手改的 helper 或状态。单行最高候选为 supernode38314 中 48-touch bool slot，baseline fire112,687，
proxy saved 5,296,289，仅占全局 `0.0527%`。

## 6. Decision

proxy `32.821%` 高于 NO0393 的 `10%` 继续门槛，因此不能直接否定；但 schedule ID 相同不足以证明 direct fire 相同。
下一步 fresh emit/build `direct-state + emit_runtime_profile` model，先验证 generated non-profile logic 与 NO0357 同源，
再做 CoreMark50k 功能运行取得 direct fire。随后用同一脚本替换 fire 输入重算，并对 direct-fire top candidates 检查
O3 disassembly 是否仍有重复 slot loads。

产物：

```text
build/logs/xs_perf/no0394/analyze_scalar_locality.py
build/logs/xs_perf/no0394/{proxy_summary,threshold_summary,batch_summary,
                          supernode_summary,top_values,top_rows}.*
```
