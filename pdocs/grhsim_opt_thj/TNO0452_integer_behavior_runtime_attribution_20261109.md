# TNO0452：整数行为模型的运行时归因（2026-11-09）

本轮没有继续增加行为模型，而是给现有 `kBehaviorComputeGroup` carrier 加入独立的 runtime profile 版本。profile 版本才编译计数器和 phase timing；默认模型和正式 walltime 入口不带这些字段。计数包括行为 helper 调用、输入活动、输出变化、输出未变化、处理的 word 数，以及 supernode fire、eval、compute/commit batch、state shadow 和 write 统计。

## 配置与负载

A 复用已验证的全硬件 `integer_bit_20261107_v1/A` RTL，B 复用 grouped `int-alu,int-bku,vec-int-alu-lane,vec-int-pu-lane` 的 `.../B` RTL。两组都重新经过相同的 profile emit/compile，保留完整 DiffTest/NEMU；profile binary 只用于归因，不用于正式性能结论。两类 100,000 周期负载均完成 10,000 周期 smoke、100,000 周期 warmup 和一次最终 profile run：

- `coremark-2-iteration.bin`；
- `microbench.bin`，包含 qsort、queen 等已有整数/位操作路径。

运行固定 CPU96、单线程和 NUMA locality 检查；按当前实验要求跳过外部 CPU 空闲 admission。原始 profile、phase 日志和机器可读汇总保存在 [`integer-bit-profile-20261109`](../../wolvrix/build/artifacts/behavior-model/integer-bit-profile-20261109.json) 与同目录的 profile 输出中。

## 动态工作量

| 负载 | B helper calls | B word iterations | compute batch executions | helper / compute batch | int-alu | int-bku | vector helpers |
|---|---:|---:|---:|---:|---:|---:|---:|
| CoreMark | 249,005 | 842,579 | 26,476,098 | 0.9405% | 226,179 | 22,821 | 5 |
| microbench | 202,640 | 677,002 | 26,476,098 | 0.7654% | 187,036 | 15,599 | 5 |

两类负载都执行了 200,102 次 model step/eval。B 的行为 helper 只占不到 1% 的 compute batch；向量 helper 在这两个负载中各只执行 5 次。剩余绝大多数工作仍是普通 compute、状态读取、commit 和 DiffTest 相关路径。

profile binary 的 phase timing 也没有显示行为 helper 改变主循环成本：

| 负载 | model step A→B | single-cycle A→B | DiffTest phase A→B | commit batch A→B |
|---|---:|---:|---:|---:|
| CoreMark | −0.3092% | −0.3102% | −1.4069% | +3.3333% |
| microbench | −0.2167% | −0.2165% | +0.3323% | +3.3333% |

B 的 compute batch 次数与 A 完全相同，state shadow 和 touched write 也相同；B 的 commit batch 次数反而增加 3.33%。这说明 carrier helper 的少量计算被调度和提交工作淹没，当前后端边界没有减少主循环中的 batch 工作。

静态图变化同样很小：B 相对 A 的 `graph_ops`、supernode 和 profile binary 分别约减少 0.387%、0.573% 和 0.579%。局部 fixture 中观察到的 carrier 加速不能直接外推到整机。

## 结论与后续方向

现有四类整数行为模型不是完整 XiangShan eval 的热点。继续扩大 carrier 覆盖或优化 helper ABI，预计只能影响不到 1% 的动态 compute 调用，收益会被通用 activity scheduler、commit batch 和 DiffTest observer 成本稀释。下一步应优先归因并优化 observer/Gateway、state-read activation、commit batch 的空调用或通用 activation guard；暂不新增行为模型，也不把 `kBehaviorComputeGroup` 设为默认 lowering。

完整 profile 的输出变化列在这版香山图中没有形成有效的 boundary change 样本，因为 carrier 结果多数不是已有 event/fanout 路径；同一计数逻辑在小型 fixture 中已验证能区分 69 次变化和 31 次未变化。该限制不影响 helper、batch 和 phase 的热点判断。
