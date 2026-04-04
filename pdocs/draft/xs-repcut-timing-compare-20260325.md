# XiangShan RepCut Timing 对比分析（2026-03-25）

## 1. 分析对象

本文对比以下两份 timing 数据：

- 修改前：[build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260324_210610.timing.jsonl)
- 修改后：[build/logs/xs-repcut/xs_verilator_repcut_20260325_161210.timing.jsonl](/workspace/wolvrix-playground/build/logs/xs-repcut/xs_verilator_repcut_20260325_161210.timing.jsonl)

两次运行的 `steps` 相同，均为 `60102`，因此可以直接比较 `avg_us`。

## 2. 总体结论

这次修改后的整体性能是明显提升的，但提升不是“所有路径都变快”，而是：

- `debug_scatter` 大幅改善
- `part_eval` 明显改善
- `writeback` 反而明显变差

总体结果如下：

- 修改前平均 step：`5887.360 us`
- 修改后平均 step：`3584.439 us`
- 单步减少：`2302.921 us`
- 提升幅度：`39.116%`
- 等效速度比：`1.642x`

因此，2026-03-25 这个版本相对 2026-03-24 这个版本，结论是“整体更快”，但新的主瓶颈已经从 `debug_scatter` 转移到了 `writeback` 和少数 `eval` 热点分区。

## 3. Step 级 Phase 对比

| phase | before avg_us | after avg_us | delta avg_us | delta pct | before pct | after pct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `debug_scatter` | `1954.372` | `273.818` | `-1680.554` | `-85.989%` | `33.20%` | `7.64%` |
| `debug_eval` | `14.219` | `4.799` | `-9.420` | `-66.249%` | `0.24%` | `0.13%` |
| `debug_publish` | `1.257` | `0.269` | `-0.988` | `-78.600%` | `0.02%` | `0.01%` |
| `part_eval` | `2616.635` | `1550.087` | `-1066.548` | `-40.760%` | `44.44%` | `43.24%` |
| `writeback` | `1299.327` | `1754.649` | `+455.322` | `+35.043%` | `22.07%` | `48.95%` |

这组数据说明：

1. 这次总提升，主要由 `debug_scatter` 和 `part_eval` 两项驱动。
2. `writeback` 是唯一显著变差的全局 phase，而且已经上升为新的最大占比阶段。
3. 修改后 `writeback` 占总 step 时间接近一半，已经成为新的关键瓶颈。

## 4. 明显提升的部分

### 4.1 Debug 路径大幅恢复

`debug_part` 自身从 `1969.847 us` 降到 `278.886 us`，改善 `1690.961 us`，降幅 `85.842%`。

拆开看：

- `scatter_avg_us`: `1954.372 -> 273.818`，减少 `1680.554 us`
- `eval_avg_us`: `14.219 -> 4.799`，减少 `9.420 us`
- `gather_avg_us`: `1.257 -> 0.269`，减少 `0.988 us`

也就是说，这次全局收益首先来自 `debug_part` 输入装载路径的大幅缩短，而不是 `debug_part->eval()` 本身。

### 4.2 Non-debug 分区整体更轻

对 128 个 non-debug `part_*` 来看，分布层面也是整体改善的：

| 指标 | before mean | after mean | before median | after median | before p95 | after p95 | before max | after max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `total avg_us` | `504.370` | `184.597` | `459.815` | `164.429` | `945.387` | `405.415` | `2141.922` | `1208.464` |
| `scatter avg_us` | `250.300` | `67.511` | `196.731` | `29.362` | `532.884` | `190.111` | `1239.429` | `218.064` |
| `eval avg_us` | `106.803` | `84.901` | `82.886` | `39.071` | `263.164` | `283.932` | `426.713` | `1037.981` |
| `gather avg_us` | `147.267` | `32.184` | `129.065` | `9.218` | `287.068` | `129.549` | `1691.358` | `288.219` |

直接结论：

1. non-debug 分区的 `total / scatter / gather` 分布都显著改善。
2. `eval` 的均值和中位数也下降，但 `p95` 和 `max` 变坏，说明大多数 part 更快了，少数 part 反而更重。
3. 热点已经从“广泛 scatter/gather 过重”变成“少数 eval-heavy part 非常重”。

### 4.3 大多数分区都变快了

以 `part_timing.total_ms` 统计 129 个分区（含 `debug_part`）：

- 改善分区：`109`
- 回退分区：`20`

按子项统计：

- `scatter` 改善：`113`
- `eval` 改善：`90`
- `gather` 改善：`116`

所以这不是“少数极端样本拉低均值”的情况，而是绝大多数 part 确实更快。

### 4.4 改善最明显的分区

按 `avg_us` 降幅排序，前 10 个改善分区如下：

| part | before avg_us | after avg_us | delta avg_us | dominant |
| --- | ---: | ---: | ---: | --- |
| `part_23` | `2141.922` | `245.975` | `-1895.947` | `gather` |
| `debug_part` | `1969.847` | `278.886` | `-1690.961` | `scatter` |
| `part_115` | `1477.626` | `151.621` | `-1326.005` | `scatter` |
| `part_114` | `1321.899` | `196.466` | `-1125.433` | `scatter` |
| `part_50` | `1015.630` | `147.625` | `-868.005` | `scatter` |
| `part_51` | `1060.984` | `200.620` | `-860.364` | `scatter` |
| `part_67` | `867.963` | `60.152` | `-807.811` | `scatter` |
| `part_66` | `864.672` | `65.748` | `-798.924` | `scatter` |
| `part_3` | `844.179` | `50.266` | `-793.913` | `scatter` |
| `part_60` | `937.238` | `163.537` | `-773.701` | `scatter` |

这张表说明，旧版本中的大热点有一大批被压了下来，尤其是：

- `debug_part`
- `part_23`
- `part_115`
- `part_114`

其中 `part_23` 的改善主要来自 `gather`，而大多数其他热点的改善主要来自 `scatter`。

## 5. 明显下降的部分

### 5.1 全局 `writeback` 反而更慢

虽然大多数 part 的 `gather` 都变快了，但全局 `step_timing_phase.writeback` 从 `1299.327 us` 上升到 `1754.649 us`，增加 `455.322 us`，涨幅 `35.043%`。

这说明：

1. `part_timing.gather` 和全局 `writeback` 不是同一个口径。
2. 当前回退更像是主流程上的集中式 writeback / 汇总 / 同步路径变重了。
3. 不能把“全局 writeback 变慢”简单解读成“每个 part 的本地 gather 都变慢”。

换句话说，这次不是普遍性的 `gather` 回退，而是 critical path 上的写回阶段更重了。

### 5.2 新的热点分区是 `eval` 主导

旧版本前 10 热点里，主导成分大多是 `scatter` 或 `gather`：

| old hotspot | total avg_us | scatter avg_us | eval avg_us | gather avg_us |
| --- | ---: | ---: | ---: | ---: |
| `part_23` | `2141.922` | `312.692` | `137.871` | `1691.358` |
| `debug_part` | `1969.847` | `1954.372` | `14.219` | `1.257` |
| `part_115` | `1477.626` | `1239.429` | `53.168` | `185.029` |
| `part_114` | `1321.899` | `1003.817` | `216.994` | `101.088` |
| `part_51` | `1060.984` | `759.830` | `256.420` | `44.734` |

新版本前 10 热点里，则明显转成 `eval` 主导：

| new hotspot | total avg_us | scatter avg_us | eval avg_us | gather avg_us |
| --- | ---: | ---: | ---: | ---: |
| `part_9` | `1208.464` | `77.172` | `1037.981` | `93.312` |
| `part_8` | `1191.695` | `20.491` | `985.754` | `185.450` |
| `part_126` | `785.011` | `130.483` | `366.308` | `288.219` |
| `part_11` | `728.566` | `131.954` | `508.012` | `88.600` |
| `part_116` | `666.972` | `19.075` | `427.434` | `220.463` |

因此，热点画像发生了明显重排：

- 旧瓶颈：`debug_scatter` + 多个 scatter/gather-heavy part
- 新瓶颈：全局 `writeback` + 少数 eval-heavy part

### 5.3 回退最明显的分区

按 `avg_us` 增量排序，前 10 个回退分区如下：

| part | before avg_us | after avg_us | delta avg_us | dominant |
| --- | ---: | ---: | ---: | --- |
| `part_9` | `492.757` | `1208.464` | `+715.707` | `eval` |
| `part_126` | `120.731` | `785.011` | `+664.280` | `eval` |
| `part_116` | `84.536` | `666.972` | `+582.436` | `eval` |
| `part_8` | `733.833` | `1191.695` | `+457.862` | `eval` |
| `part_108` | `150.269` | `483.532` | `+333.263` | `gather` |
| `part_125` | `25.721` | `263.863` | `+238.142` | `eval` |
| `part_127` | `120.222` | `355.406` | `+235.184` | `gather` |
| `part_28` | `262.459` | `475.675` | `+213.216` | `eval` |
| `part_40` | `76.039` | `283.412` | `+207.373` | `scatter` |
| `part_117` | `280.362` | `378.190` | `+97.828` | `eval` |

这批回退分区里，最突出的特征是：

- `part_9` / `part_8` / `part_116` / `part_126` 主要是 `eval` 变重
- `part_108` / `part_127` 更偏 `gather` 变重
- `part_40` 则是少数典型 `scatter` 回退

## 6. 可以支持的判断

仅基于这两份 timing 数据，可以比较确定地说：

1. 2026-03-25 版本整体明显快于 2026-03-24 版本，提升约 `39.1%`。
2. 最大收益来自 `debug_scatter` 恢复和 non-debug `part_eval` 降低。
3. 大多数分区都变快了，尤其是旧版一些大热点分区已经被压下去。
4. 这次修改并没有让所有路径同时改善，`writeback` 反而变差，而且已经成为新的最大 phase。
5. 分区级热点画像已经从“scatter/gather-heavy”转成“少数 eval-heavy part + 全局 writeback”。

## 7. 仅凭这两份 Timing 还不能直接证明的事

仅从 timing 数据还不能直接证明：

- `writeback` 变慢的具体代码位置
- `part_9` / `part_8` / `part_116` / `part_126` 为什么会变成新的 `eval` 热点
- 这是分区质量变化、生成代码变化，还是 wrapper 调度/同步路径变化导致

这些问题还需要继续结合：

- 对应版本的生成 wrapper / emitted SV diff
- `part_9`、`part_8`、`part_116`、`part_126` 的静态分区特征
- `writeback` 路径上的具体 scatter/gather/commit 代码

## 8. 最终结论

这次对比的核心结论可以概括为：

- 整体性能明显提升
- 最大收益来自 `debug_scatter` 和 `part_eval`
- 最大新增问题是 `writeback`
- 旧的大量 scatter/gather 热点被压下去以后，新瓶颈变成少数 `eval` 极重的 part

如果下一步要继续优化，最值得优先看的不是再回头处理旧的 `debug_scatter`，而是：

1. `writeback` 为什么在全局 critical path 上变重。
2. `part_9`、`part_8`、`part_116`、`part_126` 为什么成为新的 `eval` 热点。
3. `part_108`、`part_127` 这类局部 `gather` 回退分区是否有共同的边界特征。
