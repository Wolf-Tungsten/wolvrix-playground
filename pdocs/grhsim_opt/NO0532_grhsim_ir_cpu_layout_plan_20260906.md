# NO0532 GrhSIM IR CPU data layout plan

日期：2026-09-06

承接 [NO0531 分区门禁](./NO0531_grhsim_ir_cpu_partition_gate_20260906.md)，实现
`cpu.st.layout-data`。完整目标仍为 [CPU 后端计划](../draft/grhsim_ir/grhsim-ir-cpu-backend-multiclock-activity-plan-20260905.md)
及独立新 IR 路线 CoreMark 50k，本阶段不验收 runtime。

## 布局边界

- CPU 类型使用独立 ID/table，不写入语义 I/O/S/value 的类型表。当前固定 64 位指针 ABI。
- I/O/S 分配到 object arena；value 根据最终 supernode 定义/使用关系分为 boundary arena
  或 supernode local frame。所有字节偏移、大小和对齐显式物化，数组递归且检查溢出。
- helper 共享调用者 supernode frame，不能把 helper 内部临时变量当作跨 helper 值的存储。
- DPI result 保守使用 boundary 持久存储，避免未触发调用时丢失旧值；事件 value 也持久保存。
- active word、edge-domain arm 和域内 event-edge slot 各占一个运行态字节；general 域无 arm。
  这些槽不替代语义事件历史 state，不预先决定历史采样时机。
- v1 verifier 重建 canonical layout 比较，检查覆盖、必要的 lifetime boundary 和完整运行态。
  JSON 尾部扩展保持旧六阶段 checkpoint 字节形态不变，mapping 仍不完整。

## 门禁

先做标量宽度/符号/四态、嵌套数组、helper lifetime、DPI、跨 supernode、事件 slot、空图、
负向损坏和溢出测试，再从 NO0531 已验证分区 checkpoint 只运行新布局 pass，检查全图往返。
后续 schedule、emitter、HDLBits/多时钟差分、10k/50k difftest 与性能仍需独立验收。
