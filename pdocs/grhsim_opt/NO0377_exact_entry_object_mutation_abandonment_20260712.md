# NO0377 Exact-entry object mutation abandonment

日期：2026-07-12

## 1. 第二次正式构造停止点

按 [NO0376](./NO0376_relocation_verifier_file_offset_correction_20260712.md) 修正 relocation verifier 后，从原始
NO0300/direct objects 的干净副本重新执行 [NO0375](./NO0375_direct_state_read_exact_entry_probe_plan_20260712.md)。构造在
baseline `grhsim_SimTop_sched_80.o` 停止；LLVM objcopy 21.1.5 扩展 `.text` 后，把 `.rela.text` 的 `sh_info`
从合法 section index `2` 改成越界值 `1871286784`。`readelf` 明确报告：

```text
Section 3 has an out of range sh_info value of 1871286784
Info field (1871286784) should index a relocatable section
```

对原始 sched80 object 独立重复三次相同操作，得到三个不同的非法值：

```text
948310288
3892973840
241197328
```

这不是 verifier 的格式化差异，而是输出 ELF metadata 的非确定性损坏。NO0374 在 sched33 上通过只能证明单点工具
探针，不能支持 234 个 objects 的全量改写。

失败发生时尚未重新打包 archive，也没有链接新 emu 或运行仿真。partial 目录中的 archive 仍是 `cp -al` 创建的原
archive hard link；原始输入 SHA256 保持不变：

| Input | SHA256 |
| --- | --- |
| NO0300 `libgrhsim_SimTop.a` | `34b6775530e73441deebb2ff1ae96bc2f49aa5b73681af44ea11dd5d7c601a26` |
| direct `libgrhsim_SimTop.a` | `2e23f7b940b05d618583e6c40be77631401a82bff6e9cc4d43d2f0e2a94dfcd0` |

## 2. `ld.lld -r` 替代方案也不满足隔离要求

另一个探针尝试将原 object 与独立 `.text` padding object 通过 `ld.lld -r` 合并。简单 sched80 object 的入口
offset、size 和原始 body prefix 可以保持，但复杂 sched0 object 会被 relocatable link 重新规范化：

| Gate | Original sched0 | `ld.lld -r` output |
| --- | ---: | ---: |
| Entry offset | 0 | 0 |
| Entry size | 1,419,424 | 1,419,424 |
| Executable sections | 15 | 15 |
| `.rodata.cst16` bytes | 1,712 | 1,696 |
| `.LCPI*` symbols | 107 | 107, values reordered |
| Full symbol dump | reference | different |

`SHF_MERGE` constant folding和局部 `.LCPI*` 重排会改变 object 本身，不再是只增加不可执行语义的尾部 padding；因此
`ld.lld -r` 也不能用于 clean layout probe。

## 3. NO0375 的 section 结构前提不成立

NO0375 的 precheck 只匹配带空格的 `AX` flag，漏掉了 `AXG` COMDAT sections。重新按 `AX` 或 `AXG` 统计 117 个
sched objects：

| Side | Min executable sections/object | Max | Total |
| --- | ---: | ---: | ---: |
| NO0300 baseline | 1 | 37 | 1,267 |
| direct | 1 | 39 | 1,261 |

因此“每个 sched object 只有一个 `.text` 可执行 section”是 false positive。仅把两侧主 `.text` 扩到共同长度，无法
证明最终链接中 COMDAT/helper sections 的选择、对齐和累计位置也一致。

## 4. 结论与纠正方向

exact-entry 实验停止所有原 sched object 改写，也不再生成 padded archive。后续只把原始 objects 直接传给最终
linker，并在相邻 sched objects 之间插入独立、纯零、alignment=1 的 `.text` padding objects。padding 尺寸从两个
原始 emu 的真实相邻入口跨度计算，而不是从单个 object 的主 `.text` 尺寸推断。

该方法让原始 model/harness objects byte-exact 不变，也把 LLVM objcopy 的使用限制在新建 padding object 上。正式
构造和 gate 由下一篇独立计划记录。
