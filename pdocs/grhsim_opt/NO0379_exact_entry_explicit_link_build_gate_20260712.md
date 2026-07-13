# NO0379 Exact-entry explicit-link build gate

日期：2026-07-12

## 1. 构造范围

按 [NO0378](./NO0378_exact_entry_explicit_link_plan_20260712.md) 执行 corrected exact-entry 构造。两侧统一使用 NO0300
的 40 个 harness objects，随后按原 archive member order 显式列出各自 152 个 model objects；没有重编 model、改写
object 或重新打包 archive。

在 `sched_0..115.o` 后按真实相邻入口 stride 插入独立 padding objects，并在 baseline `sched_116.o` 后追加 21-byte
tail。每个 padding object 的 `.text` 均为 alignment=1 的全零内容，无 symbols 或 relocations。

## 2. 输入完整性门禁

构造前后对以下 348 项做完整 SHA256 manifest：40 个共同 harness objects、两侧各 152 个 model objects、两个原
archives 和两个原 emu。before/after manifest byte-exact，原输入没有被修改。

原 archive SHA256 再次核对为：

| Side | SHA256 |
| --- | --- |
| NO0300 | `34b6775530e73441deebb2ff1ae96bc2f49aa5b73681af44ea11dd5d7c601a26` |
| direct | `2e23f7b940b05d618583e6c40be77631401a82bff6e9cc4d43d2f0e2a94dfcd0` |

## 3. Padding 与链接结果

| Metric | NO0300 exact-entry | Direct exact-entry |
| --- | ---: | ---: |
| Harness/model inputs | 40 / 152 | 40 / 152 |
| Inter-entry pad objects | 45 | 53 |
| Inter-entry pad bytes | 855,664 | 1,926,496 |
| Tail pad objects/bytes | 1 / 21 | 0 / 0 |
| Response-file entries | 238 | 245 |
| Link warnings/errors | 0 / 0 | 0 / 0 |
| `readelf` warnings | 0 | 0 |

工具固定为 Clang/LLVM objcopy 21.1.5。99 个 padding objects 均通过 size、alignment=1、无 symbol、全零 `.text`
门禁。

## 4. Exact-entry 结构门禁

输出分别包含 117 个同序 batch entries。每个输出的 symbol key/size 都与其自身原 emu 一致；两侧完整地址 117/117
逐项相同：

| Entry | Address | Baseline size | Direct size |
| --- | --- | ---: | ---: |
| `compute:0` | `0x18c310` | 1,419,424 | 1,389,947 |
| `commit:116` | `0x54c8c50` | 173,993 | 174,014 |

全部 116 个输出相邻 stride 也逐项等于 `max(original_baseline_stride, original_direct_stride)`，不是仅检查首尾。最终
两版 `.text` 均为 `89,041,406` bytes，满足入口地址和 aggregate text 双重对齐。

输出产物：

| Side | emu SHA256 | File bytes |
| --- | --- | ---: |
| NO0300 exact-entry | `d6249d020d019b63abd27b63443c44f9851518613208928f50431c472a190e37` | 95,636,536 |
| Direct exact-entry | `b93b5f3fa2501a83e49eea206b4356522aa816654fd9cc587eec52ddafb3824c` | 95,636,448 |

文件总长仍相差 88 bytes，来自两版真实 unwind/symbol metadata，不影响已经严格相等的 `.text` 和 117 个目标入口；
不通过扩大非代码 sections 来掩盖该差异。

## 5. 结论

NO0378 的最终链接 padding 方法已通过全部输入和结构门禁，且避开了 NO0377 的 object mutation/COMDAT 问题。该
binary 是 layout isolation probe，不是生产优化。当前尚未运行仿真；下一步分别执行 10k、50k 功能门禁，功能通过
后才允许 fixed-ASLR 性能夹测。
