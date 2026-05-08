# NO0074 XS GrhSIM vs Verilator MBTB 写入口分叉定位

> 归档编号：`NO0074`。目录顺序见 [`README.md`](./README.md)。

## 1. 目的

延续 [`NO0073`](./NO0073_xs_grhsim_vs_verilator_20k_commit_cycle_alignment_20260507.md) 的结论：

- `grhsim` 在 `20k cycle` bounded run 下提交序列与 `verilator` 前缀一致
- 但从第一处滞后点开始，后续提交周期差持续扩大

本记录只回答一个更具体的问题：

- 从波形出发，沿“少提交”链路逐层回溯
- 找到最早、最决定性的功能分叉点
- 判断它究竟发生在后端、前端取指，还是 BPU/MBTB 的局部训练更新链

## 2. 分析输入

### 2.1 波形与源码

- `verilator` 参考波形：
  - `tmp/grhsim_vs_verilator_fst/xs_ref_ref20k_full_rebuild_20260507.fst`
- `grhsim` 波形：
  - `tmp/grhsim_vs_verilator_fst/xs_wolf_grhsim_20260507_wavefix20k.fst`
- Chisel 源码：
  - `testcase/xiangshan/src/main/scala/xiangshan`

### 2.2 分析方法

- 主要使用 `.codex/skills/fst-roi-discovery`
- 配合 `tools/fst_tools/fst_cycle_trace.py` 做固定 cycle 窗口导出
- 坚持“不要只抓单点，要抓连续窗口”，逐级从结果往上游比

本轮新增的 ROI 解释产物：

- [`../tmp/fst_roi/xs_mbtb_write_entry_ref.ai.md`](../../tmp/fst_roi/xs_mbtb_write_entry_ref.ai.md)
- [`../tmp/fst_roi/xs_mbtb_write_entry_grhsim.ai.md`](../../tmp/fst_roi/xs_mbtb_write_entry_grhsim.ai.md)

## 3. 已排除的大链路

本轮没有停留在单个怀疑点，而是从 retirement 掉队一路向上回溯。当前已经确认下面这些位置不是“最早分叉点”，它们更多只是后果：

- `redirectGen`
- `writeback_5`
- `BJU / BJU2`
- `IssueQueue`
- `NewDispatch`
- `dispatch -> frontend cfVec`
- `IFU / IBuffer`

这些模块上虽然能观察到 ref 与 grhsim 的差异，但继续向上游追之后，都能找到更早的共同祖先分叉。

## 4. 已坐实的前端分叉链

### 4.1 先看到的 IFU ready 分叉

在 `cycle 8703`：

- `FTQ -> IFU req.valid`
  - ref = `1`
  - grhsim = `1`
- `req.ready`
  - ref = `0`
  - grhsim = `1`

这说明差异不是 FTQ 没发请求，而是 IFU 侧是否允许继续取指已经不同。

### 4.2 上推到 ICache / WayLookup / flush

继续上推后确认：

- `mainPipe.io.req.ready` 分叉
- 原因来自 `WayLookup.bpuS3FlushValid`
- 再上游是 `FTQ.flushFromBpu.s3.valid`

在 `cycle 8702`：

- ref: `flushFromBpu.s3.valid = 1`
- grhsim: `flushFromBpu.s3.valid = 0`
- 但 `bits.ftqPtr` 相同

这说明不是 “flush 指向错了”，而是 “flush valid 没起来”。

### 4.3 上推到 BPU stage3

在 `cycle 8702`：

- ref:
  - `s3_valid = 1`
  - `s3_override = 1`
  - `s3_predictionSource = 011` = `MbtbTage`
- grhsim:
  - `s3_valid = 1`
  - `s3_override = 0`
  - `s3_predictionSource = 110` = `Fallthrough`

继续拆后发现，真正更早的分叉不是 `override`，而是：

- ref: `s3_taken = 1`
- grhsim: `s3_taken = 0`

### 4.4 上推到 slot3 condTakenMask

再继续拆到 slot3：

- ref:
  - `s3_firstTakenBranchOH_3 = 1`
  - `s3_firstTakenPosition = 00111`
  - `s3_condTakenMask_3 = 1`
- grhsim:
  - 对应 taken 分支信息都没起来
  - `s3_condTakenMask_3 = 0`

这一步把分叉压到：

- `MBTB slot3` 没有给出 taken branch

### 4.5 确认不是 bank 选错，而是 entry 本身没被写进去

进一步看 MBTB 读出链：

- `alignBanks_0.s2_internalBankMask`
- `setIdx`

两边一致，说明：

- 不是读错 `bank`
- 也不是 `set` 选错

但在 `cycle 8701`：

- ref 的 `alignBanks_0.internalBanks_3.way3` 读出有效 entry
- grhsim 对应 entry 全 0

因此根因继续收敛到：

- ref 曾经把这条 entry 写进去
- grhsim 没有

## 5. 本轮新增结论：最早决定性分叉在 MBTB 写入口

### 5.1 连续窗口

本轮关键对比窗口是：

- ref：
  - [`../../tmp/fst_roi/ref_mbtb_write_entry_8694_8697.csv`](../../tmp/fst_roi/ref_mbtb_write_entry_8694_8697.csv)
- grhsim：
  - [`../../tmp/fst_roi/grhsim_mbtb_write_entry_8694_8697.csv`](../../tmp/fst_roi/grhsim_mbtb_write_entry_8694_8697.csv)

关注链路：

- `alignBanks_0.io_write_req_valid`
- `internalBanks_3.io_writeEntry_req_valid`
- `entryWriteBuffer.io_write_3_valid`
- `entryWriteBuffer.io_read_3_valid`
- `mbtb_sram_entry_align0_bank3_way3.io_w_req_valid`

### 5.2 决定性观察

在 `cycle 8694`：

- ref:
  - `alignBanks_0.io_write_req_valid = 1`
  - `internalBanks_3.io_writeEntry_req_valid = 1`
- grhsim:
  - `alignBanks_0.io_write_req_valid = 1`
  - `internalBanks_3.io_writeEntry_req_valid = 0`

这就是当前已经坐实的最早决定性分叉点。

含义非常明确：

- 两边都收到了 `alignBanks_0` 顶层写请求
- 但只有 ref 把它继续下推成 `internalBanks_3.writeEntry.req.valid`
- grhsim 在这一拍就把训练写入口“断掉了”

### 5.3 后续连锁后果

因为 `cycle 8694` 这拍 `writeEntry.req.valid` 已经分叉，后面链路就自然全部分叉：

- `cycle 8695`
  - ref: `entryWriteBuffer.io_write_3_valid = 1`
  - grhsim: `0`
- `cycle 8696`
  - ref: `entryWriteBuffer.io_read_3_valid = 1`
  - ref: `way3.io_w_req_valid = 1`
  - grhsim: 两者都 `0`

所以可以明确排除：

- 不是 `entryWriteBuffer` 语义错误先发生
- 不是 SRAM 写端口 ready/valid 先发生
- 不是“写了但读坏了”

更准确的说法是：

- grhsim 在 `MainBtbAlignBank -> MainBtbInternalBank` 的 `writeEntry.req.valid` 这一层就没有把该写请求发出来

## 6. 当前根因范围

结合源码，当前根因已经收敛到：

- [`testcase/xiangshan/src/main/scala/xiangshan/frontend/bpu/mbtb/MainBtbAlignBank.scala`](../../testcase/xiangshan/src/main/scala/xiangshan/frontend/bpu/mbtb/MainBtbAlignBank.scala)
- [`testcase/xiangshan/src/main/scala/xiangshan/frontend/bpu/mbtb/MainBtbInternalBank.scala`](../../testcase/xiangshan/src/main/scala/xiangshan/frontend/bpu/mbtb/MainBtbInternalBank.scala)

其中更精确地说，是 `MainBtbAlignBank` 这一句的输入条件：

```scala
b.io.writeEntry.req.valid := t1_fire && t1_entryNeedWrite && t1_internalBankMask(i)
```

因为波形已经证明：

- `t1_fire` 对应的顶层 `io_write_req_valid` 两边同为 `1`
- 但传到 `writeEntry.req.valid` 时 ref=`1`、grhsim=`0`

所以最值得继续追的已不是 `InternalBank` 的 buffer/sram，而是 `AlignBank` 里决定这条 valid 的组合条件：

- `t1_entryNeedWrite`
- `t1_internalBankMask`
- `t1_entryWayMask`
- `t1_hit / t1_hitMask`
- `t1_mispredictInfo`

## 7. 当前结论

截至本记录形成时，可以稳定给出三条结论：

1. `grhsim` 提交偏少的主链已经从后端一路回溯到前端 `BPU -> MBTB`。
2. 当前已坐实的最早决定性功能分叉点是 `cycle 8694` 的：
   - `alignBanks_0.io_write_req_valid` 两边相同，都是 `1`
   - 但 `alignBanks_0.internalBanks_3.io_writeEntry_req_valid`
     - ref = `1`
     - grhsim = `0`
3. 因此当前最小根因位置不再是 `redirect`、`IFU`、`flush`、`entryWriteBuffer` 或 SRAM，而是：
   - `MainBtbAlignBank` 内部决定是否产生 `writeEntry.req.valid` 的训练更新判定逻辑

## 8. 下一步

下一步应继续抓 `cycle 8694` 前后一小段窗口，把 `writeEntry.req.valid` 再向上拆到具体组合条件：

- `t1_entryNeedWrite`
- `t1_internalBankMask`
- `t1_entryWayMask`
- `t1_hit / t1_hitMask`
- `t1_mispredictInfo.valid`
- `t1_meta.map(_.hit(...))`

如果这组信号中能找到“输入一致但某个判定位 first diverge”的位置，就可以把根因从“MBTB 写入口没发出”再压缩到单个 Chisel 条件表达式。
