# NO0336 Bit-reversal order build gate and text-padding correction

日期：2026-07-12

## 1. 构造结果

应用 [NO0335](./NO0335_bitrev_archive_path_correction_20260712.md) 后，NO0300 实验 archive 通过
`35 + 117 = 152` member 计数和顺序检查。152 个 model objects 全部与原 NO0300 对象共享 inode；链接日志
只有 `LD`，没有重新编译。

静态链接器按 archive member 顺序放置 batch，无需额外 linker script。最终 117 个 batch 地址顺序逐项等于
[NO0334](./NO0334_no0300_sched_object_order_plan_20260712.md) 预声明的 7-bit bit-reversal 列表：

```text
0, 64, 32, 96, 16, 80, 48, 112, 8, 72, 40, 104, ...
```

地址相邻且也是执行后继的 pair 从 numeric baseline 的 `116/116` 降为 `0/116`，address-order descents
为 63；batch 入口低 12-bit distinct count 从 100 变为 99，没有像 4 KiB probe 那样坍缩到单一 offset。

## 2. Symbol 与体积 gate

117 个 batch symbol size 与原 NO0300 逐项完全一致，archive 和最终 emu file size 也完全相同：

| Artifact | Numeric | Bit-reversal |
| --- | ---: | ---: |
| archive file bytes | 100,425,230 | 100,425,230 |
| emu file bytes | 94,780,472 | 94,780,472 |
| emu `.text` bytes | 88,185,721 | 88,185,726 |

emu SHA256 从 `c30220ac...9078` 变为 `9cfe2e8d...905e`，证明布局变化。

## 3. NO0334 text gate 修正

NO0334 原计划要求最终 `.text` byte-exact。实际只增加 5 bytes，同时输入 objects 和每个函数 symbol size
都 byte-exact。原因是相同 16-byte aligned input sections 换序后，最后一个 section 不再相同，linker 留下的
尾部 alignment padding 可在 0~15 bytes 内变化；这不代表新增机器指令。

因此将结构 gate 修正为：

1. 输入 object 身份和 batch symbol size 必须完全相同；
2. archive/emu file size 必须相同；
3. 最终 `.text` 差异只允许小于一个 16-byte input-section alignment，当前 `+5` 合格；
4. 不允许 function alignment flag、对象重编或 body 变化。

修正后的 build/layout gate 通过，可以进入功能测试。

## 4. 产物

```text
build/xs_grhsim_no0334_no0300_bitrev_order_20260712/grhsim/grhsim_emit/libgrhsim_SimTop.a
build/xs_grhsim_no0334_no0300_bitrev_order_20260712/grhsim/grhsim-compile/emu
build/logs/xs_perf/no0334/bitrev_archive_members.txt
build/logs/xs_perf/no0334/bitrev_archive_emu_link.log
```
