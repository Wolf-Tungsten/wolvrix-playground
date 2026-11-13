# TNO0050：宽局部 concat 与归约融合

日期：2026-11-11（America/Los_Angeles，实验启动日）。承接 [TNO0048](./TNO0048_part18_remaining_hotspots_20261111.md) 的宽 concat 热点；[TNO0049](./TNO0049_part18_dispatch_guard_control_20261111.md) 的调用前检查不叠加。

## 实现范围

为 GrhSIM C++ emitter 增加 `wide_concat_reduction=1`，环境变量为 `WOLVRIX_GRHSIM_WIDE_CONCAT_REDUCTION=1`。沿用已有 `scalar_concat_reduction=1` 的归约证明，将结果宽度限制从不超过 64 位扩展到宽局部 concat。每个输入字段仍必须是 1–64 位非事件 logic。

OR/NOR 对每个字段按实际位宽截断，然后求 OR；AND/NAND 求每个字段缺失的 bit，再聚合为一个 Boolean。每个消费者保留原极性。64 位字段使用全一掩码，不产生移位 64 的未定义行为。例如 86 个单 bit 条件只被 OR 使用时，直接在 concat 位置计算 OR 谓词，不再构造两字 Words 后归约。

安全条件与现有规则共用：

- concat 为局部、无活动跟踪的结果，不能是 input/output/inout 或持久存储；
- 所有使用者必须在同一 compute 范围内，且严格位于 concat 之后；
- 使用者只能属于 AND/NAND 或 OR/NOR 中的一个类别；
- 数值用途、混合类别、parity、跨范围使用、事件和显式副作用继续使用原 lowering；
- 在原 concat 位置生成 Boolean 快照，不将输入读取推迟到消费者，不改动变化传播、流水状态、调度或模型布局。

原标量 concat 的便宜内联路径继续保留；宽结果不调用标量 concat 表达式构造器，避免为原来超过 64 位的拼接生成非法 shift。静态 execution-plan 记录 `wide.concat_reduction` 与 `wide.concat_reduced_consumer`，不继续将已消除的数组拼接/归约计为宽 helper 工作。

规则为通用 emitter 变换，不匹配 XiangShan 层级名、opcode 或特定分区。初次性能实验显式打开新开关；当前已有共享 Boolean 掩码规则继续启用，其他配置相同。

## Focused 验证

新增 `emit-grhsim-cpp-wide-concat-reduction`，直接入口为 `WOLVRIX_TEST_WIDE_CONCAT_REDUCTION=1`。

8 类形状 × 8 类用途覆盖 65、86、110、111、638 位 Boolean concat、重复字段、混合 63/64/2 位字段、两个 64 位字段，以及 65 位输入字段的回退。验证 AND/NAND、OR/NOR、混合用途、数值输出、XOR/XNOR、跨范围、tracked fanout 和显式副作用。

使用独立逐 bit 参考逻辑，包含全零、全一、walking-one/zero、非规范高位和固定随机种子，12,000 组输入、每组重复 eval 两次。Clang 23.1.2 的 O0/O3、ASan/UBSan 全部通过。结构门确认只接受预期 14 个 concat；default/off、环境打开、attribute 覆盖环境和 parent-off 隔离均通过。

原有 scalar concat reduction 与共享输入掩码 focused 回归均通过，native replay/test 工具构建通过。完整 emitter 回归与完整图验收继续独立记录，不把 focused 结果当作完整 RVV 工作负载验证。

## 冻结图实验

基线为 TNO0043 已优化 after seed7，binary SHA256：

```text
e27e6fd69c65dc0412bb893afab3f6841222533ec64058c3656a5e13479a2aac
```

重新发射同一 partitioned GRH 与 assignment，仅开启宽归约；比较全部 source/header，只编译变化对象，复用其余模型及 harness。使用同一 Clang 23/O3/native 和对象对齐。生成、功能和性能结果后续追加独立记录。

- [实现](../../wolvrix/lib/emit/grhsim_cpp.cpp)、[focused 测试](../../wolvrix/tests/emit/test_emit_grhsim_cpp.cpp)、[功能文档](../../wolvrix/docs/emit/grhsim-wide-concat-reductions.md)
- [实验起始源码身份](../../build/artifacts/repcut-wide-reduction-20261111/start.json)、[focused 检查](../../build/artifacts/repcut-wide-reduction-20261111/checks.json)
- [冻结图生成脚本](../../build/artifacts/repcut-wide-reduction-20261111/build.py)、[独立构建目录](../../build/xs/repcut-wide-reduction-20261111/generated/)
