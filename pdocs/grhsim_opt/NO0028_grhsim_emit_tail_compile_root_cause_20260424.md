# NO0028 GrhSIM Emit Tail Compile Root Cause 20260424

## 目标

- 继续分析为什么 `build/xs/grhsim/grhsim_emit` 中后段一些 `sched_9xx~13xx.cpp` 在“文件大小 / 行数相差不大”的情况下仍然异常慢。
- 重点区分：
  - 是不是前端 parse / include 在拖时间
  - 还是 LLVM `-O3` 后端某些 pass 被特定代码形态打爆

## 输入

- 编译耗时日志：[`build/logs/xs/grhsim_emit_compile_times_20260424.tsv`](../../build/logs/xs/grhsim_emit_compile_times_20260424.tsv)
- 全量降序排序：[`build/logs/xs/grhsim_emit_compile_times_20260424.sorted.tsv`](../../build/logs/xs/grhsim_emit_compile_times_20260424.sorted.tsv)
- 代表性隔离编译报告：
  - 快文件：[`build/logs/xs/grhsim_SimTop_sched_884_isolated_time_20260424.txt`](../../build/logs/xs/grhsim_SimTop_sched_884_isolated_time_20260424.txt)
  - 快文件 trace：[`build/logs/xs/grhsim_SimTop_sched_884_isolated_trace_20260424.json`](../../build/logs/xs/grhsim_SimTop_sched_884_isolated_trace_20260424.json)
  - 慢文件：[`build/logs/xs/grhsim_SimTop_sched_945_isolated_time_20260424.txt`](../../build/logs/xs/grhsim_SimTop_sched_945_isolated_time_20260424.txt)
  - 慢文件 trace：[`build/logs/xs/grhsim_SimTop_sched_945_isolated_trace_20260424.json`](../../build/logs/xs/grhsim_SimTop_sched_945_isolated_trace_20260424.json)

## 先说结论

- “文件长度差不多”不是主解释变量。
- 真正的主因是 **单个 `eval_batch_xxx` 函数的 CFG / side-effect 形态**，不是文本大小。
- 目前至少有两类慢文件：
  - `event/sys-task heavy`：事件边沿判断和 system task 很多，`GVN + MemorySSA` 明显退化。
  - `event-heavy + commit-heavy`：system task 不多甚至为 0，但事件分支块很多，同时 masked commit write 很密，仍然把 `GVN` 顶满。
- `PCH` 已经基本排除，不是当前拖尾核心。

## 1. 长度指标解释力很差

对全量 `.cpp -> .o` 样本做粗相关性，得到：

| 指标 | 与编译耗时相关系数 |
| --- | ---: |
| `bytes` | `-0.4334` |
| `lines` | `-0.4251` |
| `ifs` | `-0.0567` |
| `event_edge_slots_` 引用次数 | `0.6914` |
| `execute_system_task` 次数 | `0.4802` |
| masked merge 模式 `& ~` | `0.5216` |

结论：

- 文件字节数、行数不仅不强相关，甚至在这一轮样本里是负相关。
- 这说明“后面那些慢文件”并不是因为单纯更长，而是 **代码结构更容易触发优化器最坏路径**。

## 2. 同体量快慢对照：`sched_884` vs `sched_945`

### 静态形态

| 文件 | bytes | lines | `if (` | `event_edge_slots_` | `execute_system_task` | `supernode_active_curr_` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `grhsim_SimTop_sched_884.cpp` | `730808` | `8546` | `1539` | `1` | `0` | `803` |
| `grhsim_SimTop_sched_945.cpp` | `771949` | `8496` | `1524` | `28` | `21` | `846` |

这两个文件长度几乎一样，`if` 数也几乎一样，但：

- `sched_884` 几乎没有 event guard，也没有 system task。
- `sched_945` 出现了明显更多的 event guard 和 system task。

### 隔离 `-O3` 编译结果

#### `sched_884`

- 总耗时：`9.634s`
- Frontend：`7.104s`
- Backend：`2.452s`
- `GVNPass`：`2.022s`

#### `sched_945`

- 总耗时：`92.627s`
- Frontend：`6.205s`
- Backend：`86.346s`
- `GVNPass`：`85.891s`

### 结论

- `sched_945` 比 `sched_884` 慢，不是 parse 慢。
- 它几乎完全是 LLVM backend，准确说是 **`GVNPass`** 在爆炸。
- 同体量文件中，真正把优化器拖死的是：
  - 更多 event-guard 造成的 CFG 分裂
  - 更多 side-effect / system-task 路径
  - 大量 masked commit write 叠加在同一个巨函数里

## 3. 后段极慢文件不是单一模式

### 模式 A：event/sys-task heavy

按 event / system task 统计，后段慢文件里有一批非常典型：

| 文件 | `event_edge_slots_` | `execute_system_task` | 编译耗时(s) |
| --- | ---: | ---: | ---: |
| `grhsim_SimTop_sched_964.cpp` | `791` | `169` | `1877.041` |
| `grhsim_SimTop_sched_949.cpp` | `768` | `384` | `745.597` |
| `grhsim_SimTop_sched_948.cpp` | `768` | `384` | `586.651` |
| `grhsim_SimTop_sched_1060.cpp` | `753` | `373` | `1221.900` |
| `grhsim_SimTop_sched_1103.cpp` | `660` | `330` | `1134.243` |

这些文件的共同点：

- 文件未必特别大。
- 但 event 判断很多，system task 也很多。
- 这非常容易把 MemorySSA / GVN 的等价传播和可见性推理拖进最坏路径。

### 模式 B：event-heavy + commit-heavy

还有一批文件 system task 并不多，但依然极慢，例如：

| 文件 | `event_if_blocks` | 其中带 `||` 的 event block | `supernode_active_curr_` | 编译耗时(s) |
| --- | ---: | ---: | ---: | ---: |
| `grhsim_SimTop_sched_1230.cpp` | `141` | `70` | `2255` | `1914.322` |
| `grhsim_SimTop_sched_1304.cpp` | `121` | `52` | `1202` | `1709.107` |
| `grhsim_SimTop_sched_1252.cpp` | `80` | `39` | `1190` | `1692.797` |
| `grhsim_SimTop_sched_1145.cpp` | `91` | `42` | `1077` | `1623.789` |

其中 `sched_1230.cpp` 尤其典型：

- `bytes = 816464`
- `lines = 10278`
- `if = 1679`
- `event_edge_slots_ = 211`
- `event_if_blocks = 141`
- `execute_system_task = 0`
- `const auto next_value = ...` / masked commit write = `768`
- `supernode_active_curr_[...]` 写入点 = `2255`

我对 `sched_1230.cpp` 做了隔离 `-O3` 编译尝试，跑了 **10 分钟以上仍未完成**。这说明：

- 即使没有 system task，
- 只要 event-guard 足够多，且一个函数里堆了大量 masked commit write + reactivation，
- 一样会把优化器拖入极长尾。

## 4. 为什么这些形态会打爆 GVN

从生成代码看，这批慢文件都大量出现下面这种模式：

```cpp
if (cond) {
    const auto next_value = (old & ~mask) | (new_bits & mask);
    if (state_reg_x != next_value) {
        state_reg_x = next_value;
        supernode_active_curr_[...] |= ...;
        ...
    }
}
```

当这种模式在一个大函数里成百上千次重复，并且外面还套着：

- `if (event_edge_slots_[...] == ...)`
- 多个 `||` 合并的 event 条件
- `execute_system_task(...)`

LLVM `GVNPass` 需要处理的问题会一起变坏：

- 控制流块数上升
- MemorySSA 图更复杂
- 大量 load/store 是否等价、是否可前提化、是否被 side effect 打断，需要反复判断
- 同类 masked merge 表达式很多，值编号和支配关系判断成本急剧上升

所以真正的瓶颈不是“C++ 太长”，而是：

- **巨函数**
- **大量 memory-visible masked write**
- **大量 event guard**
- **side-effect 路径混入同一函数**

## 5. 对 emitter 的直接启示

如果目标是继续压 compile tail，下一步应该优先改 emitter 的 cost model，而不是继续只盯 `PCH` 或文件字节数。

建议：

1. `sched` chunking 不能再只看 `ops / estimated_lines`。
   还要把 `event_edge_slots_`、`execute_system_task`、masked commit write 数量纳入 cost。
2. event-guard heavy 的 supernode / batch 要单独切小。
   尤其是带 `||` 的 event block，不该和普通 commit 密集块混在同一个大函数里。
3. system task / extern side effect 最好单独拆出尾段函数。
   不要和大批纯 state commit 共处一个 `eval_batch_xxx`。
4. commit-heavy 批次要限制 masked write 总数，而不是只限制 op 数。
   当前 `768` 只是 sink supernode op 上限，不足以约束 “CFG + MemorySSA 真成本”。
5. 后续可以考虑给 emitter 增加编译风险分数，例如：

```text
risk =
  event_ref_count * A +
  event_block_count * B +
  multi_event_block_count * C +
  system_task_count * D +
  masked_commit_write_count * E +
  reactivation_write_count * F
```

## 结论

- 后段这些文件慢，不是因为“长度差不多但运气不好”。
- 真正的解释是：**它们把 event guard、side effect、masked commit write、reactivation 全堆进了一个巨 `eval_batch` 函数里，直接把 `GVNPass` 和 MemorySSA 推进最坏区间。**
- 因此后续 emitter 优化方向应该从“按行数 / op 数切块”升级为“按编译器风险形态切块”。
