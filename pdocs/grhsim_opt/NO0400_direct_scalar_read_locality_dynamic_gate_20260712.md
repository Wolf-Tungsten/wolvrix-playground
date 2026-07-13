# NO0400 Direct scalar read-locality dynamic gate

日期：2026-07-12

## 1. Exact direct join

按 [NO0395](./NO0395_direct_scalar_locality_runtime_profile_plan_20260712.md)，使用 NO0399 direct 50k fire 重跑
NO0394 同一 verifier。63,726 fire keys、59,013 static-row supernodes和 1,773,611 static rows 全部命中；rows、touches、
candidate 和 saved 静态计数再次精确复现 emitter summary。

## 2. Direct-weighted upper bound

```text
all weighted scalar touches          30,617,117,241
candidate weighted touches           14,557,222,262   47.546%
weighted saved upper bound           10,049,562,960   32.823% of all touches
saved / candidate touches                              69.035%
```

这是 direct 真实 fire 加权后的源级 load 上界，已经消除 baseline-fire proxy 的不确定性；仍不能绕过编译器 CSE/寄存器
分配门禁。最乐观地按一个 load 对应一条 instruction，它约为 NO0388 direct compute `139.750B` instructions 的
`7.19%`。

## 3. Proxy error closure

| Metric | Baseline-fire proxy | Direct fire | Delta |
| --- | ---: | ---: | ---: |
| All weighted touches | 30,619,211,863 | 30,617,117,241 | -2,094,622 (-0.00684%) |
| Candidate weighted touches | 14,557,258,243 | 14,557,222,262 | -35,981 (-0.00025%) |
| Weighted saved | 10,049,584,698 | 10,049,562,960 | -21,738 (-0.00022%) |
| Saved/all coverage | 32.821174% | 32.823348% | +0.002174 pp |

NO0399 的 665 个 fire 下降 supernodes 中，只有 102 个有 scalar rows、29 个有候选；受影响范围为 1,658 rows 和
69 candidate rows。16.49M fire 减量主要来自没有本诊断 scalar slot reads 的 direct-state source supernodes，因此
proxy 对本候选的误差很小。

## 4. Hot batches and thresholds

compute1 仍有 287,916,271 weighted scalar touches，但 candidate/saved 均为 0；该 instruction hotspot 不能由只读重复
slot cache 改善。compute62 与 proxy 完全相同：

```text
weighted touches       1,737,186,792
candidate touches      1,354,403,281
weighted saved           727,590,232
saved / all touches        41.883%
global saved share           7.240%
```

touch threshold `3/4/8` 分别保留 direct saved 的 `69.604%/57.184%/34.366%`。候选仍分散在 57/66 compute
batches，top single supernode 仅占 `0.186%`；不能通过只改一个函数或 value 完成。

## 5. Decision

direct exact coverage `32.823%` 超过 NO0395 的 `10%` 门槛，进入 production O3 disassembly gate。下一步从 NO0357
未插桩 direct binary/source 中选：

1. 全局 top row：supernode38314、batch42、48-touch bool slot；
2. compute62 中 top weighted candidates；
3. 一组 touch 2/3/4 和 touch>=8 候选。

逐 block 对齐 generated source slot index 与反汇编 memory operands，区分编译器已 CSE、部分重复 load 和真实多次
load。只有仍存在大规模重复 memory load 时才实现默认关闭的 typed local cache；否则本方向以“source-level 假热点”
收尾。

产物：

```text
build/logs/xs_perf/no0400/{direct_summary,threshold_summary,batch_summary,
                          supernode_summary,top_values,top_rows,fire_delta_overlap}.*
```
