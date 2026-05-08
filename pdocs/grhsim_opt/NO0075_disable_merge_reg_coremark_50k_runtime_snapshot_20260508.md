# NO0075 Disable `merge-reg` CoreMark 50k Runtime Snapshot

> 归档编号：`NO0075`。目录顺序见 [`README.md`](./README.md)。

## 1. 目的

这份记录只固化一个当前阶段的直接决策：

- 在 `scripts/wolvrix_xs_grhsim.py` 中临时移除 `merge-reg` pass
- 重新从空 `build/xs/grhsim` 做一次 fresh emit / fresh build
- 用新的 `grhsim` `emu` 跑 XiangShan `coremark` `50000-cycle` bounded run
- 记录关闭 `merge-reg` 后的当前运行速度

本记录同时作为阶段性结论：

- 后续 `pdocs/grhsim_opt` 路线里，`merge-reg` 暂时不再启用
- 直到重新证明该 pass 不会引入当前怀疑的行为偏差或速度退化

## 2. 代码状态

本轮直接在 [`scripts/wolvrix_xs_grhsim.py`](../../scripts/wolvrix_xs_grhsim.py) 中移除了 pre-sched pipeline 里的：

```python
("merge-reg", merge_reg_options),
```

其余 pre-sched 流程保持不变，仍为：

- `xmr-resolve`
- `memory-read-retime`
- `multidriven-guard`
- `blackbox-guard`
- `latch-transparent-read`
- `hier-flatten`
- `comb-lane-pack`
- `comb-loop-elim`
- `simplify`
- `simplify`
- `memory-init-check`
- `stats`

也就是说，本轮不是“关闭某个 `merge-reg` 子策略”，而是整个 `merge-reg` pass 在 XS `grhsim` 主流程里不再执行。

## 3. 执行口径

### 3.1 fresh build 要求

为了避免旧 `emu` 产物复用，本轮先显式删除：

```bash
rm -rf build/xs/grhsim
```

然后重新执行：

```bash
make xs_wolf_grhsim_emu
```

这一步会重新：

- emit `grhsim` C++ 代码
- 编译 `build/xs/grhsim/grhsim_emit`
- 重新链接 `build/xs/grhsim/grhsim-compile/emu`

最终得到的新 `emu` 时间戳为：

```text
emu compiled at May  8 2026, 08:29:55
```

### 3.2 运行口径

用户已给出并确认本轮 `50k` bounded run 的实际输出。运行口径为：

```text
max cycles: 50000
image: testcase/xiangshan/ready-to-run/coremark-2-iteration.bin
diff:  testcase/xiangshan/ready-to-run/riscv64-nemu-interpreter-so
```

运行进度：

```text
[CYCLE_LIMIT] cycles=10000 max_cycles=50000
[CYCLE_LIMIT] cycles=20000 max_cycles=50000
[CYCLE_LIMIT] cycles=30000 max_cycles=50000
[CYCLE_LIMIT] cycles=40000 max_cycles=50000
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
```

## 4. 50k 结果

用户确认的本轮日志尾部为：

```text
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x80001312
Core-0 instrCnt = 73,580, cycleCnt = 49,996, IPC = 1.471718
Seed=0 Guest cycle spent: 50,001 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 423,053ms
```

整理后关键指标如下：

| 指标 | 数值 |
| --- | ---: |
| bounded cycle target | `50000` |
| final `instrCnt` | `73580` |
| final `cycleCnt` | `49996` |
| final IPC | `1.471718` |
| `Guest cycle spent` | `50001` |
| `Host time spent` | `423053 ms` |

## 5. 速度

按本轮 `50000-cycle` bounded run 直接折算：

```text
50000 / 423.053 s = 118.19 cycles/s
```

取两位小数后：

| 指标 | 数值 |
| --- | ---: |
| simulated cycles | `50000` |
| host seconds | `423.053 s` |
| throughput | `118.19 cycles/s` |

## 6. 与当前开启 `merge-reg` 基线对比

可直接对照 [`NO0065`](./NO0065_xs_grhsim_two_strategy_coremark_50k_20260503.md) 中“只保留两策略 `merge-reg`”时的 `50k` 结果：

| 方案 | `Host time spent` | throughput |
| --- | ---: | ---: |
| `merge-reg` 两策略开启 | `379910 ms` | `131.61 cycles/s` |
| 本轮：整体关闭 `merge-reg` | `423053 ms` | `118.19 cycles/s` |

差值：

| 对比项 | 数值 |
| --- | ---: |
| host time delta | `+43143 ms` |
| host time relative | `+11.36%` |
| throughput delta | `-13.42 cycles/s` |
| throughput relative | `-10.20%` |

所以单看 `50k` runtime：

- 关闭 `merge-reg` 后，当前速度比 `NO0065` 慢
- 但这轮记录的重点不是“追求当前最快速度”
- 而是优先把可疑 pass 从主流程里拿掉，避免继续把潜在语义偏差带进后续定位

## 7. 当前阶段决策

本轮之后，先采用下面的工作结论：

1. `merge-reg` 暂时不再作为 XS `grhsim` 主流程的默认 pass。
2. 后续定位 `grhsim` vs `verilator` / `reference` 的行为差异时，先以“关闭 `merge-reg`”版本为工作基线。
3. 如果后面需要重新评估 `merge-reg`，应把问题拆开：
   - 先重新证明功能 / 时序对齐不变
   - 再单独比较性能收益是否值得保留

换句话说，当前优先级是：

- 先减少不必要变量
- 再谈 `merge-reg` 的性能回收

## 8. 结论

- 本轮已在移除 `merge-reg` 后完成 fresh emit、fresh build 和 `coremark 50k` bounded run。
- 关闭 `merge-reg` 的当前速度快照为：
  - `Host time spent = 423053 ms`
  - `throughput = 118.19 cycles/s`
- 该速度慢于之前两策略 `merge-reg` 基线 [`NO0065`](./NO0065_xs_grhsim_two_strategy_coremark_50k_20260503.md) 的 `131.61 cycles/s`。
- 但当前阶段为了减少可疑变量，后续 XS `grhsim` 主流程里暂不再启用 `merge-reg` pass。
