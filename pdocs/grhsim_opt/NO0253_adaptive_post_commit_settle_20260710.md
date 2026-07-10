# NO0253 Adaptive post-commit settle for event fast path

日期：2026-07-10

## 背景

`NO0252` 已确认完整 `SimTop` 的 event fast path 几乎每个 posedge 都命中，并且每次 commit 都发生 `state_changed`。旧实现随后无条件执行一遍全图 post-commit compute fullpass：

```text
pre-commit active compute -> event commit -> clear event -> full-graph post-commit fullpass
```

`SimTop` 有 `71871` 个 compute supernode；10k 中 post-commit fullpass 执行 `10048` 次，总量约 `722159808` 次 compute-supernode execution，导致 event fast path 比完全关闭该路径更慢。

本轮目标是在不回退 event 顺序正确性的前提下，利用 commit 已产生的 reader active frontier，只收敛真正受状态变化影响的组合逻辑。

## 第一阶段：SimTop generated C++ active-settle probe

在以下 generated eval 上做临时 hotpatch：

```text
build/xs_grhsim_event_order_src_20260710/grhsim/grhsim_emit/grhsim_SimTop_eval.cpp
```

只修改 event branch 的 post-commit 部分：

1. 保留 commit 写入 `supernode_active_curr_` 的 reader bits；
2. 清除已经消费的 event edges；
3. 不再执行 `eval_compute_batch_*_fullpass()`；
4. 改为循环调用 normal `eval_compute_batch_*()`，直到 active flags 为空；
5. post-commit settle 不再扫描 commit batches，避免重复 commit 同一条 edge。

控制流变为：

```text
pre-commit active compute
-> clear compute propagation bits
-> event commit once
-> preserve commit reader frontier
-> clear event edges
-> normal compute fixed-point on reader closure only
-> refresh outputs
```

### 相邻 SimTop 10k A/B

测试前后机器均远未满载，但同一模型单核运行存在明显频率/调度波动，因此只采用相邻 A/B，不直接把本轮绝对时间与更早时段混用。

旧 post-commit fullpass 相邻基线：

```text
build/logs/xs/xs_wolf_grhsim_no0253_simtop_event_fullpass_adjacent_baseline_10k_20260710.log
```

结果：

- `instrCnt = 458`
- `cycleCnt = 9996`
- `commit_pc = 0x80001cdc`
- `Host time spent = 88144ms`

active-settle hotpatch：

```text
build/logs/xs/no0253_simtop_post_commit_active_settle_probe_build_20260710.log
build/logs/xs/no0253_simtop_post_commit_active_settle_probe_relink_20260710.log
build/logs/xs/xs_wolf_grhsim_no0253_simtop_post_commit_active_settle_probe_10k_20260710.log
```

结果：

- `instrCnt = 458`
- `cycleCnt = 9996`
- `commit_pc = 0x80001cdc`
- `Host time spent = 19222ms`

相邻 A/B：

```text
88144ms -> 19222ms
-78.19%
4.59x speedup
```

功能进度完全一致，并且时间回到 `NO0252` 完全关闭 event fast path 的 `19542ms` 附近。这说明旧 SimTop event 性能损失几乎全部来自 post-commit 全图 fullpass，而不是 pre-commit active compute 或 event candidate 判断。

### hotpatch 50k gate

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0253_simtop_post_commit_active_settle_probe_50k_20260710.log
```

结果：

- 无 difftest mismatch、refill failure 或 ABORT；
- `instrCnt = 73580`
- `cycleCnt = 49996`
- `Host time spent = 132335ms`

## 第二阶段：VtypeBuffer 反例

将 active-settle 一刀切工程化到 emitter 后，fresh 生成 `VtypeBuffer`：

```text
build/no0253_post_commit_active_settle_vtype_20260710
```

日志：

```text
build/logs/xs/no0253_vtype_post_commit_active_settle_source_gate_20260710.log
build/logs/xs/no0253_vtype_adjacent_old_fullpass_vs_active_settle_20260710.log
```

200k verify 通过，但相邻性能为：

| 版本 | GrhSIM |
| --- | ---: |
| NO0251 dense fullpass old binary run 1 | `323.414ms` |
| active-settle | `368.110ms` |
| NO0251 dense fullpass old binary run 2 | `323.467ms` |

active-settle 比旧 fullpass 慢约 `13.81%`。

这与 `NO0247` 的静态结论一致：

- VtypeBuffer commit direct reader set 为 `26/38 = 68.42%`；
- 静态 closure 为 `30/38`；
- reader frontier 很稠密时，normal compute 的 changed check 和 active propagation 成本高于一次不传播的 fullpass。

因此不能对所有模型、所有 event commit 都固定选择 active-settle。

## 最终实现：按动态 reader 密度自适应选择

修改文件：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
wolvrix/tests/emit/test_emit_grhsim_cpp.cpp
```

commit 后保留 reader frontier，并计数：

```cpp
const std::size_t post_commit_active_count =
    grhsim_count_active_supernodes(supernode_active_curr_);
```

当前 P0 选择规则：

```cpp
if (post_commit_active_count * 4 <= compute_supernode_count) {
    // sparse: normal active closure
} else {
    // dense: clear active bits and run one fullpass
}
```

即动态 reader 密度不超过 `25%` 时走 active closure，否则保留原 dense fullpass。

选择 `25%` 的依据不是拟合单个 workload 的细小差异，而是当前两个已验证 case 之间存在很大的自然间隔：

| case | direct reader density | 选择 |
| --- | ---: | --- |
| SimTop | `2959.2 / 71871 = 4.12%`（NO0252 动态平均） | sparse active settle |
| VtypeBuffer | `26 / 38 = 68.42%` | dense fullpass |

`25%` 在两者之间留出较大 margin。当前实现仍是默认关闭的 `posedge_fullpass_specialization` 内部策略，不改变未开启该开关的普通路径。

## 单测与构建

### emitter CTest

日志：

```text
build/logs/xs/no0253_wolvrix_build_hybrid_post_commit_20260710.log
build/logs/xs/no0253_ctest_emit_grhsim_hybrid_post_commit_20260710.log
build/logs/xs/no0253_py_install_hybrid_post_commit_20260710.log
```

结果：

- `emit-grhsim-cpp`: pass；
- `emit-grhsim-cpp-memory-fill`: pass；
- 2/2 passed。

测试新增了真正开启 `posedge_fullpass_specialization` 的 generated-code 断言，要求 event branch 同时包含 sparse active-settle 和 dense fullpass 两条路径，并继续运行寄存器 harness 验证 posedge 后可见输出。

### VtypeBuffer fresh hybrid gate

目录与日志：

```text
build/no0253_hybrid_post_commit_vtype_20260710
build/logs/xs/no0253_vtype_hybrid_post_commit_source_gate_20260710.log
```

结果：

- 200k verify: pass；
- GSIM: `208.796ms`；
- GrhSIM: `322.952ms`；
- checksum: `0x7d62abe96844fe00`。

相对相邻旧 fullpass 平均约 `323.44ms`，hybrid 为 `322.952ms`，等价且略快 `0.15%`，说明 VtypeBuffer 的既有性能已恢复，没有保留 active-settle 一刀切造成的 `13.8%` 回退。

## Fresh SimTop source gate

独立 fresh output：

```text
build/xs_grhsim_hybrid_post_commit_src_20260710
```

复用了 `NO0250/NO0251` 的 pre-reg-to-mem JSON checkpoint，但重新执行 reg-to-mem、activity-schedule、当前 emitter、模型编译和 emu 链接。生成代码明确包含：

```cpp
if (post_commit_active_count * 4u <= 71871u) {
    // Sparse frontier
} else {
    // Dense frontier
}
```

构建日志：

```text
build/logs/xs/no0253_simtop_hybrid_post_commit_src_build_20260710.log
build/logs/xs/xs_wolf_grhsim_build_no0253_simtop_hybrid_post_commit_src_20260710.log
```

### 10k

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0253_simtop_hybrid_post_commit_source_10k_20260710.log
```

结果：

- `instrCnt = 458`
- `cycleCnt = 9996`
- `commit_pc = 0x80001cdc`
- `Host time spent = 19421ms`

对比：

| SimTop 10k 版本 | Host time |
| --- | ---: |
| NO0252 active-pre + post-fullpass | `60834ms` |
| NO0253 fresh hybrid | `19421ms` |

按旧 NO0252 时段数据为 `-68.08% / 3.13x`；本轮相邻 hotpatch A/B 则为 `-78.19% / 4.59x`。由于机器频率有时段波动，最终应把相邻 A/B 作为最强性能证据，把跨时段数据作为量级参考。

### 50k

日志：

```text
build/logs/xs/xs_wolf_grhsim_no0253_simtop_hybrid_post_commit_source_50k_20260710.log
```

结果：

- 无 difftest mismatch、refill failure 或 ABORT；
- `instrCnt = 73580`
- `cycleCnt = 49996`
- `Host time spent = 138169ms`。

## 结论

1. SimTop event 性能下降的直接原因已被修复：post-commit 不再无条件扫描 `71871` 个 compute supernode；稀疏 commit reader frontier 改走 normal active closure。
2. 不能把 active closure 固定用于所有模型；VtypeBuffer 的宽 reader frontier 会使 changed/active 框架比 fullpass 更慢。
3. 当前 hybrid 以本次动态 reader density 做选择，同时取得：
   - SimTop 10k 从相邻 `88144ms` 降到 `19222ms`；
   - fresh SimTop 10k 为 `19421ms`，50k 功能通过；
   - VtypeBuffer 保持 `~323ms`，没有性能回退。
4. 这是比“按模型规模禁用 event fast path”更直接的机制修复：选择依据是本次 commit 的实际 reader frontier，而不是硬编码 SimTop 名称或掩盖 fast path。

## 后续方向

1. 给 sparse/dense 选择增加可选 runtime profile 计数，统计不同 workload 的分支命中率和 active density 分布；
2. 用 FTQ/Tage 复核 `25%` 阈值是否仍位于自然间隔内；
3. 后续可把简单 supernode-count 阈值升级为 batch/source-line/静态 cost 权重，但应先保留当前双边 correctness/performance gate；
4. 在最终面向 SimTop 的性能对比中继续采用相邻 GSIM/GrhSIM 或原始/优化版运行，并记录机器负载。
