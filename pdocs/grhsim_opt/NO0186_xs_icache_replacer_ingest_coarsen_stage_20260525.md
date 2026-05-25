# NO0186 XsIcacheReplacerLarge Ingest / Coarsen 阶段总结

日期：2026-05-25

## 背景

本阶段从 `testcase/xs-components` 的小矩阵扩展开始，目标是构造能真实压迫
GrhSIM 的 XiangShan 局部模块案例，并用这些案例定位 `grhsim` 相对 `gsim`
的结构差异和 runtime 差距。

核心 case 是 `XsIcacheReplacerLarge`。它来自 XiangShan ICache replacement /
PLRU 类形态，包含 64 组 replacement state、多端口 touch/victim 访问，以及大量
array / index / slice / common condition 逻辑。该 case 能稳定暴露：

- SV 层数组语义保留和 ingest lowering 的差异；
- memory read / write port 表达是否足够接近 `gsim`；
- coarsen 后 DP 前后的 graph structure 是否对齐；
- GrhSIM 生成大 compute block 后 runtime 是否退化。

## xs-components 扩展

本阶段把原先单文件的 `XsComponents.scala` 拆成更可维护的结构：

```text
testcase/xs-components/src/main/scala/XsComponentsMain.scala
testcase/xs-components/src/main/scala/common/
testcase/xs-components/src/main/scala/cases/
testcase/xs-components/tb/xs_component_bench.hpp
testcase/xs-components/tb/xs_component_bench.cpp
```

新增的大型真实模块风格案例：

| case | kind | 目的 |
| --- | --- | --- |
| `XsIcacheReplacerLarge` | `icache-replacer` | 压迫 array state、indexed read/write、PLRU 条件逻辑 |
| `XsStoreQueueBanksLarge` | `store-queue-banks` | 压迫 store queue bank 类 indexed state 访问 |
| `XsLoadQueueReplayLarge` | `load-queue-replay` | 压迫 load queue replay 类条件和状态访问 |

bench harness 被抽到 `xs_component_bench.hpp`，`xs_component_bench.cpp` 只保留入口。
同时 reset / eval 口径调整为更稳定的单周期采样方式，避免 case 增大后因为初始化
差异误判 grhsim/gsim mismatch。

`cases.json` 也同步记录每个 case 对应的 XiangShan 来源文件，避免后续再引入
“不是从真实模块抽取”的盲点。

## ingest 改造

围绕 `XsIcacheReplacerLarge` 的 SV 形态，本阶段主要补了 ingest 能力，而不是在
后端用模式恢复已经丢失的语义。

已实现方向：

- 支持 procedural local variable lowering。
  - 处理 block 内局部变量声明、初始化、赋值和 slice update。
  - 未初始化 procedural local 默认按 0 生成，和 xs-components 的 deterministic
    初始化口径对齐。
- 改进 aggregate / packed array lowering。
  - 识别一维 aggregate / packed element memory-like 形态。
  - 支持 aggregate port slice 和 indexed element update。
- 增加 memory fill / memory port 相关 lowering 信息。
  - `LoweringPlan` 新增 `memoryFills`。
  - `MemoryReadPort` 增加 `replacement` 字段，为 read/commit 合并和 fallback
    表达提供入口。
- 修正 ingest aggregate lowering 的依赖粒度，避免把大数组更新错误建成过宽的
  状态改写链。

这轮中曾经尝试从 comb-loop-elim / dead-code-elim 侧绕过问题，但已按要求撤回；
当前保留的功能修改限定在 ingest 与 activity-schedule 主路径。

## activity-schedule / coarsen 改造

本阶段针对 GrhSIM graph structure 和 `gsim` 差距做了以下调整：

1. 删除 `tryMergeNodeBoundaryGain`

   之前 xs-components 实验证明 boundary-gain 对当前 case 收益不足，且复杂度不低。
   本阶段用 siblings merge 替代该环节。

2. 新增高效 `mergeSiblings`

   目标是对齐 `gsim` 在 sibling compute node 上的合并能力，避免公共条件、slice、
   not、index 这类中间值被过早提升成跨 cluster 边。

3. 让 source-like read 可以进入 compute node 记录

   `kMemoryReadPort` 被归入 source 类，但当它需要参与 compute 调度时，可以 clone
   到 compute node 中。这样 memory/state read 不必被当作普通纯表达式随意内联，
   但也不会因为 read source 边界阻断局部合并。

4. root-driven compute node builder

   compute node 不再简单按 topo 为所有 compute op 预建独立节点，而是从 commit root、
   output root、inout root 和无结果 compute op 反向确保 owner。这样公共表达式可以
   更接近真实语义消费者。

5. earliest semantic consumer ownership

   对 shared compute def，当前规则是让最早的非 common semantic consumer 拥有它；
   后续 consumer 通过 remaining fanout 连接。common-expr 节点不抢 shared def，
   避免形成 compute-node DAG cycle。

6. 增加 coarsen shape 诊断

   在 DP 前输出 cluster 形态统计，包括 cluster 数、source/sink/孤立节点、fork/join、
   op size 分布，以及 boundary def/use kind 分布。该诊断用于避免只看 supernode
   count 而误判。

明确保留的约束：

```text
不允许用 maxOpInComputeSupernode=128 限制 coarsen 粗度。
```

`maxOpInComputeSupernode` 可以作为后续 DP / emit / split 的参数，但不能成为
coarsen 阶段的粗度上限。本阶段中短暂实验过 local shared compute clone 和 op-size
coarsen cap；前者导致结构或性能回退，后者不符合当前策略，均未作为结论保留。

## 当前 XsIcacheReplacerLarge 结构与性能

最近一次对比命令：

```sh
make -C testcase/xs-components bench \
  CASE=XsIcacheReplacerLarge \
  BUILD_DIR=build-xsicache-current-compare \
  BENCH_VECTORS=20000 \
  BENCH_VERIFY=512 \
  BENCH_REPEAT=1
```

结果文件：

```text
testcase/xs-components/build-xsicache-current-compare/XsIcacheReplacerLarge/tb/XsIcacheReplacerLarge_bench.log
testcase/xs-components/build-xsicache-current-compare/XsIcacheReplacerLarge/gsim/gsim.log
testcase/xs-components/build-xsicache-current-compare/XsIcacheReplacerLarge/grhsim/model/activity_schedule_stats.json
```

结构对比：

| 阶段 | gsim | grhsim |
| --- | ---: | ---: |
| coarsen 前 | `2517` superNodes | `817` compute nodes |
| DP 前 / coarsen 后 | `26` superNodes | `15` clusters |
| DP 后 / partition 后 | `22` superNodes | `7` compute + `1` commit = `8` total |
| emit 最终 | `21` superNodes | `8` supernodes |

仿真结果：

| model | ms | vectors/s | checksum |
| --- | ---: | ---: | --- |
| `gsim` | `3.744` | `5.34M` | `0x7fbd54ca68a86341` |
| `grhsim` | `19.404` | `1.03M` | `0x7fbd54ca68a86341` |

GrhSIM 关键 shape 指标：

```text
source_clones_in_compute_nodes = 1077
compute_nodes = 817
common_expr_compute_nodes = 618
clusters_after = 15
compute_supernodes = 7
ops_per_supernode.max = 2783
ops_per_supernode.p90 = 1045
ops_per_supernode.median = 95.5
```

DP 前 cluster shape 诊断：

```text
clusters=15 isolated=1 sources=9 sinks=2 linear=0 forks=12 joins=5 max_pred=12 max_succ=4
op_size_min=1 op_size_mean=307 op_size_p50=4 op_size_p90=573 op_size_max=2783
boundary_def_kinds=kSliceStatic:709,kAnd:385,kSub:128,kAdd:124,kNot:67,kLogicNot:64,kLogicAnd:3,kMux:2,kXor:2
boundary_use_kinds=kMux:705,kAnd:384,kLogicOr:384,kAdd:4,kConcat:4,kXor:3
```

## 阶段结论

1. `XsIcacheReplacerLarge` 上，当前 GrhSIM 的 DP 前 supernode 数量已经不是比
   `gsim` 多，而是更少：

   ```text
   gsim DP 前 26
   grhsim DP 前 15
   ```

2. 结构数量问题已从“GrhSIM 合并不够”转成“GrhSIM 合并后生成代码形态过粗”。
   当前 GrhSIM DP 后只有 `8` 个 supernode，但 runtime 仍比 gsim 慢约 `5.18x`。

3. 后续不应回到 coarsen cap 方案。下一步应比较：

   - GrhSIM `sched_*.cpp` 大 compute block 的源码和机器码形态；
   - gsim 最终 supernode 的表达树组织方式；
   - 是否需要在 DP 后或 emit 层做 oversized compute block split，而不是限制
     coarsen 本身。

4. 当前功能正确性在 `XsIcacheReplacerLarge` bench 中通过，gsim/grhsim checksum
   一致。但 runtime 仍是负向结果，不能视为优化完成。

## 已执行验证

本阶段已执行过的本地验证：

```sh
cmake --build wolvrix/build --target transform-activity-schedule
ctest --test-dir wolvrix/build --output-on-failure -R activity-schedule
python3 -m pip install --no-build-isolation -e wolvrix
make -C testcase/xs-components bench CASE=XsIcacheReplacerLarge BUILD_DIR=build-xsicache-current-compare BENCH_VECTORS=20000 BENCH_VERIFY=512 BENCH_REPEAT=1
```

未在本阶段重新完成 full XiangShan CoreMark 50k runtime gate。当前文档只记录
xs-components / `XsIcacheReplacerLarge` 阶段结论。
