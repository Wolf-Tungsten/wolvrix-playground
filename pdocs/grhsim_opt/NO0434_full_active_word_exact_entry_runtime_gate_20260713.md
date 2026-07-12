# NO0434 Full active-word exact-entry runtime gate

日期：2026-07-13

## 1. Validity gates

按 [NO0432](./NO0432_full_active_word_exact_entry_runtime_plan_20260712.md) 和
[NO0433](./NO0433_full_active_word_exact_entry_pmu_preflight_gate_20260713.md)，在 CPU131、NUMA1、
`setarch -R` 下串行执行 exact baseline / exact candidate / exact baseline 50k A/B/A。

每轮只在 CPU131/323 三秒平均 idle 均 `>=99%` 后启动 perf：

| run | attempt | CPU131 idle | CPU323 idle | result |
| --- | ---: | ---: | ---: | --- |
| baseline1 | 1 | 98.33% | 97.67% | reject before perf |
| baseline1 | 2 | 99.67% | 99.34% | pass |
| candidate | 1 | 100.00% | 100.00% | pass |
| baseline2 | 1 | 98.33% | 97.33% | reject before perf |
| baseline2 | 2 | 100.00% | 99.00% | pass |

三轮均 exit 0，fixed-ASLR state 均为 `0x55555aea2d30`，完成 73,580 instructions 的 NEMU difftest；
guest/cycleCnt/PC 为 `50,001/49,996/0x80001312`。没有 mismatch、assert/abort、fatal/error、
segmentation fault 或 `input_fullpass_blocked`，五项 PMU 均 100% scheduled。

baseline cycles spread 为 `0.075197%`，通过 `<=1%` 门禁；backend counter spread 为 `0.852482%`，其余
计数 spread 均低于 `0.1%`。

## 2. Raw counters

| run | host ms | cycles | instructions | frontend empty | cmask6 | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline1 | 77,403 | 280,003,101,922 | 166,888,265,775 | 1,282,814,590,790 | 167,138,094,309 | 91,773,198,255 |
| candidate | 79,011 | 285,832,429,148 | 165,691,209,549 | 1,317,594,338,878 | 172,955,250,392 | 91,468,147,898 |
| baseline2 | 77,456 | 280,213,734,251 | 166,888,265,839 | 1,282,790,742,360 | 167,163,621,529 | 92,558,897,447 |

以两次 baseline 均值计算：

| metric | baseline mean | candidate | delta |
| --- | ---: | ---: | ---: |
| host time | 77,429.5 ms | 79,011 ms | +2.043% |
| cycles | 280,108,418,086.5 | 285,832,429,148 | +2.043% |
| instructions | 166,888,265,807 | 165,691,209,549 | -0.717% |
| frontend empty | 1,282,802,666,575 | 1,317,594,338,878 | +2.712% |
| cmask6 cycles | 167,150,857,919 | 172,955,250,392 | +3.473% |
| backend stalls | 92,166,047,851 | 91,468,147,898 | -0.757% |

## 3. Density and decomposition

| per host cycle | baseline | candidate | delta |
| --- | ---: | ---: | ---: |
| IPC | 0.595799 | 0.579680 | -2.705% |
| frontend empty | 4.579665 | 4.609674 | +0.655% |
| cmask6 | 0.596736 | 0.605093 | +1.400% |
| backend stalls | 0.329037 | 0.320006 | -2.745% |
| non-cmask6 frontend slots | 0.999247 | 0.979115 | -2.015% |

candidate 删除 1.197B host instructions。按 baseline CPI `1.678419`，理论应节省 2.009B cycles，保持 baseline
CPI 时预计为 278.099B cycles；实际为 285.832B，等价于额外 7.733B CPI/前端成本，最终净增加 5.724B
cycles。instruction benefit realization 为 `-284.90%`。

后端与 non-cmask6 frontend density 仍改善，cycles 回退继续与 full-empty cmask6 density 增加同向。

## 4. Native comparison and conclusion

与 [NO0427](./NO0427_full_active_word_native_runtime_gate_20260712.md) 各自按现场双 baseline 归一化后比较：

| metric | native candidate delta | exact-entry candidate delta | exact - native |
| --- | ---: | ---: | ---: |
| cycles | +1.877% | +2.043% | +0.167 pp |
| instructions | -0.717% | -0.717% | 0.000 pp |
| frontend/cycle | +0.604% | +0.655% | +0.052 pp |
| cmask6/cycle | +1.172% | +1.400% | +0.228 pp |
| backend/cycle | -3.137% | -2.745% | +0.392 pp |

exact-entry 没有回收 native candidate 的 cycles/full-empty 回退，反而在这两个主指标上小幅变差。两次实验虽使用
同一 CPU，但本轮 exact baseline absolute cycles 比 NO0427 baseline 低 `8.073%`，说明跨时段运行状态不同；因此不把
两次 candidate absolute counters 的差异归因于 padding，只采用各自 A/B/A 的归一化变化。

117 个 sched entry 同址且 `.text` 同长只能控制函数入口，不能控制删指令后函数内部各基本块/IP 的地址。结果否定了
“只要恢复完整函数入口，full-word consume 就能获得净 cycles 收益”的假设；它也没有提供可部署的正收益。按 NO0432
的预声明停止该路线，`full_active_word_consume` 继续默认关闭，不再用入口漂移解释或掩盖实际回退。

下一步回到 GrhSIM/GSim 当前 hot compute 差异，选择新的、可先通过 machine/dynamic 上界门禁的候选；不继续为该
开关增加布局控制实验。

## 5. Artifacts

```text
build/logs/xs_perf/no0432/{baseline1,candidate,baseline2}_{emu.log,perf.csv}
build/logs/xs_perf/no0432/{baseline1,candidate,baseline2}_quiet_gate_attempt_*.log
build/logs/xs_perf/no0432/runtime_summary.txt
```
