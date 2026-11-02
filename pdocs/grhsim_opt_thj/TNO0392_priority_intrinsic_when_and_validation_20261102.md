# TNO0392：条件调用与原语契约回归

日期：2026-11-02。实施中；本记录不包含性能结论。

接续 [TNO0391](./TNO0391_priority_intrinsic_integration_progress_20261102.md)。

## 整机首次失败及修复

`priority_intrinsic_20261102_v3/B` 的 Chisel RTL 成功生成，但 Wolvrix 导入
`Uncache.sv:1000` 时拒绝了动态 enable。来源是 `Uncache.scala` 的 merge
方法在外层 `when` 内调用 PriorityEncoderWithFlag。虽然 IntrinsicExpr 的显式
enable 为 true，Chisel/FIRRTL 仍把外层条件并入调用使能，非命中分支赋 X。

没有放宽 Wolvrix 的纯组合契约，也没有修改生成 Verilog。utility 的 CTZ 实现
改为在一个无时钟 RawModule 中声明 IntrinsicExpr：模块内使能恒真，调用者的
条件只影响普通数据连线/使用位置。随后正常 hier-flatten 消除模块边界。
调用位置和显式同名 import 不变，普通硬件路线不增加这个模块。

失败目录和日志保留。修复后的完整 A/B 从 Chisel 重新生成到
`build/xs/priority_intrinsic_20261102_v4`，不把首次失败的数据纳入测量。

## 当前验证与工具身份

- 8 位打包/分散输入小例子的模块包装、导入与 C++ 生成通过。
- 专项补入 `when` 条件调用、空 Seq、未知位宽以及失败后作用域恢复。
- native CTZ 专项通过序列化、来源、常量折叠、CSE、DCE、活动来源及跨组变化检测。
- 不支持 CTZ 的 SystemVerilog 后端现在明确报错，避免默认分支静默漏发。
- 11 项 Python 用例通过，包括版本/签名/使能拒绝、普通 DPI 保留、单线程日志与
  NUMA 审核、A/B 顺序、逐字段轨迹比较。比较器忽略 C padding 和无效载荷，但拒绝
  有效字段、周期、记录数量或顺序不一致。
- 首次工具冻结只复制 Python 扩展仍会通过 RUNPATH 使用构建目录里的动态库。
  v4 冻结同时复制 `libwolvrix-lib.so`，用 LD_LIBRARY_PATH 指向冻结目录，并保存
  `ldd.txt` 和两个二进制的 SHA256。A/B 必须加载这一套相同的库。

## 实验矩阵

当前香山 466 个 utility 调用包含 15 种位宽：
1、2、4、5、6、7、8、9、10、14、16、32、36、38、64。
相对于预定矩阵新增 5、6、10、14、36、38 位，共 31 个位宽，打包/分散两种布局。
早期 matrix-v1 的 62 个构建完成，但它使用修复前包装；保留为失败前证据，不作为
最终版本性能数据。matrix-v2 的条件测试漏启用 verification layer 的内联选项，
在进入矩阵构建前被缺失 include 拒绝；修复测试发射选项后重建 matrix-v3。

后续正式测量只使用通过完整功能检查且运行时文件页、匿名页、亲和性和 SMT
检查通过的版本；任何失败样本保留，不因速度删除样本。
