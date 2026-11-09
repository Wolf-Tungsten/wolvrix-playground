# TNO0450：整数与位运算行为模型局部性能比较（2026-11-07）

本轮在现有 fixture 上比较 ordinary 与 `kBehaviorComputeGroup` grouped lowering。计时包含输入准备、完整 `eval` 边界和输出摘要；不包含模型构建或文件加载。每个场景先 warmup 一次，再做 8 对交替 AB/BA，固定种子为 `42 + pair`，每对检查 ordinary/grouped 输出哈希一致。

## 结果

百分比定义为 `grouped / ordinary - 1`，负值表示 grouped 更快。

| 模型 | 场景 | 平均变化 | bootstrap 95% CI | grouped 更快 |
|---|---|---:|---:|---:|
| `int-alu` | active | -78.659% | [-79.929%, -77.385%] | 8/8 |
| `int-alu` | sparse | -81.685% | [-83.204%, -80.737%] | 8/8 |
| `int-alu` | idle | +2.942% | [-2.082%, +7.866%] | 2/8 |
| `int-bku` | active | -89.906% | [-90.149%, -89.651%] | 8/8 |
| `int-bku` | sparse | -86.783% | [-88.095%, -85.504%] | 8/8 |
| `int-bku` | idle | +0.104% | [-5.889%, +6.437%] | 5/8 |
| `vec-int-alu-lane` | active | -91.011% | [-91.609%, -89.932%] | 8/8 |
| `vec-int-alu-lane` | sparse | -92.121% | [-93.849%, -90.094%] | 8/8 |
| `vec-int-alu-lane` | idle | -1.729% | [-28.377%, +27.173%] | 5/8 |
| `vec-int-pu-lane` | active | -72.214% | [-74.938%, -69.887%] | 8/8 |
| `vec-int-pu-lane` | sparse | -48.146% | [-48.934%, -47.146%] | 8/8 |
| `vec-int-pu-lane` | idle | -22.331% | [-34.017%, -10.686%] | 6/8 |

active/sparse 场景中，四类模型都满足局部的 5% grouped 加速门槛；idle 场景中只有 VIPU lane 的区间保持负值，其他三类区间跨零或方向轻微回退。所有 12 个场景的 ordinary/grouped 摘要逐对一致。

## 解释与边界

收益来自把 carrier 内部的切片、选择树、逐 lane 逻辑和辅助节点合并为一个已认证的纯计算 helper。结构矩阵中 grouped 每个模型只有一个 `kBehaviorComputeGroup`，而 ordinary 保留数千个普通 GRH 操作；因此该结果直接验证了分组节点对无状态整数行为模型的局部仿真价值。

hardware 版本只作为同一 fixture 的结构参照，未把它和 behavior 版本的内部流水状态差异混入 grouped/ordinary 主结论。whole-unit 模型没有参与测量，仍由 XiangShan wrapper 拒绝。

原始产物保存在 [integer-bit-local-measure-20261107](../../wolvrix/build/artifacts/behavior-model/integer-bit-local-measure-20261107/)；其中包含 manifest、逐对 CSV/JSON、运行摘要、输入输出哈希和 benchmark 源码使用的模型身份。测量使用 node030、CPU96、单线程、10,000 个 fixture 周期；按当前请求未执行 CPU 空闲预检。

本结果只决定局部候选优先级，不直接代表 XiangShan 整机收益。下一步若要进入整机，应分别选择通过 active/sparse 门槛的模型，保留完整 DiffTest/NEMU，并重新做 100,000 周期功能门和整机 AB/BA；默认配置仍保持 hardware。
