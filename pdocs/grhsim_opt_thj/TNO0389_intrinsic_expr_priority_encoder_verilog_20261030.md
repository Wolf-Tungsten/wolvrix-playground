# TNO0389：IntrinsicExpr 的 PriorityEncoder64 Verilog 生成实验

日期：2026-10-30。状态：生成和文本检查完成，按用户要求停在 SystemVerilog。
本轮没有 GRH 导入、C++ 模型生成、DPI 实现、仿真、等价验证或新的性能测量。

## 实例选择与边界

选择独立的 64 位最低位优先编码器：输入 UInt<64>，返回最低位的 1 的索引，输入
全零时返回 64，输出 UInt<7>。没有时钟、寄存器、复位或其他状态。

选择依据是既有 [priority64 微基准](../../wolvrix/build/artifacts/chisel-pattern-study/node030-normalized-v5/cases/priority64/summary.json)：
random 分布下，生成组合计算体中位数 19.9731 ns，软件位扫描 1.51388 ns，8 对 AB/BA
配对降幅中位数约 92.41%。这只是同功能的历史选例依据；当时没有经过 DPI 调用，
不能作为本轮 IntrinsicExpr 或 DPI 路线的性能结论，也不代表香山整机收益。

本例是独立 RawModule，没有修改香山生产 Scala、utility 或当前基线 binary。

## Scala 开关及实际语义入口

源文件：[PriorityEncoderIntrinsic.scala](../../testcase/chisel-intrinsic/PriorityEncoderIntrinsic.scala)。

```scala
new PriorityEncoderIntrinsic(useIntrinsic = false)
new PriorityEncoderIntrinsic(useIntrinsic = true)
```

false 使用普通 `Mux(in.orR, PriorityEncoder(in), 64.U(7.W))`。
true 直接调用现有 Chisel `IntrinsicExpr`：

```scala
val encoded = IntrinsicExpr(
  "circt_dpi_call", UInt(32.W),
  "functionName" -> StringParam("wolvrix_ctz64_or64"),
  "isClocked" -> IntParam(0),
  "inputNames" -> StringParam("value"),
  "outputName" -> StringParam("index")
)(true.B, in)
index := encoded(6, 0)
```

这是当前 firtool 已认识的 `circt_dpi_call`，不是已经新增了 Wolvrix 自定义 intrinsic。
Scala 开关在 elaboration 时选择；两个顶层名称及端口完全相同，分别放在独立目录。

另外保留 `probeCustomName=true` 负例，尝试：

```scala
IntrinsicExpr("wolvrix_ctz64_or64", UInt(7.W),
  "inputWidth" -> IntParam(64), "zeroResult" -> IntParam(64))(in)
```

它成功进入 CHIRRTL，但当前 firtool 报 `unknown intrinsic "wolvrix_ctz64_or64"`，
无法输出 SystemVerilog。自定义名称不会自动变成可执行的软件操作或合法 SV 函数。
Chisel API 能记录名称、类型、参数和输入，不等于 firtool 对任意新名字都有实现，见
[固定版本的 IntrinsicExpr 源码](https://github.com/chipsalliance/chisel/blob/v7.3.0/core/src/main/scala/chisel3/Intrinsic.scala)。

## 工具版本与阶段

- node030，Scala compiler 2.13.17。
- Chisel 7.3.0 / chisel-plugin 7.3.0，使用当前 XiangShan Mill classpath。
- CIRCT firtool 1.135.0，显式指定 binary 路径，未替换或修改 firtool。
- 独立 [生成脚本](../../scripts/chisel_intrinsic_emit.py) 只调用 Scala compiler 与 ChiselStage。
- 每条路线先保存 CHIRRTL，再尝试 SystemVerilog；失败路线保留原始错误日志。

## 生成的 Verilog

| 路线 | SV 生成 | 顶层接口 | 行数 | 条件运算符数 |
|---|---|---|---:|---:|
| 常规 RTL | 成功 | input [63:0] in / output [6:0] index | 138 | 63 |
| IntrinsicExpr / circt_dpi_call | 成功 | 相同 | 22 | 0 |
| 自定义名称负例 | 失败，unknown intrinsic | CHIRRTL 中保留接口 | — | — |

常规版为优先选择链，末端用 `7'h40` 定义零输入结果。它的 SV 文本没有恢复成 CTZ
语义操作。行数和条件表达式数量不是硬件面积、时序或仿真性能证据。

IntrinsicExpr 版的实际核心输出如下，省略 include guard、模块头和 SourceInfo 注释：

```systemverilog
import "DPI-C" context function void wolvrix_ctz64_or64(
  input  longint value,
  output int     index
);
reg [31:0] _GEN;
always_comb begin
  wolvrix_ctz64_or64(in, _GEN);
end
assign index = _GEN[6:0];
```

这里是 **context function void + output int**，不是 `int` 返回函数；这是指定
`outputName` 后实际生成的 ABI。调用在 always_comb 中，enable 恒真，无时钟端口。
函数仅有声明和调用，尚未提供实现，因此本轮成功的含义严格限于 Verilog 发射成功。
没有证明与普通 RTL 的行为等价或四态语义等价。

## 过程中确认的限制

1. 首次 Scala 编译把 Mux 从 chisel3.util 导入，包位置错误；已改为使用 chisel3._ 的 Mux。
2. 首次 DPI 试验直接使用 UInt<7> 返回类型，被 firtool 拒绝。该版本的 DPI 整数标量
   接受 1/8/16/32/64 位，或更宽的类型，不接受 7 位。最终使用 32 位通道再取低 7 位。
3. 自定义名称被拒绝的结果完整保留，没有修改后端、绕过未知操作检查或提供空实现。

三轮目录依次为 `priority64_20261030`、`priority64_20261030_v2`、
`priority64_20261030_v3`。每轮源文件和驱动已按 manifest 哈希核对并存档。
前两轮失败没有混入最终成功结果。

## 产物与复现

最终目录：`wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/`。

- [普通 Verilog](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/rtl/PriorityEncoder64.sv)
- [IntrinsicExpr Verilog](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/intrinsic/PriorityEncoder64.sv)
- [IntrinsicExpr CHIRRTL](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/intrinsic/PriorityEncoder64.fir)
- [自定义名称的原始拒绝日志](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/custom-name-probe/emit.log)
- [Verilog 差异](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/verilog.diff)
- [分路线状态与接口检查](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/summary.json)
- [输入、jar 和工具身份](../../wolvrix/build/artifacts/chisel-intrinsic/priority64_20261030_v3/manifest.json)
- [使用说明](../../testcase/chisel-intrinsic/README.md)

在仓库根目录运行，输出目录必须是新目录：

```bash
python3 scripts/chisel_intrinsic_emit.py   --output wolvrix/build/artifacts/chisel-intrinsic/new-emission   --probe-custom-name
```

主路线成功与自定义名称负例失败分别记录。最终检查确认两个生成顶层端口一致，
Python 编译与 diff 检查通过；目录中没有生成 C++ 模型或对象文件。
本轮工作到此停止。
