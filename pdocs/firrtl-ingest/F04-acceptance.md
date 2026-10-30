# F04 类型、组合语义与聚合验收

实施日期：2026-10-30；验收完成：2026-10-31。分支为主仓及 wolvrix 的
`grh/firrtl-ingest`。实施基点为主仓 `a084efa`、wolvrix `c798118`；
wolvrix 实现提交为 `5be5cb9`。F04 已完成，功能回归、72 项 CTest 和
生成模型执行均已验证。

正式支持合约见
[firrtl-combinational.md](../../wolvrix/docs/ingest/firrtl-combinational.md)。
本阶段只完成纯组合 FIRRTL 读取；F05–F11 和 F00 剩余项继续保留原状态。

## 退出条件与证据

| 条件 | 实现及验证 |
| --- | --- |
| 独立类型、位宽、Reset 和 flow | `semantic.cpp` 的约束求解、Reset 类型联合与 Bundle flow 检查；32 组原语/转换形式分别用 UInt/SInt 的 1024 组输入对照数学预期，检查首次 simplify 前后结果；有界循环宽度收敛与求解资源上限分别回归 |
| FIRRTL 显式定宽和符号 | add/sub 多一位、mul 和 div/rem、signed bitwise 的 UInt 结果、比较、扩展/截断、静态/动态移位、cast、cat 和 reductions；额外验证 130/131 位十进制常量与零宽规则 |
| 连接顺序和条件 | 最后连接优先、整体/部分覆盖、最终连线读取、when/else、互补 Boolean 条件和条件内局部 wire；谓词 key 包含字面量类型/位宽，不错误合并两个 head 表达式 |
| 聚合几何 | Bundle 逐字段拆分；嵌套 Vector 保持 shape；flip 反向端口；extent=1、零宽/空 Vector、名称碰撞、别名中的推导宽度与 elementWidth 签名均有定向检查 |
| 相等、构造和布局 | 以规范允许的字段/元素连接、ground eq 和 cat 验证整体行为；拒绝非法的 aggregate primitive；逐元素位宽扩展使用 kArrayCreate，不把总宽扩展当成元素扩展 |
| 数组读取和动态写 | 多索引 kSliceArray 及后缀子数组；组合动态写用 O(rank) 位偏移和 mask 合并；32/4096 槽读取操作数量相同且没有逐槽 eq；动态越界及两次写入的优先级对照独立预期 |
| 真实 node 归属和根 | 每个物化叶子一份 schema v1 身份；Vector 不按元素造 key；内部 op、结果根、常量和透明 alias 可检查；引用已有定义不复制或重标生产者；首次 simplify 的内部 4 个 and 变为 3 个，跨 node 两份仍隔离 |
| 逻辑域和 invalid 策略 | 初始图所有值保持 FourState；默认 Unknown 生成 X，显式 Zero 用于数值回归；graph metadata 保存策略；GrhSIM 走现有显式投影 |
| 普通 GRH 到 GrhSIM 实际执行 | 三个源 fixture 经读入、现有优化/分图和 CPU emitter 后，生成 Makefile，再由项目 Make target 编译并执行模型；含基础 node/when、聚合读写和 signed 算术 |
| 错误诊断及读取原子性 | 类型/位宽/Reset/索引/flow/const、缺少覆盖和组合环有准确位置；显式/default/多 top、多个源中模糊命名和失败不发布部分 design 均有回归 |

`firrtl-widths` 使用独立的数学预期与小型 GRH 位向量解释器；
`firrtl-aggregate` 使用独立的行主序数组预期，覆盖初始图、JSON 重载图和
simplify 后图。生成模型的 driver 直接计算预期，不复用待测 lowering。

## 实际命令

全部构建、测试均通过项目 Makefile。下表日志位于
`ptmp/firrtl-ingest/F04/`，新 fixture 位于
`wolvrix/tests/ingest/data/firrtl/comb/`，CMake 和模型工作产物位于
`wolvrix/build/artifacts/`。

| 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test_firrtl_comb test_firrtl_aggregate test_firrtl_widths test_wolvrix` | 三项新回归、三份模型编译/运行、完整 72/72 CTest 通过 | `final-checks.log` |
| `make test_wolvrix test_array_create test_transform_shape_mapping test_grhsim_cpu_st_cpp GRHSIM_CPU_ST_CPP_JOBS=8` | CTest 72/72、array/create verify 2/2、shape 3/3、CPU 生成 CTest 1/1 通过；批量模型中两个 packed-array-constants 用例因工作目录被并行 CTest 重建而链接失败，其余用例完成 | `regression.log` |
| `make run_grhsim_cpu_st_cpp GRHSIM_CPU_ST_CPP_JOBS=2 GRHSIM_CPU_ST_CPP_CASES='packed-array-constants-b16 packed-array-constants-b1024'` | 两个受目录重建影响的用例单独编译、链接、运行通过，命令退出码 0 | `cpu-retry.log` |
| `make test_firrtl_widths` | 最后补充的有界循环宽度和求解资源上限回归通过；随后完整 72/72 再次通过 | `width-solver.log`、`final-checks.log` |
| `make verify_firrtl_inputs test_firrtl_parser_inputs` | 冻结输入身份一致；香山 10,008 个 module body 重新通过；2146 份 SV 文件清单一致；输入门禁 4/4 通过 | `parser-inputs.log` |

上述命令带 `WOLF_ENV_SOURCED=1`，F04 构建使用本阶段 `tmp/`、`ccache/`
及 `CMAKE_BUILD_PARALLEL_LEVEL=8`；复用目标的临时目录沿用项目 Makefile。
完整 CTest 会重新生成模型；其产物在 `make test_firrtl_comb` 中已经实际编译
执行，之后的 CTest 重新生成不构成额外性能样本。
既有 CPU 批量运行的首次失败来自验证任务重叠：完整 CTest 删除并重建了
正在使用的生成目录，两个大型 driver 在链接时无法创建输出文件。已单独
重跑这两个用例，不把首次批量命令记为退出码 0。后续验证不得让生成用例
和消费其产物的编译同时使用同一目录。

## 阶段边界

寄存器/状态读写属于 F05，memory、effects、layers、probes、properties 和
annotations 属于 F06，实例及混合 FIRRTL/SV 链接/Python API 属于 F07。
本阶段对选中模块里的这些行为返回带阶段的未支持错误。F08 的完整 node
表达式判等/合并、F09 nonsink 消费未提前宣称完成。

零宽和空 Vector 的签名保留源几何并标记 ABI 待解决，GRH 中消除相应叶子；
未将其作为已经可绑定的跨语言端口。数组动态写的组合 mask 合并不代替
F05 的寄存器索引端口和旧状态采样规则。

F03 原有顶层 fixture 和冻结 manifest 未修改；新 fixture 放在独立子目录。
香山的本次复验是语法与输入身份验收，不能解释为香山 FIRRTL 仿真正确性
或性能提升。整机对照仍依赖 F00 其余项及后续阶段。
