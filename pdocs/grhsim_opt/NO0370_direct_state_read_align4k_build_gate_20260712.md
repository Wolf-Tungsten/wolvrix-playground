# NO0370 Direct state-read 4 KiB alignment build gate

日期：2026-07-12

## 1. 构建口径

按 [NO0368](./NO0368_direct_state_read_align4k_probe_plan_20260712.md)，hardlink-copy NO0357 direct generated
model 到独立目录，先在副本中清除全部旧 `.o/.a/.pch`，再使用：

```text
CXX=clang++ AR=ar ARFLAGS=rv
CXXFLAGS=-std=c++20 -O3 -falign-functions=4096
model build slots=16
```

构建开始时全机 load 为 `3.82/5.54/5.70`（384 CPUs），可用内存约 945 GiB。157 项 source manifest
（152 `.cpp`、2 `.hpp`、Makefile 和 2 个 JSON）在复制前、clean 后、model build 后逐项 SHA256 相同；代表源码
仍与 NO0357 共享 inode，原目录没有被修改。

model build 完成 153 条 Clang commands，生成 152 个 objects 和完整 archive，日志没有 warning/error。随后使用
独立 difftest `BUILD_DIR` 编译 40 个 harness objects 并完成一次最终链接，同样没有 warning/error。

## 2. object 与最终入口门禁

[NO0369](./NO0369_readelf_section_alignment_parser_correction_20260712.md) 修正首次 `readelf` verifier 的字段
误读后，全量结果为：

```text
sched objects       117
bad .text alignment 0
bad compiler        0
```

117 个 objects 的 `.text` alignment 都是 4096，`.comment` 都是 Clang 21.1.5。最终 emu 的 exact-symbol 结果：

| Model | Symbols | Compute | Commit | Non-page-aligned | Distinct low-12 offsets |
| --- | ---: | ---: | ---: | ---: | ---: |
| NO0300 aligned baseline | 117 | 66 | 51 | 0 | 1 |
| direct unaligned | 117 | 66 | 51 | 117 | 90 |
| direct aligned | 117 | 66 | 51 | 0 | 1 |

direct aligned 与 unaligned 的 117 个 symbol sizes 逐项一致，无 missing/mismatch；两边 batch body size 总和均为
`85,434,955` bytes。NO0300 original/aligned 的 source manifests 也逐项一致，且两版 batch body size 总和均为
`86,505,728` bytes，确认复用的 baseline 没有版本错配。

## 3. 体积与 metric 口径

| Metric | Direct unaligned | Direct aligned | Delta |
| --- | ---: | ---: | ---: |
| ELF `.text` section | 87,114,910 | 88,778,686 | +1,663,776 (+1.910%) |
| GNU `size` aggregate text | 93,532,652 | 95,196,428 | +1,663,776 (+1.779%) |
| emu file bytes | 93,707,232 | 95,374,304 | +1,667,072 (+1.779%) |
| model archive bytes | 99,341,410 | 104,634,706 | +5,293,296 (+5.328%) |

检查中一度发现 NO0331 文档中的 NO0300 `.text=89,843,625` 与 GNU `size` aggregate text `96,261,503`
不同。前者是单一 ELF `.text` section，后者还包含其他代码/只读 sections；原版也存在同样口径差异。源码 manifest、
symbol count 和 117 项 body sizes 均一致，因此不是 baseline 版本或编译 flags 错配。

最终 direct aligned emu 仍是未 strip 的 x86-64 PIE executable：

```text
SHA256 fd5e5af6296580bfd250178add7a49af3743800ac57800fabc7417cbbce76f2f
```

## 4. 结论与下一步

NO0368 build/layout 门禁通过：唯一实验变量是 direct model function alignment/padding，generated source 和函数内部
symbol size 未变，NO0300/direct 两边的 117 个入口都归一到相同 page offset。下一步先运行 direct aligned 10k，
再串行运行 50k CoreMark/NEMU 功能门禁；两者都通过后才进入 fixed-ASLR aligned A/B/A 性能测试。

## 5. 产物

```text
build/xs_grhsim_no0368_direct_align4k_20260712/grhsim/grhsim_emit/libgrhsim_SimTop.a
build/xs_grhsim_no0368_direct_align4k_20260712/grhsim/grhsim-compile/emu
build/logs/xs_perf/no0368/direct_align4k_model_build.log
build/logs/xs_perf/no0368/direct_align4k_emu_link.log
build/logs/xs_perf/no0368/direct_align4k_layout.tsv
build/logs/xs_perf/no0368/{baseline_align4k,direct_unaligned,direct_align4k}_batch_symbols.tsv
build/logs/xs_perf/no0368/*_source*.manifest
```
