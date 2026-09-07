# NO0589 GrhSIM IR CPU Gate57 Generation

- 日期：2026-09-07
- 前置：[NO0588](./NO0588_grhsim_ir_cpu_history_batch_implementation_20260907.md)

## Generation Result

独立 gate57 的既有 Makefile 生成流程已退出 0，耗时 86608 ms。完整 CPU mapping、
C++ 发射、JSON 存储、fresh-session 加载和稳定 round-trip 均完成。

- 日志：`ptmp/grhsim_gate57_generation.log`。
- C++：`ptmp/xs_emit_make_gate57`。
- IR：`ptmp/xs_ir_gate57.json`。
- Round-trip：`ptmp/xs_ir_gate57_roundtrip.json`。

`cmp -s` 确认 gate55/gate57 的完整 IR JSON 逐字节相同，两个模型的公开
`grhsim_SimTop.hpp` 也逐字节相同。此次变化只发生在 emitter 生成函数体，
没有更改模型语义、mapping、公开 ABI 或 DPI 的 compute + 可选 event 策略。

## Actual Coverage

对生成 task 源码的 `cpu_history_batch states=` 标记求和得到：

| 项目 | 数值 |
| --- | ---: |
| 批量覆盖的 history state | 391659 |
| 批次数 | 3240 |
| 最大批次字节数 | 8030 |

该统计来自实际生成代码，不是估算。Python 生成入口尚未输出 emitter 的 info
诊断，因此这里不宣称掌握全部候选或回退统计。批次继续受同函数、私有性、连续布局、
相同发布目标和同类型约束；各 history 的旧值和初始化保持独立。

## Pending Gates

记录时 gate57 全模型 O3 构建与 history batching 的 HDLBits 全量回归仍在运行，
日志分别为 `ptmp/grhsim_gate57_full_o3_build.log` 和
`ptmp/grhsim_ir_hdlbits_history_batch.log`。不重复启动它们。

生成成功和批量覆盖量不代表实际运行正确或性能提高。gate57 实测、IR 50k 和与
legacy 相同配置的 50k 性能门禁仍未完成。
