# NO0576 GrhSIM IR CPU HDLBits Full Gate

- 日期：2026-09-07
- 前置：[NO0575](./NO0575_grhsim_ir_cpu_hdlbits_library_alias_20260907.md)

## Functional Result

通过新增根 Makefile 入口，复用现有 162 个 DUT/GrhTB，不修改 RTL 或测试判据：

```sh
make --no-print-directory run_all_hdlbits_grhsim_ir_tests \
  SKIP_PY_INSTALL=1 WOLF_ENV_SOURCED=1 PYTHON="$PWD/.venv/bin/python" \
  TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" > ptmp/grhsim_ir_hdlbits_all4.log 2>&1
```

完整命令退出 0，日志包含 162 个 `[RUN] DUT=` 运行记录，覆盖 001–162；末尾
`dut_162 passed all prediction and training scenarios`。各 DUT 均先执行真实 GRH→IR
lowering、八阶段 CPU mapping、O3 生成模型编译和现有 GrhTB 运行，失败即中止，没有
跳过用例。全部产物位于 `ptmp/hdlbits-grhsim-ir-lMsBxv`，含每个 DUT 的 flat GRH、
独立 IR checkpoint、生成 Makefile/C++/archive 和测试可执行文件。

此前 016 的 detached value、032 的端口前缀和 119 的参数化库别名问题均已在同一
全量运行中越过。119 的参数化异步复位用例通过，不是仅完成链接。

此 gate 是既有 GrhTB 的断言验证，不是 162 个 DUT 的全量 Verilator 波形/覆盖率证明。
CPU emitter 单元中的四组 Verilator difftest 证据仍分别保留在 NO0573 对应日志。

## Event-Domain Audit

用 jq 结构化解析全部 162 份 IR JSON 和实际 CPU partition 编码（核对 JSON writer
及 CpuPartitionKind/CpuEventSource 枚举），输出
`ptmp/grhsim_ir_hdlbits_domains.json`；解析程序 `ptmp/grhsim_hdlbits_domains.jq`。

- 84 个模型没有 commit 事件域。
- 合计 98 个域：75 input、5 derived、18 general。
- 边沿项共 96 个：93 posedge、3 negedge；同域允许多个事件，不能把项数当域数。
- 098 同一 clk 的 posedge/negedge 分成两个域，与两段 always 一致。
- 111 的 KEY[0] 经位选生成一个事件 value；114 的四个子实例分别保留 KEY[0] 位选
  value，因此归成四个 derived 域。这不表示 RTL 有四个独立物理时钟，而是当前按
  canonical ValueId 键分组的保守结果。
- 087 的条件赋值和 144 的不完整 case 都推断 latch，进入 general；其余 general
  条目逐模型保存在报告，未将它们误计为时钟边沿域。

## Legacy Check and Remaining Scope

共享脚本的默认 legacy 001 定向运行通过（`ptmp/grhsim_legacy_hdlbits001.log`）。
另外独立尝试 legacy 119 时，生成/库别名/链接完成，但在现有 GrhTB 的
`async reset immediate` 断言失败（`ptmp/grhsim_legacy_hdlbits119.log`）。该失败
没有被忽略或记为 baseline 通过，本阶段不修改 legacy 调度以迎合 IR 测试。

本结果闭合计划中的 HDLBits 全量 GrhTB 功能门禁，但尚不表示整个 M5.1/M5.2 或目标
完成：XiangShan 10k/50k NEMU 对照、50k 不差于 legacy 5% 的性能门禁、指定多时钟
DUT 扩展及性能归因报告仍需完成。gate55 全模型 O3 编译正在继续。
