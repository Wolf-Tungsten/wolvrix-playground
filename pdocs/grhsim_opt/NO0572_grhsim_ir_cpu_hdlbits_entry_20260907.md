# NO0572 GrhSIM IR CPU HDLBits Entry

- 日期：2026-09-07
- 范围：原计划 M5.1 的全量 HDLBits 功能 gate，不替代 XiangShan 50k。

## Workflow

新增根 Makefile 入口 `run_hdlbits_grhsim_ir` / `run_all_hdlbits_grhsim_ir_tests`，分配
项目 ptmp 内的新目录并委托已有 GrhTB 构建/运行路径。脚本新增 `--backend ir`，
默认仍为 legacy；两路线共享既有 HDLBits GRH 预处理，IR 使用 XiangShan 的八个 CPU
pass，保留 flat GRH 和独立 IR JSON。IR 非空输出目录及尚不支持的 waveform/perf
选项明确拒绝，不覆盖旧生成结果。没有改 DUT 或测试判据。

当前 DUT/GrhTB 各有 162 个。001 定向用例已通过，日志 `ptmp/grhsim_ir_hdlbits001.log`。
首次全量入口日志 `ptmp/grhsim_ir_hdlbits_all1.log`，001–015 通过，016 在 lowering
处被 IR 单 producer 校验拒绝，因此不能称为全量通过。

## 016 Detached Values

016 将六个 5-bit 输入拼接并分割为四个 byte 输出。comb-lane-pack 等变换后，四个
输出端口已绑定新的 slice 结果；旧的 w/x/y/z value 仍在 GRH 符号表，但无 def、无
users、无端口绑定。lowering 原先遍历所有 GRH value，产生四个无 producer 的 IR value。

证据：`ptmp/hdlbits-grhsim-ir-QmomwL/grhtb_016/dut_016_flat.grh.json`；复现日志
`ptmp/grhsim_ir_hdlbits016_precheck.log`。修复仅跳过无 def、无 input/output/inout 标记
且 users 为空的脱离图 value，不放宽 IR verifier，不生成虚构零值，也不删除实际操作。

`grhsim-ir-tests` 增加三态验证：孤立旧名跳过，合法 unused input/producer 保留，
无驱动值一旦被 output 或 op operand 引用仍必须拒绝。通过生成 Makefile 的 build/test
目标验证退出 0，日志 `ptmp/grhsim_detached_value_build.log` 和
`ptmp/grhsim_detached_value_test.log`。安装/016 重跑/全量复验继续进行。

## 增量验证

`make py_install` 成功，016 定向重跑退出 0，日志
`ptmp/grhsim_ir_hdlbits016_fixed.log`。第二次全量 001–031 通过，032 被 CPU emitter
笼统的 cpu_ 前缀保留规则拒绝；不是本次 detached-value 修复回退。第二轮日志为
`ptmp/grhsim_ir_hdlbits_all2.log`，端口名问题独立记录于
[NO0573](./NO0573_grhsim_ir_cpu_port_names_20260907.md)。
