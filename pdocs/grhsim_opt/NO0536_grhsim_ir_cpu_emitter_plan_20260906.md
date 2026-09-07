# NO0536 GrhSIM IR CPU emitter implementation plan

日期：2026-09-06

承接 [NO0535 调度门禁](./NO0535_grhsim_ir_cpu_schedule_gate_20260906.md)，开始
`cpu.st.emit-cpp` 和生产运行态，完整目标仍为独立路线 XiangShan CoreMark 50k。

## 实现顺序

- 将 legacy 的独立运行库发射代码机械抽成共享函数，保留所有原选项及输出字节，不复用 legacy
  Graph、activity schedule 或 model builder。先跑两项 legacy emitter 回归。
- 新 emit pass 只读 CPU mapping，直接消费已物化的布局、word/helper/function、fanout 与 E。
- 生成明确的 object/boundary/local 存储，分区函数与 standalone Makefile；状态暂存按 touched
  state 保存，轮末比较最终 E 再发布，不全图拷贝每轮状态，也不冻结历史到 eval 结束。
- 先验证实际编译的两态逻辑/寄存器/latch/多时钟基本链路，再扩展宽值、memory、DPI/system
  calls、初始化和 XiangShan 驱动接口。当前不支持的操作必须在产生输出文件前诊断拒绝。
- 不把首批 op 子集当作最终实现；HDLBits 全量、所有 XiangShan 实际 op、10k/50k difftest 和
  性能 parity 仍是完整验收要求，后续逐篇记录，不更换成 legacy 路线或解释器冒充新 emitter。

## 运行态约束

compute 与 commit 从同一轮初状态求值，history 也进入暂存；轮末提交全部状态后才继续。
输入差分激活 input.read 及其目标，派生事件任意变化 arm；当前和下一轮 arm 分离消费。
helper 共享 supernode frame；活动位执行即消费，同一 word 后序目标当轮生效。
复制 Init 的表示不等于改变 Init 的语义；不支持的 Init 步骤不能静默变成零初始化。
