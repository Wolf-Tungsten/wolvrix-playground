# TNO0443：标量与向量乘法行为模型实现及局部功能验收（2026-11-05）

## 实现范围

新增显式模型选择 `int-mul`、`vec-int-mul`、`fp-mul`、`vec-fp-mul`，支持逗号组合。
默认 `hardware`，现有 `commit-rat` 继续兼容；只有 commit-rat 应用原先的单核、完整 DiffTest
和同步复位限制。乘法模型使用 `observer_only=false`、ordinary GRH，不增加 intrinsic 或状态节点。

YunSuan 构造参数 `behavior: Boolean = false` 由真实 XiangShan FU wrapper 传入；YunSuan
不增加 utility 依赖。manifest 记录实际模块、逐端口位宽、乘积宽度、流水延迟与使能端口。

| 模型 | 实际模块 | 行为描述 |
|---|---|---|
| 标量整数 | scalar.Mul | 固定 128-bit 乘积及高半符号修正，含 MULW/MULW7；保持两级使能寄存器 |
| 向量整数 | VIMac64b | SEW8/16/32/64 逐元素乘法、乘加减、加宽、舍入和饱和；保持两级寄存器 |
| 标量浮点 | fpu.FloatFMA | 53/24/11-bit 有效数的精确整数乘积，替换 Booth/CSA 乘法核心 |
| 向量浮点 | VectorFloatFMA | 各 lane 精确有效数乘积，按原 CSA 边界布局接回融合累加 |

浮点保留原三拍整体延迟、对阶、融合累加、规格化、舍入、NaN boxing、特殊值和 fflags；
未使用宿主 float/double。乘积没有提前舍入，各 lane 没有交叉乘积。
行为源码通过 `MultiplyBehavior.pipeline` 隐藏流水寄存器展开，payload 保持无复位，valid
继承原复位类型。外围 ROB、flush、握手、时钟门控和向量 mask/tail/vstart 合并不改。

## Wolvrix 乘法位宽修正

首轮标量浮点 B 的生成 C++ 编译失败：拼接中的 53×53 乘法被 importer 扩展为 212 位，
而不是 firtool 已明确生成的 106 位表达式，导致 mux 的 word-array 类型不匹配。

`ingest.cpp` 现在对没有额外 width context 的乘法采用 slang 解析后的表达式宽度，不再把
左右位宽相加。增加 stmt-lowerer 用例检查 53-bit self-determined、106-bit 零扩展完整乘积、
128-bit assignment-context 三种情况，`ingest-stmt-lowerer` 通过。
不通过增加特殊乘法节点规避错误。修正后原语进入现有 `kMul`，宽输入走 unsigned __int128 helper。

原失败产物 `local-v1/local-v2` 保留；最终本地构建为
`wolvrix/build/artifacts/multiply-behavior/local-v3/`，同时冻结 Python 包、扩展和 native 动态库，
通过 ldd 确认实际库路径。A/B 使用相同修正后的工具。

## 功能验证

- 四类 × A/B，共八个模型，每个三个固定种子 × 10,000 周期。整数使用 Python 任意精度独立参考，
  浮点使用本机 NEMU 附带的 RISC-V SoftFloat 源码，在独立产物目录构建参考库。
- 比较有效结果位、全部 fflags/vxsat、流水 valid；复位、气泡、连续输入、长空闲、重复 eval 和
  高电平修改输入后不重复提交均通过。不比较未初始化的无效 payload。
- 标量整数覆盖六种操作及边界；向量覆盖 signed/unsigned、各 SEW、高半、加宽、乘加减、四种
  vxrm 和饱和；浮点覆盖 FP16/32/64、五种舍入模式、特殊值、subnormal、NaN boxing、FMA 与加宽。
- 向量浮点首次 reference mismatch 同样发生在 A；原因是参考程序误读了加宽输入 lane 顺序。
  按实际输入布局修正 oracle 后 A/B 均通过，失败日志保留。
- 真实 FU wrapper 四类各 30,000 周期 A/B 对照通过，包含 flush、ready、mask/tail/vstart、
  scalar/vector 结果及最终标志合并。此测试与 core 的独立数学参考互补，不冒充 ISA 级证明。
- 原始 YunSuan HEAD 与当前默认 hardware 的 RTL，去掉注释/空白后四类逐字一致。
- `xiangshan.test.compile` 通过；模型选择拒绝未知/重复/空项；不运行全量回归。

复现入口：`scripts/multiply_behavior_study.py`、`multiply_behavior_check.py`、
`multiply_wrapper_check.py`、`multiply_hardware_audit.py`。原始日志与结果位于
`wolvrix/build/artifacts/multiply-behavior/`。

## 结构证据与后续门槛

采用完整生产 reg-to-mem、activity schedule 和 emitter 配置：

| 模型 | A 最终 ops | B 最终 ops | A compute supernodes | B compute supernodes |
|---|---:|---:|---:|---:|
| 标量整数 | 2,689 | 85 | 33 | 1 |
| 向量整数 | 5,311 | 1,039 | 60 | 11 |
| 标量浮点 | 11,760 | 5,608 | 129 | 57 |
| 向量浮点 | 17,156 | 10,520 | 180 | 105 |

B 的 kMul 输出分别为 128；16/32/64/128；22/48/106；22/48/106 位，未出现 130/212 位乘法。
局部收益单独归档；只有局部 active/sparse 稳定快约 5% 以上且 idle 无可信回退的类别进入完整
S3。整机保留全部 DiffTest/NEMU，另建定向指令负载，不用 CoreMark 代替浮点/向量覆盖。

## 增量验证：有效数精确乘积边界

`product-boundary-v1/summary.json` 通过额外 30,000 周期检查：原标量/向量 Booth+流水 CSA 的
乘积字段，与直接乘法在对应原流水边界逐拍一致，分别核对 106/48/22-bit 有效乘积及各 lane
的布局，忽略不参与计算的间隔位。完整 FMA 结果/异常标志仍由前述 SoftFloat 检查独立验证。
