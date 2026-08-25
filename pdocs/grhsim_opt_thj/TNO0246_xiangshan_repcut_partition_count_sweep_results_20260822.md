# XiangShan RepCut partition-count sweep results

日期：2026-08-22

## 1. 结论

按 [TNO0245](./TNO0245_xiangshan_repcut_partition_count_sweep_protocol_20260822.md)
冻结的同输入、同 binary、同目标和同参数协议，`k=2/4/8/16/32/64` 六档 RepCut
transform 全部成功，requested/observed partition 数一致，所有结构和证据门禁通过。

本轮最重要的静态结论是：

1. 核心多归属 op 复制率随 `k` 单调上升：`0.2771% -> 0.8432% -> 1.4116% ->
   2.9659% -> 5.7779% -> 9.0366%`。
2. 最终平均每分区 op 随 `k` 近似下降，但最大分区下降得远慢于均值，最终 op
   不平衡度从 `20.307%` 增长到 `657.243%`。
3. Mt-KaHyPar 的超图权重不平衡始终约束在 `0.6382%..1.5002%`，但这没有约束 raw
   op 数或通信端点的不平衡；`k=64` 的通信端点不平衡已达到 `789.631%`。
4. 加权 cut 从 `895,474` 增至 `12,238,947`，KM1 从 `895,474` 增至
   `23,455,797`，边界适配 op 从约 `124k` 增至 `351k`。更多分区带来明确的复制和
   通信代价。
5. `k=32` 新切分与 2026-08-19 冻结 `.part32` 的 SHA-256 均为
   `6857d47e3f36eaa3790bfdcdf2c128249fa3ef11866df19730419ec88c45e07e`，逐字节相同；
   本轮轻量 stats runner 没有改变 RepCut 切分。

这些结果是 transform-only 静态 sweep。没有构建或运行仿真，因此本文不把任何 `k`
宣布为 runtime 最优，也不从静态曲线推断仿真 speedup。

## 2. 执行与有效性门禁

六档分别启动独立 Python 进程，从 SHA-256 为
`82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba` 的同一
`SimTop` GRH 重新读取。固定 `epsilon=0.015`、requested preset `quality`、线程参数
`0`；每档日志均确认 effective preset 为 `deterministic-quality`、seed 为 `0`，本机
active Mt-KaHyPar threads 为 `384`。

全局交叉门禁结果为：

| 门禁 | 结果 |
| --- | --- |
| 六档 stats、stderr、time、HGR、`.partK` 均存在 | `PASS` |
| 六档原始 `SimTop` op 数 | 相同，均为 `5,826,569` |
| 六档核心唯一 `op_partitioned` | 相同，均为 `5,567,745` |
| 六档 HGR 内容 | 相同，SHA-256 `830ca5c22823222f3204c132fd2f40b87a4a3bfbb8d2332f7573c0edcdb371c1` |
| HGR 顶点 / hyperedge | 每档 `301,172 / 303,360` |
| `.partK` 行数与 partition id 覆盖 | 每档 `301,172` 行，完整覆盖 `0..k-1` |
| clone、feature、partition graph 记录数 | 每档均恰为 `k` |
| HGR + `.partK` 复算权重 vs pass stats | 六档逐分区完全一致 |
| preset / seed / partition completeness | 六档 `deterministic-quality / 0 / true` |
| `/usr/bin/time` 与 Python 退出状态 | 六档均为 `0` |
| bad_alloc、fatal、traceback、partition incomplete | 六档均未命中 |

本轮 runner 直接保存 RepCut 返回的结构化 info diagnostic，不调用 `store_json`、SV
emit 或 package emit。最终 part-graph op 数来自 pass 重建完成后的实际 graph 统计，而
不是从 pre-propagation feature 反推。结构化字段的生成位置见
[`repcut.cpp`](../../wolvrix/lib/transform/repcut.cpp)。

## 3. Op 规模与不平衡

`source avg` 是 constant/DPI propagation 后、clone 前每个 part 所归属的原图 op
membership 均值。最终分区 graph 还包含边界 slice/bundle 等适配 op。

| `k` | source avg | final min | final median | final mean | final max | source `I_op` | final `I_op` | weight `I` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 2,808,088.000 | 2,287,303 | 2,870,148.5 | 2,870,148.500 | 3,452,994 | 20.327% | 20.307% | 1.3318% |
| 4 | 1,412,524.500 | 923,870 | 1,156,463.5 | 1,442,748.250 | 2,534,196 | 75.201% | 75.651% | 0.6382% |
| 8 | 710,754.375 | 479,083 | 561,386.5 | 734,017.125 | 1,509,946 | 104.210% | 105.710% | 1.4951% |
| 16 | 361,133.250 | 209,906 | 274,043.5 | 375,938.625 | 1,108,950 | 187.954% | 194.982% | 1.4956% |
| 32 | 185,703.906 | 92,108 | 153,677.5 | 194,609.312 | 912,331 | 350.883% | 368.801% | 1.4811% |
| 64 | 95,869.562 | 30,650 | 75,538.5 | 101,353.719 | 767,494 | 635.495% | 657.243% | 1.5002% |

这里的 `I=max/mean-1` 使用精确均值；`k=64` 显示为 `1.5002%` 是因为该公式分母不是
Mt-KaHyPar 使用的 `ceil(total_weight/k)`。按 Mt-KaHyPar 原生分母复算为 `1.4998%`，
仍满足 `epsilon=1.5%`。

权重的 min/median/mean/max 原始分布为：

| `k` | min | median | mean | max |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 3,549,293 | 3,597,201.5 | 3,597,201.500 | 3,645,110 |
| 4 | 1,786,099 | 1,799,112.0 | 1,798,600.750 | 1,810,080 |
| 8 | 887,578 | 898,493.5 | 899,300.375 | 912,746 |
| 16 | 432,331 | 454,243.5 | 449,650.188 | 456,375 |
| 32 | 221,754 | 224,739.0 | 224,825.094 | 228,155 |
| 64 | 109,725 | 113,218.5 | 112,412.547 | 114,099 |

## 4. 复制率与最终 op 净变化

TNO0245 第 7 节已经保留首档后发现的口径勘误。本文的 headline 复制率是同阶段可严格
复算的核心多归属率：

```text
R_core = (sum(partition_static_features.op_count) - op_partitioned)
         / op_partitioned
```

`source net` 和 `final net` 都以原始 `SimTop` 的 `5,826,569` op 为分母；它们混合了
未进入 part graph 的原 op、propagation 和边界适配，因此只称“净变化率”，不冒充纯
复制率。

| `k` | core replicated memberships | `R_core` | source net | final net | boundary adapter op |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 15,430 | 0.2771% | -3.611% | -1.481% | 124,121 |
| 4 | 46,949 | 0.8432% | -3.029% | -0.954% | 120,895 |
| 8 | 78,594 | 1.4116% | -2.412% | +0.782% | 186,102 |
| 16 | 165,136 | 2.9659% | -0.831% | +3.234% | 236,886 |
| 32 | 321,698 | 5.7779% | +1.990% | +6.881% | 284,973 |
| 64 | 503,136 | 9.0366% | +5.305% | +11.329% | 350,986 |

这张表说明旧的 `(sum(final graph ops)-original)/original` 口径在 `k=2/4` 会得到负值，
不能称为 op 复制率；在 `k=32` 恰好为 `6.881%` 也不代表其中全部是复制。严格核心复制
率为 `5.7779%`，其余净增量主要还包括 propagation 与边界适配。

## 5. Cut、KM1 与跨分区通信

HGR 格式为 `11`。本文从每条超边权重和 `.partK` 重新计算：cut 为所有跨分区超边的
权重和，KM1 为 `sum(w_e * (lambda_e-1))`。`cross values` 是 phase-E 的跨分区 use
记录，`unique boundary` 是重建阶段去重后的边界 value；两者不能互换。

| `k` | avg weight | cut weight | KM1 | cross values | unique boundary | endpoint imbalance | max `lambda` |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 3,597,201.500 | 895,474 | 895,474 | 727,202 | 124,119 | 0.000% | 2 |
| 4 | 1,798,600.750 | 1,897,785 | 2,076,412 | 850,895 | 118,228 | 32.823% | 4 |
| 8 | 899,300.375 | 3,531,783 | 4,104,207 | 975,790 | 170,884 | 74.184% | 8 |
| 16 | 449,650.188 | 5,579,134 | 7,366,483 | 1,088,393 | 185,283 | 176.634% | 16 |
| 32 | 224,825.094 | 9,109,802 | 14,224,071 | 1,216,412 | 203,563 | 412.696% | 32 |
| 64 | 112,412.547 | 12,238,947 | 23,455,797 | 1,318,177 | 218,800 | 789.631% | 64 |

几点需要单独说明：

- cut edge 数本身并不单调：`k=2/4` 分别为 `8,206/7,198`，但加权 cut 和 KM1 已经
  上升，说明不能只数 edge 而忽略权重和 connectivity；
- `k=4` 的 unique boundary value 比 `k=2` 少，但 cross-use、cut weight 和 KM1 都更高，
  同样不能用单一去重 value 数判断通信代价；
- 每一档都有至少一条超边触及全部 `k` 个分区，故 `max lambda=k`；随着 `k` 增长，
  KM1 比简单 cut 增长更快；
- endpoint imbalance 从 `k=2` 的对称 `0%` 上升到 `k=64` 的 `789.631%`，计算权重
  平衡并没有阻止通信热点形成。

## 6. 生成时间与资源 raw snapshot

下表只用于解释本次 transform 成本。输入 JSON 读取受文件缓存与同机负载影响，故
external wall 不按 `k` 做算法结论；相对更局部的 partitioner 和 phase-E 时间仍完整
记录。

| `k` | partitioner | phase E | RepCut internal total | external pipeline | max RSS |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 19.780 s | 78.494 s | 207.167 s | 275.29 s | 29.95 GiB |
| 4 | 43.515 s | 82.231 s | 230.288 s | 366.21 s | 29.92 GiB |
| 8 | 45.516 s | 81.177 s | 231.834 s | 411.82 s | 29.92 GiB |
| 16 | 50.508 s | 82.206 s | 237.985 s | 353.24 s | 30.88 GiB |
| 32 | 79.846 s | 84.335 s | 274.149 s | 396.92 s | 34.68 GiB |
| 64 | 82.435 s | 101.871 s | 288.088 s | 404.04 s | 36.23 GiB |

在本次单样本 raw snapshot 中，`k=2 -> 64` 的 RepCut internal total 增长约 `39%`，峰值
RSS 增长约 `21%`。但没有 quiet-host gate 或重复样本，不能把相邻档的几秒差异当作稳定
性能结论。

## 7. 综合解释

### 7.1 权重平衡不等于 op 或通信平衡

六档的 partition weight 总和恒为 `7,194,403`，且最大权重满足 epsilon；但 op 的
单个操作代价不同，固定/传播/边界 op 也不都属于同一个 partitioner 权重口径。因此，
`k=64` 可以同时具有约 `1.5%` 的权重不平衡和 `657.2%` 的最终 op 不平衡。

### 7.2 更多分区存在明确的静态代价

随着 `k` 增长，平均 part 变小，但核心复制、最终净 op、cut、KM1、边界适配和通信热点
总体增长。最大 part 从 `3.453M` 只降至 `0.767M`，而分区数增加了 32 倍；最大 part
并没有按理想 `1/k` 缩小。

静态曲线在 `k=8/16` 左右出现从低复制向明显通信/不平衡代价过渡的形态，但这只是结构
上的 knee，不是 runtime 最优点。是否值得增加分区数仍取决于 partitioned runtime 的
实际调度、同步、cache、scatter/gather 和功能正确性；这些都不在本轮证据范围内。

## 8. 限制与不能得出的结论

- 每档只有 deterministic-quality、seed 0 的一次切分；没有跨 seed 方差。
- 没有 store/roundtrip 最终 GRH，没有 emit SV/package，也没有 Verilator 功能 gate。
- 生成时间没有 quiet-host admission、固定 CPU/NUMA 或重复采样，只是 raw snapshot。
- 本轮仅覆盖当前 `SimTop` 输入；不与历史 `SimTop.logic_part/k=128` 拼接趋势。
- `R_core` 是 op membership 数量口径，不是 RepCut 论文的权重复制 cost。
- 本文没有修改 Wolvrix 代码、默认 `partition_count`、epsilon、partitioner 或 runtime。

## 9. 持久证据

实验根目录：

```text
build/repcut_partition_sweep_20260822
```

关键汇总：

| 文件 | SHA-256 |
| --- | --- |
| `results/summary.json` | `45cb3ec39169a55871d6d1466af728b9bd23676c16e5ee4ca683242736ad65ce` |
| `results/summary.csv` | `41b787bfad922fee28ce6ae8bce8dc1655d6cf86ace9b727e832c021c205a48a` |
| `run_one.py` | `6bace0058042f9a61abff61ebed1e9c4bb469df0f451a8b9dc50d236d8e28d65` |
| `summarize.py` | `f5a2badd7d8369c38143cb6e46e15fe3194677c4762d26d798badcac2f710a13` |

每档的完整结构如下：

```text
logs/kK.stderr.log
logs/kK.time.log
results/kK.stats.json
runs/kK/work/SimTop_repcut_kK.hgr
runs/kK/work/SimTop_repcut_kK.hgr.partK
```

`summary.json` 内含每档 stats、stderr、time、HGR 和 partition 文件的独立 SHA-256，
以及所有逐档和全局 gate 布尔值。六档 `.partK` SHA 分别为：

| `k` | `.partK` SHA-256 |
| ---: | --- |
| 2 | `9d729f05e12eba2f1f1a5eaa7eb28dddbb2499ae90da62de116ce33ad9118b06` |
| 4 | `57b8358bccbffdc9c926c6d9219103be85e6160a087a198293904bdbd6b67938` |
| 8 | `0fb08251f928952a0b9b349744ffb384e6220aa0d7d04eb6fb8c0440c8f3ca0e` |
| 16 | `15b67b21eb7d480133557091490fd8bc62425b1ae62c11bcef352aab5a54dd8c` |
| 32 | `6857d47e3f36eaa3790bfdcdf2c128249fa3ef11866df19730419ec88c45e07e` |
| 64 | `021e6534beeba0effdeb2b42baf15828a846421c849520e2ae4fae2f25a3e30a` |

可复现命令、冻结 binary/input 身份、失败保留规则与指标原始定义见 TNO0245；本文没有
覆盖或删除此前的 RepCut 产物。
