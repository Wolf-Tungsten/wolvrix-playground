# TNO0032 Stage 2 bae-budget plus Stage 1 strict structure gate

记录日期：2026-07-14

状态：Stage 2 `bae-budget` 与 Stage 1 `strict` 组合 SimTop structure scan PASS；两阶段均采用，最终相对 current-default 减少 75 个 SN、1.156% BAE 和 3.748% DAG，进入完整 build/50k。

## 1. 配置与执行顺序

组合继续复用 current-default fresh pre-reg checkpoint，两个阶段使用独立的 moved budget：

```text
Stage 2:
  kahn_level_pack_policy=bae-budget
  max_moves=4096
  max_moved_op_ppm=10000
  max_regression_ppm=10000

Stage 1:
  post_dp_refine_policy=strict
  max_rounds=1
  max_moves=4096
  max_moved_op_ppm=10000
  max_regression_ppm=10000
```

执行顺序严格为 Stage 2 rebuild view/value edges/plain DP 后，Stage 1 从采用后的 `63,166` segments 重新建立 exact owner/refcount；两阶段没有复用旧 cluster ID 或 baseline metric。

## 2. 两阶段 exact detail

Stage 2：

```text
elapsed_ms=3709
swaps=420
moved_clusters=840
moved_ops=56251
segments=63241 -> 63166
compute_bae=1721698 -> 1721423
dag_edges=528622 -> 529261
adopted=true
```

Stage 1：

```text
elapsed_ms=2849
candidates=49769
moves/swaps=4096/0
moved_ops=51528
compute_bae=1721423 -> 1698769
dag_edges=529261 -> 508811
```

Stage 1 full recount 与 final actual schedule 精确一致。组合 activity-schedule 为 `176,670 ms`，全脚本 `346,431 ms`；两项 bounded search 本体合计约 `6.6 s`，没有触及 `2x` kill criterion。

## 3. 最终结构对照

| Metric | current default | Stage 1 strict | Stage 2 only | combination |
| --- | ---: | ---: | ---: | ---: |
| total / compute / commit SN | `63726/63241/485` | `63726/63241/485` | `63651/63166/485` | `63651/63166/485` |
| total BAE | `1,983,923` | `1,961,679` | `1,983,648` | `1,960,994` |
| DAG edges | `528,622` | `508,629` | `529,261` | `508,811` |
| boundary values | `1,000,463` | `998,394` | `1,000,457` | `998,529` |

组合相对 current-default：

```text
SN              -75
total BAE        -22,929 (-1.1557%)
DAG edges        -19,811 (-3.7477%)
boundary values  -1,934
```

组合相对 Stage 1 strict：

```text
SN              -75
total BAE        -685
DAG edges        +182
boundary values  +135
```

组合相对 Stage 2 only：

```text
SN               0
total BAE        -22,654
DAG edges        -20,450
boundary values  -1,928
```

因此组合主要保留 Stage 1 的 BAE/DAG 收益，并叠加 Stage 2 的 75 个 SN 减少。相对 Stage 1 strict 的差异很小且 mixed，不能从结构推断 runtime 是否优于任一单项。

## 4. Gate 与下一步

扫描 exit `0`，峰值 RSS 约 `28.3 GiB`，没有残留进程。原始产物：

```text
build/logs/xs/xs_wolf_grhsim_build_activity_stage2_kahn_bae_postdp_strict_scan_20260714.log
build/xs_activity_stage2_kahn_bae_postdp_strict_20260714/grhsim/grhsim_emit/activity_schedule_supernode_stats.json
```

stats SHA256 为：

```text
fc0f89c421e52b53ee36056150255c163eacbca2ca7644736c277136ce1b4fc3
```

下一步完成 fresh C++ emit/O3 build、fixed-ASLR 100/10k/50k，并用 current-default quiet A/B/A 裁决。组合只有越过 `1%` cycles 门槛才考虑默认晋升；否则两个策略继续默认 `off`。
