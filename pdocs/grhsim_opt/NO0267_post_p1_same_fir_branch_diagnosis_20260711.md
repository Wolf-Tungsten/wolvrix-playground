# NO0267 Post-P1 same-FIR branch diagnosis

日期：2026-07-11

## 目标与口径

承接 [NO0266](./NO0266_phr_true_merge_p1_simtop_50k_gate_20260711.md)，对 PHR true merge P1
做 fresh sampled profile，并与 [NO0255](./NO0255_simtop_same_fir_perf_profile_20260710.md) 的同一
FIR GSIM executable 对照。所有运行先执行 `source env.sh`，使用同一 CoreMark image/NEMU diff、
`-C 50000`，并绑定 CPU 8。

P1 GrhSIM 与 GSIM 分别得到 `50001` guest cycles；GrhSIM 为
`instrCnt=73580, cycleCnt=49996`，GSIM 为 `instrCnt=73584, cycleCnt=49998`，均无 difftest
mismatch 或 ABORT。

## 同窗口 perf stat

测试前 CPU 8 短窗口约 `98%~100% idle`，运行期间系统 load 约 `97~110/384`。四个事件均为
`100%` scheduled。

| metric | same-FIR GSIM | P1 GrhSIM | GrhSIM / GSIM |
| --- | ---: | ---: | ---: |
| Host time | `34660ms` | `102713ms` | `2.9634x` |
| cycles | `125693824838` | `372474492835` | `2.9633x` |
| instructions | `80427787481` | `228123993128` | `2.8364x` |
| branches | `4507536493` | `21610141861` | `4.7942x` |
| branch misses | `2155653094` | `7765590734` | `3.6024x` |

GSIM IPC 为 `0.6399`，GrhSIM 为 `0.6125`。剩余约 `2.96x` 的差距主要来自动态工作量，尤其是
约 `4.79x` 的 retired branches，而不是单纯由 IPC 差异解释。

## Cycles profile

GrhSIM 使用 `cycles:u, F=99, dwarf 8192`，得到 `10192` samples、lost `0`，近似事件数
`366462643892`。按 symbol 聚合：

| class | sampled cycles share |
| --- | ---: |
| compute batches | `57.16%` |
| commit batches | `39.84%` |
| eval control | `0.62%` |
| other | `2.41%` |

NO0258 旧模型中的 `compute_batch_54` 从 `2.30%` 降到 `1.01%`，按各自事件数折算约从
`8.89B` 降到 `3.70B` sampled cycles，下降约 `58%`。因此 PHR scalar one-hot compute 热点已按
预期退出，不能再围绕旧 `sched_54` 展开继续优化。

## Retired-branch profile

两边均使用 `branches:u, period=1500000, dwarf 8192`：

| simulator | samples | lost | approximate events |
| --- | ---: | ---: | ---: |
| P1 GrhSIM | `14268` | `0` | `21.402B` |
| same-FIR GSIM | `2956` | `0` | `4.434B` |

GrhSIM 分支按 symbol 聚合为 compute `33.30%`、commit `43.82%`、eval control `8.43%`、other
`14.54%`。最大单热点为：

| symbol | share | approximate branches |
| --- | ---: | ---: |
| `grhsim_replicate_words<4, 1>` | `11.37%` | `2.43B` |
| `eval_commit_batch_122()` | `10.39%` | `2.22B` |
| `GrhSIM_SimTop::eval()` | `8.43%` | `1.80B` |
| `eval_commit_batch_108()` | `4.42%` | `0.95B` |

以上四项合计约 `7.4B` branches，已经超过 GSIM 整个 50k 的 `4.434B`。GSIM 的头部则分散在
`subStep20/133/290/304/...`，最大单项仅 `2.77%`。

## Replicate 根因

SimTop 只有 `39` 个 `<DestN=4, SrcN=1>` call sites，分布在 `sched_32/39/40/54`；它们全部是：

```cpp
grhsim_replicate_words<4>(value, 1, 256, 256)
```

emitter 只把两字宽 replication 参数模板化，其他宽度把 `elemWidth/rep/totalWidth` 作为运行时
参数传给跨 TU 的共享 helper。该 helper 无法针对 `1 bit -> 256 bits` 常量传播，每次调用都执行
256 轮通用 insert/copy 循环。少量高频 call sites 因此累计出约 `2.43B` retired branches。

## 产物

```text
build/logs/xs_perf/no0267/gsim_same_fir_50k_cpu8_perf_stat.csv
build/logs/xs_perf/no0267/gsim_same_fir_50k_cpu8_run.log
build/logs/xs_perf/no0267/grhsim_phr_p1_50k_cpu8_perf_stat.csv
build/logs/xs_perf/no0267/grhsim_phr_p1_50k_cpu8_run.log
build/logs/xs_perf/no0267/grhsim_phr_p1_simtop_50k_cycles.data
build/logs/xs_perf/no0267/grhsim_phr_p1_simtop_50k_cycles_self.report
build/logs/xs_perf/no0267/grhsim_phr_p1_simtop_50k_branches.data
build/logs/xs_perf/no0267/grhsim_phr_p1_simtop_50k_branches_flat.report
build/logs/xs_perf/no0267/gsim_same_fir_simtop_50k_branches.data
build/logs/xs_perf/no0267/gsim_same_fir_simtop_50k_branches_flat.report
```

## 结论

PHR true merge 已恢复目标结构并消除旧 compute54 主热点，但 GrhSIM 相对 GSIM 仍执行约
`2.84x` instructions 与 `4.79x` branches。当前最明确的局部冗余是 1-bit wide replication 的
通用运行时循环；其编译期 broadcast 修复和 A/B 结果见
[NO0268](./NO0268_wide_bit_replicate_broadcast_fastpath_20260711.md)。
