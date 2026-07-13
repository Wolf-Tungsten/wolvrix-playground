# TNO0019 SimTop pure-event profile and plain bypass

记录日期：2026-07-13

来源范围：`NO0495..NO0509`，原始记录见 [NO0495](../grhsim_opt/NO0495_simtop_pure_event_word_profile_fresh_plan_20260713.md) 至 [NO0509](../grhsim_opt/NO0509_pure_event_bypass_runtime_load_gate_snapshot_20260713.md)。

状态：107-word production classifier、动态 miss 机会与 plain bypass 功能已闭合；正式 runtime 因机器负载保持零有效样本，且 batch27 存在 codegen cliff。

## 1. Profile-only production closure

fresh schedule/direct-read 与 direct-state baseline 精确一致，production classifier 命中 22 batches/107 words，与离线 audit 完全一致。profile-only 仅改变 25/154 files。

动态结果：

| Workload point | Hit | Miss | Miss ratio |
| --- | ---: | ---: | ---: |
| 100 cycles | 16,050 | 18,452 | `53.48%` |
| 10k | 1,075,350 | 1,291,582 | `54.57%` |
| 50k | 5,355,350 | 6,948,664 | `56.47%` |

50k 理论可越过约 55.59M entry tests，前五 hot batches 覆盖 67.29% misses。100/10k/50k 功能终点及 checkpoints 与 baseline 一致。

## 2. Plain bypass fresh gate

profile-off production bypass：

- schedule/direct identity 保持；
- 仅 22 sched files 改变，107 markers；
- 无 profile state 泄漏；
- 100/10k/50k difftest 与 checkpoints 全部通过；
- `input_fullpass_blocked` 与负向扫描为 0。

## 3. Batch27 codegen cliff

full emu O3 text/instructions 小幅增加 `10,128/1,538`，几乎全部由 batch27 的任一 wrapper 触发同一巨型函数 value-propagation cliff；扣除 batch27 后其余 21 batches 整体下降。

所以“动态 miss 机会大”并不等于当前 predicate 形态会产生更小机器码，必须先稳定 batch27 codegen。

## 4. Runtime load gate

fixed-ASLR baseline/bypass/baseline 预声明 sibling idle `>=99%`。CPU104/296、CPU127/319 及 node0 候选连续未达门限，共享 CI/emu 负载下没有启动正式 PMU 样本，也没有引用 raw 95.2s 作为结论。

## 5. 阶段结论

pure-event bypass 的语义和动态机会成立，plain candidate 功能正确；当前阻塞是 batch27 codegen cliff 与机器负载。后续先做 predicate materialization 的对象级稳定化，再重新 fresh build/function/runtime。

## 6. 规则审计与关键数据

记录类型：production SimTop 机会验证与 plain-candidate gate。单一议题边界是“107 个 pure-event words 在真实 SimTop 上是否有足够 miss 机会，且直接实现能否通过 codegen/功能/runtime 前置门槛”。插桩 profile host time 和高负载 raw time均不作性能数据。

| Gate | Guest/model cycles | `cycleCnt` | `instrCnt` | Terminal PC | Hit / miss |
| --- | ---: | ---: | ---: | --- | ---: |
| profile 100-cycle | `101/100` | 96 | 0 | `0x0` | `16,050 / 18,452` |
| profile 10k | `10001/10000` | 9,996 | 458 | `0x800027c6` | `1,075,350 / 1,291,582` |
| profile 50k | `50001/50000` | 49,996 | 73,580 | `0x80001312` | `5,355,350 / 6,948,664` |

Plain bypass 的 100/10k/50k 功能终点与 checkpoints 同样精确匹配 baseline。50k 理论可越过约 `55.59M` entry tests；但 O3 full emu text/instructions 反增 `10,128/1,538`，几乎全部来自 batch27 codegen cliff。

50k plain raw walltime曾为 `95.2s`，运行中整机负载上升，明确作废。预声明 fixed-ASLR A/B/A 要求 sibling idle `>=99%`，多组候选核均未过门槛，正式 PMU 样本数为 0。详见 [NO0500](../grhsim_opt/NO0500_simtop_pure_event_word_profile_50k_gate_20260713.md)、[NO0503](../grhsim_opt/NO0503_simtop_pure_event_word_bypass_build_codegen_gate_20260713.md)、[NO0506](../grhsim_opt/NO0506_simtop_pure_event_word_bypass_50k_functional_gate_20260713.md) 与 [NO0509](../grhsim_opt/NO0509_pure_event_bypass_runtime_load_gate_snapshot_20260713.md)。
