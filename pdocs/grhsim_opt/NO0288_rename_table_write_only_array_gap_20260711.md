# NO0288 RenameTable write-only array recovery gap

日期：2026-07-11

## 1. 背景

[NO0287](./NO0287_commit_state_change_unlikely_50k_gate_20260711.md) 保留 commit changed-path
layout 优化后，本轮继续检查 NO0283 instruction profile 中较大的 compute39。目标是直接对照同 FIR
的 GSim generated C++，而不是继续只从 GrhSIM 单侧热点推断原因。

## 2. compute39 映射结果

compute39 的首个重复 supernode 先动态读取一个 write-port enable bit，随后把同一个地址与
`0..31` 逐项比较。sampled operation `_op_4141272` 可映射到：

```text
cpu...rat$intRat$io_diffWritePorts_411_wen
build/xs_grhsim_event_order_src_20260710/rtl/rtl/RenameTable.sv:4309
```

RTL 是 scalarized priority write：

```systemverilog
else if (io_diffWritePorts_411_wen & io_diffWritePorts_411_addr == 5'h0)
  difftest_table_0 <= io_diffWritePorts_411_data;
```

同一 write port 对每个 table row 各生成一次地址判断。compute39 单文件静态包含：

| item | count |
| --- | ---: |
| `kAnd` comments | `37,358` |
| `grhsim_slice_words<1>` calls | `1,564` |

其 instruction profile 的 `230` samples 中，`or/shrd/movzbl/mov/xor/cmp/and` 为主，与动态
enable bit 提取、row decode 和大型 priority network 一致。

## 3. GSim 直接对照

GSim 没有对每个 scalar row 重复 decode。以 intRat 为例，它先建立局部 next array：

```cpp
difftest_table_next[0] = difftest_table_0;
// ...
difftest_table_next[31] = difftest_table_31;

if (write_411_enable) {
    difftest_table_next[write_411_addr] = write_411_data;
}
```

最后再把 next array 各 row 写回 scalar `$NEXT_*`。同 FIR GSim 中存在三组该结构：

| group | local next array | indexed writes |
| --- | ---: | ---: |
| intRat | `32` | `520` |
| fpRat | `64` | `520` |
| vecRat | `64` | `520` |

对应文件为：

```text
build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/model/SimTop278.cpp
build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/model/SimTop279.cpp
build/xs_gsim_no0255_current_20260710/gsim/gsim-compile/model/SimTop.h
```

scalarized RTL 的三份 RenameTable 实现一共保留 `48,313` 个
`wen && addr == row` 判断；GSim 对应为 `3 x 520 = 1,560` 个动态索引写。两者不是简单的
code layout 差异，而是前者把同一地址 decode 沿 row 维重复展开了约 31 倍。

## 4. 现有 reg-to-mem 为什么漏掉

pre-reg-to-mem IR 中，intRat `difftest_table_0` 的唯一 read port 直接送到独立 difftest 输出：

```text
RegisterReadPort(difftest_table_0)
  -> io_diff_rdata_0
  -> Assign(difftest_rat_xrf_value_0)
```

它不存在 `RegisterReadPort[] -> Concat -> SliceDynamic/SliceArray` 读路径。当前
`discoverIntentAnchors()` 只从这种 concat/slice 读 anchor 发现数组；
`discoverTrueOnlyStorageAnchors()` 也仍要求至少一个 register-read concat。因此三组
`difftest_table` 在 anchor discovery 阶段就完全缺席，后续 strict write matcher 没有机会处理。

日志中没有任何 `intRat$difftest_table` group，也验证了这不是 `priority_guard`、read closure 或
rewrite 阶段的拒绝。

## 5. 下一步约束

下一步增加独立的 write-side true-only discovery，但保持 fail-closed：

1. 只考虑单 register write port；
2. update OR 至少包含 64 个可完整归一化的 priority row guards；
3. 同组每个 guard family 的 address、enable、priority conflict、event 和 mask 必须一致；
4. row 必须连续，允许从 1 开始以覆盖硬连零/不可写 row 0；
5. 所有 register reads 仍必须由 true merge 完整替换；
6. 最终继续复用现有 consolidated-write matcher 校验 data、priority、reset 和完整 write ownership。

该方案预期把 95 个 scalar register 恢复为三组 memory-like state，并把数万 row decode 改回
每个 write source 一次 indexed write。以上是实施目标，只有 synthetic、SimTop stop-after、
10k/50k difftest 和固定 CPU runtime gate 全部通过后才决定是否默认保留。
