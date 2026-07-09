# NO0250 SimTop event full-pass order fix

日期：2026-07-10

## 背景

在推进 `input_fullpass` / `posedge_fullpass` specialization 时，完整 XiangShan `SimTop` 回归曾出现固定位置失败：约 `cycleCnt=8354` 时 refill checker 看到多段 `Core: 00...00`，随后 `ABORT at pc = 0x0`。上一轮 `NO0248` 先通过 commit event gate 避免了把 clock/reset edge 误走 compute-only input full-pass；但继续尝试解除生成代码中的裸 `input_fullpass_blocked = true` 后，发现 SimTop 仍会在开启 event full-pass 时失败。

本轮目标不是简单关闭 fast path，而是回答：为什么 SimTop 原本会需要阻断，以及 event/fullpass 快路径到底破坏了哪条 eval 语义。

## 关键实验

### 1. 旧 event full-pass / posedge-only 仍失败

先把 SimTop 生成物中 `event_fullpass_candidate` 限制成 clock posedge-only，并重新编译/relink：

- model rebuild: `build/logs/xs/no0250_simtop_posedge_only_hotpatch_build_20260710.log`
- relink: `build/logs/xs/no0250_simtop_posedge_only_hotpatch_relink_20260710.log`
- run: `build/logs/xs/xs_wolf_grhsim_no0250_simtop_grhsim_posedge_only_hotpatch_func_10k_20260710.log`

结果仍在同一位置失败：

- `cycleCnt = 8354`
- `instrCnt = 38`
- refill 多个 cache line 的 `Core` 数据为全 0
- `ABORT at pc = 0x0`

这排除了“只是 negedge 被错误纳入 fast path”的解释。

### 2. 关闭 event fast path，但保留 input-fullpass unblock 后通过

随后只在生成物里把 `event_fullpass_candidate` 强制为 false，保留新的 input-fullpass 条件阻断逻辑：

- model rebuild: `build/logs/xs/no0250_simtop_disable_event_hotpatch_build_20260710.log`
- relink: `build/logs/xs/no0250_simtop_disable_event_hotpatch_relink_20260710.log`
- run: `build/logs/xs/xs_wolf_grhsim_no0250_simtop_grhsim_disable_event_hotpatch_func_10k_20260710.log`

结果：

- 10k 跑到 cycle limit，无 refill failure；
- `cycleCnt = 9996`
- `instrCnt = 458`
- host time `19221ms`

这说明“纯数据输入变化允许 input full-pass”本身不是 SimTop refill failure 的直接根因；失败来自 event full-pass 快路径。

## 根因

正常 fixed-point eval 在事件边沿上的顺序是：

1. compute phase：在 event edge 可见时先计算组合逻辑；
2. commit phase：commit 读 freshly-computed `value_*_slots_` 并更新 state；
3. 清除 per-round event edge；
4. 如果 commit 改变 state，再进入下一轮 compute，此时 event edge 已被消费，不应再次可见。

旧 event full-pass 快路径的顺序是：

1. commit phase；
2. 如果 state 变化，再 compute full-pass；
3. 最后才清 event edge。

这有两个语义问题：

- commit 会先于本 eval 的 pre-commit compute 执行，因此可能读到上一轮残留的 `value_*_slots_`；
- post-commit compute 仍能看到已经消费过的 event edge。

SimTop refill 全 0 与这个顺序错误吻合：某些事件 commit 依赖本轮 compute 先产生的有效数据/guard，旧 fast path commit-first 会使用 stale value，从而破坏后续内存/refill 状态。

## 修复

源码修改在 `wolvrix/lib/emit/grhsim_cpp.cpp`：

1. `GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION` 只收集 `posedge` edge 条件，不再把 `negedge` 或任意 edge 混入候选；
2. event full-pass 分支改成 normal round 的等价 full-pass 顺序：
   - pre-commit compute full-pass；
   - 清掉 compute full-pass 遗留的 propagation bits；
   - event commit；
   - 记录 `state_changed`；
   - 清除 per-round event edge；
   - 若 state changed，再做 post-commit compute full-pass；
   - 最后刷新输出并发布 input baseline。

这不是通过关闭 event full-pass 掩盖问题，而是把 fast path 改成和正常 fixed-point round 同语义。

## 验证

### 生成代码静态检查

fresh source build 产物：

- `build/xs_grhsim_event_order_src_20260710/grhsim/grhsim_emit/grhsim_SimTop_eval.cpp`

检查结果：

- 顶层裸 `input_fullpass_blocked = true;` 数量：`0`
- 条件块内 `input_fullpass_blocked = true;` 数量：`3`
- `event_fullpass_candidate` 只包含 clock `posedge` 条件；
- event branch 中 `eval_compute_batch_0_fullpass` 出现在 `eval_commit_batch_*` 之前；
- `Event edges are per fixed-point round` 清 edge 逻辑出现在 post-commit `if (state_changed)` 之前。

### build / install

- Wolvrix C++ build: `build/logs/xs/no0250_wolvrix_build_event_order_20260710.log`，status 0
- Python editable install: `build/logs/xs/no0250_py_install_event_order_20260710.log`，status 0
- Fresh SimTop GrhSIM emit/build: `build/logs/xs/no0250_simtop_grhsim_event_order_src_build_20260710_make_xs_wolf_grhsim_emu.log`，status 0

Fresh build 使用独立目录：

```text
build/xs_grhsim_event_order_src_20260710
```

### SimTop 10k 功能回归

运行日志：

```text
build/logs/xs/xs_wolf_grhsim_no0250_simtop_grhsim_event_order_src_func_10k_20260710.log
```

结果：

- 跑到 `CYCLE_LIMIT`，没有 refill failure / ABORT；
- `host_cycles = 10000`
- `model_cycles = 10000`
- `cycleCnt = 9996`
- `instrCnt = 458`
- `Host time spent = 92408ms`

同一 10k 口径下，旧 commit-first fast path 会在 `cycleCnt=8354` refill fail；修复后可越过该点并跑到 10k cycle limit。

## 性能含义

这个修复优先恢复语义正确性，但也暴露出新的性能事实：

- 禁用 event fast path、只保留 input-fullpass unblock 的隔离版 10k host time 为 `19221ms`；
- 语义正确的 event full-pass 10k host time 为 `~92s`。

因此 full graph compute full-pass 不能作为 SimTop 的最终提速方案。后续优化应基于本轮正确顺序，继续缩小 event/post-commit compute 覆盖范围，或做 value/phase 级裁剪；不能回到旧的 commit-first fast path。

## 后续建议

1. 保留本轮 event full-pass order fix 作为 correctness baseline；
2. 对 SimTop 采集 event fast path 的实际触发次数、pre/post compute fullpass 耗时和涉及 supernode/value 子集；
3. 设计只覆盖 commit reader closure 的 post-commit subset，避免每个 posedge 做全图 compute full-pass；
4. 在任何性能优化前继续保留 SimTop 10k 以上 correctness gate，避免再次出现 refill 全 0 类错误。

## 增量更新：VtypeBuffer gate

为确认该修复不只在 SimTop 上成立，补跑 `XsReal075RobVtypebufferLarge`：

```text
make -C testcase/xs-components CASE=XsReal075RobVtypebufferLarge \
  BUILD_DIR=build/no0250_event_order_vtype_20260710 \
  GRHSIM_INPUT_FULLPASS_SPECIALIZATION=1 \
  GRHSIM_POSEDGE_FULLPASS_SPECIALIZATION=1 \
  BENCH_VECTORS=200000 BENCH_VERIFY=200000 BENCH_REPEAT=1 bench
```

日志：

```text
build/logs/xs/no0250_vtype_event_order_gate_20260710.log
```

结果：

- verify 200k: pass；
- GSIM: `201.514ms`；
- GrhSIM: `460.960ms`；
- checksum 一致：`0x7d62abe96844fe00`。

这说明 event full-pass order fix 在小负载上也保持功能正确，但性能相对 `NO0245/NO0246` 的旧 commit-first fast path 明显回退。旧 fast path 的速度不能作为有效收益，因为它在 SimTop 上语义不正确。后续 high/event phase 优化必须以本轮 `compute -> commit -> clear edge -> post-commit compute` 为正确性约束，转向更小的 compute subset 或 value-level 裁剪。

## 增量更新：emitter CTest

补跑 GrhSIM emitter 相关 CTest：

```text
ctest --test-dir wolvrix/build -R 'emit-grhsim-cpp|emit-grhsim-cpp-memory-fill' --output-on-failure
```

日志：

```text
build/logs/xs/no0250_ctest_emit_grhsim_event_order_20260710.log
```

结果：

- `emit-grhsim-cpp`: passed；
- `emit-grhsim-cpp-memory-fill`: passed；
- `100% tests passed, 0 tests failed out of 2`。
