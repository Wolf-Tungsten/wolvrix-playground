# TNO0010 Code layout, ASLR, and fixed profile

记录日期：2026-07-13

来源范围：`NO0329..NO0349`，原始记录见 [NO0329](../grhsim_opt/NO0329_batch_function_page_alignment_plan_20260712.md) 至 [NO0349](../grhsim_opt/NO0349_fixed_aslr_latest_instruction_profile_codegen_compare_20260712.md)。

状态：确立 fixed-ASLR 为正式性能口径，推翻 ordered-affine 的随机基址回退；更新 same-FIR GSim/GrhSIM gap 和 instruction flamegraph。

## 1. Layout probes

GrhSIM 117 个 batch 平均约 739..815 KB，远大于 GSim 329 个 `subStep` 的 147 KB。4 KiB function alignment 使两侧入口低位收敛，功能正确；随机基址下 ordered 版相对 aligned baseline 一度显示 `-5.94%` cycles，但主要因为 alignment 让 baseline 变慢约 10.6%，不是中性优化。

无重编 bit-reversal archive 重排使执行后继地址相邻率 `100% -> 0%`，fixed-ASLR 下 cycles 仅改善 `0.74%`，不能解释历史 4% 差异。

## 2. PIE/ASLR 勘误

确认 emu 是 PIE、系统 ASLR=2，历史 perf 未固定 load base。同一 binary 的随机地址样本 cycles 可差 8%..9%。因此旧 numeric/page-align 的绝对性能比较作废或降级为 provisional。

`setarch -R` 连续 mapping SHA 完全一致，text base 固定为 `0x55555555c000`。从此正式 runtime 必须同时固定：

- logical CPU 与 NUMA node；
- SMT sibling idle gate；
- PIE load base；
- PMU schedule ratio；
- A/B/A baseline spread。

## 3. Ordered-affine 重校准

fixed-ASLR NO0286/NO0300/NO0286 的 baseline spread 为 `0.29%`：

```text
dynamic work     -4.30%
cycles           -4.75%
cycles/work      -0.47%
```

这推翻了随机基址下约 `+4% cycles` 和 `+8.52% cycles/work` 的回退，证明 ordered-affine 的结构/工作减少能够转为真实性能收益。

## 4. 最新 GSim/GrhSIM 对照

fixed-ASLR same-FIR GSim/GrhSIM/GSim：

```text
cycles ratio        2.489x
instructions ratio  2.159x
extra instructions 解释 excess cycles 77.82%
backend stall density 1.565x
```

frontend empty/cmask6 density不比 GSim 差，主线重新回到删 host instructions。

## 5. Instruction profile

修正 fixed-period event count 与 FlameGraph period weighting 后，最新 instruction gap 近似拆为：

| Phase | Excess share |
| --- | ---: |
| compute | `71.43%` |
| commit | `23.54%` |
| other | `5.04%` |

compute8 的 timer 物化已由 slot alias 基本消除；当前 21,069 个 scalar state-read materializations 中 92.86% 来自 logEndpoint。下一主线转向跨 schedule boundary 的 state-read locality/direct forwarding。

## 6. 规则审计与关键数据

记录类型：性能口径校准与 same-FIR root-cause 更新。单一议题边界是“PIE load address 对大 batch 性能结论的污染有多大，以及固定地址后真实 GSim/GrhSIM gap 是多少”。页对齐和 object-order 都是隔离该变量的 probe；后续机制实验必须另建 TNO。

### 6.1 Fixed-ASLR 方法

fixed-ASLR 使用 `setarch $(uname -m) -R` 启动原有 PIE emu，不需要重新编译。连续两次 10k maps 的五段地址与 SHA256 完全一致，text base 固定为 `0x55555555c000`。同一 NO0300 binary 的 fixed numeric cycles 比历史随机基址低 `8.16%..8.80%`，因此旧随机地址比较不能继续作为最终结论。

### 6.2 Ordered-affine A/B/A 重校准

CPU138、NUMA1、fixed-ASLR，三轮均达到 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`，四项 PMU `100%`：

| Run | Host ms | Host cycles | Instructions |
| --- | ---: | ---: | ---: |
| NO0286 baseline1 | 81,085 | 296,693,879,641 | 188,838,091,961 |
| NO0300 ordered-affine | 77,319 | 283,010,641,755 | 172,878,903,261 |
| NO0286 baseline2 | 81,301 | 297,549,973,489 | 188,838,092,054 |

baseline cycles spread `0.288%`；candidate 相对 baseline mean 的 wall/cycles/instructions 为 `-4.77%/-4.75%/-8.45%`，cycles/work 为 `-0.47%`。这正式推翻随机基址下的回退。

### 6.3 Latest GSim/GrhSIM 50k

| Run | `instrCnt/cycleCnt` | Host ms | Host cycles | Host instructions |
| --- | ---: | ---: | ---: | ---: |
| GSim1 | `73584/49998` | 30,898 | 113,074,565,952 | 80,070,645,030 |
| GrhSIM | `73580/49996` | 77,011 | 281,912,757,469 | 172,878,902,692 |
| GSim2 | `73584/49998` | 30,989 | 113,420,551,668 | 80,070,645,292 |

GSim cycles spread `0.306%`；GrhSIM 为 GSim mean 的 `2.489x` host time/cycles、`2.159x` instructions。所有样本完成 `50001` guest cycles、五事件 `100%` scheduled。原始记录见 [NO0339](../grhsim_opt/NO0339_fixed_aslr_mapping_probe_20260712.md)、[NO0342](../grhsim_opt/NO0342_fixed_aslr_no0286_no0300_runtime_gate_20260712.md) 与 [NO0344](../grhsim_opt/NO0344_fixed_aslr_gsim_grhsim_direct_compare_gate_20260712.md)。
