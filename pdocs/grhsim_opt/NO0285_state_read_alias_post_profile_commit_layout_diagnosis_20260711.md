# NO0285 State-read alias post-profile and commit layout diagnosis

日期：2026-07-11

## 1. 目标

[NO0283](./NO0283_same_supernode_state_read_slot_alias_20260711.md) 已确认 SimTop 50k host
instructions 稳定下降约 `0.86%`。本轮使用固定 period 的 instruction/cycles profile 判断收益落点，
并继续对照 GSim，定位 GrhSIM 剩余 commit 开销来自指令数量还是单指令周期。

## 2. Instruction profile

NO0283 fresh emu 固定 CPU138，使用 `instructions:u`、period `25000000`、DWARF stack `8192`，
执行到相同 50k 功能终点：

```text
Guest cycle spent: 50001
instrCnt = 73580
cycleCnt = 49996
terminal pc = 0x80001312
Host time spent: 82902ms
samples = 7551
lost samples = 0
approx instructions = 188775000000
```

与 NO0278 的 `7617` samples 对比，compute8 从 `403` 降到 `254`，减少 `149` samples，
即约 `3.725B` sampled instructions；这超过全局净减 `66` samples，说明链接布局变化使其他符号
存在采样重分布，但 NO0283 的直接收益确实集中在目标 batch。

NO0283 分类结果：

| phase | instruction samples | share |
| --- | ---: | ---: |
| compute batches | `6536` | `86.56%` |
| commit batches | `841` | `11.14%` |
| eval/row helper/other | `174` | `2.30%` |

最大 instruction symbols 为 commit113 `267`、compute8 `254`、compute39 `230`。commit113 的
machine text 在 NO0278/NO0283 间逐字节一致，因此它从旧 profile 的 `229` 到本轮 `267` 不能解释为
NO0283 引入的源码退化。

## 3. 当前 cycles profile

采样前整机 load average 为 `6.02/6.34/6.98`，机器有 384 logical CPUs；CPU138 三秒平均
`97.32% idle`。保持相同 emu、镜像、difftest 和 50k cycle 上限，仅把 event 改为 `cycles:u`：

```text
Guest cycle spent: 50001
instrCnt = 73580
cycleCnt = 49996
terminal pc = 0x80001312
Host time spent: 83101ms
samples = 12120
lost samples = 0
approx cycles = 303000000000
```

两个 profile period 都是 `25000000`，因此同一 symbol/phase 的 cycles samples / instruction samples
可作为近似 CPI 指标。它不替代同次 `perf stat`，但足以区分热点形态：

| phase/symbol | instruction samples | cycles samples | samples ratio |
| --- | ---: | ---: | ---: |
| all compute batches | `6536` | `8042` | `1.230` |
| all commit batches | `841` | `3866` | `4.597` |
| commit113 | `267` | `344` | `1.288` |
| compute8 | `254` | `309` | `1.217` |
| compute39 | `230` | `196` | `0.852` |

结论是 commit aggregate 的周期代价很高，但最大 instruction hotspot commit113 并非高 CPI 异常点。
commit113 的 42,937 条 scalar write changed-check 主要贡献动态指令，不是每条指令异常昂贵。

真正高 ratio 的 commit batches 包括：

| symbol | instruction samples | cycles samples | ratio |
| --- | ---: | ---: | ---: |
| commit79 | `7` | `148` | `21.14` |
| commit102 | `6` | `124` | `20.67` |
| commit104 | `6` | `116` | `19.33` |
| commit94 | `14` | `196` | `14.00` |
| commit97 | `13` | `164` | `12.62` |
| commit82 | `15` | `173` | `11.53` |

## 4. commit94 code-layout evidence

commit94 generated source 约 `55k` 行、`3.71 MB`。它在一个 posedge commit batch 中扫描大量
scalar state writes，源码均为：

```cpp
if (state != next_value) {
    state = next_value;
    commit_activated_readers_ = true;
    // activate readers
}
```

Clang 对 commit94 的大量 changed-check 选择了以下布局：

```asm
cmp    next,state
je     skip_update
... update and activate ...
skip_update:
```

cycles annotate 的 `196` samples 中，`188` 落在 `je`，占 `95.92%`，且 sampled addresses 分散在
整个函数的 changed-check 链。常见的未变化路径因此持续执行 taken branches。

低 ratio 的 commit113 则主要被布局为：

```asm
cmp    next,state
jne    cold_update
... next comparison ...
```

其 instruction annotate 的 `267` samples 中有 `136` 个 `jne`，但未变化路径为 fall-through；
cycles/instructions ratio 只有 `1.288`。两者说明相同 C++ 语义在不同函数体中被 Clang 选择了不同
fall-through 方向，commit94 类 batch 的前端/分支成本被显著放大。

## 5. 与 GSim 和历史实验的关系

同一类 GSim register update 通常使用 branchless changed-mask：先保存 old state、写入 next，再用
`state ^ old` 累积 active mask。GrhSIM 多出来的是逐 scalar state 的 changed control-flow。直接全局
branchless 并不安全：

- [NO0083](./NO0083_branchless_changed_activation_experiment_20260509.md) 的粗粒度 compute tracked-value
  branchless 使 instructions 增加 `18.72%`、wall time 增加 `2.19%`；该实验未覆盖 commit state write。
- [NO0206](./NO0206_commit_activation_mask_group_plan_20260624.md) 的 exact reader-mask group 仍保留逐写
  branch，又增加 group flags，使 SimTop 50k 慢约 `1.88x`，已回退。
- [NO0270](./NO0270_simtop_tage_commit_guard_branch_miss_diagnosis_20260711.md) 证明 changed-check 本身通常
  高度可预测，不能仅凭 branch-miss 推导全局 branchless。

当前证据支持的最小实验不是 branchless，而是给 commit state-change 条件明确的 cold hint，让未变化路径
稳定保持 fall-through。它不增加无条件 state store 或 active-mask load/or/store，语义也不变。

## 6. 下一步 gate

1. emitter 增加可关闭的 commit changed-path `unlikely` hint，第一版覆盖 scalar/wide register/latch direct
   update，默认先作为 A/B 开关。
2. emitter 单测同时检查 hint 开关生成形态与执行语义。
3. fresh SimTop 先检查 commit94/commit113 反汇编方向和 `.text`，再做 10k/50k difftest。
4. 固定 CPU old/new/old 记录 cycles、instructions、branches、branch-misses；如果负收益则完整撤回实现。

## 7. 产物

```text
build/logs/xs_perf/no0283/grhsim_slot_alias_cpu138_50k_instructions.data
build/logs/xs_perf/no0283/grhsim_slot_alias_cpu138_50k_instructions_exact_symbols.report
build/logs/xs_perf/no0283/grhsim_slot_alias_cpu138_50k_cycles.data
build/logs/xs_perf/no0283/grhsim_slot_alias_cpu138_50k_cycles_exact_symbols_samples.report
build/logs/xs_perf/no0283/new_slot_alias_instruction_cycles_batch_cpi.tsv
build/logs/xs_perf/no0283/grhsim_slot_alias_commit94_cycles_annotate_samples.report
build/logs/xs_perf/no0283/grhsim_slot_alias_commit94_cycles_sampled_mnemonics.tsv
build/logs/xs_perf/no0283/grhsim_slot_alias_commit94_cycles_sampled_instructions.tsv
```
