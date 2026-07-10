# NO0252 SimTop event full-pass slowdown probe

日期：2026-07-10

## 背景

`NO0251` 将 event fast path 从 `pre-commit fullpass + post-commit fullpass` 改成：

```text
pre-commit normal active compute -> commit -> clear event -> post-commit fullpass
```

该版本在 `VtypeBuffer` 上基本恢复到此前 small-load fast path 的性能，但完整 `SimTop` 10k 仍从关闭 event fast path 的约 `19s` 下降到约 `61s`。本轮用 generated C++ hotpatch 做轻量动态计数，定位 SimTop 下降原因。

## 插桩方法

在 `build/xs_grhsim_event_order_src_20260710/grhsim/grhsim_emit/grhsim_SimTop_eval.cpp` 中临时插入 `no0252` 计数器：

- `evals`：总 eval 调用数；
- `event`：event fast path 命中数；
- `state_changed`：event commit 是否改变状态；
- `post_fullpass`：post-commit fullpass 执行次数；
- `normal_rounds`：普通 fixed-point while round 数；
- `pre_active_bits_sum`：event fast path precompute 入口 active bit 总数；
- `pre_out_active_bits_sum`：precompute 结束后 propagation bit 总数；
- `commit_reader_bits_sum`：event commit 激活 reader active bit 总数；
- `normal_round_active_bits_sum`：普通 round 入口 active bit 总数。

插桩 rebuild / relink 日志：

```text
build/logs/xs/no0252_simtop_event_probe_build_20260710.log
build/logs/xs/no0252_simtop_event_probe_relink_20260710.log
```

## 当前 active-pre event 版本 10k 结果

运行日志：

```text
build/logs/xs/xs_wolf_grhsim_no0252_simtop_grhsim_event_probe_10k_20260710.log
```

功能结果：

- 跑到 10k cycle limit；
- `instrCnt = 458`；
- `cycleCnt = 9996`；
- `Host time spent = 60834ms`。

计数器：

```text
[no0252] evals=20102 input_fullpass=0 event=10048 state_changed=10048 post_fullpass=10048 normal_rounds=20058 pre_active_bits_sum=20960128 pre_out_active_bits_sum=0 commit_reader_bits_sum=29734198 normal_round_active_bits_sum=21265187
```

关键派生量：

- event fast path 命中 `10048 / 20102`，约每个 posedge 都命中；
- `state_changed = post_fullpass = event = 10048`，即每次 event commit 都触发 post-commit fullpass；
- event precompute 入口 active bit 平均 `2086.0`；
- event commit 激活 reader active bit 平均 `2959.2`；
- 普通 round 入口 active bit 平均 `1060.2`。

## 强制关闭 event fast path 的对照

在同一插桩 generated file 中把：

```cpp
const bool event_fullpass_candidate = false && !initial_eval && ...;
```

重新 build / relink 后跑同样 10k。

日志：

```text
build/logs/xs/no0252_simtop_event_probe_disable_event_build_20260710.log
build/logs/xs/no0252_simtop_event_probe_disable_event_relink_20260710.log
build/logs/xs/xs_wolf_grhsim_no0252_simtop_grhsim_event_probe_disable_event_10k_20260710.log
```

结果：

- 跑到 10k cycle limit；
- `instrCnt = 458`；
- `cycleCnt = 9996`；
- `Host time spent = 19542ms`。

计数器：

```text
[no0252] evals=20102 input_fullpass=0 event=0 state_changed=0 post_fullpass=0 normal_rounds=40253 pre_active_bits_sum=0 pre_out_active_bits_sum=0 commit_reader_bits_sum=0 normal_round_active_bits_sum=71959513
```

对照说明：关闭 event fast path 后，普通 fixed-point round 数从 `20058` 增加到 `40253`，但总 active-bit work proxy 只有 `71959513`。

## 结论

SimTop 性能下降不是因为 event fast path 没命中，而是因为命中太稳定且每次都做全图 post-commit fullpass。

当前 `SimTop` 静态 compute supernodes：

```text
compute_supernodes = 71871
```

因此当前 active-pre event 版本的 post-commit fullpass 额外执行量约为：

```text
10048 * 71871 = 722159808 compute-supernode executions
```

而同一批 event commit 激活 reader 的平均 active bit 只有约 `2959.2`，全图 fullpass 相当于每次 post-commit 比初始 reader set 大：

```text
71871 / 2959.2 = 24.29x
```

用 active-bit 粗略 work proxy 看，event fast path 确实省掉了一部分普通 active work：

```text
71959513 - (21265187 + 20960128) = 29734198
```

但新增的 fullpass work：

```text
722159808
```

约为省掉 active work 的 `24.29x`。这解释了为什么 `NO0251` 虽然比 `NO0250` 快，但仍比关闭 event fast path 慢约 `3.11x`。

## 后续方向

1. 不能在完整 SimTop 上继续使用“全图 post-commit fullpass”作为默认高相位优化；
2. 下一步应把 post-commit fullpass 改成 commit-reader closure / value-level subset：至少要从 `71871` 个 compute supernode 缩到接近 commit reader 初始 active set或其实际闭包；
3. 如果短期无法实现 subset，应考虑对大模型按静态规模或动态 profile 禁用 event fast path，只保留 input fullpass unblock，避免 SimTop 性能被全图 post-commit fullpass 拖垮；
4. small-load 的 VtypeBuffer 成功不能直接外推到 SimTop，因为 SimTop 的 `state_changed` 几乎每个 posedge 都发生，且 full graph 规模大两个数量级。
