# NO0042 GrhSIM `keepDeclaredSymbols` 开关 AB 对照（2026-04-28）

> 归档编号：`NO0042`。目录顺序见 [`README.md`](./README.md)。

这份记录直接回答上一轮追问：

- `scripts/wolvrix_xs_grhsim.py` 里到底有没有 `keepDeclaredSymbols=false` 的入口？
- 如果有，把它关掉之后，`core.memBlock exceptionVec` 这类此前被怀疑“只是 declared symbol 保护着没删”的状态，会不会真的消失？

先给结论：

- 脚本侧开关是**存在且有效**的，不是摆设。
- 环境变量是：
  - `WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS`
- 这次用完全相同的 XiangShan `grhsim` 输入，只改这个开关做 AB 重跑后，`post_stats` 的全局规模和 `exceptionVec` 精确样本都发生了明确变化。
- 尤其是 [`NO0041`](./NO0041_core_memblock_exceptionvec_survival_case_study_20260428.md) 中的代表寄存器
  - `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`
  在 `keep=false` 时已经从 `post_stats` 中消失；
  但同组里仍有真实用户的
  - `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_19`
  仍然保留。

这说明：

- `exceptionVec_21` 之前活着，主要确实是因为 declared-symbol 保护；
- 而不是脚本开关没接上，或实现没有生效。

## 1. 运行口径

两次运行都直接复用当前 XiangShan `grhsim` 的同一套输入：

- filelist：
  - `build/xs/wolf/wolf_emit/xs_wolf.f`
- top：
  - `SimTop`
- read args：
  - `build/xs/grhsim/grhsim_emit/wolvrix_read_args.txt`

两边都只跑到 pre-sched 结束即停止：

- `WOLVRIX_XS_GRHSIM_STOP_AFTER_PRE_SCHED=1`

唯一变化是：

1. `keep=true`
   - `WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS=1`
2. `keep=false`
   - `WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS=0`

输出目录：

- `keep=true`
  - `build/xs/grhsim_compare/keeptrue/`
- `keep=false`
  - `build/xs/grhsim_compare/keepfalse/`

关键产物：

- `build/xs/grhsim_compare/keeptrue/wolvrix_xs_post_stats.json`
- `build/xs/grhsim_compare/keepfalse/wolvrix_xs_post_stats.json`
- `build/xs/grhsim_compare/keeptrue/wolvrix_xs_stats.json`
- `build/xs/grhsim_compare/keepfalse/wolvrix_xs_stats.json`

## 2. 脚本入口确实支持 `false`

脚本实现很直接：

- [`../../scripts/wolvrix_xs_grhsim.py`](../../scripts/wolvrix_xs_grhsim.py)
  - `29-33`：`env_flag()` 会把 `0 / false / no / off` 解析成 `False`
  - `186`：读取 `WOLVRIX_XS_GRHSIM_SIMPLIFY_KEEP_DECLARED_SYMBOLS`，默认值是 `True`
  - `285-286`：遇到 `simplify` pass 时，把 `keep_declared_symbols` 显式传下去

也就是说：

- 这不是“脚本里没有 `false` 分支”；
- 而是“默认值是 `true`，但可以通过环境变量关掉”。

## 3. 全局规模对照

从 `wolvrix_xs_stats.json` 直接读到的核心计数如下：

| Metric | `keep=true` | `keep=false` | Delta |
| --- | ---: | ---: | ---: |
| `kRegister` | `311336` | `286014` | `-25322` |
| `kRegisterReadPort` | `311270` | `286014` | `-25256` |
| `kRegisterWritePort` | `311335` | `286013` | `-25322` |
| `register_bitwidth_total` | `4568727` | `4206181` | `-362546` |

对应位置：

- `keep=true`
  - [`../../build/xs/grhsim_compare/keeptrue/wolvrix_xs_stats.json`](../../build/xs/grhsim_compare/keeptrue/wolvrix_xs_stats.json)
  - `8904-8906`：`kRegister / kRegisterReadPort / kRegisterWritePort`
  - `12846`：`register_bitwidth_total`
- `keep=false`
  - [`../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_stats.json`](../../build/xs/grhsim_compare/keepfalse/wolvrix_xs_stats.json)
  - `8246-8248`：`kRegister / kRegisterReadPort / kRegisterWritePort`
  - `12065`：`register_bitwidth_total`

这个量级已经足够说明：

- `keepDeclaredSymbols=false` 不是只改了一点点“名字保留策略”；
- 它确实让 pre-sched 后的状态图明显变小了。

## 4. `exceptionVec_21` 精确样本：`keep=false` 后直接消失

沿用 [`NO0041`](./NO0041_core_memblock_exceptionvec_survival_case_study_20260428.md) 的代表样本：

- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`
- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$io_out_bits_uop_exceptionVec_21`

### 4.1 `keep=true`

在 `keep=true` 的 `post_stats` 中，这条链完整存在：

- `data_uop_exceptionVec_21` 命中 `4` 次：
  - symbol 列表
  - `kRegister`
  - `kRegisterReadPort.attrs.regSymbol`
  - `kRegisterWritePort.attrs.regSymbol`
- `io_out_bits_uop_exceptionVec_21` 命中 `3` 次：
  - symbol 列表
  - value 记录
  - `kRegisterReadPort.out`

对应位置：

- `1017743`：symbol
- `11352766`：`kRegister`
- `11352767`：`kRegisterReadPort`
- `11352873`：`kRegisterWritePort`
- `1017685`：read value symbol
- `4987158`：read value 记录，且 `users=[]`

### 4.2 `keep=false`

在 `keep=false` 的 `post_stats` 中：

- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_21`
  - **完全搜不到**
- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$io_out_bits_uop_exceptionVec_21`
  - **完全搜不到**

这说明：

- 这条此前“无用户、无 output、无 DPIC”的 `bit 21`，在关掉 declared-symbol 保护后，确实被清理掉了。
- 因而它此前的存活原因，确实主要是 declared symbol 保护，而不是别的隐藏消费者。

## 5. `exceptionVec_19` 对照样本：`keep=false` 后仍然保留

同组里选一条此前已经确认有用户的 bit：

- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$data_uop_exceptionVec_19`
- `cpu$l_soc$core_with_l2$core$memBlock$inner_VlSplitConnectLdu_1$io_out_bits_uop_exceptionVec_19`

结果：

- 在 `keep=true` 中它还在；
- 在 `keep=false` 中它也还在。

而且 `io_out_bits_uop_exceptionVec_19` 在两边都保持：

- `users = [{"op": "_op_10276351", "idx": 0}]`

并继续通过：

- `_op_10276351`
  - `io_out_bits_uop_exceptionVec_19 -> _inner_VlSplitConnectLdu_1_io_out_bits_uop_exceptionVec_19`

也就是说：

- `bit 19` 不是靠 declared-symbol 保护活着；
- 它是因为确实还有真实下游使用，所以在 `keep=false` 下也保住了。

## 6. 补充观察：`bit 13` 也跟 `bit 21` 一样被清掉

此前 `NO0041` 已经看到：

- `exceptionVec_13` 的 `users=[]`
- `exceptionVec_21` 的 `users=[]`

这次 AB 里也对应出现了相同行为：

- `keep=true` 时
  - `data_uop_exceptionVec_13` 命中 `4` 次
  - `io_out_bits_uop_exceptionVec_13` 命中 `3` 次
- `keep=false` 时
  - 这两个 exact symbol 都搜不到

因此 `VlSplitConnectLdu_1` 这组 `exceptionVec` 的行为已经很清晰：

- `7 / 15 / 19 / 23`：有真实用户，`keep=false` 仍保留
- `13 / 21`：无真实用户，`keep=false` 直接消失

## 7. 运行时间对照

两轮总耗时接近，但 `keep=false` 略快：

| Metric | `keep=true` | `keep=false` | Delta |
| --- | ---: | ---: | ---: |
| total | `1221705 ms` | `1196022 ms` | `-25683 ms` |
| simplify | `434960 ms` | `409511 ms` | `-25449 ms` |

这也符合预期：

- 被保护的 declared symbol 少了，`simplify` / DCE 的可删空间更大；
- 图变小后，运行时间也会小幅下降。

## 8. 结论

这轮 AB 对照已经把问题钉死了：

- `scripts/wolvrix_xs_grhsim.py` 里确实有 `keepDeclaredSymbols=false` 的入口，而且实现是通的。
- 关掉它以后，`post_stats` 的全局寄存器规模明显下降，说明这不是“配置写了但没生效”。
- 对 `core.memBlock exceptionVec` 而言：
  - `exceptionVec_21` 这类无真实用户的 bit，会随着 `keep=false` 直接消失；
  - `exceptionVec_19` 这类仍有真实用户的 bit，会在 `keep=false` 下继续保留。

因此最准确的说法是：

- 之前 `NO0041` 对 `exceptionVec_21` 的判断是对的：
  - 它在默认 `grhsim` 中存活，主要就是因为 declared-symbol 保护。
- 这不是脚本实现不良，而是默认策略就是保 declared symbols。
