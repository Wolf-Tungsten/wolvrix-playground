# NO0460 Storage-aware bit assumption negative gate

日期：2026-07-13

## 1. Classification gate

按 [NO0459](./NO0459_storage_aware_bit_assumption_probe_plan_20260713.md)，对 NO0457 的 66 个 compute sources
逐文件解析 `grhsim_assume_bit_u8` 参数。分类器使用平衡括号和 local declaration type，不用固定长度 regex；v2 结果：

```text
files=66
calls=2,080,384
explained=2,080,384
explained_pct=100.000000
unresolved=0
wall=29.77 s
maximum RSS=97,692 KiB
```

主要类别：

| category | calls | share |
| --- | ---: | ---: |
| value bool slot byte | 875,811 | 42.099% |
| nested candidate byte expression | 475,315 | 22.847% |
| packed state logic byte | 244,269 | 11.742% |
| comparison expression | 171,106 | 8.225% |
| C++ bool local | 83,177 | 3.998% |
| candidate byte local | 76,156 | 3.661% |
| not/masked expression | 53,215 | 2.558% |
| masked/integer expression | 48,187 | 2.316% |
| mux expression | 24,634 | 1.184% |
| bool helper result | 15,416 | 0.741% |

`value_bool_slots_` 与 state byte 合计 53.84%，二者都是 raw byte storage，不能删 assumption。最保守且可证明冗余的
nested candidate、candidate-byte local、bool local、bool helper 和 explicit bool 共 652,740 calls（31.376%）；comparison、
masked 与 mux 暂不计入可删集合。

## 2. Generated-copy refinement

为避免修改 emitter 和再次 full fresh emit，复制 NO0458 的 batch `0/1/29/32/43` source，仅删除上述可证明冗余
helper 的调用边界，保留参数、byte result、语句顺序和所有 storage/comparison assumption。五个副本实际删除：

```text
total calls removed:             36,646
nested candidate byte expr:      22,627
C++ bool local:                   8,642
candidate byte local:             4,467
bool helper result:                 700
explicit bool expr:                 210
```

所有 transformed sources 使用 NO0457 candidate 的同一 PCH 和 `clang++ -std=c++20 -O3` 编译，5/5 exit 0。

## 3. Machine result

| metric | NO0357 baseline | broad candidate | storage-aware copy |
| --- | ---: | ---: | ---: |
| `.text` bytes | 6,502,780 | 6,236,609 | 6,264,410 |
| instructions | 1,305,853 | 1,236,682 | 1,242,033 |
| memory-form | 591,887 | 594,540 | 594,792 |
| jumps | 38,929 | 40,796 | 41,379 |
| calls | 1,108 | 1,108 | 1,108 |

storage-aware copy 相对 baseline：

```text
.text:        -238,370 (-3.666%)
instructions:  -63,820 (-4.887%)
memory-form:    +2,905 (+0.491%)
jumps:          +2,450 (+6.294%)
```

它相对 broad candidate 还增加 `.text +27,801`、instructions `+5,351`、memory-form `+252`、jumps `+583`。
冗余 helper 的 compiler assumptions 确实参与优化，但删除后没有回收 jump/memory 回退，反而进一步恶化；因此根因不是
helper 未内联或单纯 source 膨胀，而是大范围 byte-result 改写改变了 Clang 的全局 branch/code formation。

## 4. Decision

storage-aware refinement 仍违反 NO0459 的 aggregate memory/jump 门槛，且 batch 0/1 的 jump 回退未消失。按预声明
stop condition，停止整个 one-bit byte emit 方向：

- 不修改 emitter refinement；
- 不再 fresh emit；
- 不做 full build、SimTop 功能或 runtime；
- `one_bit_bitwise_bytes` 保持默认关闭，仅保留已提交的实验开关与 fixture；
- 不继续按 57/12 samples 做低于 direct 1% 的局部 allowlist。

下一主线应回到 corrected global compute profile，从 exact payload 中选择新的、单类覆盖 direct `>=1%` 且不依赖全局
C++ type perturbation 的候选。

产物：

```text
build/logs/xs_perf/no0459/analyze_assume_args.py
build/logs/xs_perf/no0459/{category_summary,batch_summary}.tsv
build/logs/xs_perf/no0459/analysis_summary.txt
build/logs/xs_perf/no0459/transform_redundant_assumes.py
build/logs/xs_perf/no0459/storage_aware_sources/
build/logs/xs_perf/no0459/storage_aware_sched_{0,1,29,32,43}.{o,log,time}
```
