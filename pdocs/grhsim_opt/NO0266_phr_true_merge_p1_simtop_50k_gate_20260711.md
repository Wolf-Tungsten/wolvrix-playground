# NO0266 PHR true-merge P1 SimTop 50k gate

日期：2026-07-11

## 对比口径

P1 前基线使用 [NO0258](./NO0258_scalar_state_read_change_predicate_reuse_20260710.md) 的 fresh
SimTop executable：PHR 仍为 532 个 scalar registers，调度参数与当前 P1 相同。NO0263 的 P0
matcher 在该 SimTop 上尚未命中，因此此基线与当前版本之间的主要生成模型差异就是 NO0264
的 PHR true merge，以及 NO0265 的 row-aware activation。

所有运行先执行 `source env.sh`，使用相同 coremark image/NEMU diff、`-C 50000`，并通过
`taskset -c 8` 绑定 CPU 8。测试前 CPU 8 短窗口平均 `97.33% idle`，运行期间系统 load 约
`79~104/384`；由于共享机器仍有明显 cache/频率窗口差异，采用 old/new/old，并以硬件工作量
为主结论。

## 功能 gate

三次运行完全一致：

```text
Guest cycles = 50001
instrCnt = 73580
cycleCnt = 49996
IPC = 1.471718
difftest mismatch = 0
ABORT = 0
```

因此当前 P1 没有通过缩短有效仿真 cycle 或改变 guest 执行来获得性能数字。

## Old/new/old 结果

四个 perf events 均为 `100%` scheduled：

| run | Host time | cycles | instructions | branches | branch misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| scalar PHR old 1 | `128990ms` | `467591371117` | `231820880775` | `19770555455` | `7884307385` |
| P1 row-aware | `102602ms` | `372017886726` | `228056649139` | `21596133407` | `7761362054` |
| scalar PHR old 2 | `129280ms` | `468654130461` | `231814493030` | `19769388915` | `7887917941` |

以两次 old 均值为 baseline：

| metric | old mean | P1 | delta |
| --- | ---: | ---: | ---: |
| Host time | `129135ms` | `102602ms` | `-20.5467%` |
| cycles | `468122750789` | `372017886726` | `-20.5298%` |
| instructions | `231817686903` | `228056649139` | `-1.6224%` |
| branches | `19769972185` | `21596133407` | `+9.2370%` |
| branch misses | `7886112663` | `7761362054` | `-1.5819%` |

日志：

```text
build/logs/xs/no0266_pre_p1_scalar_phr_50k_cpu8_run.log
build/logs/xs/no0266_pre_p1_scalar_phr_50k_cpu8_perf_stat.csv
build/logs/xs/no0266_p1_phr_row_activation_50k_cpu8_run.log
build/logs/xs/no0266_p1_phr_row_activation_50k_cpu8_perf_stat.csv
build/logs/xs/no0266_pre_p1_scalar_phr_50k_cpu8_repeat_run.log
build/logs/xs/no0266_pre_p1_scalar_phr_50k_cpu8_repeat_perf_stat.csv
```

## 解释

确定性较强的收益是 instructions `-1.62%` 与 branch misses `-1.58%`。P1 executable text 从
`172571947` 缩到 `106839279` bytes，即 `-38.09%`；当前共享缓存压力窗口中，这一 footprint
变化把 cycles/Host time 收益放大到约 `20.5%`，且两次 old 都稳定复现。历史较低压力窗口中
old 曾运行约 `107.6s`，因此不把 `20.5%` 写成所有机器窗口下的固定收益承诺。

P1 同时使 branches 增加 `9.24%`。NO0265 已证明 row-aware activation 会减少 branches，因此
新增分支来自 true merge 主体而不是 row table；它具体分布在 memory read changed detection、
write guard 还是 commit dispatch，仍需下一轮 sampled profile 定位。

## 结论

PHR true merge P1 通过完整 50k 功能 gate，减少了稳定硬件工作量，并显著降低 generated-code
footprint；在当前 old/new/old 窗口中 SimTop 提速约 `1.26x`。该阶段可以提交。下一阶段应对
当前 P1 做 fresh sampled profile，并直接与 GSIM 的 PHR indexed-write 路径对照，定位多出的
guard/commit branches。
