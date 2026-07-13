# NO0365 SimTop direct state-read fixed-ASLR runtime gate

日期：2026-07-12

## 1. 有效性门禁

按 [NO0362](./NO0362_simtop_direct_state_read_fixed_aslr_runtime_plan_20260712.md) 和
[NO0364](./NO0364_simtop_direct_state_read_pmu_preflight_gate_20260712.md)，使用 CPU138、NUMA1、`setarch -R`
串行执行 NO0300 / direct / NO0300 的 CoreMark 50k 五事件 A/B/A。

三轮均以 exit 0 完成：

```text
Guest cycles       50001
cycleCnt           49996
instrCnt           73580
terminal PC        0x80001312
```

没有 mismatch、assertion、abort、fatal/error 或 `input_fullpass_blocked`，五项 PMU 全部 `100.00%` 调度。两次
baseline difftest state address 均为 `0x55555afa7d30`；direct 正式轮与 preflight 均为 `0x55555aea1d30`，
fixed-ASLR 链路稳定。

baseline1 前 CPU138/330 平均空闲 `99.67%/100%`。direct 前因交互控制进程短时落到 sibling CPU330，保留五次
未达 99% 的样本并等待，第六次达到 `99.67%/99.67%` 后才启动。baseline2 前全机 load 短时升至
`9.90/384`，但 quiet gate 达到 `99%/99%` 后才启动。两次 baseline host time/cycles spread 分别为
`0.519%/0.515%`，通过 1% 门限，因此本轮 ratio 有效。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty | cmask6 cycles | Backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline1 | 77,813 | 284,814,422,631 | 172,880,103,994 | 1,301,264,341,984 | 169,033,594,407 | 96,190,521,057 |
| direct | 82,461 | 301,876,065,405 | 166,888,942,479 | 1,416,399,467,905 | 189,383,060,660 | 90,160,605,691 |
| baseline2 | 77,410 | 283,351,211,313 | 172,880,103,120 | 1,293,698,440,201 | 167,743,219,732 | 95,697,238,984 |

以两次 baseline 均值计算：

| Metric | Baseline mean | Direct | Delta |
| --- | ---: | ---: | ---: |
| Host time | 77,611.5 ms | 82,461 ms | +6.248% |
| Host cycles | 284,082,816,972 | 301,876,065,405 | +6.263% |
| Instructions | 172,880,103,557 | 166,888,942,479 | -3.466% |
| Frontend empty | 1,297,481,391,092.5 | 1,416,399,467,905 | +9.165% |
| cmask6 cycles | 168,388,407,069.5 | 189,383,060,660 | +12.468% |
| Backend stalls | 95,943,880,020.5 | 90,160,605,691 | -6.028% |

direct 确实删除约 5.991B host instructions，但固定布局下净增约 17.793B host cycles；因此该实现当前不能作为
SimTop 性能优化启用。开关默认关闭，默认路径没有本轮回退。

## 3. CPI 与 stall density

| Metric per host cycle | Baseline | Direct | Delta |
| --- | ---: | ---: | ---: |
| Host IPC | 0.608555 | 0.552839 | -9.155% |
| Frontend empty slots | 4.567265 | 4.691990 | +2.731% |
| cmask6 cycles | 0.592744 | 0.627354 | +5.839% |
| Backend stall slots | 0.337732 | 0.298668 | -11.567% |

按 `latency_slots = 6 * cmask6` 分解 frontend empty：

| Component | Baseline absolute | Direct absolute | Absolute delta | Density delta |
| --- | ---: | ---: | ---: | ---: |
| full-empty latency slots | 1,010,330,442,417 | 1,136,298,363,960 | +12.468% | +5.839% |
| remaining bandwidth slots | 287,150,948,675.5 | 280,101,103,945 | -2.455% | -8.205% |

回退不是 backend pressure 或部分 frontend bandwidth shortage；两者都改善。唯一同向恶化的是整周期无 dispatch 的
frontend latency。以 baseline CPI 折算：少执行指令本应节省约 9.845B cycles，但额外 CPI 成本约 27.638B，最终
形成 17.793B cycles 净回退。

## 4. 与 GSim gap 的关系

复用 [NO0344](./NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md) 的相邻 fixed GSim 均值：

| GrhSIM model | Cycles / GSim | Instructions / GSim |
| --- | ---: | ---: |
| 本轮 NO0300 mean | 2.509x | 2.159x |
| direct | 2.666x | 2.084x |

direct 把动态指令 gap 改善约 3.47%，但 cycles gap 因前端延迟扩大。这个结果也解释了为什么不能只看 generated
代码缩小或 instruction count。NO0361 未固定地址的 raw time 方向为 `-7.89%`，而本轮 fixed layout 为
`+6.25%`；结合此前 PIE/地址敏感性结论，下一步必须区分 static native layout 与 direct activation 导致的动态
batch/function locality，不能直接撤销已证实有效的删指令机制。

## 5. 下一步

先对 fixed baseline/direct 的 cmask6 full-empty event 做 fixed-period sampling，映射到 compute/commit batch 和
具体 generated functions；同时连接 batch dynamic work，判断额外 frontend latency 是集中在地址变化较大的少数热点，
还是来自 direct frontier 改变函数访问序列。若集中于静态地址/layout，再用两边一致的 batch alignment 做因果探针；
若动态调用序列变化，则先修正 direct consumer activation locality。

## 6. 产物

```text
build/logs/xs_perf/no0362/fixed_baseline1_emu.log
build/logs/xs_perf/no0362/fixed_baseline1_perf.csv
build/logs/xs_perf/no0362/fixed_direct_emu.log
build/logs/xs_perf/no0362/fixed_direct_perf.csv
build/logs/xs_perf/no0362/fixed_baseline2_emu.log
build/logs/xs_perf/no0362/fixed_baseline2_perf.csv
build/logs/xs_perf/no0362/fixed_*_resource*.log
build/logs/xs_perf/no0362/fixed_*_quiet_gate_attempt_*.log
```
