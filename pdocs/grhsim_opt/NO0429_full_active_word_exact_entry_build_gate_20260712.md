# NO0429 Full active-word exact-entry build gate

日期：2026-07-12

## 1. Construction result

按 [NO0428](./NO0428_full_active_word_exact_entry_build_plan_20260712.md) 执行 explicit-link padding 构造，未重编、
复制改写或重新归档任何原 model object。构造 wall time 15.23 秒，exit 0。

显式链接 preflight 先证明：

```text
NO0357 baseline original explicit link: byte-exact
NO0416 candidate original explicit link: byte-exact
candidate with shared NO0357 harness: 117 entry address/size exact
candidate shared-harness .text: native exact
```

因此后续地址变化只来自 response file 中插入的独立 pad objects，不是 harness 编译时刻或 object 顺序变化。

## 2. Input and padding gates

40 个共同 NO0357 harness objects、两侧各 152 个 model objects、两个 archive 和两个原 emu，共 348 项 SHA256
manifest 在构造前后 byte-exact。

candidate 在 `sched_0..65.o` 后各插一个 pad：

```text
pad count=66
pad bytes=674,352
max pad=33,760
non-16-byte pads=0
baseline pads=0
tail pads=0
```

66 个 pad 的 `.text` 都是 alignment=1 的全零内容，size 与文件名/stride plan 一致，无 symbol 或 relocation，且只带
空 `.note.GNU-stack`。正式 link logs 与 readelf stderr 均为空。

## 3. Exact-entry gates

输出各有 117 个同序 sched entry；每侧 symbol key/size 与自身原 emu 一致，地址 117/117 逐项相同：

```text
first compute:0=0x18c310
last commit:116=0x52f26f0
target span=85,353,440 bytes
baseline .text=87,114,910 bytes
candidate .text=87,114,910 bytes
```

全部 116 个相邻 output stride 均等于预先计算的 target stride，不是只检查首尾。

## 4. Outputs

| side | emu SHA256 | file bytes |
| --- | --- | ---: |
| exact baseline | `cad7eca081fb8f9974be8bafdb996991414a65787b4aa16447f32f79acc6ebd4` | 93,707,232 |
| exact candidate | `b342b9e7a6e4d71a479a91f03fa8a39a4c333006bc0145cb05096bacf1b9d1a4` | 93,707,232 |

exact baseline SHA 与原 NO0357 emu 相同，因为 baseline 不需要 padding；candidate 通过 674,352-byte 独立 padding 恢复
相同 entry layout 和总 `.text`。两者都是未 strip 的 x86-64 PIE executable。

输出路径：

```text
build/xs_grhsim_no0428_exact_entry_baseline_20260712/grhsim/grhsim-compile/emu
build/xs_grhsim_no0428_exact_entry_candidate_20260712/grhsim/grhsim-compile/emu
```

## 5. Next gate

结构门禁通过，但尚未运行新 candidate binary。下一步先串行运行 exact baseline/candidate 10k，再运行 50k
CoreMark/NEMU difftest；要求 progress checkpoints、终点和 NO0422/NO0423 一致，且无
`input_fullpass_blocked`。功能全部通过后才进入 exact-entry PMU A/B/A。
