# F13：层次展平、GRH 化简与 core 数据搬运优化

建立日期：2026-11-02。

状态：已完成（2026-11-02）。五项实现、代码审查和正确性门禁均通过。以下各节保留实施前的
问题和约束；实际实现与验证记录见文末。本阶段不新增性能测量。

## 目标与范围

减少层次展平和普通 GRH `simplify` 中可避免的分配、深复制与重复查询。
FIRRTL node attributes 的长字符串会放大这些成本，优先修正访问方式和
数据所有权。范围固定为下列五项，按 F13.1 → F13.5 推进。

此前整机试跑的 hier-flatten 为 467.958 s，普通 GRH simplify 首轮为
999.972 s，其中 const-fold 593.627 s、redundant-elim 303.085 s、DCE
103.259 s。完整 40 分钟预算耗尽时仍在普通 GRH simplify。这些既有时长
仅说明瓶颈位置，不代表下列各项的耗时占比，也不据此承诺优化幅度。
历史记录见 [F12](F12-ingest-performance-plan.md)。

| 子项 | 优化 | 状态 |
| --- | --- | --- |
| F13.1 | redundant-elim 只收集校验错误，避免完整 node census | 已完成 |
| F13.2 | CF/DCE 热路径改用借用访问，消除完整 Operation 中间快照 | 已完成 |
| F13.3 | 常量清理的端口绑定和 users 查询改为直接访问 | 已完成 |
| F13.4 | 展平直接构造最终限定的 node attributes | 已完成 |
| F13.5 | Graph::freeze 消耗 builder，移动拥有的 payload | 已完成 |

## F13.1：冗余消除使用仅校验入口

位置：[redundant_elim.cpp](../../wolvrix/lib/transform/redundant_elim.cpp) 的
`RedundantElimPass::run`；[node_attributes.cpp](../../wolvrix/lib/ingest/node_attributes.cpp)
的 `inspect` / `scanAttributes`。

实施前 redundant-elim 调用 `node::inspect(graph)`，只使用返回的 errors，
却构建了整图的 `map<string, NodeRecord>`、成员、roots 和孤立片段清单。

实施：复用 `scanAttributes`，提供只收集校验错误的入口，替换该调用。
保留全部错误及其顺序、文本；现有 `requireValid` 只抛首个错误，不能直接
用它替换原先的多错误诊断。需要完整清单的 inspection 调用继续使用原接口。

## F13.2：化简热路径消除完整 Operation 快照

位置：[const_fold.cpp](../../wolvrix/lib/transform/const_fold.cpp) 的
`eliminateDeadConstants` / `simplifyUnsignedComparisons`；
[dead_code_elim.cpp](../../wolvrix/lib/transform/dead_code_elim.cpp) 的 OpInfo
构造、storage 分类和相关活性遍历；
[grh.cpp](../../wolvrix/lib/core/grh.cpp) 的 `operationFromView` / `operationFromBuilder`。

实施前多处全图循环先调用 `getOperation()`，复制 symbol、operands、results、
全部 attributes 和 SrcLoc，随后才按 kind 筛选。DCE 构造 OpInfo 时还再次
复制 operands/results。

实施：先用 `opKind()` 筛选，再通过 `opOperands/opResults/opAttrs` 等现有
借用接口读取必要字段；完整 Operation 仅在需要稳定拥有数据或生成诊断时
构造。DCE 跨越图修改所需的 OpInfo 邻接副本保留，去掉前置完整快照。
借用数据必须在其失效前使用完毕；`getOperation()` 保持原有拥有语义。

## F13.3：常量清理避免逐端口扫描和 fanout 副本

位置：[const_fold.cpp](../../wolvrix/lib/transform/const_fold.cpp) 的
`isValuePortBound` / `eliminateDeadConstants`；
[grh.cpp](../../wolvrix/lib/core/grh.cpp) 的 `Value::users()`。

实施前每个常量结果都会扫描全部 input/output/inout ports，形成
O(constant results × ports) 查询；`getValue(...).users().empty()` 又为
空检查复制 Value 和完整 use-list。

实施：核对端口标记与现有绑定语义一致后，以 `valueIsInput/Output/Inout`
直接查询，覆盖 inout 的 in/out/oe；users 空检查改用公开的 `valueUsers()`。
相关 alias 输出重绑先按 output 标记筛选，再执行必要的端口更新。
跨 mutation 的 users 遍历保留稳定快照或调整修改顺序。

## F13.4：展平直接克隆最终限定的 node attributes

位置：[hier_flatten.cpp](../../wolvrix/lib/transform/hier_flatten.cpp) 的普通
op clone 路径；[node_attributes.cpp](../../wolvrix/lib/ingest/node_attributes.cpp)
的 `qualify` / `read` / `write`。

实施前 clone 先复制未限定的 node attrs 到目标，随后 qualify 读回拥有数据的
vectors、改写字符串，再 normalize 和写回；write 的 const 引用参数还会
使按值 `setAttr` 再复制最终 vectors。

实施：借用源 node attrs，复用 QualificationContext，直接构造带实例路径的
最终属性并 move 写入目标。保持排序去重、canonical key 校验、root-result
映射、64-association 上限、降级计数及既有诊断语义；覆盖同定义多实例和
嵌套实例，保证身份不碰撞。

## F13.5：core 增加消耗式 freeze

位置：[grh.cpp](../../wolvrix/lib/core/grh.cpp) 的
`GraphBuilder::freeze() const` / `Graph::freeze()`。

实施前 const freeze 深复制 attributes、op/value SrcLoc 等拥有数据的负载；
`Graph::freeze()` 成功后立即销毁旧 builder。

实施：增加 Graph 自用的 consuming freeze 路径，完成必要验证后移动可转移的
payload。保留公共 const freeze 的复制语义、ID 重排与绑定结果、确定性输出
及既有失败契约。实施前明确验证、可能抛异常的分配和所有权转移的边界，
避免失败时留下部分被移动的可变图。

## 正确性与完成记录

五项均保留现有 FIRRTL/SV 功能语义、完整 node annotations、SrcLoc、诊断、
JSON roundtrip 及 pass 默认选项；普通 CSE 继续排除 node 来源属性。

实施时按影响范围通过现有 Make 入口验证：`make test_wolvrix`、
`make test_transform_simplify`、`make test_firrtl_node_attributes test_firrtl_cse_scope`；
涉及 Python/生产 flow 时先经 `make py_install`
刷新安装库，再运行相关 `test_ingest_python` / `test_grhsim_flow`。
仅在现有覆盖不足时补充针对语义、诊断或所有权边界的回归。

本阶段不要求新增 profiling、性能 A/B 或整机计时作为前置步骤和退出门槛。
完成时逐项登记实现提交、代码审查和实际正确性验证结果；未测性能不写成
定量收益。日志及临时产物统一放在 `ptmp/firrtl-ingest/F13/`。

## 实施记录（2026-11-02）

五项实现及回归提交：wolvrix `c134542659e46bc029d5485c82171d2c5304cb7a`
（`perf: reduce GRH transformation and freeze payload copies`）。

| 子项 | 实现与审查结果 | 正确性证据 |
| --- | --- | --- |
| F13.1 | `scanAttributeErrors` 复用原 `scanAttributes`，用空回调跳过 census；redundant-elim 逐条发布完整 errors | 原 inspection 算法与新入口逐条对照，schema + 多 op 三条错误验证文本与顺序 |
| F13.2 | CF 按 kind/span 筛选，仅已接受的 comparison rewrite 持有 Operation；DCE 直接读取 kind、邻接与 storage attr，保留 OpInfo 邻接副本 | const-fold、DCE、simplify 既有语义回归；新增 frozen DCE dead/orphan 清理 |
| F13.3 | port flags 覆盖 input/output/inout 三个分量；users 空检查和只读遍历用 `valueUsers`；alias 先筛 output 标记再收集端口名重绑 | CF/DCE 的 inout in/out/oe 保留，双 output alias 重绑及标记更新 |
| F13.4 | `copyQualified` 借用源属性并复用每实例 context，构造最终 key；write 移动 vectors/root keys；普通 clone 直接接入 | 独立 parse/key 前缀 oracle、root result 1、同定义多实例、嵌套/转义路径、冻结源销毁后 JSON；既有层次测试 |
| F13.5 | Graph 私有 consuming freeze；公共 const freeze 仍复制；映射/符号校验、所有分配和端口排序索引准备都在 commit 前，commit 仅预分配目标中的 noexcept move，返回/接收同样由静态断言保护 | const 快照独立性、稀疏 ID 压紧、长 attrs/SrcLoc、shape/domain、端口/def/users；无效 operand 失败保持 payload、修复重试 |

借用生命周期审查：CF 的 span 仅在只读筛选或提取 ID 时使用，rewrite 前构造
稳定快照；DCE 在首次修改前保存 value IDs，避免 frozen view 在 thaw 后失效；
users 遍历中的 enqueue 只修改本地队列。限定 key 的全部源借用在 target 写入前
消费，支持原地 qualify。RE 的常量输出重命名也先保存端口快照，避免首次
修改释放 frozen view；新增首次 eraseValue/直接 rename 两种回归。独立代码
审查覆盖五项，未发现阻塞问题。

实际 Make 门禁如下，日志相对 `ptmp/firrtl-ingest/F13/`。使用现有工具环境
（`WOLF_ENV_SOURCED=1`、workspace clang 路径）、`.venv/bin/python` 和 4 路
构建；`TMPDIR`、`CCACHE_DIR`、`PIP_CACHE_DIR` 均指向本阶段 ptmp 目录。

| 实际 Make 命令 | 结果 | 日志 |
| --- | --- | --- |
| `make test_wolvrix` | 最终代码 81/81 CTest 通过（含 GRH、const-fold、DCE、redundant-elim、hier-flatten、node/JSON 新旧回归） | `test_wolvrix_final.log` |
| `make py_install PYTHON=$PWD/.venv/bin/python` | 最终代码重新安装成功 | `py_install_final.log` |
| `make test_transform_simplify test_firrtl_node_attributes test_firrtl_cse_scope test_ingest_python test_grhsim_flow SKIP_PY_INSTALL=1 PYTHON=$PWD/.venv/bin/python FIRRTL_NODE_TEST_WORK=$PWD/ptmp/firrtl-ingest/F13/node INGEST_MIXED_TEST_WORK=$PWD/ptmp/firrtl-ingest/F13/python GRHSIM_FLOW_TEST_WORK=$PWD/ptmp/firrtl-ingest/F13/grhsim-flow` | 三个定向 CTest、9/9 ingest Python、5/5 flow 单测和 flow 生成模型全部编译执行通过；annotations on/off 等八组 trace 比较一致 | `gates_final.log` |

所有 Make 进程均成功返回 0；`git diff --check` 通过。原 Make 门禁内部的
共享 build/CTest 临时目录仍沿用其既有 `ptmp/` 路径，测试产物仍在
`wolvrix/build/artifacts/`，未提交生成模型。

未新增 profiling、性能 A/B 或整机计时；本记录不宣称定量加速或 F10 整机完成。
