# NO0319 NO0286 / NO0300 control-flow redirect gate

日期：2026-07-12

## 1. 口径与有效性

按 [NO0318](./NO0318_control_flow_redirect_pmu_plan_20260712.md) 对无 profile NO0286 / NO0300
执行 fixed CPU138、NUMA node 1 的 old / new / old CoreMark 50k。三轮均得到 `Guest cycle spent = 50001`、
`cycleCnt = 49996`、`instrCnt = 73580` 和 terminal PC `0x80001312`，无 assertion、abort 或 difftest
mismatch；五项事件均为 `100.00%` 调度。

Host time 为 `80,887 / 84,382 / 80,935 ms`，两次 old spread 仅 `0.059%`。host cycles old spread
为 `0.071%`，NO0300 相对 old 均值回退 `4.284%`，与前几轮约 4% 结果一致。

运行前全机 load 相对 384 个逻辑 CPU 很低。CPU138 始终接近全空闲；old2 前发现 sibling CPU330
单秒 `5%~7%` 瞬态占用后等待复查，后续归零，且 old2 未出现 timing 漂移。

## 2. 原生计数

下表 old 为两次均值；per-work 使用 [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md)
的 `work_total`，per-instruction 使用 [NO0302](./NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md)
的无插桩 instructions：

| Metric | NO0286 old mean | NO0300 new | Absolute | Per cycle | Per work | Per instruction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| host cycles | 296,241,005,270 | 308,933,107,124 | +4.284% | - | +8.973% | +13.911% |
| retired taken branch | 6,975,627,785 | 6,943,662,265 | -0.458% | -4.548% | +4.017% | +8.731% |
| retired taken mispredict | 5,480,568,050.5 | 5,366,769,188 | -2.076% | -6.099% | +2.326% | +6.963% |
| decoder redirect | 2,391,208,626.5 | 2,354,673,520 | -1.528% | -5.573% | +2.900% | +7.563% |
| non-mispredict resync | 48,450,909.5 | 42,220,300 | -12.860% | -16.440% | -8.942% | -4.815% |

派生比率也改善：

| Ratio | NO0286 | NO0300 | Relative delta |
| --- | ---: | ---: | ---: |
| taken mispredict / taken | 78.5674% | 77.2902% | -1.626% |
| decoder redirect / taken | 34.2795% | 33.9111% | -1.075% |

## 3. 解释边界

NO0300 的 total work 下降 `4.30%`，因此 taken、taken-mispredict 和 decoder redirect 虽然绝对值下降，
per work 仍增加 `2.3%~4.0%`。这与 [NO0312](./NO0312_no0286_no0300_dynamic_work_gate_20260712.md)
已经记录的 branches/work `+4.56%` 一致，说明 ordered graph 的单位工作控制流密度确有恶化。

但是四类事件的绝对值和 per-host-cycle 值全部下降，mispredict/taken 与 redirect/taken 也改善；它们没有像
[NO0317](./NO0317_no0286_no0300_frontend_latency_itlb_gate_20260712.md) 的 latency slots 那样绝对值
`+11.12%`、per cycle `+6.62%`。因此不能把更多 redirect 次数当成整周期 frontend 断供的直接计数根因。
控制流密度仍可能放大单位 work 成本，但本轮没有给出应直接改 branch shape 的充分证据。

## 4. 结论与下一步

本轮排除 taken-branch、mispredict、decoder resteer 或 non-control-flow resync 的计数增加。下一步转向
op-cache access/hit/miss 与 decoder/op-cache dispatch source，检查 NO0300 的代码布局变化是否使更多 fetch
窗口无法由 op cache 供给。若 op-cache 同样不恶化，则需要用 sampled frontend-latency 事件或更细的 fetch
stall 原因把 full-empty 周期映射到具体 generated compute functions，而不是继续扩大全局 counter 列表。

## 5. 产物

```text
build/logs/xs_perf/no0318/control_redirect_old1_emu.log
build/logs/xs_perf/no0318/control_redirect_old1_perf.csv
build/logs/xs_perf/no0318/control_redirect_new_emu.log
build/logs/xs_perf/no0318/control_redirect_new_perf.csv
build/logs/xs_perf/no0318/control_redirect_old2_emu.log
build/logs/xs_perf/no0318/control_redirect_old2_perf.csv
```

