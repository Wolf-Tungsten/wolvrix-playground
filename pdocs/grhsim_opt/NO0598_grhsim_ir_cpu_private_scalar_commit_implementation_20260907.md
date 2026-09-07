# NO0598 GrhSIM IR CPU Private Scalar Commit Implementation

- 日期：2026-09-07
- 前置：[NO0597](./NO0597_grhsim_ir_cpu_private_scalar_commit_design_20260907.md)

## Implemented

`cpu_emit.cpp` 按完整 refs 计数与唯一 writer 资格选择 1..64-bit、2-state 标量。
符合资格时在原 guard/enable 下计算相同 masked/normalized 值，变化时原地写回，
并调用小型 out-of-line helper 更新原 target 表对应的 active bits/next-arms。
延续条件只累积 E 成员的最终变化，原 publish 与 pending 结果合并并清除该布尔量。
init 也清除。没有新增运行时调度条件或修改 mapping/IR。

多写者、任何 history/其他 refs、memory 和宽值继续原 shadow/pending 路径。
history batching 原样保留。DPI 保持 compute + 可选 event + 真实调用，未调整
ingest 或调用策略。公开模型头文件新增私有归约状态/helper，后续完整模型使用独立
gate58 构建，不能复用 gate57 的旧 ABI 对象混链。

## Focused and Existing Tests

通过 `make test_grhsim_cpu_emit WOLF_ENV_SOURCED=1` 完整回归，退出 0，27.84 秒。

- `cpu_chain` 明确只有前五个唯一写者使用 direct commit，两个多写者回退；
  与 Verilator 4136 样本继续通过，覆盖 masked 合并、写回原值、双时钟/派生事件/latch。
- history fixture 明确只有 16 个普通寄存器使用 direct commit，所有历史及被普通
  写口写入的 history 不入选；原历史批量采样 4624 样本通过。
- 新 `cpu_private_commit` fixture 没有 E 状态，三个非投影状态由实际 void DPI
  观察。独立 JSON fresh-load 后以 O0 ASan/UBSan、8 MiB 栈运行，4612 个 eval
  恰好 4612 次调用，每次观察轮初旧值；4 次 init，bool/signed5/unsigned64、
  零/部分/全 mask、enable 与重复 eval 全部通过。
- 原 scalar 4196、wide 3072、wide-state 2048、CDC 10756、双 RAM 9731 样本
  及 startup/init、384 样本的 DPI/system 回归均通过。
- 新 helper/member 的端口命名冲突反例被正确拒绝。

日志 `ptmp/grhsim_cpu_private_commit_test.log`，完整 CTest 输出保存在
`ptmp/grhsim_cpu_private_commit_test_details.log`。LeakSanitizer 保持既有禁用设置，
不宣称新的泄漏覆盖。测试后的局部整理只移除了 fixture 初始化时的一次多余赋值。

## Pending Measurement

HDLBits 全量、gate58 的实际覆盖、完整 O3 构建和运行收益仍待验证。当前 gate57
仍是已通过 IR 50k 的基线；不能把其 50k 证据转移给新的 emitter。下一步按既有
Makefile 安装/生成独立模型，先看真实运行收益，再推进完整功能和性能门禁。
