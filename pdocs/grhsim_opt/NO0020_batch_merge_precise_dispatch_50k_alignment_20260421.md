# NO0020 Batch Merge Precise Dispatch 50k Alignment（2026-04-21）

> 归档编号：`NO0020`。目录顺序见 [`README.md`](./README.md)。

这份记录用于固化本轮 `grhsim` XiangShan batching 调整的实际结果。目标是：

- 在不改变现有 `active flag` 数据结构的前提下，合并过碎的 `schedule batch`
- 观察 batch 合并后对 `50k-cycle` XiangShan CoreMark runtime 的真实影响
- 记录为什么第一次实现虽然合并了 batch，却反而变慢
- 固化最终“保留合批，但恢复按 active word 精确派发”的版本表现

本轮结论可以先直接写在前面：

- batch 合并已经生效，但当前 batch 数仍是 `4662`，还没有压到目标的 `~1000`
- 第一版“按 batch 全扫”的运行时调度把 `50k` 速度拉低到 `84.52 cycles/s`
- 最终改成“按 active word 即时派发 batch”后，`50k` 速度回升到 `100.94 cycles/s`
- 这个结果不仅回收了回退，还超过了当前 `NO0011` baseline 的 `89.17 cycles/s`

## 数据来源

- 本轮第一次合批后的 `50k` 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260421_codex_batch4662_perf_50k.log`
- 本轮最终“即时派发”版本的 `50k` 运行日志：
  - `build/logs/xs/xs_wolf_grhsim_20260421_codex_immediate_dispatch_50k.log`
- 本轮 emitter / emu 重建日志：
  - `build/logs/xs/xs_wolf_grhsim_build_20260421_102359.log`
  - `build/logs/xs/xs_wolf_grhsim_build_20260421_103821.log`
- 当前生成产物中的 batch 规模：
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop.hpp`
  - `build/xs/grhsim/grhsim_emit/grhsim_SimTop_declared_value_index.txt`
- 对齐基线：
  - [`NO0011 当前 GrhSIM XiangShan CoreMark 50k Runtime Snapshot`](./NO0011_current_grhsim_xiangshan_coremark_50k_runtime_snapshot_20260420.md)

## 1. 本轮修改目标

用户提出的问题是：

- 目前 `grhsim` 处理 XiangShan 时，batch 拆得太碎
- 当前规模在 `9000+` 量级
- 希望在不改变现有 `active flag` 数据结构的前提下，把 batch 合并到 `1000` 左右

本轮采取的实现策略是：

- 保持现有 `supernode_active_curr_` 布局不变
- 允许一个 `ScheduleBatch` 覆盖多个 `active flag word`
- 先从 emitter/runtime codegen 层面合并 batch，而不改底层 activity flag 存储

## 2. 当前 batch 规模

重新 emit 后，当前 XiangShan 生成产物里可直接看到：

- `kActiveFlagWordCount = 9453`
- `kBatchCount = 4662`
- `# schedule_batches=4662`

也就是说：

- batch 数已经明显低于之前的 `9000+`
- 但还没有达到预期的 `~1000`
- 当前合批只是把“一个 active word 一个 batch”的硬约束打掉，还没有引入更强的“目标 batch 数驱动”合并策略

## 3. 第一版实现为什么变慢

第一版合批之后，运行时调度从：

- 按 `active word` 精确派发相关 batch

变成了：

- 每轮直接扫描全部 `kBatchCount`，然后在每个 batch 内再检查它包含的 `active word`

这会带来两个直接后果：

- 稀疏激活时，很多不该进入的 batch 也被调用了
- 每轮的固定调度成本从“扫 active words”退化成了“扫全部 batches”

对于当前 XiangShan，这个退化是很实在的，因为：

- `active words = 9453`
- `batches = 4662`

虽然 batch 数比 active word 少，但旧路径是“active word 非零才派发对应 batch”；新路径是“每轮先过全部 batch”。这使得第一版运行时在稀疏活动图上多付出了一块稳定而昂贵的 dispatch 开销。

## 4. 第一次 50k 结果：batch 合并生效，但 runtime 回退

第一次 `50k` 复测命令：

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260421_codex_batch4662_perf_50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

最终结果：

| 指标 | 数值 |
| --- | ---: |
| batch count | `4662` |
| guest cycle spent | `50001` |
| host time spent | `591601 ms` |
| host simulation speed | `84.52 cycles/s` |

功能上这轮是正常的：

- 正常跑到 `50000-cycle` 上限
- 没有 diff mismatch / assert / crash

但性能上相对 `NO0011` 的 `89.17 cycles/s`：

- 慢了约 `5.21%`

所以第一阶段结论是：

- 合批本身生效了
- 但 runtime dispatch 被改坏了，导致合批后的版本没有带来正向收益

## 5. 中间一次错误尝试：预收集 batch 再统一执行

在定位 slowdown 之后，中间尝试过一个看起来更“省调度”的实现：

- 先扫描本轮 active words
- 把所有要执行的 batch 收集起来
- 再统一执行这一批 batch

这个版本的意图是：

- 避免整轮全扫所有 batch
- 同时避免重复进入同一个 batch

但它改坏了 fixed-point 语义，因为：

- 某个 batch 在本轮执行时新激活的 supernode
- 原本可能仍应在当前 round 内继续被后续 active word 路径观察到
- 预收集后统一执行，会把这类新激活整体推迟到下一轮

结果是在 XiangShan 早期启动阶段约 `525 cycle` 就触发断言：

- `Assertion failed at build/xs/rtl/rtl/ICacheMainPipe.sv:494`

所以这条路径已经被放弃，不作为最终方案保留。

## 6. 最终修正：按 active word 即时派发 batch

最终采用的运行时策略是：

- 保留“一个 batch 可以覆盖多个 active word”
- 重新生成 `activeWord -> batchIndices` 索引
- 在 `eval()` 里按 `active word` 顺序扫描
- 一旦某个 `active word` 非零，就立即派发它关联的 batch

这条路径的重要性质是：

- 不再每轮全扫全部 batch
- 仍然保留旧的“同轮即时传播”语义
- active flag 数据结构完全不变

换句话说，最终版本的核心不是“回退合批”，而是：

- `keep merged batches`
- `restore active-word-driven immediate dispatch`

## 7. 最终 50k 结果：即时派发版本

最终 `50k` 复测命令：

```bash
make -j2 run_xs_wolf_grhsim_emu RUN_ID=20260421_codex_immediate_dispatch_50k XS_SIM_MAX_CYCLE=50000 XS_COMMIT_TRACE=0 XS_PROGRESS_EVERY_CYCLES=5000
```

最终结果：

| 指标 | 数值 |
| --- | ---: |
| batch count | `4662` |
| guest cycle spent | `50001` |
| host time spent | `495347 ms` |
| host simulation speed | `100.94 cycles/s` |
| guest instructions | `73580` |
| IPC | `1.471718` |

这轮功能结果：

- 正常跑到 `50000-cycle` 上限
- 没有 diff mismatch
- 没有 assertion
- 没有 crash

同时，这轮速度已经明显回到更健康的区间。

## 8. 和前后版本对比

| 版本 | batch count | host time | cycles/s | 相对 `NO0011` |
| --- | ---: | ---: | ---: | ---: |
| `NO0011` baseline | 未单独记录 | `560.738 s` | `89.17` | `baseline` |
| 第一版合批 + 全扫 batch | `4662` | `591.601 s` | `84.52` | `-5.21%` |
| 最终合批 + 即时派发 | `4662` | `495.347 s` | `100.94` | `+13.20%` |

如果只看本轮内部的前后两版：

- `84.52 cycles/s -> 100.94 cycles/s`
- 提升约 `19.43%`

这基本可以确认：

- 问题不在“合批”本身
- 真正的问题在“把 runtime dispatch 改成了全量扫 batch”
- 只要恢复按 active word 即时派发，合批可以变成净收益

## 9. 当前阶段应记住的事实

如果只保留这轮最重要的事实，应当记住：

- 在不改 `active flag` 数据结构的前提下，`grhsim` 已经支持“一个 batch 覆盖多个 active word”
- 当前 XiangShan batch 数从原先的 `9000+` 降到了 `4662`
- 第一版运行时实现因为“全扫 batch”导致性能回退到 `84.52 cycles/s`
- 最终改成“按 active word 即时派发 batch”后，`50k` 速度回升到 `100.94 cycles/s`
- 这版已经不仅回收回退，还超过了当前 `NO0011` baseline 的 `89.17 cycles/s`

## 10. 后续方向

这一轮还没有完成用户最初的全部目标，因为：

- batch 数虽然降了，但还停在 `4662`
- 离目标的 `~1000` 仍有明显距离

因此下一步更合理的方向是：

- 保持当前“即时派发”的 runtime 语义不动
- 在 emitter 侧继续引入更强的目标 batch 数驱动合并策略
- 把 batch 数进一步从 `4662` 压向 `1000`
- 每做一轮合并都继续用同一套 `50k` 口径复测，确认性能没有再次被 dispatch 改坏
