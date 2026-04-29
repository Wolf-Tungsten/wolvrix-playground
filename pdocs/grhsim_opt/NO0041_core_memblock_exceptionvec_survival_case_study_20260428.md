# NO0041 `core.memBlock exceptionVec` 在 GrhSIM 中存活的案例分析（2026-04-28）

> 归档编号：`NO0041`。目录顺序见 [`README.md`](./README.md)。

这份记录承接 [`NO0040`](./NO0040_gsim_removed_regsrc_vs_grhsim_post_stats_survival_20260428.md) 中的代表样本检查，聚焦一个更具体的问题：

- `gsim RemoveDeadNodes0` 已删除的 `core.memBlock exceptionVec`，为什么在当前 `grhsim` 的 `build/xs/grhsim/wolvrix_xs_post_stats.json` 里还会存活？
- 它到底是被 output / DPIC / 真实下游消费者保住的，还是只是因为当前 `grhsim` 的保符号策略没有把它删掉？

先给结论：

- 以 `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21` 为代表，这个寄存器在当前 `grhsim` 里继续存活，**不是**因为它被 output / DPIC / `kSystemTask` / 其它下游 op 消费了。
- 对这个精确 case 来说，更直接的原因是：`simplify` 在 `grhsim` pre-sched 流程中默认开启了 `keepDeclaredSymbols=true`，而该寄存器及其读出口都仍是 declared symbol，因此被保护保留下来。
- 但 `exceptionVec` 家族并不是全部都悬空。至少在同一个 `VlSplitConnectLdu_1` 组里，`bit 7 / 15 / 19 / 23` 仍有真实用户；只是 `bit 21` 这个代表 case 本人没有。

## 1. 代表样本

这里固定分析 `NO0040` 中已经命中的这一项：

- `gsim` 删除样本：
  - `cpu$l_soc$core_with_l2$core$memBlock$inner$VlSplitConnectLdu_1$data$$uop$$exceptionVec_21`
- `grhsim` 对应寄存器：
  - `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`

在 `grhsim post-stats` 中，可以直接看到三件事：

1. `kRegister` 仍存在：
   - `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`
2. `kRegisterReadPort` 仍存在，并导出 value：
   - `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$io_out_bits_uop_exceptionVec_21`
3. `kRegisterWritePort` 仍存在：
   - `regSymbol = cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`

原始证据来自：

- [`../../build/xs/grhsim/wolvrix_xs_post_stats.json`](../../build/xs/grhsim/wolvrix_xs_post_stats.json)

其中对应行可直接搜到：

- `1017743`：寄存器 symbol 名出现在 symbol 列表中
- `11352766`：`kRegister`
- `11352767`：`kRegisterReadPort`
- `11352873`：`kRegisterWritePort`

## 2. 为什么说它不是被真实消费者保住的

关键证据是 read-port 产出的 value：

- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$io_out_bits_uop_exceptionVec_21`

在 `post-stats` 中这项 value 的记录是：

- `def = _op_10265128`
- `users = []`
- `out = false`
- `inout = false`

对应位置：

- `1017685`：该 value 名出现在 symbol 列表中
- `4987158`：该 value 的完整记录

这几个字段合起来说明：

- 它不是 output port value。
- 它没有任何下游用户。
- 因而它不是被普通组合逻辑消费保住的。

再看 exact symbol 的出现次数，也支持同样结论：

- `io_out_bits_uop_exceptionVec_21` 在整份 JSON 中只出现 `3` 次：
  - symbol 列表
  - value 记录
  - `kRegisterReadPort.out`
- `data_uop_exceptionVec_21` 只出现 `4` 次：
  - symbol 列表
  - `kRegister`
  - `kRegisterReadPort.attrs.regSymbol`
  - `kRegisterWritePort.attrs.regSymbol`

如果它真的还接到了 output / DPIC / system task / 其它 assign 链上，通常不会只有这几次出现。

## 3. 真正让它留下来的原因

当前 `grhsim` 生成脚本在 pre-sched pipeline 中会这样调用 `simplify`：

- [`../../scripts/wolvrix_xs_grhsim.py`](../../scripts/wolvrix_xs_grhsim.py)
  - `186`：`simplify_keep_declared_symbols = env_flag(..., default=True)`
  - `285-286`：如果 pass 是 `simplify`，则传入 `keep_declared_symbols = simplify_keep_declared_symbols`

也就是说，当前默认配置就是：

- `keepDeclaredSymbols = true`

而现有 `dead-code-elim` 文档明确写了：

- [`../../wolvrix/docs/transform/dead-code-elim.md`](../../wolvrix/docs/transform/dead-code-elim.md)
  - 死代码判定要求“结果未被使用、非端口值、非声明符号”
  - 启用声明符号保护时，声明符号不会被删

`simplify` 规划文档也重复了这一点：

- [`../draft/simplify-pass-plan.md`](../draft/simplify-pass-plan.md)
  - `82-85`：`keepDeclaredSymbols()` 打开时，声明符号对应的 value 不允许被删除或替换为无名临时值

因此，这个 case 的更合理解释是：

- `bit 21` 对应的读出口虽然已经没有用户；
- 但它仍然带着稳定 symbol，且当前 `simplify` 默认保 declared symbol；
- 所以它没有被当前 `grhsim` 的 DCE / simplify 清掉。

## 4. 这个结论只针对 `bit 21`，不代表整个 `exceptionVec` 家族都没有消费者

同一个 `VlSplitConnectLdu_1` 组里，`exceptionVec` 不同 bit 的命运已经分化了。

在 `post-stats` 里可以看到：

- `bit 7`：`users = [{"op": "_op_10276353", "idx": 0}]`
- `bit 15`：`users = [{"op": "_op_10276352", "idx": 0}]`
- `bit 19`：`users = [{"op": "_op_10276351", "idx": 0}]`
- `bit 23`：`users = [{"op": "_op_10276350", "idx": 0}]`
- `bit 13`：`users = []`
- `bit 21`：`users = []`

对应 consumer op 是简单的 `kAssign`：

- `_op_10276353`：`io_out_bits_uop_exceptionVec_7 -> _inner_VlSplitConnectLdu_1_io_out_bits_uop_exceptionVec_7`
- `_op_10276352`：`io_out_bits_uop_exceptionVec_15 -> _inner_VlSplitConnectLdu_1_io_out_bits_uop_exceptionVec_15`
- `_op_10276351`：`io_out_bits_uop_exceptionVec_19 -> _inner_VlSplitConnectLdu_1_io_out_bits_uop_exceptionVec_19`
- `_op_10276350`：`io_out_bits_uop_exceptionVec_23 -> _inner_VlSplitConnectLdu_1_io_out_bits_uop_exceptionVec_23`

这说明：

- `exceptionVec` 家族内部确实已经出现“部分 bit 仍活、部分 bit 已悬空”的状态。
- 所以不能简单说“整个 `exceptionVec` 都没有真实用途”。
- 但至少 `bit 21` 这个代表样本，不是靠真实消费活下来的。

## 5. 再给一个“家族里确实有人被消费”的对照样本

例如这条 `exceptionVec` 写回链就有真实用户：

- `cpu$l_soc$core_with_l2$core$_memBlock_io_mem_to_ooo_intWriteback_4_0_bits_exceptionVec_3`
  - `def = _op_10286584`
  - `users = [{"op": "_op_6639752", "idx": 0}]`
- `_op_6639752`
  - 把它赋给 `cpu$l_soc$core_with_l2$core$backend$inner_intRegion$intWBDataPath$io_toCtrlBlock_writeback_13_bits_exceptionVec_3`
- 该 backend value 还有后续用户：
  - `users = [{"op": "_op_6641840", "idx": 0}]`

这条对照路径说明：

- 在 `grhsim` 里，`exceptionVec` 家族并非完全不被使用；
- 只是“家族里有真实消费”这件事，不能拿来解释 `data_uop_exceptionVec_21` 为什么仍然存在。

## 6. 结论

对 `core.memBlock exceptionVec` 这个案例，当前最准确的说法应该是：

- `NO0040` 里命中的代表寄存器 `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`，在 `grhsim` 中仍存活，**主要不是因为 output / DPIC / system task / 内部逻辑消费**。
- 对这个精确 bit 而言，它的 read-port value 已经 `users=[]`，并且 `out=false`。
- 它之所以没被删，更像是因为当前 `grhsim` 的 `simplify` 默认开启了 `keepDeclaredSymbols=true`，把 declared symbol 保护了下来。
- 但这不等于整个 `exceptionVec` 家族都没有真实消费者；家族中的其它 bit 和其它路径仍然存在真实下游使用。
