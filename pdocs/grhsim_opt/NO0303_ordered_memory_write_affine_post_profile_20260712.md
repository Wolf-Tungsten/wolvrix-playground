# NO0303 Ordered memory-write affine post profile

日期：2026-07-12

## 1. 目的与口径

承接 [NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md)，解释 affine emitter 已改善约 `0.8%` cycles 后，NO0300 为什么相对 NO0286 仍回退约 `3.85%`。比较对象为：

```text
old = build/xs_grhsim_no0286_commit_change_unlikely_20260711/grhsim/grhsim-compile/emu
new = build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim-compile/emu
```

两边均 fresh 采集 `cycles:u`、`25,000,000` period 与 8 KiB DWARF call graph，固定 CPU 138，负载为 CoreMark 两迭代镜像、NEMU difftest、`-C 50000`。两次功能端点完全一致，没有 lost samples。

## 2. Phase 分解

| Phase | NO0286 samples | NO0300 samples | Delta | Share of total increase |
| --- | ---: | ---: | ---: | ---: |
| compute | 8,039 | 8,351 | +312 | 65.96% |
| commit | 3,689 | 3,872 | +183 | 38.69% |
| eval | 22 | 18 | -4 | -0.85% |
| other | 183 | 165 | -18 | -3.81% |
| total | 11,933 | 12,406 | +473 | 100.00% |

profile event count 约为 `298.325B -> 310.150B` cycles，增幅 `3.96%`，与 NO0302 的原生 cycles `+3.85%` 一致。剩余回退约三分之二落在 compute，不能继续把它整体归因到 RAT commit path。

## 3. Affine 循环本体

NO0300 的精确 symbol samples 为：

| Function | Whole-function samples | RAT loops observed samples |
| --- | ---: | ---: |
| `eval_commit_batch_90()` | 72 | 6 |
| `eval_commit_batch_104()` | 83 | 0 |

batch90 的两个 511-writer loops 各自编译为约 13 条指令的紧凑循环；6 个 samples 落在 `dec/inc/guard branch`。batch104 的 511-writer loop 和编译器展开的 9-writer tail 均为 `0 observed`。因此 affine 已基本消除 NO0298 观察到的 1,542 个直接 guard 热点。

NO0298 曾用两个完整 commit functions 的 `248` samples 估算目标成本；NO0300 中对应完整 functions 降到 `155` samples，但汇编证明其中绝大多数来自同函数内其他 commit 代码。后续不能再把 whole-function samples 全部记到 RAT writes。NO0286 的 scalar RAT 所在 batch116 为 `43` samples，也只能作为含其他代码的函数级参考。

## 4. Compute batch 内容映射

ordered-write 改变了 graph、boundary 与 DAG，最终 compute supernodes 从 `67,449` 降到 `63,241`。为避免把同编号函数误当成同一逻辑，本轮按 generated comments 中稳定的 `_op_<id>` 对 old/new compute batches 做 overlap 映射：

```text
old compute batches: 66
old unique op ids: 2,073,444
cross-batch ambiguous op ids: 0
new compute batches: 65
```

NO0300 的前几个 cycles 热点及其最大旧版来源如下：

| New batch | Samples | Unique op ids | Largest old origins (share of new ops) |
| --- | ---: | ---: | --- |
| compute8 | 276 | 68,490 | old7 `19.09%`, old8 `8.23%` |
| compute36 | 259 | 18,117 | old33 `7.45%`, old31 `7.21%`, old32 `7.18%` |
| compute62 | 245 | 30,731 | old59 `14.60%`, old60 `11.24%`, old58 `7.02%` |
| compute21 | 227 | 22,323 | old19 `18.69%`, old20 `16.43%` |
| compute61 | 214 | 26,141 | old58 `18.80%`, old59 `11.89%`, old60 `10.23%` |

这不是简单的 batch 编号平移，而是广泛的跨 batch 混合。最直接的例子是 old compute8 以 `timer + logEndpoint` state reads 开头，new compute8 则以 frontend ibuffer state reads 开头；两者同名但逻辑内容不同。尤其 new compute36 的任一旧来源都不足 `8%`，说明 topology 改变已重排大量原本相隔的 supernodes。

## 5. 结论与下一步

本轮将 root cause 边界收紧为：

1. affine loop 已解决 ordered RAT direct guard 的主要直接成本，不应继续优化该循环作为主线；
2. 剩余 `+3.85%` 回退以 compute 为主，并伴随全局 compute batch 内容重排；
3. NO0302 中 instructions `-8.45%` 但 IPC `-11.84%`，与代码布局/前端供给受重排影响相符；当前证据不足以归因于更多工作量；
4. 下一步检查 activity-schedule 的 final topo tie-break、batch packing 和 emitter/link 顺序，寻找对局部 graph rewrite 不敏感的稳定 ordering key。先做只改变布局、不改变 supernode/DAG/activation 的 probe，再跑相同功能与 fixed-CPU gate。

## 6. 产物

```text
build/logs/xs_perf/no0303/old_no0286_cpu138_50k_cycles.data
build/logs/xs_perf/no0303/new_no0300_cpu138_50k_cycles.data
build/logs/xs_perf/no0303/old_no0286_exact_symbols_samples.report
build/logs/xs_perf/no0303/new_no0300_exact_symbols_samples.report
build/logs/xs_perf/no0303/new_no0300_commit90_cycles_annotate.report
build/logs/xs_perf/no0303/new_no0300_commit104_cycles_annotate.report
build/logs/xs_perf/no0303/old_no0286_commit116_cycles_annotate.report
build/logs/xs_perf/no0303/compute_batch_op_overlap.report
```
