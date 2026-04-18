# Activity-Schedule Tail Merge 阶段记录（2026-04-19）

这份记录用于收口本阶段已经完成的 `activity-schedule` 修改，重点说明：

- special partition 语义已经从旧的 `sink-dom` 模型切换到新的 `sink-supernode + tail-supernode` 模型
- 相关旧参数与旧草案文档已经移除
- 为了让回归测试通过，顺手修了两处 `emit-grhsim-cpp` 的生成问题

## Commit 锚点

| 仓库 | 路径 | commit |
| --- | --- | --- |
| `wolvrix-playground` | `/home/gaoruihao/wksp/wolvrix-playground` | `fe9acb5787486ddfd346b62ff2dbecb830ee81b1` |
| `wolvrix` | `/home/gaoruihao/wksp/wolvrix-playground/wolvrix` | `0fc3c750053249c05662f5033aeabfd12ddbfa4e` |

说明：

- 本记录对应的是当前工作区状态，不是一个已经提交的独立 commit
- `wolvrix` 当前仍有未提交修改，见下文“修改文件”

## 本阶段目标

本阶段的直接目标有三件事：

1. 把 `activity-schedule` 从旧的 `dom-sink` 局部吸收切到新的 `tail-supernode` 反向合并语义。
2. 删除已经失效的 `-max-dom-sink-supernode-op` 参数和与其绑定的旧设计文档。
3. 把相关 transform / emit 回归重新跑通，保证当前代码树是自洽的。

## 核心实现变更

### 1. special partition 改为 `sink-supernode + tail-supernode`

主改动在：

- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/lib/transform/activity_schedule.cpp`

当前流程变为：

1. 先识别 `sink op`
2. 按 topo 顺序分块生成 `sink-supernode`
3. 再从 residual DAG 的尾部按 reverse topo 扫描，生成 `tail-supernode`
4. 然后仅对剩余未覆盖区域走普通 `coarsen + DP + refine`

新 `tail-supernode` 的判断规则已经固定为：

- 如果某个 residual op 只服务一个已存在的 `tail-supernode`，则直接吸收进去
- 如果某个 residual op 没有 residual supernode 后继，或者同时服务多个 supernode，则它自己成为新的 tail seed
- 这里的“多个 supernode”包括：
  - 多个 `tail-supernode`
  - `tail-supernode + sink-supernode`
  - 多个 `sink-supernode`

也就是说，旧的：

- `collectDomSinkSeedTopoPositions(...)`
- `buildDomSinkPartition(...)`
- “只服务某一个 op”式的局部闭包

已经被新的：

- `collectResidualConsumerSupernodes(...)`
- `buildTailPartition(...)`
- “只服务某一个 supernode”式反向吸收

替换。

### 2. 统计与日志字段同步切换

当前 `activity-schedule` summary / timing 中，旧的 `dom_sink_*` 统计已经全部替换为：

- `tail_supernodes`
- `tail_initial_seed_ops`
- `tail_shared_seed_ops`
- `tail_absorbed_ops`
- `tail_ops`

这样后续排查时，可以直接看出：

- 初始尾部 seed 有多少
- 共享前驱被单独立种子的数量有多少
- 真正被吸收到 tail-supernode 里的前驱有多少

### 3. 移除旧参数

已经删除：

- `ActivityScheduleOptions::maxDomSinkSupernodeOp`
- CLI 参数 `-max-dom-sink-supernode-op`

对应文件：

- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/include/transform/activity_schedule.hpp`
- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/lib/core/transform.cpp`

现在 special partition 只保留一个显式额外阈值：

- `-max-sink-supernode-op`

`tail-supernode` 本身不再有独立 size limit 参数。

## 文档收口

### 1. 正式文档已更新

已更新：

- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/docs/transform/activity-schedule.md`

目前正式文档已经只描述当前生效语义：

- `sink-supernode`
- `tail-supernode`
- `supernode-max-size` 只约束普通 coarsen / DP / refine，而不约束 tail special partition

### 2. 旧草案已删除

本阶段已经删除两份过时草案：

- `/home/gaoruihao/wksp/wolvrix-playground/pdocs/draft/activity-schedule-sink-dom-sink-coarsen-plan.md`
- `/home/gaoruihao/wksp/wolvrix-playground/pdocs/draft/activity-schedule-post-sink-aggressive-merge-plan.md`

删除原因：

- 第一份描述的是已经被放弃的 `dom-sink` 设计
- 第二份描述的是已经实现完成的过渡草案
- 再保留会造成“正式实现、正式文档、草案设计”三份语义同时存在，容易误导后续修改

## 测试调整

主改动在：

- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/tests/transform/test_activity_schedule_pass.cpp`

这轮测试调整的重点不是简单改字符串，而是把预期整体切到新语义：

### 1. 纯 output 尾链不再看 DP 分段

以前有两条测试默认认为：

- 纯输出链会先走普通 DP 分段
- 因此会被切成两个 bounded supernode

在新实现下，这类图会直接被识别为纯 `tail-supernode`，所以现在改为验证：

- 整条输出尾链会合成一个 tail-supernode

### 2. sink-fed exclusive chain 会整体吸收

`top6` 现在验证：

- 喂给 sink 的独占三段链会全部并入一个 tail-supernode
- 不再受已经删除的 `max-dom-sink-supernode-op` 影响

### 3. shared predecessor 的预期切到“按 supernode 共享”

`top7/top8/top9/top11` 的断言已经改成验证下面几种情况：

- 被两个消费者 supernode 共享的前驱，不会错误吸进某个 tail-supernode
- 同时服务 sink 和 output 的 seed，会自己形成新的 tail-supernode
- 如果某个前驱最终只服务同一个 tail-supernode，即使它最初是多 op shared，也允许被吸收

## 额外修复：emit-grhsim-cpp

在回归 `emit-grhsim-cpp` 时，遇到了两处和本轮 transform 改动不直接相关、但会阻塞测试通过的 emitter 问题，因此一并修复。

改动文件：

- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/lib/emit/grhsim_cpp.cpp`

### 1. bool state-write range helper 生成条件过宽

现象：

- emitter 会生成 `apply_scalar_state_write_bool_range(...)`
- 但某些 case 下类里并没有对应的 `state_logic_bool_slots_ / state_shadow_bool_slots_`
- 结果生成物编译失败

修复：

- `modelUsesScalarStateWriteKind(...)` 现在除了检查 `value` slot，还会检查对应 `state_logic` / `state_shadow` slot 是否存在
- 只有 slot 完整存在时才允许生成对应 range helper

### 2. `kActiveFlagBitsPerWord` 没有进入生成类作用域

现象：

- `grhsim_top_eval.cpp` 用到了 `kActiveFlagBitsPerWord`
- 但生成 header 没有把这个常量声明进类里
- 结果生成物编译失败

修复：

- 在生成类 header 时，把 `kActiveFlagBitsPerWord` 作为类内 `static constexpr` 一并输出

## 本阶段修改文件

当前阶段性修改集中在下面 6 个文件：

- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/docs/transform/activity-schedule.md`
- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/include/transform/activity_schedule.hpp`
- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/lib/core/transform.cpp`
- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/lib/emit/grhsim_cpp.cpp`
- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/lib/transform/activity_schedule.cpp`
- `/home/gaoruihao/wksp/wolvrix-playground/wolvrix/tests/transform/test_activity_schedule_pass.cpp`

## 验证结果

本阶段结束时，已通过下面两组聚焦测试：

```bash
ctest --test-dir wolvrix/build --output-on-failure -R "transform-activity-schedule|emit-grhsim-cpp"
```

结果：

- `emit-grhsim-cpp`：`Passed`
- `transform-activity-schedule`：`Passed`

总耗时约：

- `73.76 sec`

## 当前结论

到本阶段结束，可以认为：

1. `activity-schedule` 的 special partition 语义已经正式切换到 `tail-supernode` 模型。
2. 旧的 `dom-sink` 参数、旧的 `dom-sink` 草案、旧的测试预期都已清理。
3. 当前 transform 侧和 `emit-grhsim-cpp` 侧的聚焦回归已经重新打通。

## 后续建议

下一阶段如果继续推进，建议优先做下面两件事之一：

1. 在 XiangShan / GrhSIM workload 上补一次真实数据记录，观察：
   - `tail_supernodes`
   - `tail_initial_seed_ops`
   - `tail_shared_seed_ops`
   - `tail_absorbed_ops`
   - 最终 `dag_edges`
2. 继续看 tail 合并后对：
   - supernode DAG 边数
   - `grhsim` fixed-point round 行为
   - 生成 C++ 体量
   的实际影响，再决定是否需要额外的 special partition 约束或统计项
