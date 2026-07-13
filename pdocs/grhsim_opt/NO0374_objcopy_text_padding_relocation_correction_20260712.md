# NO0374 objcopy text-padding relocation correction

日期：2026-07-12

## 1. 背景

[NO0373](./NO0373_direct_state_read_align4k_runtime_gate_20260712.md) 将下一步收敛为 exact-entry probe：对
baseline/direct 同名 sched object 的 `.text` 尾部 padding 到共同尺寸，使对应函数完整入口地址一致，同时保留函数
body、symbol size 和 relocations。

在正式计划和产物构造前，使用 `grhsim_SimTop_sched_33.o` 的两侧副本在 `/tmp` 做工具可行性探针；原 objects、
archives 和 emu 均未修改。

## 2. GNU objcopy 失败

GNU objcopy 2.42 执行：

```text
--dump-section .text=<file>
truncate 到 paired 16-byte-rounded max
--update-section .text=<file>
```

可以把 baseline/direct `.text` 从 `763605/763609` 扩为共同 `763616` bytes，function symbol offset/size 也保持
不变；但输出 object 的 `.rela.text` size 从 `59232` 变成 0，2,468 个 text relocations 全部丢失，只剩
`.rela.eh_frame`。该 object 不可用于链接，GNU probe 明确作废。

## 3. LLVM objcopy 修正

改用与编译器相同 toolchain 的 LLVM objcopy 21.1.5：

```text
/nfs/home/tanghaojin/LLVM-21.1.5-Linux-X64/bin/llvm-objcopy
```

同一输入、目标尺寸和命令语义下：

| Gate | Baseline padded | Direct padded |
| --- | ---: | ---: |
| `.text` section | 763,616 | 763,616 |
| Function symbol offset | 0 | 0 |
| Function symbol size | 763,605 | 763,609 |
| `.rela.text` bytes | 59,232 | 59,232 |
| `readelf -r` before/after diff | 0 lines | 0 lines |
| `nm -S -C` before/after diff | 0 lines | 0 lines |

LLVM objcopy 在扩展 `.text` 时保留全部 relocation 和 symbol metadata，满足 exact-entry probe 的必要条件。

## 4. 结论

正式 object padding 必须固定使用 LLVM objcopy 21.1.5，不得使用系统 GNU objcopy 2.42。每个 padded object 都要
逐项验证：原始 `.text` 前缀 SHA256、symbol table、relocation dump 完全不变，只有 section size 和新增尾部 bytes
允许变化。任一 object 未通过时停止，不构建 archive/emu。

本篇只修正工具选择，没有生成正式模型，也没有运行仿真或性能测试。
