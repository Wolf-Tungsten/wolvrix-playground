# NO0344 Fixed-ASLR GSim / GrhSIM direct compare gate

日期：2026-07-12

## 1. 口径与有效性

按 [NO0343](./NO0343_fixed_aslr_gsim_grhsim_direct_compare_plan_20260712.md)，先用 GSim `-C 100`
确认 cycles、instructions、frontend empty、cmask6、backend stalls 五事件均为 `100.00%` 调度，再以
`setarch -R`、CPU138、NUMA node 1 执行 GSim / NO0300 GrhSIM / GSim 的 CoreMark 50k A/B/A。

正式运行前全机 load 约 `5~11/384`；一次 `15.81/384` 的短时 load 峰值出现后等待并复查，CPU138/330
恢复到 `98.01%/100%` 平均空闲才启动 GSim1。GrhSIM 与 GSim2 前目标核分别连续三秒 `100%` 和
`99.67%` 空闲。

三轮都完成 `50001` guest cycles，无 mismatch/assertion/abort，五事件全部 `100.00%` 调度：

| Simulator | `instrCnt / cycleCnt` | Terminal PC |
| --- | ---: | --- |
| GSim | `73584 / 49998` | `0x8000131e` |
| GrhSIM | `73580 / 49996` | `0x80001312` |

两次 GSim 的 difftest state pointer 均为 `0x555558adcd20`；GrhSIM 为与 NO0340/NO0342 一致的
`0x55555afa8d30`，固定地址链路生效。

## 2. 原始计数

| Run | Host time (ms) | Host cycles | Instructions | Frontend empty | cmask6 cycles | Backend stalls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GSim1 | 30,898 | 113,074,565,952 | 80,070,645,030 | 527,480,058,407 | 67,733,353,070 | 24,040,856,246 |
| GrhSIM | 77,011 | 281,912,757,469 | 172,878,902,692 | 1,287,725,034,023 | 166,702,467,587 | 93,537,427,300 |
| GSim2 | 30,989 | 113,420,551,668 | 80,070,645,292 | 529,593,482,943 | 68,089,857,480 | 23,971,865,678 |

GSim Host time spread 为 `0.294%`，cycles spread 为 `0.306%`，通过计划中的 `1%` 门限。中间
GrhSIM cycles 比 NO0342 的 fixed NO0300 低 `0.388%`，同样处于相邻基线波动量级。

以两次 GSim 均值计算：

| Metric | GSim mean | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| Host time | 30,943.5 ms | 77,011 ms | 2.489x |
| Host cycles | 113,247,558,810 | 281,912,757,469 | 2.489x |
| Instructions | 80,070,645,161 | 172,878,902,692 | 2.159x |
| Frontend empty | 528,536,770,675 | 1,287,725,034,023 | 2.436x |
| cmask6 cycles | 67,911,605,275 | 166,702,467,587 | 2.455x |
| Backend stalls | 24,006,360,962 | 93,537,427,300 | 3.896x |

Host IPC 为 GSim `0.707041`、GrhSIM `0.613235`，GSim 高 `1.153x`。

## 3. Frontend / backend density

dispatch-slot 事件按 host cycles 归一化：

| Metric / host cycle | GSim | GrhSIM | GrhSIM / GSim |
| --- | ---: | ---: | ---: |
| Frontend empty slots | 4.667092 | 4.567814 | 0.979x |
| cmask6 cycles | 0.599674 | 0.591326 | 0.986x |
| Backend stall slots | 0.211981 | 0.331796 | 1.565x |

按 `latency_slots = 6 * cmask6` 分解后，GrhSIM/GSim 的 latency density 为 `0.986x`，剩余
bandwidth-empty density 为 `0.954x`。因此 latest GrhSIM 每个 host cycle 的 frontend supply 不差于 GSim；
明显恶化的是 backend stall density。这与 NO0281 的方向一致，但本轮排除了随机 PIE 基址。

## 4. Excess-cycle 分解

使用 GSim CPI 对 GrhSIM 的额外 instructions 做算术折算：

```text
total excess cycles                     = 168,665,198,659
extra-instruction component             = 131,262,943,887  (77.825%)
remaining CPI component                 =  37,402,254,772  (22.175%)
```

该分解不假设两边指令语义相同，但明确了优先级：即使把 GrhSIM 的 IPC 提升到 GSim 水平，额外动态指令
仍占 excess cycles 的约四分之三；backend/CPI 是第二问题，不能取代 instruction-count 主线。

相对 NO0281 的随机地址 NO0278 对照，cycles ratio 从 `2.672x` 降到 `2.489x`，instructions ratio 从
`2.378x` 降到 `2.159x`。fixed GSim cycles 相对 NO0281 两组历史值只变化 `-0.65%/-0.27%`，instructions
变化 `-0.0007%`；GSim 没有出现 NO0300 的约 `8%` 基址敏感度。gap 缩小主要来自后续 GrhSIM 优化和
NO0300 fixed layout，而不是 GSim 基线变慢。

## 5. 结论与下一步

same-FIR、fixed-ASLR 下，latest NO0300 GrhSIM 功能正确，但 SimTop 50k 仍比 GSim 慢 `2.489x`。
frontend density 已不是主要差异；额外 host instructions 解释约 `77.82%` excess cycles，backend stall
density `1.565x` 解释剩余 CPI 问题的方向。

下一步先用 fixed-ASLR、固定 period `instructions:u` 重新 profile GSim 与 NO0300，更新 NO0282 的
`subStep`、compute、commit 动态指令分布，并直接对照最新 generated C++。若 extra instructions 仍集中于
compute，则继续删 GrhSIM 独有的 value materialization/activation work；若 commit 占比已显著上升，再并行
处理 backend-stall 高的 commit code。该 profile 形成新文档后再决定具体代码改动。

## 6. 产物

```text
build/logs/xs_perf/no0343/gsim_event_preflight_emu.log
build/logs/xs_perf/no0343/gsim_event_preflight_perf.csv
build/logs/xs_perf/no0343/fixed_gsim1_emu.log
build/logs/xs_perf/no0343/fixed_gsim1_perf.csv
build/logs/xs_perf/no0343/fixed_grhsim_emu.log
build/logs/xs_perf/no0343/fixed_grhsim_perf.csv
build/logs/xs_perf/no0343/fixed_gsim2_emu.log
build/logs/xs_perf/no0343/fixed_gsim2_perf.csv
```
