# NO0017 Current Words-Only Selective-Inline 59k Snapshot（2026-04-20）

> 归档编号：`NO0017`。目录顺序见 [`README.md`](./README.md)。

这份记录固化当前 `grhsim-cpp` 的一组明确状态，以及对应的 `XiangShan coremark` `59000-cycle` 运行快照。当前状态的目标不是“回退到 NO0011”，而是先把宽值路径收敛成一个语义明确、实现简单的版本，再继续查剩余性能差距。

## 1. 当前状态

当前 emitter/runtime 在 `local value / 宽值表示` 上的策略是：

- 宽值彻底去掉 `_BitInt`
- 宽值统一使用 `std::array<std::uint64_t, N>` words-only 表示
- 保留必要的 `local_value_`
- 只对 cheap scalar 单用户表达式做选择性内联
- 宽值 `local value` 不做表达式内联，继续显式保留为 `local_value_`

这意味着当前版本相对前面几轮实验，已经明确排除了两类路径：

- 不再有 `words <-> _BitInt` 的往返转换税
- 不再把 wide words 单用户值一律内联进后续表达式

## 2. 数据来源

- 本次运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260420_codex_words_selective_inline_59k.log`
- 直接对比对象：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)
  - [`NO0015 Remove BitInt Words-Only 50k Alignment`](./NO0015_remove_bitint_words_only_50k_alignment_20260420.md)
  - [`NO0016 Disable Single-User Inline 50k Alignment`](./NO0016_disable_single_user_inline_50k_alignment_20260420.md)

## 3. 运行命令

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260420_codex_words_selective_inline_59k XS_SIM_MAX_CYCLE=59000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

本次运行口径：

- workload：`coremark-2-iteration.bin`
- runtime 上限：`59000 cycles`
- `commit trace`：关闭
- 进度打印间隔：`5000 cycles`

## 4. 最终结果

本次运行正常推进到 cycle limit，并以 `EXCEEDING CYCLE/INSTR LIMIT` 结束，没有出现 crash、assert 或 diff mismatch。

最终日志摘要：

- `instrCnt = 116358`
- `cycleCnt = 58996`
- `IPC = 1.972303`
- `Guest cycle spent = 59001`
- `Host time spent = 895694 ms`

因此本轮运行的功能结论是：

- 当前 words-only + selective-inline 版本在 `59k` 窗口内功能仍与前序版本对齐
- 当前状态可以继续作为后续 runtime 优化的观察点

## 5. 当前运行速度

按本次 `0 -> 59000 cycles` 窗口折算：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `59000` |
| guest instructions | `116358` |
| host wall time | `895.694 s` |
| host simulation speed | `65.87 cycles/s` |
| host instruction throughput | `129.91 instr/s` |

由于目前还没有与之严格对齐的 `59k` 历史窗口，所以更可比的数字是本次运行在 `50000-cycle` 时刻的 checkpoint：

- 本次 `50000-cycle`：`734869 ms`
- [`NO0015`](./NO0015_remove_bitint_words_only_50k_alignment_20260420.md) `50000-cycle`：`730523 ms`

也就是说，在目前这版“必要 local value + 选择性 cheap scalar inline”配置下：

- `50k checkpoint` 仍比 `NO0015` 略慢
- 回退幅度不大，约 `0.59%`
- 但它没有表现出相对 `NO0015` 的明确性能提升

因此这轮快照支持的结论是：

- “完全去掉 `_BitInt`”这一步是稳定的
- “wide value 保留显式 local_value_、只内联便宜 scalar”目前在性能上还没有跑赢 `NO0015`

## 6. 分段推进情况

从日志中的 `EMU_PROGRESS` 可抽出以下进度点：

| model cycles | instr | host ms |
| --- | ---: | ---: |
| `5000` | `3` | `34202` |
| `10000` | `458` | `73416` |
| `15000` | `5532` | `149619` |
| `20000` | `14121` | `243159` |
| `25000` | `20048` | `326762` |
| `30000` | `27809` | `385825` |
| `35000` | `35570` | `445085` |
| `40000` | `43350` | `535686` |
| `45000` | `52481` | `628226` |
| `50000` | `73580` | `734869` |
| `55000` | `97042` | `825475` |
| `59000` | `116358` | `895694` |

从这些点可以直接看出：

- early boot 明显偏慢
- 中段一度追回一部分差距
- 到 `50000-cycle` 时仍略慢于 `NO0015`
- `55000 -> 59000` 这最后一段没有出现异常抖动或功能问题

## 7. 本轮快照应记住的事实

如果只保留一组结论，应当记住：

- 当前版本的语义状态已经很明确：`_BitInt` 全去掉，宽值走 words-only，wide local value 保留，cheap scalar 才内联
- 这版在 `59000-cycle` 下能稳定跑到 cycle limit
- 最终结果是 `895.694 s / 65.87 cycles/s`
- 在 `50000-cycle` checkpoint 上，它仍略慢于 `NO0015`

因此当前阶段最合适的判断是：

- 现在已经把 `bitint` 变量从问题空间里基本剥离掉了
- 剩余性能差距更可能来自 activity-schedule 结构、state write/commit 热路径、以及 wide helper/临时对象的组织方式
