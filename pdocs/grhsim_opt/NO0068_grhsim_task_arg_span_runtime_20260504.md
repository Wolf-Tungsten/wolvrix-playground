# NO0068 GrhSIM Task Arg Span Runtime 小优化记录（2026-05-04）

> 归档编号：`NO0068`。目录顺序见 [`README.md`](./README.md)。

## 1. 目的

记录一次针对 GrhSIM system task / task arg 路径的低风险 runtime 小优化。

本轮不是继续 `NO0066` 中已经证明收益不足或回退的 helper fast path，也不保留前一轮 read / storage alias 生命周期实验。前置动作是先撤回 alias/read 相关改动，再只改 task runtime 的参数传递与切片方式。

## 2. 改动内容

改动文件：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
```

核心变化：

- 生成的 system task runtime 增加 `<span>`。
- `grhsim_format_task_message` 从 `const std::vector<grhsim_task_arg> &` 改为 `std::span<const grhsim_task_arg>`。
- `execute_system_task(std::string_view, std::initializer_list<grhsim_task_arg>)` 内部不再把 `initializer_list` 复制成 `std::vector`。
- `$fdisplay` / `$fwrite` / `$fatal` / `$finish` / `$stop` 的消息参数不再构造子 `vector`，改用 `items.subspan(...)`。

原先的热路径形态大致是：

```cpp
const std::vector<grhsim_task_arg> items(args.begin(), args.end());
const std::vector<grhsim_task_arg> msgArgs(items.begin() + 1, items.end());
```

现在变为：

```cpp
const std::span<const grhsim_task_arg> items(args.begin(), args.size());
const auto msgArgs = items.subspan(1);
```

该改动保持现有 callsite 发射形态不变，仍生成：

```cpp
execute_system_task("display", {...});
```

因此它只减少 runtime 内部的参数容器复制，不改变 system task 语义和发射结构。

## 3. 验证命令

本地 emitter 构建：

```bash
cmake --build wolvrix/build --target emit-grhsim-cpp emit-grhsim-cpp-memory-fill
```

本地 emitter 测试：

```bash
ctest --test-dir wolvrix/build --output-on-failure -R 'emit-grhsim-cpp|emit-grhsim-cpp-memory-fill'
```

XS GrhSIM 重新 emit / build：

```bash
make xs_wolf_grhsim_emu RUN_ID=task_span_20260504 XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_LOG_BEGIN=0 XS_LOG_END=0
```

XS CoreMark 50k 运行：

```bash
make run_xs_wolf_grhsim_emu RUN_ID=task_span_20260504 XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_LOG_BEGIN=0 XS_LOG_END=0
```

## 4. 验证结果

emitter 测试通过：

```text
1/2 Test #11: emit-grhsim-cpp ..................   Passed   57.80 sec
2/2 Test #12: emit-grhsim-cpp-memory-fill ......   Passed    0.01 sec

100% tests passed, 0 tests failed out of 2
```

XS 运行日志：

```text
build/logs/xs/xs_wolf_grhsim_task_span_20260504.log
```

运行尾部：

```text
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x8000042c
Core-0 instrCnt = 22484, cycleCnt = 49996, IPC = 0.449716
Seed=0 Guest cycle spent: 50001 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 386551ms
```

二进制大小：

```text
   text	   data	    bss	    dec	    hex	filename
170266553	   9360	  14688	170290601	a266da9	build/xs/grhsim/grhsim-compile/emu
```

## 5. 效果评估

### 5.1 运行速度

本轮 `Host time spent = 386551 ms`，约等于 `129.35 cycles/s`。

对照近期记录：

| 对照 | Host time spent | 结果 |
| --- | ---: | --- |
| `NO0065` two-strategy snapshot | `379910 ms` | 本轮慢 `+6641 ms` / `+1.75%` |
| `NO0066` scalar slice u64 尝试 | `385094 ms` | 本轮慢 `+1457 ms` / `+0.38%` |
| 本轮 task span | `386551 ms` | 功能正确，但速度无可见收益 |

结论：这次 task arg span 优化没有改善 CoreMark 50k 的整机运行时间。原因很可能是 CoreMark 50k 主热点不在 system task 输出路径；task runtime 的容器复制被清掉后，主耗时仍然在生成的调度 / eval 指令流里。

### 5.2 代码段体量

本轮 `.text = 170266553`。

相对最近记录过的 `.text = 170459337`，减少：

```text
170459337 - 170266553 = 192784 bytes
192784 / 170459337 = 0.1131%
```

也就是代码段约减少 `0.113%`。

注意：本轮没有单独重测“撤回 alias/read 后、尚未加入 task span”的干净二进制，因此上面的百分比只应视为相对最近已记录二进制体量的近似比较，而不是严格 AB。

## 6. 结论

这轮优化可以保留为“小幅清理”：

- 代码语义清楚，减少不必要的 `std::vector` 构造和子切片复制。
- emitter 测试与 XS CoreMark 50k 都通过。
- `.text` 有小幅下降，约 `0.113%` 量级。

但它不能视为有效的主线性能优化：

- 50k `Host time spent` 仍然是 `386551 ms`。
- 速度没有优于 `NO0065` 和近期更优日志。
- 对 CoreMark 主热点的影响基本可以判定为“聊胜于无”。

## 7. 后续建议

如果继续沿 task/task arg 方向推进，不应继续只优化 `grhsim_task_arg` 容器搬移。更值得验证的下一步是把高频、形态固定的 system task 在 emitter 阶段特殊化：

- 无参 task 或固定少参 task 避免进入 `execute_system_task` 的字符串分派链。
- `$display` / `$write` / `$fdisplay` / `$fwrite` 直接发射专用路径，减少 runtime name 比较。
- 对不需要格式串解析的纯参数输出路径做单独 fast path。

但在 CoreMark 50k 上，这条方向的优先级不应高于 eval / sched 主体热路径优化。
