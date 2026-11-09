# TNO0449：整数与位运算行为模型统一功能矩阵（2026-11-07）

本记录补充 TNO0448 的固定向量检查，覆盖 ordinary 与 `kBehaviorComputeGroup` grouped lowering 的随机逐拍等价性。测试使用同一 generated model、同一 C++ 编译参数和同一输入序列；每个模型使用种子 `1`、`42`、`20261107`，每个种子 10,000 个周期，复位窗口为周期 `[0,4)` 和 `[5000,5004)`。无效载荷只在 fixture 的有效控制下参与摘要。

## 结果

| 模型 | ordinary digest | grouped digest | 结果 |
|---|---|---|---|
| `int-alu` | `9f481b66fe289f71` | `9f481b66fe289f71` | 通过 |
| `int-bku` | `4d8e9c144cc7b078` | `4d8e9c144cc7b078` | 通过 |
| `vec-int-alu-lane` | `d03e1b0a50502f7b` | `d03e1b0a50502f7b` | 通过 |
| `vec-int-pu-lane` | `1af25617a85280d6` | `1af25617a85280d6` | 通过 |

标量 ALU 检查覆盖已声明的 7 位 `ALUOpType` 值及 9 位 `FuOpType` carrier 的高位清零语义；BKU 覆盖 Count、CLMUL 和 XPERM 的有效操作。VIAlu lane 检查 SEW 8/16/32/64 的 add/sub 和基本位逻辑，并比较 `narrowVd` 与 compare sideband；VIPU 检查当前无状态单 uop 子集：`vcpop.m`、`vfirst.m`、`vmsbf.m`、`vmsif.m`、`vmsof.m`、`viota.m`、`vid.v` 和 `vmv.x.s`。

检查过程中修正了几个真实语义差异：ALU helper 只使用 `FuOpType` 低 7 位；补齐 `orh48`、XPERM.B 高位索引拒绝和 32 位 rotate；VIAlu helper 保留窄化结果以及 `vor/vnor` 共用 adder 产生的比较 sideband。修正后四类摘要完全一致。

## 结构矩阵

机器可读矩阵位于 [matrix.json](../../wolvrix/build/artifacts/behavior-model/integer-bit-matrix-20261107/matrix.json)，其中每个 grouped 载体都恰好导入一个 `kBehaviorComputeGroup`：

- `int-alu`：hardware 1,093 ops；behavior ordinary 1,093 ops；grouped 1 group。
- `int-bku`：hardware 3,820 ops；behavior ordinary 3,512 ops；grouped 1 group。
- `vec-int-alu-lane`：hardware 5,284 ops；behavior ordinary 5,048 ops；grouped 1 group。
- `vec-int-pu-lane`：behavior ordinary 4,067 ops；grouped 1 group。

whole-unit 选择仍在 XiangShan wrapper 中显式拒绝，因为它尚未包含完整 mask、tail、`vstart`、旧目的数据合并和跨 uop 状态契约；fixture/manifest 入口保留用于后续验证。

## 性能测量状态

本轮没有把 node030 的局部 walltime 记为结果。2026-11-07 18:57 CST 的 CPU96 sibling 为 `96,288`，但 CPU96–127 上存在多组持续约 8 倍 CPU 的 SPEC/NEMU 工作，无法满足连续空闲门禁。原始检查保存在 [node030-preflight.txt](../../wolvrix/build/artifacts/behavior-model/integer-bit-functional-20261107/node030-preflight.txt)。因此没有运行 active/sparse/idle 的 8 对 AB/BA，避免把外部负载误认为 grouped 收益；性能比较待区域满足空闲条件后按同一矩阵单独执行。

默认配置保持 `--wolvrix-sim-models hardware` 和 `--wolvrix-behavior-compute-lowering ordinary`；本记录只证明功能和结构闭环，不改变整机默认路径。
