# XiangShan RepCut 修改前后 Timing 对比分析（2026-03-24）

## 1. 分析对象

本分析对比以下两份 timing 数据：

- 修改前：[build/logs/xs-repcut/xs_verilator_repcut_20260324_194327.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_194327.timing.jsonl)
- 修改后：[build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.timing.jsonl)

辅助对比脚本与中间结果见：

- [tmp/xs_repcut_timing_compare.py](/workspace/wolvrix-playground/tmp/xs_repcut_timing_compare.py)
- [tmp/xs_repcut_timing_compare_20260324/compare.json](/workspace/wolvrix-playground/tmp/xs_repcut_timing_compare_20260324/compare.json)
- [tmp/xs_repcut_timing_compare_20260324/compare.md](/workspace/wolvrix-playground/tmp/xs_repcut_timing_compare_20260324/compare.md)

两次运行的 step 数相同，均为 `60102`，因此可以直接按 `avg_us` 比较。

## 2. 总体结论

修改后整体性能显著回退：

- 修改前平均 step：`3601.299 us`
- 修改后平均 step：`5887.360 us`
- 单步增加：`2286.061 us`
- 回退幅度：`63.479%`

这不是单一热点的小幅变差，而是多个 phase 同时变慢，其中最大头是：

- `debug_scatter`
- `part_eval`
- `writeback`

但从绝对增量看，最大的单项拖累是：

- `debug_scatter +1166.072 us/step`

也就是说，本次回退首先表现为主线程 debug 输入装载路径明显变慢。

## 3. Step 级 phase 对比

| phase | before avg_us | after avg_us | delta avg_us | delta pct |
| --- | ---: | ---: | ---: | ---: |
| `debug_scatter` | `788.300` | `1954.372` | `+1166.072` | `+147.922%` |
| `debug_eval` | `6.126` | `14.219` | `+8.093` | `+132.109%` |
| `debug_publish` | `0.493` | `1.257` | `+0.764` | `+154.970%` |
| `part_eval` | `1966.821` | `2616.635` | `+649.814` | `+33.039%` |
| `writeback` | `838.666` | `1299.327` | `+460.661` | `+54.928%` |

几个直接结论：

1. 五个 phase 全部回退，没有任何一个全局 phase 变快。
2. `debug_scatter` 是最大的绝对增量来源，占总回退的一半以上。
3. `part_eval` 和 `writeback` 也明显变慢，说明非 debug 路径也发生了实质性退化。
4. 修改后 `debug_scatter` 的时间占比从 `21.89%` 上升到 `33.20%`，已经成为更突出的瓶颈。

## 4. Debug 分区变化

`debug_part` 自身总耗时也同步恶化：

- total avg_us: `794.920 -> 1969.847`，增加 `1174.927 us`，回退 `147.804%`
- scatter avg_us: `788.300 -> 1954.372`
- eval avg_us: `6.126 -> 14.219`
- gather avg_us: `0.493 -> 1.257`

这里几乎可以明确：

- `debug_part` 的回退几乎完全由 `scatter` 驱动
- `debug_eval` 虽然比例上翻倍，但绝对值仍然很小，不是主因
- `debug_publish` 也不是主因

因此，本次修改后的主瓶颈首先不在 `debug_part->eval()`，而在它的输入装载路径。

## 5. Non-debug 分区分布变化

非 debug `part_*` 的分布不是简单整体平移，而是明显重排。

### 5.1 总体分布

- total mean：`389.987 -> 504.370`
- total median：`308.536 -> 459.815`
- total p95：`749.256 -> 945.387`
- total max：`1675.831 -> 2141.922`

### 5.2 子阶段分布

- scatter mean：`199.011 -> 250.300`
- eval mean：`77.852 -> 106.803`
- gather mean：`113.125 -> 147.267`

- scatter p95：`445.109 -> 532.884`
- eval p95：`196.704 -> 263.164`
- gather p95：`253.546 -> 287.068`

- gather max：`586.794 -> 1691.358`

这里最重要的观察是：

1. `scatter / eval / gather` 三项的均值都上升了。
2. `gather max` 从 `586.794 us` 暴涨到 `1691.358 us`，说明至少有个别分区的本地 gather 路径出现了极端异常。
3. `median` 也显著上升，说明不是只多了几个 outlier，而是大量分区都变慢了。

## 6. 回退不是均匀的，而是分区画像重排

128 个 non-debug 分区中：

- 回退分区：`85`
- 改善分区：`43`

也就是说，绝大多数分区都变慢了，但仍有相当数量分区变快，说明：

- 本次修改并非简单叠加一笔固定开销
- 更像是改变了分区级数据搬运或局部执行画像
- 使得部分分区显著变差，同时另一些分区反而受益

按“主导增量来源”统计：

- 回退分区里，`58` 个以 `scatter` 为主导
- `17` 个以 `gather` 为主导
- `10` 个以 `eval` 为主导

因此可以判断：

- 本次回退的主导因素仍然是边界数据搬运
- 其次才是局部 `eval()`

## 7. 最严重的回退分区

总时间回退最严重的几个分区如下：

| part | before total | after total | delta total | dominant |
| --- | ---: | ---: | ---: | --- |
| `part_23` | `298.713` | `2141.922` | `+1843.209` | `gather` |
| `part_115` | `391.379` | `1477.626` | `+1086.247` | `scatter` |
| `part_114` | `305.864` | `1321.899` | `+1016.035` | `scatter` |
| `part_16` | `165.458` | `1016.505` | `+851.047` | `scatter` |
| `part_50` | `179.121` | `1015.630` | `+836.509` | `scatter` |

其中最异常的是 `part_23`：

- scatter: `+95.721 us`
- eval: `+58.392 us`
- gather: `+1689.096 us`

也就是说，它的回退几乎完全来自本地 gather 暴涨。

而其他几个大回退分区则更多表现为：

- `scatter` 大幅上升

这说明修改后并没有形成单一的“统一回退模式”，而是至少出现了两类退化：

- 一类是本地 scatter 变重
- 一类是本地 gather 变重

## 8. 也有明显改善的分区

改善最明显的几个分区如下：

| part | before total | after total | delta total | dominant |
| --- | ---: | ---: | ---: | --- |
| `part_81` | `1667.977` | `272.357` | `-1395.620` | `scatter` |
| `part_80` | `1675.831` | `286.244` | `-1389.587` | `scatter` |
| `part_41` | `749.256` | `93.357` | `-655.899` | `scatter` |
| `part_26` | `846.613` | `219.762` | `-626.851` | `gather` |
| `part_55` | `1424.231` | `811.649` | `-612.582` | `scatter` |

这进一步强化了前面的判断：

- 修改并不是给所有 part 都统一加了一笔固定成本
- 而是让局部数据路径重分布了
- 有的 part 明显受益，有的 part 明显受损

## 9. 基于 timing 数据能支持的判断

仅基于这两份 timing 数据，可以比较有把握地说：

1. 本次修改后，整体性能显著回退，幅度约 `63.5%`。
2. 最大的单项回退来自 `debug_scatter`。
3. non-debug part 的平均 `scatter / eval / gather` 都上升了。
4. 回退的主导来源是分区级数据搬运，而不是纯 `eval()`。
5. 本次回退不是均匀的，分区级成本分布发生了明显重排。
6. 至少有一批分区出现了异常大的本地 gather 回退，另有大量分区出现了明显的本地 scatter 回退。

## 10. 基于 timing 数据还不能直接下的结论

仅凭这两份 timing，还不能直接证明以下更强结论：

- 是哪个具体代码改动导致了 `debug_scatter` 变慢
- 是端口数量变化、位宽变化，还是访问局部性变化导致某些 part 的 gather 暴涨
- 是调度顺序变化、数据布局变化，还是 cache 行为变化导致了这次分区画像重排

这些需要继续结合：

- 修改前后的生成代码 diff
- 具体 `part_*` 的 scatter/gather 代码规模
- 对应分区的静态 `cross_*` 特征

## 11. 最终结论

这次修改后的性能特征可以概括为：

- 全局明显回退
- 主因不是纯 `eval()`，而是数据搬运路径变重
- 最大全局热点是 `debug_scatter`
- non-debug 分区层面主要表现为 `scatter` 主导的广泛回退，以及少数 `gather` 极端爆炸
- 分区级热点发生了显著重排，而不是简单整体变慢

如果要继续定位原因，下一步最值得做的是：

1. 对比修改前后生成的 `debug_part` 输入 scatter 代码规模和访问模式。
2. 抽取 `part_23`、`part_114`、`part_115`、`part_16` 这类回退分区的 scatter/gather 代码量。
3. 将本次 timing 与 `partition_features.jsonl` 再做一次关联，验证回退是否集中在某类高 `cross_in` 或高 `cross_out` 分区上。

