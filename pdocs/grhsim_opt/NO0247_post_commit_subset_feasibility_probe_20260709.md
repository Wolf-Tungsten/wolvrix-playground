# NO0247 Post-commit compute subset feasibility probe

日期：2026-07-09

## 背景

`NO0246` 的核心结论是：当前 best GrhSIM 在 `VtypeBuffer` 上剩余 `1.52x` gap，主要来自每个 vector 执行两遍 fullpass compute；其中 high eval 是 `commit + 全量 compute fullpass`，明显比 GSIM 的第二阶段 `subStep1()` 更重。

本文继续做一个轻量 feasibility probe：不改 emitter，直接解析 `NO0246` 的 generated C++，估算如果 high eval 改成“只跑 commit 后可能受影响的 compute supernode subset”，能省多少。

产物目录：

```text
tmp/no0246_best_vs_gsim_20260709/
```

## 静态解析方法

从 generated C++ 解析：

1. `eval_commit_batch_4()` 中 state write changed 后写入的 `supernode_active_curr_` bitmask，得到 commit 直接 reader set。
2. `eval_compute_batch_0..3()` 的 normal active-propagation 语句，建立 supernode -> supernode 的可能边。
3. 从 commit direct reader set 做静态 union closure。
4. 用 normal compute block 的源码行数粗略估计 subset 覆盖比例。

注意：这是静态 union，上界偏保守；它没有考虑运行时 changed 值，也没有切到 supernode 内部 value 级。

## 静态结果

`VtypeBuffer` 当前有 `38` 个 compute supernode（`0..37`），commit supernode 为 `38`。

commit direct reader set：`26/38`。

```text
[4, 5, 6, 7, 8, 9, 10, 11,
 12, 13, 14, 15, 16, 17, 18, 21,
 24, 25, 26, 27, 28, 29, 31, 32, 34, 36]
```

沿现有 active-propagation DAG 做 closure：`30/38`。

```text
[4, 5, 6, 7, 8, 9, 10, 11,
 12, 13, 14, 15, 16, 17, 18, 21, 22,
 24, 25, 26, 27, 28, 29, 30, 31,
 32, 33, 34, 35, 36]
```

未进入 closure 的 supernode：

```text
[0, 1, 2, 3, 19, 20, 23, 37]
```

源码块行数 proxy：

| subset | block source lines | ratio to all compute blocks |
| --- | ---: | ---: |
| commit direct set | `5698 / 8479` | `67.20%` |
| static closure | `6452 / 8479` | `76.09%` |

这说明 whole-supernode 粒度的 post-commit subset 最多只能去掉约 `24%` 的 high compute block 源码；考虑 high eval 只是总 runtime 的一部分，总体收益上限不会接近把 `1.52x` gap 完全抹平。

## 动态 commit mask 计数

为了判断静态 union 是否过保守，在 tmp generated C++ 中临时加计数器：在 posedge fast path 执行 `eval_commit_batch_4()` 后、清空 `supernode_active_curr_` 前，统计每个 active bit 的出现次数。该 patch 只作用于 tmp 产物，不修改仓库源码。

口径：`200000` vectors，`repeat=1`；bench 自带一次 warmup，因此样本约为 `2 * 200002` 次 posedge。

```text
[GRHSIM_COMMIT_MASK] samples=400005 bits=,
4:400003,5:399972,6:399997,7:399976,
8:399963,9:399971,10:400001,11:400003,
12:398767,13:399994,14:399985,15:399994,
16:399375,17:235860,18:235860,21:235860,
24:300524,25:399890,26:397237,27:399971,
28:399852,29:393455,31:399862,32:235860,
34:399891,36:399862
```

大多数 direct reader bit 几乎每次 posedge 都出现；少数 bit 仍有显著覆盖率：

| bit | count | pct |
| ---: | ---: | ---: |
| `17` | `235860` | `58.96%` |
| `18` | `235860` | `58.96%` |
| `21` | `235860` | `58.96%` |
| `24` | `300524` | `75.13%` |
| `32` | `235860` | `58.96%` |

因此静态 direct set 的 `26` 个 bit 不是由极少数异常 vector 造成；动态上也确实是一个很宽的 post-commit reader frontier。

## 结论

1. 只按 current supernode bit 做 post-commit subset，VtypeBuffer high phase 的候选闭包仍覆盖 `30/38` 个 compute supernode、约 `76%` 源码块；它有潜在收益，但不足以解释/回收 GSIM `subStep1()` 与 GrhSIM high fullpass 的全部差距。
2. 这也解释了为什么之前 active-propagation high path 并不快：commit 后直接 reader frontier 已经很宽，且多数 bit 每次都会出现；动态选择本身还要付 changed/active propagation 成本。
3. 若要接近 GSIM `subStep1()` 的规模，下一步不能只做 whole-supernode closure；需要 value/phase 级裁剪，区分：
   - pre-edge/input-only cone；
   - commit 后真正需要刷新 public outputs 的 cone；
   - 只为下一拍 commit 计算、但不需要在 high eval 立即重算的 cone。
4. 仍可做一个 generated C++ subset probe，但预期收益应按“high compute 减少约 20%~25%”估计，而不是按“high phase 接近 GSIM subStep1”估计。

## 下一步

优先做 GSIM `subStep1()` vs GrhSIM high fullpass 的 value/name 抽样对照：找出 GrhSIM 第二遍 fullpass 中被重复计算、但 GSIM 没有在 `subStep1()` 重算的主要 value 家族。确认后再决定是做：

- high-phase value subset；
- cycle-level fused API；
- 或者继续优化 fullpass batch 内 stack spill / slot-ref 代码形态。
