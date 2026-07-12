# NO0376 Relocation verifier file-offset correction

日期：2026-07-12

## 1. 首次正式构造停止点

执行 [NO0375](./NO0375_direct_state_read_exact_entry_probe_plan_20260712.md) 的首次 paired archive 构造时，脚本在
第一对 `grhsim_SimTop_sched_0.o` 的 direct relocation gate 停止。此时只修改了新 build 目录中的 object copies，
尚未构造新 archive、链接 emu 或运行仿真；两个原始 archive SHA256 复核不变。

baseline 该 object 不需要 padding，全部门禁通过。direct `.text` 从 `1,389,947` 扩为 paired target
`1,419,424` bytes 后，prefix、零尾部、symbol table 和 section metadata 均通过，但旧 verifier 对
`readelf -r` 全文本做 SHA256，报告不一致。

## 2. 根因

diff 证明所有 relocation entries 的 offset、Info、Type、symbol value/name 和 addend 完全相同；变化只出现在每个
relocation section 的显示标题：

```text
before: Relocation section '.rela.text' at offset 0x1581a0 contains 592 entries
after:  Relocation section '.rela.text' at offset 0x15f4c0 contains 592 entries
```

`.text` 增长会移动后续 sections 在 relocatable ELF 文件中的物理 file offset。`readelf -r` 把该 file offset 写入
标题，因此全文 hash 变化不代表 relocation 语义或内容变化。

进一步直接 dump `.rela.text` 得到相同 SHA256：

```text
35ba6c52cb520b484fcc84fa12d779574d7965d50d5463891ffacf24bc5ca85c
```

raw symbol table dump 也无差异。旧门禁把允许变化的物理 section offset 混入 relocation 内容比较，属于 verifier
false negative。

## 3. 修正

正式 verifier 改为：

1. 用 LLVM readelf JSON 列出全部 `SHT_RELA` sections，名称集合必须一致；
2. 用 LLVM objcopy 分别 dump 每个 relocation section 的原始 bytes；
3. 按 section name 连接 SHA256，整份 fingerprint before/after 必须相同；
4. 继续用 canonical section metadata 检查 relocation section 的 type、size、flags、link、info、alignment 和
   entry size，只排除允许变化的 file offset；
5. 不再比较包含物理 file offset 标题的 `readelf -r` 全文本。

该门禁比格式化文本 hash 更直接，仍要求 relocation raw contents byte-exact。首次 partial copies 在复核原 archive
SHA 后删除，随后从干净目录全量重跑；不得从已修改 object 继续 resume。
