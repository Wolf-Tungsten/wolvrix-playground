# TNO0448：整数与位运算行为模型 carrier 闭环（2026-11-07）

本轮把 `kBehaviorComputeGroup` 从乘法扩展到标量整数和位运算。模型作者通过显式 `HostOpSpec` 描述操作集合、位宽、signedness、lane 宽度、移位掩码和 native/fallback 类别；没有修改全局 `UInt` 运算符。

## 已接入路径

- `int-alu`：XiangShan `Alu` 的 64 位 carrier，覆盖加减、比较、移位、rotate、word 操作、bit-manip、misc、Zicond 和 PC-relative 输入。`aluNeedPc` 使用独立的稳定 carrier 端口布局。
- `int-bku`：`Bku` 的 Count、CLMUL 和 XPERM carrier；CryptoModule 保持原硬件路径。carrier 结果在原有两级外部流水中提交，crypto 指令仍由原模块处理。
- `vec-int-alu-lane` / `vec-int-alu-whole`：`VIAluFix` 已接入无寄存器的 adder/misc/S1 carrier，外层保留原有一拍边界；两种选择互斥。当前 host helper 覆盖 add/sub 和基本位逻辑，饱和/narrow/mask 结果仍由 carrier 的完整 Chisel 回退验证。
- `vec-int-mac-lane` / `vec-int-mac-whole`：复用已有 VIMac 纯 lane 算术 carrier，并把边界写入 manifest；两种选择互斥。`vec-int-mul` 继续作为旧兼容名称。

- `vec-int-pu-lane` / `vec-int-pu-whole`：新增 `VIPUComputeCarrier`，覆盖单 uop、`vlmul=0` 的 `vcpop.m`、`vfirst.m`、`vmsbf.m`、`vmsif.m`、`vmsof.m`、`viota.m`、`vid.v` 和 `vmv.x.s`。carrier 只处理无状态的当前 128 位片段；需要跨 uop 保存累加器的 reduction 和 mask 累积继续走原 `VIAlu` 状态机。wrapper 的显式 guard 保证不把不完整 carrier 用到多 uop 路径。

`vec-int-alu-whole`、`vec-int-mac-whole` 和 `vec-int-pu-whole` 仍保留为 fixture/manifest 边界契约，但 XiangShan wrapper 现在会明确拒绝启用它们；它们尚未把整个向量 merge、mask/tail/vstart 或跨 uop 状态纳入 carrier。这样不会把 lane carrier 冒充成完整 whole-vector 模型。

当前统一 fixture matrix 已同时生成硬件、ordinary 和 grouped 结果（PU 仅生成已支持的 lane 子集）。Scalar ALU/BKU 和 VIAlu lane 的硬件/行为图均通过 manifest 检查；grouped 图各自收敛为一个 `kBehaviorComputeGroup`，ordinary 图保留展开后的 carrier 逻辑。机器可读结果保存在 `wolvrix/build/artifacts/behavior-model/integer-bit-matrix-20261107/matrix.json`。

## Wolvrix 变化

`kBehaviorComputeGroup` 的认证契约现在检查模型 ID、`none/lane-core/whole-unit` 边界、操作 ID 列表、端口宽度和语义 hash。C++ emitter 增加：

- `int-alu`：按 9 位 `ALUOpType` 分派宿主整数实现，显式处理 word 截断、符号扩展、shift mask、rotate、min/max、bit-manip 和 Zicond；
- `int-bku`：`std::countl_zero`、`std::countr_zero`、`std::popcount`、精确 carry-less multiply 和 XPERM fallback；
- `vec-int-pu-*`：按 559 位 `VIFuInput` carrier 解码单 uop mask/scalar 操作，使用 host `popcount`/`countr_zero` 和显式 prefix/index helper；129 位 `VIFuOutput` 的 `vxsat` 与高位截断显式处理；
- 现有 VIMac helper 继续服务新的 MAC boundary 名称。

未匹配的 carrier、端口、模型、边界或操作列表会在导入阶段报错，不会静默退回普通图。普通 SystemVerilog carrier 仍保留作为回退路径。

## 针对性验证

在不跑全量回归的前提下完成：

1. `mill -i xiangshan.compile` 通过；
2. Wolvrix `wolvrix-lib`、Python binding、`grhsim32_frontend` 和 `grhsim32_pattern_emit` focused build 通过；
3. `int-alu` ordinary/grouped fixture 均完成 Verilog→GRH→C++ 编译；
4. `int-bku` ordinary/grouped fixture 均完成 Verilog→GRH→C++ 编译；
5. grouped C++ fixture 检查了加法、算术右移、rotate、符号扩展、PC-relative、CLZ/CTZ/CPOP、CLMUL 和 XPERM 的固定向量；
6. `vec-int-alu-lane` ordinary/grouped fixture 的 basic add lane 固定向量通过；
7. `vec-int-mac-lane` 与 `vec-int-mac-whole` ordinary/grouped fixture 生成和编译通过。
8. `vec-int-pu-lane` 与 `vec-int-pu-whole` ordinary/grouped fixture 均完成 Verilog→GRH→C++ 编译；`vcpop/vfirst/vmsbf/vmsif/vmsof/viota/vid/vmv.x.s` 固定向量的普通/分组模型逐项通过。PU grouped helper 的 559 位输入布局和 129 位输出布局已与 emitted SV 对齐。

PU carrier 的 200,000 次输入变化局部循环仅作结构 sanity check：ordinary 约 0.107 s、grouped 约 0.0048 s；该数字不包含 XiangShan 调度、真实指令分布或 AB/BA 统计，不能作为整机收益结论。

本轮没有进行 XiangShan 整机 walltime 测量。默认配置仍为硬件 RTL；行为模型必须通过 `--wolvrix-sim-models` 显式选择，grouped lowering 必须通过 `--wolvrix-behavior-compute-lowering grouped` 显式开启。
