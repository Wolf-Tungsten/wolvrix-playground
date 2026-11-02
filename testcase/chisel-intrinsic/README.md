# IntrinsicExpr 的 Verilog 生成实验

本例只检查 Scala/Chisel → CHIRRTL → SystemVerilog。不会生成 GRH/C++ 仿真模型，
不会实现 DPI 函数，也不会运行仿真、等价验证或性能测试。

选择 64 位 PriorityEncoder：返回最低位的置位索引，输入全零时返回 64，输出宽度 7。
此前同语义微基准的生成计算体约 19.97 ns、软件位扫描约 1.51 ns；这个历史差值只用于
选择实例，不代表本例的 IntrinsicExpr 或 DPI 路径已经测得收益。

## Scala 参数

```scala
new PriorityEncoderIntrinsic(useIntrinsic = false) // 普通 PriorityEncoder + 零输入处理
new PriorityEncoderIntrinsic(useIntrinsic = true)  // IntrinsicExpr("circt_dpi_call", ...)
```

两种模式在 elaboration 时选择，顶层都叫 `PriorityEncoder64`，端口都是
`in: UInt<64>` 和 `index: UInt<7>`。文件必须分目录使用，不能把同名顶层同时加入 filelist。

`probeCustomName = true` 是单独的负例：直接使用自定义 `wolvrix_ctz64_or64` intrinsic 名称。
当前 firtool 会报 `unknown intrinsic`。名称本身不能替代对应的 compiler lowering。

## 复现

使用当前 XiangShan 已生成的 Mill classpath：Scala 2.13.17、Chisel/plugin 7.3.0，
firtool 1.135.0。该脚本只调用 Scala 编译器和 ChiselStage。

```bash
python3 scripts/chisel_intrinsic_emit.py \
  --output wolvrix/build/artifacts/chisel-intrinsic/new-emission \
  --probe-custom-name
```

输出目录必须是新目录。默认生成常规版和 DPI intrinsic 版；也可用
`--mode rtl` / `--mode intrinsic` 单独生成。自定义名称负例的失败会明确记录在
`summary.json`，不作为主路线成功。

## 实测生成形态

普通版是 138 行、63 个 `?` 的组合优先选择链。IntrinsicExpr 版是 22 行，核心内容为：

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

这里选择的是已有 `circt_dpi_call` intrinsic 的组合模式，`isClocked=0`、enable 恒真。
因为指定了 `outputName`，实际生成的 ABI 是 `void` 加 `output int`，不能误写成返回 int
的函数。7 位结果不能直接作为该版本的 DPI 标量类型；实验使用 32 位返回通道，再取
低 7 位，保持顶层端口相同。

此处仅有函数声明和调用，没有函数实现。普通 RTL 与 intrinsic 版没有做行为等价或
四态语义验证；约定的功能语义来自二态实例。行数变少不能当作仿真加速证据。

记录和实际文件见 [TNO0389](../../pdocs/grhsim_opt_thj/TNO0389_intrinsic_expr_priority_encoder_verilog_20261030.md)。
