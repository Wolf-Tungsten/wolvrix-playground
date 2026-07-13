# NO0458 SimTop one-bit AND/OR representative static gate

日期：2026-07-13

## 1. Fresh emit completion

按 [NO0457](./NO0457_simtop_one_bit_and_or_static_gate_plan_20260713.md)，从 NO0357 相同 pre-reg-to-mem
checkpoint fresh emit，只新增：

```text
WOLVRIX_GRHSIM_ONE_BIT_BITWISE_BYTES=1
```

editable package 已重建，实际加载 `.venv` 中的 `libwolvrix-lib.so`，其 strings 同时包含 option 和 helper。
fresh flow exit 0：

```text
read checkpoint:     45.061 s
reg-to-mem:         154.792 s
activity schedule:  126.274 s
C++ emit:             61.304 s
flow total:          387.436 s
wall:                   6:30.71
maximum RSS:       29,128,324 KiB
swap:                         0
```

日志与输出：

```text
build/logs/xs/xs_wolf_grhsim_emit_no0457_one_bit_and_or_20260713.log
build/xs_grhsim_no0457_one_bit_and_or_20260713/grhsim/grhsim_emit
```

## 2. Structural identity

schedule stats SHA256 与 NO0357 相同：

```text
e3056375a7d3ae06061d95becfa2200bd9d31f97c66bda71bdb332fcab2dfe77
```

核心计数精确复现：

```text
supernodes=63,726 compute=63,241 commit=485
dag_edges=528,622 boundary_values=1,000,463
boundary_activation_edges=1,983,923
direct reads/canonical/aliases=75,830/40,108/35,722
direct groups/source_groups=40,108/40,108
```

generated source 对照为：

- 66/66 compute sched files 变化；
- 51/51 commit sched files byte-exact；
- 37 个其他 `.cpp/.hpp/Makefile` byte-exact；
- 仅 runtime header 增加 12 行 `grhsim_assume_bit_u8()` helper。

NO0457 原计划中的“变化文本只位于 kAnd/kOr block”需勘正：非物化 bitwise value 会内联到 consumer expression，
所以 helper 文本可以出现在 Add、Mux、Not 等 consumer block 中，但定义来源仍是 width-1 AND/OR。不能用当前 comment
scope 作为 def ownership；后续必须沿 expression def-use 连接。

## 3. Source expansion

开关覆盖 current SimTop 所有满足条件的 width-1 AND/OR，而不只覆盖 profile 中的 69 个 samples：

```text
helper name occurrences: 2,080,385
actual call sites:        2,080,384
files containing helper: 67 = runtime + 66 compute
```

| metric | NO0357 | candidate | delta |
| --- | ---: | ---: | ---: |
| generated source bytes | 1,357,268,699 | 1,456,910,442 | `+99,641,743 (+7.341%)` |
| generated source lines | 13,684,550 | 13,719,317 | `+34,767 (+0.254%)` |

bytes 大幅增加主要来自每个 operand 的重复 helper/cast 文本，不是 schedule 或 operation 增长。

## 4. Representative O3 objects

使用两侧各自的 production `clang++ -std=c++20 -O3` PCH 编译 batch `0/1/29/32/43`。所有 objects exit 0，
helper 完全内联；五个 objects 的 call 总数均为 1,108。

| batch | text baseline/candidate | instructions baseline/candidate | memory-form baseline/candidate | jumps baseline/candidate |
| --- | ---: | ---: | ---: | ---: |
| 0 | 1,389,947 / 1,380,495 | 276,912 / 269,761 | 141,595 / 143,486 | 4,127 / 4,972 |
| 1 | 1,751,129 / 1,726,152 | 339,711 / 330,728 | 177,651 / 179,051 | 13,185 / 14,161 |
| 29 | 1,343,904 / 1,259,288 | 271,921 / 251,137 | 115,885 / 111,397 | 7,742 / 7,864 |
| 32 | 957,853 / 874,880 | 199,098 / 177,216 | 77,185 / 78,050 | 6,531 / 6,360 |
| 43 | 1,059,947 / 995,794 | 218,211 / 207,840 | 79,571 / 82,556 | 7,344 / 7,439 |
| aggregate | 6,502,780 / 6,236,609 | 1,305,853 / 1,236,682 | 591,887 / 594,540 | 38,929 / 40,796 |

aggregate delta：

```text
.text:        -266,171 (-4.093%)
instructions:  -69,171 (-5.297%)
memory-form:    +2,653 (+0.448%)
jumps:          +1,867 (+4.796%)
```

跳转增长不是 call 或未内联 helper：mnemonic 对照中 `jne +1,362`、`je +295`、`jmp +223`，其余净变化很小。
四个 batch 的 memory-form 增加，四个 batch 的 jumps 增加；不能用 batch 29/32 的 text/instruction 收益掩盖。

## 5. Decision

当前 broad candidate 虽然显著减少静态 text 和 instructions，但违反 NO0457 预声明的 aggregate memory/branch
不得增加门槛，尤其 jumps 增加 `4.796%`。因此停止该 source shape，不做 full build、SimTop 功能回归或 runtime；
开关继续默认关闭。

下一轮只能先做更窄的 codegen probe：区分 compiler 已知为 bool 的 operand 与 packed raw state byte，只对后者使用
`grhsim_assume_bit_u8`，同时保持 byte result。目标是保留 normalization 删除，避免 208 万个无必要 assumption 改变
全局 branch formation。该 refinement 仍须先过同一五 batch aggregate gate，不能直接运行 SimTop。
