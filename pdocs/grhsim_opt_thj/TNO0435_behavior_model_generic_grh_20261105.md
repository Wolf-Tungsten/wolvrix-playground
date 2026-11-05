# TNO0435：Chisel 行为模型 API 与普通 GRH 状态基线（2026-11-05）

## 目的

为 DiffTest/debug 逻辑提供 elaboration 阶段可选的行为模型入口，并验证第一版是否
需要新增专用 GRH Register/Memory operation。性能目标是减少仿真运行时工作，而不是
只增加另一种表达方式。

## 实现

新增 `utility.SimulationModels` 和开关：

```text
--wolvrix-sim-models hardware
--wolvrix-sim-models commit-rat
```

API 支持输入、同步 register、小型 memory、更新条件和输出声明。模型生成
`simulation_models.json`，记录模型版本、observer-only、时钟/复位、状态、输入输出、
debug capability、检查输出和更新组。默认 `hardware` 模式不生成模型记录，也不改变原有 RTL。

`commit-rat` fixture 以两个长度为 32 的可索引状态数组表达架构寄存器和 RAT，声明 6 个
输入和 2 个状态输出。行为模型只需要两次 `array.update(valid, index, value)`，与硬件模型
具有相同的 Chisel 端口和更新语义。

## 验证

- XiangShan/utility focused Scala 编译通过。
- Python 驱动和 manifest 校验通过。
- hardware manifest 的 models 数为 0；commit-rat manifest 含两个 32 行 array state 和两组更新。
- 两个版本均由 Wolvrix frontend 和 GrhSIM C++ emitter 处理。
- A/B GRH operation 数均为 591，两个数组都沿现有普通 Chisel state 路径展开为 64 个
  `kRegister`、`kRegisterReadPort` 和 `kRegisterWritePort`，其他 operation kind 也完全一致。
- Clang 23/O2 生成模型通过 1,001 个采样点的随机 commit/RAT 状态轨迹比较。

## 结论

当前普通 `kRegister/kRegisterWritePort` 已能表达模型，并且 GRH 结构没有额外 operation
膨胀。现阶段不新增 `kBehaviorRegister/kBehaviorMemory`。后续只有在精简后的真实
DiffTest 模型中证明 generic state 更新是运行时热点，才增加分组级专用 lowering；该
lowering 必须显式暴露输入、状态、更新和输出依赖，不能退化为 BlackBox 或 opaque DPI。

本记录没有进行香山整机 walltime；下一步应先把 `commit-rat` 模型接到实际 DiffTest
字段裁剪和检查适配器，再测量 generic behavior path 与 S3 baseline。
