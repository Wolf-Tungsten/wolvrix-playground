# NO0427 Full active-word native runtime gate

日期：2026-07-12

## 1. Validity gates

按 [NO0424](./NO0424_full_active_word_fixed_aslr_runtime_plan_20260712.md)、
[NO0425](./NO0425_full_active_word_runtime_cpu_reselection_20260712.md) 和
[NO0426](./NO0426_full_active_word_pmu_preflight_gate_20260712.md)，在 CPU131、NUMA1、`setarch -R` 下串行执行
NO0357 baseline / full-word candidate / NO0357 baseline 50k A/B/A。

每轮前 CPU131/323 quiet gate 均通过：

| run | CPU131 idle | CPU323 idle |
| --- | ---: | ---: |
| baseline1 | 100.00% | 100.00% |
| candidate | 100.00% | 99.00% |
| baseline2 | 99.67% | 99.00% |

三轮均 exit 0，完成 73,580 instructions 的 NEMU difftest，guest/cycleCnt/PC 为
`50,001/49,996/0x80001312`。没有 mismatch、assert/abort、fatal/error、segmentation fault 或
`input_fullpass_blocked`；五项 PMU 全部 100% scheduled。

两次 baseline state 地址同为 `0x55555aea2d30`，candidate 为 `0x55555adfed30`，fixed-ASLR 对各自 PIE 稳定。
baseline cycles spread 为 `0.282865%`，通过 1% 门禁。host time spread 为 `1.195%`，但 host time 从未作为
有效性硬门禁或主判指标。

## 2. Raw counters

| run | host ms | cycles | instructions | frontend empty | cmask6 | backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline1 | 84,206 | 304,276,750,732 | 166,888,272,975 | 1,429,772,460,411 | 191,528,586,082 | 91,492,814,957 |
| candidate | 85,634 | 310,425,955,548 | 165,691,216,438 | 1,468,073,432,162 | 197,876,650,645 | 90,121,200,719 |
| baseline2 | 83,206 | 305,138,662,841 | 166,888,271,247 | 1,434,993,676,906 | 192,434,215,229 | 91,158,935,630 |

以两次 baseline 均值计算：

| metric | baseline mean | candidate | delta |
| --- | ---: | ---: | ---: |
| host time | 83,706 ms | 85,634 ms | +2.303% |
| cycles | 304,707,706,786.5 | 310,425,955,548 | +1.877% |
| instructions | 166,888,272,111 | 165,691,216,438 | -0.717% |
| frontend empty | 1,432,383,068,658.5 | 1,468,073,432,162 | +2.492% |
| cmask6 cycles | 191,981,400,655.5 | 197,876,650,645 | +3.071% |
| backend stalls | 91,325,875,293.5 | 90,121,200,719 | -1.319% |

## 3. Density and decomposition

| per host cycle | baseline | candidate | delta |
| --- | ---: | ---: | ---: |
| IPC | 0.547700 | 0.533754 | -2.546% |
| frontend empty | 4.700843 | 4.729223 | +0.604% |
| cmask6 | 0.630051 | 0.637436 | +1.172% |
| backend stalls | 0.299716 | 0.290315 | -3.137% |
| non-cmask6 frontend slots | 0.920537 | 0.904607 | -1.730% |

candidate 确实删除约 1.197B host instructions。按 baseline CPI `1.825819`，该删指令本应节省约 2.186B
cycles；candidate 若保持 baseline CPI，预计为 302.522B cycles，但实际为 310.426B，等价于额外 7.904B
CPI/layout 成本，最终净增加 5.718B cycles。instruction benefit realization 为 `-261.63%`。

后端 stall 与 non-cmask6 frontend bandwidth density 均改善，唯一与 cycles 回退同向的是 full-empty cmask6 latency。
这与此前 SimTop 对 batch function 地址高度敏感的结果一致，不支持把回退归因于更多动态工作。

## 4. Conclusion and next gate

native fixed-load-base 下 candidate 为 `instructions -0.717% / cycles +1.877%`，当前不能据此默认启用；开关继续
默认关闭。同时该结果满足 NO0424 的两个 exact-entry 触发条件：cycles/instructions 反向，且 cmask6 density
`+1.172% > 1%`。

下一步复用 NO0378 已验证的 explicit-link padding 方法，保持原 O3 objects 不变，在对应 sched function 之间插入
独立 padding objects，使 baseline/candidate 的 117 个完整入口逐项同址且最终 `.text` 同长。构造通过后必须先做
10k/50k 双边功能，再运行 exact-entry A/B/A，才能判断 clear/restore 删除本身的净 cycles 收益。

本轮使用 CPU131，不把 absolute cycles 与其他 CPU 的历史 GSim 数据直接相除。

## 5. Artifacts

```text
build/logs/xs_perf/no0424/{baseline1,candidate,baseline2}_{emu.log,perf.csv}
build/logs/xs_perf/no0424/{baseline1,candidate,baseline2}_quiet_gate_attempt_1.log
build/logs/xs_perf/no0424/runtime_summary.txt
```
