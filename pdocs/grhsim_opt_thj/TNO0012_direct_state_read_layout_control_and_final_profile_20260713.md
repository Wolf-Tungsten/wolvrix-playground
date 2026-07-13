# TNO0012 Direct state-read layout control and final profile

记录日期：2026-07-13

来源范围：`NO0368..NO0388`，原始记录见 [NO0368](../grhsim_opt/NO0368_direct_state_read_align4k_probe_plan_20260712.md) 至 [NO0388](../grhsim_opt/NO0388_direct_state_read_instruction_profile_gate_20260712.md)。

状态：入口同址后 direct state-read 的净收益闭合为约 `1.7% cycles`；native 正负方向主要由布局决定。

## 1. 4 KiB alignment 证据

117 个 sched 入口全部页对齐且 symbol size 不变，10k/50k 功能一致。aligned A/B/A 中：

```text
instructions  -3.465%
cycles        -9.084%
cmask6 density -4.503%
```

但 alignment 同时使 baseline cycles `+7.843%`、direct `-7.732%`，所以统一页对齐不是中性控制，只能证明 native layout 主导方向。

## 2. Exact-entry 构造方法

直接用 GNU/LLVM objcopy 修改 object `.text` 会丢 relocation 或随机损坏 `sh_info`；`ld.lld -r` 也会合并/重排 section。最终方法是：

1. 保留原始 O3 objects；
2. 使用显式最终链接；
3. 在相邻 sched objects 间插入 alignment=1 的独立 padding objects；
4. 逐项验证 input SHA、symbol、relocation 和入口地址；
5. 使两版 117 个完整入口同址且 `.text` 同长。

构造后两版入口范围相同，`.text` 均为 89,041,406 bytes；10k/50k checkpoints 与 baseline byte-exact。

## 3. Exact-entry runtime

CPU188 fixed-ASLR A/B/A baseline spread `0.641%`：

```text
instructions  -3.465%
cycles        -1.733%
cmask6 density +0.465%
```

理论删指令收益约实现 50.017%。对照 native `+6.263%` 和 4 KiB `-9.084%`，同址结果给出 direct 机制更可信的净收益：约 `1.7% cycles`。

## 4. Instruction profile closure

direct profile 6,675 samples、0 lost，compute 占净减少样本 97.07%；compute8 单独 `255 -> 44`，覆盖总收益 88.28%。这闭合了 timer/logEndpoint state-read 物化根因。

direct 仍约为 GSim `2.084x` instructions；关闭的只是 instruction excess 的 6.455%。剩余约 69.66% excess 仍在 compute，top compute1/62 指向通用 materialized slot/ref 搬运。

## 5. 决策

- direct forwarding 是正向机制候选，但必须在 layout-controlled 口径评价；
- native binary 的单次正负结果不能代表机制方向；
- 后续先审计 scalar slot repeated-load 的真实 O3 realization，再决定是否扩展 direct/local forwarding。

## 6. 规则审计与关键数据

记录类型：direct state-read 的 layout-controlled root-cause 更新。单一议题边界是“在对应 sched 入口同址后，direct forwarding 的固有 runtime 方向与收益是多少”。4 KiB probe 证明 layout 主导方向，exact-entry 才给出净机制值。

所有正式轮均完成 guest/cycleCnt/instr/PC=`50001/49996/73580/0x80001312`，无 `input_fullpass_blocked`，五事件 `100%` scheduled：

| Layout | Baseline cycles spread | Instructions delta | Host cycles delta | cmask6 density delta | 解释 |
| --- | ---: | ---: | ---: | ---: | --- |
| native | `0.515%` | `-3.466%` | `+6.263%` | `+5.839%` | 入口与函数体均漂移 |
| 4 KiB aligned | `0.291%` | `-3.465%` | `-9.084%` | `-4.503%` | alignment 自身改变两侧布局 |
| exact-entry | `0.641%` | `-3.465%` | `-1.733%` | `+0.465%` | 117 个入口逐项同址 |

Exact-entry CPU188 A/B/A 原始主计数：

| Run | Host ms | Host cycles | Instructions |
| --- | ---: | ---: | ---: |
| baseline1 | 83,678 | 306,232,601,819 | 172,879,276,228 |
| direct | 82,455 | 301,892,311,894 | 166,888,327,986 |
| baseline2 | 84,180 | 308,201,931,010 | 172,879,276,383 |

两版 `.text` 同为 `89,041,406` bytes，117 个 sched entry 地址一致；direct 实际节省 `5,324,954,521` cycles，实现按 baseline CPI 估算删指令收益的 `50.017%`。数据见 [NO0373](../grhsim_opt/NO0373_direct_state_read_align4k_runtime_gate_20260712.md)、[NO0379](../grhsim_opt/NO0379_exact_entry_explicit_link_build_gate_20260712.md) 与 [NO0386](../grhsim_opt/NO0386_exact_entry_fixed_aslr_runtime_gate_20260712.md)。
