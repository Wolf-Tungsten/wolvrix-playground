# NO0071 GrhSIM Sched 308 SLPVectorizer 编译热点记录

## 背景

本次调查对象是当前生成产物中的单个编译单元：

- `build/xs/grhsim/grhsim_emit/grhsim_SimTop_sched_308.cpp`

现象是该文件的编译速度显著慢于普通 `sched` 分片。目标是用 `clang++` 的 `-ftime-report` / `-ftime-trace` 判断慢在前端、优化器还是后端 codegen，并确认是否有可直接绕开的编译器 pass。

## 编译口径

本目录的 `Makefile` 对 `sched` 文件使用：

```bash
clang++ -std=c++20 -O3 -I. -include-pch grhsim_SimTop.hpp.pch -c <src> -o <obj>
```

本次隔离复现使用相同核心参数，额外打开 timing：

```bash
cd build/xs/grhsim/grhsim_emit

/usr/bin/time -v clang++ \
  -std=c++20 -O3 \
  -I. \
  -include-pch grhsim_SimTop.hpp.pch \
  -ftime-report \
  -ftime-trace=/tmp/grhsim_SimTop_sched_308.ftime-trace.json \
  -ftime-trace-granularity=0 \
  -c grhsim_SimTop_sched_308.cpp \
  -o /tmp/grhsim_SimTop_sched_308.ftime.o
```

使用的编译器：

```text
clang version 22.1.2
Target: x86_64-unknown-linux-gnu
InstalledDir: /home/gaoruihao/wksp/LLVM-22.1.2-Linux-X64/bin
```

## 静态形态

`sched_308` 并不是前端包含链异常，而是一个平铺的大生成函数：

| 指标 | 数值 |
| --- | ---: |
| 文件行数 | `39968` |
| 文件大小 | `3.3M` |
| `Supernode` 注释数 | `8` |
| `// op` 数量 | `22486` |
| `activeWordFlags` 出现次数 | `27` |
| 主函数 | `GrhSIM_SimTop::eval_compute_batch_308()` |

相邻文件对照：

| 文件 | 行数 | 大小 |
| --- | ---: | ---: |
| `grhsim_SimTop_sched_307.cpp` | `1841` | `124K` |
| `grhsim_SimTop_sched_308.cpp` | `39968` | `3.3M` |
| `grhsim_SimTop_sched_309.cpp` | `54750` | `3.0M` |

注意：`sched_309` 行数更多，但本次慢点仍需要由具体优化 pass 解释，不能只按行数归因。

## `-ftime-report` 结果

完整编译 wall time：

```text
Elapsed (wall clock) time: 3:16.74
Maximum resident set size: 1478444 KB
```

Clang 阶段拆解：

| 阶段 | wall time | 占比 |
| --- | ---: | ---: |
| `Optimizer` | `192.0476s` | `97.6%` |
| `Machine code generation` | `4.4312s` | `2.3%` |
| `Front end` | `0.1637s` | `0.1%` |
| `LLVM IR generation` | `0.0590s` | `0.0%` |
| Total | `196.7015s` | `100.0%` |

Pass 级别拆解：

| Pass | wall time | 占比 |
| --- | ---: | ---: |
| `SLPVectorizerPass` | `191.1988s` | `97.3%` |
| `X86 DAG->DAG Instruction Selection` | `2.7006s` | `1.4%` |
| `Machine InstCombiner` | `1.0099s` | `0.5%` |
| `InstCombinePass` | `0.4825s` | `0.2%` |
| 其他 | `< 0.2s` | 很小 |

结论非常集中：这次慢编译不是 PCH、parse、IR 生成或普通 codegen 问题，而是 `SLPVectorizerPass` 单 pass 占满。

## Trace 归因

`-ftime-trace` 中对应的长事件为：

```text
191198829 us  SLPVectorizerPass  _ZN13GrhSIM_SimTop22eval_compute_batch_308Ev
192047583 us  Optimizer
196481428 us  Backend
196702081 us  ExecuteCompiler
```

其中：

```text
_ZN13GrhSIM_SimTop22eval_compute_batch_308Ev
```

即：

```cpp
GrhSIM_SimTop::eval_compute_batch_308()
```

所以耗时不是某个 include 或多个函数分散造成的，而是集中在 `eval_compute_batch_308()` 这个单个大函数的 SLP vectorization。

## 关掉 SLP 的验证

为了确认 `SLPVectorizerPass` 是根因，而不是 timing 统计误导，使用相同口径但加 `-fno-slp-vectorize` 复编：

```bash
cd build/xs/grhsim/grhsim_emit

/usr/bin/time -v clang++ \
  -std=c++20 -O3 \
  -fno-slp-vectorize \
  -I. \
  -include-pch grhsim_SimTop.hpp.pch \
  -ftime-report \
  -c grhsim_SimTop_sched_308.cpp \
  -o /tmp/grhsim_SimTop_sched_308.no-slp.o
```

结果：

```text
Elapsed (wall clock) time: 0:05.04
Maximum resident set size: 196204 KB
```

Clang 阶段拆解：

| 阶段 | wall time | 占比 |
| --- | ---: | ---: |
| `Machine code generation` | `3.9016s` | `77.5%` |
| `Optimizer` | `0.9613s` | `19.1%` |
| `Front end` | `0.1179s` | `2.3%` |
| `LLVM IR generation` | `0.0548s` | `1.1%` |
| Total | `5.0356s` | `100.0%` |

对比：

| 口径 | wall time | 最大 RSS |
| --- | ---: | ---: |
| `-O3` 默认 SLP | `196.70s` | `1.48GB` |
| `-O3 -fno-slp-vectorize` | `5.04s` | `196MB` |

关掉 SLP 后编译时间下降约 `39x`，内存峰值也显著下降。

## 代码形态解释

`SLPVectorizerPass` 会尝试把同一个基本块或局部区域中的多条相似标量语句打包成 SIMD 向量操作。`grhsim` 生成代码里大量出现如下模式：

```cpp
{
    const auto next_value = static_cast<bool>(
        value_bool_slots_[462775] & value_bool_slots_[283727]);
    if (grhsim_value_3196549_0_slot != next_value) {
        supernode_active_curr_[8586u] |= UINT8_C(32);
        grhsim_value_3196549_0_slot = next_value;
    }
}
```

以及许多相邻的同形结构：

```cpp
{
    const auto next_value = static_cast<bool>(
        value_bool_slots_[462776] & value_bool_slots_[283728]);
    if (grhsim_value_3196550_0_slot != next_value) {
        supernode_active_curr_[8586u] |= UINT8_C(32);
        grhsim_value_3196550_0_slot = next_value;
    }
}
```

这类代码对 SLP 很“像”可向量化候选：

- 连续出现大量 `load -> bit op -> compare -> conditional store`。
- 操作形状高度重复。
- 类型多为 `bool` / `std::uint8_t` / 整数 slot。
- 大量访问同几个数组，如 `value_bool_slots_`、`supernode_active_curr_`。

但实际又很难高效完成向量化：

- 下标不规则，不是简单连续内存。
- 有大量条件写和活性标志写入。
- 同一个大函数里临时值、数组 load/store、alias 判断和控制依赖全部交织。
- 代码平铺规模过大，SLP 枚举候选、建依赖图、做 cost model 的搜索空间急剧膨胀。

因此它不像 `NO0028` 记录的 `GVNPass` / MemorySSA 类慢点；本次 `sched_308` 的主因是 **平铺重复标量计算触发 SLPVectorizer 病态耗时**。

## 与既有编译拖尾记录的关系

此前记录：

- [`NO0027`](./NO0027_grhsim_emit_real_compile_time_snapshot_20260424.md) 说明编译重尾集中在大量 `sched` 分片。
- [`NO0028`](./NO0028_grhsim_emit_tail_compile_root_cause_20260424.md) 说明当时一批慢文件主要由 `GVNPass` / MemorySSA 被 event guard、side effect、masked commit write 打爆。
- [`NO0030`](./NO0030_sched124_llvm_ir_gvn_memdep_root_cause_20260424.md) 继续确认了另一类 `GVN + MemoryDependence + TBAA alias` 组合退化。

本次 `sched_308` 是新的、独立的慢点类型：

- `Frontend` 很小。
- `GVNPass` 很小。
- `SLPVectorizerPass` 单独占 `191.20s`。

这说明 `grhsim_emit` 的编译风险模型不能只盯 event guard / system task / masked commit write。对于大规模重复布尔/整型 slot 更新，还需要单独考虑 SLP 风险。

## 结论

- `grhsim_SimTop_sched_308.cpp` 的慢编译根因是 `SLPVectorizerPass`。
- 该 pass 在 `GrhSIM_SimTop::eval_compute_batch_308()` 上耗时 `191.20s`，占总编译时间 `97.3%`。
- 加 `-fno-slp-vectorize` 后，同文件从 `196.70s` 降到 `5.04s`。
- 该 case 不是文本长度、PCH 或普通后端 codegen 导致，而是生成代码中超大平铺重复标量序列触发了 SLP 的病态搜索。

## 后续建议

短期：

- 对 `grhsim_emit` 生成的 `sched` 编译单元评估全局添加 `-fno-slp-vectorize`。
- 如果只想最小化影响，可先对识别出的 SLP outlier 文件单独加该 flag。

中期：

- emitter 的 compile-risk 统计中新增 SLP 风险项，例如：

```text
slp_risk =
  repeated_bool_slot_update_count * A +
  repeated_integer_slot_update_count * B +
  same_active_word_flag_write_count * C +
  large_single_function_op_count * D
```

- 对 SLP 风险高的 `compute batch` 提前切小，避免一个函数内堆叠数万条同形标量操作。

长期：

- 将 `compute batch` 从“按文本 / op 数量粗切”升级为“按编译器风险形态切块”：
  - `GVN / MemorySSA` 风险：event guard、system task、masked commit write、side effect。
  - `SLP` 风险：大规模平铺重复 scalar slot update。
  - codegen 风险：单函数机器指令调度和寄存器压力。
