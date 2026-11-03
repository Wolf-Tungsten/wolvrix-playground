# TNO0400：Gray-to-binary intrinsic 接入与 GrhSIM lowering

日期：2026-11-03。

本轮按“下一个 intrinsic 先做 Gray 码”开始实现。目标是把紧凑 `UInt` 上的
Gray-to-binary 组合语义保留下来，让 Wolvrix 在生成 C++ 时使用字级移位异或，
同时保留普通硬件生成路线。当前只完成可复查的 utility、Verilog、GRH 和 C++ fixture；
尚未把它接到一个真实的 XiangShan Gray-to-binary 调用，也没有整机 walltime 结论。

## 接口和选择

`testcase/xiangshan/utility/src/main/scala/utility/SimulationPrimitives.scala` 新增
`utility.GrayToBinary`。默认实现是硬件侧的对数级移位异或前缀：

```scala
var decoded = in
var shift = 1
while (shift < width) {
  decoded = decoded ^ (decoded >> shift)
  shift <<= 1
}
```

在一次 elaboration 中传入 `--wolvrix-sim-primitives gray-decode` 后，packed
`Bits/UInt` 改用版本化 transport `wolvrix_gray_decode_v1_w<N>`。输入和输出均为
`N` 位，输入为 Gray 编码，输出为同宽 binary；没有状态、时钟或副作用。没有提供
`Vec[Bool]`/`Seq[Bool]` 重载，避免隐式增加 gather/pack 成本。

## 生成证据

新增 fixture `testcase/chisel-intrinsic/GrayDecodeStudy.scala` 和驱动
`scripts/gray_intrinsic_study.py`。在 Chisel 7.3.0/firtool 1.135.0 下生成了 32 位
和 65 位两组 A/B：

- A 使用硬件前缀表达式，不含 DPI import；
- B 使用 `gray-decode`，保留 `import "DPI-C" context function` 作为 Verilog 中转；
- 32 位 ABI 承载为 `int`，65 位保持 packed `bit [64:0]`；
- `calls.json` 记录同一调用在 CHIRRTL 和 SystemVerilog 两次 elaboration 中的选择，
  两次均为 `GrayToBinary.Bits` intrinsic。

示例产物在 `/tmp/grhsim-gray-32-v3` 和 `/tmp/grhsim-gray-65`，属于临时验证目录，
正式代码路径不依赖这些文件。

## Wolvrix lowering

新增 `OperationKind::kGrayDecode`，并在导入层验证：版本化名称、逻辑输入宽度、同宽
输出、恒真 enable、无时钟调用和二态 DPI transport。导入后不保留 `kDpicCall`，而是
生成普通组合 SSA 操作。GRH JSON 中会出现：

```json
{"kind":"kGrayDecode","in":["in"],"out":["out"]}
```

GrhSIM C++ 对单机器字使用 `grhsim_gray_decode_u64`；多字值使用
`grhsim_gray_decode_words`，按 64 位字处理跨字移位并屏蔽尾字。已用 frontend 和
`grhsim32_pattern_emit` 检查 32/65 位生成结果：生成调度代码分别调用
`grhsim_gray_decode_u64(in, 32)` 和 `grhsim_gray_decode_words(in, 65)`，手工编译
生成源文件通过。

## 功能检查

- 32 位生成模型穷举 `0..65535` 个 Gray 输入，输出与移位异或参考实现一致；
- 65 位生成模型使用 100,000 个固定向量，输出与跨字参考实现一致；
- 32/65 位的 Scala 生成、Slang frontend、GRH operation 识别和 C++ lowering 均通过；
- `kGrayDecode` 已加入常量折叠、操作合法性检查、宽值形态统计和 SystemVerilog
  明确拒绝路径。

## 当前边界

扫描 XiangShan/Rocket-Chip 源码时，找到的是 `GrayCounter` 这类 Gray 编码器；尚未找到
可以直接替换、且不会改变异步 FIFO 指针语义的完整 Gray-to-binary packed 调用。因此
没有修改 AsyncQueue，也没有用 fixture 结果冒充 XiangShan 整机收益。下一步只有在找到
真实调用或明确加入一个等价 utility 调用后，才进行单线程 CPU96 walltime；届时仍应先
做同 binary A/A 控制，再解释小于当前噪声的差异。
