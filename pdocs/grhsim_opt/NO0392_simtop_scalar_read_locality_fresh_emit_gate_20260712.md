# NO0392 SimTop scalar read-locality fresh emit gate

日期：2026-07-12

## 1. Configuration

承接 [NO0391](./NO0391_scalar_read_locality_python_emitter_rebuild_gate_20260712.md)，直接调用 Python driver，从
NO0300/NO0357 相同 pre-reg-to-mem checkpoint fresh 执行 reg-to-mem、activity-schedule 和 C++ emission。保持
NO0357 direct-state 配置不变，只额外开启：

```text
WOLVRIX_GRHSIM_MATERIALIZED_SCALAR_READ_LOCALITY_STATS=1
```

关键输入和输出：

```text
checkpoint:
  build/xs_grhsim_event_order_src_20260710/grhsim/wolvrix_xs_pre_reg_to_mem.json
read args:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit/wolvrix_read_args.txt
  SHA256 bd420039afef16f5ba578bf7a3d8e79f1c327b40f921e4d216f5058504de2b9c
output:
  build/xs_grhsim_no0392_scalar_read_locality_20260712/grhsim/grhsim_emit
```

108-op compute supernode、4096-op commit、64 batch target、4 路 emit、ordered/decoded write、`level-id` 和
`storage_ref_aliases=0` 均显式保持。所有命令先执行 `source env.sh`。

## 2. Fresh flow

flow exit 0：

```text
reg-to-mem           157.691 s
activity schedule    127.029 s
C++ emission          68.686 s
driver total         399.399 s
wall time            403.05 s
max RSS               29,132,280 KiB
```

本轮 emission 比 NO0357 多写 202 MB 诊断文件，时间不作仿真性能结论。

## 3. Identity gates

activity-schedule 关键计数仍为：

```text
graph ops                    7,204,108
compute/commit supernodes    63,241 / 485
total supernodes             63,726
DAG edges                    528,622
boundary values            1,000,463
boundary activation edges  1,983,923
```

NO0300、NO0357 和本轮 `activity_schedule_supernode_stats.json` SHA256 均为
`e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77`。direct emitter 再次精确命中：

```text
reads=75,830 canonical=40,108 aliases=35,722
removed_source_heads=37,672 consumer_heads=39,602
```

本轮和 NO0357 的 154 个 `grhsim_SimTop*.cpp/.hpp` 文件名集合相同且逐文件 SHA256 全部一致，总 bytes 都是
`1,357,263,998`。因此诊断没有改变 schedule、storage layout 或 generated model code，可以复用 NO0311 的同一
schedule-ID 50k fire 数据。

## 4. Static diagnostic

输出：

```text
grhsim_materialized_scalar_read_locality.tsv
rows:    1,773,611
bytes:   202,499,759
SHA256:  60e978313c5e3be46c9a9a430c76f9df781392e596b9ef0db7bcc1b4615a62e5
```

stderr 汇总：

| Metric | Count | Static share |
| --- | ---: | ---: |
| All scalar operand touches | 2,851,771 | 100% |
| Direct-state skipped touches | 75,830 | separate, not in scalar rows |
| Candidate rows | 377,895 | 21.307% of rows |
| Candidate touches | 1,386,865 | 48.632% of all touches |
| Saved loads per one fire of every row | 1,008,970 | 35.380% of all touches |

`saved/candidate_touches=72.752%` 只表示候选集合内部的重复度，不能替代动态全量覆盖率。

## 5. Next gate

下一步将所有 1,773,611 行与 NO0311 NO0300 CoreMark50k fire 按 `(supernode_id, compute)` 连接，使用所有 scalar
touches 作分母；分别汇总 threshold `2/3/4/8`、compute1、compute62、top supernodes/values，并检查所有 compute
supernode 是否都有 fire row。静态规模本身不作为实现 typed local cache 的依据。

日志：

```text
build/logs/xs/xs_wolf_grhsim_build_no0392_scalar_read_locality_emit_20260712.log
build/logs/xs/xs_wolf_grhsim_build_no0392_scalar_read_locality_emit_20260712.time
```
