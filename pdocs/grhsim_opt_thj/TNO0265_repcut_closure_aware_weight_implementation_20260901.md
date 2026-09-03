# TNO0265: RepCut closure-aware weight implementation

日期：2026-09-01

状态：`IMPLEMENTED; DEFAULT BASELINE; FOCUSED GATES PASS; RUNTIME NOT RUN`。

## 1. 结论

本轮按 [TNO0264](./TNO0264_xiangshan_repcut_part3_imbalance_root_cause_20260901.md)
的 P0/P1 路线实现了显式 `baseline/closure-aware` weight mode，先修正求解器看到的
`hyper_partition_weight` 与 shared closure 负载口径；没有拆分 ASC，没有改变 storage/state
归属语义，也没有修改 graph rebuild 规则。

默认仍是 `baseline`。`closure-aware` 是可复现的实验模式，包含：

1. 守恒的 shared-piece fair-share vertex weight；
2. compute replication 与 communication proxy 的 KM1 edge；
3. assignment 后的 exact closure-load 观测；
4. 有界 whole-ASC post-refine 和 raw/effective partition 双产物。

实现与 focused tests 已完成；K=32 静态 A/B 独立记录在
[TNO0266](./TNO0266_xiangshan_repcut_closure_weight_k32_static_ab_20260901.md)。
本篇不包含 Verilator emit/build、C=100 功能门或仿真 runtime 结果。

## 2. 接口与默认值

| 层次 | 接口 | 契约 |
| --- | --- | --- |
| C++ | `RepcutOptions::weightMode` | enum `kBaseline/kClosureAware`，默认 `kBaseline` |
| pass CLI | `-weight-mode=baseline|closure-aware` | 大小写敏感；非法 token fail-close |
| Python | `weight_mode="baseline"|"closure-aware"` | 非字符串与别名均抛 `ValueError` |
| XiangShan script | `XS_REPCUT_WEIGHT_MODE` | 默认 `baseline`；脚本再次严格校验 |
| Make | `XS_REPCUT_WEIGHT_MODE ?= baseline` | `run_xs_repcut`、partitioned smoke、Verilator build 三条路径均透传 |

baseline 的 HGR vertex/edge 公式、edge 顺序和 percentile 样本选择保持原实现；新增 exact
instrumentation 和 guard 会增加 transform 观测工作，因此这里只承诺 graph/HGR 算法分支保持，
不承诺与历史 binary 的 transform wall-time 完全相同。

## 3. closure weight 模型

对每个非空 piece `p`，记计算权重为 `w(p)`，引用该 piece 的 ASC 集合为 `A(p)`。

### 3.1 unique 与 full closure

```text
referenced_unique_weight = sum(w(p), A(p) != empty)
full_closure_weight(a)   = sum(w(p), a in A(p))
exact_load(part)         = sum(w(p), exists a in A(p): owner(a) == part)
```

`full_closure_weight` 会对 shared piece 在每个 incident ASC 中完整计数，用于识别单个 ASC
一旦落入某 part 后可能带来的完整 closure；`exact_load(part)` 则在同一 part 内对 piece 去重。
Phase E 另行归属的 storage/source 和 rebuild adapter 不在这个 exact 指标中，继续由
`estimated_node_weight_sum`、pre-rebuild ops 与 final graph ops 观测。

### 3.2 守恒 fair-share vertex

singleton piece 全额计入唯一 ASC。degree 为 `d` 的 shared piece 按 `q=w/d`、`r=w%d`
分摊，余数从 `piece_id % d` 开始确定性轮转。由此保证：

```text
sum(fair_share_weight(a)) == referenced_unique_weight
```

fair-share 为零的 ASC 在 HGR 中使用 vertex weight `1`，该 padding 单独统计。超过
Mt-KaHyPar `int32` 权重上限时不静默 clamp，而是使 candidate fail-close。

### 3.3 shared edge 与 exact identity

对 degree 大于 1 的非空 shared piece，candidate HGR edge weight 为：

```text
edge_weight(p) = piece_weight(p) + communication_proxy(p)
```

因此 KM1 同时惩罚跨 part 重复物化 compute closure 和原 communication proxy。assignment
完成后重新计算：

```text
sum(exact_load(part)) == referenced_unique_weight + compute_km1
```

该恒等式在 pass 内 fail-close 校验，不依赖日志后处理。

## 4. whole-ASC post-refine

`closure-aware` 在 raw Mt-KaHyPar assignment 后构建 piece-by-part occupancy，并按完整降序
per-part exact-load vector 做字典序优化；vector 相同后才比较 total closure load 和
communication proxy KM1。约束如下：

- 不移动 `full_closure_weight > ceil(referenced_unique/K)` 的 overweight ASC；
- 不向 overweight raw owner 增加正边际 closure load；
- source part 至少保留一个 ASC；
- total closure load 与 communication proxy KM1 均不得超过 raw assignment 的 `101%`；
- 最多 4 轮、64 个 accepted moves；每个 source 仅枚举 `sourceLoss` 最大的 128 个 ASC；
- 只在 `K <= 64` 且估算 dense working set 不超过 512 MiB 时启用；否则保留 raw assignment
  并记录 skip reason。

这是一种确定性的 bounded heuristic，不是全局最优证明。overweight 规则也是 reserved-owner
guard，不是 solver 级独占约束；raw owner 上已经存在的普通 ASC 可能保留，不能只根据
`overweight=true` 声称 owner 一定独占。

refine 结束后会从 Phase-B incidence 全量重算 exact loads/KM1，并与增量 occupancy 逐项比较。
solver 原始文件继续写入 `.hgr.partK`，实际 rebuild 使用的 assignment 写入
`.hgr.closure-aware.partK`。

## 5. 统计与审计

info JSON 新增：

- 顶层 `weight_mode`、`mt_weight_clamp_count`；
- `closure_weight_stats`：referenced/unreferenced、exclusive/shared unique、fair-share 守恒、
  nominal target、top full-closure ASC、exact max/sum/avg、compute/communication KM1；
- `partition_refine_stats`：enabled/applied/skip、round/move、raw/effective 路径，以及 before/after
  的 `partition_loads`、sum/max/KM1；
- 每个 partition 的 `exact_referenced_closure_weight`。

所有大权重与 exact 指标用 `uint64_t`；refiner delta 使用 checked arithmetic/`__int128`，
避免 signed delta underflow/overflow。hyperedge guard 直接利用 Phase-B 已排序去重的 incidence
做线性比较，不再为每条 edge 复制并排序节点向量。

## 6. 修改范围

Wolvrix：

```text
include/transform/repcut.hpp
lib/core/transform.cpp
lib/transform/repcut.cpp
app/pybind/wolvrix/__init__.py
docs/transform/repcut.md
tests/transform/test_repcut_pass.cpp
tests/transform/test_transform_pass_manager.cpp
tests/pybind/test_repcut_options.py
```

playground：

```text
Makefile
scripts/wolvrix_xs_repcut.py
```

实现没有改动 `.gitignore` 的既有用户修改，也没有清理 dirty `external/mt-kahypar`。

## 7. 验证

| gate | 结果 |
| --- | --- |
| `wolvrix-lib` / `transform-repcut` / `transform-pass-manager` build | PASS |
| focused CTest `^transform-(repcut($|-)|pass-manager$)` | `5/5 PASS` |
| Python RepCut option tests | `3/3 PASS` |
| 既有 activity-schedule option tests | `7/7 PASS` |
| full build | PASS |
| full CTest | `52/53 PASS`；唯一失败为历史 `transform-comb-lane-pack` 同签名 |
| Python `py_compile` | PASS |
| outer/nested `git diff --check` | PASS |

closure-aware integration test覆盖实际 pass、stats schema 和 effective partition 文件；大图 A/B
另外由 TNO0266 的 strict summarizer 校验 fair-share 守恒、exact identity、raw/effective HGR
assignment、per-part load 与二进制身份。full CTest 的唯一失败为：

```text
transform-comb-lane-pack
[comb-lane-pack-tests] Expected one packed kAnd for storage frontier rewrite
```

该失败连续复跑 3 次签名相同，且 TNO0250 等历史 gate 已记录同一既有失败；本轮没有修改
comb-lane-pack。尚未加入专门触发 512 MiB/K>64 skip 的小型单测，也尚未运行 emitted
simulator 功能测试。

## 8. 当前边界

- 默认没有改变，用户必须显式选择 `closure-aware`；
- 没有拆 giant ASC，也没有改变 memory/state boundary；
- exact closure weight 是静态 proxy，不是 Verilator 微秒；
- post-refine 搜索有 shortlist/move cap，达到 cap 不表示局部或全局最优；
- 本轮只完成 transform/static gate；runtime 结论必须另建 TNO。
