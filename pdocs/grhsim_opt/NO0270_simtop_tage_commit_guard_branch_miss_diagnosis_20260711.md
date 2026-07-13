# NO0270 SimTop TAGE commit guard branch-miss diagnosis

日期：2026-07-11

## 目标

承接 [NO0269](./NO0269_packed_active_flag_scan_20260711.md) 的 retired-branch profile。该 profile
中 `eval_commit_batch_122()` 和 `eval_commit_batch_108()` 分别占 `12.75%` 和 `5.96%`，表面上是
最大的两个分支热点。本阶段补采 `branch-misses`，区分“分支数量多”与“真正预测失败”，避免直接把
所有 commit changed-check 改成 branchless 后重复 [NO0083](./NO0083_branchless_changed_activation_experiment_20260509.md)
中 instructions 上升、runtime 回退的问题。

## 50k branch-miss profile

所有命令先执行 `source env.sh`。profile 固定 CPU 140；采样期间机器 load 约 `104/384`，CPU 140
及其 SMT sibling CPU 332 约 `97%~98%` idle。该运行只用于热点归因，不把 Host time 当作新的
性能 A/B 结论。

```text
Guest cycles: 50001
instrCnt: 73580
cycleCnt: 49996
Host time: 100924ms
branch-misses:u samples: 15453
lost samples: 0
event count (approx.): 7726500000
mismatch / ABORT: 0 / 0
```

产物：

```text
build/logs/xs_perf/no0270/packed_active_scan_simtop_50k_branch_misses.data
build/logs/xs_perf/no0270/packed_active_scan_simtop_50k_branch_misses_run.log
build/logs/xs_perf/no0270/packed_active_scan_simtop_50k_branch_misses_symbols.report
```

按列出符号聚合，commit batches 占 `68.19%`，compute batches 占 `31.21%`，`eval()` 控制仅
`0.06%`。但 retired branches 与 branch misses 的头部并不相同：

| commit batch | retired branches share | branch misses share |
| --- | ---: | ---: |
| `122` | `12.75%` | `1.35%` |
| `108` | `5.96%` | `0.19%` |
| `101` | 非头部 | `2.84%` |
| `116` | 非头部 | `2.81%` |
| `119` | 非头部 | `2.80%` |
| `109` | 非头部 | `2.69%` |
| `112` | 非头部 | `2.62%` |
| `115` | 非头部 | `2.59%` |
| `114` | 非头部 | `2.43%` |

因此 batch122/108 中大量 scalar `state != next` 分支虽然数量大，但高度可预测；把它们作为全局
branchless 改写目标没有充分依据。

## 真正失效的分支

batch101/116 的 `perf annotate` 显示 branch-miss sample 几乎全部落在每个 register write 外层的
guard `je skip`，而不是内层 `state == next` 的 changed-check：

```asm
cmpb $0, guard_slot
je   skip_write       # branch-miss hotspot
mov  next_slot, reg
cmp  reg, state
je   skip_write       # 基本没有 branch-miss sample
```

对应报告：

```text
build/logs/xs_perf/no0270/commit101_branch_misses_annotate.report
build/logs/xs_perf/no0270/commit116_branch_misses_annotate.report
build/logs/xs_perf/no0270/commit122_branch_misses_annotate.report
build/logs/xs_perf/no0270/commit108_branch_misses_annotate.report
```

静态源码也呈现完全不同的结构：batch122 有 `42937` 个 register writes，但只有一个大粒度 guard；
batch101 有 `4108` 个 writes 和约 `4108` 个独立 write guards，batch109/112/114/115/116/119 则
各有 `4096` 个 writes 和 `4096` 个独立 guards。后六个文件均约 `53.3K` 行、`3.6 MB`，guard、
next slot 和 state offset 都按行连续展开。

这些热点对应 TAGE useful counter storage，例如每张表的
`usefulCtrs[4][2][512]`。GrhSIM 把每张表展开为 `4096` 个 scalar registers，commit 时形成
`4096` 个静态 one-hot guard branch sites。这里的主要问题不是某个 guard 难以预测，而是大量静态
分支站点给 BTB、I-cache 和前端带来的压力。

## 与 GSim 的结构差异

同一 FIR 的 GSim 保留了数组结构，在 generated C++ 中用紧凑三层循环提交：

```cpp
for (int i0 = 0; i0 < 4; ++i0)
    for (int i1 = 0; i1 < 2; ++i1)
        for (int i2 = 0; i2 < 512; ++i2)
            usefulCtrs.value[i0][i1][i2] = usefulCtrs.value$NEXT[i0][i1][i2];
```

GSim 参考文件为：

```text
build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/model/SimTop38.cpp
```

GrhSIM pre-reg-to-mem IR 中也保留了可恢复的信息：每个 512-row view 是一个 register-read concat，
并由两个 `kSliceArray` 动态读取；每行写回则是共享地址、共享数据、row equality guard 加 reset 的
compound write。当前 `reg-to-mem` intent matcher 要求 concat 只有一个 user，而 true-only storage
discovery 只识别“单个 register read 被共享”或“concat operand layout 重复”，因此遗漏了这种
“整个 packed concat 被多个动态 slice 共享”的数组证据。

## 结论与下一步

1. 不对 batch122/108 做宽泛 branchless changed-check 改写；它们不是 branch-miss 主因。
2. 下一目标是恢复 TAGE useful counters 的 memory/array storage，消除每张表 4096 个 scalar commit
   guards。
3. 最小实现方向是在 true-only storage discovery 中识别 shared packed concat，同时继续依赖现有
   strict write-family、read-closure、reset 和 domain checks；不能仅靠信号名合并。
4. fresh gate 必须确认对应 scalar `kRegisterWritePort` 从 generated commit batches 中消失，再进行
   SimTop 10k/50k 功能与 paired 性能测试。
