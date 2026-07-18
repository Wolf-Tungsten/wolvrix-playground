# TNO0147 Stage 32 current-profile replay and log audit

日期：2026-07-19

状态：已解释 legacy NO0311 profile 与 current-default 50k fire 的差异，并用 current profile
完成 fresh no-mutation emit replay。候选集、252 条 static row 和生成 schedule/header/eval
全部复现；Stage33 统一使用 current profile，不继续把 `profile_valid=true` 误写成全量 fire
identity。

## 1. Legacy 与 current fire 绝对差异

legacy 输入：

```text
build/logs/xs_perf/no0311/no0300_grhsim_supernode_fire.tsv
sha256=dce335d4a2c9e4fc27dfd213f13731efa57b62a79181ccc429ad0867699ae740
bytes=1157875
compute rows=63241
ignored commit rows=485
compute fire sum=805762327
```

current Stage32 50k：

```text
build/logs/xs_perf/stage32_same_batch_cohort_probe_20260719/fire_50000.tsv
sha256=308ae8ef5192feca7036eb9ccbc86a02bc2139c081e1759a46173dec88cc053a
bytes=1155117
compute rows=63241
ignored commit rows=468
compute fire sum=735024637
```

按 compute SN ID 全量对齐后，绝对 `1,553 / 63,241` 行不同；current 全部更低，signed/absolute
sum delta 都是 `-70,737,690 / 70,737,690`，最大单行下降 `100,053`（SN11510）。因此
`profile_valid=true` 只能表示 header/key/coverage 合法，不能表示 legacy profile 与当前运行的
每个 fire 值全等。

## 2. 为什么 positive witness 未受影响

旧 profile emit 的绝对 scan 值为 `signature_runs=252`、`selected=252`、
`rejectedProfile=0`：所有由 topology/signature 产生的 run 都已通过 profile gate，不存在因
legacy fire mismatch 被隐藏的额外 run。进一步把 1,553 个差异 SN 与 902 个 selected member
求交，绝对交集为 `0`。

50k current TSV 也直接证明 selected 902 行全部
`body_fire == current fire == legacy selected profile fire`。因此 TNO0146 的 252 个 positive
witness 有效；仍需 replay 来排除工具分析错误。

## 3. Current-profile fresh replay

replay 使用完全相同的 current-default checkpoint/生成参数，只把显式 profile path 换成上述
current `fire_50000.tsv`。结果：

```text
profile_compute_rows=63241
profile_ignored_commit_rows=468
compute_supernodes=63241
pure_boundary_only=14814
signature_runs=252
selected=252
members=902
ops=88334
control_bae=3619
projected_bae=1450
bae_saved=2169
control/projected entries=342/252
control/projected chunks=257/252
production_request=true
production_witness_valid=true
```

reject 绝对计数也逐项相同：`impure=306`、`input=2354`、`state=41152`、
`memory=2050`、`event=801`、`empty_source=12`、`source_order=1752`，其余为 0。

验证：

- 252 条 `cohort=` static row 与 legacy-profile emit 完整 `diff=0`，row stream SHA256
  `5ac64b74cb51d947b5c9c8da422d95ed55a007395be5aac804bbeae4503e3b3b`；
- 97 个 schedule CPP、header、eval CPP 全部 `cmp=0`；
- activity/emitter stats SHA256 仍为
  `6c41b8b25d83e05d402dbeb6164553bdd10903b8c8e67efae8cfd3cf6542257c` /
  `9dd1bdddd01606507b2e3425917f260ca3ac8c5b88c55fa21408bffb17080a8b`；
- replay exit0，wall `4:19.55`；raw log SHA256
  `5b9ce6dc7b362a54d2fccd56a1d4a09e469c39bec08d7e5cbb410e5d0c7b8175`，
  bytes=`122382`。

生成物已经静态 byte identity，因此没有重复进行 9 分钟 O3/link 或动态功能；TNO0146 的
binary 本身 no-mutation，且 50k current fire 已来自该 binary。

## 4. Raw log 插断审计

100/10k/50k 退出阶段同时写 stdout/stderr，shell `2>&1` 合流后各有一条 runtime summary
被其他终止文本插在字段中间：100 的 cohort224、10k 的 cohort243 marker、50k 的
cohort237。不能用 raw log 中“每条 summary 都能逐行解析”作为完整性断言。

权威计数来自每次先完整写出再关闭的 cohort TSV：三份均为 `903` 行、每行 `28` 列、
cohort ID `0..251`、member/ordinal/static membership 全部完整；TSV 与 fire TSV、emit static
rows 的交叉核对均通过。raw log 仍保留其原始 SHA/size，不做事后改写。

## 5. 后续规则

1. Stage33 profile 固定为 current `fire_50000.tsv`（SHA256
   `308ae8ef5192feca7036eb9ccbc86a02bc2139c081e1759a46173dec88cc053a`）。
2. profile loader 的 `valid` 只描述 schema/coverage；文档必须另记 fire identity/replay。
3. runtime 绝对计数以 TSV 为准，raw log 插断必须如实记录。
4. strict candidate 仍需未插桩 50k `Host time spent`；profile/BAE/guard tests 不能替代 walltime。
