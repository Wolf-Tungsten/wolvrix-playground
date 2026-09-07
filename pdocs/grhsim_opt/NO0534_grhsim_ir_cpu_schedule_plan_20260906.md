# NO0534 GrhSIM IR CPU schedule plan

日期：2026-09-06

承接 [NO0533 布局门禁](./NO0533_grhsim_ir_cpu_layout_gate_20260906.md)，实现第八个 pass
`cpu.st.build-schedule`。完整目标仍为新 IR 路线 XiangShan CoreMark 50k。

## 实现边界

- 单 NUMA/core、函数级 tasks，compute 后按域执行 commit；空 waitsFor。
- 三张稀疏扇出表，activate 指向 compute supernode，arm 指向 edge domain；稳定排序去重。
- E 按当前 overview 的输出/事件状态反向闭包推导，跨所有状态写口继续传播；事件历史本身
  影响边沿判定，也在 E 中。历史 next 值只依赖 event，不误引入该写口的数据条件闭包。
- commitStateFanout 的 key 集合严格等于 E；无 reader 的闭包状态仍保留空 targets 条目。
- 额外 roundSeeds 保守覆盖 system function/task/DPI 以及 E 外的 state readers，使无输入变化
  的新 G 应用仍能更新这些计算，不把 E 外状态错误加入静止投影。
- inputFanout 显式激活 input.read 生产者，输入 shadow 的类型、偏移及 arena 字节数物化。
- 完成 schedule 后 mapping.complete 表示映射数据齐全，不表示 emitter 或 runtime 已验收。

## 必要的语义修正

草案的冻结 history 不符合当前 core 方言“每次应用 G 采样”的定义，后续 runtime 按后者实现。
派生事件值的任意变化都必须 arm，包括 posedge 域的下降沿，否则不采样下降沿就会丢失下次
上升沿。数据 enable/mask 变化不单独重 arm 边沿域；历史变化重 arm 所属域，在下一 G 应用
精判，不能靠全域重 arm 冻结的历史导致一条输入边沿被重复执行。

## 验证

正负向测试覆盖跨 supernode/同 word 扇出、重复 input.read、混合输入/派生时钟、general 域、
无扇出输入、E 跨状态/多写口依赖、闭包外状态、系统调用源、完整 JSON、损坏 targets/缺边。
随后从 NO0533 layout checkpoint 运行全图 schedule 与往返，再验证真实 Make 入口。
HDLBits、多时钟 Verilator 差分、emitter 和 10k/50k difftest/perf 仍需后续运行态门禁。
