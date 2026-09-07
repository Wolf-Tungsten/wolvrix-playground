# NO0581 GrhSIM IR CPU Extended Multiclock Gate

- 日期：2026-09-07
- 前置：[NO0580](./NO0580_grhsim_ir_cpu_unchanged_state_staging_20260907.md)

## Independent DUTs

在已有 `cpu_chain` 之外新增两个独立 DUT，并接入既有 CPU emitter 测试入口：

1. `cpu_cdc`：两个 8-bit 计数器分别在 posedge clock_a、negedge clock_b 更新，
   两个方向各有两级跨时钟采样。共享异步 reset。测试包含 1024 次连续双域同时
   触发、计数回绕、A/B 不同频率、暂停/重复 eval、无时钟边沿的异步 reset。
2. `cpu_dual_ram`：两个 posedge 域向 8x16-bit memory 独立 masked write，
   每个域同步捕获本端地址的旧值，另有组合读 probe。测试零/全/随机 mask、双域
   同时触发、慢域空闲、同边沿读旧写新、异步 reset 和全地址扫描。

双 RAM 用例显式排除同时同地址双写，不借助 Verilator 的任意冲突排序作为语义标准。
两个 DUT 都在每一步同时检查 CPU 模型、Verilator RTL 和独立 C++ 记分板，
而不是只比较最终输出。IR fixture 手工构造以隔离 CPU backend；本测试不宣称
ingest 等价证明或真实硬件 CDC 亚稳态建模。

## Executed Gate

```sh
make --no-print-directory test_grhsim_cpu_emit WOLF_ENV_SOURCED=1 \
  > ptmp/grhsim_cpu_multiclock_extended_test.log 2>&1
```

退出 0，CTest 28.16 秒。详细输出保存于
`ptmp/grhsim_cpu_multiclock_extended_test_details.log`。

| DUT | Samples | Additional Observed Coverage |
| --- | --- | --- |
| cpu_chain | 4136 | derived clock、latch、mask merge、同拍写回原值 |
| cpu_cdc | 10756 | 1182 次双域触发，20 次不伴随域边沿的异步 reset |
| cpu_dual_ram | 9731 | 293 次双域触发，424 次内容变化写，15 次独立异步 reset |

三个多时钟 DUT 的 Verilator 对照均使用既有 UBSan 编译配置。原 scalar 4196、wide
3072、wide-state 2048 样本以及 startup/init/calls 回归也通过，没有删减旧用例。

本阶段补齐计划要求的 2-3 个独立多时钟 DUT 覆盖，但不单独宣布 M5.2 整体完成：
XiangShan 完整回归与 50k 性能仍须执行。运行本测试时 gate56 的全模型 O3 构建在
并行进行，因此测试耗时不用于任何生产性能比较。

## Fresh-Load Extension

随后为两个新 DUT 补充实际域数量断言（CDC 两个、双 RAM 四个 canonical event set），
并先序列化完整 IR/mapping、独立加载，再发射和运行。四个 RAM 域分别区分两个
纯时钟 memory 写和两个含异步 reset 的读捕获，不表示四个物理时钟。

同一 Makefile 测试入口再次退出 0，CTest 25.30 秒，所有上述样本计数与对照结果不变。
日志为 `ptmp/grhsim_cpu_multiclock_fresh_load_test.log`，详细结果保存于
`ptmp/grhsim_cpu_multiclock_fresh_load_test_details.log`。此扩展确认运行所需的
mapping 信息来自持久化模型，而不是创建 fixture 的临时会话状态。
