# TNO0005 Array true-merge expansion

记录日期：2026-07-13

来源范围：`NO0270..NO0280`，原始记录见 [NO0270](../grhsim_opt/NO0270_simtop_tage_commit_guard_branch_miss_diagnosis_20260711.md) 至 [NO0280](../grhsim_opt/NO0280_or_decoded_true_merge_cycles_post_profile_20260711.md)。

状态：true-merge 从 PHR 扩展到 TAGE、ROB、DCache/LLPTW；各阶段功能与相邻 50k A/B/A 闭合。

## 1. TAGE shared packed-view merge

branch profile 将热点定位到 TAGE useful counters 的 4096 个 one-hot scalar write guards；GSim 保留 `[4][2][512]` 数组循环。

扩展 shared packed-view discovery 后恢复 64 个 `[512]` memories：

```text
scalar writes      32,768 -> 0
compute-commit pairs        -20.83%
50k Host time              -13.71%
branches                   -10.58%
branch misses              -23.85%
```

## 2. ROB edge-padded merge

下一热点 `debug_VecOtherPdest` 是 512-bit view 对 352-row storage。edge-padding matcher 保守恢复 8 组 ROB memory：

- 2,816 scalar writes 变为 16 indexed writes + 8 fills；
- `.text -0.71%`，compute-commit pairs `-5.70%`；
- 50k Host time/cycles 约 `-16.97%`；
- throughput `+20.44%`；
- 目标 branch-miss samples 从 282 降到 0 observed。

## 3. OR-decoded priority merge

对单个 OR 内最多 32 个独立地址 alternative 增加保守 matcher，恢复 4 个 DCache `[256]` 与 3 个 LLPTW `[6]` groups。generated C++ 减少 4.88 MB，50k Host time/cycles `-11.28%`。

instructions 只下降 `0.22%`，但 frontend stalled cycles 与 empty slots 分别下降 `15.02%/12.69%`。cycles profile 显示 89.64% sample 减量在 compute，说明收益被全局 compute code layout 放大，而不只是目标写口直接成本。

## 4. 共同约束

所有扩展都保持：

- 严格地址/掩码/domain 匹配；
- 明确 priority 与同地址冲突语义；
- synthetic collision/reset gate；
- fresh SimTop 10k/50k difftest；
- 相邻 baseline/new/baseline 50k 复测。

## 5. 阶段结论

array true-merge 是本轮最有效的结构优化之一。它同时减少 scalar guards、代码体积、branch pressure 与 boundary pairs，并证明 generated code layout 会放大局部结构变化。剩余 gap 需要在 fixed layout/ASLR 口径下重新拆解。

## 6. 规则审计与关键数据

记录类型：array true-merge 扩展的阶段 root-cause 总结。单一议题边界是“将已验证的 packed-array merge 契约扩展到不同 decode shape 时，收益和安全边界是否一致”。TAGE、ROB 与 OR-decoded 三项是同一机制的 shape 验证，不作为后续新 matcher 的追加位置。

三轮正式 gate 均为相邻 baseline/candidate/baseline、CoreMark `-C 50000`；每个样本都达到 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`：

| Shape | Baseline mean host ms | Candidate host ms | Baseline mean host cycles | Candidate host cycles | Cycles delta | Baseline cycles spread |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TAGE shared packed view | 98,572 | 85,053 | 361,573,825,318 | 311,976,022,625 | `-13.72%` | `0.14%` 以下 |
| ROB edge-padded | 103,913 | 86,277 | 371,488,508,546 | 308,487,317,278 | `-16.96%` | `0.07%` 以下 |
| DCache/LLPTW OR-decoded | 94,968.5 | 84,257 | 342,122,050,869 | 303,535,719,660 | `-11.28%` | `0.13%` 以下 |

对应 host instructions 分别下降 `3.10%/1.44%/0.22%`；OR-decoded 的 cycles 降幅远大于 instructions，且 frontend stalled cycles/empty slots 分别下降 `15.02%/12.69%`，支持“局部结构变化通过全局 code layout 放大”的判断。原始数据见 [NO0272](../grhsim_opt/NO0272_tage_true_merge_simtop_50k_gate_20260711.md)、[NO0276](../grhsim_opt/NO0276_edge_padded_true_merge_simtop_50k_gate_20260711.md) 与 [NO0279](../grhsim_opt/NO0279_or_decoded_true_merge_simtop_50k_gate_20260711.md)。
