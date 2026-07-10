# NO0251 Event active-precompute + post-commit full-pass

日期：2026-07-10

## 背景

`NO0250` 把 event full-pass 从错误的 `commit -> compute` 修为语义正确的：

```text
pre-commit compute full-pass -> commit -> clear event -> post-commit compute full-pass
```

该修复解决了完整 XiangShan `SimTop` 在 `cycleCnt=8354` 附近 refill 全 0 的功能问题，但性能明显回退：

- SimTop 10k：约 `92408ms`；
- VtypeBuffer 200k：GrhSIM `460.960ms`。

本轮目标是在不回到错误 commit-first 的前提下，减少 event fast path 的 full graph work。

## 方案

正常 fixed-point round 的正确顺序要求 commit 之前必须已经执行本 eval 的 pre-commit compute，使 commit guard/data 读到 fresh `value_*_slots_`。但这一步不一定需要全图 full-pass；它可以复用 normal active compute，因为前面已经根据 input/event change seed 了 `supernode_active_curr_`。

因此本轮改为：

```text
pre-commit normal active compute
-> clear propagation bits
-> event commit
-> clear consumed event edge
-> if state_changed: post-commit compute full-pass
```

要点：

- pre-commit 阶段不能清空 `supernode_active_curr_`，否则 active compute 没有 seed，会导致 SimTop 不启动；
- commit 前仍清空 compute propagation bits，因为 event commit 是 edge-scanned，不依赖 compute active bits；
- post-commit 仍使用 full-pass，先保留 `NO0243/NO0245` 想要跳过 commit-activated active propagation 的收益。

## Hotpatch 实验

### SimTop：错误 hotpatch 反例

第一次 hotpatch 把 pre-commit full-pass 替换成 active compute，但仍保留了 event branch 入口处的：

```cpp
supernode_active_curr_.fill(0);
```

结果 10k 虽没有 refill fail，但功能不对：

- `instr = 0`
- `commit_pc = 0x0`
- `cycleCnt = 0`

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0251_simtop_grhsim_active_pre_post_full_hotpatch_func_10k_20260710.log
```

该反例确认：active precompute 必须保留 input/event seed 出来的 active flags。

### SimTop：保留 seed 后 10k 通过

修正 hotpatch：删除 event branch 入口处的初始 clear，仅在 pre-commit active compute 之后、event commit 之前清 propagation bits。

日志：

```text
build/logs/xs/no0251_simtop_active_pre_keep_seed_hotpatch_build_20260710.log
build/logs/xs/no0251_simtop_active_pre_keep_seed_hotpatch_relink_20260710.log
build/logs/xs/xs_wolf_grhsim_no0251_simtop_grhsim_active_pre_keep_seed_hotpatch_func_10k_20260710.log
```

结果：

- first instruction committed；
- 跑到 10k cycle limit，无 refill failure / ABORT；
- `host_cycles = 10000`
- `model_cycles = 10000`
- `cycleCnt = 9996`
- `instrCnt = 458`
- `Host time spent = 61366ms`

对比：

- `NO0250` 语义正确 full/full：`92408ms`；
- 本轮 active-pre/post-full：`61366ms`，约 `-33.6%`；
- 关闭 event fast path 隔离版：`19221ms`，说明 SimTop 仍需要继续缩小 post-commit full-pass 覆盖范围。

### VtypeBuffer hotpatch

对 `NO0250` 的 VtypeBuffer 生成物做同样 hotpatch，重新编译 model 并 relink bench。

日志：

```text
build/logs/xs/no0251_vtype_active_pre_post_full_hotpatch_build_20260710.log
build/logs/xs/no0251_vtype_active_pre_post_full_hotpatch_bench_20260710.log
```

结果：

- verify 200k: pass；
- GSIM: `217.112ms`；
- GrhSIM: `324.856ms`；
- checksum 一致：`0x7d62abe96844fe00`。

这基本追回 `NO0250` full/full 在 VtypeBuffer 上的退化（`460.960ms -> 324.856ms`）。

## 源码实现与验证

源码修改位置：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
```

event branch 生成逻辑调整为：

- 不在 branch 入口清空 `supernode_active_curr_`；
- pre-commit compute 使用普通 `eval_compute_batch_N()`；
- pre-commit compute 后清空 propagation bits；
- commit 后清 event edge；
- post-commit 仍使用 `eval_compute_batch_N_fullpass()`。

### build / install

- Wolvrix build: `build/logs/xs/no0251_wolvrix_build_active_pre_event_20260710.log`，status 0；
- Python editable install: `build/logs/xs/no0251_py_install_active_pre_event_20260710.log`，status 0。

### VtypeBuffer source gate

用源码重新 emit/build `XsReal075RobVtypebufferLarge`：

```text
build/no0251_active_pre_event_vtype_20260710
```

日志：

```text
build/logs/xs/no0251_vtype_active_pre_event_source_gate_20260710.log
```

结果：

- verify 200k: pass；
- GSIM: `203.340ms`；
- GrhSIM: `323.409ms`；
- checksum 一致：`0x7d62abe96844fe00`。

### emitter CTest

日志：

```text
build/logs/xs/no0251_ctest_emit_grhsim_active_pre_event_20260710.log
```

结果：

- `emit-grhsim-cpp`: passed；
- `emit-grhsim-cpp-memory-fill`: passed；
- `100% tests passed, 0 tests failed out of 2`。

## 结论

本轮不是回退到旧的错误 commit-first，而是在 `NO0250` 正确语义约束下减少 pre-commit work：

- 对 SimTop，10k 功能通过，并把 full/full 的 `~92s` 降到 `~61s`；
- 对 VtypeBuffer，恢复到 `~323ms`，接近此前 small-load fast path 水平；
- 但 SimTop 仍比关闭 event fast path 的 `~19s/10k` 慢，说明最大的剩余问题是 post-commit full graph full-pass。

下一步应继续把 post-commit full-pass 缩成 commit reader closure / value-level subset，或者在 SimTop 上根据动态触发 profile 决定是否启用 event fast path。
