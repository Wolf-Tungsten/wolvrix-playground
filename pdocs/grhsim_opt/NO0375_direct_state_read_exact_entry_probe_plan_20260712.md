# NO0375 Direct state-read exact-entry probe plan

日期：2026-07-12

## 1. 目的

[NO0373](./NO0373_direct_state_read_align4k_runtime_gate_20260712.md) 证明 direct state-read 的相对 cycles 会随
function alignment 从 `+6.263%` 反转到 `-9.084%`，而 instructions 始终约 `-3.465%`。统一 4 KiB 只让
low-12 offset 相同；两版对应 batch 仍有 115/117 个完整入口地址不同，不能量化排除跨函数入口布局后的 direct
机制收益。

本轮构造 paired common slots：保持原 O3 function body、symbol size、relocation、16-byte alignment、archive
member order 和 activity schedule 不变，只在每个 sched object 的目标函数之后增加不可达尾部 padding，使
baseline/direct 同名 object 的 `.text` section 具有共同尺寸。这样累计到任意 batch 前的 `.text` 总长度严格相同，
对应函数在最终两个 PIE emu 中必须具有完全相同的完整入口地址。

## 2. 可行性前置检查

对 NO0300 baseline 与 NO0357 direct 原始 unaligned O3 产物的只读检查已经确认：

- 两个 archives 都有 152 members，名称和顺序逐项一致；
- 35 个 non-sched model objects 的 `.text` sizes 全部相同；
- 40 个 difftest harness objects 的 `.text` sizes 全部相同；唯一 object-byte 不同的 `common.o` 其 `.text`
  bytes SHA256 仍完全一致，差异只在非 alloc metadata；
- 117 个 sched objects 每侧都只有一个 AX `.text` section，目标 `eval_{compute,commit}_batch_*` symbol offset
  都为 0；
- 117 对中 105 对 `.text` size 不同，其余 12 对相同；
- [NO0374](./NO0374_objcopy_text_padding_relocation_correction_20260712.md) 已证明 LLVM objcopy 21.1.5 可扩展
  `.text` 并保持 symbol/relocation dump 零差异；GNU objcopy 2.42 禁止使用。

## 3. common-slot 构造

输入固定为：

```text
baseline objects/archive:
  build/xs_grhsim_no0300_ordered_affine_fresh_20260712/grhsim/grhsim_emit
direct objects/archive:
  build/xs_grhsim_no0357_direct_state_read_20260712/grhsim/grhsim_emit
```

输出使用两个全新目录，不修改输入：

```text
build/xs_grhsim_no0375_exact_entry_baseline_20260712/grhsim
build/xs_grhsim_no0375_exact_entry_direct_20260712/grhsim
```

每对 sched object 的目标 section size 定义为：

```text
target = align_up(max(baseline_text_size, direct_text_size), 16)
```

预计算结果：

| Metric | Baseline | Direct |
| --- | ---: | ---: |
| Original sched `.text` sum | 86,505,728 | 85,434,955 |
| Common target sum | 87,360,912 | 87,360,912 |
| Added tail padding | 855,184 | 1,925,957 |
| Padding / original sched text | 0.989% | 2.254% |
| Objects receiving nonzero padding | 116 | 115 |

复制 objects 时必须使用独立文件而非 hardlink。仅对 117 个 sched copies 使用 LLVM objcopy：dump `.text`，以零字节
扩展到 target，再 `--update-section` 写入新 object；35 个 non-sched objects 保持 byte-identical。两个 archives
按原 152-member manifest 重新构造，不能改变顺序。

## 4. object/archive 硬门禁

对 234 个 padded sched-side objects 逐项要求：

1. `.text size == paired target`，alignment 仍为 16；
2. 原始 `.text` 长度范围内 prefix SHA256 完全一致；新增尾部全部为零且位于 function `st_size` 之外；
3. `nm -S -C` 的 symbol table before/after 完全一致，function offset 仍为 0、size 仍为各自原值；
4. `readelf -r` before/after 完全一致，`.rela.text` count/bytes 不变；
5. 所有非 `.text` sections 的 name/type/size/flags 不变；
6. archive member names/order 精确复现输入，152 个 members 全部存在。

任一项失败即停止，不链接 emu。正式 verifier 和 paired target TSV 保存到 `build/logs/xs_perf/no0375/`。

## 5. 最终链接与 exact-entry 门禁

使用独立 difftest `BUILD_DIR` 链接 baseline/direct emu，model archive 必须比 source 新，避免 generated Makefile
重编并覆盖 padded objects。编译器、harness flags 和链接顺序与原版一致，不使用 4 KiB alignment。

最终 binary 必须满足：

- 各有 117 个 batch symbols（66 compute + 51 commit）；
- 对每个同名 batch，baseline/direct 完整入口 virtual address 逐项相等，`different_address=0`；
- 各自 117 个 function `st_size` 与原 unpadded binary 逐项一致；
- 两边 ELF `.text` section size 相同；
- PIE、Clang version、data/bss 和 model ABI 不变；
- padded slots 之外不接受额外 object/order 差异。

如果最终入口不能全量同址，不能把该 binary 用于性能测试；先定位前缀 section/order 差异。

## 6. 功能门禁

由于本轮直接改写 relocatable objects，baseline/direct 都重新执行：

1. 10k CoreMark/NEMU difftest：终点 `10001/9996/458/0x800027c6`；
2. 50k 串行功能：终点 `50001/49996/73580/0x80001312`；
3. 去掉 `host_ms` 后与 NO0360/NO0361 checkpoints 严格一致；
4. 无 mismatch/assert/abort/fatal/error/`input_fullpass_blocked`。

raw Host time 不进入结论。

## 7. fixed-ASLR runtime 门禁

功能通过后，以 CPU138、NUMA1、`setarch -R` 执行 exact-entry baseline / direct / baseline CoreMark 50k
五事件 A/B/A。quiet gate、功能、PMU 100% 和 baseline cycles spread `<=1%` 要求与 NO0373 相同。

主判定：

- instructions 应继续约 `-3.465%`；若不符，说明 object 构造或执行路径改变；
- 若 exact-entry direct cycles 下降，量化删除 state-read scan 在入口布局隔离后的真实收益；
- 若 cycles 回退，则回退来自函数内部 basic-block/branch layout 或动态访问序列，而不是跨函数入口漂移；
- 本轮仍只代表一个固定地址布局，但比统一 page offset 更严格，不把 padding 方案直接作为默认优化。

## 8. 预定产物

```text
build/logs/xs_perf/no0375/paired_text_targets.tsv
build/logs/xs_perf/no0375/object_padding_verifier.report
build/logs/xs_perf/no0375/{baseline,direct}_archive_members.txt
build/logs/xs_perf/no0375/exact_entry_layout.tsv
build/logs/xs_perf/no0375/{baseline,direct}_link.log
build/logs/xs_perf/no0375/{baseline,direct}_functional_{10k,50k}.log
build/logs/xs_perf/no0375/fixed_exact_{baseline1,direct,baseline2}_{emu.log,perf.csv}
```
