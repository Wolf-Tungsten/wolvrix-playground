# TNO0007 Ordered memory write and affine loop

记录日期：2026-07-13

来源范围：`NO0291..NO0303`，原始记录见 [NO0291](../grhsim_opt/NO0291_ordered_memory_write_contract_plan_20260711.md) 至 [NO0303](../grhsim_opt/NO0303_ordered_memory_write_affine_post_profile_20260712.md)。

状态：ordered-write 与 affine-loop 功能、结构均完成；随机 PIE 基址下的 runtime 回退结论后来由 TNO0010 的 fixed-ASLR 重测推翻。

## 1. Ordered-write contract

三组 RAT 约含 395,550 个理论 pair conflicts。新契约以 `priorityGroup + priority` 表达顺序 indexed writes，使 activity-schedule 和 SV/C++ emitter 共同保证同地址覆盖顺序，将冲突规模从近二次降为 writer 线性。

初版 priority 使用错误的 regular index，10k 在 cycle 664 失败。修复后仅当 conflict ranks 唯一连续覆盖 `[0,N)` 时启用 ordered，否则保守回退。

## 2. 结构与功能结果

rank 修复后的 fresh SimTop：

```text
generated source     -7.32%
emu text             -9.04%
supernodes           -6.19%
DAG edges           -17.23%
boundary activation -12% 左右
```

10k/50k difftest 完整通过，消除了 write-only recovery 的结构爆炸。

## 3. 首轮 runtime 反常

随机基址 CPU138 old/new/old 中：

```text
instructions  -8.60%
Host cycles   +4.24%
Host time     +4.21%
```

profile 将 38.8% 增量映射到三个 RAT batch，92%..94% samples 落在 1,542 个稀疏 guard `je`；I-cache miss 与 backend stalls 反而改善，表面上指向前端控制流/layout。

## 4. Affine-loop codegen

对至少 16 writers、完整 ordered u8 group 的严格形态生成 affine loops，并以 changed-row bitmap 复用 row-aware activation。SimTop 只将 fp/int/vec RAT 三组生成 4 个 loops，图结构保持不变。

相对 guard 版：

```text
目标 batch source  -21.83%
emu text            -0.098%
cycles              -0.797%
branch misses       -1.422%
```

但相对 NO0286 的随机基址整体仍显示 cycles `+3.85%`。post-profile 中 affine loop 本体仅 6 samples，旧 guard hotspot 已消失；剩余差异是全局 batch 布局，不是 loop 本体。

## 5. 阶段结论

ordered-write/affine-loop 在语义、结构和动态 work 上均正确，不能因当时随机 PIE 基址下的 wall/cycle 结果撤回。后续 fixed-ASLR 重测确认其真实方向为正；本篇保留该历史纠偏链。

## 6. 规则审计与关键数据

记录类型：ordered-write 契约的连续实现/root-cause 总结。单一议题边界是“如何把 RAT 的 pairwise conflict 网络恢复为语义正确、近线性的顺序写入”。rank 修复、功能 gate、runtime 反常与 affine-loop 修复属于同一契约闭环。

所有下列 runtime 样本均为 CPU138、CoreMark `-C 50000`，且 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`：

| Comparison | Baseline host ms | Candidate host ms | Baseline host cycles | Candidate cycles | Candidate instructions delta | Cycles delta |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| NO0286 vs ordered rank-fix | `81,492 / 81,403` | 84,874 | `298,115,248,219 / 298,037,335,452` | 310,713,254,780 | `-8.60%` | `+4.24%` |
| rank-fix vs affine loop | `84,809 / 85,119` | 84,297 | `310,510,395,601 / 311,627,426,114` | 308,588,918,402 | `+0.164%` | `-0.797%` |
| NO0286 vs affine overall | `81,230 / 81,313` | 84,405 | `297,422,782,679 / 297,678,058,907` | 309,005,122,520 | `-8.45%` | `+3.85%` |

这些三轮均为随机 PIE 基址，虽然 A/A spread 只有 `0.026%..0.36%`，跨 binary 的 load address 未受控，故整体 `+3.85%` 后被降级为历史 provisional 结果。fixed-ASLR 同二进制重测在 [TNO0010](./TNO0010_code_layout_aslr_and_fixed_profile_20260713.md) 中得到 cycles `-4.75%`。原始随机基址表见 [NO0297](../grhsim_opt/NO0297_ordered_memory_write_simtop_50k_gate_20260711.md)、[NO0301](../grhsim_opt/NO0301_ordered_memory_write_affine_loop_50k_gate_20260712.md) 与 [NO0302](../grhsim_opt/NO0302_ordered_memory_write_affine_overall_50k_gate_20260712.md)。
