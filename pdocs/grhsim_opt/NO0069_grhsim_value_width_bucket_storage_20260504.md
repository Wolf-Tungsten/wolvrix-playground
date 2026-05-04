# NO0069 GrhSIM Value 按位宽分桶 Storage 优化记录（2026-05-04）

> 归档编号：`NO0069`。目录顺序见 [`README.md`](./README.md)。

## 1. 目的

记录一次针对 GrhSIM 生成代码中 combinational logic value storage 的布局优化。

前一阶段已经确认：

- 单纯继续做 `NO0066` 里的 helper fast path 收益不足，且部分尝试会回退。
- 统一 byte pool 虽然减少字段数量，但在生成 C++ 与最终二进制层面会引入大量 typed ref helper / offset / alias 形态。
- 当前更值得尝试的是把 value 的生命周期和访问形态收窄，让编译器直接看到 typed array slot，而不是每次从统一 byte arena 里按 offset 取引用。

本轮目标是：把 logic value 从单一 packed `value_logic_storage_` 改成按位宽分桶保存，减少生成调度代码里的 storage ref 计算与 alias 压力，以最终二进制指令数和 CoreMark 50k 运行时间为主要评估指标。

## 2. 改动内容

改动文件：

```text
wolvrix/lib/emit/grhsim_cpp.cpp
wolvrix/tests/emit/test_emit_grhsim_cpp.cpp
```

### 2.1 value storage 从统一 byte pool 改为 typed buckets

旧形态：

```cpp
alignas(std::uint64_t) std::array<std::byte, kValueLogicStorageBytes> value_logic_storage_{};
```

value 引用通过类似下面的方式生成：

```cpp
grhsim_value_storage_ref<T>(value_logic_storage_, offset)
```

新形态按 scalar kind 和 wide word count 分桶：

```cpp
std::array<std::uint8_t, N> value_bool_slots_{};
std::array<std::uint8_t, N> value_u8_slots_{};
std::array<std::uint16_t, N> value_u16_slots_{};
std::array<std::uint32_t, N> value_u32_slots_{};
std::array<std::uint64_t, N> value_u64_slots_{};
std::array<std::array<std::uint64_t, W>, N> value_words_W_slots_{};
```

value 引用直接变成：

```cpp
value_u64_slots_[slot]
value_words_2_slots_[slot]
```

也就是说，value 的 `slotIndex` 不再是 byte offset，而是对应 bucket 内的元素下标。

### 2.2 state storage 保持 packed byte pool

本轮只拆 value，不拆 state。

state logic storage 改名为独立字段：

```cpp
alignas(std::uint64_t) std::array<std::byte, kStateLogicStorageBytes> state_logic_storage_{};
```

state 仍使用 packed accessor：

```cpp
grhsim_value_storage_ref<T>(state_logic_storage_, offset)
```

这样可以避免把 persistent state 的布局风险和 value bucket 实验混在一起。

### 2.3 supernode value alias 改为按 value id/generation 命名

由于不同 bucket 中的 slot 下标会重复，原先仅用 slot offset 形成的 alias 名称不再可靠。

本轮将 value alias 名称改为：

```text
grhsim_value_<index>_<generation>_slot
```

这样可以避免跨 bucket 同下标造成别名名冲突。

### 2.4 init chunk 按 bucket 清零

原先 value init chunk 是：

```cpp
std::fill(value_logic_storage_.begin(), value_logic_storage_.end(), std::byte{});
```

现在改为对每个非空 bucket 分别 `std::fill`：

```cpp
std::fill(value_u64_slots_.begin(), value_u64_slots_.end(), std::uint64_t{});
std::fill(value_words_2_slots_.begin(), value_words_2_slots_.end(), std::array<std::uint64_t, 2>{});
```

## 3. 生成 XS 头文件布局确认

本轮重新 emit / build 后，`build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp` 中的 value bucket 形态如下：

```text
std::array<std::uint8_t, 999236> value_bool_slots_{};
std::array<std::uint8_t, 184214> value_u8_slots_{};
std::array<std::uint16_t, 35301> value_u16_slots_{};
std::array<std::uint32_t, 15594> value_u32_slots_{};
std::array<std::uint64_t, 105944> value_u64_slots_{};
std::array<std::array<std::uint64_t, 2>, 7526> value_words_2_slots_{};
...
std::array<std::array<std::uint64_t, 1239>, 1> value_words_1239_slots_{};
alignas(std::uint64_t) std::array<std::byte, kStateLogicStorageBytes> state_logic_storage_{};
```

同时确认生成代码中不再出现：

```text
value_logic_storage_
kValueLogicStorageBytes
grhsim_value_storage_ref<...>(value_logic_storage_, ...)
```

## 4. 验证命令

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
make xs_wolf_grhsim_emu RUN_ID=value_bucket_20260504 XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_LOG_BEGIN=0 XS_LOG_END=0
```

XS CoreMark 50k 运行：

```bash
make run_xs_wolf_grhsim_emu RUN_ID=value_bucket_20260504 XS_SIM_MAX_CYCLE=50000 XS_WAVEFORM=0 XS_WAVEFORM_FULL=0 XS_COMMIT_TRACE=0 XS_LOG_BEGIN=0 XS_LOG_END=0
```

二进制与指令数统计：

```bash
size build/xs/grhsim/grhsim-compile/emu
find build/xs/grhsim/grhsim_emit -maxdepth 1 -name 'grhsim_SimTop_sched_*.o' -print0 | xargs -0 size
objdump -d build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_*.o
```

## 5. 验证结果

emitter 测试通过：

```text
1/2 Test #11: emit-grhsim-cpp ..................   Passed   50.87 sec
2/2 Test #12: emit-grhsim-cpp-memory-fill ......   Passed    0.01 sec

100% tests passed, 0 tests failed out of 2
```

XS CoreMark 50k 日志：

```text
build/logs/xs/xs_wolf_grhsim_value_bucket_20260504.log
```

运行尾部：

```text
[CYCLE_LIMIT] cycles=50000 max_cycles=50000
Core 0: EXCEEDING CYCLE/INSTR LIMIT at pc = 0x8000042c
Core-0 instrCnt = 22484, cycleCnt = 49996, IPC = 0.449716
Seed=0 Guest cycle spent: 50001 (this will be different from cycleCnt if emu loads a snapshot)
Host time spent: 349281ms
```

## 6. 效果评估

### 6.1 对照口径

本轮对照的上一版是已包含宽值 `grhsim_assign_words` 小优化后的版本。该上一版关键数值为：

```text
final emu .text        = 169341020
sched objects text     = 170244207
sched total inst       = 36700882
sched_104 inst         = 83794
sched_335 inst         = 79205
CoreMark 50k host time = 368178ms
```

### 6.2 二进制体量

本轮最终 `emu`：

```text
   text	   data	    bss	    dec	    hex	filename
166805308	   9360	  14688	166829356	9f19d2c	build/xs/grhsim/grhsim-compile/emu
```

对比上一版：

| 指标 | 上一版 | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| final emu `.text` | `169341020` | `166805308` | `-2535712` / `-1.50%` |
| sched objects text | `170244207` | `167775882` | `-2468325` / `-1.45%` |

### 6.3 sched 指令数

全量 sched object 反汇编统计：

```text
files=1175 inst=36199996
```

对比上一版：

| 指标 | 上一版 | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| sched total inst | `36700882` | `36199996` | `-500886` / `-1.36%` |
| sched_104 inst | `83794` | `84496` | `+702` |
| sched_335 inst | `79205` | `79113` | `-92` |

注意：单个 sched object 不一定都下降，例如 `sched_104` 本轮增加了 `702` 条。但总量级明确下降，说明优化收益来自全局存储访问形态简化，而不是某个单一编译单元。

### 6.4 CoreMark 50k runtime

| 指标 | 上一版 | 本轮 | 变化 |
| --- | ---: | ---: | ---: |
| Host time spent | `368178ms` | `349281ms` | `-18897ms` / `-5.13%` |
| cycles/s | `135.80` | `143.16` | `+5.42%` |

这次静态指令数下降约 `1.36%`，但 50k runtime 改善约 `5.13%`。可能原因是 bucket 后不仅减少了指令数量，还改善了 typed alias / offset 计算 / load-store forwarding 等局部代码形态。

## 7. 结论

这轮 value 按位宽分桶是当前值得保留的优化：

- 功能验证通过：emitter tests 与 XS CoreMark 50k 都通过。
- 生成代码形态更直接：value 不再从 unified byte pool 中按 offset reinterpret。
- 最终 `.text` 减少约 `1.50%`。
- sched 总指令数减少约 `1.36%`。
- CoreMark 50k host time 从 `368178ms` 降到 `349281ms`，单次约快 `5.13%`。

相对 `NO0068` 的 task span 小优化，这一轮已经不是“聊胜于无”，而是能在当前 50k 口径下产生可见 runtime 收益。

## 8. 后续观察点

1. state 仍是 packed byte storage。本轮没有证明 state 也应该分桶；state 的 persistent 语义和初始化/commit 路径风险更高，应单独 AB。
2. wide bucket 数量较多，极端宽度会生成很多 `value_words_W_slots_` 字段。当前收益为正，但后续如果遇到编译时间或头文件体量问题，可以考虑只对高频 `W` 分桶，长尾宽度合并为 fallback bucket。
3. 本轮说明“一个统一 value 池”并不一定优于“按位宽分桶”。至少在当前 GrhSIM 生成代码中，让 C++ 编译器直接看到 typed slot，对二进制代码和 runtime 都更友好。
4. 若继续沿 storage 方向优化，应优先分析 value read/write 热点中是否还存在多余临时 ref、窄宽度掩码和宽 words helper 调用，而不是先扩大到 state 或 memory-like storage。
