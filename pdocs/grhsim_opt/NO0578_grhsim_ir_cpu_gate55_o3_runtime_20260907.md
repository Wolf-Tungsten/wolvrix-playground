# NO0578 GrhSIM IR CPU Gate55 O3 Runtime

- 日期：2026-09-07
- 前置：[NO0577](./NO0577_grhsim_ir_cpu_gate55_full_o3_build_20260907.md)

## Actual Runtime

使用已完成全模型 O3 构建的 gate55，默认 8192 KiB 栈，经既有 Makefile 运行：

```sh
make --no-print-directory run_xs_wolf_grhsim_ir_emu WOLF_ENV_SOURCED=1 \
  XS_SIM_MAX_CYCLE=1000 XS_WAVEFORM=0 XS_WAVEFORM_PATH= \
  XS_LOG_DIR="$PWD/ptmp" XS_PROGRESS_EVERY_CYCLES=100 \
  RUN_ID=20260907_gate55_o3_1000 TMPDIR="$PWD/ptmp/cpu_emit_test_tmp" \
  > ptmp/grhsim_gate55_o3_1000.log 2>&1
```

进程已终态确认退出 0。日志为 `ptmp/grhsim_gate55_o3_1000.log` 和
`ptmp/xs_wolf_grhsim_20260907_gate55_o3_1000.log`。
RAM、CoreMark image、NEMU 初始化完成；首次提交后 difftest 已启用。

| Host/Model Cycles | Instructions | Commit PC | Host ms |
| --- | --- | --- | --- |
| 100 | 0 | 0x0 | 8458 |
| 500 | 0 | 0x0 | 30417 |
| 600 | 1 | 0x10000000 | 35945 |
| 700 | 3 | 0x10000008 | 41466 |
| 1000 | 3 | 0x10000008 | 57897 |

终态为 `EXCEEDING CYCLE/INSTR LIMIT`，`instrCnt=3`、`cycleCnt=996`、
guest cycles 1001，host time 57958 ms。该有限窗口没有报告断言或 NEMU 不一致，
不是 CoreMark 程序完成。十个采样点的指令数及 PC 与
[NO0568](./NO0568_grhsim_ir_cpu_first_commit_20260907.md) 的 legacy 启动段记录一致。

## Performance Boundary

O3 后总耗时约 58 秒，稳定段每 100 cycles 仍约 5.5 秒。
NO0568 中已有 legacy 优化二进制的同长度启动段为 734 ms；该历史对照足以显示明显
差距，但不是本计划要求的配套配置、50k 性能门禁，不报告性能对齐。

只读检查发现以下待测候选，尚无采样 profile 证明其耗时占比：

- `cpu_emit.cpp` 的 `memWrite` 向 `cpu_stage_bytes` 传整个数组大小，首次触碰时
  整块复制到 shadow；`cpu_publish` 再整块比较，并在变化时整块复制回对象。
  因而单行写也可能产生与 memory 总尺寸相关的数据搬运。legacy 使用写地址、
  data/mask 槽和行级提交路径，应以其数据搬运策略作为后续实现参考。
- 部分宽逻辑/移位/加减输出使用 out-buffer 后直接激活 fanout，没有先判定结果变化；
  与有变化比较的 scalar/concat 路径不同，可能扩大实际执行量。

这两项是源码形态证据，不是已确认的性能根因。本次没有据此修改运行实现、
启动新构建或发起耗时更长的仿真。后续应先量化实际执行与数据搬运成本，再选定修复。

## Preserved Policy and Remaining Gates

按用户讨论结论保持 DPI 现状：compute 分类、可选 event metadata、真实外部调用，
不删除无返回值调用，不在 ingest 统一抹除 event，也不按有无返回值重分 phase。
helper 的任何后续优化仍须先参考 legacy，构建/测试必须使用已有 Makefile 路径，
日志和临时输出只留在项目内 `ptmp/`。

已有 IR HDLBits 162/162 GrhTB 通过见
[NO0576](./NO0576_grhsim_ir_cpu_hdlbits_full_gate_20260907.md)。
XiangShan 10k/50k NEMU 对照、指定多时钟 DUT 扩展及 50k 不差于 legacy 5% 的
性能验收仍未完成。本次 1k 启动段不替代这些门禁。
