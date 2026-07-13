# NO0312 NO0286 / NO0300 dynamic-work gate

日期：2026-07-12

## 1. 运行口径与功能端点

承接 [NO0310](./NO0310_no0286_no0300_runtime_profile_build_gate_20260712.md)，将 strict NO0286 与
ordered NO0300 两套 profile-enabled emu 依次固定到 CPU138、NUMA node 1，运行同一 CoreMark 两迭代
镜像、NEMU difftest 和 50k cycle limit。运行前整机 load average 为 `7.72/10.95/9.38`，机器有 384
个逻辑 CPU；CPU138 连续三秒平均空闲 `99%`，strict 结束后再次检查为连续两秒 `100%` 空闲。

两版功能端点完全一致：

| Metric | strict NO0286 | ordered NO0300 |
| --- | ---: | ---: |
| guest cycles | 50,001 | 50,001 |
| `cycleCnt` | 49,996 | 49,996 |
| `instrCnt` | 73,580 | 73,580 |
| terminal PC | `0x80001312` | `0x80001312` |
| fire TSV rows | 67,934 | 63,726 |

两次均无 assertion、abort 或 difftest mismatch，TSV 行数与各自 static 表精确一致。

profile 插桩版 host time 为 `82,159 ms -> 78,229 ms`（ordered `-4.78%`）。每次 supernode fire 都会
执行额外计数，且 ordered 的 fire 更少，因此该 timing 被插桩成本显著影响，只作运行完整性检查，不替代
[NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md) 的无插桩固定 CPU 结论。

## 2. Dynamic fire 与 work

使用 [NO0311](./NO0311_grhsim_runtime_profile_compare_tool_20260712.md) 严格连接 static/fire TSV：

| Metric | strict NO0286 | ordered NO0300 | Delta |
| --- | ---: | ---: | ---: |
| total fire | 855,899,893 | 813,853,977 | -42,045,916 (-4.912%) |
| compute fire | 847,808,243 | 805,762,327 | -42,045,916 (-4.960%) |
| commit fire | 8,091,650 | 8,091,650 | 0 |
| `work_comp` | 47,587,268,356 | 44,532,821,278 | -3,054,447,078 (-6.419%) |
| `work_src` | 13,945,995,639 | 13,867,797,019 | -78,198,620 (-0.561%) |
| `work_sink` | 10,502,094,870 | 10,574,667,370 | +72,572,500 (+0.691%) |
| `work_const` | 15,459,706,258 | 14,755,065,828 | -704,640,430 (-4.558%) |
| `work_total` | 87,495,065,123 | 83,730,351,495 | -3,764,713,628 (-4.303%) |
| `a_succ_work` | 20,193,598,869 | 18,714,440,805 | -1,479,158,064 (-7.325%) |

phase 分解：

| Phase | Metric | strict NO0286 | ordered NO0300 | Delta |
| --- | --- | ---: | ---: | ---: |
| compute | work total | 76,992,970,253 | 73,155,684,125 | -4.984% |
| compute | activation work | 9,691,503,999 | 8,139,773,435 | -16.011% |
| commit | work total | 10,502,094,870 | 10,574,667,370 | +0.691% |
| commit | fire | 8,091,650 | 8,091,650 | 0% |

ordered lowering 确实减少了约 42.0M 次 compute supernode fire、3.84B compute work 和 1.55B compute
activation work。新增 commit sink work 只有 72.6M，且 commit fire 完全不变，无法解释整体回退。

top-by-fire 的高频 compute 链在两版中保持相同 `f=200098` 和相同静态权重；top-by-work 也仍由
`n_sink=42937/18439/5130` 等既有 commit supernodes 主导。没有出现一个新的动态 fire 热点吞掉静态收益。

## 3. 与无插桩 PMU / cycles profile 合并

NO0302 的无插桩 fixed-CPU 结果为 cycles `+3.850%`、instructions `-8.451%`、IPC `-11.845%`。
将它与本轮 work 比率合并：

| Normalized metric | NO0300 vs NO0286 |
| --- | ---: |
| host cycles / `work_total` | +8.519% |
| host cycles / fire | +9.215% |
| host instructions / `work_total` | -4.335% |
| host branches / `work_total` | +4.561% |
| host branch misses / `work_total` | +2.373% |

[NO0303](./NO0303_ordered_memory_write_affine_post_profile_20260712.md) 的同口径 fixed-period cycles
samples 再按本轮 phase work 归一化：

| Phase | Cycles samples delta | Work delta | Samples / work delta |
| --- | ---: | ---: | ---: |
| compute | +3.881% (`8039 -> 8351`) | -4.984% | +9.330% |
| commit | +4.961% (`3689 -> 3872`) | +0.691% | +4.240% |

因此 NO0300 不是用更多 instructions 完成更多工作；它用更少 instructions 和更少 counted work，却因每单位
work 的停顿成本上升而执行更慢。compute 同时满足“work 明显下降、cycles samples 上升”，是剩余回退的
第一主因；commit 单位成本也回退，但幅度较小。

## 4. 结论与下一步

本轮拒绝以下解释：

- ordered graph 触发更多 compute supernodes；
- boundary activation 数量抵消结构收益；
- 三组 RAT affine loop 的额外动态执行次数主导回退。

当前 root-cause 边界收紧为：ordered graph 的全局 code layout/packing 变化使 compute 单位 work 的 host
执行效率下降约 `9.3%`。这与 NO0303 的广泛 batch 混排以及 NO0302 的 IPC 大降一致，也与更早的
GSim/GrhSIM 对照中“单位动态工作成本，而非总工作量，主导 host gap”的结论一致。

下一步停止继续压 activation 数量或盲试 topo tie-break，改为对 NO0286/NO0300 无插桩 binary 做同一固定
CPU 的 frontend/backend/cache/TLB stall PMU 配对，并将差异映射到 NO0303 已知的 compute/commit phase。
目标是区分 instruction-fetch/layout、data-cache/state footprint 和 dependency/backend stall，再决定是改 batch
packing、函数/section 布局，还是缩短具体 generated hot path。

## 5. 产物

```text
build/logs/xs/xs_wolf_grhsim_no0311_no0286_rtprof50k_20260712.log
build/logs/xs/xs_wolf_grhsim_no0311_no0300_rtprof50k_20260712.log
build/logs/xs_perf/no0311/no0286_grhsim_supernode_fire.tsv
build/logs/xs_perf/no0311/no0300_grhsim_supernode_fire.tsv
build/logs/xs_perf/no0311/no0286_vs_no0300_dynamic_work.report
build/logs/xs_perf/no0311/no0286_vs_no0300_dynamic_work.json
```

