# NO0428 Full active-word exact-entry build plan

日期：2026-07-12

## 1. Objective

[NO0427](./NO0427_full_active_word_native_runtime_gate_20260712.md) 测得 candidate
`instructions -0.717% / cycles +1.877%`，并且 cmask6 density `+1.172%`。按 NO0424 的预声明门槛，本轮构造
117 个 sched function 完整入口同址的隔离 binary，区分删 clear/restore 的真实收益和 native address layout。

比较对象仍为 NO0357 direct baseline 与 NO0416 full-word candidate；不重新编译或改写任何 model object。

## 2. Entry preflight

从两个原 O3 emu 提取同序的 117 个 `eval_compute/commit_batch` symbol：

```text
entries=117
original exact addresses=1/117
first entry compute:0=0x18c310
baseline last commit:116=0x52f26f0
candidate last commit:116=0x524dcc0
```

66 个 compute symbol size 全部在 candidate 中减小，51 个 commit size 全部相同。对每个相邻入口按
`target_stride=max(baseline_stride,candidate_stride)` 计算，结果 baseline stride 在全部 116 个位置都不小于
candidate。因此构造简化为：

| metric | baseline | candidate |
| --- | ---: | ---: |
| inter-entry pad count | 0 | 66 |
| inter-entry pad bytes | 0 | 674,352 |
| max single pad | 0 | 33,760 |
| non-16-byte pad | 0 | 0 |
| tail pad | 0 | 0 |

共同 target span 为 85,353,440 bytes，最后入口保持 baseline 原地址 `0x52f26f0`。candidate 原 `.text`
86,440,558 bytes 加 pad 后正好等于 baseline 原 `.text` 87,114,910 bytes，无需 tail padding。

## 3. Explicit-link construction

1. 从 NO0357 build 提取 40 个 harness objects，并在两侧共同使用；
2. 按各自 `libgrhsim_SimTop.a` member order 显式列出 152 个 model objects；
3. baseline 不插 pad，candidate 在 `sched_0..65.o` 后插入对应独立 pad object；
4. pad object 仅含全零 `.text` 和空 `.note.GNU-stack`，`.text` alignment 必须为 1、无 symbol/relocation；
5. 使用原链接 flags `clang++ @response -lz -lzstd -ldl`；
6. 构造前后核对 348 项输入 SHA256 manifest，不允许修改原 object/archive/emu。

输出：

```text
baseline:
  build/xs_grhsim_no0428_exact_entry_baseline_20260712/grhsim/grhsim-compile/emu
candidate:
  build/xs_grhsim_no0428_exact_entry_candidate_20260712/grhsim/grhsim-compile/emu
```

## 4. Structural gates

- baseline 显式链接必须 byte-exact 复现原 NO0357 emu；
- candidate 在插 pad 前用相同 baseline harness 显式链接时，117 个 entry address/size 和 `.text` 必须与原 candidate
  相同，排除 harness 元数据影响；
- 正式输出各有 117 个同序 entry，自身 symbol size 与原版一致；
- 两侧 117/117 地址逐项相同，首尾为 `0x18c310/0x52f26f0`；
- 两侧 `.text` 均为 87,114,910 bytes；
- 66 个 pad 的 count/sum/max/alignment/content 均满足预检值；
- 链接和 readelf 0 warning/error。

任一门禁失败即停止，不运行仿真。该 binary 只是 layout isolation probe，不作为生产实现提交。

## 5. Follow-up gates

结构通过后，先对两侧运行 10k、50k CoreMark/NEMU difftest，要求 checkpoints 与 NO0422/NO0423 一致且无
`input_fullpass_blocked`。功能通过后再按新文档选择安静 CPU，执行 exact baseline/candidate/baseline 五事件
fixed-ASLR A/B/A；不复用 NO0427 的绝对计数替代现场 baseline。
