# TNO0429 译码表优化重新启用与顺序探索起点

本轮把 `decode-table` 生成模式的两个部分固定到同一构建配置：香山源码中的译码表（包括 CSR 权限表）继续通过 `utility.decoder`／`utility.DecodeLogic` 接入，Wolvrix 后端对可证明恒定输出的 `kDecodeTable` 默认执行恒定折叠。

恒定折叠不再依赖只为调查准备的环境变量。单线程生成器在 `sim_primitives=decode-table` 且未指定消融选项时写入 `WOLVRIX_FOLD_CONSTANT_DECODE=1`；`constant_decode_fold=False` 可用于 CSR-only 或其它历史对照。旧的 `WOLVRIX_RESEARCH_FOLD_CONSTANT_DECODE` 仍作为兼容回退，避免冻结诊断 fixture 失效。

本轮只完成配置和提交前验证：相关 C++ 目标成功重建，`emit-grhsim-decode-table` 与 `transform-activity-schedule` 测试通过，译码表和单线程 runner 的 Python 测试通过。没有把新的整机 walltime 结果写入本记录。

提交后将从已保存的 post-reg-to-mem 快照继续研究 source order。已有 C/E 合法顺序干预说明：source 遍历顺序会改变共享归属、节点数量和调度函数形态，但一次 E-order 交叉变体的 walltime 区间跨零。因此下一阶段先做固定快照上的多种顺序策略结构扫描，再选择少量结构差异明确的变体做 CPU96 单线程测量。
