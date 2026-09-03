# TNO0266: XiangShan RepCut closure-weight K32 static A/B

日期：2026-09-01

状态：`STATIC PARETO CANDIDATE; DEFAULT UNCHANGED; RUNTIME GATE NOT RUN`。

## 1. 结论

在同一当前 binary、同一 XiangShan JSON、`K=32`、epsilon `0.015`、deterministic-quality、
seed 0 下，TNO0265 的 `closure-aware` mode 将最大 realized static load 压到不可拆 giant ASC
的 exact full-closure 下界：

- exact closure max：`1,700,869 -> 1,115,421`，`-34.421%`；
- estimated node-weight max：`1,785,172 -> 1,158,927`，`-35.080%`；
- pre-rebuild ops max：`823,809 -> 534,601`，`-35.106%`；
- final graph ops max：`912,331 -> 608,762`，`-33.274%`。

这证明应先修 `hyper_partition_weight`/closure 目标，而不是先 sweep preset、seed 或 epsilon；旧
solver 已经很好地平衡了错误 proxy，新目标可以移除 giant owner 上的可避免附加载荷。

但 candidate 同时增加 total work 与通信：exact total `+3.012%`、final ops total `+4.480%`、
cross endpoint words total `+5.739%`、compute KM1 `+60.414%`、communication proxy KM1
`+56.822%`。因此它是明确的 max-load/total-work Pareto candidate，不足以直接替换默认。
下一步可以进入独立 runtime gate；本文没有 emit/build simulator，也没有 C=100/10000/30000
或 N=1/N=4 的功能、difftest、签名和性能结果。

## 2. 冻结协议与身份 gate

| 项目 | 冻结值 |
| --- | --- |
| host | `node030.bosccluster.com`，baseline/candidate 串行执行 |
| input | `build/xs/wolf/wolf_emit/xs_wolf.json` |
| input SHA-256 | `82a29e6e2f715c18ffd61ab0106ed5abb6d0fbb6843eea58d8782eb3d30994ba` |
| input size | `3,427,740,706 B` |
| graph / K | `SimTop / 32` |
| epsilon | `0.015` |
| backend | `mt-kahypar` |
| preset / seed | requested `quality`，effective `deterministic-quality` / `0` |
| backend threads | `0`，由 backend 使用 node 默认 |
| Wolvrix HEAD | `054c6a7c09b007a12eb36fdb49fcb659a1bfc590` |
| nested diff SHA-256 | `985b7cf0a727ad636df411006896a88e103ce4ecf6aeddfa628ac668e61fc3e9` |
| `_wolvrix.so` SHA-256 | `86eb9b354156c8bd6830d16a166b205cbd029bccf9a24237ecb2687869030f91` |
| `libwolvrix-lib.so` SHA-256 | `a97bb01351df3ed0a4b84a657435eb07c6cda9624ee202ce2b0258ae6aa65ac7` |
| runner SHA-256 | `a92293e10e07cbe1eaf81000ee4107dd785ef24b95cde9a883eb410d55ff5fb4` |
| summarizer SHA-256 | `64f64dfac407b58fae2ed64bb34d6f3b160fefab0ba3d053f2b93665e3433054` |

strict summarizer 的十项 gate 全过：两侧结果完整、K/input path/input SHA/除 mode 与 work-dir
外的 RepCut 参数相同、native extension SHA 相同、native library SHA 相同、source HEAD+diff
相同、runner SHA 相同，且两次 `/usr/bin/time` exit status 都为 0。

## 3. exact closure 事实

| 指标 | 数值 |
| --- | ---: |
| total piece weight | `13,682,460` |
| referenced unique weight | `12,450,769` |
| unreferenced piece weight | `1,231,690` |
| empty-piece artificial padding | `1` |
| exclusive unique weight | `7,895,270` |
| shared unique weight | `4,555,499` |
| nominal unique target `ceil(W/32)` | `389,087` |
| overweight full-closure ASC count | `1` |

最大 ASC 为 `aid=4`：

| 分量 | weight |
| --- | ---: |
| exclusive | `710,271` |
| shared incident | `405,150` |
| full closure | `1,115,421` |
| fair-share solver vertex | `743,702` |

`1,115,421` 是当前 exact closure 口径、whole-ASC 粒度下的 assignment max 下界；它不同于
TNO0264 的 `491,447 raw ops` 下界，两者单位和统计层次不同。candidate raw/effective assignment
中 `aid=4` owner 都是 `part_8`，该 part 的 ASC entry count 实测均为 `1`。这是本次结果事实，
不提升为算法对任意输入的 hard-isolation 保证。

## 4. baseline/candidate 静态对照

| 指标 | baseline | closure-aware | 变化 |
| --- | ---: | ---: | ---: |
| exact closure sum | `13,104,200` | `13,498,964` | `+3.012%` |
| exact closure max | `1,700,869` | `1,115,421` | `-34.421%` |
| exact closure population CV | `0.632184` | `0.309391` | 降低 |
| estimated weight sum | `13,735,606` | `14,130,370` | `+2.874%` |
| estimated weight max | `1,785,172` | `1,158,927` | `-35.080%` |
| pre-rebuild ops sum | `5,889,443` | `6,127,794` | `+4.047%` |
| pre-rebuild ops max | `823,809` | `534,601` | `-35.106%` |
| final graph ops sum | `6,227,498` | `6,506,503` | `+4.480%` |
| final graph ops max | `912,331` | `608,762` | `-33.274%` |
| cross endpoint words sum | `2,455,010` | `2,595,894` | `+5.739%` |
| cross endpoint words max | `390,861` | `357,295` | `-8.588%` |
| compute KM1 | `653,431` | `1,048,195` | `+60.414%` |
| communication proxy KM1 | `14,224,071` | `22,306,433` | `+56.822%` |

不同 mode 的 HGR vertex/edge weight 定义和尺度不同，不能把 solver hyper-weight sum、max 或
imbalance 当作跨 mode 性能指标；上表只用共同定义的 exact/rebuild/graph 指标比较。

baseline 最大 exact part 是 `part_3=1,700,869`；candidate 最大 part 是
`part_8=1,115,421`，第二大降到 `part_18=475,889`。candidate 的前两大 gap 说明 giant ASC
仍是唯一 dominant singleton，其他 part 的最大 closure 已明显收敛。

## 5. post-refine 行为

Mt-KaHyPar raw candidate 与最终 effective candidate：

| 指标 | raw | effective | 变化 |
| --- | ---: | ---: | ---: |
| accepted moves / rounds | `0 / 0` | `64 / 1` | 达到 move cap |
| exact sum | `13,491,800` | `13,498,964` | `+7,164 / +0.053%` |
| exact max | `1,115,421` | `1,115,421` | 不变 |
| second exact load | `491,316` | `475,889` | `-15,427 / -3.140%` |
| compute KM1 | `1,041,031` | `1,048,195` | `+7,164 / +0.688%` |
| communication proxy KM1 | `22,113,866` | `22,306,433` | `+192,567 / +0.871%` |

raw 前十个降序 exact loads：

```text
1115421, 491316, 465614, 458644, 446646,
444850, 429031, 425268, 410511, 405341
```

effective 前十个：

```text
1115421, 475889, 465614, 461502, 452900,
444850, 434718, 429031, 410511, 405341
```

完整 load-vector 字典序确实改善；total 和 communication 的增加都在相对 raw 的 1% 预算内。
搜索达到 64-move cap，因此不能声称已经局部或全局最优。

开发中还保留了一个 rejected sum-first intermediate：41 moves 将 exact total 降到
`13,460,529`，但第二/第三大 load 变为 `493,646/489,770`，exact imbalance 反而恶化。
该版本只作为诊断归档在 `build/repcut_closure_weight_ab_20260901/*sum-first-v2*`；最终实现和
本篇 headline 均使用完整降序 load-vector 版本。

## 6. 产物身份

| artifact | baseline SHA-256 | closure-aware SHA-256 |
| --- | --- | --- |
| result JSON | `4a72f88ec45cce123b24870e2875e3461fd3d35870768d9e6180020eea8a5567` | `21eec25971ade2e11a618290f2a0bd67749fde965a39790a2a13888e5b898e3f` |
| HGR | `fa37d58cdc754340ac23a2ce56771dbb1f845547f30a8f6d2e3a2c8b74f773fb` | `f48e4156022f2d94d848c39674f31f4c66a1637f6ea66968e2e52251abf5aae0` |
| raw `.part32` | `c2712f03b0ed58f23db1b49be1f3809d35b4abb290415abc88ed0a3044f308f3` | `aa4745967a588a4bc446308a698150bd5cb84fdc0a3c4ad0ddb34b59ad781de8` |
| effective `.part32` | 同 raw | `ffefbb1d1373cb30290e6725479d339b87e637f3db32132dcbe416fd2c52d589` |

汇总：

```text
build/repcut_closure_weight_ab_20260901/results/summary.json
  SHA-256 4b28707c12076f6c86ed731d03ec095a374df48feb6a081c21c47ee6c2060b10
build/repcut_closure_weight_ab_20260901/results/summary.csv
  SHA-256 df0ac9c9069b3c5d4090f4013f863cc5525f489d396f62eab1811a173f5f4ab6
```

当前 baseline HGR 与 TNO0246 的 2026-08-22 HGR SHA 不同；source review 确认本轮 patch 的
baseline HGR 公式/顺序保持，但不能据此声称跨历史 snapshot byte-identical。本篇只比较同一
当前 binary 内的 baseline/candidate。

## 7. transform wall 的证据边界

最终单次 `/usr/bin/time` wall 为 baseline `383.25 s`、candidate `515.17 s`；candidate 的
`read_json` 恰好为 `221.854 s`，baseline 仅 `43.529 s`，说明 node030 同时存在明显外部竞争。
RepCut pass wall 则为 `332.519/286.870 s`。这些单次 transform 数据只证明两次正常退出，
既不构成 transform 加速结论，更不是 emitted simulator runtime。

## 8. 决策与下一 gate

1. **优先修正 hyper/closure weight 的方向成立。** 它消除了旧 `part_3` 上的大量可避免负载，
   并将 max 压到当前 whole-ASC exact 下界。
2. **默认暂不改变。** total ops、compute replication 和 communication 都有明确回退；静态数据
   不能证明 N=1、N=4 或 K=N runtime 获益。
3. **candidate 可以进入独立 runtime gate。** 先 emit/build closure-aware package，跑 C=100
   功能/签名/difftest；再跑 C=10000 的 N=1 与 N=4。N=1 观察 serial total work，N=4 必须按
   连续 part-to-worker 映射同时比较 predicted worker load 与实际 barrier critical path。
4. C=30000、更多 N 和重复性能样本只在前述 gate 通过后执行并另建 TNO。
5. giant ASC 再拆分按用户要求留到下一步，不与本轮 weight A/B 混合。

因此当前结论是 `KEEP EXPERIMENTAL MODE / DO NOT PROMOTE DEFAULT / PROCEED TO SEPARATE
RUNTIME GATE`，不是 `SIMULATION SPEEDUP`。
